"""Motion models operate on snapshots, without mutating the world."""

from dataclasses import dataclass, replace
from math import cos, radians, sin
from random import Random
from typing import Protocol

from mssa.simulation.state import AgentState, WorldState


class Dynamics(Protocol):
    def propagate(
        self, agent: AgentState, world: WorldState, dt: float, rng: Random
    ) -> AgentState: ...


@dataclass(frozen=True)
class KinematicDynamics:
    """Constant speed, heading in degrees, unbounded Cartesian coordinates."""

    def propagate(self, agent: AgentState, world: WorldState, dt: float, rng: Random) -> AgentState:
        angle = radians(agent.heading)
        return replace(
            agent,
            x=agent.x + agent.speed * cos(angle) * dt,
            y=agent.y + agent.speed * sin(angle) * dt,
        )
