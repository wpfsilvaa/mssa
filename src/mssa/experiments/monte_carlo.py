"""Sequential Monte Carlo baseline with independent worlds and random streams."""

from dataclasses import asdict, dataclass, field, fields
from math import hypot
from random import Random
from statistics import fmean, stdev
from typing import Annotated

from pydantic import Field

from mssa.application.run import RunResult, run_scenario
from mssa.communications.model import NetworkMetrics
from mssa.scenarios.schema import Configuration, NonNegative, ScenarioConfig


class MonteCarloConfig(Configuration):
    runs: Annotated[int, Field(strict=True, gt=0)] = 100
    seed: Annotated[int, Field(strict=True, ge=0)] = 0
    position_std: NonNegative = 0.0
    speed_std: NonNegative = 0.0


@dataclass(frozen=True)
class MonteCarloSummary:
    mean_displacement: float
    sample_std_displacement: float | None
    min_displacement: float
    max_displacement: float
    mission_runs: int = 0
    successful_missions: int = 0
    success_rate: float | None = None
    runs_with_detection: int = 0
    mean_first_detection_time: float | None = None
    mean_completion_time: float | None = None
    network: NetworkMetrics = field(default_factory=NetworkMetrics)


@dataclass(frozen=True)
class MonteCarloResult:
    scenario: ScenarioConfig
    experiment: MonteCarloConfig
    runs: tuple[RunResult, ...]
    summary: MonteCarloSummary

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "scenario": self.scenario.model_dump(mode="json"),
            "experiment": self.experiment.model_dump(mode="json"),
            "runs": [run.to_dict() for run in self.runs],
            "summary": asdict(self.summary)
            | {
                "network": self.summary.network.to_dict(),
            },
        }


def run_monte_carlo(scenario: ScenarioConfig, experiment: MonteCarloConfig) -> MonteCarloResult:
    """Perturb x/y and motion speed independently; negative samples become zero.

    The experiment seed determines each run seed and its separate sampling seed.
    Position samples are unbounded, matching the current motion model.
    For policy-controlled agents, perturb the policy's commanded speed.
    """
    seeds = Random(experiment.seed)
    results = []
    displacements = []
    for _ in range(experiment.runs):
        run_seed = seeds.getrandbits(63)
        samples = Random(seeds.getrandbits(63))
        data = scenario.model_dump(mode="json")
        data["simulation"]["seed"] = run_seed
        for agent in data["agents"]:
            agent["x"] += samples.gauss(0, experiment.position_std)
            agent["y"] += samples.gauss(0, experiment.position_std)
            motion = agent["policy"] if agent.get("policy") is not None else agent
            motion["speed"] = max(0.0, motion["speed"] + samples.gauss(0, experiment.speed_std))
        result = run_scenario(ScenarioConfig.model_validate(data))
        results.append(result)
        distances = [
            hypot(final.x - initial.x, final.y - initial.y)
            for initial, final in zip(result.initial.agents, result.final.agents, strict=True)
        ]
        displacements.append(fmean(distances) if distances else 0.0)
    missions = [result.mission for result in results if result.mission is not None]
    first_detections = [
        mission.first_detection_time
        for mission in missions
        if mission.first_detection_time is not None
    ]
    completions = [
        mission.completion_time for mission in missions if mission.completion_time is not None
    ]
    network_totals = {
        item.name: sum(getattr(result.network, item.name) for result in results)
        for item in fields(NetworkMetrics)
    }
    return MonteCarloResult(
        scenario=scenario,
        experiment=experiment,
        runs=tuple(results),
        summary=MonteCarloSummary(
            mean_displacement=fmean(displacements),
            sample_std_displacement=stdev(displacements) if len(displacements) > 1 else None,
            min_displacement=min(displacements),
            max_displacement=max(displacements),
            mission_runs=len(missions),
            successful_missions=len(completions),
            success_rate=len(completions) / len(missions) if missions else None,
            runs_with_detection=len(first_detections),
            mean_first_detection_time=fmean(first_detections) if first_detections else None,
            mean_completion_time=fmean(completions) if completions else None,
            network=NetworkMetrics(**network_totals),
        ),
    )
