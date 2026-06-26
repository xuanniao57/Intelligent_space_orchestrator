import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = ROOT / "hermes_urban_agent"
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

from urban_hermes.route_tree_state import refresh_active_path, validate_route_tree_rigor


def _tsp():
    return {
        "time": "7-day aggregate",
        "space": "500m grid",
        "people": "aggregate activity proxy",
    }


def _artifact(node_id, role="output"):
    return {
        "artifact_id": f"art_{node_id}",
        "node_id": node_id,
        "path": f"{node_id}.json",
        "artifact_type": "table",
        "role": role,
        "review_status": "passed",
    }


def _review():
    return {"reviewer_status": "passed", "recommendation": "proceed"}


def _worker():
    return {"worker_delegated": True, "worker_status": "completed"}


def _node(node_id, node_type, depends_on=(), *, role="main"):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "step_id": {
            "research_object": "S1_research_object",
            "feature_package": "S2_variables",
            "model_execution": "S3_model_route",
            "model_explanation": "S4_explanation_diagnostics",
            "diagnostic": "S4_explanation_diagnostics",
            "route_comparison": "S5_route_comparison",
            "claim_synthesis": "S6_claim_synthesis",
        }[node_type],
        "question": node_id,
        "depends_on": list(depends_on),
        "time_space_people": _tsp(),
        "claim_boundary": "descriptive association only",
        "status": "completed",
        "route_role": role,
        "main_route": role == "main",
        "artifacts": [_artifact(node_id)],
        "worker_task_record": _worker(),
        "review_record": _review(),
        "design_basis": "unit-test route-design memory",
    }


def _valid_state():
    nodes = [
        _node("ro_total", "research_object"),
        _node("fp_built_env", "feature_package", ["ro_total"]),
        _node("me_rf", "model_execution", ["ro_total", "fp_built_env"]),
        _node("mx_shap", "model_explanation", ["me_rf"]),
        _node("diag_residual", "diagnostic", ["me_rf"], role="comparison_input"),
        _node("rc_gate", "route_comparison", ["mx_shap", "diag_residual"]),
        _node("claim_final", "claim_synthesis", ["rc_gate"]),
        {
            **_node("fp_perception", "feature_package", ["ro_total"], role="blocked"),
            "status": "blocked",
            "main_route": False,
        },
    ]
    nodes[5]["combines_alternatives"] = True
    nodes[5]["artifacts"].append(_artifact("rc_gate", role="claim_gate"))
    nodes[0]["branch_not_applicable_reason"] = "minimal unit-test tree uses one outcome branch"
    state = {
        "nodes": nodes,
        "edges": [],
        "declared_main_path": ["ro_total", "fp_built_env", "me_rf", "mx_shap", "rc_gate", "claim_final"],
        "human_plan_decision": {
            "plan_was_shown": True,
            "decision": "approved",
            "approved_steps": ["S1", "S2", "S3", "S4", "S5", "S6"],
        },
        "plan_review_record": {"passed": True, "decision": "proceed"},
    }
    refresh_active_path(state)
    return state


def test_route_tree_rigor_counts_route_comparison_claim_gate():
    state = _valid_state()
    review = validate_route_tree_rigor(state)

    assert review["status"] == "pass"
    assert review["gate_counts"]["route_comparison_on_main_path"] == 1
    assert review["gate_counts"]["claim_synthesis_on_main_path"] == 1
    assert review["gate_counts"]["claim_gate_artifacts"] == 1


def test_route_tree_rigor_requires_plan_gate_for_completed_execution():
    state = _valid_state()
    state.pop("human_plan_decision")
    state.pop("plan_review_record")
    refresh_active_path(state)

    issues = state["route_tree_review"]["issues"]
    assert any("plan gate missing" in issue for issue in issues)
    assert any("plan-level review missing" in issue for issue in issues)


def test_route_tree_rigor_rejects_pending_review_record():
    state = _valid_state()
    nodes = {node["node_id"]: node for node in state["nodes"]}
    nodes["mx_shap"]["review_record"] = {"reviewer_status": "pending"}
    refresh_active_path(state)

    assert any("mx_shap: review record is still pending" in issue for issue in state["route_tree_review"]["issues"])


def test_branchy_claim_synthesis_requires_route_comparison_gate():
    state = _valid_state()
    nodes = [node for node in state["nodes"] if node["node_id"] != "rc_gate"]
    for node in nodes:
        if node["node_id"] == "claim_final":
            node["depends_on"] = ["mx_shap"]
    state["nodes"] = nodes
    state["declared_main_path"] = ["ro_total", "fp_built_env", "me_rf", "mx_shap", "claim_final"]
    refresh_active_path(state)

    assert any("without a preceding route_comparison" in issue for issue in state["route_tree_review"]["issues"])
    assert any("must depend on a route_comparison" in issue for issue in state["route_tree_review"]["issues"])
