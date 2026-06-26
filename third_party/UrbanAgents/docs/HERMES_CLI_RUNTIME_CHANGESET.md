# Hermes CLI and Runtime Changeset Status

Date: 2026-05-05

Branch: `paper4/hermes-cli-runtime-upgrade`

Validation: `C:/Users/18029/.conda/envs/urban-mobility/python.exe -m pytest` passed with 85 tests.

## Purpose

This branch turns UrbanAgent from a research pipeline with a CLI wrapper into a more mature agent framework experience, using Hermes Agent as an implementation reference.
The main upgrade is not to copy Hermes internals, but to adapt its operational patterns for urban science: a session-oriented shell, slash commands, runtime ledgers, checkpoint visibility, progressive tool disclosure, and cleaner provider/tool execution surfaces.

## Change Groups

### 1. Hermes-style CLI and shell interaction

Files:

- `urban_agent/cli.py`
- `pyproject.toml`
- `tests/test_cli.py`

Purpose:

- Adds `prompt-toolkit` and `rich` as CLI dependencies.
- Adds a centralized slash-command registry similar to Hermes's command registry.
- Adds Hermes-style shell affordances: `/commands`, `/tools`, `/runtime`, `/status`, `/new`, `/mode`, `/bbox`, `/input`, and `/output`.
- Adds shell aliases such as `/help -> /commands`, `/tools -> /capabilities`, and `/reset -> /new`.
- Adds shell history, autocomplete, session id, mode-aware prompt, richer banner, status panels, and runtime-summary panels.
- Suppresses noisy third-party startup logs so help and JSON output remain clean.
- Removes benchmark-style `--task-type` routing from `analyze`, `plan`, `shell`, and legacy wrapper paths. The CLI now passes the natural-language task directly to PlannerAgent.

### 2. Runtime ledger and checkpointed execution

Files:

- `urban_agent/agents/runtime.py`
- `urban_agent/agents/manager.py`
- `urban_agent/agents/__init__.py`
- `urban_agent/__init__.py`
- `tests/test_hermes_runtime_upgrade.py`
- `docs/HERMES_RUNTIME_UPGRADE.md`

Purpose:

- Adds `RuntimeLedger` for session-scoped todos, checkpoint records, selected tool-surface snapshots, and runtime events.
- Wires `HumanCheckpointAgent` into the actual `ManagerAgent` execution path.
- Records DP-1 task scoping plus role-specific checkpoints for perception, analysis, cartography, and reporting.
- Allows guided-mode checkpoint callbacks to block a subtask and records the decision in structured output.
- Exposes runtime summary under `results["runtime"]` and in CLI run summaries.

### 3. Method-level capability disclosure and feedback memory

Files:

- `urban_agent/capabilities.py`
- `urban_agent/feedback_memory.py`
- `urban_agent/agents/planner.py`
- `urban_agent/agents/orchestrator.py`
- `urban_agent/agents/workers.py`
- `tests/test_capabilities.py`
- related additions in `tests/test_cli.py` and `tests/test_public_api.py`

Purpose:

- Adds a method-level capability registry that separates urban-analysis methods from backend implementations.
- Supports progressive disclosure: level 0 index, level 1 capability cards, level 2 invocation schemas, and level 3 full tool definitions.
- Feeds selected capabilities into PlannerAgent and worker contexts.
- Adds reusable feedback lessons for data authority, GIS audit layers, and rerun/correction memory.
- Keeps the framework generic rather than hardcoding local case-study logic into the core.
- Replaces `task_category` with `workflow_profile=adaptive_urban_analysis` in planner/runtime metadata so tasks are planned from the prompt instead of classified into benchmark categories.
- Removes the CityBench evaluator source modules and benchmark answer-normalization capability from the active package/tool surface.

### 4. Model client and tool-call robustness

Files:

- `.env.example`
- `urban_agent/llm/deepseek_client.py`
- `urban_agent/llm/kimi_client.py`
- `urban_agent/mcp_tools.py`
- `tests/test_deepseek_client.py`

Purpose:

- Updates DeepSeek defaults for `deepseek-v4-pro` thinking mode and preserves reasoning content during tool-call loops.
- Adds Kimi coding-client preference and fallback to the standard Kimi client.
- Exposes MCP tools in OpenAI-compatible function-calling format.
- Adds tool-handler maps so model clients can execute selected MCP tools through structured tool calls.
- Adds `urban_agent.tools.agent_toolkit`, a Hermes-inspired core agent tool surface for UrbanAgent: web search/extract, terminal/process, file read/write/patch/search, browser action requests, vision/image requests, skills, todo, memory, session search, clarify, code execution, delegation, cron, messaging, Home Assistant, and kanban coordination.
- Keeps `plugins.hermes` as a compatibility wrapper while making the general tool surface part of UrbanAgent's own `tools` package.
- Keeps external or risky tools gated: terminal/code/file-write/process-control actions return dry-run or enablement records unless the corresponding UrbanAgent environment flag is set.

### 5. Observable runtime and QGIS-oriented artifacts

Files:

- `urban_agent/runtime_observatory.py`
- `tests/test_runtime_observatory.py`

Purpose:

- Adds safer local-case routing so generic heritage requests are not accidentally hijacked by the Ningbo old-bund case.
- Adds QGIS live-command generation for generic layer stacks.
- Adds a `qgis_live_commands` artifact to observable runs.
- Makes artifact production more consistent with the framework's reviewable-output design.
- Observable runtime routing is now `planner_driven`; it no longer infers an internal task type from keywords.

### 6. Public documentation and paper-support artifacts

Files:

- `README.md`
- `figures/urbanagent_framework_workflow_current.png`
- `figures/urbanagent_task_grounding_evidence_current.png`
- `figures/urbanagent_review_quality_memory_current.png`

Purpose:

- Documents method-level capability disclosure and updated provider settings.
- Adds current framework figures referenced by the CEUS draft.
- These figures support the paper narrative rather than the runtime mechanics directly.

## Current State

- The branch exists and is active: `paper4/hermes-cli-runtime-upgrade`.
- The codebase is test-clean with 85 passing tests in the `urban-mobility` conda environment.
- CLI help and JSON commands now produce clean output without third-party startup log pollution.
- `urban-agent analyze --help` exposes only task, bbox, input, output, interaction mode, and run name. No task-type flag remains on the primary user path.
- The changes are still uncommitted; they are ready for review and can be split into commits by the change groups above.

## Suggested Commit Split

1. `feat(cli): add Hermes-style UrbanAgent shell interaction`
2. `feat(runtime): add checkpointed runtime ledger to manager execution`
3. `feat(capabilities): add progressive method capability registry`
4. `feat(llm): harden DeepSeek and Kimi tool-call clients`
5. `feat(observability): add QGIS layer-stack runtime artifacts`
6. `docs(paper4): document Hermes runtime upgrade and current figures`
