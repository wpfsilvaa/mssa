from dataclasses import dataclass, field, replace
from math import isfinite, ulp
from random import Random

from mssa.agents.model import Agent
from mssa.communications.model import (
    CommunicationLink,
    NetworkEvent,
    NetworkMetrics,
    ObservationBatch,
    PendingMessage,
)
from mssa.communications.runtime import CommunicationSystem
from mssa.environment.model import Environment
from mssa.missions.observation import ObservationMission
from mssa.perception.model import AgentContext
from mssa.policies.model import PolicySpec, PolicyState
from mssa.sensors.runtime import SensingSystem, SensorMount
from mssa.simulation.dynamics import Dynamics, KinematicDynamics
from mssa.simulation.state import AgentState, WorldState


@dataclass
class Simulation:
    environment: Environment
    agents: list[Agent] = field(default_factory=list)
    seed: int = 0
    dynamics: Dynamics = field(default_factory=KinematicDynamics)
    sensor_mounts: tuple[SensorMount, ...] = ()
    mission: ObservationMission | None = None
    communication_links: tuple[CommunicationLink, ...] = ()
    policies: dict[str, PolicySpec] = field(default_factory=dict)
    tick: int = field(default=0, init=False)
    _rng: Random = field(init=False, repr=False)
    _sensing: SensingSystem = field(init=False, repr=False)
    _communications: CommunicationSystem = field(init=False, repr=False)
    _policy_states: dict[str, PolicyState] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = Random(self.seed)
        self._validate_world()
        self._sensing = SensingSystem(self.sensor_mounts, self.seed, self.environment.time)
        self._communications = CommunicationSystem(self.communication_links, self.seed)
        self._policy_states = {agent_id: PolicyState() for agent_id in self.policies}

    def _validate_world(self) -> None:
        if any(
            not isfinite(value) or value <= 0
            for value in (self.environment.width, self.environment.height)
        ):
            raise ValueError("environment dimensions must be finite and positive")
        if not isfinite(self.environment.time) or self.environment.time < 0:
            raise ValueError("environment time must be finite and nonnegative")
        ids = [agent.agent_id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent IDs must be unique")
        for agent in self.agents:
            self._validate_agent(agent)
        if not set(self.policies) <= set(ids):
            raise ValueError("policy references an unknown agent")
        for link in self.communication_links:
            if link.sender_id not in ids or link.recipient_id not in ids:
                raise ValueError("communication link references unknown agent IDs")
        owners = {mount.agent_id for mount in self.sensor_mounts}
        if not owners <= set(ids):
            raise ValueError("sensor references an unknown agent")
        if self.mission is not None:
            if not set(self.mission.observer_ids) <= owners:
                raise ValueError("each mission observer must have a sensor")
            if not set(self.mission.target_ids) <= set(ids):
                raise ValueError("mission references an unknown target")

    @property
    def total_scans(self) -> int:
        return self._sensing.total_scans

    @property
    def total_detections(self) -> int:
        return self._sensing.total_detections

    @property
    def network_metrics(self) -> NetworkMetrics:
        return self._communications.metrics

    @property
    def policy_states(self) -> dict[str, PolicyState]:
        return dict(self._policy_states)

    @property
    def network_events(self) -> tuple[NetworkEvent, ...]:
        return self._communications.events

    @property
    def pending_messages(self) -> tuple[PendingMessage, ...]:
        return self._communications.pending

    def context(self, agent_id: str) -> AgentContext:
        """Return only an agent's own state and its most recent sensor scans."""
        for context in self.contexts():
            if context.own_state.agent_id == agent_id:
                return context
        raise ValueError(f"unknown agent: {agent_id}")

    def contexts(self) -> tuple[AgentContext, ...]:
        """Analyst-facing collection; each policy must receive only its own context."""
        return tuple(
            AgentContext(
                agent,
                self.environment.time,
                self._sensing.observations_for(agent.agent_id),
                self._communications.messages_for(agent.agent_id, self.environment.time),
            )
            for agent in self.snapshot().agents
        )

    @staticmethod
    def _validate_agent(agent: Agent | AgentState) -> None:
        if not isinstance(agent.agent_id, str) or not agent.agent_id.strip():
            raise ValueError("agent ID must not be empty")
        if not all(isfinite(v) for v in (agent.x, agent.y, agent.speed, agent.heading)):
            raise ValueError("agent state must be finite")
        if agent.speed < 0:
            raise ValueError("agent speed must be nonnegative")
        if agent.affiliation not in {"friendly", "hostile", "neutral"}:
            raise ValueError("unsupported agent affiliation")

    def snapshot(self) -> WorldState:
        return WorldState(
            time=self.environment.time,
            tick=self.tick,
            width=self.environment.width,
            height=self.environment.height,
            agents=tuple(
                AgentState(a.agent_id, a.x, a.y, a.speed, a.heading, a.affiliation)
                for a in self.agents
            ),
        )

    def step(self, dt: float) -> None:
        if not isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and greater than zero")
        next_time = self.environment.time + dt
        if not isfinite(next_time) or next_time <= self.environment.time:
            raise ValueError("dt must advance the clock to a finite time")
        self._validate_world()
        world = self.snapshot()
        rng_state = self._rng.getstate()
        try:
            sensor_updates = self._sensing.prepare(world)
            network_frame = self._communications.prepare(
                world,
                tuple(
                    ObservationBatch(
                        update.key[0],
                        update.key[1],
                        tuple(detection.observation for detection in update.detections),
                    )
                    for update in sensor_updates
                ),
            )
            states = []
            policy_states = dict(self._policy_states)
            for agent in world.agents:
                controlled = agent
                if agent.agent_id in self.policies:
                    context = AgentContext(
                        agent,
                        world.time,
                        self._sensing.observations_for(agent.agent_id, sensor_updates),
                        self._communications.messages_for(
                            agent.agent_id, world.time, network_frame
                        ),
                    )
                    decision = self.policies[agent.agent_id].decide(
                        context, policy_states[agent.agent_id], dt
                    )
                    controlled = replace(agent, speed=decision.speed, heading=decision.heading)
                    policy_states[agent.agent_id] = decision.state
                state = self.dynamics.propagate(controlled, world, dt, self._rng)
                self._validate_agent(state)
                if state.agent_id != agent.agent_id:
                    raise ValueError("dynamics must preserve agent IDs")
                if state.affiliation != agent.affiliation:
                    raise ValueError("dynamics must preserve agent affiliation")
                states.append(state)
        except Exception:
            self._rng.setstate(rng_state)
            raise

        for agent, state in zip(self.agents, states, strict=True):
            agent.x, agent.y = state.x, state.y
            agent.speed, agent.heading = state.speed, state.heading

        self.environment.advance(dt)
        self.tick += 1
        self._sensing.commit(sensor_updates)
        self._communications.commit(network_frame)
        self._policy_states = policy_states
        if self.mission is not None:
            self.mission.consume(
                tuple(detection for update in sensor_updates for detection in update.detections)
            )

    def run(self, duration: float, dt: float) -> None:
        if not isfinite(duration) or duration <= 0:
            raise ValueError("duration must be finite and greater than zero")

        if not isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and greater than zero")

        elapsed = 0.0
        steps = 0

        while elapsed < duration:
            next_elapsed = min((steps + 1) * dt, duration)
            if duration - next_elapsed <= 4 * ulp(duration):
                next_elapsed = duration
            step_dt = next_elapsed - elapsed

            if elapsed + step_dt <= elapsed:
                raise ValueError("dt is too small to advance elapsed time")

            self.step(step_dt)

            elapsed = next_elapsed
            steps += 1
