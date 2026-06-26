# Hermes Urban Agent Adapter

This folder is the Urban-Hermes runtime carried inside the UrbanAgents
repository branch. It vendors the Hermes agent runtime under the MIT license,
registers UrbanAgent analysis tools, and presents the user-facing CLI as
Urban Agents while keeping runtime memory and generated artifacts local.

The adapter implements the three paper gaps as Hermes-native extensions:

- Step 1: `urban_hermes.tools` registers an `urban` toolset with Hermes `tools.registry`.
- Step 2: `urban_ground_task` and `urban_review` expose input grounding and review routing.
- Step 3: `urban_hermes.memory_provider` implements a single Hermes `MemoryProvider` that internally composes feedback, place, research-design, urban-method, and tool-artifact memory.

## Install for collaborators

Use Python 3.11 or newer. From a fresh checkout:

```powershell
cd paper4_urban_svgagent
python -m pip install -e .
urban-hermes setup
```

Then fill in your provider API key when prompted, or edit the generated
`.urban-agent/urban_hermes/.env` file. A separate `hermes-agent` checkout is
not required; UrbanAgents includes the vendored runtime used by `urban-hermes`.

## Start the interactive CLI

From the `paper4_urban_svgagent` repository root:

```powershell
urban-hermes --toolsets urban,todo,memory
```

This enters the Urban Agents CLI after registering the `urban` toolset.
Type your task at the Urban Agents prompt, for example:

```text
Assess walkability in Le Marais and review evidence gaps before giving recommendations.
```

To start the browser workspace and CLI together, use the repository helper:

```powershell
python scripts/start_urban_agent_workspace.py --toolsets urban,todo,memory,delegation
```

The helper serves the frontend at `http://localhost:8017`, opens the Urban Agent
route workspace, and then launches the same Urban-Hermes CLI in the terminal.
During a run, `urban_route_tree` writes `route_tree_frontend_state.json` and
returns a matching `frontend_url`, so the browser and CLI inspect the same
route-state file.

For one-shot mode, pass the query directly:

```powershell
urban-hermes "Assess walkability in Le Marais and review evidence gaps" --toolsets urban,todo,memory
```

On Windows, Hermes-Urban filters upstream generic `file` and `terminal` toolsets
by default even if they are requested, because upstream Hermes executes them via
Git Bash. Use `urban_host_fs`, `urban_host_python`, and `urban_qgis_process` for
native `D:/...` paths and QGIS artifacts. Pass `--allow-wsl-tools` only when you
explicitly want the upstream Git-Bash/WSL-style tools.

## Quick smoke test

From the repository root:

```powershell
urban-hermes-dogfood
```

The smoke test prints a JSON diagnostic report.
It uses synthetic OSM-like data by default so it works without network access.

Expected minimum signal from a passing run:

- 17 registered urban tools.
- `grounding_status` is `grounded` or `grounded_with_gaps`.
- `review_recommendation` is `accept` or `accept_with_warnings` for the fixture.
- `research_memory_hit` is `true` for the built-in research-design cue store.
- `memory_recall_hit` is `true` after the feedback write.
- `host_fs_hit` and `host_python_hit` are `true` for native host execution.

## Non-interactive and QGIS runs

For scripted experiments, prefer plain/quiet mode so Hermes does not route
output through `prompt_toolkit`:

```powershell
urban-hermes "..." --quiet --plain --toolsets urban,todo,memory
```

If the run must execute shell/GIS commands without interactive approval prompts,
add `--yolo` for that process:

```powershell
urban-hermes "..." --quiet --plain --yolo --toolsets urban,todo,memory
```

Use the `urban_qgis_process` tool for real QGIS Processing artifacts. It wraps
`qgis_process`, writes a JSONL command log when `output_dir` or `log_path` is
provided, and verifies GeoJSON outputs with feature counts. Use `urban_host_fs`
to list/read native files and `urban_host_python` for small Windows-native
preparation scripts when QGIS Processing alone is not enough.

Use `urban_qgis_workspace` after a GIS-heavy run to package loose layers into a
QGIS workbench: source layers, derived metric layers, `.qgz/.qgs`, README, and
`spatial_reasoning_manifest.json` for later agent reasoning.

For mechanism ablations, remove registered Urban-Hermes tools at CLI startup
instead of relying on prompt-only instructions:

```powershell
urban-hermes --toolsets urban,todo,memory --disable-urban-tool urban_ground_task
urban-hermes --toolsets urban,todo,memory --disable-urban-tool urban_review
```

The resulting session is still a normal Urban-Hermes CLI session; the selected
tool is absent from `--list-tools` and cannot be called by the agent.

## Launch Hermes with the explicit launcher

```powershell
urban-hermes --toolsets urban,todo,memory
```

The launcher imports `urban_hermes.bootstrap` before entering the vendored runtime, so the dynamic `urban` toolset is visible to the toolset resolver.

## Install the Hermes memory bridge

This creates a small `urban_memory` bridge under the active Hermes home plugin directory.

```powershell
python -m urban_hermes.install_plugin
```

The bridge uses the vendored runtime by default. Set `URBAN_HERMES_HERMES_ROOT`
only when intentionally testing against an external Hermes checkout.

Then set `memory.provider: urban_memory` in `.urban-agent/urban_hermes/config.yaml` if you want the normal memory-provider discovery path to load it automatically.

## Programmatic use

```python
from urban_hermes.bootstrap import bootstrap

names = bootstrap()
print(names)

from tools.registry import registry
print(registry.dispatch("urban_ground_task", {"task": "Assess walkability in Le Marais"}))
```

## Hermes memory plugin shape

Hermes allows only one external memory provider at a time.
Use `UrbanMemoryProvider`, which combines the Urban-Hermes stores behind one provider.

Urban-Hermes memory is organized along two axes:

- Temporal scope: `working` memory is session/context memory loaded by Hermes and may decay through compaction; `reflective` memory is cross-session knowledge promoted from references, review failures, or human corrections.
- Content layer: `research_design` stores problem-data-algorithm cards with temporal, spatial, and population descriptors; `urban_method` stores urban/spatial/social analysis conventions and scientific cautions; `tool_artifact` stores concrete software, algorithm, file-format, and artifact-validation procedures; `place_case` indexes context to specific places or projects; `feedback_correction` stores reusable human/reviewer corrections.

The implemented loading order is progressive: Hermes base context first; compact `research_design`/`urban_method`, place, and feedback cards before planning; only an index of matching `tool_artifact` cards during prefetch; full tool-artifact procedures are retrieved later with `urban_research_memory(content_layers=["tool_artifact"])` by execution or review subtasks; reviewed corrections are promoted after the run.

```python
from agent.memory_manager import MemoryManager
from urban_hermes.memory_provider import UrbanMemoryProvider

manager = MemoryManager()
provider = UrbanMemoryProvider()
provider.initialize("dogfood-session")
manager.add_provider(provider)
```
