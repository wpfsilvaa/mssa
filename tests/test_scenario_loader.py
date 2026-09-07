from pathlib import Path

import pytest

from mssa.scenarios.loader import load_scenario


def test_load_scenario():
    scenario_path = Path("scenarios/basic.yaml")

    environment, agents = load_scenario(scenario_path)

    assert environment.width == 1000
    assert environment.height == 1000
    assert environment.time == 0.0

    assert len(agents) == 2

    assert agents[0].agent_id == "agent-1"
    assert agents[0].x == pytest.approx(100)
    assert agents[0].y == pytest.approx(100)

    assert agents[1].agent_id == "agent-2"
    assert agents[1].x == pytest.approx(500)
    assert agents[1].y == pytest.approx(500)
