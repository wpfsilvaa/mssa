from pathlib import Path

import yaml

from mssa.agents.model import Agent
from mssa.environment.model import Environment
from mssa.scenarios.schema import ScenarioConfig


def load_config(path: str | Path) -> ScenarioConfig:
    """Read and validate a scenario before creating any runtime objects."""
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return ScenarioConfig.model_validate(data)


def build_world(config: ScenarioConfig) -> tuple[Environment, list[Agent]]:
    """Create a fresh world on every call, including repeated experiments."""
    environment = Environment(
        width=config.environment.width,
        height=config.environment.height,
    )
    agents = [
        Agent(
            agent_id=agent.id,
            x=agent.x,
            y=agent.y,
            speed=agent.speed,
            heading=agent.heading,
            affiliation=agent.affiliation,
        )
        for agent in config.agents
    ]
    return environment, agents


def load_scenario(path: str | Path) -> tuple[Environment, list[Agent]]:
    """Legacy physical-world API; use load_config/create_simulation for full scenarios."""
    return build_world(load_config(path))
