import json

import pytest
from pydantic import ValidationError

from mssa.cli import main
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.scenarios.schema import ScenarioConfig


def scenario():
    return ScenarioConfig.model_validate(
        {
            "environment": {"width": 100, "height": 100},
            "simulation": {"duration": 2, "dt": 0.3},
            "agents": [{"id": "a", "x": 0, "y": 0, "speed": 5}],
        }
    )


def test_monte_carlo_reproducible_and_varies_between_seeds():
    config = scenario()
    experiment = MonteCarloConfig(runs=4, seed=42, position_std=1, speed_std=1)
    first = run_monte_carlo(config, experiment)
    assert first == run_monte_carlo(config, experiment)
    assert first != run_monte_carlo(config, experiment.model_copy(update={"seed": 43}))
    assert len({run.scenario.simulation.seed for run in first.runs}) == 4
    assert len({run.initial.agents[0].x for run in first.runs}) == 4
    assert config.agents[0].x == 0
    assert first.summary.sample_std_displacement > 0


def test_zero_uncertainty_has_known_displacement_and_zero_spread():
    result = run_monte_carlo(scenario(), MonteCarloConfig(runs=3))
    assert result.summary.mean_displacement == pytest.approx(10)
    assert result.summary.sample_std_displacement == 0
    assert result.summary.min_displacement == result.summary.max_displacement


def test_single_run_has_no_sample_standard_deviation():
    result = run_monte_carlo(scenario(), MonteCarloConfig(runs=1))
    assert result.summary.sample_std_displacement is None


@pytest.mark.parametrize("kwargs", [{"runs": 0}, {"speed_std": -1}, {"position_std": float("nan")}])
def test_invalid_experiment_is_rejected(kwargs):
    with pytest.raises(ValidationError):
        MonteCarloConfig(**kwargs)


def test_cli_writes_experiment_json(tmp_path):
    output = tmp_path / "result.json"
    assert (
        main(
            [
                "scenarios/contested.yaml",
                "--runs",
                "3",
                "--experiment-seed",
                "42",
                "--speed-std",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert len(data["runs"]) == 3
    assert data["experiment"]["seed"] == 42
    assert data["runs"][0]["final"]["agents"][2]["affiliation"] == "hostile"


def test_cli_rejects_experiment_options_without_runs(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["scenarios/basic.yaml", "--speed-std", "1"])
    assert exc.value.code == 2
    assert "require --runs" in capsys.readouterr().err


def test_cli_reports_missing_scenario(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "missing.yaml")])
    assert exc.value.code == 2
    assert "mssa:" in capsys.readouterr().err
