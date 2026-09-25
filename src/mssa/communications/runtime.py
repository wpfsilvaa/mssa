"""Transactional, deterministic transport of reports from fresh sensor scans."""

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from math import hypot, isfinite, ulp
from random import Random

from mssa.communications.model import (
    CommunicationLink,
    NetworkEvent,
    NetworkMetrics,
    ObservationBatch,
    PendingMessage,
)
from mssa.perception.model import ReceivedMessage
from mssa.simulation.state import WorldState


def _reached(now: float, deadline: float) -> bool:
    return now >= deadline or deadline - now <= 4 * max(ulp(now), ulp(deadline))


@dataclass(frozen=True)
class NetworkFrame:
    pending: tuple[PendingMessage, ...]
    inbox: tuple[ReceivedMessage, ...]
    rng_states: dict[tuple[str, str], object]
    sequences: dict[tuple[str, str], int]
    metrics: NetworkMetrics
    events: tuple[NetworkEvent, ...] = ()


class CommunicationSystem:
    def __init__(self, links: tuple[CommunicationLink, ...], seed: int):
        self._links = {link.key: link for link in sorted(links, key=lambda link: link.key)}
        if len(self._links) != len(links):
            raise ValueError("directed communication links must be unique")
        rng_states = {}
        for key in self._links:
            encoded = json.dumps(["communications", seed, *key], ensure_ascii=True).encode("utf-8")
            rng_states[key] = Random(sha256(encoded).digest()).getstate()
        self._frame = NetworkFrame(
            (), (), rng_states, dict.fromkeys(self._links, 0), NetworkMetrics()
        )

    @property
    def metrics(self) -> NetworkMetrics:
        return self._frame.metrics

    @property
    def events(self) -> tuple[NetworkEvent, ...]:
        return self._frame.events

    @property
    def pending(self) -> tuple[PendingMessage, ...]:
        return self._frame.pending

    def messages_for(
        self, agent_id: str, time: float, frame: NetworkFrame | None = None
    ) -> tuple[ReceivedMessage, ...]:
        return tuple(
            message
            for message in (frame if frame is not None else self._frame).inbox
            if message.recipient_id == agent_id and not _reached(time, message.expires_at)
        )

    def prepare(self, world: WorldState, batches: tuple[ObservationBatch, ...]) -> NetworkFrame:
        """Deliver earlier reports first, then enqueue new scans for later steps."""
        agents = {agent.agent_id: agent for agent in world.agents}
        pending = []
        events = []

        def record(sender: str, recipient: str, message_id: str, status: str) -> None:
            source, destination = agents[sender], agents[recipient]
            events.append(
                NetworkEvent(
                    world.time,
                    status,
                    message_id,
                    sender,
                    recipient,
                    (source.x, source.y),
                    (destination.x, destination.y),
                )
            )

        inbox = {
            (message.recipient_id, message.sender_id, message.sensor_id): message
            for message in self._frame.inbox
            if not _reached(world.time, message.expires_at)
        }
        counts = {
            name: getattr(self._frame.metrics, name)
            for name in (
                "attempted",
                "enqueued",
                "delivered",
                "dropped_out_of_range",
                "dropped_loss",
                "dropped_queue_full",
                "expired",
                "total_delivery_latency",
            )
        }

        def in_range(link: CommunicationLink) -> bool:
            sender, recipient = agents[link.sender_id], agents[link.recipient_id]
            return hypot(sender.x - recipient.x, sender.y - recipient.y) <= link.max_range

        for message in sorted(self._frame.pending, key=lambda message: message.deliver_at):
            if _reached(world.time, message.expires_at):
                counts["expired"] += 1
                record(message.sender_id, message.recipient_id, message.message_id, "expired")
            elif not _reached(world.time, message.deliver_at):
                pending.append(message)
            elif not in_range(self._links[(message.sender_id, message.recipient_id)]):
                counts["dropped_out_of_range"] += 1
                record(message.sender_id, message.recipient_id, message.message_id, "out_of_range")
            else:
                delivered = ReceivedMessage(
                    message_id=message.message_id,
                    sender_id=message.sender_id,
                    recipient_id=message.recipient_id,
                    sensor_id=message.sensor_id,
                    sent_at=message.sent_at,
                    received_at=world.time,
                    expires_at=message.expires_at,
                    observations=tuple(
                        replace(observation, available_at=world.time)
                        for observation in message.observations
                    ),
                )
                inbox[(message.recipient_id, message.sender_id, message.sensor_id)] = delivered
                counts["delivered"] += 1
                record(message.sender_id, message.recipient_id, message.message_id, "delivered")
                counts["total_delivery_latency"] += world.time - message.sent_at

        rng_states = dict(self._frame.rng_states)
        sequences = dict(self._frame.sequences)
        batches_by_sender: dict[str, list[ObservationBatch]] = {}
        for batch in sorted(batches, key=lambda batch: (batch.sender_id, batch.sensor_id)):
            batches_by_sender.setdefault(batch.sender_id, []).append(batch)
        occupancies = dict.fromkeys(self._links, 0)
        for message in pending:
            occupancies[(message.sender_id, message.recipient_id)] += 1
        for key, link in self._links.items():
            occupancy = occupancies[key]
            rng = Random(0)
            rng.setstate(rng_states[key])
            for batch in batches_by_sender.get(link.sender_id, ()):
                sequence = sequences[key]
                message_id = json.dumps([*key, sequence], separators=(",", ":"))
                sequences[key] += 1
                counts["attempted"] += 1
                if not in_range(link):
                    counts["dropped_out_of_range"] += 1
                    record(*key, message_id, "out_of_range")
                    continue
                if occupancy >= link.queue_capacity:
                    counts["dropped_queue_full"] += 1
                    record(*key, message_id, "queue_full")
                    continue
                if rng.random() < link.loss_probability:
                    counts["dropped_loss"] += 1
                    record(*key, message_id, "lost")
                    continue
                deliver_at = world.time + link.latency
                expires_at = world.time + link.ttl
                if not isfinite(deliver_at) or not isfinite(expires_at) or expires_at <= world.time:
                    raise ValueError(
                        "communication deadlines must be finite and TTL must advance time"
                    )
                pending.append(
                    PendingMessage(
                        message_id=message_id,
                        sender_id=link.sender_id,
                        recipient_id=link.recipient_id,
                        sensor_id=batch.sensor_id,
                        sent_at=world.time,
                        deliver_at=deliver_at,
                        expires_at=expires_at,
                        observations=batch.observations,
                    )
                )
                counts["enqueued"] += 1
                record(*key, message_id, "sent")
                occupancy += 1
            rng_states[key] = rng.getstate()
        return NetworkFrame(
            tuple(pending),
            tuple(inbox[key] for key in sorted(inbox)),
            rng_states,
            sequences,
            NetworkMetrics(**counts, pending=len(pending)),
            tuple(events),
        )

    def commit(self, frame: NetworkFrame) -> None:
        self._frame = frame
