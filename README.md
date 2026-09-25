# MSSA

## Mission Simulation & Systems Analysis

MSSA is an experimental modeling and simulation framework for
studying autonomous multi-agent systems.

The project focuses on:

- Modeling autonomous agents
- Sensor uncertainty
- Communication constraints
- Navigation
- Monte Carlo simulation
- Mission-level metrics
- Systems analysis
- Trade-space exploration

## Objectives

Build a reproducible 2D simulation of multi-agent missions with uncertain
observations and constrained communication, supporting Monte Carlo experiments,
system trade-space analysis and optimization.

## Architecture

The [architecture document](docs/architecture.md) describes module boundaries,
the simulation lifecycle, sensors, communication, opposing systems, Monte Carlo
experiments and the implementation roadmap (in Portuguese).

Implemented: validated YAML scenarios, configurable motion models, immutable
snapshots, seeded execution, friendly/hostile/neutral affiliations, a CLI and
sequential Monte Carlo with initial position and speed uncertainty. Geometric
sensors support range, field of view, sampling period, detection probability and
position noise. Agents receive isolated, anonymous observations. Observation
missions report target detection times and success; batches aggregate mission metrics.
Directed communication links share sensor reports with range limits, latency,
random loss, bounded in-flight queues and expiry. Network metrics are exported per
run and aggregated across Monte Carlo batches.

Patrol and reaction policies use only local observations and delivered messages.
A local dashboard provides a 2D map, sensor/network ranges, message traffic and
scenario editing. Routing, bandwidth models, tracking and obstacles remain planned.
Sensors and policies follow the same rules for every affiliation. Motion is
unbounded 2D kinematics with instantaneous heading and speed changes.

## Dashboard

From the repository root, with the project dependencies installed:

```bash
PYTHONPATH=src .venv/bin/python -m mssa.dashboard
```

Open **http://127.0.0.1:8765** and choose `patrol_reaction.yaml`. The dashboard supports:

- Play, pause, step, reset and playback speed.
- Sensor sectors, communication ranges, trajectories and message events.
- Agent, sensor, directed-link and mission editors.
- Patrol waypoints drawn on the map and configurable approach/avoid/hold reactions.
- Scenario creation, YAML/JSON import, YAML export and local draft persistence.
- A selected agent's local perception, separate from the analyst's world view.

Apply edits to restart the simulation with the new configuration. The installed
`mssa-dashboard` command is equivalent. See the [dashboard and policy guide](docs/dashboard.md).
The first dashboard runs one scenario at a time; Monte Carlo remains available via the CLI.

## Run locally

Requires Python 3.12 or later.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m mssa scenarios/basic.yaml
python -m mssa scenarios/contested.yaml --output result.json
```

Run an experiment with independent initial position and speed perturbations:

```bash
python -m mssa scenarios/contested.yaml --runs 100 --experiment-seed 42 --position-std 10 --speed-std 1 --output experiment.json
```

Position uncertainty is in meters and speed uncertainty is in m/s. Negative
sampled speeds are clamped to zero. For agents with a policy, speed uncertainty
varies `policy.speed`; otherwise it varies initial speed. The experiment seed controls per-run seeds.
JSON results include effective configurations, initial/final snapshots, final
local perceptions and mission results when configured. Mean net displacement
remains available for scenarios without a mission.

## Observation missions

The example includes two friendly observers, an opposing patrol with its own
sensor, and a stationary opposing system:

```bash
python -m mssa scenarios/observation.yaml --output observation.json
python -m mssa scenarios/observation.yaml --runs 100 --experiment-seed 42 --output detection-experiment.json
```

Even without initial-state perturbations, probabilistic sensors produce varying
outcomes across runs. The mission succeeds when designated observers collectively
detect every required target at least once. Every run still covers its full
configured duration; incomplete missions report `timeout`.

Sensors sample at the start of eligible steps, including time zero and excluding
the final endpoint. Local perception contains only each sensor's latest scan,
with timestamps and no true target identity or affiliation. Mission reports use
truth associations for scoring. They do not imply agents share detections.

Batch `success_rate` includes all mission runs. `mean_first_detection_time` is
conditional on runs with a detection; `mean_completion_time` is conditional on
successful runs. Missing times are `null`, not zero. See the
[observation guide](docs/observation.md) for configuration and timing semantics.

## Communication

```bash
python -m mssa scenarios/communication.yaml --output communication.json
python -m mssa scenarios/communication.yaml --runs 100 --experiment-seed 42 --output communication-batch.json
```

Each fresh sensor scan is sent over the sender's explicitly configured outgoing
links. Received reports appear in the recipient's `messages`; its own sensor
measurements remain in `observations`. There is no automatic team broadcast or relay.
Even zero-latency messages arrive in a later step. Undelivered messages remain
pending when the configured duration ends.

Results distinguish losses due to range, random drops, queue capacity and expiry.
The existing observation mission still scores local detections, independently of
message delivery. Reaction policies can use delivered reports to change movement. See the
[communication guide](docs/communication.md) for queue, TTL and metric definitions.

The installed `mssa` command accepts the same arguments. From an uninstalled
checkout with dependencies available, use `PYTHONPATH=src python -m mssa ...`.

```python
from mssa.application.run import run_scenario
from mssa.experiments.monte_carlo import MonteCarloConfig, run_monte_carlo
from mssa.scenarios.loader import load_config

scenario = load_config("scenarios/contested.yaml")
result = run_scenario(scenario)
batch = run_monte_carlo(scenario, MonteCarloConfig(runs=100, seed=42, speed_std=1))
```

## Development

```bash
python -m pytest -q
ruff check .
ruff format --check .
node --check src/mssa/dashboard/static/app.js
```

The optional browser smoke test is `node tests/dashboard_smoke.mjs`, with the
dashboard running, a recent Node version and Chromium available. Runtime dashboard
usage itself does not require Node or browser automation dependencies.

Early development — v0.1.0. Existing `load_scenario`, `Agent.move` and
`Simulation.run` entry points remain available.
Use `load_config` with `create_simulation` or `run_scenario` to load sensors,
missions and communications; the legacy `load_scenario` returns only the physical world.
