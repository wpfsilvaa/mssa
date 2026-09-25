"""Versioned scenario input, independent of mutable simulation state."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[Finite, Field(gt=0)]
NonNegative = Annotated[Finite, Field(ge=0)]
Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EnvironmentConfig(Configuration):
    width: Positive
    height: Positive


class SensorConfig(Configuration):
    id: Identifier
    range: Positive
    field_of_view: Annotated[Finite, Field(gt=0, le=360)] = 360.0
    heading_offset: Finite = 0.0
    period: Positive = 1.0
    probability_of_detection: Annotated[Finite, Field(ge=0, le=1)] = 1.0
    position_std: NonNegative = 0.0


class WaypointConfig(Configuration):
    x: Finite
    y: Finite


class PolicyConfig(Configuration):
    kind: Literal["patrol", "react"]
    speed: NonNegative = 10.0
    waypoints: tuple[WaypointConfig, ...] = ()
    loop: bool = True
    arrival_radius: NonNegative = 1.0
    reaction: Literal["approach", "avoid", "hold"] = "approach"
    reaction_distance: Positive = 250.0
    max_observation_age: Positive = 5.0
    use_messages: bool = True

    @model_validator(mode="after")
    def patrol_requires_route(self) -> "PolicyConfig":
        if self.kind == "patrol" and not self.waypoints:
            raise ValueError("patrol policy requires at least one waypoint")
        return self


class AgentConfig(Configuration):
    id: Identifier
    x: Finite
    y: Finite
    speed: NonNegative = 0.0
    heading: Finite = 0.0
    affiliation: Literal["friendly", "hostile", "neutral"] = "friendly"
    sensors: tuple[SensorConfig, ...] = ()
    policy: PolicyConfig | None = None

    @model_validator(mode="after")
    def unique_sensor_ids(self) -> "AgentConfig":
        ids = [sensor.id for sensor in self.sensors]
        if len(ids) != len(set(ids)):
            raise ValueError("sensor IDs must be unique within each agent")
        return self


class ObservationMissionConfig(Configuration):
    kind: Literal["observe_targets"] = "observe_targets"
    observer_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    target_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_participants(self) -> "ObservationMissionConfig":
        for ids in (self.observer_ids, self.target_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("mission participant IDs must be unique")
        if set(self.observer_ids) & set(self.target_ids):
            raise ValueError("mission observers and targets must be disjoint")
        return self


class RunConfig(Configuration):
    duration: Positive = 60.0
    dt: Positive = 0.1
    seed: Annotated[int, Field(strict=True, ge=0)] = 0


class CommunicationLinkConfig(Configuration):
    sender_id: Identifier
    recipient_id: Identifier
    range: Positive
    latency: NonNegative = 0.0
    loss_probability: Annotated[Finite, Field(ge=0, le=1)] = 0.0
    queue_capacity: Annotated[int, Field(strict=True, gt=0)] = 32
    ttl: Positive = 5.0


class ScenarioConfig(Configuration):
    schema_version: Literal[1] = 1
    environment: EnvironmentConfig
    agents: tuple[AgentConfig, ...] = ()
    simulation: RunConfig = Field(default_factory=RunConfig)
    mission: ObservationMissionConfig | None = None
    communication_links: tuple[CommunicationLinkConfig, ...] = ()

    @model_validator(mode="after")
    def unique_agent_ids(self) -> "ScenarioConfig":
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent IDs must be unique")
        links = [(link.sender_id, link.recipient_id) for link in self.communication_links]
        if len(links) != len(set(links)):
            raise ValueError("directed communication links must be unique")
        for sender, recipient in links:
            if sender == recipient:
                raise ValueError("communication links must connect distinct agents")
            if sender not in ids or recipient not in ids:
                raise ValueError("communication link references unknown agent IDs")
        if self.mission is not None:
            participants = set(self.mission.observer_ids) | set(self.mission.target_ids)
            if not participants <= set(ids):
                raise ValueError("mission references unknown agent IDs")
            agents = {agent.id: agent for agent in self.agents}
            if any(not agents[observer].sensors for observer in self.mission.observer_ids):
                raise ValueError("each mission observer must have at least one sensor")
        return self
