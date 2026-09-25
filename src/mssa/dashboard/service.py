from dataclasses import asdict, dataclass
from math import ulp
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

import yaml

from mssa.application.run import create_simulation
from mssa.scenarios.schema import ScenarioConfig
from mssa.simulation.engine import Simulation


def validate_scenario(data: dict | str) -> ScenarioConfig:
    config = ScenarioConfig.model_validate(yaml.safe_load(data) if isinstance(data, str) else data)
    if len(config.agents) > 100 or len(config.communication_links) > 500:
        raise ValueError("O dashboard suporta até 100 agentes e 500 enlaces por cenário.")
    if sum(len(agent.sensors) for agent in config.agents) > 200:
        raise ValueError("O dashboard suporta até 200 sensores por cenário.")
    if sum(len(agent.policy.waypoints) for agent in config.agents if agent.policy) > 5000:
        raise ValueError("O dashboard suporta até 5000 pontos de rota por cenário.")
    if any(link.queue_capacity > 1000 for link in config.communication_links):
        raise ValueError("No dashboard, cada fila pode conter até 1000 mensagens.")
    return config


@dataclass
class Session:
    config: ScenarioConfig
    simulation: Simulation
    accessed_at: float


class DashboardService:
    def __init__(self, scenario_directory: Path):
        self.scenario_directory = scenario_directory
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()

    def examples(self) -> list[dict]:
        examples = []
        for path in sorted(self.scenario_directory.glob("*.yaml")):
            try:
                config = validate_scenario(path.read_text(encoding="utf-8"))
                examples.append({"name": path.name, "scenario": config.model_dump(mode="json")})
            except (OSError, ValueError, yaml.YAMLError):
                continue
        return examples

    def create(self, data: dict | str, replace_id: str | None = None) -> dict:
        config = validate_scenario(data)
        simulation = create_simulation(config)
        with self._lock:
            now = monotonic()
            self._sessions = {
                key: session
                for key, session in self._sessions.items()
                if now - session.accessed_at < 3600 and key != replace_id
            }
            if len(self._sessions) >= 32:
                raise ValueError(
                    "Limite de sessões atingido. Feche sessões antigas ou reinicie o servidor."
                )
            session_id = uuid4().hex
            self._sessions[session_id] = Session(config, simulation, now)
            return {
                "session_id": session_id,
                "scenario": config.model_dump(mode="json"),
                **self._state(self._sessions[session_id]),
            }

    def step(self, session_id: str, steps: int = 1) -> dict:
        if type(steps) is not int or not 1 <= steps <= 100:
            raise ValueError("steps deve ser um inteiro entre 1 e 100.")
        with self._lock:
            session = self._sessions[session_id]
            session.accessed_at = monotonic()
            events = []
            for _ in range(steps):
                remaining = session.config.simulation.duration - session.simulation.environment.time
                if remaining <= 4 * ulp(session.config.simulation.duration):
                    break
                session.simulation.step(min(session.config.simulation.dt, remaining))
                events.extend(asdict(event) for event in session.simulation.network_events)
            return self._state(session) | {"events": events}

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    @staticmethod
    def _state(session: Session) -> dict:
        sim = session.simulation
        finished = session.config.simulation.duration - sim.environment.time <= 4 * ulp(
            session.config.simulation.duration
        )
        return {
            "world": asdict(sim.snapshot()),
            "contexts": [asdict(context) for context in sim.contexts()],
            "policies": {key: asdict(state) for key, state in sim.policy_states.items()},
            "network": sim.network_metrics.to_dict(),
            "pending_messages": [asdict(message) for message in sim.pending_messages],
            "events": [],
            "mission": asdict(sim.mission.result(finished=finished)) if sim.mission else None,
            "total_scans": sim.total_scans,
            "total_detections": sim.total_detections,
            "finished": finished,
        }
