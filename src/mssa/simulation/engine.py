from dataclasses import dataclass, field

from mssa.agents.model import Agent
from mssa.environment.model import Environment


@dataclass
class Simulation:
    environment: Environment
    agents: list[Agent] = field(default_factory=list)

    def step(self, dt: float) -> None:
        if dt <= 0:
            raise ValueError("dt must be greater than zero")

        for agent in self.agents:
            agent.move(dt)

        self.environment.advance(dt)

    def run(self, duration: float, dt: float) -> None:
        if duration <= 0:
            raise ValueError("duration must be greater than zero")

        if dt <= 0:
            raise ValueError("dt must be greater than zero")

        elapsed = 0.0

        while elapsed < duration:
            step_dt = min(dt, duration - elapsed)

            self.step(step_dt)

            elapsed += step_dt
