import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest
from pydantic import ValidationError

from mssa.application.run import create_simulation, run_scenario
from mssa.cli import main
from mssa.communications.model import CommunicationLink
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.scenarios.schema import ScenarioConfig


def network_config(**link_changes):
    return ScenarioConfig.model_validate(
        {
            "environment": {"width": 100, "height": 100},
            "simulation": {"duration": 2, "dt": 0.25, "seed": 42},
            "agents": [
                {
                    "id": "sender",
                    "x": 0,
                    "y": 0,
                    "sensors": [
                        {
                            "id": "sensor",
                            "range": 10,
                            "field_of_view": 90,
                            "period": 0.5,
                        }
                    ],
                },
                {"id": "receiver", "x": -5, "y": 0},
                {"id": "target", "x": 5, "y": 0, "affiliation": "hostile"},
                {"id": "unconnected", "x": -4, "y": 1},
            ],
            "communication_links": [
                {
                    "sender_id": "sender",
                    "recipient_id": "receiver",
                    "range": 5,
                    "latency": 0.5,
                    "ttl": 5,
                }
                | link_changes
            ],
        }
    )


def assert_conservation(metrics):
    assert metrics.attempted == (
        metrics.delivered
        + metrics.dropped_out_of_range
        + metrics.dropped_loss
        + metrics.dropped_queue_full
        + metrics.expired
        + metrics.pending
    )


def test_zero_latency_still_requires_later_step_and_preserves_privacy():
    simulation = create_simulation(network_config(latency=0))
    simulation.step(0.25)
    assert simulation.context("receiver").messages == ()
    assert simulation.network_metrics.pending == 1
    simulation.step(0.25)
    context = simulation.context("receiver")
    assert context.observations == ()
    assert len(context.messages) == 1
    message = context.messages[0]
    assert message.sender_id == "sender"
    assert message.sent_at == message.observations[0].measured_at == 0
    assert message.received_at == message.observations[0].available_at == 0.25
    assert simulation.context("sender").observations[0].available_at == 0
    assert "target_id" not in asdict(message.observations[0])
    assert "affiliation" not in asdict(message.observations[0])
    assert simulation.context("unconnected").messages == ()
    assert simulation.context("sender").messages == ()
    with pytest.raises(FrozenInstanceError):
        message.sender_id = "other"
    assert simulation.network_metrics.mean_delivery_latency == 0.25
    assert_conservation(simulation.network_metrics)


def test_latency_is_quantized_to_first_eligible_start_of_step():
    simulation = create_simulation(network_config(latency=0.3))
    simulation.run(0.5, 0.25)
    assert simulation.context("receiver").messages == ()
    simulation.step(0.25)
    assert simulation.context("receiver").messages[0].received_at == 0.5
    assert simulation.network_metrics.mean_delivery_latency == 0.5


def test_delivery_preserves_old_measurement_instead_of_reading_current_target_truth():
    data = network_config(latency=0).model_dump(mode="json")
    data["agents"][2].update(speed=2, heading=0)
    simulation = create_simulation(ScenarioConfig.model_validate(data))
    simulation.run(0.5, 0.25)
    assert simulation.context("receiver").messages[0].observations[0].x == 5
    assert simulation.agents[2].x == 6


def test_affiliation_does_not_override_explicit_link_configuration():
    data = network_config().model_dump(mode="json")
    data["agents"][1]["affiliation"] = "hostile"
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.network.delivered == 3


def test_directed_link_and_range_boundary():
    result = run_scenario(network_config())
    assert result.network.attempted == 4
    assert result.network.delivered == 3
    assert result.network.pending == 1  # Due at endpoint; no implicit drain.
    assert result.network.dropped_out_of_range == 0
    assert result.network.delivery_rate == 0.75
    assert_conservation(result.network)
    result = run_scenario(network_config(range=4.99))
    assert result.network.dropped_out_of_range == 4
    assert result.network.delivered == result.network.pending == 0
    assert_conservation(result.network)


