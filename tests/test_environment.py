import pytest

from mssa.environment.model import Environment


def test_environment_creation():
    environment = Environment(width=1000, height=1000)

    assert environment.width == 1000
    assert environment.height == 1000
    assert environment.time == 0.0


def test_environment_time_advances():
    environment = Environment(width=1000, height=1000)

    environment.advance(0.5)

    assert environment.time == 0.5


def test_environment_rejects_invalid_timestep():
    environment = Environment(width=1000, height=1000)

    with pytest.raises(ValueError):
        environment.advance(0)
