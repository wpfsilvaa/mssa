from pathlib import Path

import yaml

from mssa.agents.model import Agent
from mssa.environment.model import Environment


def load_scenario(path: str | Path) -> tuple[Environment, list[Agent]]:
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    environment_data = data["environment"]

    environment = Environment(
        width=environment_data["width"],
        height=environment_data["height"],
    )

    agents = []

    for agent_data in data["agents"]:
        agent = Agent(
            agent_id=agent_data["id"],
            x=agent_data["x"],
            y=agent_data["y"],
            speed=agent_data["speed"],
            heading=agent_data["heading"],
        )

        agents.append(agent)

    return environment, agents
