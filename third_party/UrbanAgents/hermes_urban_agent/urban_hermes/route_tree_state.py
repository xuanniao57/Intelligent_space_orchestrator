"""Generic route-tree state manager for Urban-Hermes.

The route tree is a planner-owned research design object. It records typed
branches, user decisions, worker/reviewer patches, and artifact links in a
form that both the CLI and a browser viewer can inspect.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROUTE_NODE_TYPES = {
    "research_object",
    "feature_package",
    "data_preparation",
    "model_execution",
    "model_explanation",
    "diagnostic",
    "route_comparison",
    "claim_synthesis",
    "report_option",
}

ROUTE_STATUSES = {
    "candidate",
    "suggested",
    "waiting_choice",
    "pending",
    "approved",
    "active",
    "selected",
    "completed",
    "merged",
    "deferred",
    "blocked",
    "revised",
    "triggered_not_validated",
    "not_validated",
    "failed",
}

MAIN_ROUTE_ROLES = {"main", "selected_main", "primary", "primary_route", "main_path"}
SIDE_ROUTE_ROLES = {"side", "completed_branch", "branch_evidence", "comparison_input"}
MERGE_NODE_TYPES = {"route_comparison", "report_option", "claim_synthesis"}
ACTIVE_ROUTE_STATUSES = {"approved", "active", "selected", "completed", "merged"}
SUGGESTED_STATUSES = {"candidate", "suggested", "waiting_choice", "pending", "revised"}
REVIEWABLE_NODE_TYPES = {
    "research_object",
    "feature_package",
    "data_preparation",
    "model_execution",
    "model_explanation",
    "diagnostic",
    "route_comparison",
    "claim_synthesis",
}
WORKER_REQUIRED_NODE_TYPES = {
    "research_object",
    "feature_package",
    "data_preparation",
    "model_execution",
    "model_explanation",
    "diagnostic",
}
PLAN_REVIEW_RECORD_KEYS = {
    "plan_review_record",
    "planner_review_record",
    "plan_level_review",
    "urban_plan_review",
}
PLAN_DECISION_KEYS = {
    "human_plan_decision",
    "plan_approval",
    "human_plan_approval",
}

PATCH_TYPES = {
    "add_node",
    "add_branch",
    "update_node",
    "update_status",
    "add_edge",
    "attach_artifact",
    "request_human_choice",
    "merge_branches",
    "revise_dependency",
    "add_report_option",
    "sync_trace",
}

ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", {}, []):
        return []
    if isinstance(value, list):
        return value
    return [value]


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value).strip())[:80] or "node"


def _choice_decision(raw: dict[str, Any]) -> tuple[str, str]:
    value = raw.get("decision") if "decision" in raw else raw.get("choice")
    reason = raw.get("reason") or ""
    if isinstance(value, dict):
        reason = reason or value.get("reason") or value.get("status_reason") or ""
        value = value.get("decision") or value.get("choice") or value.get("status")
    return str(value or "").lower().strip(), str(reason or "")


def state_paths(run_dir: str | Path) -> dict[str, Path]:
    base = Path(run_dir).expanduser()
    return {
        "run_dir": base,
        "state": base / "route_tree_state.json",
        "events": base / "route_tree_events.jsonl",
        "frontend": base / "route_tree_frontend_state.json",
        "visual": base / "route_tree_visual_spec.json",
        "choice": base / "human_choice_request.md",
    }


def _node_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node.get("node_id")): node for node in state.get("nodes", []) if isinstance(node, dict)}


def _step_order(step_id: Any) -> int:
    text = str(step_id or "")
    if text.startswith("S"):
        digits = "".join(ch for ch in text[1:3] if ch.isdigit())
        if digits:
            return int(digits)
    fallback = {
        "research_object": 1,
        "feature_package": 2,
        "data_preparation": 2,
        "model_execution": 3,
        "model_explanation": 4,
        "diagnostic": 4,
        "route_comparison": 5,
        "report_option": 5,
        "claim_synthesis": 6,
    }
    return fallback.get(text, 99)


def _node_step(node: dict[str, Any]) -> int:
    return _step_order(node.get("step_id") or _default_step(str(node.get("node_type") or "")))


def _route_role(node: dict[str, Any]) -> str:
    return str(
        node.get("route_role")
        or node.get("selection_role")
        or node.get("branch_role")
        or ""
    ).lower().strip()


def _is_main_node(node: dict[str, Any]) -> bool:
    role = _route_role(node)
    return bool(node.get("main_route") is True or node.get("main_path") is True or role in MAIN_ROUTE_ROLES)


def _is_side_evidence(node: dict[str, Any]) -> bool:
    role = _route_role(node)
    return bool(role in SIDE_ROUTE_ROLES or str(node.get("status") or "") in {"merged"})


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str).lower()
    except TypeError:
        return str(value).lower()


def _load_json_reference(value: Any, *, run_dir: str | Path) -> Any:
    """Load a JSON object from a dict/list or from a run-relative path."""

    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(run_dir) / path
    if not path.exists() or path.stat().st_size > 10_000_000:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _record_node_ids(record: Any, nodes: dict[str, dict[str, Any]]) -> list[str]:
    """Find route-tree nodes named in a worker/reviewer/trace record."""

    if record in (None, "", [], {}):
        return []
    ids: list[str] = []
    if isinstance(record, dict):
        for key in (
            "node_id",
            "branch_id",
            "node",
            "approved_branch",
            "deferred_branch",
            "blocked_branch",
            "artifact",
        ):
            for item in _as_list(record.get(key)):
                if str(item) in nodes:
                    ids.append(str(item))
        for key in ("approved_nodes", "deferred_nodes", "blocked_nodes", "approved_steps", "deferred_steps", "blocked_steps", "artifacts"):
            for item in _as_list(record.get(key)):
                if str(item) in nodes:
                    ids.append(str(item))
    text = json.dumps(record, ensure_ascii=False, default=str) if not isinstance(record, str) else record
    # Exact id containment is enough for ids such as RO_Y1+FP_X3 and
    # ME_RF+EX_SHAP+DIAG_RESID without requiring a case-specific parser.
    for node_id in nodes:
        if node_id and node_id in text:
            ids.append(node_id)
    return list(dict.fromkeys(ids))


def _existing_review_path(name: str, *, run_dir: str | Path) -> str | None:
    """Resolve common review-record filename drift without hiding failures."""

    if not name:
        return None
    direct = Path(name)
    if not direct.is_absolute():
        direct = Path(run_dir) / name
    if direct.exists():
        return str(direct)
    # Some runs name the readiness review by stage instead of by selected
    # branch. Keep this generic by matching the stage prefix before the first
    # branch id.
    stem = Path(name).stem
    prefix = stem.split("_RO_")[0].split("_FP_")[0]
    candidates = sorted(Path(run_dir).glob(f"{prefix}*.json")) if prefix else []
    return str(candidates[0]) if candidates else None


def _first_present_mapping(state: dict[str, Any], keys: set[str]) -> Any:
    for key in keys:
        value = state.get(key)
        if value not in (None, "", [], {}):
            return value
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    for key in keys:
        value = meta.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _plan_decision_issues(state: dict[str, Any]) -> list[str]:
    if state.get("plan_gate_not_applicable_reason"):
        return []
    record = _first_present_mapping(state, PLAN_DECISION_KEYS)
    if record in (None, "", [], {}):
        return ["plan gate missing: human_plan_decision/plan_approval"]
    text = _json_text(record)
    issues: list[str] = []
    if isinstance(record, dict):
        shown = record.get("plan_was_shown") is True or record.get("visible_to_user") is True
    else:
        shown = False
    if not shown and not any(term in text for term in ("shown", "visible", "presented", "rendered", "cli")):
        issues.append("plan gate does not state that the plan was shown before execution")
    if not any(term in text for term in ("approve", "approved", "revise", "revision", "block", "blocked", "continue", "proceed")):
        issues.append("plan gate does not record approve, revise, block, continue, or proceed")
    return issues


def _plan_review_issues(state: dict[str, Any]) -> list[str]:
    if state.get("plan_review_not_applicable_reason"):
        return []
    record = _first_present_mapping(state, PLAN_REVIEW_RECORD_KEYS)
    if record in (None, "", [], {}):
        return ["plan-level review missing: plan_review_record/planner_review_record"]
    text = _json_text(record)
    if isinstance(record, dict):
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        if result.get("passed") is True or record.get("passed") is True:
            return []
    if any(term in text for term in ("passed", "pass", "proceed", "accept", "approved", "sound", "complete")):
        return []
    return ["plan-level review does not record a pass/proceed/accept decision"]


def _completed_execution_requires_plan_gate(state: dict[str, Any]) -> bool:
    nodes = state.get("nodes", [])
    return any(
        isinstance(node, dict)
        and node.get("status") in {"completed", "merged"}
        and node.get("node_type") in WORKER_REQUIRED_NODE_TYPES.union(MERGE_NODE_TYPES)
        for node in nodes
    )


def _review_status_issues(node_id: str, node: dict[str, Any]) -> list[str]:
    record = (
        node.get("reviewer_record")
        or node.get("review_record")
        or node.get("planner_review_record")
        or node.get("review_decision")
    )
    if record in (None, "", [], {}):
        return [f"{node_id}: completed node is missing a reviewer/planner-review record."]
    text = _json_text(record)
    if any(term in text for term in ("pending", "todo", "not reviewed", "awaiting")):
        return [f"{node_id}: review record is still pending."]
    if any(term in text for term in ("failed", "reject", "rejected", "hard_failure", "hard failures")) and not any(
        term in text for term in ("resolved", "repaired", "accepted_after", "proceed")
    ):
        return [f"{node_id}: review record contains unresolved failure/rejection."]
    return []


def _branch_like_state(state: dict[str, Any]) -> bool:
    branch_tree = state.get("branch_tree") if isinstance(state.get("branch_tree"), dict) else {}
    return any(branch_tree.get(key) for key in ("completed_branch", "deferred", "blocked", "suggested"))


def _gate_counts(state: dict[str, Any]) -> dict[str, int]:
    nodes = _node_index(state)
    main_path = [str(item) for item in state.get("main_path") or []]
    artifact_gate_count = 0
    for node in nodes.values():
        for artifact in node.get("artifacts") or []:
            text = _json_text(artifact)
            if "claim_gate" in text or "gate matrix" in text:
                artifact_gate_count += 1
    return {
        "route_comparison_nodes": sum(1 for node in nodes.values() if node.get("node_type") == "route_comparison"),
        "claim_synthesis_nodes": sum(1 for node in nodes.values() if node.get("node_type") == "claim_synthesis"),
        "route_comparison_on_main_path": sum(1 for node_id in main_path if nodes.get(node_id, {}).get("node_type") == "route_comparison"),
        "claim_synthesis_on_main_path": sum(1 for node_id in main_path if nodes.get(node_id, {}).get("node_type") == "claim_synthesis"),
        "claim_gate_artifacts": artifact_gate_count,
    }


def _design_basis_present(node: dict[str, Any]) -> bool:
    return bool(
        node.get("memory_sources")
        or node.get("design_basis")
        or node.get("source_memory")
        or node.get("branch_not_applicable_reason")
    )


def _early_branch_design_warnings(state: dict[str, Any]) -> list[str]:
    """Warn when early research-design branches are too thin for model tasks.

    This remains a generic route-tree check: it does not force a specific case
    template, but it asks the planner to either expose alternatives or explain
    why the data contract only supports one operationalization.
    """

    nodes = list(_node_index(state).values())
    task_text = _json_text(state.get("meta", {})).lower()
    model_like = any(node.get("node_type") in {"model_execution", "model_explanation"} for node in nodes)
    exploratory_like = model_like or any(node.get("node_type") == "feature_package" for node in nodes)
    if not exploratory_like:
        return []

    research_objects = [node for node in nodes if node.get("node_type") == "research_object"]
    feature_packages = [node for node in nodes if node.get("node_type") in {"feature_package", "data_preparation"}]
    warnings: list[str] = []
    if len(research_objects) < 2 and not any(node.get("branch_not_applicable_reason") for node in research_objects):
        warnings.append("S1 has fewer than two research_object alternatives; add outcome/spatial/temporal alternatives or record why the data contract supports only one.")
    if len(feature_packages) < 2 and not any(node.get("branch_not_applicable_reason") for node in feature_packages):
        warnings.append("S2 has fewer than two feature_package/data_preparation alternatives; add X-package alternatives or record why only one package is defensible.")

    activity_like = any(term in task_text for term in ("vitality", "lbs", "activity", "pedestrian", "street"))
    if activity_like and len(research_objects) < 3:
        warnings.append("Activity/vitality route tree has fewer than three outcome-design alternatives; consider all-window, weekday/weekend, and day-period branches when fields exist.")
    population_like = any(
        term in task_text
        for term in (
            "population",
            "demographic",
            "social attribute",
            "education",
            "income",
            "age_group",
            "gender",
            "home/work",
            "live_lon",
            "work_lon",
        )
    )
    if activity_like and population_like and not any(
        any(term in _json_text(node) for term in ("population", "demographic", "education", "income", "age_group", "gender", "home/work", "privacy"))
        for node in research_objects
    ):
        warnings.append(
            "Activity/LBS data contract mentions population or social-attribute fields, but S1 has no people-aware aggregation branch with privacy, sampling, and claim-boundary requirements."
        )
    for node in [*research_objects, *feature_packages]:
        if not _design_basis_present(node):
            warnings.append(f"{node.get('node_id')}: early S1/S2 node has no memory_sources/design_basis; record recalled research-design memory or a data-contract-only reason.")
    return warnings


def _default_step(node_type: str) -> str:
    mapping = {
        "research_object": "S1_research_object",
        "feature_package": "S2_variables",
        "data_preparation": "S2_variables",
        "model_execution": "S3_model_route",
        "model_explanation": "S4_explanation_diagnostics",
        "diagnostic": "S4_explanation_diagnostics",
        "route_comparison": "S5_route_comparison",
        "report_option": "S5_route_comparison",
        "claim_synthesis": "S6_claim_synthesis",
    }
    return mapping.get(node_type, "Sx_custom")


def normalize_node(raw: dict[str, Any], *, default_status: str = "suggested") -> dict[str, Any]:
    node = dict(raw)
    node_id = node.get("node_id") or node.get("branch_id") or node.get("id")
    if not node_id:
        node_id = f"{node.get('node_type') or 'node'}_{datetime.now().strftime('%H%M%S%f')}"
    node["node_id"] = _safe_id(str(node_id))
    node_type = str(node.get("node_type") or node.get("type") or "custom").strip()
    node["node_type"] = node_type
    node.setdefault("step_id", _default_step(node_type))
    node.setdefault("question", node.get("title") or node.get("description") or node["node_id"])
    node["depends_on"] = [str(item) for item in _as_list(node.get("depends_on") or node.get("parent_nodes") or node.get("parents"))]
    node["required_inputs"] = _as_list(node.get("required_inputs"))
    node["required_parameters"] = node.get("required_parameters") or {}
    node["expected_outputs"] = _as_list(node.get("expected_outputs") or node.get("outputs") or node.get("expected_artifacts"))
    node["artifacts"] = _as_list(node.get("artifacts"))
    node.setdefault("time_space_people", node.get("meaning_review") or {"time": "", "space": "", "people": ""})
    node.setdefault("claim_boundary", "")
    node.setdefault("status", default_status)
    node.setdefault("route_role", node.get("selection_role") or node.get("branch_role") or "")
    node.setdefault("created_at", _now())
    node["updated_at"] = _now()
    return node


def init_state(
    *,
    run_dir: str | Path,
    task: str,
    nodes: list[dict[str, Any]] | None = None,
    todo_steps: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = state_paths(run_dir)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    normalized_nodes = [normalize_node(node) for node in (nodes or [])]
    state = {
        "schema_version": "urban_route_tree_state_v1",
        "meta": {
            "state_id": f"urt_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "task": task,
            "created_at": _now(),
            "updated_at": _now(),
            "run_dir": str(paths["run_dir"]),
            **(metadata or {}),
        },
        "planner_todo": todo_steps or infer_todo_steps(normalized_nodes),
        "nodes": normalized_nodes,
        "edges": infer_edges(normalized_nodes),
        "active_path": [],
        "main_path": [],
        "patch_events": [],
        "human_choices": [],
        "artifact_index": [],
        "claim_options": [],
        "current_choice_request": None,
    }
    refresh_active_path(state)
    save_state(state, run_dir=run_dir, event=None)
    return state


def infer_todo_steps(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [
        ("S1_research_object", "Research object and outcome definition"),
        ("S2_variables", "Explanatory variable and data-preparation package"),
        ("S3_model_route", "Model route execution"),
        ("S4_explanation_diagnostics", "Model explanation and diagnostics"),
        ("S5_route_comparison", "Route comparison and report-option selection"),
        ("S6_claim_synthesis", "Claim synthesis and calibrated report"),
    ]
    present = {node.get("step_id") for node in nodes}
    return [
        {
            "step_id": step_id,
            "title": title,
            "status": "candidate" if step_id in present else "template",
            "planner_role": "define choices, maintain dependencies, and request human decisions",
        }
        for step_id, title in ordered
    ]


def infer_edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    node_ids = {node["node_id"] for node in nodes}
    for node in nodes:
        for parent in node.get("depends_on", []):
            if parent in node_ids:
                edges.append({"source": parent, "target": node["node_id"], "relation": "depends_on"})
    return edges


def merge_edges(nodes: list[dict[str, Any]], explicit_edges: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Merge dependency-inferred edges with planner-provided edge metadata."""

    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in infer_edges(nodes):
        edge_map[(edge["source"], edge["target"])] = dict(edge)
    for edge in explicit_edges or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        key = (source, target)
        merged = dict(edge_map.get(key, {}))
        merged.update({k: v for k, v in edge.items() if v not in (None, "", [])})
        merged.setdefault("source", source)
        merged.setdefault("target", target)
        merged.setdefault("relation", edge.get("relation") or "depends_on")
        edge_map[key] = merged
    return list(edge_map.values())


