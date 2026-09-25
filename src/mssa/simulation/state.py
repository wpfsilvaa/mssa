"""Immutable observations of the authoritative world state."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentState:
    agent_id: str
    x: float
    y: float
    speed: float
    heading: float
    affiliation: str = "friendly"


@dataclass(frozen=True)
class WorldState:
    time: float
    tick: int
    width: float
    height: float
    agents: tuple[AgentState, ...]
