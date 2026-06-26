# Urban-Hermes

Urban-Hermes is the current release implementation of Urban Agent: a Hermes-based
runtime for reviewable urban-analysis workflows.

It combines an interactive CLI, urban analysis tools, stage-triggered research
memory, worker-reviewer delegation, and a browser route workspace that makes
planning choices, artifacts, review records, and claim boundaries inspectable.

> Current release: `urban-hermes-v0.2.0`
>
> The legacy `urban_agent` package has been retired from the public release
> surface. Use `urban-hermes` or the compatibility alias `urban-agent`, both of
> which launch the Urban-Hermes runtime.

## What is included

- `hermes_urban_agent/urban_hermes/`: the Urban-Hermes runtime package.
- `hermes_urban_agent/urban_hermes/_vendor/hermes_runtime/`: vendored Hermes
  runtime used by this release, so a separate Hermes checkout is not required.
- `frontend/urban_hermes_route_viewer/`: static browser workspace for route
  trees, node artifacts, review records, and a CLI mirror.
- `scripts/start_urban_agent_workspace.py`: helper that serves the frontend and
  launches the CLI against the same route-state files.
- `tests/test_hermes_urban_memory_provider.py` and
  `tests/test_urban_hermes_route_tree_state.py`: release smoke and mechanism
  tests for the current runtime.

## Install

Use Python 3.10+.

```powershell
git clone https://github.com/xuanniao57/UrbanAgents.git
cd UrbanAgents
python -m pip install -e .
urban-hermes setup
```

`urban-hermes setup` creates a project-local runtime home under
`.urban-agent/urban_hermes/`. Fill in the provider key in the generated `.env`
file, or set the relevant environment variables before launching.

## Start the CLI

```powershell
urban-hermes --toolsets urban,todo,memory,delegation --yolo
```

The CLI banner should show:

- `Urban-Hermes runtime`
- enabled toolsets such as `urban`, `todo`, `memory`, and `delegation`
- urban tools such as `urban_ground_task`, `urban_review`,
  `urban_route_tree`, `urban_host_fs`, and `urban_host_python`

One-shot mode is also supported:

```powershell
urban-hermes "Assess street vitality drivers using the prepared data canvas" --toolsets urban,todo,memory,delegation --plain --compact --max-turns 60
```

## Start the browser route workspace

From the repository root:

```powershell
python scripts/start_urban_agent_workspace.py --toolsets urban,todo,memory,delegation
```

The helper serves:

```text
http://localhost:8017/frontend/urban_hermes_route_viewer/index.html
```

When a run writes a `route_tree_frontend_state.json`, open it with:

```text
http://localhost:8017/frontend/urban_hermes_route_viewer/index.html?state=experiments/<run>/route_tree_frontend_state.json
```

The workspace is arranged for live review and paper screenshots:

- left: selected node, required inputs, artifacts, time-space-people meaning,
  and claim boundary;
- upper right: typed planner route tree with selected, candidate, deferred,
  blocked, and merge states;
- lower right: CLI-style mirror of route choices, todo status, worker-review
  events, patch events, and artifacts.

## Key runtime ideas

Urban-Hermes is designed for urban research workflows where the final answer is
not enough. The system records how a task becomes a route tree, how route nodes
depend on data and methods, what each worker produced, what reviewers checked,
and which claims are allowed, downgraded, deferred, or blocked.

The current implementation focuses on:

- route-state management for branch selection, dependencies, and merge gates;
- planner-level review of research meaning, especially time, space, and people
  assumptions;
- worker-reviewer validation of method fit, artifact readiness, file/schema
  quality, and claim boundaries;
- stage-triggered memory retrieval for research-design, method, execution, and
  repair knowledge;
- Windows-native host tools for filesystem, Python, and GIS-oriented execution.

## Validation

Recommended release checks:

```powershell
node --check frontend/urban_hermes_route_viewer/app.js
python -m py_compile hermes_urban_agent/urban_hermes/launcher.py
pytest tests/test_hermes_urban_memory_provider.py tests/test_urban_hermes_route_tree_state.py -q
python -m pip install -e . --no-deps --dry-run
```

Expected install dry-run output includes:

```text
Would install urban-hermes-0.2.0
```

## Repository status

This repository now publishes Urban-Hermes as the active Urban Agent
implementation. Older prototype packages, legacy benchmark scaffolds, and
paper-specific experiment artifacts are not part of the public release surface.
