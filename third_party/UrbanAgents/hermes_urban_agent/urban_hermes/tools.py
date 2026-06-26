"""Hermes tool registrations for the UrbanAgent dogfood adapter."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .paths import ensure_paths
from .route_tree_state import run_action as run_route_tree_action


TOOLSET = "urban"


def register_all_urban_tools() -> list[str]:
    """Register all urban tools with Hermes' registry."""
    ensure_paths()
    from tools.registry import registry

    specs = [
        ("urban_capabilities", CAPABILITIES_SCHEMA, _handle_capabilities),
        ("urban_fetch_osm", FETCH_OSM_SCHEMA, _handle_fetch_osm),
        ("urban_analyze_connectivity", CONNECTIVITY_SCHEMA, _handle_connectivity),
        ("urban_measure_accessibility", ACCESSIBILITY_SCHEMA, _handle_accessibility),
        ("urban_calculate_density", DENSITY_SCHEMA, _handle_density),
        ("urban_generate_svg_overlay", SVG_SCHEMA, _handle_svg),
        ("urban_export_geojson", GEOJSON_SCHEMA, _handle_geojson),
        ("urban_build_topology", TOPOLOGY_SCHEMA, _handle_topology),
        ("urban_ground_task", GROUND_TASK_SCHEMA, _handle_ground_task),
        ("urban_route_tree", ROUTE_TREE_SCHEMA, _handle_route_tree),
        ("urban_review", REVIEW_SCHEMA, _handle_review),
        ("urban_quality_control", QUALITY_SCHEMA, _handle_quality),
        ("urban_record_feedback", RECORD_FEEDBACK_SCHEMA, _handle_record_feedback),
        ("urban_research_memory", RESEARCH_MEMORY_SCHEMA, _handle_research_memory),
        ("urban_memory_reflect", MEMORY_REFLECT_SCHEMA, _handle_memory_reflect),
        ("urban_host_fs", HOST_FS_SCHEMA, _handle_host_fs),
        ("urban_host_python", HOST_PYTHON_SCHEMA, _handle_host_python),
        ("urban_gis_workspace", GIS_WORKSPACE_SCHEMA, _handle_gis_workspace),
        ("urban_qgis_workspace", QGIS_WORKSPACE_SCHEMA, _handle_qgis_workspace),
        ("urban_qgis_process", QGIS_PROCESS_SCHEMA, _handle_qgis_process),
    ]
    names: list[str] = []
    for name, schema, handler in specs:
        names.append(name)
        if registry.get_entry(name):
            continue
        registry.register(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=lambda: True,
            description=schema.get("description", ""),
            emoji="U",
        )
    return names


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _ok(result: Any, **meta: Any) -> str:
    payload = {"success": True, "result": result}
    payload.update(meta)
    return _json(payload)


def _fail(error: str, **meta: Any) -> str:
    payload = {"success": False, "error": error}
    payload.update(meta)
    return _json(payload)


def _host_path(value: Any) -> Path:
    text = str(value or ".").strip()
    if text.startswith("file:///"):
        text = text[8:]
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if match:
        text = f"{match.group(1).upper()}:/{match.group(2)}"
    else:
        match = re.match(r"^/([a-zA-Z])/(.*)$", text)
        if match:
            text = f"{match.group(1).upper()}:/{match.group(2)}"
    return Path(text).expanduser()