def test_link_breaking_during_transit_discards_message():
    data = network_config(range=6).model_dump(mode="json")
    data["agents"][1].update(speed=10, heading=180)
    simulation = create_simulation(ScenarioConfig.model_validate(data))
    simulation.run(0.75, 0.25)
    assert simulation.network_metrics.enqueued == 1
    assert simulation.network_metrics.dropped_out_of_range == 2
    assert simulation.context("receiver").messages == ()
    assert_conservation(simulation.network_metrics)


def test_queue_capacity_counts_inflight_messages_and_delivery_frees_capacity():
    simulation = create_simulation(network_config(latency=1, queue_capacity=1))
    simulation.run(1, 0.25)
    assert simulation.network_metrics.enqueued == 1
    assert simulation.network_metrics.dropped_queue_full == 1
    simulation.step(0.25)  # Delivery at t=1 precedes the new scan's transmission.
    assert simulation.network_metrics.delivered == 1
    assert simulation.network_metrics.enqueued == 2
    assert simulation.network_metrics.pending == 1
    assert_conservation(simulation.network_metrics)


def test_full_loss_never_delivers_and_does_not_occupy_queue():
    result = run_scenario(network_config(loss_probability=1, queue_capacity=1))
    assert result.network.dropped_loss == result.network.attempted == 4
    assert result.network.enqueued == result.network.pending == result.network.delivered == 0
    assert result.network.mean_delivery_latency is None
    assert_conservation(result.network)


@pytest.mark.parametrize("ttl", [0.25, 0.5])
def test_expiry_precedes_delivery_including_equal_deadline(ttl):
    result = run_scenario(network_config(ttl=ttl))
    assert result.network.delivered == 0
    assert result.network.expired > 0
    assert all(not context.messages for context in result.perceptions)
    assert_conservation(result.network)


def test_received_reports_expire_without_being_counted_as_transmission_losses():
    data = network_config(latency=0.25, ttl=1).model_dump(mode="json")
    data["agents"][0]["sensors"][0]["period"] = 10
    simulation = create_simulation(ScenarioConfig.model_validate(data))
    simulation.run(0.5, 0.25)
    assert simulation.context("receiver").messages
    simulation.run(0.5, 0.25)
    assert simulation.context("receiver").messages == ()
    assert simulation.network_metrics.delivered == 1
    assert simulation.network_metrics.expired == 0


def test_empty_scan_is_sent_and_replaces_previous_received_report():
    simulation = create_simulation(network_config(latency=0))
    simulation.run(0.5, 0.25)
    assert simulation.context("receiver").messages[0].observations
    simulation.agents[2].x = 50
    simulation.run(0.5, 0.25)
    assert len(simulation.context("receiver").messages) == 1
    assert simulation.context("receiver").messages[0].observations == ()
    assert simulation.network_metrics.delivered == 2


def test_receiving_does_not_relay_messages_or_generate_new_transmissions():
    data = network_config(latency=0).model_dump(mode="json")
    data["communication_links"].append(
        {
            "sender_id": "receiver",
            "recipient_id": "unconnected",
            "range": 10,
        }
    )
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.network.attempted == 4
    assert result.perceptions[3].messages == ()


def test_same_sensor_ids_from_different_senders_remain_separate():
    data = network_config(latency=0).model_dump(mode="json")
    data["agents"][3]["sensors"] = [{"id": "sensor", "range": 10}]
    data["communication_links"].append(
        {
            "sender_id": "unconnected",
            "recipient_id": "receiver",
            "range": 10,
        }
    )
    result = run_scenario(ScenarioConfig.model_validate(data))
    messages = result.perceptions[1].messages
    assert {message.sender_id for message in messages} == {"sender", "unconnected"}
    assert len(messages) == 2


def test_link_stream_is_independent_of_other_links_and_sensing():
    data = network_config(latency=0, loss_probability=0.5).model_dump(mode="json")
    data["agents"][0]["sensors"][0]["position_std"] = 1
    data["simulation"]["duration"] = 10
    original = create_simulation(ScenarioConfig.model_validate(data))
    data["communication_links"].append(
        {
            "sender_id": "sender",
            "recipient_id": "unconnected",
            "range": 10,
            "loss_probability": 0.5,
        }
    )
    data["communication_links"].reverse()
    extended = create_simulation(ScenarioConfig.model_validate(data))
    for _ in range(40):
        original.step(0.25)
        extended.step(0.25)
        assert original.context("receiver") == extended.context("receiver")
        assert original.context("sender") == extended.context("sender")


