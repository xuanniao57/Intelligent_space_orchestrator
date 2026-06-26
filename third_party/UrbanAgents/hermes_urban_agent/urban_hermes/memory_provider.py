"""Hermes MemoryProvider for UrbanAgent feedback, place, and research memory."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import DEFAULT_MEMORY_ROOT, ensure_paths

ensure_paths()

from agent.memory_provider import MemoryProvider


MEMORY_SCOPES = {
    "working": "Conversation/session-scoped memory that is loaded first by Hermes and may decay or compact with the active dialogue.",
    "reflective": "Cross-session memory promoted from research references, domain conventions, review failures, or human corrections.",
}

MEMORY_CHAINS = {
    "research_chain": "Research-facing records: question, evidence, variables, units, methods, and validity caveats.",
    "execution_chain": "Execution-facing records: tool calls, procedures, artifacts, validation, review, cost, duration, and repairs.",
}

CONTENT_LAYERS = {
    "research_design": "Problem-data-algorithm research design memory with temporal, spatial, and population descriptors.",
    "urban_method": "Urban/spatial/social analysis method memory: conventions, scientific cautions, units, proxies, and validation concerns.",
    "tool_artifact": "Concrete tool, algorithm, file-format, and artifact-presentation memory such as QGIS/Rhino/segmentation validation rules.",
    "place_case": "Place- or case-bound context that indexes the other content layers to a district, project, or repeated site.",
    "feedback_correction": "Human or reviewer correction promoted into reusable guidance.",
}

DEFAULT_MEMORY_SCOPE = "reflective"
PLANNING_CONTENT_LAYERS = {"research_design"}
METHOD_CONTENT_LAYERS = {"urban_method"}
EXECUTION_CONTENT_LAYERS = {"tool_artifact"}
EXECUTION_CHAIN_LAYERS = {"tool_artifact", "feedback_correction"}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _tokens(value: Any) -> set[str]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return set(re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]+", text.lower()))


def _record_search_text(record: dict[str, Any]) -> str:
    fields = [
        "summary",
        "method_hint",
        "domain",
        "triggers",
        "caveats",
        "place",
        "correction",
        "evidence_scope",
        "problem_data_algorithm",
        "temporal_scope",
        "spatial_scope",
        "population_scope",
    ]
    return json.dumps(
        [record.get(field) for field in fields if record.get(field) not in (None, [], {})],
        ensure_ascii=False,
        default=str,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _append_jsonl(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "record_id": payload.get("record_id") or f"urban_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
        "timestamp": datetime.now().isoformat(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item).strip()]


def _normalize_scope(value: Any) -> str:
    scope = str(value or DEFAULT_MEMORY_SCOPE).strip().lower()
    return scope if scope in MEMORY_SCOPES else DEFAULT_MEMORY_SCOPE


def _normalize_memory_chain(value: Any, *, content_layer: str) -> str:
    chain = str(value or "").strip().lower()
    if chain in MEMORY_CHAINS:
        return chain
    if content_layer in EXECUTION_CHAIN_LAYERS:
        return "execution_chain"
    return "research_chain"


def _linked_memory_chains(payload: dict[str, Any], *, content_layer: str, memory_chain: str) -> list[str]:
    explicit = [item.strip().lower() for item in _string_list(payload.get("linked_memory_chains") or payload.get("memory_chains"))]
    explicit = [item for item in explicit if item in MEMORY_CHAINS]
    if explicit:
        return explicit
    if content_layer in {"place_case", "feedback_correction", "urban_method"}:
        return ["research_chain", "execution_chain"]
    return [memory_chain]


def _infer_content_layer(payload: dict[str, Any], *, default: str) -> str:
    explicit = str(payload.get("content_layer") or payload.get("knowledge_layer") or payload.get("memory_layer") or "").strip().lower()
    if explicit in CONTENT_LAYERS:
        return explicit
    memory_type = str(payload.get("memory_type") or "").strip().lower()
    if memory_type in CONTENT_LAYERS:
        return memory_type
    domain = str(payload.get("domain") or "").lower()
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    if any(term in domain or term in text for term in ["qgis", "rhino", "grasshopper", "qml", "qgz", "qgs", "manifest", "semantic segmentation", "segmentation", "artifact", "workspace", "tool"]):
        return "tool_artifact"
    if any(term in domain or term in text for term in ["method", "spatial_unit", "buffer", "maup", "proxy", "network", "可达性", "缓冲", "网格", "空间句法", "尺度"]):
        return "urban_method"
    if any(term in domain or term in text for term in ["paper", "literature", "variable", "research", "problem", "algorithm", "y变量", "x变量", "变量", "论文"]):
        return "research_design"
    return default if default in CONTENT_LAYERS else "feedback_correction"


def _base_memory_metadata(payload: dict[str, Any], *, default_layer: str) -> dict[str, Any]:
    content_layer = _infer_content_layer(payload, default=default_layer)
    memory_chain = _normalize_memory_chain(payload.get("memory_chain") or payload.get("chain"), content_layer=content_layer)
    return {
        "memory_scope": _normalize_scope(payload.get("memory_scope") or payload.get("scope")),
        "memory_chain": memory_chain,
        "linked_memory_chains": _linked_memory_chains(payload, content_layer=content_layer, memory_chain=memory_chain),
        "content_layer": content_layer,
        "source_kind": payload.get("source_kind") or payload.get("source") or "agent_record",
        "promotion_state": payload.get("promotion_state") or "promoted",
    }


def _enrich_record(record: dict[str, Any], *, default_layer: str) -> dict[str, Any]:
    enriched = dict(record)
    if "memory_scope" not in enriched:
        enriched["memory_scope"] = _normalize_scope(enriched.get("scope"))
    if "content_layer" not in enriched:
        enriched["content_layer"] = _infer_content_layer(enriched, default=default_layer)
    if "memory_chain" not in enriched:
        enriched["memory_chain"] = _normalize_memory_chain(enriched.get("chain"), content_layer=str(enriched.get("content_layer") or default_layer))
    if "linked_memory_chains" not in enriched:
        enriched["linked_memory_chains"] = _linked_memory_chains(enriched, content_layer=str(enriched.get("content_layer") or default_layer), memory_chain=str(enriched.get("memory_chain") or "research_chain"))
    if "source_kind" not in enriched:
        enriched["source_kind"] = enriched.get("source") or enriched.get("timestamp") or "unknown"
    if "promotion_state" not in enriched:
        enriched["promotion_state"] = "seed" if str(enriched.get("timestamp")) == "seed" else "promoted"
    return enriched


def _filters_from_args(args: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    layers = {str(item).strip().lower() for item in _as_list(args.get("content_layers") or args.get("content_layer") or args.get("knowledge_layers")) if str(item).strip()}
    scopes = {str(item).strip().lower() for item in _as_list(args.get("memory_scopes") or args.get("memory_scope") or args.get("scopes")) if str(item).strip()}
    chains = {str(item).strip().lower() for item in _as_list(args.get("memory_chains") or args.get("memory_chain") or args.get("chains")) if str(item).strip()}
    chains = {item for item in chains if item in MEMORY_CHAINS}
    return layers, scopes, chains


def _apply_axis_filters(records: list[dict[str, Any]], *, content_layers: set[str] | None = None, memory_scopes: set[str] | None = None, memory_chains: set[str] | None = None) -> list[dict[str, Any]]:
    content_layers = content_layers or set()
    memory_scopes = memory_scopes or set()
    memory_chains = memory_chains or set()
    filtered = []
    for record in records:
        if content_layers and str(record.get("content_layer", "")).lower() not in content_layers:
            continue
        if memory_scopes and str(record.get("memory_scope", "")).lower() not in memory_scopes:
            continue
        linked_chains = {str(item).lower() for item in _as_list(record.get("linked_memory_chains"))}
        record_chain = str(record.get("memory_chain", "")).lower()
        if memory_chains and record_chain not in memory_chains and not (linked_chains & memory_chains):
            continue
        filtered.append(record)
    return filtered


def _compact_memory_card(record: dict[str, Any]) -> dict[str, Any]:
    """Keep prefetch cards compact so tool procedures stay on-demand."""
    return {
        key: record.get(key)
        for key in [
            "record_id",
            "memory_scope",
            "memory_chain",
            "linked_memory_chains",
            "content_layer",
            "memory_type",
            "domain",
            "summary",
            "method_hint",
            "caveats",
            "triggers",
        ]
        if key in record and record.get(key) not in (None, [], {})
    }


@dataclass
class FeedbackMemoryProvider:
    """Local feedback lesson store used by UrbanMemoryProvider."""

    root: Path

    @property
    def path(self) -> Path:
        return self.root / "feedback_memory" / "feedback_lessons.jsonl"

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = str(payload.get("summary") or payload.get("correction") or "Urban feedback lesson")
        record = {
            **_base_memory_metadata(payload, default_layer="feedback_correction"),
            "memory_type": "feedback",
            "summary": summary,
            "triggers": _string_list(payload.get("triggers")),
            "place": payload.get("place"),
            "correction": payload.get("correction"),
            "review_policy": payload.get("review_policy"),
            "payload": payload,
        }
        _append_jsonl(self.path, record)
        return record

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        records = [_enrich_record(record, default_layer="feedback_correction") for record in _read_jsonl(self.path)]
        return _rank_records(records, query, limit=limit)


@dataclass
class PlaceMemoryProvider:
    """Local place-context store used by UrbanMemoryProvider."""

    root: Path

    @property
    def path(self) -> Path:
        return self.root / "place_memory" / "place_context.jsonl"

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        place = str(payload.get("place") or payload.get("location") or "unknown-place")
        record = {
            **_base_memory_metadata(payload, default_layer="place_case"),
            "memory_type": "place",
            "place": place,
            "summary": str(payload.get("summary") or payload.get("correction") or f"Context for {place}"),
            "triggers": [place.lower()],
            "payload": payload,
        }
        _append_jsonl(self.path, record)
        return record

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        records = [_enrich_record(record, default_layer="place_case") for record in _read_jsonl(self.path)]
        return _rank_records(records, query, limit=limit)

    def context_for_place(self, place: str, *, limit: int = 5) -> list[dict[str, Any]]:
        records = [_enrich_record(record, default_layer="place_case") for record in _read_jsonl(self.path)]
        lowered = place.lower()
        matches = [record for record in records if lowered in str(record.get("place", "")).lower() or lowered in json.dumps(record, ensure_ascii=False).lower()]
        return matches[-limit:]


@dataclass
class ResearchMemoryProvider:
    """Reusable urban research-design lessons, not hard-coded workflow rules."""

    root: Path

    @property
    def path(self) -> Path:
        return self.root / "research_memory" / "research_lessons.jsonl"

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = str(payload.get("summary") or payload.get("lesson") or "Urban research design lesson")
        content_layer = _infer_content_layer(payload, default="research_design")
        memory_type = str(payload.get("memory_type") or content_layer or "research_design")
        record = {
            **_base_memory_metadata(payload, default_layer=content_layer),
            "memory_type": memory_type,
            "summary": summary,
            "triggers": _string_list(payload.get("triggers")),
            "domain": payload.get("domain") or "urban_analysis",
            "method_hint": payload.get("method_hint"),
            "evidence_scope": payload.get("evidence_scope"),
            "caveats": payload.get("caveats") or [],
            "problem_data_algorithm": payload.get("problem_data_algorithm"),
            "temporal_scope": payload.get("temporal_scope"),
            "spatial_scope": payload.get("spatial_scope"),
            "population_scope": payload.get("population_scope"),
            "payload": payload,
        }
        _append_jsonl(self.path, record)
        return record

    def search(self, query: str, *, limit: int = 5, content_layers: set[str] | None = None, memory_scopes: set[str] | None = None, memory_chains: set[str] | None = None) -> list[dict[str, Any]]:
        records = [_enrich_record(record, default_layer="research_design") for record in [*_builtin_research_lessons(), *_read_jsonl(self.path)]]
        records = _apply_axis_filters(records, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains)
        return _rank_records(records, query, limit=limit)

    def list(self, *, limit: int = 20, content_layers: set[str] | None = None, memory_scopes: set[str] | None = None, memory_chains: set[str] | None = None) -> list[dict[str, Any]]:
        records = [_enrich_record(record, default_layer="research_design") for record in [*_builtin_research_lessons(), *_read_jsonl(self.path)]]
        records = _apply_axis_filters(records, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains)
        return records[-limit:]


class UrbanMemoryProvider(MemoryProvider):
    """Single Hermes external provider that composes feedback and place memory."""

    def __init__(self, root: str | Path | None = None) -> None:
        raw_root = root or os.getenv("URBAN_HERMES_MEMORY_ROOT") or DEFAULT_MEMORY_ROOT
        self.root = Path(raw_root).expanduser().resolve()
        self.feedback = FeedbackMemoryProvider(self.root)
        self.place = PlaceMemoryProvider(self.root)
        self.research = ResearchMemoryProvider(self.root)
        self._session_id = ""
        self._platform = ""
        self._initialized = False

    @property
    def name(self) -> str:
        return "urban_memory"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._platform = str(kwargs.get("platform") or "local")
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def system_prompt_block(self) -> str:
        return (
            "Urban memory provider is active. Use retrieval facets rather than loading everything. "
            "memory_chain separates research-facing records from execution-facing records; content_layer narrows "
            "the slice to research-design, urban-method, tool-artifact, place/case, or feedback-correction memory. "
            "Before urban analysis, recall task-relevant cards progressively: first compact research-design "
            "cues for the main plan, then branch-local method cards only after a concrete method branch exists, "
            "then selected tool-artifact procedures for execution and review. "
            "Treat recalled lessons as professional cues, not automatic facts or hard-coded rules. Store "
            "new reusable lessons when the user changes a spatial unit, data source, scale, stakeholder "
            "caveat, variable operationalization, artifact validation rule, or rerun instruction. "
            "After each major analysis step, use urban_review as a reviewer pause: ask what the step "
            "implies about time, space, and people; what it ignores; what assumptions it carries; "
            "and what further analysis would be possible before moving to the next claim. "
            "For concrete urban-analysis tasks with an output directory, maintain an observable workflow "
            "trace instead of only a final answer: save the main workflow plan, worker or tool-task records, "
            "per-step reviewer pauses, artifact readiness, claim gates, and main/worker reflections. "
            "The main plan must name each step, why that step is needed, expected artifacts, and review risks. "
            "After saving the main plan, show a compact human-readable plan in the CLI before execution: "
            "steps, expected artifacts, review risks, delegation plan, claim gates, and branch choices. "
            "Do not rely on a todo count or hidden workflow_plan.json as the user's only view of the plan. "
            "Wait for the user to approve, revise, or block the plan before starting artifact-producing "
            "worker/model/GIS execution beyond basic grounding and inventory. Record that decision in the "
            "trace as human_plan_decision or plan_approval, including whether the plan was shown, the user "
            "response, requested changes, approved steps, and timestamp. "
            "Do not let recalled memory or the capability catalog silently create the main workflow. "
            "For prepared data canvases, first audit data roles, spatial and temporal units, existing "
            "model/map artifacts, and claim boundaries. Propose density, connectivity, accessibility, "
            "topology, or GIS-packaging work only as optional branches when the current canvas and the "
            "user's question justify them. Treat tool-artifact memories such as QGIS packaging, layer naming, "
            "renderer checks, and manifest validation as downstream readiness constraints rather than "
            "automatic analysis steps. "
            "When delegation is available, do not keep all artifact-producing analysis in the main context: "
            "use delegate_task for at least one bounded worker task unless the task is only a single tool call; "
            "record worker input, worker output, and parent verification in the trace. "
            "For multi-step artifact-producing analysis, call delegate_task before doing all worker-suitable "
            "analysis yourself; a record that labels parent_agent as the worker does not satisfy delegation. "
            "When calling delegate_task for urban analysis, pass a self-contained context: exact data paths, "
            "the worker output subdirectory, allowed toolsets such as urban, the expected file handles, and "
            "a required JSON-style return with status, files_written, assumptions, and errors. "
            "For delegated worker packets, explicitly tell the child it is an Urban-Hermes worker, not the "
            "main planner; require role=worker, status, files_written, operations, time_space_people_notes, "
            "assumptions, errors, and claim_boundaries. The worker should write artifacts but not make final "
            "paper claims. For delegated reviewer packets, explicitly tell the child it is an independent "
            "Urban-Hermes reviewer; require role=reviewer, status, checked_files, time_review, space_review, "
            "people_review, artifact_readiness, claim_gates, hard_failures, and recommendation. The reviewer "
            "should inspect and judge artifacts, not silently repair them. "
            "For worker-reviewer dialogue, use distinct delegated roles when feasible: one worker produces "
            "analysis artifacts, a separate reviewer inspects those artifacts, and the main agent verifies both. "
            "Do not implement the worker and reviewer as sections of one main-agent script and label that as "
            "multi-agent dialogue. If a worker returns no usable artifacts, retry a narrower delegated worker "
            "once before any main-agent fallback; if fallback is used, record actual_executor=main_agent_fallback "
            "and mark the trace not fully delegated. "
            "Call urban_review after each execution step, not only at the end, and save one review record per step. "
            "Separate worker_reflection, reviewer_reflection, main_reflection, and memory_carryover notes. "
            "A per-step review record is incomplete if it only contains a score or warnings; it must name "
            "time, space, and people implications, ignored or missing evidence, assumptions, further analysis, "
            "artifact readiness, claim impact, and the next action. "
            "If a delegated worker fails, times out, or is interrupted, preserve the raw failure, record the "
            "recovery path, and distinguish worker-produced artifacts from main-agent fallback artifacts. "
            "Claim gates must be claim-level: descriptive association may proceed when supported, while causal, "
            "policy, people-specific, perception, or local-mechanism claims should be downgraded or blocked when "
            "the evidence or diagnostics are missing. "
            "Before finalizing, validate the trace itself: require main_workflow_plan, worker_task_records, "
            "human_plan_decision or plan_approval, parent_verification, per_step_review_records, claim_gates, "
            "artifact_manifest, worker_reflection, reviewer_reflection, main_reflection, and memory_carryover. "
            "Artifact readiness is not ready unless reusable downstream files are inventoried, including tables, "
            "maps or GIS layers, model diagnostics when used, and a manifest such as spatial_reasoning_manifest.json. "
            "For spatial analysis with reusable outputs, produce or package at least one map/GIS layer plus a "
            "spatial reasoning manifest; otherwise mark artifact readiness as not ready. "
            "After writing or repairing the final trace, call urban_review on that saved trace. If the final "
            "review does not pass the threshold, do not call the trace validated; either repair and review again "
            "or report the run as failed with reasons. "
            "If delegation or per-step review is skipped, record why in the trace. "
            "Do not hard-code a case-specific step list; let the main plan fit the user's task."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        feedback = [_compact_memory_card(item) for item in self.feedback.search(query, limit=4)]
        places = [_compact_memory_card(item) for item in self.place.search(query, limit=4)]
        planning = [
            _compact_memory_card(item)
            for item in self.research.search(
                query,
                limit=4,
                content_layers=PLANNING_CONTENT_LAYERS,
                memory_scopes={"reflective"},
                memory_chains={"research_chain"},
            )
        ]
        tool_artifact_index = [
            {
                "record_id": item.get("record_id"),
                "memory_chain": item.get("memory_chain"),
                "linked_memory_chains": item.get("linked_memory_chains"),
                "content_layer": item.get("content_layer"),
                "summary": item.get("summary"),
                "triggers": item.get("triggers"),
            }
            for item in self.research.search(
                query,
                limit=2,
                content_layers=EXECUTION_CONTENT_LAYERS,
                memory_scopes={"reflective"},
                memory_chains={"execution_chain"},
            )
        ]
        if not feedback and not places and not planning and not tool_artifact_index:
            return ""
        payload = {
            "provider": self.name,
            "session_id": session_id or self._session_id,
            "memory_axes": _memory_axes_payload(),
            "loading_order": _memory_loading_order(),
            "planning_memory_cards": planning,
            "feedback_lessons": feedback,
            "place_context": places,
            "deferred_method_memory_instruction": (
                "Do not load urban_method cards into the global main plan. When a branch, worker, or reviewer "
                "needs a concrete method such as GWR, GWRF, SHAP/PDP, temporal stratification, or street-view "
                "alignment, call urban_research_memory with content_layer='urban_method', branch_id, "
                "retrieval_scope='branch_local', and record the result in memory_retrieval_log. Treat the "
                "retrieved card as temporary context for that branch, not as a template for unrelated branches."
            ),
            "deferred_tool_artifact_index": tool_artifact_index,
            "deferred_tool_artifact_instruction": "Fetch full tool_artifact procedures with urban_research_memory only when execution or review needs concrete software/artifact rules.",
        }
        return "[Urban memory recall]\n" + json.dumps(payload, ensure_ascii=False, default=str, indent=2)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        return None

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        text = f"{user_content}\n{assistant_content}"
        if _looks_like_feedback(text):
            self.feedback.record(
                {
                    "summary": _shorten(text, 300),
                    "triggers": sorted(_tokens(text))[:12],
                    "session_id": session_id or self._session_id,
                    "source": "sync_turn",
                }
            )

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [URBAN_MEMORY_SEARCH_SCHEMA, URBAN_MEMORY_RECORD_SCHEMA, URBAN_PLACE_CONTEXT_SCHEMA, URBAN_RESEARCH_MEMORY_SCHEMA, URBAN_MEMORY_REFLECT_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if tool_name == "urban_memory_search":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 5)
            memory_types = set(_string_list(args.get("memory_types") or ["feedback", "place"]))
            content_layers, memory_scopes, memory_chains = _filters_from_args(args)
            result: dict[str, Any] = {
                "query": query,
                "memory_root": str(self.root),
                "memory_axes": _memory_axes_payload(),
                "loading_order": _memory_loading_order(),
                "filters": {"memory_types": sorted(memory_types), "content_layers": sorted(content_layers), "memory_scopes": sorted(memory_scopes), "memory_chains": sorted(memory_chains)},
            }
            if "feedback" in memory_types:
                records = self.feedback.search(query, limit=max(limit * 2, limit))
                result["feedback_lessons"] = _apply_axis_filters(records, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains)[:limit]
            if "place" in memory_types:
                records = self.place.search(query, limit=max(limit * 2, limit))
                result["place_context"] = _apply_axis_filters(records, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains)[:limit]
            if "research" in memory_types or "research_design" in memory_types:
                result["research_design_lessons"] = self.research.search(query, limit=limit, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains)
            return _json({"success": True, "result": result})
        if tool_name == "urban_memory_record":
            memory_type = str(args.get("memory_type") or "feedback")
            content_layer = _infer_content_layer(args, default="feedback_correction")
            should_record_research = memory_type in {"research", "research_design", "urban_method", "tool_artifact"} or content_layer in {"research_design", "urban_method", "tool_artifact"}
            should_record_place = memory_type in {"place", "place_case"} or content_layer == "place_case" or bool(args.get("place") and not should_record_research)
            should_record_feedback = (
                memory_type in {"feedback", "feedback_correction"}
                or content_layer == "feedback_correction"
                or bool(args.get("correction") or args.get("review_policy"))
                or not (should_record_research or should_record_place)
            )
            feedback_record = self.feedback.record(args) if should_record_feedback else None
            place_record = None
            research_record = None
            if should_record_place:
                place_record = self.place.record(args)
            if should_record_research:
                research_record = self.research.record(args)
            return _json({"success": True, "result": {"feedback": feedback_record, "place": place_record, "research": research_record, "memory_root": str(self.root)}})
        if tool_name == "urban_place_context":
            place = str(args.get("place") or args.get("location") or "")
            limit = int(args.get("limit") or 5)
            return _json({"success": True, "result": {"place": place, "records": self.place.context_for_place(place, limit=limit), "memory_root": str(self.root)}})
        if tool_name == "urban_research_memory":
            action = str(args.get("action") or "search")
            limit = int(args.get("limit") or 5)
            content_layers, memory_scopes, memory_chains = _filters_from_args(args)
            branch_id = str(args.get("branch_id") or "").strip()
            retrieval_scope = str(args.get("retrieval_scope") or "").strip() or ("branch_local" if content_layers & METHOD_CONTENT_LAYERS else "global")
            retrieval_context = {
                "branch_id": branch_id,
                "retrieval_scope": retrieval_scope,
                "review_target_type": args.get("review_target_type"),
                "expires_after": args.get("expires_after") or ("branch_review" if retrieval_scope in {"branch_local", "worker_local", "reviewer_local"} else None),
                "context_policy": (
                    "Use retrieved urban_method records only for the named branch/review target. "
                    "Do not promote them into the global plan unless the user explicitly approves that branch."
                )
                if content_layers & METHOD_CONTENT_LAYERS
                else "Use retrieved records as task-relevant cues, not fixed workflow steps.",
            }
            if action == "record":
                return _json({"success": True, "result": {"record": self.research.record(args), "memory_root": str(self.root)}})
            if action == "list":
                return _json({"success": True, "result": {"records": self.research.list(limit=limit, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains), "memory_root": str(self.root), "memory_axes": _memory_axes_payload(), "retrieval_context": retrieval_context}})
            query = str(
                args.get("query")
                or args.get("task")
                or args.get("method_hint")
                or " ".join(_string_list(args.get("triggers") or []))
                or args.get("domain")
                or ""
            )
            return _json({"success": True, "result": {"query": query, "records": self.research.search(query, limit=limit, content_layers=content_layers, memory_scopes=memory_scopes, memory_chains=memory_chains), "memory_root": str(self.root), "memory_axes": _memory_axes_payload(), "loading_order": _memory_loading_order(), "retrieval_context": retrieval_context}})
        if tool_name == "urban_memory_reflect":
            return _json({"success": True, "result": self.reflect_execution(args)})
        return _json({"success": False, "error": f"UrbanMemoryProvider does not handle {tool_name}"})

    def reflect_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = str(payload.get("task") or payload.get("goal") or "urban execution")
        memory_scope = _normalize_scope(payload.get("memory_scope") or payload.get("scope"))
        record_memory = payload.get("record_memory", True) is not False
        observations = _execution_reflection_observations(payload)
        records: list[dict[str, Any]] = []
        for observation in observations:
            record_payload = {
                "summary": observation["summary"],
                "method_hint": observation.get("method_hint"),
                "domain": observation.get("domain"),
                "content_layer": observation["content_layer"],
                "memory_chain": observation.get("memory_chain"),
                "linked_memory_chains": observation.get("linked_memory_chains"),
                "memory_scope": memory_scope,
                "source_kind": "execution_reflection",
                "promotion_state": "promoted" if record_memory else "draft",
                "triggers": observation.get("triggers") or sorted(_tokens(observation["summary"]))[:12],
                "caveats": observation.get("caveats") or [],
                "task": task,
            }
            if observation["content_layer"] == "place_case":
                record_payload["place"] = observation.get("place") or payload.get("place") or task
            if not record_memory:
                records.append({"would_record": record_payload})
                continue
            if observation["content_layer"] in {"research_design", "urban_method", "tool_artifact"}:
                records.append({"research": self.research.record(record_payload)})
            elif observation["content_layer"] == "place_case":
                records.append({"place": self.place.record(record_payload)})
            else:
                records.append({"feedback": self.feedback.record(record_payload)})
        return {
            "task": task,
            "record_memory": record_memory,
            "memory_scope": memory_scope,
            "summary": _summarize_execution_reflection(task, observations),
            "observations": observations,
            "records": records,
            "memory_root": str(self.root),
        }

    def on_memory_write(self, action: str, target: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        if _looks_like_feedback(content):
            self.feedback.record({"summary": content, "triggers": sorted(_tokens(content))[:12], "action": action, "target": target, "metadata": metadata, "source": "builtin_memory_mirror"})

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any) -> None:
        text = f"Delegated task: {task}\nResult: {result}"
        if _looks_like_feedback(text):
            self.feedback.record({"summary": _shorten(text, 300), "triggers": sorted(_tokens(text))[:12], "child_session_id": child_session_id, "source": "delegation"})

    def shutdown(self) -> None:
        self._initialized = False


def register(ctx: Any) -> None:
    """Hermes plugin entry point."""
    ctx.register_memory_provider(UrbanMemoryProvider())


def _memory_axes_payload() -> dict[str, Any]:
    return {
        "temporal_axis": MEMORY_SCOPES,
        "chain_axis": MEMORY_CHAINS,
        "content_axis": CONTENT_LAYERS,
        "note": (
            "Temporal scope controls when memory is loaded and whether it decays or persists; "
            "memory_chain separates research-facing and execution-facing records; content layers slice either chain "
            "for targeted retrieval."
        ),
    }


def _memory_loading_order() -> list[dict[str, Any]]:
    return [
        {
            "stage": "hermes_base_context",
            "scope": "working",
            "content": "Hermes persona/config/project/session context such as soul or project guidance, before Urban-Hermes retrieval.",
            "recipient": "main_agent",
        },
        {
            "stage": "urban_prefetch",
            "scope": "reflective",
            "content": "Compact task-relevant research_design, place_case, and feedback_correction cards. urban_method cards are deferred until a branch-local retrieval is requested.",
            "recipient": "main_agent_planning",
        },
        {
            "stage": "progressive_expansion",
            "scope": "reflective",
            "content": "Only selected tool_artifact schemas, validation rules, scripts, or prior traces needed for execution.",
            "recipient": "executor_or_reviewer",
        },
        {
            "stage": "promotion_after_review",
            "scope": "reflective",
            "content": "Reusable human corrections, reviewer failures, and artifact validation rules normalized into memory records.",
            "recipient": "future_runs",
        },
    ]


def _rank_records(records: list[dict[str, Any]], query: str, *, limit: int) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    lowered = query.lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        haystack = _record_search_text(record).lower()
        triggers = [str(item).lower() for item in record.get("triggers", [])]
        trigger_score = 1.0 if any(trigger and trigger in lowered for trigger in triggers) else 0.0
        overlap_count = len(query_tokens & _tokens(haystack))
        if not trigger_score and len(query_tokens) >= 3 and overlap_count < 2:
            continue
        overlap = overlap_count / max(len(query_tokens), 1)
        score = trigger_score + overlap
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("timestamp", ""))))
    return [record for _, record in scored[:limit]]


def _execution_reflection_observations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    task = str(payload.get("task") or payload.get("goal") or "urban execution")
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    observations: list[dict[str, Any]] = []

    if any(term in text for term in ["qgis", "qgz", "qgs", "renderer", "classattribute", "manifest", "invalid_layers"]):
        observations.append(
            {
                "content_layer": "tool_artifact",
                "domain": "qgis_artifact_validation",
                "summary": "QGIS deliverables should be accepted only after independent project read-back, empty invalid layer lists, metric-layer renderer checks, and manifest consistency checks.",
                "method_hint": "Validate .qgs/.qgz with PyQGIS, inspect QgsGraduatedSymbolRenderer.classAttribute(), verify basemap ordering and manifest metric_layers before reporting success.",
                "triggers": ["qgis", "qgz", "qgs", "renderer", "invalid_layers", "manifest"],
                "caveats": ["Layer names or GeoJSON fields alone are not enough evidence that the rendered map encodes the intended metric."],
            }
        )

    if any(term in text for term in ["delegate_task", "subagent", "delegation", "worker", "reviewer"]):
        observations.append(
            {
                "content_layer": "urban_method",
                "domain": "multi_agent_execution_review",
                "summary": "When Urban-Hermes delegates analysis or artifact generation to subagents, the main agent remains responsible for research design, child-task specification, and final read-back verification.",
                "method_hint": "Require child agents to return verifiable handles such as file paths, validation summaries, and manifest locations; the parent should independently inspect critical outputs before acceptance.",
                "triggers": ["delegate_task", "subagent", "worker", "reviewer", "验收"],
                "caveats": ["Subagent summaries are self-reports until the parent verifies artifacts or metrics."],
            }
        )

    if any(term in text for term in ["ablation", "no_memory", "without memory", "memory-off", "消融", "无记忆", "cost", "duration", "用时"]):
        observations.append(
            {
                "content_layer": "research_design",
                "domain": "memory_ablation_protocol",
                "summary": "Memory ablation for historical-district experiments should compare paired memory-on and memory-off runs with the same prompt, case list, model/provider, validation rubric, duration, and cost accounting.",
                "method_hint": "Record per-case prompt, memory setting, tool calls, elapsed time, token/cost estimate, artifact validity, and reviewer score; summarize matched differences rather than isolated anecdotes.",
                "triggers": ["memory ablation", "no_memory", "消融", "cost", "duration", "历史街区"],
                "caveats": ["Do not attribute all quality differences to memory unless prompts, tools, and validation settings are held constant."],
            }
        )

    place = payload.get("place") or payload.get("location")
    if place:
        observations.append(
            {
                "content_layer": "place_case",
                "domain": "historical_district_case",
                "place": str(place),
                "summary": f"Execution context and validation lessons for {place} should be indexed as a place-case memory rather than mixed into generic method memory.",
                "method_hint": "Store case-specific AOI, data availability, artifact paths, and known validation failures under place_case; keep reusable QGIS or modeling rules in tool_artifact or urban_method memory.",
                "triggers": [str(place), "历史街区", "place_case"],
            }
        )

    issues = _string_list(payload.get("issues") or payload.get("failures") or payload.get("corrections"))
    validation = payload.get("validation") or payload.get("review") or payload.get("quality") or {}
    if issues or (isinstance(validation, dict) and not bool(validation.get("passed", True))):
        issue_text = "; ".join(issues[:5]) or _shorten(json.dumps(validation, ensure_ascii=False, default=str), 240)
        observations.append(
            {
                "content_layer": "feedback_correction",
                "domain": "execution_quality_feedback",
                "summary": f"Execution review found reusable correction points for {task}: {issue_text}",
                "method_hint": "Promote repeated review failures into feedback memory and require the next run to pre-check them before final reporting.",
                "triggers": ["review", "feedback", "correction", "复盘", "验收"],
            }
        )

    if observations:
        return observations
    return [
        {
            "content_layer": "feedback_correction",
            "domain": "execution_reflection",
            "summary": f"Execution reflection for {task} produced no specialized rule; preserve the trace as a lightweight review checkpoint.",
            "method_hint": "Use more explicit artifacts, validation results, issues, or metrics when asking for reflective memory promotion.",
            "triggers": ["execution_reflection", "review", "memory"],
        }
    ]


def _summarize_execution_reflection(task: str, observations: list[dict[str, Any]]) -> str:
    layers = []
    for observation in observations:
        layer = str(observation.get("content_layer") or "unknown")
        if layer not in layers:
            layers.append(layer)
    return f"Reflected on {task}; produced {len(observations)} reusable observation(s) across {', '.join(layers)}."


def _builtin_research_lessons() -> list[dict[str, Any]]:
    """Built-in seed lessons used as recallable cues, not fixed policies."""
    seed_path = Path(__file__).with_name("research_memory_seed.json")
    if seed_path.exists():
        try:
            data = json.loads(seed_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
    return [
        {
            "record_id": "builtin_aoi_context_buffer_pattern",
            "timestamp": "builtin",
            "memory_type": "research_design",
            "domain": "spatial_scope",
            "summary": (
                "Many urban studies distinguish an authoritative AOI or study boundary from a larger "
                "context buffer used to collect surrounding roads, buildings, POIs, viewsheds, or spillover "
                "conditions. Treat AOI/context-buffer separation as a task-relevant research design cue, "
                "not as a universal hard rule."
            ),
            "triggers": ["aoi", "context buffer", "buffer", "研究范围", "历史街区", "空间范围"],
            "method_hint": "Ask or infer whether the user supplied an AOI, a context buffer, or both; label exploratory scope explicitly when the authoritative AOI is missing.",
            "caveats": ["Do not silently substitute a context buffer for the analytic AOI.", "Buffer size should be justified by research question and domain convention."],
        },
        {
            "record_id": "builtin_grid_units_for_perception_models",
            "timestamp": "builtin",
            "memory_type": "research_design",
            "domain": "spatial_unit_design",
            "summary": (
                "For studies linking historical-district built environment to subjective perception, uniform "
                "grid cells such as 200m x 200m can increase sample size and improve X/Y spatial alignment "
                "compared with one observation per district. Social-media perception signals can be aggregated "
                "to the same grid cells as built-environment indicators."
            ),
            "triggers": ["历史感", "主观感知", "social media", "小红书", "grid", "200m", "网格", "建成环境"],
            "method_hint": "Consider 200m grids, street segments, or blocks; compare sensitivity across spatial units and report MAUP risks.",
            "caveats": ["Grid size is a research design choice, not a law.", "Avoid machine learning on a few dozen district-level observations unless the design supports it."],
        },
        {
            "record_id": "builtin_social_media_y_alignment",
            "timestamp": "builtin",
            "memory_type": "research_design",
            "domain": "variable_operationalization",
            "summary": (
                "When using social-media posts to represent historical-sense perception, geocode posts, align "
                "them to the chosen spatial unit and observation window, and model posting bias, visitor bias, "
                "platform demographics, duplicate posts, and text/image sentiment uncertainty."
            ),
            "triggers": ["小红书", "社交媒体", "游客", "历史感", "perception", "Y变量", "subjective"],
            "method_hint": "Aggregate historical-sense labels/scores per grid or segment; keep the Y construction separate from X indicators before modeling.",
            "caveats": ["Social-media signals are not representative surveys.", "Do not overclaim causality without design or validation."],
        },
        {
            "record_id": "builtin_paper_gap_variable_verifiability",
            "timestamp": "builtin",
            "memory_type": "research_design",
            "domain": "paper_gap",
            "summary": (
                "A useful paper gap for urban-analysis agents is variable verifiability: the agent should map "
                "research questions to measurable variables, required data, spatial/temporal units, validation "
                "checks, and comparable literature choices, then flag variables that are only proxies or missing."
            ),
            "triggers": ["gap", "paper", "变量", "可验证", "研究设计", "literature", "method"],
            "method_hint": "Return a research design table with question, X/Y variables, data, unit, model family, validation, and risks.",
            "caveats": ["Literature memory should guide alternatives, not force a single template."],
        },
    ]


def _looks_like_feedback(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "correction",
        "correct",
        "override",
        "feedback",
        "review",
        "rerun",
        "barrier",
        "stakeholder",
        "scale",
        "source",
        "license",
        "human",
        "纠正",
        "反馈",
        "修复",
        "复盘",
        "验收",
        "重跑",
        "尺度",
        "数据源",
        "利益相关",
        "图层",
        "manifest",
    ]
    return any(marker in lowered for marker in markers)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


URBAN_MEMORY_SEARCH_SCHEMA = {
    "name": "urban_memory_search",
    "description": "Search UrbanAgent memory across temporal scopes and content layers.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "memory_types": {"type": "array", "items": {"type": "string", "enum": ["feedback", "place", "research", "research_design"]}},
            "content_layers": {"type": "array", "items": {"type": "string", "enum": list(CONTENT_LAYERS)}},
            "memory_scopes": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_SCOPES)}},
            "memory_chains": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_CHAINS)}},
            "branch_id": {"type": "string"},
            "review_target_type": {"type": "string"},
            "retrieval_scope": {"type": "string", "enum": ["global", "branch_local", "worker_local", "reviewer_local"]},
            "expires_after": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
}

URBAN_MEMORY_RECORD_SCHEMA = {
    "name": "urban_memory_record",
    "description": "Record a reusable urban feedback lesson and optional place context.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "correction": {"type": "string"},
            "place": {"type": "string"},
            "triggers": {"type": "array", "items": {"type": "string"}},
            "memory_type": {"type": "string", "enum": ["feedback", "place", "research", "research_design", "urban_method", "tool_artifact", "place_case", "feedback_correction"], "default": "feedback"},
            "content_layer": {"type": "string", "enum": list(CONTENT_LAYERS)},
            "memory_scope": {"type": "string", "enum": list(MEMORY_SCOPES), "default": DEFAULT_MEMORY_SCOPE},
            "memory_chain": {"type": "string", "enum": list(MEMORY_CHAINS)},
            "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_CHAINS)}},
            "source_kind": {"type": "string"},
            "promotion_state": {"type": "string"},
        },
        "required": ["summary"],
    },
}

URBAN_PLACE_CONTEXT_SCHEMA = {
    "name": "urban_place_context",
    "description": "Retrieve stored place context for a specific urban location.",
    "parameters": {"type": "object", "properties": {"place": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["place"]},
}

URBAN_RESEARCH_MEMORY_SCHEMA = {
    "name": "urban_research_memory",
    "description": "Search, list, or record reusable urban memories. Records have a temporal scope and a content layer: research_design, urban_method, tool_artifact, place_case, or feedback_correction.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "record", "list"], "default": "search"},
            "query": {"type": "string"},
            "task": {"type": "string"},
            "summary": {"type": "string"},
            "method_hint": {"type": "string"},
            "domain": {"type": "string"},
            "content_layer": {"type": "string", "enum": list(CONTENT_LAYERS)},
            "memory_scope": {"type": "string", "enum": list(MEMORY_SCOPES), "default": DEFAULT_MEMORY_SCOPE},
            "memory_chain": {"type": "string", "enum": list(MEMORY_CHAINS)},
            "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_CHAINS)}},
            "source_kind": {"type": "string"},
            "problem_data_algorithm": {"type": "object"},
            "temporal_scope": {"type": "object"},
            "spatial_scope": {"type": "object"},
            "population_scope": {"type": "object"},
            "triggers": {"type": "array", "items": {"type": "string"}},
            "caveats": {"type": "array", "items": {"type": "string"}},
            "content_layers": {"type": "array", "items": {"type": "string", "enum": list(CONTENT_LAYERS)}},
            "memory_scopes": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_SCOPES)}},
            "memory_chains": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_CHAINS)}},
            "limit": {"type": "integer", "default": 5},
        },
        "required": [],
    },
}

URBAN_MEMORY_REFLECT_SCHEMA = {
    "name": "urban_memory_reflect",
    "description": "Reflect on an Urban-Hermes execution trace and optionally promote reusable lessons into memory. memory_chain is a retrieval facet, not a separate storage backend.",
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
            "memory_scope": {"type": "string", "enum": list(MEMORY_SCOPES), "default": DEFAULT_MEMORY_SCOPE},
            "memory_chain": {"type": "string", "enum": list(MEMORY_CHAINS)},
            "linked_memory_chains": {"type": "array", "items": {"type": "string", "enum": list(MEMORY_CHAINS)}},
            "record_memory": {"type": "boolean", "default": True},
        },
        "required": ["task"],
    },
}
