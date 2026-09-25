from dataclasses import replace

import pytest
from pydantic import ValidationError

from mssa.application.run import create_simulation
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.perception.model import AgentContext, Observation
from mssa.policies.model import PolicySpec, PolicyState
from mssa.scenarios.schema import ScenarioConfig
from mssa.simulation.state import AgentState


def config(loss=0):
    return ScenarioConfig.model_validate(
        {
            "environment": {"width": 100, "height": 100},
            "agents": [
                {
                    "id": "observer",
                    "x": 0,
                    "y": 0,
                    "sensors": [{"id": "forward", "range": 20, "field_of_view": 90}],
                },
                {
                    "id": "receiver",
                    "x": -10,
                    "y": 0,
                    "policy": {"kind": "react", "speed": 2, "reaction_distance": 100},
                },
                {"id": "target", "x": 10, "y": 0, "affiliation": "hostile"},
            ],
            "communication_links": [
                {
                    "sender_id": "observer",
                    "recipient_id": "receiver",
                    "range": 100,
                    "latency": 0.5,
                    "loss_probability": loss,
                }
            ],
        }
    )


def test_patrol_does_not_overshoot_and_stops_at_end_of_nonloop_route():
    data = config().model_dump(mode="json")
    data["agents"][1]["policy"] = {
        "kind": "patrol",
        "speed": 100,
        "loop": False,
        "waypoints": [{"x": 0, "y": 0}, {"x": 0, "y": 10}],
    }
    simulation = create_simulation(ScenarioConfig.model_validate(data))
    simulation.step(1)
    assert simulation.agents[1].x == pytest.approx(0)
    simulation.step(1)
    assert simulation.agents[1].y == pytest.approx(10)
    simulation.step(1)
    assert simulation.agents[1].speed == 0
    assert simulation.policy_states["receiver"].mode == "idle"


def test_loop_patrol_returns_to_first_waypoint():
    policy = PolicySpec("patrol", speed=10, waypoints=((10, 0), (0, 0)), loop=True)
    context = AgentContext(AgentState("a", 0, 0, 0, 0), 0, ())
    first = policy.decide(context, PolicyState(), 1)
    second = policy.decide(
        replace(context, own_state=replace(context.own_state, x=10)), first.state, 1
    )
    third = policy.decide(context, second.state, 1)
    assert first.state.waypoint_index == third.state.waypoint_index == 0
    assert second.heading == 180


def test_reaction_cannot_see_truth_and_waits_for_message_delivery():
    simulation = create_simulation(config())
    simulation.run(0.5, 0.25)
    assert simulation.agents[1].x == -10
    simulation.step(0.25)
    assert simulation.agents[1].x == pytest.approx(-9.5)
    assert simulation.policy_states["receiver"].mode == "react_approach"


def test_network_loss_changes_reaction_behavior():
    simulation = create_simulation(config(loss=1))
    simulation.run(2, 0.25)
    assert simulation.agents[1].x == -10
    assert simulation.policy_states["receiver"].mode == "idle"


def test_agent_can_disable_reaction_to_received_messages():
    data = config().model_dump(mode="json")
    data["agents"][1]["policy"]["use_messages"] = False
    simulation = create_simulation(ScenarioConfig.model_validate(data))
    simulation.run(2, 0.25)
    assert simulation.agents[1].x == -10
    assert simulation.context("receiver").messages


@pytest.mark.parametrize(
    "reaction,speed,heading", [("approach", 2, 0), ("avoid", 2, 180), ("hold", 0, 0)]
)
def test_reactions_use_measured_position(reaction, speed, heading):
    policy = PolicySpec("react", speed=2, reaction=reaction)
    observation = Observation("measurement", "sensor", 0, 0, 10, 0, 0)
    context = AgentContext(AgentState("a", 0, 0, 0, 0), 0, (observation,))
    decision = policy.decide(context, PolicyState(), 1)
    assert decision.speed == speed
    assert decision.heading == heading


@pytest.mark.parametrize("time,available,x", [(6, 0, 10), (0, 1, 10), (0, 0, 1000)])
def test_stale_unavailable_or_distant_contact_falls_back_to_route(time, available, x):
    policy = PolicySpec("react", speed=2, waypoints=((0, 10),))
    observation = Observation("measurement", "sensor", 0, available, x, 0, 0)
    context = AgentContext(AgentState("a", 0, 0, 0, 0), time, (observation,))
    decision = policy.decide(context, PolicyState(), 1)
    assert decision.state.mode == "patrol"
    assert decision.heading == 90


class InvalidMotion:
    def propagate(self, agent, world, dt, rng):
        return replace(agent, x=float("nan"))


def test_failure_does_not_commit_policy_or_event_state():
    simulation = create_simulation(config())
    before = simulation.policy_states
    simulation.dynamics = InvalidMotion()
    with pytest.raises(ValueError):
        simulation.step(1)
    assert simulation.policy_states == before
    assert simulation.network_events == ()
    assert simulation.pending_messages == ()


def test_patrol_requires_waypoints_in_scenario():
    data = config().model_dump(mode="json")
    data["agents"][1]["policy"] = {"kind": "patrol"}
    with pytest.raises(ValidationError, match="waypoint"):
        ScenarioConfig.model_validate(data)


def test_monte_carlo_varies_policy_speed_instead_of_overridden_initial_speed():
    data = config().model_dump(mode="json")
    data["simulation"] = {"duration": 1, "dt": 0.25}
    data["agents"][1]["policy"] = {"kind": "patrol", "speed": 10, "waypoints": [{"x": 100, "y": 0}]}
    scenario = ScenarioConfig.model_validate(data)
    experiment = MonteCarloConfig(runs=4, seed=42, speed_std=1)
    batch = run_monte_carlo(scenario, experiment)
    assert len({run.scenario.agents[1].policy.speed for run in batch.runs}) == 4
    assert len({run.final.agents[1].x for run in batch.runs}) == 4
    assert scenario.agents[1].policy.speed == 10
    assert batch == run_monte_carlo(scenario, experiment)
