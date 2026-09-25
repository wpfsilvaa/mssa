from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite

from mssa.perception.model import AgentContext


@dataclass(frozen=True)
class PolicyState:
    waypoint_index: int = 0
    mode: str = "idle"
    target: tuple[float, float] | None = None


@dataclass(frozen=True)
class Decision:
    speed: float
    heading: float
    state: PolicyState


@dataclass(frozen=True)
class PolicySpec:
    kind: str
    speed: float = 10.0
    waypoints: tuple[tuple[float, float], ...] = ()
    loop: bool = True
    arrival_radius: float = 1.0
    reaction: str = "approach"
    reaction_distance: float = 250.0
    max_observation_age: float = 5.0
    use_messages: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {"patrol", "react"}:
            raise ValueError("unknown policy kind")
        if self.kind == "patrol" and not self.waypoints:
            raise ValueError("patrol policy requires at least one waypoint")
        if self.reaction not in {"approach", "avoid", "hold"}:
            raise ValueError("unknown reaction")
        values = (self.speed, self.arrival_radius, self.reaction_distance, self.max_observation_age)
        if not all(isfinite(value) for value in values):
            raise ValueError("policy parameters must be finite")
        if min(self.speed, self.arrival_radius) < 0 or min(values[2:]) <= 0:
            raise ValueError("invalid policy speed, radius or observation age")
        if any(not isfinite(value) for point in self.waypoints for value in point):
            raise ValueError("waypoints must be finite")

    def decide(self, context: AgentContext, previous: PolicyState, dt: float) -> Decision:
        """Pure decision: no world access, hidden target IDs, or mutable policy state."""
        own = context.own_state
        if self.kind == "react":
            observations = list(context.observations)
            if self.use_messages:
                observations.extend(
                    observation
                    for message in context.messages
                    if message.expires_at > context.time
                    for observation in message.observations
                )
            candidates = [
                observation
                for observation in observations
                if observation.available_at <= context.time
                and 0 <= context.time - observation.measured_at <= self.max_observation_age
                and hypot(observation.x - own.x, observation.y - own.y) <= self.reaction_distance
            ]
            if candidates:
                contact = min(
                    candidates,
                    key=lambda observation: (
                        -observation.measured_at,
                        hypot(observation.x - own.x, observation.y - own.y),
                        observation.sensor_id,
                        observation.measurement_id,
                    ),
                )
                target = (contact.x, contact.y)
                state = PolicyState(previous.waypoint_index, f"react_{self.reaction}", target)
                if self.reaction == "hold":
                    return Decision(0, own.heading, state)
                if self.reaction == "avoid":
                    dx, dy = own.x - contact.x, own.y - contact.y
                    heading = degrees(atan2(dy, dx)) if dx or dy else own.heading + 180
                    return Decision(self.speed, heading % 360, state)
                return self._approach(context, target, state, dt)
        index = previous.waypoint_index
        for _ in range(len(self.waypoints)):
            if index >= len(self.waypoints):
                break
            target = self.waypoints[index]
            if hypot(target[0] - own.x, target[1] - own.y) > self.arrival_radius:
                return self._approach(context, target, PolicyState(index, "patrol", target), dt)
            index += 1
            if self.loop:
                index %= len(self.waypoints)
        return Decision(0, own.heading, PolicyState(index, "idle"))

    def _approach(
        self, context: AgentContext, target: tuple[float, float], state: PolicyState, dt: float
    ) -> Decision:
        own = context.own_state
        dx, dy = target[0] - own.x, target[1] - own.y
        distance = hypot(dx, dy)
        if distance <= self.arrival_radius:
            return Decision(0, own.heading, state)
        return Decision(min(self.speed, distance / dt), degrees(atan2(dy, dx)) % 360, state)
