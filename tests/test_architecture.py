from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import ValidationError

from mssa.agents.model import Agent
from mssa.application.run import create_simulation, run_scenario
from mssa.environment.model import Environment
from mssa.scenarios.loader import load_config
from mssa.scenarios.schema import ScenarioConfig
from mssa.simulation.engine import Simulation


def scenario_data():
    return {
        "environment": {"width": 100, "height": 100},
        "agents": [{"id": "a", "x": 0, "y": 0, "speed": 2}],
        "simulation": {"duration": 1, "dt": 0.1, "seed": 42},
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": 2},
        {"unexpected": True},
        {"environment": {"width": 0, "height": 1}},
        {"simulation": {"dt": float("nan")}},
        {"simulation": {"duration": float("inf")}},
        {"agents": [{"id": "a", "x": 0, "y": 0}] * 2},
        {"agents": [{"id": "a", "x": 0, "y": 0, "affiliation": "unknown"}]},
    ],
)
def test_invalid_scenario_is_rejected(patch):
    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(scenario_data() | patch)


def test_empty_yaml_is_rejected(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_snapshots_are_immutable_and_worlds_are_isolated():
    config = ScenarioConfig.model_validate(scenario_data())
    first, second = create_simulation(config), create_simulation(config)
    before = first.snapshot()
    first.step(1)
    assert before.agents[0].x == second.agents[0].x == 0
    assert first.agents[0].x == 2
    with pytest.raises(FrozenInstanceError):
        before.agents[0].x = 7


def test_run_returns_metadata_and_no_spurious_final_tick():
    result = run_scenario(ScenarioConfig.model_validate(scenario_data()))
    assert result.final.tick == 10
    assert result.final.time == pytest.approx(1)
    assert result.final.agents[0].x == pytest.approx(2)
    assert result.to_dict()["scenario"]["simulation"]["seed"] == 42


class FollowFirstAgent:
    def propagate(self, agent, world, dt, rng):
        return replace(agent, x=world.agents[0].x + 1)


def test_all_agents_observe_same_start_of_tick_world():
    simulation = Simulation(
        Environment(100, 100),
        [Agent("a", 0, 0), Agent("b", 10, 0)],
        dynamics=FollowFirstAgent(),
    )
    simulation.step(1)
    assert [agent.x for agent in simulation.agents] == [1, 1]


class RandomMotion:
    def propagate(self, agent, world, dt, rng):
        return replace(agent, x=agent.x + rng.random())


class FailingMotion:
    def propagate(self, agent, world, dt, rng):
        x = rng.random()
        return replace(agent, x=x if agent.agent_id == "a" else float("nan"))


def test_failed_step_preserves_world_and_random_stream():
    simulation = Simulation(
        Environment(100, 100),
        [Agent("a", 0, 0), Agent("b", 0, 0)],
        seed=42,
        dynamics=FailingMotion(),
    )
    before = simulation.snapshot()
    with pytest.raises(ValueError):
        simulation.step(1)
    assert simulation.snapshot() == before
    simulation.dynamics = RandomMotion()
    fresh = Simulation(
        Environment(100, 100),
        [Agent("a", 0, 0), Agent("b", 0, 0)],
        seed=42,
        dynamics=RandomMotion(),
    )
    simulation.step(1)
    fresh.step(1)
    assert simulation.snapshot() == fresh.snapshot()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_nonfinite_or_nonpositive_runtime_parameters_are_rejected(value):
    simulation = Simulation(Environment(100, 100))
    with pytest.raises(ValueError):
        simulation.step(value)
    with pytest.raises(ValueError):
        simulation.run(value, 1)
    with pytest.raises(ValueError):
        simulation.run(1, value)


def test_hostile_affiliation_survives_run():
    result = run_scenario(load_config("scenarios/contested.yaml"))
    assert result.final.agents[2].affiliation == "hostile"
