from dataclasses import dataclass


@dataclass
class Environment:
    width: float
    height: float
    time: float = 0.0

    def advance(self, dt: float) -> None:
        if dt <= 0:
            raise ValueError("dt must be greater than zero")

        self.time += dt