def _decode_bytes(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    candidates = [encoding] if encoding else []
    candidates.extend(["utf-8-sig", "utf-8", "utf-16", "gbk"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _read_host_text(path: Path, *, encoding: str | None = None, max_bytes: int | None = None) -> tuple[str, str, bool]:
    data = path.read_bytes()
    truncated = False
    if max_bytes is not None and max_bytes >= 0 and len(data) > max_bytes:
        data = data[:max_bytes]
        truncated = True
    text, used_encoding = _decode_bytes(data, encoding)
    return text, used_encoding, truncated


def _host_entry(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        stat = None
    return {
        "name": path.name,
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "suffix": path.suffix,
        "size": stat.st_size if stat else None,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
    }


def _json_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        summary: dict[str, Any] = {"type": "object", "keys": list(value.keys())[:30], "key_count": len(value)}
        if value.get("type") == "FeatureCollection":
            features = value.get("features") or []
            summary["geojson_type"] = "FeatureCollection"
            summary["feature_count"] = len(features) if isinstance(features, list) else None
            if isinstance(features, list) and features:
                geom_types = Counter((feature.get("geometry") or {}).get("type", "unknown") for feature in features if isinstance(feature, dict))
                summary["geometry_types"] = dict(geom_types)
                first_props = features[0].get("properties") if isinstance(features[0], dict) else None
                if isinstance(first_props, dict):
                    summary["sample_property_keys"] = list(first_props.keys())[:30]
        return summary
    if isinstance(value, list):
        return {"type": "array", "length": len(value), "sample_type": type(value[0]).__name__ if value else None}
    return {"type": type(value).__name__, "repr": repr(value)[:200]}


def _redact_sensitive_host_value(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if any(token in key_lower for token in ("raw_lbs", "lbs_parquet", "parquet_dir", "uuid_level")):
        return "[REDACTED_RAW_LBS_REFERENCE]"
    if isinstance(value, dict):
        return {nested_key: _redact_sensitive_host_value(nested_value, key=str(nested_key)) for nested_key, nested_value in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_host_value(item, key=key) for item in value]
    if isinstance(value, str):
        value_lower = value.lower()
        if ".parquet" in value_lower or ("parquet" in value_lower and "lbs" in value_lower):
            return "[REDACTED_RAW_LBS_REFERENCE]"
    return value


def _handle_host_fs(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "stat")
    path = _host_path(args.get("path") or ".")
    limit = max(1, min(int(args.get("limit") or 100), 1000))

    try:
        if action in {"stat", "exists"}:
            return _ok(_host_entry(path), action=action, host=os.name)

        if action == "list":
            if not path.exists():
                return _fail(f"path does not exist: {path}", action=action)
            if not path.is_dir():
                return _fail(f"path is not a directory: {path}", action=action)
            entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
            return _ok({"path": str(path), "entries": [_host_entry(item) for item in entries[:limit]], "truncated": len(entries) > limit}, action=action, host=os.name)

        if action == "glob":
            pattern = str(args.get("pattern") or "*")
            base = path if path.is_dir() else path.parent
            matches = sorted(base.glob(pattern), key=lambda item: str(item).lower())
            return _ok({"base": str(base), "pattern": pattern, "matches": [_host_entry(item) for item in matches[:limit]], "truncated": len(matches) > limit}, action=action, host=os.name)

        if action == "read_text":
            max_chars = max(1, int(args.get("max_chars") or 20000))
            max_bytes = max_chars * 4
            text, used_encoding, truncated = _read_host_text(path, encoding=args.get("encoding"), max_bytes=max_bytes)
            if len(text) > max_chars:
                text = text[:max_chars]
                truncated = True
            text = str(_redact_sensitive_host_value(text))
            return _ok({"path": str(path), "encoding": used_encoding, "chars": len(text), "truncated": truncated, "text": text}, action=action, host=os.name)

        if action in {"read_json", "json_summary", "geojson_summary"}:
            max_bytes = max(1, int(args.get("max_bytes") or 25_000_000))
            text, used_encoding, truncated = _read_host_text(path, encoding=args.get("encoding"), max_bytes=max_bytes)
            if truncated:
                return _fail(f"JSON file exceeds max_bytes={max_bytes}: {path}", action=action)
            data = json.loads(text)
            data = _redact_sensitive_host_value(data)
            result = {"path": str(path), "encoding": used_encoding, "summary": _json_summary(data)}
            if action == "read_json":
                result["data"] = data
            return _ok(result, action=action, host=os.name)

        return _fail(f"unsupported action: {action}", supported_actions=["stat", "exists", "list", "glob", "read_text", "read_json", "json_summary", "geojson_summary"])
    except Exception as exc:
        return _fail(str(exc), action=action, path=str(path), host=os.name)


def _handle_host_python(args: dict[str, Any], **_: Any) -> str:
    python_executable = str(args.get("python") or sys.executable)
    timeout = max(1, int(args.get("timeout") or 300))
    argv = [str(item) for item in args.get("argv") or []]
    workdir = _host_path(args.get("workdir") or os.getcwd())
    output_dir = args.get("output_dir")
    script_path_arg = args.get("script_path")
    code = args.get("code")
    keep_script = bool(args.get("keep_script", False) or output_dir)
    script_path: Path | None = None
    temporary_script = False

    try:
        workdir.mkdir(parents=True, exist_ok=True)
        if script_path_arg:
            script_path = _host_path(script_path_arg)
        else:
            if not code:
                return _fail("code or script_path is required")
            if output_dir:
                out_dir = _host_path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                script_path = out_dir / f"urban_host_python_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.py"
            else:
                handle = tempfile.NamedTemporaryFile(prefix="urban_host_python_", suffix=".py", delete=False, mode="w", encoding="utf-8")
                script_path = Path(handle.name)
                temporary_script = True
                handle.close()
            script_path.write_text(str(code), encoding="utf-8")

        env = os.environ.copy()
        for key, value in (args.get("env") or {}).items():
            env[str(key)] = str(value)

        cmd = [python_executable, str(script_path), *argv]
        started = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        duration = round(time.time() - started, 3)
        stdout_tail = proc.stdout[-20000:]
        stderr_tail = proc.stderr[-20000:]
        result = {
            "command": cmd,
            "workdir": str(workdir),
            "returncode": proc.returncode,
            "duration_s": duration,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "script_path": str(script_path) if keep_script or script_path_arg else None,
            "windows_native": os.name == "nt",
        }
        if temporary_script and not keep_script:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                result["cleanup_warning"] = f"could not remove temporary script: {script_path}"
        return _ok(result, host=os.name) if proc.returncode == 0 else _fail("host python script failed", result=result, host=os.name)
    except subprocess.TimeoutExpired as exc:
        return _fail(f"host python script timed out after {timeout}s", stdout=exc.stdout, stderr=exc.stderr, host=os.name)
    except Exception as exc:
        return _fail(str(exc), host=os.name, script_path=str(script_path) if script_path else None)


def _handle_capabilities(args: dict[str, Any], **_: Any) -> str:
    task = args.get("task") or args.get("query") or "urban spatial analysis"
    limit = int(args.get("limit") or 6)
    return _ok(_fallback_capabilities(str(task), limit=limit), source="urban_hermes.capability_catalog")


def _handle_fetch_osm(args: dict[str, Any], **_: Any) -> str:
    location = str(args.get("location") or "sample district")
    radius = float(args.get("radius") or 500)
    data_types = [str(item) for item in args.get("data_types") or ["roads", "buildings", "pois"]]
    use_mock = bool(args.get("mock", False))
    if not use_mock:
        try:
            return _ok(_fetch_osmnx(location, radius, data_types), source="osmnx")
        except Exception as exc:
            synthetic = _synthetic_osm(location, radius, data_types)
            synthetic["warning"] = f"osmnx unavailable or fetch failed: {exc}"
            return _ok(synthetic, source="synthetic_fallback")
    return _ok(_synthetic_osm(location, radius, data_types), source="synthetic")


def _handle_connectivity(args: dict[str, Any], **_: Any) -> str:
    graph = args.get("road_graph") or args.get("graph") or {}
    if hasattr(graph, "degree"):
        degrees = [degree for _, degree in graph.degree()]
        node_count = len(graph.nodes())
        edge_count = len(graph.edges())
    else:
        nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
        edges = graph.get("edges", []) if isinstance(graph, dict) else []
        degree_counter: Counter[str] = Counter()
        for edge in edges:
            u = str(edge.get("u") or edge.get("source") or "")
            v = str(edge.get("v") or edge.get("target") or "")
            if u:
                degree_counter[u] += 1
            if v:
                degree_counter[v] += 1
        node_ids = [str(node.get("id")) for node in nodes if isinstance(node, dict)]
        for node_id in node_ids:
            degree_counter.setdefault(node_id, 0)
        degrees = list(degree_counter.values())
        node_count = len(node_ids) or len(degree_counter)
        edge_count = len(edges)
    average_degree = sum(degrees) / len(degrees) if degrees else 0.0
    density = (2 * edge_count / (node_count * (node_count - 1))) if node_count > 1 else 0.0
    isolated = sum(1 for degree in degrees if degree == 0)
    return _ok(
        {
            "average_degree": average_degree,
            "max_degree": max(degrees) if degrees else 0,
            "node_count": node_count,
            "edge_count": edge_count,
            "density": density,
            "isolated_nodes": isolated,
            "connectivity_class": "high" if average_degree >= 2.5 else "moderate" if average_degree >= 1.5 else "low",
        }
    )


def _handle_accessibility(args: dict[str, Any], **_: Any) -> str:
    buildings = _feature_list(args.get("buildings") or args.get("origins") or [])
    target_points = [_point_like(item) for item in args.get("target_points") or args.get("targets") or []]
    target_points = [item for item in target_points if item is not None]
    max_distance = float(args.get("max_distance") or args.get("threshold") or 500)
    if not buildings or not target_points:
        return _fail("buildings and target_points are required")
    distances: list[float] = []
    for feature in buildings:
        centroid = _feature_centroid(feature)
        if centroid is None:
            continue
        distances.append(min(_distance_m(centroid, target) for target in target_points))
    if not distances:
        return _fail("no valid building centroids found")
    distances_sorted = sorted(distances)
    return _ok(
        {
            "origin_count": len(distances),
            "target_count": len(target_points),
            "average_distance_m": sum(distances) / len(distances),
            "median_distance_m": distances_sorted[len(distances_sorted) // 2],
            "coverage_ratio": sum(1 for item in distances if item <= max_distance) / len(distances),
            "within_100m": sum(1 for item in distances if item <= 100) / len(distances),
            "within_300m": sum(1 for item in distances if item <= 300) / len(distances),
        }
    )


def _handle_density(args: dict[str, Any], **_: Any) -> str:
    features = _feature_list(args.get("buildings") or args.get("features") or [])
    grid_size = float(args.get("grid_size") or 100)
    if not features:
        return _fail("features or buildings are required")
    bbox = _features_bbox(features)
    if bbox is None:
        return _fail("could not derive feature bounds")
    width_m = max(1.0, _distance_m((bbox[0], bbox[1]), (bbox[2], bbox[1])))
    height_m = max(1.0, _distance_m((bbox[0], bbox[1]), (bbox[0], bbox[3])))
    x_cells = max(1, math.ceil(width_m / grid_size))
    y_cells = max(1, math.ceil(height_m / grid_size))
    cells = [0.0 for _ in range(x_cells * y_cells)]
    for feature in features:
        centroid = _feature_centroid(feature)
        if centroid is None:
            continue
        x_ratio = (centroid[0] - bbox[0]) / max(bbox[2] - bbox[0], 1e-12)
        y_ratio = (centroid[1] - bbox[1]) / max(bbox[3] - bbox[1], 1e-12)
        x_idx = min(x_cells - 1, max(0, int(x_ratio * x_cells)))
        y_idx = min(y_cells - 1, max(0, int(y_ratio * y_cells)))
        cells[y_idx * x_cells + x_idx] += _feature_area_m2(feature)
    mean_density = sum(cells) / len(cells)
    variance = sum((cell - mean_density) ** 2 for cell in cells) / len(cells)
    uniformity = 1.0 / ((math.sqrt(variance) / (mean_density + 1e-9)) + 1.0)
    return _ok(
        {
            "grid_shape": [y_cells, x_cells],
            "mean_density": mean_density,
            "max_density": max(cells) if cells else 0.0,
            "uniformity": uniformity,
            "bbox": bbox,
        }
    )


def _handle_svg(args: dict[str, Any], **_: Any) -> str:
    base_features = args.get("base_features") or args.get("features") or {}
    interventions = args.get("interventions") or args.get("intervention_areas") or []
    bbox = [float(item) for item in args.get("bbox") or _infer_bbox(base_features) or [0, 0, 1, 1]]
    width = int(args.get("width") or 800)
    height = int(args.get("height") or max(300, width * 0.65))
    svg = _make_svg(base_features, interventions, bbox, width, height)
    return _ok({"svg_content": svg, "format": "svg", "size": len(svg), "bbox": bbox})


def _handle_geojson(args: dict[str, Any], **_: Any) -> str:
    features = args.get("features") or []
    crs = str(args.get("crs") or "EPSG:4326")
    collection = _feature_collection(features, crs=crs)
    return _ok({"geojson": collection, "feature_count": len(collection["features"])})


def _handle_topology(args: dict[str, Any], **_: Any) -> str:
    features = _feature_list(args.get("features") or args.get("base_features") or [])
    threshold = float(args.get("relation_threshold") or 100)
    nodes = []
    for index, feature in enumerate(features):
        centroid = _feature_centroid(feature)
        if centroid is None:
            continue
        nodes.append(
            {
                "id": str(feature.get("id") or feature.get("properties", {}).get("id") or f"node_{index + 1}"),
                "type": _infer_feature_type(feature),
                "centroid": list(centroid),
                "properties": dict(feature.get("properties") or {}),
            }
        )
    relations = []
    for left_index, left in enumerate(nodes):
        for right in nodes[left_index + 1 :]:
            distance = _distance_m(tuple(left["centroid"]), tuple(right["centroid"]))
            if distance <= threshold:
                relations.append(
                    {
                        "source": left["id"],
                        "target": right["id"],
                        "relation": "adjacent" if distance <= threshold / 2 else "connected",
                        "distance_m": distance,
                    }
                )
    return _ok({"nodes": nodes, "relations": relations, "threshold_m": threshold})


def _handle_ground_task(args: dict[str, Any], **_: Any) -> str:
    task_data = args.get("task_data") if isinstance(args.get("task_data"), dict) else dict(args)
    task_text = str(args.get("task") or task_data.get("task") or task_data.get("question") or task_data)
    capability_pack = json.loads(_handle_capabilities({"task": task_text, "limit": args.get("capability_limit", 6)}))["result"]
    research_memory = _search_research_memory(task_text, limit=int(args.get("research_memory_limit") or 4))
    evidence = _build_evidence_manifest(task_data, task_text)
    gaps = _evidence_gaps(evidence, task_text)
    dataset_cards = _dataset_cards(task_data, evidence)
    plan = _execution_plan(task_text, capability_pack, evidence, gaps, research_memory=research_memory)
    grounding = {
        "status": "grounded_with_gaps" if gaps else "grounded",
        "task": task_text,
        "capability_context": capability_pack,
        "research_design_memory": research_memory,
        "dataset_cards": dataset_cards,
        "evidence_manifest": evidence,
        "grounding_gaps": gaps,
        "execution_plan": plan,
        "quality_gate": {
            "mode": "configurator",
            "passed": not any(item.get("severity") == "critical" for item in gaps),
            "checked_at": datetime.now().isoformat(),
        },
    }
    return _ok(grounding)


def _handle_route_tree(args: dict[str, Any], **_: Any) -> str:
    """Maintain a generic planner route tree and export it for CLI/frontend review."""
    try:
        result = run_route_tree_action(args)
        return _ok(result, action=args.get("action") or "export", host=os.name)
    except Exception as exc:
        return _fail(str(exc), action=args.get("action") or "export", host=os.name)


def _flatten_review_terms(value: Any, *, prefix: str = "") -> list[str]:
    terms: list[str] = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_text = f"{prefix}.{key}" if prefix else str(key)
            terms.append(key_text)
            terms.extend(_flatten_review_terms(nested_value, prefix=key_text))
    elif isinstance(value, list):
        for index, nested_value in enumerate(value[:50]):
            terms.extend(_flatten_review_terms(nested_value, prefix=f"{prefix}[{index}]"))
    elif isinstance(value, (str, int, float, bool)) and value is not None:
        terms.append(str(value))
    return terms


def _score_artifact_readiness(results: Any) -> dict[str, Any]:
    payload = results if isinstance(results, dict) else {}
    issues: list[str] = []
    review_text = "\n".join(_flatten_review_terms(payload)).lower()
    spatial_like = any(token in review_text for token in ("spatial", "map", "geojson", "gis", "qgis", "layer", ".qgs", ".qgz"))
    signals = {
        "tables": any(token in review_text for token in ("csv", "table", "dataframe")),
        "figures": any(token in review_text for token in ("figure", "plot", "map", ".png", ".svg", ".pdf")),
        "gis_layers": any(token in review_text for token in ("geojson", "layer", "qgis", ".qgs", ".qgz", "shapefile", "filegdb")),
        "manifest": any(token in review_text for token in ("manifest", "schema", "metadata")),
        "model_outputs": any(token in review_text for token in ("model", "diagnostic", "residual", "pdp", "shap", "cross-validation", "cv")),
    }
    artifact_paths = payload.get("artifact_paths") or payload.get("outputs") or payload.get("artifacts") or []
    if isinstance(artifact_paths, dict):
        artifact_paths = list(artifact_paths.values())
    if artifact_paths:
        signals["declared_paths"] = True
    if not any(signals.values()):
        issues.append("no explicit downstream artifact, table, map, model, GIS layer, or manifest signal was provided")

    artifact_manifest = payload.get("artifact_manifest")
    if isinstance(artifact_manifest, dict):
        manifest_counts: dict[str, int] = {}
        for key, value in artifact_manifest.items():
            if isinstance(value, list):
                manifest_counts[key] = len(value)
            elif value:
                manifest_counts[key] = 1
            else:
                manifest_counts[key] = 0
        signals["artifact_manifest_counts"] = manifest_counts
        if sum(manifest_counts.values()) == 0:
            issues.append("artifact_manifest is present but empty")
        map_count = manifest_counts.get("figures", 0) + manifest_counts.get("maps", 0)
        gis_count = manifest_counts.get("gis_layers", 0) + manifest_counts.get("layers", 0)
        manifest_count = manifest_counts.get("manifests", 0)
        if spatial_like and map_count == 0 and gis_count == 0:
            issues.append("spatial artifact package has no reusable map, figure, or GIS layer")
        if spatial_like and "spatial_reasoning_manifest" not in review_text:
            issues.append("spatial artifact package has no spatial reasoning manifest")
        score = max(0.0, 1.0 - 0.18 * len(issues))
        if spatial_like and (map_count == 0 and gis_count == 0 or "spatial_reasoning_manifest" not in review_text):
            score = min(score, 0.55)
    else:
        if spatial_like and "manifest" not in review_text:
            issues.append("spatial artifact output has no manifest")
        score = 1.0 if any(signals.values()) and not issues else max(0.0, 0.75 - 0.15 * len(issues)) if any(signals.values()) else 0.45
    return {"score": score, "issues": issues, "signals": signals, "applicable": True}


def _score_method_requirements(results: Any) -> dict[str, Any]:
    """Check model-specific inputs/parameters without hard-coding a case workflow."""
    review_text = "\n".join(_flatten_review_terms(results if isinstance(results, dict) else {})).lower()
    if not review_text:
        review_text = json.dumps(results, ensure_ascii=False, default=str).lower()
    method_terms = (
        "gwr",
        "mgwr",
        "gtwr",
        "gwrf",
        "random forest",
        "rf",
        "shap",
        "pdp",
        "partial dependence",
        "temporal regression",
        "period-specific",
        "weekday",
        "weekend",
        "morning_peak",
        "evening_peak",
        "street-view",
        "street view",
        "perception",
        "image-grid",
    )
    if not any(term in review_text for term in method_terms):
        return {"score": 1.0, "issues": [], "signals": {}, "applicable": False}

    issues: list[str] = []
    has_gwr = bool(re.search(r"(?<![a-z0-9_])(?:gwr|mgwr|gtwr)(?![a-z0-9_])", review_text))
    has_gwrf = bool(re.search(r"(?<![a-z0-9_])gwrf(?![a-z0-9_])", review_text))
    signals: dict[str, Any] = {
        "mentions_gwr": has_gwr,
        "mentions_gwrf": has_gwrf,
        "mentions_explainability": any(term in review_text for term in ("shap", "pdp", "partial dependence")),
        "mentions_temporal_model": any(term in review_text for term in ("temporal regression", "period-specific", "weekday", "weekend", "morning_peak", "evening_peak", "fixed effect", "panel")),
        "mentions_perception": any(term in review_text for term in ("street-view", "street view", "perception", "image-grid")),
    }

    if signals["mentions_gwr"]:
        if not any(term in review_text for term in ("bandwidth", "bw", "adaptive", "fixed bandwidth")):
            issues.append("GWR/MGWR/GTWR branch mentions the method but not spatial bandwidth")
        if "kernel" not in review_text:
            issues.append("GWR/MGWR/GTWR branch does not state kernel")
        if not any(term in review_text for term in ("crs", "projected", "centroid", "coordinate", "geometry")):
            issues.append("GWR/MGWR/GTWR branch does not state projected coordinates or geometry basis")
        if "local multicollinearity" not in review_text and "condition number" not in review_text:
            issues.append("GWR/MGWR/GTWR branch does not mention local multicollinearity or condition-number diagnostics")

    if signals["mentions_gwrf"]:
        if not any(term in review_text for term in ("bandwidth", "neighbor", "neighbour", "k=", "k-neighbor", "local window", "adaptive")):
            issues.append("GWRF branch does not state spatial bandwidth/neighborhood")
        if not any(term in review_text for term in ("local rf", "local random forest", "geographically weighted", "sample_weight", "weighted")):
            issues.append("GWRF branch does not clarify the local/weighted RF design")
        if not any(term in review_text for term in ("local importance", "local feature", "local prediction", "residual")):
            issues.append("GWRF branch lacks expected local prediction/importance/residual artifacts")

    if signals["mentions_explainability"]:
        if not any(term in review_text for term in ("fitted model", "trained model", "rf model", "local rf", "model output")):
            issues.append("SHAP/PDP branch does not state the fitted model it explains")
        if not any(term in review_text for term in ("model explanation", "model behavior", "not causal", "not mechanism", "downgrade")):
            issues.append("SHAP/PDP branch lacks model-explanation claim boundary")

    if signals["mentions_temporal_model"]:
        if not any(term in review_text for term in ("weekday", "weekend", "period", "morning", "evening", "night", "daytime", "date", "time split", "fixed effect")):
            issues.append("temporal model branch does not state time split or temporal grouping")
        if not any(term in review_text for term in ("aggregate", "panel", "grid-date", "grid_date", "period-specific", "stratified")):
            issues.append("temporal model branch does not state whether it is stratified, aggregate, or panel-like")

    perception_blocked = signals["mentions_perception"] and any(term in review_text for term in ("blocked", "block until", "missing", "not supplied", "absent"))
    if signals["mentions_perception"] and not perception_blocked:
        if not any(term in review_text for term in ("alignment", "image-grid", "image grid", "coordinate", "lon", "lat", "geotag")):
            issues.append("street-view/perception branch does not state image-coordinate or image-grid alignment")
        if not any(term in review_text for term in ("coverage", "images per grid", "grid coverage", "manifest", "inventory")):
            issues.append("street-view/perception branch lacks image coverage or alignment manifest artifact")

    score = max(0.0, 1.0 - 0.10 * len(issues))
    if any("bandwidth" in issue or "image-coordinate" in issue for issue in issues):
        score = min(score, 0.70)
    return {"score": score, "issues": issues, "signals": signals, "applicable": True}


def _has_review_field(review: dict[str, Any], aliases: Iterable[str]) -> bool:
    for alias in aliases:
        if alias in review and review[alias] not in (None, "", [], {}):
            return True
    return False


def _load_json_path(value: Any, *, max_bytes: int = 5_000_000) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.strip().strip('"')
    if not candidate.lower().endswith(".json"):
        return value
    try:
        path = Path(candidate)
        if not path.is_file() or path.stat().st_size > max_bytes:
            return value
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return value


def _as_record_list(value: Any) -> list[dict[str, Any]]:
    value = _load_json_path(value)
    if isinstance(value, dict):
        if any(isinstance(nested, dict) for nested in value.values()):
            return [nested for nested in value.values() if isinstance(nested, dict)]
        return [value]
    if isinstance(value, list):
        records: list[dict[str, Any]] = []
        for item in value:
            loaded = _load_json_path(item)
            if isinstance(loaded, dict):
                records.append(loaded)
        return records
    return []


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


def _extract_route_nodes(route_tree: Any) -> list[dict[str, Any]]:
    route_tree = _load_json_path(route_tree)
    if isinstance(route_tree, dict):
        for key in ("nodes", "route_nodes", "branches", "routes"):
            nodes = route_tree.get(key)
            if isinstance(nodes, list):
                return [node for node in nodes if isinstance(node, dict)]
        return [route_tree] if any(key in route_tree for key in ("node_type", "branch_id", "node_id")) else []
    if isinstance(route_tree, list):
        return [node for node in route_tree if isinstance(node, dict)]
    return []


def _text_has_any(value: Any, terms: tuple[str, ...]) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).lower()
    return any(term in text for term in terms)


def _validate_typed_route_tree(route_tree: Any) -> list[str]:
    nodes = _extract_route_nodes(route_tree)
    if not nodes:
        return []

    issues: list[str] = []
    node_types: dict[str, str] = {}
    for index, node in enumerate(nodes, start=1):
        node_id = str(node.get("node_id") or node.get("branch_id") or node.get("id") or f"node_{index}")
        node_type = str(node.get("node_type") or node.get("type") or "").strip()
        if not node_type:
            issues.append(f"route node {node_id} has no node_type")
        elif node_type not in ROUTE_NODE_TYPES:
            issues.append(f"route node {node_id} has unsupported node_type '{node_type}'")
        node_types[node_id] = node_type

        parent_nodes = node.get("parent_nodes") or node.get("depends_on") or node.get("parents") or []
        if isinstance(parent_nodes, str):
            parent_nodes = [parent_nodes]
        dependency_list = node.get("requires") or parent_nodes

        if node_type != "research_object" and dependency_list in (None, "", [], {}):
            issues.append(f"route node {node_id} has no requires/dependency list")
        if (
            node.get("expected_artifacts") in (None, "", [], {})
            and node.get("expected_outputs") in (None, "", [], {})
            and node.get("outputs") in (None, "", [], {})
        ):
            issues.append(f"route node {node_id} has no outputs or expected_artifacts")

        meaning = node.get("time_space_people") or node.get("meaning_review") or {}
        has_tsp = isinstance(meaning, dict) and all(key in meaning for key in ("time", "space", "people"))
        has_tsp = has_tsp or all(node.get(key) not in (None, "", [], {}) for key in ("time", "space", "people"))
        if not has_tsp:
            issues.append(f"route node {node_id} does not state time, space, and people meaning")

        if node_type == "research_object":
            if not _text_has_any(node, ("spatial unit", "grid", "hex", "segment", "block", "空间", "网格")):
                issues.append(f"research_object node {node_id} does not declare spatial unit")
            if not _text_has_any(node, ("time", "week", "weekday", "weekend", "period", "temporal", "时间", "时段")):
                issues.append(f"research_object node {node_id} does not declare temporal design")
            if not _text_has_any(node, ("outcome", "dependent", "activity", "vitality", "因变量")):
                issues.append(f"research_object node {node_id} does not declare outcome meaning")

        if node_type in {"feature_package", "data_preparation"} and not parent_nodes:
            issues.append(f"{node_type} node {node_id} has no parent research_object")

        if node_type == "model_execution":
            if not parent_nodes and not _text_has_any(node.get("requires"), (" y", "outcome", " x", "feature", "aligned")):
                issues.append(f"model_execution node {node_id} does not depend on research object and feature package")
            if _text_has_any(node, ("gwr", "gwrf", "spatial heterogeneity")):
                if not _text_has_any(node, ("bandwidth", "kernel", "neighbor", "projected", "crs", "coordinate")):
                    issues.append(f"spatial model node {node_id} does not expose bandwidth/kernel/coordinate requirements")

        if node_type == "model_explanation":
            if not parent_nodes and not _text_has_any(node.get("requires"), ("fitted model", "trained model", "model output")):
                issues.append(f"model_explanation node {node_id} does not depend on a fitted model")
            if _text_has_any(node, ("shap", "pdp", "partial dependence")) and not _text_has_any(node, ("fitted", "trained", "model version")):
                issues.append(f"SHAP/PDP node {node_id} does not state fitted-model dependency")

        if node_type == "diagnostic" and not parent_nodes:
            issues.append(f"diagnostic node {node_id} has no fitted model or artifact parent")

        if node_type in {"route_comparison", "report_option"}:
            if not parent_nodes and not _text_has_any(dependency_list, ("route", "branch", "review", "artifact", "claim gate")):
                issues.append(f"{node_type} node {node_id} does not depend on completed route outputs or reviews")

        if node_type == "claim_synthesis":
            if not parent_nodes and not _text_has_any(dependency_list, ("completed", "route output", "branch output", "review", "claim gate", "route_comparison", "report_option")):
                issues.append(f"claim_synthesis node {node_id} does not require completed route outputs and reviews")

    has_explanation = any(node_type == "model_explanation" for node_type in node_types.values())
    has_model = any(node_type == "model_execution" for node_type in node_types.values())
    if has_explanation and not has_model:
        issues.append("route tree contains model_explanation but no model_execution node")
    return issues


def _is_workflow_trace_payload(value: Any) -> bool:
    return isinstance(value, dict) and any(
        key in value
        for key in (
            "workflow_trace",
            "main_workflow_plan",
            "human_plan_decision",
            "plan_approval",
            "worker_task_records",
            "per_step_review_records",
            "branch_tree",
            "branch_progress",
            "human_branch_decisions",
            "claim_gates",
            "artifact_manifest",
        )
    )


def _score_trace_completeness(results: Any, args: dict[str, Any]) -> dict[str, Any]:
    payload = results if isinstance(results, dict) else {}
    review_text = "\n".join(_flatten_review_terms(payload)).lower()
    trace_markers = {
        "main_workflow_plan",
        "human_plan_decision",
        "plan_approval",
        "worker_task_records",
        "parent_verification",
        "per_step_review_records",
        "claim_gates",
        "artifact_manifest",
        "branch_tree",
        "branch_progress",
        "human_branch_decisions",
        "memory_retrieval_log",
        "worker_reflection",
        "reviewer_reflection",
        "main_reflection",
        "memory_carryover",
        "workflow_trace",
        "steps",
    }
    stage = str(args.get("stage") or "").lower()
    trace_like = (
        any(marker in payload for marker in trace_markers)
        or "final" in stage
        or "trace" in stage
        or "workflow_trace" in review_text
    )
    if not trace_like:
        return {"score": 1.0, "issues": [], "signals": {}, "applicable": False}

    issues: list[str] = []
    required_trace_fields = [
        "main_workflow_plan",
        "worker_task_records",
        "parent_verification",
        "per_step_review_records",
        "claim_gates",
        "artifact_manifest",
        "worker_reflection",
        "reviewer_reflection",
        "main_reflection",
        "memory_carryover",
    ]
    for field in required_trace_fields:
        if payload.get(field) in (None, "", [], {}):
            issues.append(f"trace missing or empty: {field}")

    plan_decision = (
        payload.get("human_plan_decision")
        or payload.get("plan_approval")
        or payload.get("human_plan_approval")
    )
    if plan_decision in (None, "", [], {}):
        issues.append("trace missing or empty: human_plan_decision/plan_approval")
    elif isinstance(plan_decision, dict):
        decision_text = json.dumps(plan_decision, ensure_ascii=False, default=str).lower()
        if not any(term in decision_text for term in ("approve", "approved", "revise", "revision", "block", "blocked", "continue")):
            issues.append("human_plan_decision/plan_approval does not record approve, revise, block, or continue")
        if not any(term in decision_text for term in ("shown", "visible", "cli", "presented", "rendered")):
            issues.append("human_plan_decision/plan_approval does not state that the plan was visibly shown to the user")

    worker_records = _as_record_list(payload.get("worker_task_records"))
    delegation_skipped = payload.get("delegation_skipped_reason") or payload.get("delegation_omission_reason")
    if worker_records:
        worker_ids = {str(record.get("worker_id") or record.get("agent_id") or record.get("executor") or "").lower() for record in worker_records}
        actual_executors = {str(record.get("actual_executor") or record.get("executor") or "").lower() for record in worker_records}
        has_real_worker = any(worker_id and worker_id not in {"parent_agent", "main_agent", "parent", "main"} for worker_id in worker_ids)
        has_delegated_executor = any("delegate" in executor or "subagent" in executor for executor in actual_executors)
        has_main_fallback = any("fallback" in executor or "main_agent" in executor or "parent_agent" in executor for executor in actual_executors)
        if not (has_real_worker or has_delegated_executor) and not delegation_skipped:
            issues.append("worker_task_records only contain the parent/main agent; no real delegated worker or skip reason is recorded")
        if has_main_fallback and not payload.get("delegation_recovery"):
            issues.append("main-agent fallback is recorded without a delegation_recovery record")

    if any(term in review_text for term in ("worker-reviewer", "worker reviewer", "dialogue_turns", "reviewer_critique")):
        if "delegate_subagent" not in review_text and "delegate_task" not in review_text and "subagent" not in review_text:
            issues.append("worker-reviewer dialogue trace has no delegated worker/reviewer executor evidence")

    branch_like = any(
        term in review_text
        for term in (
            "branch_tree",
            "branch progress",
            "branch_candidates",
            "suggested branch",
            "deferred branch",
            "gwr",
            "gwrf",
            "shap",
            "pdp",
            "street-view",
            "perception",
            "weekday",
            "weekend",
            "period-specific",
        )
    )
    if branch_like:
        if payload.get("branch_tree") in (None, "", [], {}):
            issues.append("branch-like workflow has no branch_tree")
        if payload.get("branch_progress") in (None, "", [], {}):
            issues.append("branch-like workflow has no branch_progress")
        branch_decision = payload.get("human_branch_decisions") or payload.get("human_plan_decision") or payload.get("plan_approval")
        if branch_decision in (None, "", [], {}):
            issues.append("branch-like workflow has no human branch or plan decision record")
        if payload.get("memory_retrieval_log") in (None, "", [], {}) and any(term in review_text for term in ("gwr", "gwrf", "shap", "pdp", "perception")):
            issues.append("method-branch workflow has no memory_retrieval_log for on-demand method memory")
        route_tree = payload.get("typed_route_tree") or payload.get("branch_tree") or payload.get("route_tree")
        issues.extend(_validate_typed_route_tree(route_tree))

    if "in_progress" in review_text:
        issues.append("trace still contains an in_progress status")

    step_records = _as_record_list(payload.get("per_step_review_records"))
    if not step_records:
        step_records = [
            step.get("review")
            for step in _as_record_list(payload.get("steps"))
            if isinstance(step.get("review"), dict)
        ]
    if not step_records:
        issues.append("trace has no structured per-step reviewer pause records")

    required_step_fields = {
        "actual_executor": ("actual_executor", "executor", "worker_or_tool_task"),
        "review_target_type": ("review_target_type", "target_type", "review_object"),
        "time_implications": ("time_implications", "time", "temporal_implications", "temporal_review", "time_review"),
        "space_implications": ("space_implications", "space", "spatial_implications", "spatial_review", "space_review"),
        "people_implications": ("people_implications", "people", "population_implications", "stakeholder_implications", "people_review"),
        "method_requirement_review": ("method_requirement_review", "method_review", "method_requirements"),
        "ignored_or_missing_evidence": ("ignored_or_missing_evidence", "missing_evidence", "ignored_evidence", "evidence_gaps"),
        "assumptions": ("assumptions", "assumption_boundary", "working_assumptions"),
        "further_analysis": ("further_analysis", "next_analysis", "additional_analysis", "could_analyze"),
        "branch_candidates": ("branch_candidates", "suggested_branches", "new_branches", "branch_progress_update"),
        "artifact_readiness": ("artifact_readiness", "artifact_review", "readiness"),
        "claim_impact": ("claim_impact", "claim_gate", "claim_boundary", "claim_gates"),
        "next_action": ("next_action", "decision", "intervention_decision"),
    }
    for index, review in enumerate(step_records, start=1):
        missing = [
            field
            for field, aliases in required_step_fields.items()
            if not _has_review_field(review, aliases)
        ]
        if missing:
            step_id = review.get("step_id") or review.get("main_plan_step") or f"step_{index}"
            issues.append(f"per-step review {step_id} missing fields: {', '.join(missing)}")

    risky_claim_terms = (
        "causal",
        "causality",
        "policy",
        "intervention",
        "people-specific",
        "demographic",
        "perception",
        "street-view",
        "gwr",
        "gwrf",
        "shap",
        "mechanism",
        "local mechanism",
    )
    gate_terms = ("downgrade", "block", "gated", "gate", "unsupported")
    if any(term in review_text for term in risky_claim_terms) and not any(term in review_text for term in gate_terms):
        issues.append("risky causal, policy, people-specific, perception, or local-mechanism claims appear without downgrade/block gates")

    failure_terms = ("worker_failed", "worker failure", "worker failed", "timeout", "timed out", "interrupted", "delegate error", "subagent error")
    recovery_terms = ("recovery", "fallback", "main-agent fallback", "parent recovery", "takeover")
    if any(term in review_text for term in failure_terms) and not any(term in review_text for term in recovery_terms):
        issues.append("worker failure/interruption appears without an explicit recovery path")

    spatial_terms = ("spatial", "map", "geojson", "gis", "qgis", "layer", ".qgs", ".qgz")
    if any(term in review_text for term in spatial_terms) and "manifest" not in review_text:
        issues.append("spatial artifact trace is missing a reusable manifest")

    people_review_text = "\n".join(
        str(record.get(alias) or "")
        for record in step_records
        for alias in (
            "people_implications",
            "people",
            "population_implications",
            "stakeholder_implications",
            "people_review",
        )
    ).lower()
    if any(term in review_text for term in ("people", "population", "stakeholder")):
        if not people_review_text.strip():
            issues.append("people/stakeholder lens is named but no per-step people implications are recorded")
        elif not any(term in people_review_text for term in ("proxy", "missing", "not individual", "activity", "stakeholder", "user", "demographic", "behavior")):
            issues.append("people/stakeholder review does not state whether people evidence is direct, proxied, missing, or activity-based")

    reviewer_reflection = payload.get("reviewer_reflection")
    if isinstance(reviewer_reflection, dict):
        reviewer_text = json.dumps(reviewer_reflection, ensure_ascii=False, default=str).lower()
        if "revise" in reviewer_text or "hard_failures" in reviewer_text:
            issues.append("reviewer_reflection records unresolved revise recommendation or hard failures")

    validation_status = payload.get("validation_status")
    positive_validation_claim = payload.get("validated") is True
    if isinstance(validation_status, dict):
        positive_validation_claim = positive_validation_claim or validation_status.get("validated") is True
        positive_validation_claim = positive_validation_claim or str(validation_status.get("overall") or "").lower() in {
            "valid",
            "validated",
            "pass",
            "passed",
            "ready",
            "fully_validated",
        }
    elif isinstance(validation_status, str):
        positive_validation_claim = positive_validation_claim or validation_status.lower() in {
            "valid",
            "validated",
            "pass",
            "passed",
            "ready",
            "fully_validated",
        }
    if not positive_validation_claim:
        positive_validation_claim = any(
            phrase in review_text
            for phrase in ("fully validated", "trace validated", "run validated", "validation passed")
        ) and not any(
            phrase in review_text
            for phrase in ("not validated", "not_validated", "validated: false", '"validated": false')
        )
    if positive_validation_claim and any(term in review_text for term in ("revise", "below threshold", "hard failure", "hard_failures")):
        issues.append("trace claims validation while unresolved review failures remain")

    score = max(0.0, 1.0 - 0.08 * len(issues))
    if any(
        issue.startswith("worker_task_records only contain")
        or issue.startswith("worker-reviewer dialogue trace has no delegated")
        for issue in issues
    ):
        score = min(score, 0.50)
    signals = {
        "trace_like": trace_like,
        "per_step_review_count": len(step_records),
        "required_trace_fields_present": [field for field in required_trace_fields if payload.get(field) not in (None, "", [], {})],
        "human_plan_decision_present": plan_decision not in (None, "", [], {}),
    }
    return {"score": score, "issues": issues, "signals": signals, "applicable": True}


REVIEWER_PAUSE_GUIDANCE: dict[str, Any] = {
    "purpose": (
        "Pause before the workflow moves on. This is a review hub: choose the review lens "
        "from the target being inspected instead of applying one fixed checklist."
    ),
    "target_types": {
        "plan": "Review research meaning, data-method fit, branch tree, human choices, and time-space-people implications before execution.",
        "route_tree": "Review node types, parent dependencies, allowed child nodes, human choices, and whether analysis routes are at the right research-design level.",
        "method_branch": "Review model-specific input requirements, parameters, diagnostics, and interpretation boundaries.",
        "worker_output": "Review concrete artifacts, schemas, model outputs, maps/layers, and whether the output can be a downstream input.",
        "claim_synthesis": "Review whether multiple analysis routes support the same claim, condition it by time or space, or require downgrade.",
        "final_trace": "Review trace completeness, branch progress, human decisions, memory retrieval, claim gates, and artifact manifest.",
    },
    "lenses": [
        {
            "lens_id": "time",
            "label": "Time",
            "questions": [
                "What temporal meaning does this step introduce or rely on?",
                "What time window, granularity, freshness, dynamics, or long-term claim is missing or ignored?",
                "What temporal assumptions should be carried into the next step?",
                "What further temporal analysis would be possible if more evidence were available?",
            ],
        },
        {
            "lens_id": "space",
            "label": "Space",
            "questions": [
                "What spatial meaning does this step introduce or rely on?",
                "What AOI, CRS, spatial unit, scale, boundary effect, or heterogeneity is missing or ignored?",
                "What spatial assumptions should be carried into the next step?",
                "What further spatial analysis would be possible if more evidence were available?",
            ],
        },
        {
            "lens_id": "people",
            "label": "People",
            "questions": [
                "What people, activity, stakeholder, or urban-use meaning does this step imply?",
                "Which users, behaviors, demographics, or stakeholder voices are missing or only proxied?",
                "What people-related assumptions should be carried into the next step?",
                "What further people or activity analysis would be possible if more evidence were available?",
            ],
        },
    ],
    "claim_boundary": (
        "Use the pause to decide whether the next claim should proceed, branch, be downgraded, "
        "or be blocked until stronger evidence or artifacts exist."
    ),
    "dynamic_branching": (
        "Review can discover new branches during execution, not only during planning. Save candidate "
        "branches with required inputs, method parameters, time-space-people meaning, expected artifacts, "
        "claim boundary, and status such as suggested, approved, active, deferred, blocked, or completed."
    ),
    "typed_route_tree": {
        "node_types": sorted(ROUTE_NODE_TYPES),
        "required_node_fields": [
            "node_id",
            "node_type",
            "parent_nodes",
            "requires",
            "expected_artifacts or outputs",
            "time_space_people",
            "claim_boundary",
            "status",
            "human_choice",
        ],
        "dependency_rule": (
            "research_object defines spatial unit, temporal design, and outcome meaning; feature_package "
            "depends on a research_object; model_execution depends on research_object + feature_package; "
            "model_explanation depends on a fitted model; diagnostic depends on a fitted model or artifact; "
            "claim_synthesis depends on completed route outputs and reviews."
        ),
        "reject_examples": [
            "SHAP/PDP listed as a peer of GWR instead of as an explanation node for a fitted RF/GWRF model",
            "street-view alignment treated as a perception-effect claim before perception features exist",
            "GWR/GWRF branch missing bandwidth, kernel, coordinates, or neighborhood requirements",
        ],
    },
    "analysis_route_comparison": (
        "When multiple approved branches address the same urban question, compare their outputs in a shared "
        "claim-calibration table. The planner should check whether a candidate claim is supported globally, "
        "stable across time splits, spatially consistent or local, and valid under people/data-proxy boundaries. "
        "Use plain decisions such as stable support, conditional support, insufficient interpretation, or unsupported."
    ),
    "method_requirement_review": {
        "GWR_MGWR_GTWR": [
            "Y and X aligned to the same spatial unit",
            "projected coordinates or geometry basis",
            "spatial bandwidth and selection rule",
            "kernel and fixed/adaptive choice",
            "local multicollinearity or condition-number diagnostics",
            "local coefficients downgraded to association diagnostics unless causal design exists",
        ],
        "GWRF": [
            "Y and X aligned to the same spatial unit",
            "projected coordinates or geometry basis",
            "spatial bandwidth/neighborhood size",
            "local/weighted RF design and validation scheme",
            "local prediction, local feature reliance, and residual artifacts",
            "feature reliance downgraded to model behavior unless stronger evidence exists",
        ],
        "temporal_regression": [
            "time split design such as weekday/weekend, period-specific, grid-date-period, or fixed effects",
            "whether X varies over time or is time-invariant",
            "whether the branch is descriptive, stratified association, panel-like, or causal",
            "claim boundary for seasonality, events, long-term dynamics, and individual behavior",
        ],
        "SHAP_PDP": [
            "fitted model being explained",
            "global vs local explanation scope",
            "feature support and collinearity caveats",
            "model explanation distinguished from urban mechanism or intervention effect",
        ],
        "street_view_perception": [
            "image inventory and coordinate parsing",
            "image-grid or image-segment alignment manifest",
            "grid coverage and images-per-unit distribution",
            "perception scorer/features and aggregation rule",
            "sampling, timestamp, viewpoint, and people-claim boundaries",
        ],
    },
    "save_record": {
        "recommended_file": "workflow_trace.json or step_reviews/<step_id>_review.json",
        "granularity": "Save one reviewer pause record for each execution step, not only one final review.",
        "minimum_fields": [
            "step_id",
            "main_plan_step",
            "review_target_type",
            "worker_or_tool_task",
            "actual_executor",
            "time_implications",
            "space_implications",
            "people_implications",
            "method_requirement_review",
            "ignored_or_missing_evidence",
            "assumptions",
            "further_analysis",
            "branch_candidates",
            "branch_progress_update",
            "artifact_readiness",
            "claim_impact",
            "claim_gate",
            "decision",
            "next_action",
            "reflection_note",
        ],
        "trace_fields": [
            "main_workflow_plan",
            "human_plan_decision",
            "plan_approval",
            "worker_task_records",
            "parent_verification",
            "per_step_review_records",
            "branch_tree",
            "branch_progress",
            "human_branch_decisions",
            "claim_gates",
            "artifact_manifest",
            "delegation_recovery",
            "worker_reflection",
            "reviewer_reflection",
            "main_reflection",
            "memory_carryover",
            "memory_retrieval_log",
        ],
        "final_trace_self_check": (
            "Before finalizing, run urban_review on the saved trace. If trace_completeness_review "
            "or artifact_readiness_review fails, repair the trace or explicitly mark the run as not ready."
        ),
        "human_plan_gate": {
            "instruction": (
                "After writing workflow_plan.json, show a concise plan summary in the CLI and wait for "
                "approve, revise, or block before artifact-producing execution."
            ),
            "required_record_fields": [
                "plan_was_shown",
                "user_response",
                "decision",
                "requested_changes",
                "approved_steps",
                "timestamp",
            ],
        },
        "delegation_recovery": (
            "If any worker fails, times out, or is interrupted, preserve raw failure text, parent recovery, "
            "fallback artifacts, and verification status."
        ),
        "delegated_worker_packet": {
            "role": "worker",
            "instruction": "Use only the provided inputs, write artifacts into the assigned subdirectory, and do not make final claims.",
            "required_return_fields": [
                "role",
                "status",
                "files_written",
                "operations",
                "time_space_people_notes",
                "assumptions",
                "errors",
                "claim_boundaries",
            ],
        },
        "delegated_reviewer_packet": {
            "role": "reviewer",
            "instruction": "Inspect the named artifacts independently; judge readiness and claims instead of repairing artifacts silently.",
            "required_return_fields": [
                "role",
                "status",
                "checked_files",
                "time_review",
                "space_review",
                "people_review",
                "artifact_readiness",
                "claim_gates",
                "hard_failures",
                "recommendation",
            ],
        },
        "claim_gate_policy": (
            "Gate claims by claim type: allow supported descriptive associations; downgrade or block causal, "
            "policy/action, people-specific, perception, or local-mechanism claims when evidence is missing."
        ),
        "claim_gate_values": ["allow", "branch", "downgrade", "block"],
        "decision_values": ["proceed", "branch", "downgrade", "block"],
    },
}


def _handle_review(args: dict[str, Any], **_: Any) -> str:
    results = _load_json_path(args.get("results") or args.get("analysis") or args)
    evidence = args.get("evidence_manifest") or _find_evidence(results)
    trace_review = _score_trace_completeness(results, args)
    policy_scores = {
        "spatial_structural_review": _score_spatial(evidence, results),
        "temporal_consistency_review": _score_temporal(evidence, results),
        "population_and_stakeholder_review": _score_population(evidence, results),
        "method_requirement_review": _score_method_requirements(results),
        "evidence_and_governance_review": _score_governance(evidence, results),
        "trace_completeness_review": trace_review,
    }
    semantic_review = {
        "description": "Meaning-level review of the time, space, people, and governance assumptions carried into downstream reasoning.",
        "reviewer_pause_guidance": REVIEWER_PAUSE_GUIDANCE,
        "policies": {
            name: policy_scores[name]
            for name in (
                "spatial_structural_review",
                "temporal_consistency_review",
                "population_and_stakeholder_review",
                "method_requirement_review",
                "evidence_and_governance_review",
            )
        },
    }
    artifact_review = {
        "description": "Format-level review of whether outputs are usable as downstream tables, maps, model diagnostics, GIS layers, reports, or manifests.",
        "artifact_readiness_review": _score_artifact_readiness(results),
    }
    applicable_scores = [item["score"] for item in policy_scores.values() if item.get("applicable", True)]
    validity = sum(applicable_scores) / len(applicable_scores) if applicable_scores else 1.0
    issues = [issue for item in policy_scores.values() for issue in item.get("issues", [])]
    issues.extend(artifact_review["artifact_readiness_review"].get("issues", []))
    hard_failures = [name for name, item in policy_scores.items() if item["score"] < 0.55 and item.get("applicable", True)]
    artifact_score = artifact_review["artifact_readiness_review"].get("score", 1.0)
    if trace_review.get("applicable") and trace_review.get("score", 1.0) < 0.70:
        hard_failures.append("trace_completeness_review")
    if trace_review.get("applicable") and artifact_score < 0.70:
        hard_failures.append("artifact_readiness_review")
    hard_failures = list(dict.fromkeys(hard_failures))
    passed = validity >= float(args.get("threshold") or 0.70) and not hard_failures
    return _ok(
        {
            "urban_validity_score": validity,
            "quality_score": validity,
            "passed": passed,
            "policy_scores": policy_scores,
            "semantic_review": semantic_review,
            "artifact_review": artifact_review,
            "issues": issues,
            "hard_failures": hard_failures,
            "recommendation": "accept" if passed and not issues else "accept_with_warnings" if passed else "revise",
            "reviewed_at": datetime.now().isoformat(),
        }
    )


def _handle_quality(args: dict[str, Any], **_: Any) -> str:
    output = args.get("output") or args.get("results") or args
    required = [str(item) for item in args.get("required_fields") or []]
    issues = []
    if not isinstance(output, dict):
        issues.append("output is not a JSON object")
    for field in required:
        if isinstance(output, dict) and field not in output:
            issues.append(f"missing required field: {field}")
    confidence = 1.0 if not issues else max(0.0, 1.0 - 0.25 * len(issues))
    return _ok(
        {
            "confidence_score": confidence,
            "passed": not issues,
            "issues": issues,
            "recommendation": "accept" if not issues else "reject",
            "dimension_scores": {"syntax": 1.0 if isinstance(output, dict) else 0.0, "required_fields": 1.0 if not issues else confidence},
        }
    )


def _handle_record_feedback(args: dict[str, Any], **_: Any) -> str:
    from .memory_provider import UrbanMemoryProvider

    provider = UrbanMemoryProvider()
    provider.initialize(session_id=str(args.get("session_id") or "tool-call"))
    return provider.handle_tool_call("urban_memory_record", args)


def _handle_research_memory(args: dict[str, Any], **_: Any) -> str:
    """Search or record reusable urban research-design lessons."""
    from .memory_provider import UrbanMemoryProvider

    provider = UrbanMemoryProvider()
    provider.initialize(session_id=str(args.get("session_id") or "tool-call"))
    return provider.handle_tool_call("urban_research_memory", args)


def _handle_memory_reflect(args: dict[str, Any], **_: Any) -> str:
    """Reflect on an execution trace and promote reusable lessons."""
    from .memory_provider import UrbanMemoryProvider

    provider = UrbanMemoryProvider()
    provider.initialize(session_id=str(args.get("session_id") or "tool-call"))
    return provider.handle_tool_call("urban_memory_reflect", args)


def _handle_gis_workspace(args: dict[str, Any], **_: Any) -> str:
    """Run a backend-neutral GIS workspace protocol adapter."""
    try:
        from .paths import PAPER4_ROOT

        paper4_root = str(PAPER4_ROOT)
        if paper4_root in sys.path:
            sys.path.remove(paper4_root)
        sys.path.insert(0, paper4_root)
        loaded_plugins = sys.modules.get("plugins")
        loaded_plugins_path = str(getattr(loaded_plugins, "__file__", "")) if loaded_plugins else ""
        if loaded_plugins and paper4_root not in loaded_plugins_path:
            sys.modules.pop("plugins", None)
        from plugins.gis_backends.registry import get_backend

        backend = get_backend(args.get("backend"))
        result = backend.run(args)
        if result.get("success"):
            return _ok(result)
        return _fail("GIS backend did not complete cleanly", result=result)
    except Exception as exc:
        return _fail(str(exc), backend=args.get("backend"), mode=args.get("mode"))


def _handle_qgis_workspace(args: dict[str, Any], **_: Any) -> str:
    """Package GIS outputs into a QGIS project plus agent-readable manifest."""
    from .paths import PAPER4_ROOT

    workspace_type = str(args.get("workspace_type") or "custom")
    run_dir_raw = args.get("run_dir")
    if not run_dir_raw:
        return _fail("run_dir is required so the workspace packager does not guess which experiment to package")
    run_dir = _host_path(run_dir_raw)
    if not run_dir.exists():
        return _fail(f"run_dir does not exist: {run_dir}")

    if args.get("packager_script"):
        packager_script = _host_path(args["packager_script"])
    elif workspace_type == "case1_nanjing_200m":
        if not args.get("allow_case_template"):
            return _fail(
                "case1_nanjing_200m packager is case-specific and disabled by default",
                hint="For Case 2 or any new run, author a task-specific packager with urban_host_python and pass packager_script. Set allow_case_template=true only for the original Case 1 Nanjing 200m run.",
            )
        packager_script = PAPER4_ROOT / "scripts" / "package_case1_qgis_workspace.py"
    else:
        return _fail(
            f"no reusable packager selected for workspace_type: {workspace_type}",
            hint="Author a task-specific workspace packager with urban_host_python, then call urban_qgis_workspace with packager_script. Do not reuse case-specific templates across cases.",
        )
    if not packager_script.exists():
        return _fail(
            f"packager script does not exist: {packager_script}",
            hint="Use urban_host_python to create a task-specific QGIS workspace packager, then record the pattern with urban_research_memory.",
        )

    qgis_python = _resolve_qgis_python(args.get("qgis_python"))
    timeout = int(args.get("timeout") or 600)
    command = [sys.executable, str(packager_script), "--run-dir", str(run_dir)]
    if qgis_python:
        command.extend(["--qgis-python", qgis_python])
    started = datetime.now().isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=str(PAPER4_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _fail("qgis workspace packager timed out", command=command, timeout_s=timeout, stdout=exc.stdout, stderr=exc.stderr)
    except Exception as exc:
        return _fail(f"qgis workspace packager failed to start: {exc}", command=command)

    parsed_stdout = None
    stdout = completed.stdout or ""
    for start in [idx for idx, char in enumerate(stdout) if char == "{"]:
        try:
            parsed_stdout = json.loads(stdout[start:])
            break
        except Exception:
            continue

    workspace = run_dir / "qgis_workspace"
    manifest_path = workspace / "manifests" / "spatial_reasoning_manifest.json"
    manifest = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            manifest = {"read_warning": str(exc), "path": str(manifest_path)}
    project_qgz = Path(str(manifest.get("project_qgz"))) if isinstance(manifest, dict) and manifest.get("project_qgz") else None
    result = {
        "workspace_type": workspace_type,
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "parsed_stdout": parsed_stdout,
        "workspace": str(workspace),
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "project_qgz": str(project_qgz) if project_qgz else "",
        "project_qgz_exists": project_qgz.exists() if project_qgz else False,
        "layer_count": len(manifest.get("layers", [])) if isinstance(manifest, dict) else None,
        "started_at": started,
        "finished_at": datetime.now().isoformat(),
    }
    success = completed.returncode == 0 and result["manifest_exists"] and result["project_qgz_exists"]
    return _json({"success": success, "result": result, "error": None if success else "workspace packager did not complete cleanly"})


def _handle_qgis_process(args: dict[str, Any], **_: Any) -> str:
    """Run qgis_process directly from the Hermes-Urban Python process."""
    algorithm = str(args.get("algorithm") or "").strip()
    if not algorithm:
        return _fail("algorithm is required, e.g. native:fixgeometries")
    parameters = args.get("parameters") if isinstance(args.get("parameters"), dict) else {}
    if not parameters:
        return _fail("parameters are required")

    qgis_path = _resolve_qgis_process(args.get("qgis_process"))
    if not qgis_path:
        return _fail(
            "qgis_process was not found",
            searched=_candidate_qgis_process_paths(),
            hint="Pass qgis_process explicitly, or install QGIS 3.x in a standard location.",
        )

    command = _qgis_command(qgis_path, algorithm, parameters, verbose=bool(args.get("verbose", False)))
    timeout = int(args.get("timeout") or 300)
    started = datetime.now().isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=str(args.get("workdir") or Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        _write_qgis_log(args, command, started, returncode=None, stdout=exc.stdout, stderr=exc.stderr, timed_out=True)
        return _fail("qgis_process timed out", command=command, timeout_s=timeout)
    except Exception as exc:
        _write_qgis_log(args, command, started, returncode=None, stdout="", stderr=str(exc), timed_out=False)
        return _fail(f"qgis_process failed to start: {exc}", command=command)

    outputs = _qgis_outputs(parameters)
    verification = [_verify_spatial_output(path) for path in outputs]
    log_path = _write_qgis_log(
        args,
        command,
        started,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
        outputs=verification,
    )
    success = completed.returncode == 0 and all(item.get("exists") for item in verification)
    return _json(
        {
            "success": success,
            "result": {
                "algorithm": algorithm,
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-4000:],
                "stderr_tail": (completed.stderr or "")[-4000:],
                "outputs": verification,
                "log_path": log_path,
                "started_at": started,
                "finished_at": datetime.now().isoformat(),
            },
            "error": None if success else "qgis_process returned nonzero or one or more outputs were not created",
        }
    )


def _candidate_qgis_process_paths() -> list[str]:
    env_path = os.getenv("QGIS_PROCESS") or os.getenv("QGIS_PROCESS_PATH")
    candidates = [env_path] if env_path else []
    candidates.extend(
        [
            r"C:\Program Files\QGIS 3.40.11\bin\qgis_process-qgis-ltr.bat",
            r"C:\Program Files\QGIS 3.40\bin\qgis_process-qgis-ltr.bat",
            r"C:\Program Files\QGIS 3.40.11\apps\qgis-ltr\bin\qgis_process.exe",
            r"C:\Program Files\QGIS 3.40\apps\qgis-ltr\bin\qgis_process.exe",
            "qgis_process",
        ]
    )
    return [item for item in candidates if item]


def _candidate_qgis_python_paths() -> list[str]:
    env_path = os.getenv("QGIS_PYTHON") or os.getenv("QGIS_PYTHON_PATH")
    candidates = [env_path] if env_path else []
    candidates.extend(
        [
            r"C:\Program Files\QGIS 3.40.11\bin\python-qgis-ltr.bat",
            r"C:\Program Files\QGIS 3.40\bin\python-qgis-ltr.bat",
            r"C:\Program Files\QGIS 3.40.11\bin\python.exe",
            r"C:\Program Files\QGIS 3.40\bin\python.exe",
        ]
    )
    return [item for item in candidates if item]


def _resolve_qgis_python(value: Any = None) -> str | None:
    candidates = [str(value)] if value else []
    candidates.extend(_candidate_qgis_python_paths())
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def _resolve_qgis_process(value: Any = None) -> str | None:
    candidates = [str(value)] if value else []
    candidates.extend(_candidate_qgis_process_paths())
    for candidate in candidates:
        if not candidate:
            continue
        if candidate == "qgis_process":
            return candidate
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def _qgis_command(qgis_path: str, algorithm: str, parameters: dict[str, Any], *, verbose: bool) -> list[str]:
    args: list[str] = []
    if os.name == "nt" and qgis_path.lower().endswith((".bat", ".cmd")):
        args.extend(["cmd.exe", "/c", qgis_path])
    else:
        args.append(qgis_path)
    if verbose:
        args.append("--verbose")
    args.extend(["run", algorithm, "--"])
    for key, value in parameters.items():
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                args.append(f"{key}={item}")
        else:
            args.append(f"{key}={value}")
    return args


def _qgis_outputs(parameters: dict[str, Any]) -> list[str]:
    outputs = []
    for key, value in parameters.items():
        if "OUTPUT" not in str(key).upper():
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item)
            if text and not text.lower().startswith("memory:") and text.upper() != "TEMPORARY_OUTPUT":
                outputs.append(text)
    return outputs


def _verify_spatial_output(path: str) -> dict[str, Any]:
    item: dict[str, Any] = {"path": path, "exists": Path(path).exists()}
    if not item["exists"]:
        return item
    item["size_bytes"] = Path(path).stat().st_size
    if path.lower().endswith((".geojson", ".json")):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            features = data.get("features") if isinstance(data, dict) else None
            if isinstance(features, list):
                item["feature_count"] = len(features)
                types = Counter(str((feature.get("geometry") or {}).get("type")) for feature in features if isinstance(feature, dict))
                item["geometry_types"] = dict(types)
        except Exception as exc:
            item["read_warning"] = str(exc)
    return item


def _write_qgis_log(
    args: dict[str, Any],
    command: list[str],
    started: str,
    *,
    returncode: int | None,
    stdout: Any,
    stderr: Any,
    timed_out: bool,
    outputs: list[dict[str, Any]] | None = None,
) -> str | None:
    log_path_raw = args.get("log_path")
    if not log_path_raw and args.get("output_dir"):
        log_path_raw = str(Path(str(args["output_dir"])) / "qgis_process_log.jsonl")
    if not log_path_raw:
        return None
    path = Path(str(log_path_raw))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "started_at": started,
        "finished_at": datetime.now().isoformat(),
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "outputs": outputs or [],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return str(path)


def _fallback_capabilities(task: str, *, limit: int) -> dict[str, Any]:
    catalog = [
        _capability("review_hub", "Urban Review Hub", "review", "Review spatial, temporal, people, governance, and artifact-readiness implications", ["analysis", "evidence_manifest"], ["review_report"], ["review", "governance", "trace", "reasoning"]),
        _capability("data_canvas_audit", "Data canvas audit", "research_design", "Audit available layers, tables, time windows, spatial units, and people proxies before analysis", ["data_canvas"], ["canvas_inventory", "evidence_roles"], ["canvas", "data", "audit", "vitality", "drivers"]),
        _capability("variable_role_audit", "Variable-role audit", "research_design", "Classify variables as direct, proxy, missing, or gated evidence for the research question", ["variable_table"], ["role_audit"], ["variables", "evidence", "claim", "drivers"]),
        _capability("branch_tree_design", "Research branch-tree design", "research_design", "Create and maintain approved, active, deferred, blocked, and suggested analysis branches with human decisions", ["data_contract", "method_memory"], ["branch_tree", "branch_progress"], ["branch", "plan", "hypothesis", "drivers", "method"]),
        _capability("typed_route_tree_design", "Typed research-route tree design", "research_design", "Create route nodes with node_type, dependencies, inputs, outputs, time-space-people meaning, and allowed downstream nodes", ["data_contract", "research_design_memory", "method_memory"], ["typed_route_tree", "dependency_review"], ["route", "dependency", "research_object", "feature_package", "model_execution", "model_explanation"]),
        _capability("claim_synthesis", "Analysis-route comparison and claim calibration", "review", "Compare completed branch outputs to decide which urban claims are stable, conditional, insufficient, or unsupported", ["branch_outputs", "claim_gates"], ["branch_comparison", "claim_synthesis"], ["branch", "comparison", "claim", "synthesis", "review"]),
        _capability("method_requirement_review", "Method requirement review", "review", "Check model-specific required inputs, parameters, diagnostics, and claim boundaries", ["method_branch", "artifacts"], ["method_review", "branch_candidates"], ["gwr", "gwrf", "shap", "pdp", "temporal", "perception"]),
        _capability("street_view_alignment", "Street-view image-grid alignment", "multimodal_data", "Inventory geotagged street-view images, align them to grids or segments, and report coverage before perception claims", ["image_folder_or_zip", "spatial_units"], ["image_inventory", "alignment_manifest", "coverage_table"], ["street-view", "perception", "image", "multimodal", "alignment"]),
        _capability("temporal_stratified_modeling", "Temporal stratified modeling", "analysis", "Design weekday/weekend, period-specific, or grid-date-period association branches when aggregate temporal data exist", ["grid_date_period_table", "X_variables"], ["temporal_branch_plan", "stratified_model_diagnostics"], ["temporal", "weekday", "weekend", "period", "morning", "evening"]),
        _capability("descriptive_mapping", "Descriptive mapping", "analysis", "Map observed spatial patterns and branch interpretations without over-claiming mechanisms", ["grid_metrics"], ["maps", "branch_notes"], ["map", "spatial", "pattern", "vitality"]),
        _capability("model_diagnostics", "Model diagnostics", "analysis", "Review baseline model artifacts, residuals, importance, and explanation readiness", ["model_outputs"], ["diagnostics", "claim_gates"], ["model", "diagnostic", "rf", "shap", "pdp"]),
        _capability("artifact_manifest", "Artifact manifest", "artifact", "Inventory reusable tables, maps, GIS layers, model outputs, and manifests", ["outputs"], ["artifact_manifest"], ["artifact", "manifest", "readiness"]),
        _capability("osm_acquisition", "OpenStreetMap acquisition", "data", "Fetch roads, buildings, POIs, land use when missing from the current canvas", ["location"], ["osm_features"], ["osm", "open-data"]),
        _capability("network_connectivity", "Network connectivity", "optional_analysis", "Measure node degree, density, isolated nodes only when network structure is an approved branch", ["road_graph"], ["connectivity_metrics"], ["network", "topology"]),
        _capability("accessibility", "Accessibility measurement", "optional_analysis", "Measure origin-to-target access distances only when accessibility is an approved branch", ["origins", "targets"], ["coverage", "distance_metrics"], ["walkability"]),
        _capability("density", "Urban density", "optional_analysis", "Compute grid density and uniformity only when not already supplied by the data canvas", ["features"], ["density_grid"], ["morphology"]),
        _capability("svg_overlay", "SVG overlay", "optional_cartography", "Generate reviewable map artifacts after the map branch is approved", ["features", "bbox"], ["svg"], ["cartography", "artifact"]),
    ]
    terms = set(_tokens(task))
    ranked = sorted(catalog, key=lambda item: (-len(terms & set(item["tags"] + [item["name"]])), catalog.index(item)))[:limit]
    return {
        "disclosure_policy": "progressive",
        "planning_warning": "Selected capabilities are candidates for human-approved planning, not mandatory workflow steps. Do not turn optional analysis operators into the main plan without data-role justification.",
        "level0_index_size": len(catalog),
        "selected_names": [item["name"] for item in ranked],
        "selected_level0": [{key: item[key] for key in ("name", "title", "family", "summary", "tags")} for item in ranked],
        "level1_cards": ranked,
    }


def _capability(name: str, title: str, family: str, summary: str, inputs: list[str], outputs: list[str], tags: list[str]) -> dict[str, Any]:
    return {"name": name, "title": title, "family": family, "type": "urban_method", "summary": summary, "inputs": inputs, "outputs": outputs, "tags": tags, "backend_names": [f"urban_{name}"], "constraints": []}


def _fetch_osmnx(location: str, radius: float, data_types: list[str]) -> dict[str, Any]:
    import osmnx as ox

    result: dict[str, Any] = {"location": location, "radius_m": radius, "data_types": data_types}
    if "roads" in data_types:
        graph = ox.graph_from_address(location, dist=radius, network_type="all")
        result["road_graph"] = _summarize_networkx_graph(graph)
    tags = {}
    if "buildings" in data_types:
        tags["building"] = True
    if "pois" in data_types:
        tags.update({"amenity": True, "shop": True})
    if tags:
        gdf = ox.features_from_address(location, tags=tags, dist=radius)
        try:
            gdf = gdf.to_crs(epsg=4326)
        except Exception:
            pass
        collection = json.loads(gdf.head(200).to_json())
        if "buildings" in data_types:
            result["buildings"] = [feature for feature in collection.get("features", []) if feature.get("properties", {}).get("building")]
        if "pois" in data_types:
            result["pois"] = [feature for feature in collection.get("features", []) if feature not in result.get("buildings", [])]
    result["bbox"] = _infer_bbox(result)
    return result


def _summarize_networkx_graph(graph: Any, *, limit: int = 500) -> dict[str, Any]:
    nodes = []
    for node_id, data in list(graph.nodes(data=True))[:limit]:
        nodes.append({"id": str(node_id), "x": data.get("x"), "y": data.get("y")})
    edges = []
    for u, v, data in list(graph.edges(data=True))[:limit]:
        edges.append({"u": str(u), "v": str(v), "length_m": data.get("length")})
    return {"nodes": nodes, "edges": edges, "node_count_total": len(graph.nodes()), "edge_count_total": len(graph.edges())}


def _synthetic_osm(location: str, radius: float, data_types: list[str]) -> dict[str, Any]:
    center = _synthetic_center(location)
    lon, lat = center
    delta = max(radius, 100) / 111_320
    nodes = [
        {"id": "n1", "x": lon - delta * 0.45, "y": lat - delta * 0.20},
        {"id": "n2", "x": lon, "y": lat - delta * 0.05},
        {"id": "n3", "x": lon + delta * 0.40, "y": lat + delta * 0.10},
        {"id": "n4", "x": lon - delta * 0.20, "y": lat + delta * 0.35},
    ]
    edges = [
        {"u": "n1", "v": "n2", "length_m": 130},
        {"u": "n2", "v": "n3", "length_m": 145},
        {"u": "n2", "v": "n4", "length_m": 115},
        {"u": "n4", "v": "n3", "length_m": 160},
    ]
    buildings = [
        _square_feature("b1", lon - delta * 0.25, lat - delta * 0.15, 35, {"type": "building", "area_m2": 1225}),
        _square_feature("b2", lon + delta * 0.12, lat - delta * 0.08, 42, {"type": "building", "area_m2": 1764}),
        _square_feature("b3", lon - delta * 0.05, lat + delta * 0.20, 55, {"type": "building", "area_m2": 3025}),
    ]
    pois = [
        _point_feature("p1", lon + delta * 0.20, lat + delta * 0.15, {"type": "poi", "amenity": "cafe"}),
        _point_feature("p2", lon - delta * 0.32, lat + delta * 0.22, {"type": "poi", "amenity": "park"}),
    ]
    result: dict[str, Any] = {"location": location, "radius_m": radius, "center": [lon, lat], "bbox": [lon - delta, lat - delta, lon + delta, lat + delta]}
    if "roads" in data_types:
        result["road_graph"] = {"nodes": nodes, "edges": edges}
    if "buildings" in data_types:
        result["buildings"] = buildings
    if "pois" in data_types:
        result["pois"] = pois
    return result


def _build_evidence_manifest(task_data: dict[str, Any], task_text: str) -> dict[str, Any]:
    bbox = task_data.get("bbox") or _infer_bbox(task_data)
    location = task_data.get("location") or task_data.get("place")
    spatial = {
        "bbox": bbox,
        "crs": task_data.get("crs") or "EPSG:4326" if bbox or location else None,
        "admin_level": task_data.get("admin_level"),
        "scale_band": task_data.get("scale_band") or _infer_scale(task_text),
        "spatial_relation_frame": task_data.get("spatial_relation_frame") or "network+metric" if _mentions(task_text, ["walk", "route", "access", "connect", "topology"]) else None,
    }
    temporal = {
        "timestamp": task_data.get("timestamp") or datetime.now().isoformat(),
        "time_window": task_data.get("time_window") or task_data.get("temporal_range"),
        "granularity": task_data.get("granularity"),
        "forecast_horizon": task_data.get("forecast_horizon"),
        "freshness": task_data.get("freshness"),
    }
    population = {
        "target_group": task_data.get("target_group") or "pedestrians" if _mentions(task_text, ["walk", "pedestrian", "accessibility"]) else task_data.get("target_group"),
        "observed_group": task_data.get("observed_group"),
        "affected_group": task_data.get("affected_group"),
        "sampling_bias": task_data.get("sampling_bias"),
        "stakeholder_source": task_data.get("stakeholder_source"),
    }
    governance = {
        "provenance": task_data.get("provenance") or "OpenStreetMap/synthetic fixture" if task_data.get("mock") or location else task_data.get("provenance"),
        "license": task_data.get("license") or "ODbL or fixture-only" if task_data.get("mock") or location else task_data.get("license"),
        "collection_method": task_data.get("collection_method") or "tool-mediated acquisition",
        "uncertainty": task_data.get("uncertainty"),
        "missing_layers": list(task_data.get("missing_layers") or []),
    }
    tags = ["urban", "hermes", "grounding"]
    if _mentions(task_text, ["walk", "access"]):
        tags.append("walkability")
    if _mentions(task_text, ["mobility", "trajectory", "traffic"]):
        tags.append("mobility")
    return {"spatial": spatial, "temporal": temporal, "population": population, "governance": governance, "tags": tags, "data_sources": _data_sources(task_data)}


def _evidence_gaps(evidence: dict[str, Any], task_text: str) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    spatial = evidence.get("spatial", {})
    temporal = evidence.get("temporal", {})
    population = evidence.get("population", {})
    governance = evidence.get("governance", {})
    if not spatial.get("bbox"):
        gaps.append({"dimension": "spatial", "field": "bbox", "severity": "warning", "message": "No explicit spatial extent was supplied."})
    if not spatial.get("crs"):
        gaps.append({"dimension": "spatial", "field": "crs", "severity": "warning", "message": "CRS is not declared."})
    if _mentions(task_text, ["mobility", "temporal", "trajectory", "traffic", "forecast"]) and not temporal.get("time_window"):
        gaps.append({"dimension": "temporal", "field": "time_window", "severity": "warning", "message": "Temporal workflow lacks observation window."})
    if _mentions(task_text, ["people", "pedestrian", "population", "stakeholder", "walk"]) and not population.get("affected_group"):
        gaps.append({"dimension": "population", "field": "affected_group", "severity": "warning", "message": "Affected group is not explicit."})
    for field in ("provenance", "license", "uncertainty"):
        if not governance.get(field):
            gaps.append({"dimension": "governance", "field": field, "severity": "warning", "message": f"Governance field {field} is missing."})
    return gaps


def _dataset_cards(task_data: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    cards = task_data.get("dataset_cards")
    if isinstance(cards, list) and cards:
        return cards
    sources = evidence.get("data_sources") or ["task_context"]
    return [
        {
            "resource_id": f"dataset_{index + 1}",
            "name": str(source),
            "role": "primary_evidence" if index == 0 else "supporting_evidence",
            "spatial": evidence.get("spatial", {}),
            "temporal": evidence.get("temporal", {}),
            "governance": evidence.get("governance", {}),
            "known_limits": evidence.get("governance", {}).get("missing_layers") or ["coverage and freshness should be verified before final claims"],
        }
        for index, source in enumerate(sources)
    ]


def _search_research_memory(task_text: str, *, limit: int = 4) -> list[dict[str, Any]]:
    try:
        from .memory_provider import UrbanMemoryProvider

        provider = UrbanMemoryProvider()
        provider.initialize(session_id="ground-task")
        raw = provider.handle_tool_call(
            "urban_research_memory",
            {
                "action": "search",
                "query": task_text,
                "limit": limit,
                "content_layers": ["research_design", "urban_method"],
                "memory_scopes": ["reflective"],
            },
        )
        payload = json.loads(raw)
        result = payload.get("result") if isinstance(payload, dict) else {}
        records = result.get("records") if isinstance(result, dict) else []
        return records if isinstance(records, list) else []
    except Exception:
        return []


def _execution_plan(
    task_text: str,
    capability_pack: dict[str, Any],
    evidence: dict[str, Any],
    gaps: list[dict[str, str]],
    *,
    research_memory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    names = capability_pack.get("selected_names", []) if isinstance(capability_pack, dict) else []
    return {
        "plan_id": f"urban_{int(time.time())}",
        "workflow_profile": "hermes_urban_gap_harness",
        "task": task_text,
        "selected_capabilities": names,
        "research_design_cues": [
            {
                "record_id": item.get("record_id"),
                "summary": item.get("summary"),
                "method_hint": item.get("method_hint"),
                "caveats": item.get("caveats"),
            }
            for item in (research_memory or [])[:4]
        ],
        "steps": [
            {"id": "ground", "tool": "urban_ground_task", "purpose": "make data/method/evidence requirements explicit"},
            {"id": "data_contract", "tool": "urban_host_fs|urban_review", "purpose": "summarize Y/X/G/T/P or equivalent data contract before choosing methods"},
            {"id": "typed_route_tree_gate", "tool": "urban_route_tree|urban_review|assistant_response", "purpose": "initialize and show a typed route tree with node types, dependencies, required inputs and parameters, expected artifacts, time-space-people meaning, claim gates, and human choices"},
            {"id": "human_route_decision", "tool": "urban_route_tree|assistant_response", "purpose": "ask the analyst to approve, defer, block, or revise route nodes before artifact-producing execution; record choices through urban_route_tree"},
            {"id": "branch_local_method_memory", "tool": "urban_research_memory", "purpose": "retrieve only the method cards needed by approved active route nodes, then record memory_retrieval_log with branch id and expiry"},
            {"id": "approved_route_execution", "tool": "delegate_task|urban_host_python|urban_host_fs", "purpose": "execute approved worker-sized route nodes and save worker artifacts, not unapproved optional analyses"},
            {"id": "dynamic_review_branching", "tool": "urban_review|urban_route_tree", "purpose": "pause after each major step; if worker/reviewer feedback reveals new research hypotheses, patch the route tree with suggested/deferred/blocked branch candidates"},
            {"id": "route_comparison", "tool": "urban_route_tree|urban_review", "purpose": "merge completed route outputs into report-option and claim-calibration nodes; compare claims as stable, conditional, insufficient, or unsupported"},
            {"id": "reuse", "tool": "urban_record_feedback", "purpose": "store human corrections as reusable memory"},
        ],
        "known_gaps": gaps,
        "evidence_manifest": evidence,
    }


def _score_spatial(evidence: dict[str, Any], results: Any) -> dict[str, Any]:
    spatial = (evidence or {}).get("spatial", {}) if isinstance(evidence, dict) else {}
    issues = []
    score = 1.0
    if not spatial.get("bbox"):
        issues.append("missing bbox")
        score -= 0.25
    if not spatial.get("crs"):
        issues.append("missing CRS")
        score -= 0.20
    if _result_mentions(results, ["route", "connect", "access", "walk"]) and not spatial.get("spatial_relation_frame"):
        issues.append("missing spatial relation frame for network/access reasoning")
        score -= 0.15
    return {"score": max(0.0, score), "issues": issues, "applicable": True}


def _score_temporal(evidence: dict[str, Any], results: Any) -> dict[str, Any]:
    temporal = (evidence or {}).get("temporal", {}) if isinstance(evidence, dict) else {}
    applicable = _result_mentions(results, ["mobility", "trajectory", "traffic", "forecast", "temporal"])
    if not applicable and not any(value for value in temporal.values()):
        return {"score": 1.0, "issues": [], "applicable": False}
    issues = []
    score = 1.0
    if applicable and not temporal.get("time_window"):
        issues.append("missing time_window")
        score -= 0.25
    if applicable and not temporal.get("freshness"):
        issues.append("missing freshness declaration")
        score -= 0.15
    return {"score": max(0.0, score), "issues": issues, "applicable": True}


def _score_population(evidence: dict[str, Any], results: Any) -> dict[str, Any]:
    population = (evidence or {}).get("population", {}) if isinstance(evidence, dict) else {}
    if _is_workflow_trace_payload(results) and not any(value for value in population.values()):
        step_records = _as_record_list(results.get("per_step_review_records"))
        people_text = "\n".join(
            str(record.get(alias) or "")
            for record in step_records
            for alias in (
                "people_implications",
                "people",
                "population_implications",
                "stakeholder_implications",
                "people_review",
            )
        ).lower()
        if not people_text.strip():
            return {
                "score": 0.65,
                "issues": ["workflow trace has no per-step people implications"],
                "applicable": True,
            }
        issues: list[str] = []
        score = 1.0
        if not any(term in people_text for term in ("proxy", "missing", "not individual", "activity", "stakeholder", "user", "demographic", "behavior")):
            issues.append("people implications do not clarify direct/proxy/missing or activity/stakeholder meaning")
            score -= 0.15
        return {"score": max(0.0, score), "issues": issues, "applicable": True}

    applicable = _result_mentions(results, ["walk", "people", "pedestrian", "stakeholder", "population", "access"])
    if not applicable and not any(value for value in population.values()):
        return {"score": 1.0, "issues": [], "applicable": False}
    issues = []
    score = 1.0
    if not population.get("target_group"):
        issues.append("missing target_group")
        score -= 0.20
    if applicable and not population.get("affected_group"):
        issues.append("missing affected_group")
        score -= 0.25
    if not population.get("stakeholder_source"):
        issues.append("missing stakeholder_source")
        score -= 0.10
    return {"score": max(0.0, score), "issues": issues, "applicable": True}


def _score_governance(evidence: dict[str, Any], results: Any) -> dict[str, Any]:
    governance = (evidence or {}).get("governance", {}) if isinstance(evidence, dict) else {}
    tags = (evidence or {}).get("tags", []) if isinstance(evidence, dict) else []
    if _is_workflow_trace_payload(results) and not any(value for value in governance.values()):
        issues: list[str] = []
        score = 1.0
        if results.get("artifact_manifest") in (None, "", [], {}):
            issues.append("workflow trace has no artifact_manifest")
            score -= 0.20
        if results.get("claim_gates") in (None, "", [], {}):
            issues.append("workflow trace has no claim_gates")
            score -= 0.20
        if results.get("parent_verification") in (None, "", [], {}):
            issues.append("workflow trace has no parent_verification")
            score -= 0.15
        return {"score": max(0.0, score), "issues": issues, "applicable": True}

    issues = []
    score = 1.0
    for field in ("provenance", "license", "collection_method", "uncertainty"):
        if not governance.get(field):
            issues.append(f"missing governance field {field}")
            score -= 0.12
    if governance.get("missing_layers"):
        issues.append(f"missing evidence layers: {governance.get('missing_layers')}")
        score -= 0.10
    if not tags:
        issues.append("evidence manifest has no tags")
        score -= 0.05
    return {"score": max(0.0, score), "issues": issues, "applicable": True}


def _find_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if isinstance(value.get("evidence_manifest"), dict):
            return value["evidence_manifest"]
        for item in value.values():
            found = _find_evidence(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_evidence(item)
            if found:
                return found
    return {}


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9_\-]+", text.lower())


def _mentions(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _result_mentions(value: Any, terms: Iterable[str]) -> bool:
    return _mentions(json.dumps(value, ensure_ascii=False, default=str), terms)


def _data_sources(task_data: dict[str, Any]) -> list[str]:
    sources = task_data.get("data_sources") or task_data.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    if task_data.get("location"):
        sources = list(sources) + [f"open-data:{task_data['location']}"]
    return [str(item) for item in sources] or ["task_context"]


def _infer_scale(task_text: str) -> str:
    if _mentions(task_text, ["street", "block", "walk"]):
        return "street_to_neighborhood"
    if _mentions(task_text, ["city", "metropolitan"]):
        return "city"
    return "district"


def _synthetic_center(location: str) -> tuple[float, float]:
    lowered = location.lower()
    if "marais" in lowered or "paris" in lowered:
        return (2.361, 48.858)
    if "pudong" in lowered or "shanghai" in lowered:
        return (121.544, 31.221)
    return (0.0, 0.0)


def _feature_collection(features: Any, *, crs: str = "EPSG:4326") -> dict[str, Any]:
    if isinstance(features, dict) and features.get("type") == "FeatureCollection":
        collection = dict(features)
        collection.setdefault("crs", {"type": "name", "properties": {"name": crs}})
        return collection
    return {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": crs}}, "features": _feature_list(features)}


def _feature_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("type") == "FeatureCollection":
            return [item for item in value.get("features", []) if isinstance(item, dict)]
        if value.get("type") == "Feature":
            return [value]
        features = []
        for key in ("buildings", "pois", "features"):
            features.extend(_feature_list(value.get(key, [])))
        return features
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _point_like(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (float(value[0]), float(value[1]))
    if isinstance(value, dict):
        if "lon" in value and "lat" in value:
            return (float(value["lon"]), float(value["lat"]))
        if "x" in value and "y" in value:
            return (float(value["x"]), float(value["y"]))
        return _feature_centroid(value)
    return None


def _feature_centroid(feature: dict[str, Any]) -> tuple[float, float] | None:
    props = feature.get("properties") or {}
    if isinstance(props.get("centroid"), (list, tuple)) and len(props["centroid"]) >= 2:
        return (float(props["centroid"][0]), float(props["centroid"][1]))
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return (float(coords[0]), float(coords[1]))
    points = list(_iter_coords(coords))
    if points:
        return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))
    bbox = feature.get("bbox") or props.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return ((float(bbox[0]) + float(bbox[2])) / 2, (float(bbox[1]) + float(bbox[3])) / 2)
    return None


def _iter_coords(value: Any):
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield (float(value[0]), float(value[1]))
        else:
            for item in value:
                yield from _iter_coords(item)


def _features_bbox(features: list[dict[str, Any]]) -> list[float] | None:
    points = []
    for feature in features:
        points.extend(_iter_coords((feature.get("geometry") or {}).get("coordinates")))
        centroid = _feature_centroid(feature)
        if centroid:
            points.append(centroid)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _infer_bbox(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        if isinstance(value.get("bbox"), list) and len(value["bbox"]) >= 4:
            return [float(item) for item in value["bbox"][:4]]
        features = _feature_list(value)
        if features:
            return _features_bbox(features)
    return None


def _distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    lon1, lat1 = left
    lon2, lat2 = right
    avg_lat = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * 111_320 * math.cos(avg_lat)
    dy = (lat2 - lat1) * 110_574
    return math.sqrt(dx * dx + dy * dy)


def _feature_area_m2(feature: dict[str, Any]) -> float:
    props = feature.get("properties") or {}
    if props.get("area_m2") is not None:
        return float(props["area_m2"])
    bbox = _features_bbox([feature])
    if not bbox:
        return 1.0
    return max(1.0, _distance_m((bbox[0], bbox[1]), (bbox[2], bbox[1])) * _distance_m((bbox[0], bbox[1]), (bbox[0], bbox[3])))


def _infer_feature_type(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    return str(props.get("type") or props.get("amenity") or props.get("building") or "feature")


def _square_feature(feature_id: str, lon: float, lat: float, size_m: float, properties: dict[str, Any]) -> dict[str, Any]:
    dx = size_m / 111_320
    dy = size_m / 110_574
    coords = [[lon - dx / 2, lat - dy / 2], [lon + dx / 2, lat - dy / 2], [lon + dx / 2, lat + dy / 2], [lon - dx / 2, lat + dy / 2], [lon - dx / 2, lat - dy / 2]]
    return {"type": "Feature", "id": feature_id, "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"id": feature_id, **properties}}


def _point_feature(feature_id: str, lon: float, lat: float, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "id": feature_id, "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"id": feature_id, **properties}}


def _make_svg(base_features: Any, interventions: list[Any], bbox: list[float], width: int, height: int) -> str:
    minx, miny, maxx, maxy = bbox
    sx = width / max(maxx - minx, 1e-12)
    sy = height / max(maxy - miny, 1e-12)

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return ((point[0] - minx) * sx, height - (point[1] - miny) * sy)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#f7f7f3"/>']
    graph = base_features.get("road_graph") if isinstance(base_features, dict) else None
    if isinstance(graph, dict):
        node_lookup = {str(node.get("id")): (float(node.get("x", 0)), float(node.get("y", 0))) for node in graph.get("nodes", []) if isinstance(node, dict)}
        for edge in graph.get("edges", []):
            left = node_lookup.get(str(edge.get("u")))
            right = node_lookup.get(str(edge.get("v")))
            if not left or not right:
                continue
            x1, y1 = project(left)
            x2, y2 = project(right)
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#8a8a8a" stroke-width="2"/>')
    for feature in _feature_list(base_features):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Point":
            center = _feature_centroid(feature)
            if center:
                x, y = project(center)
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#2b7a78"/>')
            continue
        points = list(_iter_coords(geom.get("coordinates")))
        if points:
            path = " ".join(f"{project(point)[0]:.1f},{project(point)[1]:.1f}" for point in points)
            parts.append(f'<polygon points="{path}" fill="#d8c99b" stroke="#816c3a" stroke-width="1" opacity="0.75"/>')
    for item in interventions:
        if isinstance(item, dict) and isinstance(item.get("bbox"), list) and len(item["bbox"]) >= 4:
            x1, y1 = project((float(item["bbox"][0]), float(item["bbox"][1])))
            x2, y2 = project((float(item["bbox"][2]), float(item["bbox"][3])))
            parts.append(f'<rect x="{min(x1, x2):.1f}" y="{min(y1, y2):.1f}" width="{abs(x2-x1):.1f}" height="{abs(y2-y1):.1f}" fill="#d1495b" opacity="0.25" stroke="#d1495b"/>')
    parts.append("</svg>")
    return "".join(parts)


CAPABILITIES_SCHEMA = {
    "name": "urban_capabilities",
    "description": "Select UrbanAgent method-level capabilities for an urban analysis task.",
    "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "limit": {"type": "integer", "default": 6}}, "required": ["task"]},
}
FETCH_OSM_SCHEMA = {
    "name": "urban_fetch_osm",
    "description": "Fetch or synthesize OSM-like roads, buildings, and POIs for a location.",
    "parameters": {"type": "object", "properties": {"location": {"type": "string"}, "radius": {"type": "number", "default": 500}, "data_types": {"type": "array", "items": {"type": "string"}}, "mock": {"type": "boolean", "default": False}}, "required": ["location"]},
}
CONNECTIVITY_SCHEMA = {"name": "urban_analyze_connectivity", "description": "Analyze road graph connectivity.", "parameters": {"type": "object", "properties": {"road_graph": {"type": "object"}}, "required": ["road_graph"]}}
ACCESSIBILITY_SCHEMA = {"name": "urban_measure_accessibility", "description": "Measure accessibility from building origins to target points.", "parameters": {"type": "object", "properties": {"buildings": {"type": "array"}, "target_points": {"type": "array"}, "max_distance": {"type": "number", "default": 500}}, "required": ["buildings", "target_points"]}}
DENSITY_SCHEMA = {"name": "urban_calculate_density", "description": "Calculate simple grid density from urban features.", "parameters": {"type": "object", "properties": {"buildings": {"type": "array"}, "features": {"type": "array"}, "grid_size": {"type": "number", "default": 100}}, "required": []}}
SVG_SCHEMA = {"name": "urban_generate_svg_overlay", "description": "Generate a reviewable SVG overlay from features and interventions.", "parameters": {"type": "object", "properties": {"base_features": {"type": "object"}, "interventions": {"type": "array"}, "bbox": {"type": "array"}, "width": {"type": "integer", "default": 800}, "height": {"type": "integer"}}, "required": ["base_features"]}}
GEOJSON_SCHEMA = {"name": "urban_export_geojson", "description": "Export features as GeoJSON FeatureCollection.", "parameters": {"type": "object", "properties": {"features": {"type": "array"}, "crs": {"type": "string", "default": "EPSG:4326"}}, "required": ["features"]}}
TOPOLOGY_SCHEMA = {"name": "urban_build_topology", "description": "Build a lightweight topology graph from urban features.", "parameters": {"type": "object", "properties": {"features": {"type": "array"}, "relation_threshold": {"type": "number", "default": 100}}, "required": ["features"]}}
GROUND_TASK_SCHEMA = {"name": "urban_ground_task", "description": "Ground an urban question in capabilities, dataset cards, research-design memory, evidence manifest, and explicit gaps.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "location": {"type": "string"}, "bbox": {"type": "array"}, "task_data": {"type": "object"}, "capability_limit": {"type": "integer", "default": 6}, "research_memory_limit": {"type": "integer", "default": 4}}, "required": ["task"]}}
ROUTE_TREE_SCHEMA = {
    "name": "urban_route_tree",
    "description": "Create and maintain the generic Urban-Hermes planner route tree. Use this as the backend git-like state manager for research-route nodes, dependencies, user choices, worker/reviewer patches, artifact links, route comparison, and frontend export. It writes route_tree_state.json, route_tree_events.jsonl, route_tree_frontend_state.json, route_tree_visual_spec.json, and human_choice_request.md in the run directory.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["init", "patch", "apply_patch", "choose", "human_choice", "attach_artifact", "sync_trace", "validate", "export"],
                "default": "export",
            },
            "run_dir": {"type": "string", "description": "Experiment run directory receiving the route-tree state files."},
            "task": {"type": "string", "description": "Research task, required for action=init."},
            "metadata": {"type": "object", "description": "Optional state metadata such as session id, data contract path, or paper figure id."},
            "todo_steps": {"type": "array", "items": {"type": "object"}, "description": "Planner-level workflow scaffold. It is task-derived, not hard-coded; for model-oriented cases it often maps to research object, variables, model route, explanation/diagnostics, and claim synthesis."},
            "nodes": {"type": "array", "items": {"type": "object"}, "description": "Typed route nodes for initialization. Each node should include node_id, node_type, question/title, depends_on, required_inputs, required_parameters, expected_outputs, time_space_people, claim_boundary, status."},
            "patch": {"type": "object", "description": "Single route-tree patch event."},
            "patches": {"type": "array", "items": {"type": "object"}, "description": "Patch events. patch_type may be add_node, add_branch, update_node, update_status, add_edge, attach_artifact, request_human_choice, merge_branches, revise_dependency, or add_report_option."},
            "choice": {"type": "object", "description": "Single human choice for one route node."},
            "choices": {"type": "array", "items": {"type": "object"}, "description": "Human choices with node_id, decision approve/defer/block/revise, and reason."},
            "actor": {"type": "string", "description": "planner, reviewer, worker, human, or main_agent."},
            "node_id": {"type": "string", "description": "Node id for attach_artifact or status update."},
            "path": {"type": "string", "description": "Artifact path for action=attach_artifact."},
            "artifact_type": {"type": "string", "description": "figure, table, map, model_output, review_json, manifest, report, etc."},
            "role": {"type": "string", "description": "Artifact role, e.g. input, intermediate_output, reviewer_output, downstream_input."},
            "title": {"type": "string", "description": "Human-readable artifact title."},
            "review_status": {"type": "string", "description": "pending_review, passed, warning, failed."},
            "trace_path": {"type": "string", "description": "Workflow trace JSON path for action=sync_trace."},
            "workflow_trace": {"type": "object", "description": "Workflow trace object for action=sync_trace. Synchronizes human decisions, worker records, reviewer records, claim gates, selected route, and artifact manifest back into route_tree_state.json."},
            "trace": {"type": "object", "description": "Alias for workflow_trace."},
        },
        "required": ["run_dir"],
    },
}
REVIEW_SCHEMA = {"name": "urban_review", "description": "Pause after a major urban-analysis step and review two coupled layers: semantic implications of time, space, people, and governance assumptions, plus artifact readiness for downstream tables, maps, model outputs, GIS layers, manifests, and reports. Use it after intermediate steps and before final claims. When reviewing a workflow trace, also check trace completeness: main plan, visible human plan decision or approval, worker records, parent verification, per-step reviewer pauses, claim gates, artifact manifest, layered reflections, and memory carryover.", "parameters": {"type": "object", "properties": {"analysis": {"type": "object"}, "results": {"type": "object"}, "evidence_manifest": {"type": "object"}, "step_id": {"type": "string"}, "stage": {"type": "string"}, "threshold": {"type": "number", "default": 0.7}}, "required": []}}
QUALITY_SCHEMA = {"name": "urban_quality_control", "description": "Run lightweight configurator-style quality checks on an urban output.", "parameters": {"type": "object", "properties": {"output": {"type": "object"}, "required_fields": {"type": "array", "items": {"type": "string"}}}, "required": ["output"]}}
RECORD_FEEDBACK_SCHEMA = {"name": "urban_record_feedback", "description": "Record a human correction or review finding into the Urban Hermes memory store.", "parameters": {"type": "object", "properties": {"summary": {"type": "string"}, "triggers": {"type": "array", "items": {"type": "string"}}, "place": {"type": "string"}, "correction": {"type": "string"}, "session_id": {"type": "string"}, "content_layer": {"type": "string", "enum": ["research_design", "urban_method", "tool_artifact", "place_case", "feedback_correction"]}, "memory_scope": {"type": "string", "enum": ["working", "reflective"], "default": "reflective"}, "memory_chain": {"type": "string", "enum": ["research_chain", "execution_chain"]}, "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": ["research_chain", "execution_chain"]}}, "source_kind": {"type": "string"}}, "required": ["summary"]}}
RESEARCH_MEMORY_SCHEMA = {
    "name": "urban_research_memory",
    "description": "Search, list, or record reusable Urban-Hermes memories. memory_chain is a retrieval facet; content_layer is the semantic tag.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "record", "list"], "default": "search"},
            "query": {"type": "string"},
            "task": {"type": "string"},
            "summary": {"type": "string"},
            "method_hint": {"type": "string"},
            "domain": {"type": "string"},
            "content_layer": {"type": "string", "enum": ["research_design", "urban_method", "tool_artifact", "place_case", "feedback_correction"]},
            "memory_scope": {"type": "string", "enum": ["working", "reflective"], "default": "reflective"},
            "memory_chain": {"type": "string", "enum": ["research_chain", "execution_chain"]},
            "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": ["research_chain", "execution_chain"]}},
            "source_kind": {"type": "string"},
            "problem_data_algorithm": {"type": "object"},
            "temporal_scope": {"type": "object"},
            "spatial_scope": {"type": "object"},
            "population_scope": {"type": "object"},
            "triggers": {"type": "array", "items": {"type": "string"}},
            "caveats": {"type": "array", "items": {"type": "string"}},
            "content_layers": {"type": "array", "items": {"type": "string", "enum": ["research_design", "urban_method", "tool_artifact", "place_case", "feedback_correction"]}},
            "memory_scopes": {"type": "array", "items": {"type": "string", "enum": ["working", "reflective"]}},
            "memory_chains": {"type": "array", "items": {"type": "string", "enum": ["research_chain", "execution_chain"]}},
            "branch_id": {"type": "string", "description": "Optional branch id when retrieving method memory for a branch-local worker or reviewer context."},
            "review_target_type": {"type": "string", "description": "Optional review target such as plan, method_branch, worker_output, or final_trace."},
            "retrieval_scope": {"type": "string", "enum": ["global", "branch_local", "worker_local", "reviewer_local"], "description": "Use branch_local/worker_local/reviewer_local for concrete method cards to avoid global context pollution."},
            "expires_after": {"type": "string", "description": "Optional expiry marker such as branch_review, worker_task, or final_trace."},
            "limit": {"type": "integer", "default": 5},
            "session_id": {"type": "string"},
        },
        "required": [],
    },
}
MEMORY_REFLECT_SCHEMA = {
    "name": "urban_memory_reflect",
    "description": "Reflect on an Urban-Hermes execution trace, summarize reusable lessons, and optionally promote them into research/tool/feedback memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "goal": {"type": "string"},
            "place": {"type": "string"},
            "trajectory": {"type": "array", "items": {"type": "object"}},
            "execution_trace": {"type": "array", "items": {"type": "object"}},
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "deliverables": {"type": "array", "items": {"type": "object"}},
            "validation": {"type": "object"},
            "review": {"type": "object"},
            "metrics": {"type": "object"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "memory_scope": {"type": "string", "enum": ["working", "reflective"], "default": "reflective"},
            "memory_chain": {"type": "string", "enum": ["research_chain", "execution_chain"]},
            "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": ["research_chain", "execution_chain"]}},
            "record_memory": {"type": "boolean", "default": True},
            "session_id": {"type": "string"},
        },
        "required": ["task"],
    },
}
HOST_FS_SCHEMA = {
    "name": "urban_host_fs",
    "description": "Use native host Python to inspect Windows/host files and folders, including D:/... paths. Prefer this over generic read_file/search_files/terminal on Windows so paths do not go through Git Bash or WSL.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stat", "exists", "list", "glob", "read_text", "read_json", "json_summary", "geojson_summary"],
                "default": "stat",
            },
            "path": {"type": "string", "description": "Native host path such as D:/data/file.geojson or C:/Users/..."},
            "pattern": {"type": "string", "description": "Glob pattern used when action=glob, relative to path when path is a directory."},
            "encoding": {"type": "string", "description": "Optional text encoding override."},
            "limit": {"type": "integer", "default": 100},
            "max_chars": {"type": "integer", "default": 20000},
            "max_bytes": {"type": "integer", "default": 25000000},
        },
        "required": [],
    },
}
HOST_PYTHON_SCHEMA = {
    "name": "urban_host_python",
    "description": "Run a Python script with native host paths and shell=False. Use this for Windows-local data preparation or artifact checks when generic terminal would enter Git Bash/WSL. Use urban_qgis_process for QGIS Processing algorithms.",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to run. The adapter writes it to a native temporary/script file before execution."},
            "script_path": {"type": "string", "description": "Optional existing Python script path to run instead of inline code."},
            "python": {"type": "string", "description": "Optional Python executable. Defaults to the interpreter running Hermes-Urban."},
            "workdir": {"type": "string", "description": "Native host working directory."},
            "output_dir": {"type": "string", "description": "Optional directory where the generated script is preserved for provenance."},
            "argv": {"type": "array", "items": {"type": "string"}},
            "env": {"type": "object"},
            "timeout": {"type": "integer", "default": 300},
            "keep_script": {"type": "boolean", "default": False},
        },
        "required": [],
    },
}
GIS_WORKSPACE_SCHEMA = {
    "name": "urban_gis_workspace",
    "description": "Run the backend-neutral GIS artifact protocol: probe, package, validate, or package-and-validate a GIS workspace from spatial_reasoning_manifest.json. Backends are detachable tool extensions such as qgis_desktop, arcgis_pro, or web_map; currently qgis_desktop is implemented.",
    "parameters": {
        "type": "object",
        "properties": {
            "backend": {
                "type": "string",
                "enum": ["auto", "qgis_desktop", "arcgis_pro"],
                "default": "auto",
                "description": "GIS backend adapter to use. auto currently resolves to qgis_desktop.",
            },
            "mode": {
                "type": "string",
                "enum": ["probe", "package", "validate", "package_and_validate"],
                "default": "package_and_validate",
            },
            "run_dir": {"type": "string", "description": "Experiment run directory containing spatial_reasoning_manifest.json and source layers."},
            "artifact_manifest": {"type": "string", "description": "Optional explicit path to spatial_reasoning_manifest.json."},
            "workspace_dir": {"type": "string", "description": "Existing backend workspace directory, mainly for validate mode."},
            "output_dir": {"type": "string", "description": "Optional backend workspace output directory."},
            "runtime_executable": {"type": "string", "description": "Optional backend runtime executable, e.g. QGIS Python .bat/.exe."},
            "qgis_python": {"type": "string", "description": "Compatibility alias for runtime_executable when backend=qgis_desktop."},
            "arcgis_python": {"type": "string", "description": "Compatibility alias for runtime_executable when backend=arcgis_pro."},
            "template_aprx": {"type": "string", "description": "Optional ArcGIS Pro project template. If omitted, the arcgis_pro backend searches common Blank.aprx locations automatically."},
            "timeout": {"type": "integer", "default": 180},
        },
        "required": [],
    },
}
QGIS_WORKSPACE_SCHEMA = {
    "name": "urban_qgis_workspace",
    "description": "Package completed GIS analysis outputs into a QGIS workspace: source/derived layers, .qgz/.qgs project, visual styles, README, and spatial_reasoning_manifest.json for later agent reasoning. Use this after generating GIS layers instead of leaving only loose GeoJSON/CSV files.",
    "parameters": {
        "type": "object",
        "properties": {
            "workspace_type": {
                "type": "string",
                "enum": ["case1_nanjing_200m", "custom"],
                "default": "custom",
                "description": "Workspace packager type. Use custom with packager_script for all new cases. The case1_nanjing_200m packager is disabled unless allow_case_template=true.",
            },
            "run_dir": {"type": "string", "description": "Experiment run directory containing outputs/ and receiving qgis_workspace/."},
            "packager_script": {"type": "string", "description": "Optional task-specific Python packager authored during the run."},
            "allow_case_template": {"type": "boolean", "default": False, "description": "Explicitly allow a case-specific built-in packager. Leave false for new cases to avoid cross-case template contamination."},
            "qgis_python": {"type": "string", "description": "Optional QGIS Python .bat/.exe path for writing .qgz/.qgs projects."},
            "timeout": {"type": "integer", "default": 600},
        },
        "required": ["run_dir"],
    },
}
QGIS_PROCESS_SCHEMA = {
    "name": "urban_qgis_process",
    "description": "Run a QGIS Processing algorithm with qgis_process and return command logs plus output verification. Use this for real GIS intermediate artifacts instead of merely drafting scripts.",
    "parameters": {
        "type": "object",
        "properties": {
            "algorithm": {"type": "string", "description": "QGIS algorithm id, e.g. native:fixgeometries or native:lineintersections."},
            "parameters": {"type": "object", "description": "QGIS PARAMETER=VALUE map, including OUTPUT paths."},
            "qgis_process": {"type": "string", "description": "Optional explicit qgis_process executable or .bat path."},
            "output_dir": {"type": "string", "description": "Optional directory for qgis_process_log.jsonl."},
            "log_path": {"type": "string", "description": "Optional explicit JSONL command log path."},
            "workdir": {"type": "string"},
            "timeout": {"type": "integer", "default": 300},
            "verbose": {"type": "boolean", "default": False},
        },
        "required": ["algorithm", "parameters"],
    },
}
