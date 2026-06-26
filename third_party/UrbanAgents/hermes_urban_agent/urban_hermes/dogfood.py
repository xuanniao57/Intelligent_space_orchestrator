"""End-to-end smoke test for the Hermes-Urban adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bootstrap import bootstrap
from .memory_provider import UrbanMemoryProvider
from .paths import ensure_paths


def _dispatch(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    from tools.registry import registry

    raw = registry.dispatch(tool_name, args)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool_name} returned non-JSON: {raw[:200]}") from exc
    if not payload.get("success"):
        raise RuntimeError(f"{tool_name} failed: {payload}")
    return payload


def run_dogfood() -> dict[str, Any]:
    ensure_paths()
    registered = bootstrap()

    from tools.registry import registry

    schemas = registry.get_definitions(set(registered), quiet=True)
    host_fs = _dispatch("urban_host_fs", {"action": "stat", "path": __file__})["result"]
    host_python = _dispatch(
        "urban_host_python",
        {"code": "print('urban_host_python_ok')", "workdir": str(Path(__file__).parent), "timeout": 30},
    )["result"]
    osm = _dispatch(
        "urban_fetch_osm",
        {"location": "Le Marais, Paris", "radius": 450, "data_types": ["roads", "buildings", "pois"], "mock": True},
    )
    osm_data = osm["result"]
    connectivity = _dispatch("urban_analyze_connectivity", {"road_graph": osm_data["road_graph"]})["result"]
    target_points = [feature["geometry"]["coordinates"] for feature in osm_data["pois"]]
    accessibility = _dispatch(
        "urban_measure_accessibility",
        {"buildings": osm_data["buildings"], "target_points": target_points, "max_distance": 300},
    )["result"]
    density = _dispatch("urban_calculate_density", {"buildings": osm_data["buildings"], "grid_size": 100})["result"]
    topology = _dispatch("urban_build_topology", {"features": osm_data["buildings"] + osm_data["pois"], "relation_threshold": 180})["result"]
    svg = _dispatch("urban_generate_svg_overlay", {"base_features": osm_data, "interventions": [], "bbox": osm_data["bbox"], "width": 640})["result"]
    research = _dispatch(
        "urban_research_memory",
        {"query": "历史街区建成环境影响游客历史感 社交媒体 200m 网格 AOI context buffer", "limit": 4},
    )["result"]
    grounding = _dispatch(
        "urban_ground_task",
        {
            "task": "Assess walkability in Le Marais with reviewable network and accessibility evidence.",
            "location": "Le Marais, Paris",
            "bbox": osm_data["bbox"],
            "mock": True,
            "affected_group": "pedestrians and visitors",
            "observed_group": "synthetic OSM fixture users",
            "stakeholder_source": "dogfood analyst",
            "uncertainty": "synthetic fixture for runtime validation",
            "freshness": "dogfood fixture generated at runtime",
        },
    )["result"]
    analysis = {
        "task": grounding["task"],
        "metrics": {"connectivity": connectivity, "accessibility": accessibility, "density": density},
        "topology": topology,
        "artifact": {"svg_size": svg["size"]},
        "evidence_manifest": grounding["evidence_manifest"],
    }
    review = _dispatch("urban_review", {"analysis": analysis, "evidence_manifest": grounding["evidence_manifest"]})["result"]
    feedback = _dispatch(
        "urban_record_feedback",
        {
            "summary": "Treat the Le Marais canal crossing as a reviewable barrier correction, not a silent topology assumption.",
            "triggers": ["Le Marais", "footbridge", "barrier", "walkability"],
            "place": "Le Marais, Paris",
            "correction": "When a canal or narrow waterway separates clusters, require a footbridge or crossing evidence check before marking it connected.",
            "review_policy": "spatial_structural_review",
            "session_id": "dogfood-smoke",
        },
    )["result"]

    provider = UrbanMemoryProvider()
    provider.initialize("dogfood-smoke", platform="cli")
    recall = provider.prefetch("Le Marais footbridge barrier walkability", session_id="dogfood-smoke")

    return {
        "registered_tools": registered,
        "schema_count": len(schemas),
        "host_fs_hit": bool(host_fs.get("exists")),
        "host_python_hit": host_python.get("returncode") == 0 and "urban_host_python_ok" in host_python.get("stdout_tail", ""),
        "fetch_source": osm.get("source"),
        "connectivity_class": connectivity["connectivity_class"],
        "accessibility_coverage_ratio": accessibility["coverage_ratio"],
        "density_grid_shape": density["grid_shape"],
        "topology_nodes": len(topology["nodes"]),
        "svg_size": svg["size"],
        "grounding_status": grounding["status"],
        "grounding_gap_count": len(grounding["grounding_gaps"]),
        "review_recommendation": review["recommendation"],
        "review_score": review["urban_validity_score"],
        "feedback_recorded": bool(feedback.get("feedback")),
        "research_memory_hit": bool(research.get("records")),
        "memory_recall_hit": "Le Marais" in recall,
        "memory_root": feedback.get("memory_root"),
    }


def main() -> None:
    summary = run_dogfood()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