def compute_main_path(state: dict[str, Any]) -> list[str]:
    """Return the selected primary route, not every completed branch.

    The planner may execute side branches for comparison, but the visible black
    route in the paper/frontend should remain one dependency-consistent chain.
    An explicit `declared_main_path` or `selected_route` wins when it
    references existing, non-blocked nodes. The exported `main_path` itself is
    recomputed so later patch/choice events can update the black route.
    """
    nodes = _node_index(state)
    explicit_source = state.get("declared_main_path") or state.get("selected_route")
    explicit = [str(item) for item in _as_list(explicit_source)]
    valid_explicit = [
        node_id
        for node_id in explicit
        if node_id in nodes and nodes[node_id].get("status") not in {"blocked", "deferred"}
    ]
    if valid_explicit:
        return sorted(dict.fromkeys(valid_explicit), key=lambda item: (_node_step(nodes[item]), valid_explicit.index(item)))

    main_candidates = [
        node
        for node in nodes.values()
        if _is_main_node(node) and node.get("status") not in {"blocked", "deferred"}
    ]
    if not main_candidates:
        terminal_path = infer_main_path_from_terminal(state)
        if terminal_path:
            return terminal_path
    if not main_candidates:
        main_candidates = [
            node
            for node in nodes.values()
            if node.get("status") in {"selected", "active"}
        ]

    # If the planner only marked nodes as completed, infer conservatively:
    # choose at most one completed node per step, preferring nodes with fewer
    # branch-like dependencies and final synthesis/comparison nodes at S5/S6.
    if not main_candidates:
        completed = [
            node
            for node in nodes.values()
            if node.get("status") in {"completed", "merged"}
            and not _is_side_evidence(node)
            and node.get("status") not in {"blocked", "deferred"}
        ]
        by_step: dict[int, list[dict[str, Any]]] = {}
        for node in completed:
            by_step.setdefault(_node_step(node), []).append(node)
        for step in sorted(by_step):
            step_nodes = sorted(
                by_step[step],
                key=lambda node: (
                    0 if node.get("node_type") in {"claim_synthesis", "route_comparison"} else 1,
                    len(node.get("depends_on", [])),
                    str(node.get("node_id")),
                ),
            )
            main_candidates.append(step_nodes[0])

    ordered = sorted(main_candidates, key=lambda node: (_node_step(node), str(node.get("node_id"))))
    path: list[str] = []
    seen_steps: set[int] = set()
    for node in ordered:
        node_id = str(node.get("node_id"))
        step = _node_step(node)
        if step in seen_steps and node.get("node_type") not in MERGE_NODE_TYPES:
            continue
        path.append(node_id)
        seen_steps.add(step)
    return path


