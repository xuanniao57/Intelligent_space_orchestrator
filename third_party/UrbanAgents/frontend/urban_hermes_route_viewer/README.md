# Urban-Hermes Route Workspace

Static runtime viewer for Urban-Hermes route-tree state.
It is designed as the browser-side companion to the CLI: the CLI continues the dialogue and writes state files, while this page renders a readable workspace for review.

The release layout is intentionally sparse for paper screenshots and live review:

- left: selected node, required inputs, artifacts, time-space-people meaning, and claim boundary;
- upper right: typed planner route tree with selected, candidate, deferred, blocked, and merge states;
- lower right: a CLI-like mirror of the same route state, todo items, human choices, patch events, and artifacts.

Benchmark tables and long workflow rails are kept in the code path but hidden from the default workspace so the core review interface remains readable.

## Open with live experiment data

From `D:/GitHub_1/world_agent/urban-mobility-agent/paper4_urban_svgagent/`:

```powershell
python scripts/start_urban_agent_workspace.py --toolsets urban,todo,memory,delegation
```

This starts the static frontend, opens the Urban Agent workspace, and then
launches the Urban-Hermes CLI with the same frontend port. If you only need the
viewer without the CLI, run the static server directly:

```powershell
python -m http.server 8017
```

Then open:

```text
http://localhost:8017/frontend/urban_hermes_route_viewer/index.html
```

To open a live Urban-Hermes route-tree state exported by `urban_route_tree`, pass the state file as a query parameter:

```text
http://localhost:8017/frontend/urban_hermes_route_viewer/index.html?state=experiments/case2_typed_route_tree_rerun_20260524/route_tree_frontend_state.json
```

The CLI-side route-tree tool writes this URL in its return payload as `frontend_url`.
Use the Refresh button to reload the latest route state, or enable Auto refresh during an Urban-Hermes run.

This mode reads:

- `experiments/case2_typed_route_tree_rerun_20260524/typed_route_tree.json`
- `experiments/case2_typed_route_tree_rerun_20260524/route_tree_frontend_state.json` when `?state=...` is supplied
- `experiments/case2_typed_route_tree_rerun_20260524/workflow_trace.json`
- `experiments/case2_typed_route_tree_rerun_20260524/branch_comparison.json`
- `experiments/urbanworkflowbench_60tasks_20260524/condition_traces/all60_design_gate_20260524/condition_trace_score_summary.json`
- `experiments/urbanworkflowbench_60tasks_20260524/condition_traces/all60_design_gate_20260524/full/all60_design_gate_decisions.csv`

## What the workspace shows

- A curved, node-link route tree with selected, candidate, deferred, blocked, and merge states.
- Clickable nodes. The detail panel shows required inputs, method parameters, expected outputs, attached artifacts, time/space/people assumptions, and claim boundaries.
- A CLI-synchronized terminal mirror for planner todo, route choice requests, patch events, and recorded human choices.
- A selected-node artifact panel for maps, plots, tables, manifests, review records, and claim boundaries.
- Hidden support panels for selected-route rails and benchmark tables when a debugging view is needed.

## Notes

The viewer is intentionally plain black-and-white for paper screenshots.
It has no package install step and does not rerun Urban-Hermes.
It only reads state and artifact files written by the runtime.
