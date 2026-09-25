from dataclasses import FrozenInstanceError, asdict, replace
from random import Random
from statistics import fmean, stdev

import pytest
from pydantic import ValidationError

from mssa.application.run import create_simulation, run_scenario
from mssa.scenarios.schema import ScenarioConfig
from mssa.sensors.model import GeometricSensor
from mssa.simulation.state import AgentState, WorldState


def observation_config(**sensor_changes):
    return ScenarioConfig.model_validate(
        {
            "environment": {"width": 100, "height": 100},
            "simulation": {"duration": 1, "dt": 0.25, "seed": 42},
            "agents": [
                {
                    "id": "observer",
                    "x": 0,
                    "y": 0,
                    "sensors": [{"id": "sensor", "range": 10, "period": 0.5} | sensor_changes],
                },
                {"id": "target", "x": 5, "y": 0, "affiliation": "hostile"},
            ],
            "mission": {"observer_ids": ["observer"], "target_ids": ["target"]},
        }
    )


@pytest.mark.parametrize(
    "x,y,heading,fov,offset,expected",
    [
        (10, 0, 0, 90, 0, True),  # Range boundary is inclusive.
        (10.01, 0, 0, 90, 0, False),
        (5, 5, 0, 90, 0, True),  # FOV boundary is inclusive.
        (5, 5.01, 0, 90, 0, False),
        (-5, 0, 0, 90, 0, False),
        (-5, 0, 0, 360, 0, True),
        (5, 0, 359, 10, 0, True),  # Bearing wraps at 360 degrees.
        (0, 5, 0, 10, 90, True),  # Sensor mount has its own orientation.
        (0, 0, 180, 10, 0, True),  # Coincident platforms have no bearing.
    ],
)
def test_geometric_visibility(x, y, heading, fov, offset, expected):
    observer = AgentState("observer", 0, 0, 0, heading)
    target = AgentState("target", x, y, 0, 0, "hostile")
    world = WorldState(0, 0, 100, 100, (observer, target))
    sensor = GeometricSensor(10, fov, offset)
    detections = sensor.observe(observer, world, Random(42), "sensor", 0)
    assert bool(detections) == expected
    if expected:
        assert len(detections) == 1  # The observer never detects itself.
        assert detections[0].target_id == "target"
        assert detections[0].observation.x == x
        assert detections[0].observation.y == y


def test_measurement_noise_is_reproducible_and_has_configured_scale():
    observer = AgentState("observer", 0, 0, 0, 0)
    target = AgentState("target", 3, 4, 0, 0)
    world = WorldState(0, 0, 100, 100, (observer, target))
    sensor = GeometricSensor(10, position_std=2)
    rng = Random(42)
    measurements = [
        sensor.observe(observer, world, rng, "sensor", i)[0].observation for i in range(1000)
    ]
    errors = [observation.x - target.x for observation in measurements]
    assert fmean(errors) == pytest.approx(0, abs=0.25)
    assert stdev(errors) == pytest.approx(2, abs=0.15)
    assert target.x == 3  # Measurement noise cannot perturb ground truth.
    assert (
        measurements[0] == sensor.observe(observer, world, Random(42), "sensor", 0)[0].observation
    )


def test_context_contains_only_local_anonymous_measurements():
    simulation = create_simulation(observation_config())
    assert simulation.context("observer").observations == ()
    simulation.step(0.25)
    context = simulation.context("observer")
    assert len(context.observations) == 1
    assert simulation.context("target").observations == ()
    assert set(asdict(context)) == {"own_state", "time", "observations", "messages"}
    assert context.messages == ()
    measurement = asdict(context.observations[0])
    assert "target_id" not in measurement
    assert "affiliation" not in measurement
    assert measurement["measured_at"] == 0
    with pytest.raises(FrozenInstanceError):
        context.observations[0].x = 10
    with pytest.raises(ValueError, match="unknown agent"):
        simulation.context("unknown")


