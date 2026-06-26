import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = ROOT / "hermes_urban_agent"
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

from urban_hermes.memory_provider import UrbanMemoryProvider
from urban_hermes.paths import HERMES_ROOT


def _result(raw: str) -> dict:
    payload = json.loads(raw)
    assert payload["success"] is True
    return payload["result"]


def test_urban_hermes_defaults_to_vendored_runtime():
    if os.getenv("URBAN_HERMES_HERMES_ROOT"):
        pytest.skip("developer override uses an external Hermes checkout")
    assert HERMES_ROOT.name == "hermes_runtime"
    assert HERMES_ROOT.parent.name == "_vendor"
    assert (HERMES_ROOT / "cli.py").exists()
    assert (HERMES_ROOT / "hermes_cli" / "banner.py").exists()


def test_vendored_tool_discovery_handles_bom_encoded_modules():
    from tools.registry import _module_registers_tools

    assert _module_registers_tools(HERMES_ROOT / "tools" / "delegate_tool.py") is True


def test_tool_artifact_memory_routes_to_research_store(tmp_path):
    provider = UrbanMemoryProvider(root=tmp_path)
    provider.initialize("test-session")

    recorded = _result(
        provider.handle_tool_call(
            "urban_memory_record",
            {
                "summary": "QGIS workbench packaging should validate qgz readability and layer styles.",
                "memory_type": "tool_artifact",
                "content_layer": "tool_artifact",
                "memory_scope": "reflective",
                "triggers": ["qgis", "workbench", "layer styles"],
            },
        )
    )

    assert recorded["feedback"] is None
    assert recorded["place"] is None
    assert recorded["research"]["content_layer"] == "tool_artifact"
    assert recorded["research"]["memory_scope"] == "reflective"
    assert recorded["research"]["memory_chain"] == "execution_chain"

    search = _result(
        provider.handle_tool_call(
            "urban_memory_search",
            {
                "query": "qgis workbench layer styles",
                "memory_types": ["feedback", "research"],
                "content_layers": ["tool_artifact"],
                "limit": 3,
            },
        )
    )

    assert search.get("feedback_lessons") == []
    assert search["research_design_lessons"]
    assert search["research_design_lessons"][0]["content_layer"] == "tool_artifact"

    execution_chain_search = _result(
        provider.handle_tool_call(
            "urban_memory_search",
            {
                "query": "qgis workbench layer styles",
                "memory_types": ["research"],
                "memory_chains": ["execution_chain"],
                "limit": 3,
            },
        )
    )
    research_chain_search = _result(
        provider.handle_tool_call(
            "urban_memory_search",
            {
                "query": "qgis workbench layer styles",
                "memory_types": ["research"],
                "memory_chains": ["research_chain"],
                "limit": 3,
            },
        )
    )

    assert execution_chain_search["research_design_lessons"]
    assert research_chain_search["research_design_lessons"] == []


def test_prefetch_keeps_tool_artifacts_deferred(tmp_path):
    provider = UrbanMemoryProvider(root=tmp_path)
    provider.initialize("test-session")

    _result(
        provider.handle_tool_call(
            "urban_research_memory",
            {
                "action": "record",
                "summary": "Vitality-grid studies should separate population observation windows from built-environment indicators.",
                "content_layer": "research_design",
                "memory_scope": "reflective",
                "triggers": ["vitality-grid", "observation window"],
            },
        )
    )
    _result(
        provider.handle_tool_call(
            "urban_research_memory",
            {
                "action": "record",
                "summary": "QGIS vitality workbench packaging procedure stores project files, style files, and a manifest.",
                "content_layer": "tool_artifact",
                "memory_scope": "reflective",
                "method_hint": "Create qgz, qgs, styles, README, and spatial_reasoning_manifest.json.",
                "triggers": ["vitality-grid", "qgis workbench"],
            },
        )
    )

    recall = provider.prefetch("vitality-grid qgis workbench", session_id="test-session")
    assert recall.startswith("[Urban memory recall]")
    payload = json.loads(recall.split("\n", 1)[1])

    assert payload["planning_memory_cards"]
    assert all(item["content_layer"] in {"research_design", "urban_method"} for item in payload["planning_memory_cards"])
    assert payload["deferred_tool_artifact_index"]
    assert all(item["content_layer"] == "tool_artifact" for item in payload["deferred_tool_artifact_index"])
    assert all(item["memory_chain"] == "execution_chain" for item in payload["deferred_tool_artifact_index"])
    assert "method_hint" not in payload["deferred_tool_artifact_index"][0]


def test_provider_tool_schemas_expose_reflect_and_chain_filter(tmp_path):
    provider = UrbanMemoryProvider(root=tmp_path)
    provider.initialize("test-session")

    schemas = {schema["name"]: schema for schema in provider.get_tool_schemas()}

    assert "urban_memory_reflect" in schemas
    assert "memory_chains" in schemas["urban_memory_search"]["parameters"]["properties"]
    assert "memory_chain" in schemas["urban_research_memory"]["parameters"]["properties"]


def test_execution_reflection_promotes_qgis_and_ablation_lessons(tmp_path):
    provider = UrbanMemoryProvider(root=tmp_path)
    provider.initialize("test-session")

    reflected = _result(
        provider.handle_tool_call(
            "urban_memory_reflect",
            {
                "task": "Run paired historical district QGIS memory ablation",
                "place": "Badaguan historical district",
                "trajectory": [{"tool": "delegate_task"}, {"tool": "urban_qgis_workspace"}],
                "validation": {"passed": True, "qgis_invalid_layers": [], "renderer_fields": ["building_coverage_ratio"]},
                "metrics": {"duration_s": 120, "cost_usd": 0.3, "ablation": "memory_on_vs_no_memory"},
                "artifacts": [{"path": "project.qgz"}, {"path": "spatial_reasoning_manifest.json"}],
            },
        )
    )

    layers = {item["content_layer"] for item in reflected["observations"]}
    assert {"tool_artifact", "urban_method", "research_design", "place_case"}.issubset(layers)
    assert reflected["records"]

    search = _result(
        provider.handle_tool_call(
            "urban_research_memory",
            {"query": "QGIS renderer memory ablation historical district", "content_layers": ["tool_artifact", "research_design"], "limit": 5},
        )
    )
    stored_layers = {item["content_layer"] for item in search["records"]}
    assert "tool_artifact" in stored_layers
    assert "research_design" in stored_layers