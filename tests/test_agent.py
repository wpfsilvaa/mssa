import pytest

from mssa.agents.model import Agent


def test_agent_creation():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
        speed=10,
        heading=0,
    )

    assert agent.agent_id == "A01"
    assert agent.x == 100
    assert agent.y == 200
    assert agent.speed == 10
    assert agent.heading == 0


def test_agent_moves_east():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
        speed=10,
        heading=0,
    )

    agent.move(2)

    assert agent.x == pytest.approx(120)
    assert agent.y == pytest.approx(200)


def test_agent_moves_north():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
        speed=10,
        heading=90,
    )

    agent.move(2)

    assert agent.x == pytest.approx(100)
    assert agent.y == pytest.approx(220)


def test_agent_moves_west():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
        speed=10,
        heading=180,
    )

    agent.move(2)

    assert agent.x == pytest.approx(80)
    assert agent.y == pytest.approx(200)


def test_agent_moves_south():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
        speed=10,
        heading=270,
    )

    agent.move(2)

    assert agent.x == pytest.approx(100)
    assert agent.y == pytest.approx(180)


def test_agent_rejects_invalid_timestep():
    agent = Agent(
        agent_id="A01",
        x=100,
        y=200,
    )

    with pytest.raises(ValueError):
        agent.move(0)
