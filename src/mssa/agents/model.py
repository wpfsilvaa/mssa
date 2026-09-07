from dataclasses import dataclass
from math import cos, radians, sin


@dataclass
class Agent:
    agent_id: str
    x: float
    y: float
    speed: float = 0.0
    heading: float = 0.0

    def move(self, dt: float) -> None:
        if dt <= 0:
            raise ValueError("dt must be greater than zero")

        angle = radians(self.heading)

        dx = self.speed * cos(angle) * dt
        dy = self.speed * sin(angle) * dt

        self.x += dx
        self.y += dy
