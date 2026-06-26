# Hermes Runtime Upgrade Notes

Reference studied: `NousResearch/hermes-agent`, shallow clone at commit `c5b4c48`.

## What Hermes contributes

Hermes is useful in real tasks because its agent loop is surrounded by operational infrastructure, not because it only has more agent roles.
The main reusable patterns are:

1. A session-scoped todo ledger that decomposes long tasks, preserves active work after context compression, and makes progress auditable.
2. A central tool registry where tools self-register with schema, handler, toolset, availability checks, result limits, and dispatch metadata.
3. Checkpoint and approval infrastructure around risky or user-visible operations.
4. Isolated subagents with restricted toolsets and their own execution state.
5. Persistent session traces, memory prefetch, skill progressive disclosure, and background self-improvement review.
6. Multiple runtime surfaces over one core loop: CLI, TUI, gateway, cron, webhook, and ACP.

## UrbanAgent adaptation

UrbanAgent already had the urban-science side of the framework: Planning, Manager execution, Perception, Analyst, Cartographer, Reporter, Review Hub, Quality Controller, capability disclosure, and evidence manifests.
The missing piece was a task-runtime substrate that makes the framework usable during longer real city-analysis runs.

This upgrade adds `urban_agent.agents.runtime.RuntimeLedger` and wires it into `ManagerAgent`.
The ledger records:

- `todos`: one item per planned subtask, with agent, dependencies, status, timestamps, errors, and produced artifact markers.
- `checkpoints`: DP-1 task scoping plus role-specific DP checkpoints for perception, analysis, cartography, and reporting.
- `tool_surface`: selected capabilities from the progressive capability registry.
- `events`: compact runtime events for initialization, subtask starts/completions/failures, and checkpoint decisions.

The existing `HumanCheckpointAgent` is now part of the real Manager execution path.
In `supervisory` and `autonomous` modes it remains non-blocking; in `guided` mode a callback can block or revise a decision.
Blocking actions such as `reject`, `revise`, `stop`, `cancel`, or `pause` now stop the affected stage and are reflected in the runtime ledger.

## Why this matters for real urban analysis

Real urban tasks usually involve data authority checks, spatial representation choices, map-layer packaging, and final narrative interpretation.
These are not just model responses; they are operational decisions that need a durable trace.
The new runtime ledger makes those decisions visible and testable without tying UrbanAgent to Hermes internals.

## Next upgrade targets

The next Hermes-derived pieces should be added incrementally:

1. Convert `UrbanMCPTools` into a self-registering registry with availability checks and role-aware dispatch.
2. Add shadow-checkpoint snapshots before file or GIS artifact mutation.
3. Add reusable urban-analysis skills loaded by progressive disclosure, parallel to the existing capability cards.
4. Add cron/webhook task triggers for repeated city monitoring workflows.
5. Persist runtime ledgers into the memory module so successful procedures become strategy memory.
