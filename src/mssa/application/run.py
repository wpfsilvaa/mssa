from dataclasses import dataclass, field

from mssa.communications.model import CommunicationLink, NetworkMetrics
from mssa.missions.observation import ObservationMission, ObservationMissionResult
from mssa.perception.model import AgentContext
from mssa.policies.model import PolicySpec
from mssa.scenarios.loader import build_world
from mssa.scenarios.schema import ScenarioConfig
from mssa.sensors.model import GeometricSensor
from mssa.sensors.runtime import SensorMount
from mssa.simulation.engine import Simulation
from mssa.simulation.state import WorldState


@dataclass(frozen=True)
class RunResult:
    schema_version: int
    scenario: ScenarioConfig
    initial: WorldState
    final: WorldState
    perceptions: tuple[AgentContext, ...] = ()
    mission: ObservationMissionResult | None = None
    total_scans: int = 0
    total_detections: int = 0
    network: NetworkMetrics = field(default_factory=NetworkMetrics)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario.model_dump(mode="json"),
            "initial": asdict(self.initial),
            "final": asdict(self.final),
            "perceptions": [asdict(context) for context in self.perceptions],
            "mission": asdict(self.mission) if self.mission is not None else None,
            "total_scans": self.total_scans,
            "total_detections": self.total_detections,
            "network": self.network.to_dict(),
        }


def create_simulation(config: ScenarioConfig) -> Simulation:
    environment, agents = build_world(config)
    mounts = tuple(
        SensorMount(
            agent_id=agent.id,
            sensor_id=sensor.id,
            period=sensor.period,
            model=GeometricSensor(
                max_range=sensor.range,
                field_of_view=sensor.field_of_view,
                heading_offset=sensor.heading_offset,
                probability_of_detection=sensor.probability_of_detection,
                position_std=sensor.position_std,
            ),
        )
        for agent in config.agents
        for sensor in agent.sensors
    )
    mission = None
    if config.mission is not None:
        mission = ObservationMission(config.mission.observer_ids, config.mission.target_ids)
    return Simulation(
        environment=environment,
        agents=agents,
        seed=config.simulation.seed,
        sensor_mounts=mounts,
        mission=mission,
        policies={
            agent.id: PolicySpec(
                **agent.policy.model_dump(exclude={"waypoints"}),
                waypoints=tuple((point.x, point.y) for point in agent.policy.waypoints),
            )
            for agent in config.agents
            if agent.policy is not None
        },
        communication_links=tuple(
            CommunicationLink(
                sender_id=link.sender_id,
                recipient_id=link.recipient_id,
                max_range=link.range,
                latency=link.latency,
                loss_probability=link.loss_probability,
                queue_capacity=link.queue_capacity,
                ttl=link.ttl,
            )
            for link in config.communication_links
        ),
    )


def run_scenario(config: ScenarioConfig) -> RunResult:
    simulation = create_simulation(config)
    initial = simulation.snapshot()
    simulation.run(duration=config.simulation.duration, dt=config.simulation.dt)
    return RunResult(
        schema_version=1,
        scenario=config,
        initial=initial,
        final=simulation.snapshot(),
        perceptions=simulation.contexts(),
        mission=simulation.mission.result(finished=True)
        if simulation.mission is not None
        else None,
        total_scans=simulation.total_scans,
        total_detections=simulation.total_detections,
        network=simulation.network_metrics,
    )