def infer_main_path_from_terminal(state: dict[str, Any]) -> list[str]:
    """Infer a defensible primary route by walking backward from the final node.

    This fallback is used when the planner forgot to set `route_role="main"`.
    It intentionally prefers a single predecessor per stage, while treating
    other completed branches as comparison inputs.
    """
    nodes = _node_index(state)
    if not nodes:
        return []
    terminal_types = ("claim_synthesis", "report_option", "route_comparison")
    terminals = [
        node
        for node in nodes.values()
        if node.get("node_type") in terminal_types
        and node.get("status") in ACTIVE_ROUTE_STATUSES
        and node.get("status") not in {"blocked", "deferred"}
    ]
    if not terminals:
        return []
    terminals.sort(key=lambda node: (_node_step(node), str(node.get("node_id"))), reverse=True)
    target = terminals[0]
    path_rev = [str(target.get("node_id"))]
    current = target
    visited = {str(target.get("node_id"))}

    def score_dep(dep_id: str, current_node: dict[str, Any]) -> tuple[int, int, int, str]:
        dep = nodes[dep_id]
        current_type = current_node.get("node_type")
        dep_type = dep.get("node_type")
        status = dep.get("status")
        preferred_type_rank = 50
        if current_type == "claim_synthesis":
            preferred_type_rank = {"route_comparison": 0, "report_option": 1, "model_explanation": 4, "diagnostic": 5, "model_execution": 6}.get(str(dep_type), 20)
        elif current_type in {"route_comparison", "report_option"}:
            preferred_type_rank = {"model_explanation": 0, "diagnostic": 1, "model_execution": 2}.get(str(dep_type), 20)
        elif current_type in {"model_explanation", "diagnostic"}:
            preferred_type_rank = {"model_execution": 0, "data_preparation": 2, "feature_package": 3}.get(str(dep_type), 20)
        elif current_type == "model_execution":
            preferred_type_rank = {"feature_package": 0, "data_preparation": 1, "research_object": 2}.get(str(dep_type), 20)
        elif current_type in {"feature_package", "data_preparation"}:
            preferred_type_rank = {"research_object": 0}.get(str(dep_type), 20)
        status_rank = 0 if status in {"completed", "selected", "active", "merged"} else 1 if status == "approved" else 2
        main_rank = 0 if _is_main_node(dep) else 1
        return (preferred_type_rank, status_rank, main_rank, str(dep.get("node_id")))

    while True:
        deps = [
            dep
            for dep in current.get("depends_on", [])
            if dep in nodes
            and dep not in visited
            and nodes[dep].get("status") not in {"blocked", "deferred"}
            and _node_step(nodes[dep]) <= _node_step(current)
        ]
        if not deps:
            break
        chosen = sorted(deps, key=lambda dep_id: score_dep(dep_id, current))[0]
        path_rev.append(chosen)
        visited.add(chosen)
        current = nodes[chosen]
        if current.get("node_type") == "research_object":
            break
    return list(reversed(path_rev))


