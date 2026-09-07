import pytest

from mssa.agents.model import Agent
from mssa.environment.model import Environment
from mssa.simulation.engine import Simulation


def test_simulation_step_updates_agents_and_time():
    environment = Environment(width=1000, height=1000)

    agent = Agent(
        agent_id="agent-1",
        x=0,
        y=0,
        speed=10,
        heading=0,
    )

    simulation = Simulation(
        environment=environment,
        agents=[agent],
    )

    simulation.step(1.0)

    assert environment.time == pytest.approx(1.0)
    assert agent.x == pytest.approx(10.0)
    assert agent.y == pytest.approx(0.0)


def test_simulation_run():
    environment = Environment(width=1000, height=1000)

    agent = Agent(
        agent_id="agent-1",
        x=0,
        y=0,
        speed=10,
        heading=0,
    )

    simulation = Simulation(
        environment=environment,
        agents=[agent],
    )

    simulation.run(duration=2.0, dt=0.5)

    assert environment.time == pytest.approx(2.0)
    assert agent.x == pytest.approx(20.0)


def test_simulation_run_handles_partial_final_step():
    environment = Environment(width=1000, height=1000)

    agent = Agent(
        agent_id="agent-1",
        x=0,
        y=0,
        speed=10,
        heading=0,
    )

    simulation = Simulation(
        environment=environment,
        agents=[agent],
    )

    simulation.run(duration=1.0, dt=0.3)

    assert environment.time == pytest.approx(1.0)
    assert agent.x == pytest.approx(10.0)


def test_simulation_rejects_invalid_step():
    environment = Environment(width=1000, height=1000)

    simulation = Simulation(environment=environment)

    with pytest.raises(ValueError):
        simulation.step(0)


def test_simulation_rejects_invalid_duration():
    environment = Environment(width=1000, height=1000)

    simulation = Simulation(environment=environment)

    with pytest.raises(ValueError):
        simulation.run(duration=0, dt=0.1)