@pytest.mark.parametrize(
    "period,dt,duration,scans,last_scan",
    [
        (0.5, 0.25, 1, 2, 0.5),
        (0.3, 0.1, 1, 4, 0.9),
        (0.2, 0.5, 1.5, 3, 1),  # No synthetic scans for missed periods.
        (0.9, 0.3, 1, 2, 0.9),  # Partial final step still samples its start.
        (10, 0.25, 1, 1, 0),
    ],
)
def test_sampling_periods_and_last_scan_timestamps(period, dt, duration, scans, last_scan):
    simulation = create_simulation(observation_config(period=period))
    simulation.run(duration, dt)
    assert simulation.total_scans == scans
    assert simulation.context("observer").observations[0].measured_at == pytest.approx(last_scan)


def test_continued_run_preserves_sampling_schedule_and_rng():
    config = observation_config(position_std=1, probability_of_detection=0.8)
    continuous, continued = create_simulation(config), create_simulation(config)
    continuous.run(1, 0.25)
    continued.run(0.5, 0.25)
    continued.run(0.5, 0.25)
    assert continuous.context("observer") == continued.context("observer")
    assert continuous.total_detections == continued.total_detections


def test_empty_scan_clears_previous_measurements_but_mission_retains_detection():
    simulation = create_simulation(observation_config())
    simulation.step(0.5)
    assert simulation.context("observer").observations
    simulation.agents[1].x = 50
    simulation.step(0.5)
    assert simulation.context("observer").observations == ()
    assert simulation.mission.result().status == "succeeded"


def test_sensor_stream_does_not_depend_on_other_sensors_or_agent_order():
    config = observation_config(position_std=2, probability_of_detection=0.8)
    data = config.model_dump(mode="json")
    data["agents"][1]["sensors"] = [{"id": "extra", "range": 100}]
    data["agents"].reverse()
    original = create_simulation(config)
    extended = create_simulation(ScenarioConfig.model_validate(data))
    original.run(1, 0.25)
    extended.run(1, 0.25)
    assert original.context("observer") == extended.context("observer")


class InvalidMotion:
    def propagate(self, agent, world, dt, rng):
        rng.random()
        return replace(agent, x=float("nan"))


def test_failed_step_does_not_commit_scans_perception_or_mission():
    config = observation_config(position_std=2)
    simulation, fresh = create_simulation(config), create_simulation(config)
    dynamics = simulation.dynamics
    simulation.dynamics = InvalidMotion()
    with pytest.raises(ValueError):
        simulation.step(0.25)
    assert simulation.snapshot() == fresh.snapshot()
    assert simulation.total_scans == simulation.total_detections == 0
    assert simulation.context("observer").observations == ()
    assert simulation.mission.result().status == "in_progress"
    simulation.dynamics = dynamics
    simulation.step(0.25)
    fresh.step(0.25)
    assert simulation.context("observer") == fresh.context("observer")


@pytest.mark.parametrize(
    "changes",
    [
        {"range": 0},
        {"field_of_view": 0},
        {"field_of_view": 361},
        {"period": 0},
        {"probability_of_detection": 1.1},
        {"probability_of_detection": -0.1},
        {"position_std": -1},
        {"position_std": float("nan")},
    ],
)
def test_invalid_sensor_config_is_rejected(changes):
    with pytest.raises(ValidationError):
        observation_config(**changes)


def test_duplicate_sensor_ids_are_rejected():
    data = observation_config().model_dump(mode="json")
    data["agents"][0]["sensors"] *= 2
    with pytest.raises(ValidationError, match="sensor IDs must be unique"):
        ScenarioConfig.model_validate(data)


def test_scenario_without_sensors_keeps_legacy_behavior():
    data = observation_config().model_dump(mode="json")
    data["agents"][0]["sensors"] = []
    data["mission"] = None
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.total_detections == result.total_scans == 0
    assert result.mission is None
    assert all(not context.observations for context in result.perceptions)
