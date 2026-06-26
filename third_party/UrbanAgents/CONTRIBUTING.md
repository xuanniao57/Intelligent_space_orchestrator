# Contributing to Urban-Hermes

## Development setup

1. Create or activate a Python 3.10+ environment.
2. Install the current package in editable mode:

   ```powershell
   python -m pip install -e .[dev]
   ```

3. Configure a local runtime home:

   ```powershell
   urban-hermes setup
   ```

## Release checks

Before opening a pull request or publishing a release, run:

```powershell
node --check frontend/urban_hermes_route_viewer/app.js
python -m py_compile hermes_urban_agent/urban_hermes/launcher.py
pytest tests/test_hermes_urban_memory_provider.py tests/test_urban_hermes_route_tree_state.py -q
python -m pip install -e . --no-deps --dry-run
```

## Scope boundaries

- Keep the public runtime centered on `hermes_urban_agent/urban_hermes`.
- Keep the browser review surface in `frontend/urban_hermes_route_viewer`.
- Do not reintroduce the retired `urban_agent` package as a public entry point.
- Keep generated experiment outputs, paper drafts, API keys, and local runtime
  folders out of release commits.
- When adding new urban tools, include route-state or review-memory tests when
  the behavior affects planner branches, reviewer decisions, or claim gates.

## Pull request checklist

1. Tests or smoke checks updated.
2. README or runtime docs updated when CLI, frontend, tool, or memory behavior
   changes.
3. No secrets, local machine paths, or large generated experiment artifacts.
4. The release checks above pass locally.
