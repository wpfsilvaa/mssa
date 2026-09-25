"""Multirate sampling with independent per-sensor random streams."""

import json
from dataclasses import dataclass
from hashlib import sha256
from math import floor, isfinite, ulp
from random import Random

from mssa.perception.model import Observation
from mssa.sensors.model import Detection, GeometricSensor
from mssa.simulation.state import WorldState


@dataclass(frozen=True)
class SensorMount:
    agent_id: str
    sensor_id: str
    model: GeometricSensor
    period: float = 1.0

    def __post_init__(self) -> None:
        if not self.agent_id.strip() or not self.sensor_id.strip():
            raise ValueError("sensor and agent IDs must not be empty")
        if not isfinite(self.period) or self.period <= 0:
            raise ValueError("sensor period must be finite and positive")


@dataclass(frozen=True)
class SensorUpdate:
    key: tuple[str, str]
    next_sample: int
    rng_state: object
    detections: tuple[Detection, ...]


class SensingSystem:
    def __init__(self, mounts: tuple[SensorMount, ...], seed: int, epoch: float):
        self.mounts = mounts
        self.epoch = epoch
        self._rngs: dict[tuple[str, str], Random] = {}
        self._next_samples: dict[tuple[str, str], int] = {}
        self._observations: dict[tuple[str, str], tuple[Observation, ...]] = {}
        self.total_detections = 0
        self.total_scans = 0
        for mount in mounts:
            key = (mount.agent_id, mount.sensor_id)
            if key in self._rngs:
                raise ValueError("sensor IDs must be unique within each agent")
            encoded = json.dumps([seed, *key], ensure_ascii=True).encode("utf-8")
            self._rngs[key] = Random(sha256(encoded).digest())
            self._next_samples[key] = 0

    def prepare(self, world: WorldState) -> tuple[SensorUpdate, ...]:
        """Calculate scans without consuming RNG or changing local perceptions."""
        agents = {agent.agent_id: agent for agent in world.agents}
        updates = []
        elapsed = world.time - self.epoch
        for mount in self.mounts:
            key = (mount.agent_id, mount.sensor_id)
            sample = self._next_samples[key]
            due = self.epoch + sample * mount.period
            if not isfinite(due):
                continue
            tolerance = 4 * max(ulp(world.time), ulp(due))
            if world.time < due - tolerance:
                continue
            slot = elapsed / mount.period
            if not isfinite(slot):
                raise ValueError("sensor period is too small for the simulation clock")
            next_sample = max(sample + 1, floor(slot + 4 * ulp(slot)) + 1)
            rng = Random(0)
            rng.setstate(self._rngs[key].getstate())
            detections = mount.model.observe(
                agents[mount.agent_id], world, rng, mount.sensor_id, sample
            )
            updates.append(SensorUpdate(key, next_sample, rng.getstate(), detections))
        return tuple(updates)

    def commit(self, updates: tuple[SensorUpdate, ...]) -> None:
        for update in updates:
            self._rngs[update.key].setstate(update.rng_state)
            self._next_samples[update.key] = update.next_sample
            self._observations[update.key] = tuple(d.observation for d in update.detections)
            self.total_scans += 1
            self.total_detections += len(update.detections)

    def observations_for(
        self, agent_id: str, updates: tuple[SensorUpdate, ...] = ()
    ) -> tuple[Observation, ...]:
        observations_by_sensor = self._observations | {
            update.key: tuple(detection.observation for detection in update.detections)
            for update in updates
        }
        return tuple(
            observation
            for (owner, sensor), observations in sorted(observations_by_sensor.items())
            if owner == agent_id
            for observation in observations
        )
