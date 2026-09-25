import json

import pytest
from pydantic import ValidationError

from mssa.application.run import create_simulation, run_scenario
from mssa.cli import main
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.scenarios.schema import ScenarioConfig


def mission_config(probability=1, target_x=11):
    return ScenarioConfig.model_validate(
        {
            "environment": {"width": 100, "height": 100},
            "simulation": {"duration": 2, "dt": 0.5},
            "agents": [
                {
                    "id": "observer",
                    "x": 0,
                    "y": 0,
                    "sensors": [
                        {
                            "id": "sensor",
                            "range": 10,
                            "period": 0.5,
                            "probability_of_detection": probability,
                        }
                    ],
                },
                {
                    "id": "target",
                    "x": target_x,
                    "y": 0,
                    "speed": 1,
                    "heading": 180,
                    "affiliation": "hostile",
                },
            ],
            "mission": {"observer_ids": ["observer"], "target_ids": ["target"]},
        }
    )


def test_target_entering_range_completes_mission_at_known_time():
    result = run_scenario(mission_config())
    assert result.mission.status == "succeeded"
    assert result.mission.first_detection_time == pytest.approx(1)
    assert result.mission.completion_time == pytest.approx(1)
    assert result.final.time == pytest.approx(2)  # Success does not shorten the horizon.
    assert result.mission.detected_targets == result.mission.required_targets == 1


def test_completion_requires_last_target_and_repeated_detections_do_not_double_count():
    data = mission_config().model_dump(mode="json")
    data["agents"].append({"id": "early-target", "x": 5, "y": 0})
    data["mission"]["target_ids"].append("early-target")
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.mission.first_detection_time == 0
    assert result.mission.completion_time == pytest.approx(1)
    assert result.mission.detected_targets == 2
    assert result.total_detections == 6


def test_final_endpoint_is_excluded_from_sensing():
    result = run_scenario(mission_config(target_x=12))
    assert result.mission.status == "timeout"
    assert result.mission.first_detection_time is None
    assert result.mission.completion_time is None
    assert result.final.agents[1].x == pytest.approx(10)


def test_all_targets_are_required_and_only_designated_observers_score():
    data = mission_config(target_x=5).model_dump(mode="json")
    data["agents"].extend(
        [
            {"id": "second-target", "x": 50, "y": 0},
            {"id": "other-observer", "x": 50, "y": 1, "sensors": [{"id": "sensor", "range": 5}]},
        ]
    )
    data["mission"]["target_ids"].append("second-target")
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.mission.status == "timeout"
    assert result.mission.first_detection_time == 0
    assert result.mission.detected_targets == 1
    assert result.mission.completion_time is None
    data["mission"]["observer_ids"].append("other-observer")
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.mission.status == "succeeded"
    assert result.mission.completion_time == 0


def test_hostile_observer_uses_same_sensor_and_mission_rules():
    data = mission_config().model_dump(mode="json")
    data["agents"][0]["affiliation"] = "hostile"
    data["agents"][1]["affiliation"] = "friendly"
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.mission.first_detection_time == pytest.approx(1)


@pytest.mark.parametrize(
    "observers,targets",
    [
        ([], ["target"]),
        (["observer"], []),
        (["missing"], ["target"]),
        (["observer"], ["missing"]),
        (["observer"], ["observer"]),
        (["observer", "observer"], ["target"]),
        (["observer"], ["target", "target"]),
        (["target"], ["observer"]),  # This observer has no sensor.
    ],
)
def test_invalid_mission_is_rejected(observers, targets):
    data = mission_config().model_dump(mode="json")
    data["mission"] = {"observer_ids": observers, "target_ids": targets}
    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(data)


@pytest.mark.parametrize("probability,rate,first_time", [(0, 0, None), (1, 1, 0)])
def test_monte_carlo_extreme_detection_probabilities(probability, rate, first_time):
    result = run_monte_carlo(mission_config(probability, target_x=5), MonteCarloConfig(runs=3))
    assert result.summary.mission_runs == 3
    assert result.summary.success_rate == rate
    assert result.summary.successful_missions == 3 * rate
    assert result.summary.runs_with_detection == 3 * rate
    assert result.summary.mean_first_detection_time == first_time
    assert result.summary.mean_completion_time == first_time


def test_monte_carlo_has_stochastic_outcomes_and_reproducible_mission_metrics():
    data = mission_config(0.5, target_x=5).model_dump(mode="json")
    data["simulation"]["duration"] = 0.5  # Exactly one detection opportunity.
    config = ScenarioConfig.model_validate(data)
    experiment = MonteCarloConfig(runs=200, seed=42)
    result = run_monte_carlo(config, experiment)
    assert 0.35 < result.summary.success_rate < 0.65
    assert result == run_monte_carlo(config, experiment)
    assert result.summary.mean_first_detection_time == 0


def test_mission_progress_is_isolated_between_simulations():
    config = mission_config(target_x=5)
    first, second = create_simulation(config), create_simulation(config)
    first.step(0.5)
    assert first.mission.result().status == "succeeded"
    assert second.mission.result().status == "in_progress"


def test_cli_exports_observation_and_mission_results(tmp_path):
    output = tmp_path / "observation.json"
    assert main(["scenarios/observation.yaml", "--runs", "4", "--output", str(output)]) == 0
    data = json.loads(output.read_text())
    assert data["summary"]["mission_runs"] == 4
    assert all(run["mission"]["required_targets"] == 2 for run in data["runs"])
    assert data["runs"][0]["total_scans"] == 50
    assert data["runs"][0]["perceptions"][3]["observations"] == []