class InvalidMotion:
    def propagate(self, agent, world, dt, rng):
        rng.random()
        return replace(agent, x=float("nan"))


@pytest.mark.parametrize("steps_before,loss", [(0, 0.5), (1, 0), (2, 0.5)])
def test_failed_step_rolls_back_transmissions_deliveries_rng_and_counters(steps_before, loss):
    config = network_config(latency=0, loss_probability=loss)
    simulation, fresh = create_simulation(config), create_simulation(config)
    for _ in range(steps_before):
        simulation.step(0.25)
        fresh.step(0.25)
    dynamics = simulation.dynamics
    simulation.dynamics = InvalidMotion()
    with pytest.raises(ValueError):
        simulation.step(0.25)
    assert simulation.network_metrics == fresh.network_metrics
    assert simulation.contexts() == fresh.contexts()
    simulation.dynamics = dynamics
    simulation.run(2, 0.25)
    fresh.run(2, 0.25)
    assert simulation.network_metrics == fresh.network_metrics
    assert simulation.contexts() == fresh.contexts()


def test_continued_run_preserves_network_state():
    config = network_config(loss_probability=0.3)
    continuous, continued = create_simulation(config), create_simulation(config)
    continuous.run(2, 0.25)
    continued.run(1, 0.25)
    continued.run(1, 0.25)
    assert continuous.network_metrics == continued.network_metrics
    assert continuous.contexts() == continued.contexts()


@pytest.mark.parametrize(
    "changes",
    [
        {"range": 0},
        {"latency": -1},
        {"ttl": 0},
        {"queue_capacity": 0},
        {"queue_capacity": 1.5},
        {"queue_capacity": True},
        {"loss_probability": -0.1},
        {"loss_probability": 1.1},
        {"latency": float("nan")},
        {"range": float("inf")},
        {"recipient_id": "unknown"},
        {"sender_id": "unknown"},
        {"recipient_id": "sender"},
    ],
)
def test_invalid_links_are_rejected(changes):
    with pytest.raises(ValidationError):
        network_config(**changes)


def test_duplicate_links_are_rejected():
    data = network_config().model_dump(mode="json")
    data["communication_links"] *= 2
    with pytest.raises(ValidationError, match="unique"):
        ScenarioConfig.model_validate(data)


def test_runtime_link_validates_direct_python_use():
    with pytest.raises(ValueError):
        CommunicationLink("a", "b", 10, ttl=-1)


def test_no_network_keeps_contexts_empty_and_metrics_unset():
    data = network_config().model_dump(mode="json")
    data["communication_links"] = []
    result = run_scenario(ScenarioConfig.model_validate(data))
    assert result.network.attempted == 0
    assert result.network.delivery_rate is result.network.mean_delivery_latency is None
    assert all(not context.messages for context in result.perceptions)


def test_monte_carlo_aggregates_counts_and_weighted_latency_reproducibly():
    config = network_config(loss_probability=0.5)
    experiment = MonteCarloConfig(runs=100, seed=42)
    batch = run_monte_carlo(config, experiment)
    assert batch == run_monte_carlo(config, experiment)
    metrics = batch.summary.network
    assert metrics.attempted == 400
    assert 140 < metrics.dropped_loss < 260
    assert metrics.delivered == sum(run.network.delivered for run in batch.runs)
    assert metrics.mean_delivery_latency == 0.5
    assert metrics.delivery_rate == metrics.delivered / 400
    assert_conservation(metrics)


def test_cli_exports_network_results(tmp_path):
    output = tmp_path / "communication.json"
    assert main(["scenarios/communication.yaml", "--runs", "3", "--output", str(output)]) == 0
    data = json.loads(output.read_text())
    assert data["summary"]["network"]["attempted"] == 72
    assert data["runs"][0]["perceptions"][3]["messages"] == []
    assert "delivery_rate" in data["runs"][0]["network"]
