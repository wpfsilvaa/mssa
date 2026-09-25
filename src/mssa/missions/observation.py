from dataclasses import dataclass
from typing import Literal

from mssa.sensors.model import Detection


@dataclass(frozen=True)
class TargetDetection:
    target_id: str
    first_detected_at: float


@dataclass(frozen=True)
class ObservationMissionResult:
    status: Literal["in_progress", "succeeded", "timeout"]
    required_targets: int
    detected_targets: int
    first_detection_time: float | None
    completion_time: float | None
    target_detections: tuple[TargetDetection, ...]


class ObservationMission:
    def __init__(self, observer_ids: tuple[str, ...], target_ids: tuple[str, ...]):
        if not observer_ids or not target_ids:
            raise ValueError("observation mission requires observers and targets")
        if len(set(observer_ids)) != len(observer_ids) or len(set(target_ids)) != len(target_ids):
            raise ValueError("mission participant IDs must be unique")
        if set(observer_ids) & set(target_ids):
            raise ValueError("mission observers and targets must be disjoint")
        self.observer_ids = observer_ids
        self.target_ids = target_ids
        self._first_detections: dict[str, float] = {}

    def consume(self, detections: tuple[Detection, ...]) -> None:
        for detection in detections:
            if (
                detection.observer_id in self.observer_ids
                and detection.target_id in self.target_ids
            ):
                self._first_detections.setdefault(
                    detection.target_id, detection.observation.measured_at
                )

    def result(self, *, finished: bool = False) -> ObservationMissionResult:
        times = tuple(self._first_detections.values())
        succeeded = len(times) == len(self.target_ids)
        return ObservationMissionResult(
            status="succeeded" if succeeded else "timeout" if finished else "in_progress",
            required_targets=len(self.target_ids),
            detected_targets=len(times),
            first_detection_time=min(times) if times else None,
            completion_time=max(times) if succeeded else None,
            target_detections=tuple(
                TargetDetection(target, self._first_detections[target])
                for target in self.target_ids
                if target in self._first_detections
            ),
        )
