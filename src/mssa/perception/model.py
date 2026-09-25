from dataclasses import dataclass

from mssa.simulation.state import AgentState


@dataclass(frozen=True)
class Observation:
    """An anonymous position measurement, without target identity or affiliation."""

    measurement_id: str
    sensor_id: str
    measured_at: float
    available_at: float
    x: float
    y: float
    position_std: float


@dataclass(frozen=True)
class ReceivedMessage:
    """A delivered sensor report; payload contains no evaluator truth associations."""

    message_id: str
    sender_id: str
    recipient_id: str
    sensor_id: str
    sent_at: float
    received_at: float
    expires_at: float
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class AgentContext:
    own_state: AgentState
    time: float
    observations: tuple[Observation, ...]
    messages: tuple[ReceivedMessage, ...] = ()