def _edge_relation(state: dict[str, Any], source: str, target: str, relation: str | None = None) -> str:
    nodes = _node_index(state)
    source_node = nodes.get(source, {})
    target_node = nodes.get(target, {})
    main_path = [str(item) for item in state.get("main_path") or state.get("active_path") or []]
    main_pairs = set(zip(main_path, main_path[1:]))
    if (source, target) in main_pairs:
        return "main_path"
    if target_node.get("node_type") in MERGE_NODE_TYPES and source in nodes and source not in main_path:
        return "merge_input"
    if "blocked" in {source_node.get("status"), target_node.get("status")}:
        return "blocked_requirement"
    if "deferred" in {source_node.get("status"), target_node.get("status")}:
        return "deferred_dependency"
    if source_node.get("status") in SUGGESTED_STATUSES or target_node.get("status") in SUGGESTED_STATUSES:
        return "candidate_dependency"
    return relation or "dependency"


def _edge_review_note(state: dict[str, Any], source: str, target: str, relation: str) -> dict[str, str]:
    """Create generic, reviewable meaning for a route-tree edge.

    The note is deliberately typed by node roles rather than by a single case,
    so the front end can explain what each line in the route tree actually does.
    Explicit edge metadata supplied by the planner overrides these defaults.
    """

    nodes = _node_index(state)
    source_node = nodes.get(source, {})
    target_node = nodes.get(target, {})
    source_type = str(source_node.get("node_type") or "node")
    target_type = str(target_node.get("node_type") or "node")

    operation = "Pass reviewed output from the source node to the target node."
    dependency_reason = "The target node requires the source node's reviewed decision, data contract, or artifact."
    claim_boundary_effect = "The target claim inherits the source node's time, space, people, and evidence limits."

    if source_type == "research_object" and target_type in {"feature_package", "data_preparation"}:
        operation = "Align candidate explanatory variables to the selected outcome definition."
        dependency_reason = "The X package must use the same spatial unit, temporal window, activity proxy, and boundary as the selected research object."
        claim_boundary_effect = "All later claims are limited to this unit/window/proxy unless a separate branch is compared."
    elif source_type in {"feature_package", "data_preparation"} and target_type == "model_execution":
        operation = "Build the model-ready matrix from the reviewed feature package."
        dependency_reason = "The model route needs a validated X table/layer, joined keys, missing-value treatment, and feature roles."
        claim_boundary_effect = "Model evidence can only speak for variables and units that passed the feature review."
    elif source_type == "research_object" and target_type == "model_execution":
        operation = "Bind the model to the selected outcome branch."
        dependency_reason = "The model needs a declared Y variable, temporal split, spatial support, and people proxy before fitting."
        claim_boundary_effect = "Prediction or association claims inherit the selected Y definition."
    elif source_type == "model_execution" and target_type == "model_explanation":
        operation = "Use a fitted model output as the input for explanation diagnostics."
        dependency_reason = "SHAP, PDP, permutation importance, and fitted-model explanations require a trained model and its feature matrix."
        claim_boundary_effect = "Explanation claims are about model behavior, not direct causal mechanisms."
    elif source_type == "model_execution" and target_type == "diagnostic":
        operation = "Inspect model residuals, stability, or assumptions before extending the route."
        dependency_reason = "Diagnostics require model predictions, residuals, or fitted parameters."
        claim_boundary_effect = "A failed diagnostic downgrades claims or opens a side branch instead of strengthening the main claim."
    elif source_type == "diagnostic" and target_type == "model_execution":
        operation = "Open a model branch motivated by a diagnostic finding."
        dependency_reason = "The diagnostic supplies the reason for trying a spatial, temporal, or robustness route."
        claim_boundary_effect = "The branch is conditional evidence until it passes its own method review."
    elif target_type in {"route_comparison", "report_option"}:
        operation = "Send completed or reviewed branch evidence into route comparison."
        dependency_reason = "The planner compares compatible outputs rather than merging raw files."
        claim_boundary_effect = "Agreements may support stable claims; disagreements become conditional or insufficient claims."
    elif target_type == "claim_synthesis":
        operation = "Convert route-comparison evidence into calibrated final claims."
        dependency_reason = "The final report depends on completed branch outputs, reviewer decisions, and human report choices."
        claim_boundary_effect = "Final claims must remain stable, conditional, insufficient, or unsupported according to the compared evidence."

    if relation == "merge_input":
        operation = "Use this side branch as comparison evidence, not as the selected main route."
        claim_boundary_effect = "The side branch may modify confidence or add conditions, but it should not overwrite the main route without a recorded choice."
    elif relation == "blocked_requirement":
        operation = "Record an unmet requirement or unsupported branch."
        dependency_reason = "The target branch cannot proceed until missing inputs, parameters, or alignment checks are supplied."
        claim_boundary_effect = "Claims that depend on this branch are blocked or explicitly deferred."
    elif relation == "deferred_dependency":
        operation = "Preserve a possible route for later exploration."
        claim_boundary_effect = "The deferred branch is visible as a future route and cannot support current claims."

    return {
        "operation": operation,
        "dependency_reason": dependency_reason,
        "claim_boundary_effect": claim_boundary_effect,
        "edge_explanation": f"{operation} {dependency_reason}",
    }


