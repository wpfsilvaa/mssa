"""Thin CLI adapter; simulation behavior lives in application/domain modules."""

import argparse
import json
from pathlib import Path

import yaml

from mssa.application.run import run_scenario
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.scenarios.loader import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MSSA mission simulation")
    parser.add_argument("scenario", type=Path, help="YAML scenario file")
    parser.add_argument("--output", type=Path, help="Write the JSON result to this file")
    parser.add_argument("--runs", type=int, help="Run a Monte Carlo experiment")
    parser.add_argument("--experiment-seed", type=int, default=None)
    parser.add_argument("--position-std", type=float, default=None, help="Position sigma in meters")
    parser.add_argument("--speed-std", type=float, default=None, help="Speed sigma in m/s")
    args = parser.parse_args(argv)
    if args.runs is None and any(
        value is not None for value in (args.experiment_seed, args.position_std, args.speed_std)
    ):
        parser.error("Monte Carlo options require --runs")
    try:
        scenario = load_config(args.scenario)
        if args.runs is None:
            result = run_scenario(scenario)
        else:
            experiment = MonteCarloConfig(
                runs=args.runs,
                seed=args.experiment_seed if args.experiment_seed is not None else 0,
                position_std=args.position_std if args.position_std is not None else 0,
                speed_std=args.speed_std if args.speed_std is not None else 0,
            )
            result = run_monte_carlo(scenario, experiment)
        payload = json.dumps(result.to_dict(), indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(payload, end="")
        else:
            args.output.write_text(payload, encoding="utf-8")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(2, f"mssa: {exc}\n")
    return 0
