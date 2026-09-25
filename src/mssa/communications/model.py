from dataclasses import asdict, dataclass
from math import isfinite

from mssa.perception.model import Observation


@dataclass(frozen=True)
class CommunicationLink:
    sender_id: str
    recipient_id: str
    max_range: float
    latency: float = 0.0
    loss_probability: float = 0.0
    queue_capacity: int = 32
    ttl: float = 5.0

    def __post_init__(self) -> None:
        if not self.sender_id.strip() or not self.recipient_id.strip():
            raise ValueError("communication endpoint IDs must not be empty")
        if self.sender_id == self.recipient_id:
            raise ValueError("communication links must connect distinct agents")
        if not all(
            isfinite(value)
            for value in (self.max_range, self.latency, self.loss_probability, self.ttl)
        ):
            raise ValueError("communication parameters must be finite")
        if self.max_range <= 0 or self.latency < 0 or self.ttl <= 0:
            raise ValueError("invalid communication range, latency or TTL")
        if not 0 <= self.loss_probability <= 1:
            raise ValueError("loss probability must be in [0, 1]")
        if type(self.queue_capacity) is not int or self.queue_capacity <= 0:
            raise ValueError("queue capacity must be a positive integer")

    @property
    def key(self) -> tuple[str, str]:
        return self.sender_id, self.recipient_id


@dataclass(frozen=True)
class ObservationBatch:
    sender_id: str
    sensor_id: str
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class PendingMessage:
    message_id: str
    sender_id: str
    recipient_id: str
    sensor_id: str
    sent_at: float
    deliver_at: float
    expires_at: float
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class NetworkEvent:
    time: float
    status: str
    message_id: str
    sender_id: str
    recipient_id: str
    sender_position: tuple[float, float]
    recipient_position: tuple[float, float]


@dataclass(frozen=True)
class NetworkMetrics:
    attempted: int = 0
    enqueued: int = 0
    delivered: int = 0
    dropped_out_of_range: int = 0
    dropped_loss: int = 0
    dropped_queue_full: int = 0
    expired: int = 0
    pending: int = 0
    total_delivery_latency: float = 0.0

    @property
    def delivery_rate(self) -> float | None:
        return self.delivered / self.attempted if self.attempted else None

    @property
    def mean_delivery_latency(self) -> float | None:
        return self.total_delivery_latency / self.delivered if self.delivered else None

    def to_dict(self) -> dict:
        return asdict(self) | {
            "delivery_rate": self.delivery_rate,
            "mean_delivery_latency": self.mean_delivery_latency,
        }