def annotate_edge_roles(state: dict[str, Any]) -> None:
    annotated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in state.get("edges", []):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target or (source, target) in seen:
            continue
        seen.add((source, target))
        relation = _edge_relation(state, source, target, edge.get("relation"))
        record: dict[str, Any] = {
            "source": source,
            "target": target,
            "relation": relation,
            **_edge_review_note(state, source, target, relation),
        }
        record.update({k: v for k, v in edge.items() if k not in {"source", "target", "relation"} and v not in (None, "", [])})
        annotated.append(record)
    state["edges"] = annotated


def validate_route_tree_rigor(state: dict[str, Any]) -> dict[str, Any]:
    nodes = _node_index(state)
    main_path = [str(item) for item in state.get("main_path") or []]
    issues: list[str] = []
    warnings: list[str] = []
    gate_counts = _gate_counts(state)

    if not main_path:
        warnings.append("No selected main_path is declared or inferable; frontend will show branches but no continuous black route.")
    else:
        last = nodes.get(main_path[-1], {})
        if last.get("node_type") not in {"claim_synthesis", "report_option", "route_comparison"}:
            warnings.append("Selected main_path does not yet reach route comparison or claim synthesis.")
        for idx, node_id in enumerate(main_path[1:], start=1):
            node = nodes.get(node_id, {})
            deps = [dep for dep in node.get("depends_on", []) if dep in nodes]
            if deps and not any(dep in main_path[:idx] for dep in deps):
                issues.append(f"{node_id}: main-path node has dependencies outside earlier main-path nodes; mark as merge/side evidence or revise depends_on.")
        for node_id in main_path:
            node = nodes.get(node_id, {})
            if node.get("node_type") == "claim_synthesis":
                previous_types = {nodes.get(prev_id, {}).get("node_type") for prev_id in main_path[: main_path.index(node_id)]}
                if _branch_like_state(state) and not ({"route_comparison", "report_option"} & previous_types):
                    issues.append(f"{node_id}: branch-like run reaches claim_synthesis without a preceding route_comparison/report gate on the main path.")

    mutually_exclusive_parent_types = {"research_object", "feature_package", "data_preparation", "model_execution"}
    for node_id, node in nodes.items():
        is_merge_node = node.get("node_type") in MERGE_NODE_TYPES or node.get("combines_alternatives") is True
        if not is_merge_node:
            parent_types: dict[str, list[str]] = {}
            for dep in node.get("depends_on", []):
                if dep in nodes:
                    parent_types.setdefault(str(nodes[dep].get("node_type")), []).append(dep)
            for parent_type, dep_ids in parent_types.items():
                if parent_type in mutually_exclusive_parent_types and len(dep_ids) > 1:
                    issues.append(f"{node_id}: depends on multiple {parent_type} nodes {dep_ids}; split into branches or set combines_alternatives=true.")
        if node.get("status") == "completed" and node.get("node_type") in REVIEWABLE_NODE_TYPES:
            if not node.get("artifacts") and not node.get("artifact_not_applicable"):
                issues.append(f"{node_id}: completed node has no attached artifact or artifact_not_applicable reason.")
            if node.get("node_type") in WORKER_REQUIRED_NODE_TYPES and not (
                node.get("worker_record") or node.get("worker_task_record") or node.get("actual_executor") == "delegated_worker"
            ):
                issues.append(f"{node_id}: completed executable node is missing a delegated worker record.")
            issues.extend(_review_status_issues(node_id, node))
            if node.get("node_type") == "claim_synthesis" and _branch_like_state(state):
                dep_types = {nodes.get(dep, {}).get("node_type") for dep in node.get("depends_on", []) if dep in nodes}
                if not ({"route_comparison", "report_option"} & dep_types):
                    issues.append(f"{node_id}: branch-like claim_synthesis must depend on a route_comparison/report_option gate, not raw branch outputs.")

    if _completed_execution_requires_plan_gate(state):
        issues.extend(_plan_decision_issues(state))
        issues.extend(_plan_review_issues(state))
    warnings.extend(_early_branch_design_warnings(state))

    for edge in state.get("edges", []):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target and not edge.get("operation"):
            warnings.append(f"{source}->{target}: edge has no operation explanation.")

    status = "pass" if not issues and not warnings else "warning" if not issues else "fail"
    return {"status": status, "issues": issues, "warnings": warnings, "main_path": main_path, "gate_counts": gate_counts}


