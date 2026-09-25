from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite
from random import Random

from mssa.perception.model import Observation
from mssa.simulation.state import AgentState, WorldState


@dataclass(frozen=True)
class Detection:
    """Evaluator-only association; never exposed through AgentContext."""

    observer_id: str
    target_id: str
    observation: Observation


@dataclass(frozen=True)
class GeometricSensor:
    max_range: float
    field_of_view: float = 360.0
    heading_offset: float = 0.0
    probability_of_detection: float = 1.0
    position_std: float = 0.0

    def __post_init__(self) -> None:
        if not all(
            isfinite(value)
            for value in (
                self.max_range,
                self.field_of_view,
                self.heading_offset,
                self.probability_of_detection,
                self.position_std,
            )
        ):
            raise ValueError("sensor parameters must be finite")
        if self.max_range <= 0 or not 0 < self.field_of_view <= 360:
            raise ValueError("sensor range must be positive and field of view in (0, 360]")
        if not 0 <= self.probability_of_detection <= 1 or self.position_std < 0:
            raise ValueError("invalid sensor probability or position uncertainty")

    def observe(
        self,
        observer: AgentState,
        world: WorldState,
        rng: Random,
        sensor_id: str,
        sample_index: int,
    ) -> tuple[Detection, ...]:
        detections = []
        for target in sorted(world.agents, key=lambda agent: agent.agent_id):
            if target.agent_id == observer.agent_id:
                continue
            dx, dy = target.x - observer.x, target.y - observer.y
            distance = hypot(dx, dy)
            if distance > self.max_range:
                continue
            bearing = degrees(atan2(dy, dx))
            offset = (bearing - observer.heading - self.heading_offset + 180) % 360 - 180
            # Coincident platforms have no meaningful bearing and are in view.
            if distance > 0 and abs(offset) > self.field_of_view / 2:
                continue
            if rng.random() >= self.probability_of_detection:
                continue
            x = target.x + rng.gauss(0, self.position_std)
            y = target.y + rng.gauss(0, self.position_std)
            if not isfinite(x) or not isfinite(y):
                raise ValueError("sensor measurement overflow")
            detections.append(
                Detection(
                    observer_id=observer.agent_id,
                    target_id=target.agent_id,
                    observation=Observation(
                        measurement_id=f"{sensor_id}/{sample_index}/{len(detections)}",
                        sensor_id=sensor_id,
                        measured_at=world.time,
                        available_at=world.time,
                        x=x,
                        y=y,
                        position_std=self.position_std,
                    ),
                )
            )
        return tuple(detections)