def load_state(run_dir: str | Path) -> dict[str, Any]:
    path = state_paths(run_dir)["state"]
    if not path.exists():
        raise FileNotFoundError(f"route tree state does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], *, run_dir: str | Path, event: dict[str, Any] | None) -> dict[str, Any]:
    paths = state_paths(run_dir)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    state.setdefault("meta", {})["updated_at"] = _now()
    paths["state"].write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if event:
        with paths["events"].open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    frontend = export_frontend_state(state, run_dir=run_dir)
    paths["frontend"].write_text(json.dumps(frontend, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    visual = {"nodes": frontend["tree"]["nodes"], "edges": frontend["tree"]["edges"]}
    paths["visual"].write_text(json.dumps(visual, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if state.get("current_choice_request"):
        paths["choice"].write_text(render_choice_request(state), encoding="utf-8")
    return {
        "state_path": str(paths["state"]),
        "event_log_path": str(paths["events"]),
        "frontend_state_path": str(paths["frontend"]),
        "visual_spec_path": str(paths["visual"]),
        "choice_request_path": str(paths["choice"]) if state.get("current_choice_request") else None,
        "frontend_url": frontend.get("frontend_url"),
    }


def apply_patches(state: dict[str, Any], patches: list[dict[str, Any]], *, actor: str = "planner") -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    nodes = _node_index(state)
    for raw in patches:
        patch = dict(raw)
        patch_type = str(patch.get("patch_type") or patch.get("type") or "").strip()
        if patch_type not in PATCH_TYPES:
            patch_type = "update_node" if patch.get("node_id") else "add_node"
        event = {
            "event_id": f"evt_{len(state.get('patch_events', [])) + len(applied) + 1:04d}",
            "timestamp": _now(),
            "actor": actor,
            "patch_type": patch_type,
            "reason": patch.get("reason") or patch.get("review_reason") or "",
            "patch": patch,
        }
        if patch_type in {"add_node", "add_branch", "add_report_option"}:
            node = normalize_node(patch.get("node") or patch, default_status=patch.get("status") or "suggested")
            nodes[node["node_id"]] = node
        elif patch_type == "update_node":
            node_id = str(patch.get("node_id") or "")
            if node_id in nodes:
                updates = patch.get("updates") if isinstance(patch.get("updates"), dict) else {
                    key: value for key, value in patch.items() if key not in {"patch_type", "type", "node_id", "reason"}
                }
                nodes[node_id].update(updates)
                nodes[node_id]["updated_at"] = _now()
        elif patch_type == "update_status":
            node_id = str(patch.get("node_id") or "")
            if node_id in nodes:
                nodes[node_id]["status"] = str(patch.get("status") or nodes[node_id].get("status"))
                nodes[node_id]["status_reason"] = patch.get("reason") or patch.get("status_reason")
                for key in ("route_role", "selection_role", "branch_role", "main_route", "combines_alternatives"):
                    if key in patch:
                        nodes[node_id][key] = patch[key]
                nodes[node_id]["updated_at"] = _now()
        elif patch_type == "add_edge":
            state.setdefault("edges", []).append({
                "source": str(patch.get("source")),
                "target": str(patch.get("target")),
                "relation": str(patch.get("relation") or "depends_on"),
                "operation": patch.get("operation"),
                "dependency_reason": patch.get("dependency_reason") or patch.get("reason"),
                "claim_boundary_effect": patch.get("claim_boundary_effect"),
                "edge_explanation": patch.get("edge_explanation") or patch.get("explanation"),
            })
        elif patch_type == "attach_artifact":
            attach_artifact_to_state(state, patch)
        elif patch_type == "request_human_choice":
            state["current_choice_request"] = {
                "message": patch.get("message") or "Select how to proceed.",
                "choices": patch.get("choices") or [],
                "created_at": _now(),
                "required_before": patch.get("required_before") or "next artifact-producing step",
            }
        elif patch_type == "merge_branches":
            merge_node = normalize_node(
                {
                    "node_id": patch.get("node_id") or "claim_synthesis",
                    "node_type": "claim_synthesis",
                    "question": patch.get("question") or "Compare completed route outputs and calibrate claims.",
                    "depends_on": patch.get("source_nodes") or patch.get("depends_on") or [],
                    "status": patch.get("status") or "waiting_choice",
                    "expected_outputs": patch.get("expected_outputs") or ["claim_synthesis.md", "branch_comparison.json"],
                    "claim_boundary": patch.get("claim_boundary") or "Final claims must be calibrated from completed branch outputs and reviews.",
                },
                default_status="waiting_choice",
            )
            nodes[merge_node["node_id"]] = merge_node
        elif patch_type == "revise_dependency":
            node_id = str(patch.get("node_id") or "")
            if node_id in nodes:
                nodes[node_id]["depends_on"] = [str(item) for item in _as_list(patch.get("depends_on"))]
                nodes[node_id]["updated_at"] = _now()
        applied.append(event)
    state["nodes"] = list(nodes.values())
    state["edges"] = merge_edges(state["nodes"], state.get("edges", []))
    state.setdefault("patch_events", []).extend(applied)
    refresh_active_path(state)
    return applied


def attach_artifact_to_state(state: dict[str, Any], patch: dict[str, Any]) -> None:
    node_id = str(patch.get("node_id") or patch.get("branch_id") or "")
    artifact = {
        "artifact_id": patch.get("artifact_id") or f"art_{len(state.get('artifact_index', [])) + 1:04d}",
        "node_id": node_id,
        "path": patch.get("path"),
        "artifact_type": patch.get("artifact_type") or patch.get("type") or "artifact",
        "role": patch.get("role") or "intermediate_output",
        "title": patch.get("title") or Path(str(patch.get("path") or "")).name,
        "created_at": patch.get("created_at") or _now(),
        "review_status": patch.get("review_status") or "pending_review",
    }
    state.setdefault("artifact_index", []).append(artifact)
    nodes = _node_index(state)
    if node_id in nodes:
        nodes[node_id].setdefault("artifacts", []).append(artifact)
        nodes[node_id]["updated_at"] = _now()
        state["nodes"] = list(nodes.values())


def sync_trace_to_state(state: dict[str, Any], trace: dict[str, Any], *, run_dir: str | Path) -> dict[str, Any]:
    """Synchronize a finished workflow trace back into the planner route tree.

    Planner, worker, and reviewer outputs often land in separate JSON files.
    This generic sync step makes the route tree the single inspectable state
    object used by the CLI, frontend, and figure scripts.
    """

    nodes = _node_index(state)
    state.setdefault("trace_sync_records", [])
    state["trace_sync_records"].append({"timestamp": _now(), "source": trace.get("trace_id") or trace.get("workflow_id") or "workflow_trace"})
    for key in (
        "human_plan_decision",
        "claim_gates",
        "artifact_manifest",
        "worker_reflection",
        "reviewer_reflection",
        "main_reflection",
        "memory_carryover",
    ):
        if trace.get(key) not in (None, "", [], {}):
            state[key] = trace[key]

    # Promote plan-gate records so plan-level validation uses the same source
    # as the final trace.
    if trace.get("human_plan_decision"):
        state["human_plan_decision"] = trace["human_plan_decision"]

    branch_tree = trace.get("branch_tree") if isinstance(trace.get("branch_tree"), dict) else {}
    for status_key, node_status in (
        ("completed", "completed"),
        ("triggered_not_validated", "triggered_not_validated"),
        ("deferred", "deferred"),
        ("blocked", "blocked"),
        ("suggested", "suggested"),
    ):
        for node_id in _as_list(branch_tree.get(status_key)):
            if str(node_id) in nodes:
                nodes[str(node_id)]["status"] = node_status
                nodes[str(node_id)]["updated_at"] = _now()

    # Main workflow steps are the most reliable source for the selected route.
    selected_route: list[str] = []
    plan = trace.get("main_workflow_plan") if isinstance(trace.get("main_workflow_plan"), dict) else {}
    for step in _as_list(plan.get("steps")):
        if not isinstance(step, dict):
            continue
        for key in ("approved_branch", "artifact"):
            node_id = str(step.get(key) or "")
            if node_id in nodes:
                selected_route.append(node_id)
                if step.get("status") == "completed":
                    nodes[node_id]["status"] = "completed"
        for node_id in _as_list(step.get("artifacts")):
            if str(node_id) in nodes:
                selected_route.append(str(node_id))
                if step.get("status") == "completed":
                    nodes[str(node_id)]["status"] = "completed"

    # Route-comparison and claim-synthesis artifacts usually name files, not
    # node ids. Add their canonical nodes when present.
    for node_id in ("RC_CMP", "CS_FINAL"):
        if node_id in nodes and node_id not in selected_route and nodes[node_id].get("status") in {"active", "completed", "merged"}:
            selected_route.append(node_id)

    selected_route = [node_id for node_id in dict.fromkeys(selected_route) if node_id in nodes and nodes[node_id].get("status") not in {"blocked", "deferred", "triggered_not_validated", "failed"}]
    if selected_route:
        state["declared_main_path"] = selected_route
        for node_id in selected_route:
            nodes[node_id]["route_role"] = "main"

    for record in _as_list(trace.get("worker_task_records")):
        if not isinstance(record, dict):
            continue
        for node_id in _record_node_ids(record, nodes):
            nodes[node_id]["worker_record"] = record
            nodes[node_id]["actual_executor"] = record.get("actual_executor") or record.get("executor") or nodes[node_id].get("actual_executor")
            nodes[node_id]["updated_at"] = _now()

    review_records: list[Any] = []
    for record in _as_list(trace.get("per_step_review_records")):
        if isinstance(record, dict) and record.get("review_file"):
            resolved = _existing_review_path(str(record.get("review_file")), run_dir=run_dir)
            loaded = _load_json_reference(resolved, run_dir=run_dir) if resolved else None
            if loaded:
                loaded.setdefault("review_file", resolved)
                review_records.append(loaded)
                if record.get("review_file") != Path(resolved).name:
                    record["resolved_review_file"] = Path(resolved).name
            review_records.append(record)
        else:
            review_records.append(record)
    if review_records:
        state["per_step_review_records"] = review_records

    for review in review_records:
        if not isinstance(review, dict):
            continue
        if str(review.get("step_id") or "").startswith("plan") or str(review.get("stage") or "").startswith("plan"):
            state["plan_review_record"] = review
        matched = _record_node_ids(review, nodes)
        step_id = str(review.get("step_id") or review.get("main_plan_step") or "")
        if not matched and step_id:
            for node_id, node in nodes.items():
                if str(node.get("step_id") or "") == step_id:
                    matched.append(node_id)
        for node_id in dict.fromkeys(matched):
            nodes[node_id]["review_record"] = review
            nodes[node_id]["updated_at"] = _now()

    # If a review names a combined selected route (e.g. RO_Y1 + FP_X3), attach
    # it to both nodes through string matching. For final synthesis reviews,
    # attach the trace-level review to terminal nodes.
    for node_id in ("RC_CMP", "CS_FINAL"):
        if node_id in nodes and not nodes[node_id].get("review_record") and trace.get("per_step_review_records"):
            nodes[node_id]["review_record"] = trace["per_step_review_records"][-1]

    state["nodes"] = list(nodes.values())
    state["edges"] = merge_edges(state["nodes"], state.get("edges", []))
    refresh_active_path(state)
    return state


def apply_choices(state: dict[str, Any], choices: list[dict[str, Any]], *, actor: str = "human") -> list[dict[str, Any]]:
    nodes = _node_index(state)
    records: list[dict[str, Any]] = []
    for raw in choices:
        node_id = str(raw.get("node_id") or raw.get("branch_id") or "")
        decision, reason = _choice_decision(raw)
        record = {
            "choice_id": f"choice_{len(state.get('human_choices', [])) + len(records) + 1:04d}",
            "timestamp": _now(),
            "actor": actor,
            "node_id": node_id,
            "decision": decision,
            "reason": reason,
            "report_style": raw.get("report_style"),
        }
        if node_id in nodes:
            if decision in {"approve", "approved", "select", "run", "activate"}:
                missing = [dep for dep in nodes[node_id].get("depends_on", []) if nodes.get(dep, {}).get("status") not in {"approved", "active", "selected", "completed", "merged"}]
                nodes[node_id]["status"] = "approved" if not missing else "waiting_choice"
                nodes[node_id]["dependency_blockers"] = missing
            elif decision in {"defer", "deferred"}:
                nodes[node_id]["status"] = "deferred"
            elif decision in {"block", "blocked"}:
                nodes[node_id]["status"] = "blocked"
            elif decision in {"revise", "revision"}:
                nodes[node_id]["status"] = "revised"
            nodes[node_id]["human_decision"] = record
            nodes[node_id]["updated_at"] = _now()
        records.append(record)
    state["nodes"] = list(nodes.values())
    state.setdefault("human_choices", []).extend(records)
    state["current_choice_request"] = None
    refresh_active_path(state)
    return records


def refresh_active_path(state: dict[str, Any]) -> None:
    main_path = compute_main_path(state)
    state["main_path"] = main_path
    # Backward-compatible name for the frontend and older figure scripts. From
    # this point on it means the selected primary route, not all completed work.
    state["active_path"] = main_path
    branch_tree = {
        "active": state["active_path"],
        "main": main_path,
        "completed_branch": [
            node["node_id"]
            for node in state.get("nodes", [])
            if _is_side_evidence(node) or (
                node.get("status") in ACTIVE_ROUTE_STATUSES
                and node.get("node_id") not in main_path
                and node.get("status") not in {"blocked", "deferred"}
            )
        ],
        "suggested": [node["node_id"] for node in state.get("nodes", []) if node.get("status") in {"candidate", "suggested", "waiting_choice", "revised"}],
        "deferred": [node["node_id"] for node in state.get("nodes", []) if node.get("status") == "deferred"],
        "blocked": [node["node_id"] for node in state.get("nodes", []) if node.get("status") == "blocked"],
        "merged": [
            node["node_id"]
            for node in state.get("nodes", [])
            if node.get("status") == "merged" or node.get("node_type") in MERGE_NODE_TYPES
        ],
    }
    state["branch_tree"] = branch_tree
    annotate_edge_roles(state)
    state["route_tree_review"] = validate_route_tree_rigor(state)
    refresh_planner_todo(state)


def refresh_planner_todo(state: dict[str, Any]) -> None:
    nodes_by_step: dict[str, list[dict[str, Any]]] = {}
    for node in state.get("nodes", []):
        nodes_by_step.setdefault(str(node.get("step_id") or _default_step(str(node.get("node_type") or ""))), []).append(node)
    terminal = {"completed", "merged", "deferred", "blocked"}
    active = {"approved", "active", "selected"}
    todo = state.get("planner_todo") or infer_todo_steps(state.get("nodes", []))
    for item in todo:
        step_nodes = nodes_by_step.get(str(item.get("step_id") or ""), [])
        if not step_nodes:
            item["status"] = "template"
            continue
        statuses = {str(node.get("status") or "") for node in step_nodes}
        if any(status in {"waiting_choice"} for status in statuses):
            item["status"] = "waiting_choice"
        elif any(status in active for status in statuses):
            item["status"] = "active"
        elif statuses and statuses.issubset(terminal) and any(status in {"completed", "merged"} for status in statuses):
            item["status"] = "completed"
        elif any(status in {"pending", "candidate", "suggested", "revised"} for status in statuses):
            item["status"] = "pending"
        elif statuses and statuses.issubset({"deferred", "blocked"}):
            item["status"] = "deferred"
        else:
            item["status"] = "candidate"
    state["planner_todo"] = todo


def render_choice_request(state: dict[str, Any]) -> str:
    req = state.get("current_choice_request") or {}
    lines = ["# Urban-Hermes Route Choice Request", "", str(req.get("message") or "Select how to proceed."), ""]
    for choice in req.get("choices") or []:
        node_id = choice.get("node_id") or choice.get("branch_id") or ""
        label = choice.get("label") or choice.get("decision") or "option"
        desc = choice.get("description") or choice.get("reason") or ""
        lines.append(f"- `{node_id}`: {label}. {desc}".rstrip())
    lines.extend(["", f"Required before: {req.get('required_before') or 'next step'}"])
    return "\n".join(lines)


def validate_state(state: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    nodes = _node_index(state)
    if not nodes:
        issues.append("route tree has no nodes")
    for node_id, node in nodes.items():
        node_type = node.get("node_type")
        if node_type not in ROUTE_NODE_TYPES:
            issues.append(f"{node_id}: unsupported node_type {node_type!r}")
        if node.get("status") not in ROUTE_STATUSES:
            issues.append(f"{node_id}: unsupported status {node.get('status')!r}")
        for dep in node.get("depends_on", []):
            if dep not in nodes:
                issues.append(f"{node_id}: dependency {dep!r} does not exist")
        tsp = node.get("time_space_people") or {}
        if not isinstance(tsp, dict) or not all(key in tsp and str(tsp.get(key)).strip() for key in ("time", "space", "people")):
            issues.append(f"{node_id}: missing time/space/people meaning")
        if node_type == "model_explanation":
            parent_types = {nodes[dep].get("node_type") for dep in node.get("depends_on", []) if dep in nodes}
            if "model_execution" not in parent_types:
                issues.append(f"{node_id}: model_explanation must depend on a fitted model_execution node")
        if node_type == "claim_synthesis" and not node.get("depends_on"):
            issues.append(f"{node_id}: claim_synthesis must depend on completed branch outputs/reviews")
    rigor = state.get("route_tree_review") or validate_route_tree_rigor(state)
    issues.extend(str(item) for item in rigor.get("issues", []))
    return issues


def export_frontend_state(state: dict[str, Any], *, run_dir: str | Path) -> dict[str, Any]:
    refresh_active_path(state)
    paths = state_paths(run_dir)
    try:
        rel = paths["frontend"].relative_to(ROOT).as_posix()
        frontend_port = os.getenv("URBAN_HERMES_FRONTEND_PORT", "8017").strip() or "8017"
        frontend_url = f"http://localhost:{frontend_port}/frontend/urban_hermes_route_viewer/index.html?state={rel}"
    except ValueError:
        frontend_url = None
    return {
        "schema_version": "urban_route_frontend_state_v1",
        "generated_at": _now(),
        "frontend_url": frontend_url,
        "tree": {
            "meta": state.get("meta", {}),
            "nodes": state.get("nodes", []),
            "edges": state.get("edges", []),
            "branch_tree": state.get("branch_tree", {}),
            "active_path": state.get("active_path", []),
            "main_path": state.get("main_path", []),
            "route_tree_review": state.get("route_tree_review", {}),
        },
        "workflow": {
            "planner_todo": state.get("planner_todo", []),
            "patch_events": state.get("patch_events", []),
            "human_choices": state.get("human_choices", []),
            "current_choice_request": state.get("current_choice_request"),
            "artifact_index": state.get("artifact_index", []),
            "claim_options": state.get("claim_options", []),
        },
        "validation": {
            "issues": validate_state(state),
            "route_tree_review": state.get("route_tree_review", {}),
        },
    }


def run_action(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "export").strip()
    run_dir = args.get("run_dir")
    if not run_dir:
        raise ValueError("run_dir is required")
    if action == "init":
        state = init_state(
            run_dir=run_dir,
            task=str(args.get("task") or ""),
            nodes=args.get("nodes") or [],
            todo_steps=args.get("todo_steps") or None,
            metadata=args.get("metadata") or None,
        )
        event = {"event_id": "evt_0000", "timestamp": _now(), "actor": "planner", "patch_type": "init", "reason": "route tree initialized"}
        save = save_state(state, run_dir=run_dir, event=event)
        return {"state": state, "files": save, "validation_issues": validate_state(state)}

    state = load_state(run_dir)
    result: dict[str, Any] = {}
    event: dict[str, Any] | None = None
    if action in {"patch", "apply_patch"}:
        patches = args.get("patches") or args.get("patch") or []
        patches = patches if isinstance(patches, list) else [patches]
        applied = apply_patches(state, patches, actor=str(args.get("actor") or "planner"))
        result["applied_events"] = applied
        event = {"event_id": f"batch_{_now()}", "timestamp": _now(), "actor": args.get("actor") or "planner", "patch_type": "patch_batch", "count": len(applied)}
    elif action in {"choose", "human_choice"}:
        choices = args.get("choices") or args.get("choice") or []
        choices = choices if isinstance(choices, list) else [choices]
        records = apply_choices(state, choices, actor=str(args.get("actor") or "human"))
        result["human_choices"] = records
        event = {"event_id": f"choice_{_now()}", "timestamp": _now(), "actor": args.get("actor") or "human", "patch_type": "human_choice", "count": len(records)}
    elif action == "attach_artifact":
        attach_artifact_to_state(state, args)
        event = {"event_id": f"artifact_{_now()}", "timestamp": _now(), "actor": args.get("actor") or "worker", "patch_type": "attach_artifact", "node_id": args.get("node_id"), "path": args.get("path")}
    elif action == "sync_trace":
        trace = args.get("workflow_trace") or args.get("trace") or _load_json_reference(args.get("trace_path"), run_dir=run_dir)
        if not isinstance(trace, dict):
            raise ValueError("sync_trace requires workflow_trace/trace object or trace_path JSON")
        sync_trace_to_state(state, trace, run_dir=run_dir)
        event = {
            "event_id": f"sync_trace_{_now()}",
            "timestamp": _now(),
            "actor": args.get("actor") or "planner",
            "patch_type": "sync_trace",
            "trace_id": trace.get("trace_id") or trace.get("workflow_id"),
        }
    elif action == "validate":
        result["validation_issues"] = validate_state(state)
    elif action == "export":
        pass
    else:
        raise ValueError(f"unsupported action: {action}")

    save = save_state(state, run_dir=run_dir, event=event)
    result.update({"state": state, "files": save, "validation_issues": validate_state(state)})
    return result
