"""Zhichang Tongyu adapter around the vendored Hermes runtime.

This module keeps the central hub on a real Agent runtime path:

1. physical semantics enter as a Hermes turn;
2. short and long memory are compacted into context;
3. the zhichang toolset is registered in Hermes;
4. the model/tool execution path is attempted through Hermes;
5. dispatch and ACK feedback are recorded back into the same turn.

The UI consumes the public trajectory extracted here. It is not private
chain-of-thought; it is a concise audit log of inputs, tool calls, outputs,
and physical feedback.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from agent_planner import LLMConfig, _candidate_env_files, _read_env_values, load_llm_configs


CST = timezone(timedelta(hours=8))
TOOLSET = "zhichang"


ZHICHANG_TOOL_NAMES = [
    "zhichang_observe_scene",
    "zhichang_retrieve_context",
    "zhichang_select_scene_policy",
    "zhichang_plan_device_commands",
    "zhichang_emit_device_command",
    "zhichang_record_physical_feedback",
]


ZHICHANG_SKILLS = [
    {
        "id": "spray_scene",
        "name": "spray.scene",
        "target_type": "spray_gateway",
        "description": "Mist or stop a zone with duration and intensity bounds.",
        "required_params": ["op", "zone", "duration_sec", "intensity"],
    },
    {
        "id": "speaker_play",
        "name": "speaker.play",
        "target_type": "speaker_gateway",
        "description": "Play a named music, voice, or soundscape asset.",
        "required_params": ["op", "content_id", "volume", "loop"],
    },
    {
        "id": "projection_play",
        "name": "projection.play",
        "target_type": "projection_gateway",
        "description": "Project a visual asset or sound-reactive visual scene.",
        "required_params": ["op", "content_id", "loop"],
    },
    {
        "id": "lan_raw_command",
        "name": "lan.raw_command",
        "target_type": "lan_control_gateway",
        "description": "Send or dry-run registered TCP/UDP STR/HEX commands for lighting, projectors, playback controllers, and PCs.",
        "required_params": ["protocol", "host", "port", "payload", "payload_format"],
    },
    {
        "id": "lan_wol",
        "name": "lan.wol",
        "target_type": "lan_control_gateway",
        "description": "Wake a registered display/control PC by MAC address using Wake-on-LAN.",
        "required_params": ["mac"],
    },
    {
        "id": "g1_unitree_sdk_sequence",
        "name": "g1.unitree_sdk_sequence",
        "target_type": "robot",
        "description": "Issue a safe, staged Unitree G1 dry-run action sequence.",
        "required_params": ["scene_id", "speech_cn", "safety", "sdk_sequence"],
    },
]


DEFAULT_TARGET_IDS = {
    "robot": "unitree_g1",
    "spray_gateway": "spray_gateway",
    "speaker_gateway": "speaker_gateway",
    "projection_gateway": "projection_gateway",
    "lan_control_gateway": "lan_control_gateway",
}


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}+08:00"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _ok(result: Any, **meta: Any) -> str:
    payload = {"success": True, "result": result}
    payload.update(meta)
    return _json(payload)


def _compact(value: Any, max_chars: int = 700) -> Any:
    text = _json(value)
    if len(text) <= max_chars:
        return value
    return {"preview": text[:max_chars] + "...", "truncated": True}


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_device_command(command: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(command, Mapping):
        return None
    target_type = str(command.get("target_type") or "")
    target_id = str(command.get("target_id") or DEFAULT_TARGET_IDS.get(target_type) or "")
    body = command.get("command")
    if isinstance(body, Mapping):
        command_type = str(body.get("type") or command.get("type") or command.get("command_type") or "")
        params = body.get("params") if isinstance(body.get("params"), Mapping) else command.get("params")
    else:
        command_type = str(command.get("type") or command.get("command_type") or "")
        params = command.get("params")
    if not target_type or not command_type:
        return None
    return {
        "target_id": target_id,
        "target_type": target_type,
        "command": {"type": command_type, "params": dict(params or {})},
        "routing": dict(command.get("routing") or {}),
        "ack_required": bool(command.get("ack_required", True)),
        "timeout_ms": int(command.get("timeout_ms") or 60000),
    }


def _normalize_device_commands(commands: Any) -> List[Dict[str, Any]]:
    if not isinstance(commands, list):
        return []
    normalized = []
    for command in commands:
        item = _normalize_device_command(command)
        if item:
            normalized.append(item)
    return normalized


def _summarize_frame(frame: Mapping[str, Any]) -> str:
    scene = frame.get("scene") or {}
    summary = scene.get("summary") or scene.get("situation_id") or frame.get("frame_id") or "scene semantic frame"
    tags = ", ".join(str(tag) for tag in frame.get("semantic_tags") or []) or "no tags"
    return f"{frame.get('space_id', 'unknown')} / {summary} / {tags}"


def _detect_policy(frame: Mapping[str, Any]) -> str:
    scene = frame.get("scene") or {}
    haystack = " ".join(
        str(item)
        for item in [
            scene.get("situation_id"),
            scene.get("intent_hint"),
            scene.get("summary"),
            frame.get("semantic_tags"),
            frame.get("semantics"),
            frame.get("events"),
        ]
    ).lower()
    if any(token in haystack for token in ["feedback", "confirmed", "balanced", "mood_neutral", "mood_bright"]):
        return "observe_only"
    if any(token in haystack for token in ["music", "sound", "cocktail", "loud", "lively"]):
        return "music_cocktail_loop"
    if any(token in haystack for token in ["hot", "heat", "cooling", "spray", "ice_water", "human_hot"]):
        return "heat_cooling_loop"
    return "observe_only"


def _tool_observe_scene(args: Dict[str, Any], **_: Any) -> str:
    frame = args.get("frame") or args
    return _ok(
        {
            "frame_id": frame.get("frame_id"),
            "space_id": frame.get("space_id"),
            "summary": (frame.get("scene") or {}).get("summary"),
            "semantic_tags": frame.get("semantic_tags") or [],
            "confidence": frame.get("confidence"),
            "priority": frame.get("priority"),
            "safety": frame.get("safety") or {},
        },
        stage="observe",
    )


def _tool_retrieve_context(args: Dict[str, Any], **_: Any) -> str:
    context = args.get("context") or {}
    return _ok(
        {
            "latest_scene_frame_id": ((context.get("latest_scene") or {}).get("frame_id")),
            "recent_run_count": len(context.get("recent_runs") or []),
            "recent_command_count": len(context.get("recent_commands") or []),
            "recent_robot_ack_count": len(context.get("recent_robot_acks") or []),
            "recent_device_ack_count": len(context.get("recent_device_acks") or []),
            "retrieved_memory": context.get("retrieved_memory") or [],
            "memory_policy": context.get("memory_policy") or {},
        },
        stage="context",
    )


def _tool_select_scene_policy(args: Dict[str, Any], **_: Any) -> str:
    frame = args.get("frame") or {}
    scenario_id = args.get("scenario_id") or _detect_policy(frame)
    allowed = ["heat_cooling_loop", "music_cocktail_loop", "observe_only", "feedback_recovery"]
    if scenario_id not in allowed:
        scenario_id = "observe_only"
    return _ok(
        {
            "scenario_id": scenario_id,
            "mode": "linear_physical_loop",
            "branching": False,
            "allowed_scenarios": allowed[:2],
            "reason": "selected from scene semantic tags, safety state, and recent feedback",
        },
        stage="policy",
    )


def _tool_plan_device_commands(args: Dict[str, Any], **_: Any) -> str:
    scenario_id = args.get("scenario_id") or "observe_only"
    space_id = args.get("space_id") or "unknown"
    task_id = args.get("task_id") or f"{scenario_id}_{int(time.time() * 1000)}"
    if scenario_id == "heat_cooling_loop":
        commands = [
            {
                "target_id": "spray_gateway",
                "target_type": "spray_gateway",
                "command": {
                    "type": "spray.scene",
                    "params": {
                        "task_id": task_id,
                        "op": "mist",
                        "zone": space_id,
                        "duration_sec": 45,
                        "intensity": 0.55,
                        "reason": "human_hot_or_unhappy",
                    },
                },
                "ack_required": True,
                "timeout_ms": 30000,
            },
            {
                "target_id": "unitree_g1",
                "target_type": "robot",
                "command": {
                    "type": "g1.unitree_sdk_sequence",
                    "params": {
                        "task_id": task_id,
                        "scene_id": scenario_id,
                        "speech_cn": "检测到现场热感升高，我将启动清凉联动，并递送冰水。",
                        "safety": {
                            "dry_run": True,
                            "speed_limit_mps": 0.25,
                            "min_human_distance_m": 0.8,
                            "require_debug_mode": True,
                        },
                        "sdk_sequence": [
                            {"seq": 1, "client": "SafetyGuard", "method": "CheckPreconditions", "source_primitive": "safety_check"},
                            {"seq": 2, "client": "SpeechAdapter", "method": "Speak", "source_primitive": "speak"},
                            {"seq": 3, "client": "WaterStationAdapter", "method": "DeliverItem", "source_primitive": "deliver_ice_water"},
                            {"seq": 4, "client": "FeedbackAdapter", "method": "ReportReady", "source_primitive": "report_ready"},
                        ],
                    },
                },
                "ack_required": True,
                "timeout_ms": 60000,
            },
            {
                "target_id": "speaker_gateway",
                "target_type": "speaker_gateway",
                "command": {
                    "type": "speaker.play",
                    "params": {"task_id": task_id, "op": "play", "content_id": "cooling_notice", "volume": 62, "loop": False},
                },
                "ack_required": True,
                "timeout_ms": 15000,
            },
            {
                "target_id": "projection_gateway",
                "target_type": "projection_gateway",
                "command": {
                    "type": "projection.play",
                    "params": {"task_id": task_id, "op": "play", "content_id": "cool_wave_visual", "volume": 0, "loop": False},
                },
                "ack_required": True,
                "timeout_ms": 15000,
            },
        ]
    elif scenario_id == "music_cocktail_loop":
        commands = [
            {
                "target_id": "speaker_gateway",
                "target_type": "speaker_gateway",
                "command": {
                    "type": "speaker.play",
                    "params": {
                        "task_id": task_id,
                        "op": "play",
                        "content_id": "music_cocktail_lively_to_melodic",
                        "volume": 68,
                        "loop": False,
                        "mix_profile": {"source": "field_soundscape", "mood": "lively_to_melodic", "tempo_bpm": 92},
                    },
                },
                "ack_required": True,
                "timeout_ms": 15000,
            },
            {
                "target_id": "projection_gateway",
                "target_type": "projection_gateway",
                "command": {
                    "type": "projection.play",
                    "params": {
                        "task_id": task_id,
                        "op": "play",
                        "content_id": "sound_wave_cocktail_visual",
                        "volume": 0,
                        "loop": False,
                        "visual_profile": "sound_to_waveform_cocktail",
                    },
                },
                "ack_required": True,
                "timeout_ms": 15000,
            },
        ]
    else:
        commands = []
    return _ok(
        {
            "scenario_id": scenario_id,
            "space_id": space_id,
            "task_id": task_id,
            "command_blueprints": commands,
            "known_skills": ZHICHANG_SKILLS,
        },
        stage="tool_plan",
    )


def _tool_emit_device_command(args: Dict[str, Any], **_: Any) -> str:
    command = args.get("command") or args
    return _ok(
        {
            "target_id": command.get("target_id"),
            "target_type": command.get("target_type"),
            "command_type": ((command.get("command") or {}).get("type")),
            "ack_required": command.get("ack_required", True),
            "envelope": "DeviceCommand",
        },
        stage="emit",
    )


def _tool_record_physical_feedback(args: Dict[str, Any], **_: Any) -> str:
    ack = args.get("ack") or args
    return _ok(
        {
            "message_id": ack.get("message_id"),
            "target_id": ack.get("target_id"),
            "status": ack.get("status"),
            "stage": ack.get("stage"),
            "memory_layer": "execution_feedback",
        },
        stage="feedback",
    )


def tool_schemas() -> Dict[str, Dict[str, Any]]:
    return {
        "zhichang_observe_scene": {
            "name": "zhichang_observe_scene",
            "description": "Normalize a physical SceneSemanticFrame into the current Hermes turn.",
            "parameters": {
                "type": "object",
                "properties": {"frame": {"type": "object"}},
                "required": ["frame"],
            },
        },
        "zhichang_retrieve_context": {
            "name": "zhichang_retrieve_context",
            "description": "Read short-term scene state, recent actions, ACK feedback, and retrieved long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {"context": {"type": "object"}},
                "required": ["context"],
            },
        },
        "zhichang_select_scene_policy": {
            "name": "zhichang_select_scene_policy",
            "description": "Select one linear physical-world policy for the current scene without route branching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frame": {"type": "object"},
                    "scenario_id": {"type": "string", "enum": ["heat_cooling_loop", "music_cocktail_loop", "observe_only", "feedback_recovery"]},
                },
                "required": ["frame"],
            },
        },
        "zhichang_plan_device_commands": {
            "name": "zhichang_plan_device_commands",
            "description": "Compile selected policy into standard DeviceCommand blueprints for spray, speaker, projection, and Unitree G1 tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "space_id": {"type": "string"},
                    "task_id": {"type": "string"},
                },
                "required": ["scenario_id", "space_id"],
            },
        },
        "zhichang_emit_device_command": {
            "name": "zhichang_emit_device_command",
            "description": "Expose one DeviceCommand envelope before the hub routes it to HTTP polling or direct push.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "object"}},
                "required": ["command"],
            },
        },
        "zhichang_record_physical_feedback": {
            "name": "zhichang_record_physical_feedback",
            "description": "Record robot/device ACK as execution feedback and long-horizon memory material.",
            "parameters": {
                "type": "object",
                "properties": {"ack": {"type": "object"}, "command": {"type": "object"}},
                "required": ["ack"],
            },
        },
    }


class ZhichangHermesRuntime:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.session_id = f"zhichang_{uuid.uuid4().hex[:10]}"
        self.urban_agents_root = self._resolve_urban_agents_root()
        self.available = False
        self.import_error: Optional[str] = None
        self.registered_tools: List[str] = []
        self.tool_defs: List[Dict[str, Any]] = []
        self.turns: List[Dict[str, Any]] = []
        self.conversation: List[Dict[str, Any]] = []
        self.turn_index: Dict[str, Dict[str, Any]] = {}
        self.llm_configs: List[LLMConfig] = load_llm_configs(project_root)
        file_values = _read_env_values(_candidate_env_files(project_root))
        self.llm_timeout_sec = float(os.getenv("TONGYU_HERMES_LLM_TIMEOUT_SEC") or file_values.get("TONGYU_HERMES_LLM_TIMEOUT_SEC") or "16")
        self.use_llm = os.getenv("TONGYU_HERMES_LLM", "1").lower() not in {"0", "false", "no"}
        self.deepseek_default_thinking = (
            os.getenv("TONGYU_DEEPSEEK_THINKING_DEFAULT")
            or file_values.get("TONGYU_DEEPSEEK_THINKING_DEFAULT")
            or "disabled"
        ).strip().lower()
        self.deepseek_escalation_thinking = (
            os.getenv("TONGYU_DEEPSEEK_THINKING_ESCALATION")
            or file_values.get("TONGYU_DEEPSEEK_THINKING_ESCALATION")
            or "enabled"
        ).strip().lower()
        self.deepseek_reasoning_effort = (
            os.getenv("TONGYU_DEEPSEEK_REASONING_EFFORT")
            or file_values.get("TONGYU_DEEPSEEK_REASONING_EFFORT")
            or "high"
        ).strip().lower()
        self.registry = None
        self.bootstrap()

    def _resolve_urban_agents_root(self) -> Path:
        candidates = []
        env_root = os.getenv("URBAN_AGENTS_ROOT")
        if env_root:
            candidates.append(Path(env_root))
        candidates.extend(
            [
                self.project_root / "third_party" / "UrbanAgents",
                self.project_root.parent / "third_party" / "UrbanAgents",
            ]
        )
        for candidate in candidates:
            if (candidate / "hermes_urban_agent").exists():
                return candidate
        return candidates[0]

    def bootstrap(self) -> None:
        try:
            package_root = self.urban_agents_root / "hermes_urban_agent"
            if not package_root.exists():
                raise FileNotFoundError(f"UrbanAgents package root not found: {package_root}")
            if str(package_root) not in sys.path:
                sys.path.insert(0, str(package_root))
            from urban_hermes.paths import ensure_paths

            ensure_paths()
            from tools.registry import registry
            from toolsets import create_custom_toolset
            from model_tools import get_tool_definitions

            schemas = tool_schemas()
            handlers = {
                "zhichang_observe_scene": _tool_observe_scene,
                "zhichang_retrieve_context": _tool_retrieve_context,
                "zhichang_select_scene_policy": _tool_select_scene_policy,
                "zhichang_plan_device_commands": _tool_plan_device_commands,
                "zhichang_emit_device_command": _tool_emit_device_command,
                "zhichang_record_physical_feedback": _tool_record_physical_feedback,
            }
            for name in ZHICHANG_TOOL_NAMES:
                if not registry.get_entry(name):
                    registry.register(
                        name=name,
                        toolset=TOOLSET,
                        schema=schemas[name],
                        handler=handlers[name],
                        check_fn=lambda: True,
                        description=schemas[name].get("description", ""),
                        emoji="Z",
                    )
            create_custom_toolset(
                name=TOOLSET,
                description="Zhichang Tongyu physical-world semantic input, tool orchestration, and feedback tools.",
                tools=ZHICHANG_TOOL_NAMES,
                includes=[],
            )
            self.registry = registry
            self.registered_tools = list(ZHICHANG_TOOL_NAMES)
            self.tool_defs = get_tool_definitions(enabled_toolsets=[TOOLSET], quiet_mode=True)
            self.available = True
            self.import_error = None
        except Exception as exc:
            self.available = False
            self.import_error = str(exc)

    def status(self) -> Dict[str, Any]:
        return {
            "agent_name": "Zhichang Tongyu Central Agent",
            "session_id": self.session_id,
            "hermes_available": self.available,
            "import_error": self.import_error,
            "urban_agents_root": str(self.urban_agents_root),
            "toolset": TOOLSET,
            "registered_tools": self.registered_tools,
            "tool_count": len(self.tool_defs),
            "llm_enabled": self.use_llm,
            "llm_timeout_sec": self.llm_timeout_sec,
            "runtime_policy": {
                "default_model": (self.llm_configs[0].model if self.llm_configs else None),
                "default_thinking": self.deepseek_default_thinking,
                "escalation_thinking": self.deepseek_escalation_thinking,
                "reasoning_effort": self.deepseek_reasoning_effort,
            },
            "candidate_providers": [config.public_status() for config in self.llm_configs],
            "turn_count": len(self.turns),
            "conversation_count": len(self.conversation),
            "frontend_reference": "internal runtime dashboard/chat trajectory adapter",
        }

    def tools_status(self) -> Dict[str, Any]:
        return {
            "toolset": TOOLSET,
            "registered_tools": self.registered_tools,
            "tool_definitions": self.tool_defs,
            "skills": ZHICHANG_SKILLS,
            "available": self.available,
            "import_error": self.import_error,
        }

    def latest_turns(self, limit: int = 20) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        return {"turns": self.turns[-limit:], "total": len(self.turns), "session_id": self.session_id}

    def latest_conversation(self, limit: int = 80) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 300))
        return {"messages": self.conversation[-limit:], "total": len(self.conversation), "session_id": self.session_id}

    def get_turn(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.turn_index.get(run_id)

    def record_human_message(self, text: str, *, role: str = "operator", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        item = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "role": role,
            "kind": "human_intervention",
            "timestamp": now_cst(),
            "content": text,
            "meta": meta or {},
        }
        self.conversation.append(item)
        self.conversation = self.conversation[-300:]
        return item

    def run_turn(
        self,
        frame: Mapping[str, Any],
        context: Mapping[str, Any],
        planner: Any,
        *,
        run_id: str,
        context_window: Optional[Dict[str, Any]] = None,
        agent_mode: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        agent_mode = dict(agent_mode or {})
        turn = {
            "turn_id": run_id,
            "run_id": run_id,
            "session_id": self.session_id,
            "frame_id": frame.get("frame_id"),
            "space_id": frame.get("space_id"),
            "status": "running",
            "started_at": now_cst(),
            "updated_at": now_cst(),
            "steps": [],
            "llm_attempt": None,
            "tool_registry": self.tools_status(),
            "commands": [],
            "acks": [],
            "agent_mode": agent_mode,
            "world_state": context.get("world_state"),
        }
        self._append_turn(turn)
        self._append_message("physical", "scene_semantic_frame", _summarize_frame(frame), run_id=run_id, frame=frame)

        observe_output = self._dispatch_tool(turn, "zhichang_observe_scene", {"frame": dict(frame)}, chain="reasoning")
        context_output = self._dispatch_tool(turn, "zhichang_retrieve_context", {"context": dict(context)}, chain="reasoning")
        policy_output = self._dispatch_tool(turn, "zhichang_select_scene_policy", {"frame": dict(frame)}, chain="reasoning")

        planner_decision: Optional[Dict[str, Any]] = None
        if agent_mode.get("model_loop") == "skip":
            llm_attempt = {
                "status": "skipped_fast_layer",
                "provider": "fast-rule-layer",
                "model": None,
                "duration_ms": 0,
                "tool_outputs": [],
                "error": agent_mode.get("reason"),
            }
            self._add_step(
                turn,
                chain="reasoning",
                stage="runtime.fast_layer",
                title="Fast layer handled frame",
                summary=agent_mode.get("reason") or "Model loop skipped for this frame.",
                status="completed",
                input={"agent_mode": agent_mode},
                output={"model_loop": "skip"},
            )
        else:
            llm_attempt = self._attempt_hermes_llm(turn, frame, context, policy_output)
        turn["llm_attempt"] = llm_attempt
        if llm_attempt.get("status") == "ok":
            planner_decision = self._decision_from_llm(llm_attempt.get("final_response") or "", llm_attempt.get("tool_outputs") or [])

        if not planner_decision:
            planner_decision = self._fallback_decision(planner, frame, context)
            if llm_attempt.get("status") not in {"disabled", "not_available"}:
                planner_decision["planner_warning"] = (
                    f"Hermes model path did not produce a valid command decision "
                    f"({llm_attempt.get('status')}: {llm_attempt.get('error', '')}); fallback skill used."
                ).strip()

        plan_args = {
            "scenario_id": planner_decision.get("scenario_id"),
            "space_id": frame.get("space_id"),
            "task_id": self._task_id_from_decision(planner_decision),
        }
        plan_tool_output = self._dispatch_tool(turn, "zhichang_plan_device_commands", plan_args, chain="execution")
        self._add_step(
            turn,
            chain="reasoning",
            stage="public_trace",
            title="Public agent trajectory extracted",
            summary="Scenario, intent, context, and command plan were normalized for the central hub.",
            status="completed",
            input={"observe": observe_output, "context": context_output, "policy": policy_output},
            output={
                "scenario_id": planner_decision.get("scenario_id"),
                "intent": planner_decision.get("intent"),
                "command_count": len(planner_decision.get("commands") or []),
                "context_window": context_window or {},
                "agent_mode": agent_mode,
            },
        )
        planner_decision.setdefault("public_reasoning_trace", [])
        planner_decision["public_reasoning_trace"] = self._merge_public_trace(
            planner_decision.get("public_reasoning_trace") or [],
            turn,
        )
        provider = planner_decision.get("provider") or {}
        planner_decision["provider"] = {
            "provider": "zhichang-agent-runtime",
            "model": (llm_attempt.get("model") or provider.get("model") or "fallback-skills"),
            "toolset": TOOLSET,
            "runtime_available": self.available,
            "llm_status": llm_attempt.get("status"),
            "thinking": agent_mode.get("thinking") or {},
            "agent_mode": agent_mode.get("mode"),
            "fallback_provider": provider,
            "attempts": provider.get("attempts") or [],
        }
        planner_decision["runtime_turn_id"] = run_id
        planner_decision["tool_plan"] = plan_tool_output

        turn["planner_decision"] = planner_decision
        turn["scenario_id"] = planner_decision.get("scenario_id")
        turn["intent"] = planner_decision.get("intent")
        turn["status"] = "planned" if planner_decision.get("commands") else "observed"
        turn["updated_at"] = now_cst()
        self._append_message(
            "assistant",
            "agent_decision",
            f"{planner_decision.get('scenario_id')} / {len(planner_decision.get('commands') or [])} commands",
            run_id=run_id,
            decision={
                "scenario_id": planner_decision.get("scenario_id"),
                "intent": planner_decision.get("intent"),
                "warning": planner_decision.get("planner_warning"),
            },
        )
        return {
            "planner_decision": planner_decision,
            "hermes_turn": turn,
            "public_trace": self.legacy_trace(turn),
        }

    def record_dispatch(self, run_id: str, commands: List[Dict[str, Any]], dispatch_results: List[Dict[str, Any]]) -> None:
        turn = self.turn_index.get(run_id)
        if not turn:
            return
        turn["commands"] = commands
        for command in commands:
            self._dispatch_tool(turn, "zhichang_emit_device_command", {"command": command}, chain="execution")
        self._add_step(
            turn,
            chain="execution",
            stage="dispatch",
            title="DeviceCommand routed",
            summary=f"{len(commands)} commands routed through polling/direct HTTP transports.",
            status="completed" if commands else "skipped",
            input={"commands": _compact(commands, 1600)},
            output={"dispatch_results": dispatch_results},
        )
        turn["updated_at"] = now_cst()

    def record_ack(
        self,
        ack: Dict[str, Any],
        command: Optional[Dict[str, Any]],
        memory_record: Optional[Dict[str, Any]],
        *,
        ack_kind: str,
    ) -> None:
        run_id = (command or {}).get("agent_run_id")
        turn = self.turn_index.get(run_id) if run_id else None
        if turn:
            turn.setdefault("acks", []).append(ack)
            if memory_record:
                turn.setdefault("memory_updates", []).append(memory_record)
            self._dispatch_tool(turn, "zhichang_record_physical_feedback", {"ack": ack, "command": command or {}}, chain="execution")
            self._add_step(
                turn,
                chain="feedback",
                stage=ack_kind,
                title="Physical feedback entered memory",
                summary=f"{ack.get('target_id')} reported {ack.get('status')}.",
                status=str(ack.get("status") or "received"),
                input={"ack": ack, "matched_command": _compact(command or {}, 1000)},
                output={"memory_record": memory_record},
            )
            turn["updated_at"] = now_cst()
            if ack.get("status") in {"failed", "blocked", "timeout", "error"}:
                turn["status"] = "needs_review"
        self._append_message(
            "physical",
            ack_kind,
            f"{ack.get('target_id')} / {ack.get('status')} / {ack.get('stage') or ''}",
            run_id=run_id,
            ack=ack,
            memory_record=memory_record,
        )

    def legacy_trace(self, turn: Mapping[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "stage": step.get("stage"),
                "label": step.get("title"),
                "output": {
                    "summary": step.get("summary"),
                    "chain": step.get("chain"),
                    "status": step.get("status"),
                    "tool_name": step.get("tool_name"),
                    "output": step.get("output"),
                },
            }
            for step in turn.get("steps", [])
        ]

    def _append_turn(self, turn: Dict[str, Any]) -> None:
        self.turns.append(turn)
        self.turn_index[turn["run_id"]] = turn
        self.turns = self.turns[-100:]

    def _append_message(self, role: str, kind: str, content: str, *, run_id: Optional[str] = None, **payload: Any) -> None:
        item = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "role": role,
            "kind": kind,
            "timestamp": now_cst(),
            "run_id": run_id,
            "content": content,
            "payload": payload,
        }
        self.conversation.append(item)
        self.conversation = self.conversation[-300:]

    def _add_step(
        self,
        turn: Dict[str, Any],
        *,
        chain: str,
        stage: str,
        title: str,
        summary: str,
        status: str = "completed",
        tool_name: Optional[str] = None,
        input: Any = None,
        output: Any = None,
    ) -> Dict[str, Any]:
        step = {
            "step_id": f"{turn['run_id']}_s{len(turn['steps']) + 1:02d}",
            "turn_id": turn["run_id"],
            "session_id": self.session_id,
            "seq": len(turn["steps"]) + 1,
            "chain": chain,
            "stage": stage,
            "title": title,
            "summary": summary,
            "status": status,
            "tool_name": tool_name,
            "timestamp": now_cst(),
            "input": input,
            "output": output,
        }
        turn["steps"].append(step)
        turn["updated_at"] = now_cst()
        return step

    def _dispatch_tool(self, turn: Dict[str, Any], tool_name: str, args: Dict[str, Any], *, chain: str) -> Dict[str, Any]:
        self._add_step(
            turn,
            chain=chain,
            stage="tool.start",
            title=f"{tool_name} called",
            summary=self._tool_summary(tool_name, args),
            status="running",
            tool_name=tool_name,
            input=_compact(args, 1200),
            output=None,
        )
        if not self.registry:
            result = {"success": False, "error": self.import_error or "Hermes registry unavailable"}
        else:
            raw = self.registry.dispatch(tool_name, args)
            result = _extract_json_object(raw) or {"raw": raw}
        self._add_step(
            turn,
            chain=chain,
            stage="tool.complete",
            title=f"{tool_name} completed",
            summary=self._tool_result_summary(tool_name, result),
            status="completed" if result.get("success", True) else "failed",
            tool_name=tool_name,
            input={"tool_name": tool_name},
            output=result,
        )
        return result

    def _is_deepseek_config(self, config: LLMConfig) -> bool:
        text = f"{config.provider} {config.model} {config.base_url}".lower()
        return "deepseek" in text

    def _runtime_options_for(self, config: LLMConfig, agent_mode: Mapping[str, Any]) -> Dict[str, Any]:
        model_loop = str(agent_mode.get("model_loop") or "fast_llm")
        thinking_type = str((agent_mode.get("thinking") or {}).get("type") or self.deepseek_default_thinking or "disabled").lower()
        if model_loop == "deep_llm":
            thinking_type = self.deepseek_escalation_thinking if self.deepseek_escalation_thinking in {"enabled", "disabled"} else "enabled"
        elif thinking_type not in {"enabled", "disabled"}:
            thinking_type = "disabled"

        request_overrides: Dict[str, Any] = {}
        public_request_overrides: Dict[str, Any] = {}
        reasoning_config: Optional[Dict[str, Any]] = None

        if self._is_deepseek_config(config):
            thinking_payload: Dict[str, Any] = {"type": thinking_type}
            if thinking_type == "enabled" and self.deepseek_reasoning_effort:
                thinking_payload["reasoning_effort"] = self.deepseek_reasoning_effort
            request_overrides = {"extra_body": {"thinking": thinking_payload}}
            public_request_overrides = request_overrides
        else:
            reasoning_config = {"enabled": thinking_type == "enabled"}
            if thinking_type == "enabled":
                reasoning_config["effort"] = self.deepseek_reasoning_effort or "medium"

        if model_loop == "deep_llm":
            max_iterations = 6
            max_tokens = 1400
            skip_memory = False
        else:
            max_iterations = 4
            max_tokens = 900
            skip_memory = False

        return {
            "model_loop": model_loop,
            "thinking_type": thinking_type,
            "max_iterations": max_iterations,
            "max_tokens": max_tokens,
            "skip_memory": skip_memory,
            "reasoning_config": reasoning_config,
            "request_overrides": request_overrides,
            "public_request_overrides": public_request_overrides,
        }

    def _attempt_hermes_llm(
        self,
        turn: Dict[str, Any],
        frame: Mapping[str, Any],
        context: Mapping[str, Any],
        policy_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.available:
            return {"status": "not_available", "error": self.import_error}
        if not self.use_llm:
            return {"status": "disabled", "error": "TONGYU_HERMES_LLM disabled"}
        config = next((item for item in self.llm_configs if item.configured), None)
        if not config:
            return {"status": "not_configured", "error": "No configured LLM provider"}
        agent_mode = turn.get("agent_mode") or {}
        runtime_options = self._runtime_options_for(config, agent_mode)

        tool_outputs: List[Dict[str, Any]] = []
        accept_callbacks = {"active": True}

        def tool_start(call_id: str, name: str, args: Dict[str, Any]) -> None:
            if not accept_callbacks["active"]:
                return
            self._add_step(
                turn,
                chain="execution",
                stage="runtime.tool.start",
                title=f"Model requested {name}",
                summary="The model selected a registered zhichang tool.",
                status="running",
                tool_name=name,
                input={"call_id": call_id, "args": _compact(args, 1200)},
            )

        def tool_complete(call_id: str, name: str, args: Dict[str, Any], result: Any) -> None:
            if not accept_callbacks["active"]:
                return
            parsed = _extract_json_object(str(result)) or {"raw": str(result)}
            tool_outputs.append({"call_id": call_id, "name": name, "args": args, "result": parsed})
            self._add_step(
                turn,
                chain="execution",
                stage="runtime.tool.complete",
                title=f"Model completed {name}",
                summary=self._tool_result_summary(name, parsed),
                status="completed",
                tool_name=name,
                input={"call_id": call_id},
                output=parsed,
            )

        def step_callback(iteration: int, previous_tools: Any) -> None:
            if not accept_callbacks["active"]:
                return
            self._add_step(
                turn,
                chain="reasoning",
                stage="runtime.step",
                title=f"Agent iteration {iteration}",
                summary="Model/tool loop advanced.",
                status="completed",
                input={"previous_tools": _compact(previous_tools, 800)},
                output=None,
            )

        def run_agent() -> str:
            from run_agent import AIAgent

            agent = AIAgent(
                provider=config.provider,
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
                max_iterations=runtime_options["max_iterations"],
                tool_delay=0,
                enabled_toolsets=[TOOLSET],
                quiet_mode=True,
                save_trajectories=False,
                skip_context_files=True,
                skip_memory=runtime_options["skip_memory"],
                session_id=f"{self.session_id}_{turn['run_id']}",
                ephemeral_system_prompt=self._system_prompt(agent_mode),
                tool_start_callback=tool_start,
                tool_complete_callback=tool_complete,
                step_callback=step_callback,
                max_tokens=runtime_options["max_tokens"],
                reasoning_config=runtime_options["reasoning_config"],
                request_overrides=runtime_options["request_overrides"],
            )
            return agent.chat(self._turn_prompt(frame, context, policy_output, agent_mode))

        started = time.time()
        self._add_step(
            turn,
            chain="reasoning",
            stage="runtime.llm.start",
            title="Agent model loop started",
            summary=f"{config.provider} / {config.model}",
            status="running",
            input={
                "provider": config.public_status(),
                "timeout_sec": self.llm_timeout_sec,
                "agent_mode": agent_mode,
                "runtime_options": {
                    key: value
                    for key, value in runtime_options.items()
                    if key not in {"request_overrides"}
                },
                "request_overrides": runtime_options.get("public_request_overrides"),
            },
        )
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_agent)
        try:
            final_response = future.result(timeout=self.llm_timeout_sec)
        except concurrent.futures.TimeoutError:
            accept_callbacks["active"] = False
            executor.shutdown(wait=False, cancel_futures=True)
            self._add_step(
                turn,
                chain="reasoning",
                stage="runtime.llm.timeout",
                title="Agent model loop timed out",
                summary="Fallback skills will keep the physical loop running.",
                status="timeout",
                output={"timeout_sec": self.llm_timeout_sec},
            )
            return {
                "status": "timeout",
                "provider": config.provider,
                "model": config.model,
                "duration_ms": int((time.time() - started) * 1000),
                "tool_outputs": tool_outputs,
                "error": f"Timed out after {self.llm_timeout_sec}s",
            }
        except Exception as exc:
            accept_callbacks["active"] = False
            executor.shutdown(wait=False, cancel_futures=True)
            self._add_step(
                turn,
                chain="reasoning",
                stage="runtime.llm.error",
                title="Agent model loop failed",
                summary=str(exc)[:240],
                status="failed",
                output={"error": str(exc)[:1000]},
            )
            return {
                "status": "failed",
                "provider": config.provider,
                "model": config.model,
                "duration_ms": int((time.time() - started) * 1000),
                "tool_outputs": tool_outputs,
                "error": str(exc)[:1000],
            }
        else:
            accept_callbacks["active"] = False
            executor.shutdown(wait=False, cancel_futures=True)
        self._add_step(
            turn,
            chain="reasoning",
            stage="runtime.llm.complete",
            title="Agent model loop completed",
            summary="Final response received and will be normalized.",
            status="completed",
            output={"final_response_preview": str(final_response)[:1000]},
        )
        return {
            "status": "ok",
            "provider": config.provider,
            "model": config.model,
            "duration_ms": int((time.time() - started) * 1000),
            "tool_outputs": tool_outputs,
            "final_response": final_response,
        }

    def _decision_from_llm(self, final_response: str, tool_outputs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        parsed = _extract_json_object(final_response)
        if parsed and isinstance(parsed.get("commands"), list):
            parsed["commands"] = _normalize_device_commands(parsed.get("commands"))
            parsed.setdefault("source", "hermes-llm")
            return parsed
        for output in reversed(tool_outputs):
            if output.get("name") != "zhichang_plan_device_commands":
                continue
            result = output.get("result") or {}
            body = result.get("result") or {}
            commands = body.get("command_blueprints")
            if isinstance(commands, list):
                scenario_id = body.get("scenario_id") or "unknown"
                return {
                    "source": "hermes-tool-plan",
                    "scenario_id": scenario_id,
                    "situation": scenario_id,
                    "intent": "physical_world_response",
                    "confidence": 0.72,
                    "priority": 0.6,
                    "public_reasoning_trace": [],
                    "commands": _normalize_device_commands(commands),
                }
        return None

    def _fallback_decision(self, planner: Any, frame: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        if hasattr(planner, "_fallback_plan"):
            decision = planner._fallback_plan(frame, context)
        else:
            decision = planner.plan(frame, context)
        decision = dict(decision)
        decision.setdefault("source", "hermes-fallback-skills")
        decision["source"] = f"hermes-adapter:{decision.get('source')}"
        return decision

    def _merge_public_trace(self, existing: List[Dict[str, Any]], turn: Mapping[str, Any]) -> List[Dict[str, Any]]:
        extracted = [
            {
                "stage": step.get("stage"),
                "label": step.get("title"),
                "output": {
                    "chain": step.get("chain"),
                    "summary": step.get("summary"),
                    "status": step.get("status"),
                    "tool_name": step.get("tool_name"),
                },
            }
            for step in turn.get("steps", [])
            if step.get("stage") in {
                "tool.start",
                "tool.complete",
                "runtime.llm.start",
                "runtime.llm.complete",
                "runtime.llm.error",
                "runtime.llm.timeout",
                "runtime.fast_layer",
                "public_trace",
            }
        ]
        return extracted + list(existing)

    def _system_prompt(self, agent_mode: Optional[Mapping[str, Any]] = None) -> str:
        agent_mode = agent_mode or {}
        return (
            "You are the Zhichang Tongyu Central Agent. "
            "You receive continuous physical-world semantic frames and must use only the registered zhichang tools. "
            "Do not branch route choices. Select one linear policy, plan standard DeviceCommand envelopes, and wait for ACK feedback. "
            "Active demo scenes are only heat_cooling_loop and music_cocktail_loop; otherwise observe_only. "
            f"Current runtime mode is {agent_mode.get('mode') or 'fast_planner'}; thinking is {((agent_mode.get('thinking') or {}).get('type') or 'disabled')}. "
            "Return a compact JSON object with keys: scenario_id, situation, intent, confidence, priority, public_reasoning_trace, commands. "
            "Every command must be canonical: {target_id,target_type,command:{type,params},routing?,ack_required?,timeout_ms?}; never put type/params only at the top level. "
            "Do not reveal private chain-of-thought; public_reasoning_trace must contain concise audit steps only."
        )

    def _turn_prompt(
        self,
        frame: Mapping[str, Any],
        context: Mapping[str, Any],
        policy_output: Dict[str, Any],
        agent_mode: Optional[Mapping[str, Any]] = None,
    ) -> str:
        agent_mode = agent_mode or {}
        return _json(
            {
                "task": "Process one physical-world semantic frame and produce standard tool commands if needed.",
                "scene_semantic_frame": frame,
                "world_state": context.get("world_state"),
                "context": context,
                "agent_mode": agent_mode,
                "policy_hint": policy_output,
                "known_skills": ZHICHANG_SKILLS,
                "required_five_step_loop": [
                    "observe physical semantic input",
                    "retrieve short and long memory",
                    "select one scene policy",
                    "plan and emit standard DeviceCommand tools",
                    "record ACK feedback into memory when it arrives",
                ],
            }
        )

    def _task_id_from_decision(self, decision: Mapping[str, Any]) -> Optional[str]:
        for command in decision.get("commands") or []:
            task_id = (((command.get("command") or {}).get("params") or {}).get("task_id"))
            if task_id:
                return str(task_id)
        return None

    def _tool_summary(self, tool_name: str, args: Mapping[str, Any]) -> str:
        if tool_name == "zhichang_observe_scene":
            return _summarize_frame(args.get("frame") or {})
        if tool_name == "zhichang_retrieve_context":
            context = args.get("context") or {}
            return f"{len(context.get('recent_runs') or [])} runs / {len(context.get('recent_commands') or [])} commands / {len(context.get('retrieved_memory') or [])} memories"
        if tool_name == "zhichang_select_scene_policy":
            return "Select one non-branching physical scene policy."
        if tool_name == "zhichang_plan_device_commands":
            return f"{args.get('scenario_id')} -> DeviceCommand blueprints"
        if tool_name == "zhichang_emit_device_command":
            command = args.get("command") or {}
            return f"{command.get('target_id')} / {((command.get('command') or {}).get('type'))}"
        if tool_name == "zhichang_record_physical_feedback":
            ack = args.get("ack") or {}
            return f"{ack.get('target_id')} / {ack.get('status')}"
        return tool_name

    def _tool_result_summary(self, tool_name: str, result: Mapping[str, Any]) -> str:
        body = result.get("result") if isinstance(result.get("result"), Mapping) else result
        if tool_name == "zhichang_plan_device_commands":
            return f"{len((body or {}).get('command_blueprints') or [])} command blueprints"
        if tool_name == "zhichang_select_scene_policy":
            return str((body or {}).get("scenario_id") or "policy selected")
        if tool_name == "zhichang_record_physical_feedback":
            return str((body or {}).get("status") or "feedback recorded")
        return "tool result normalized"


def semantic_text_to_frame(text: str) -> Dict[str, Any]:
    raw = text or ""
    lower = raw.lower()
    frame_id = f"ssf_intervention_{int(time.time() * 1000)}"
    if any(token in lower for token in ["music", "sound", "noise", "cocktail", "loud", "音乐", "声音", "鸡尾酒"]):
        return {
            "message_type": "scene_semantic_frame",
            "frame_id": frame_id,
            "timestamp": now_cst(),
            "source_id": "operator_semantic_intervention",
            "space_id": "sound_cocktail_zone_01",
            "scene": {
                "situation_id": "music_cocktail_loop",
                "summary": raw,
                "intent_hint": "music_cocktail",
                "tags": ["sound_cocktail", "loud", "lively", "music"],
            },
            "semantics": {"operator_semantic": {"label": raw, "tags": ["music"]}},
            "semantic_tags": ["sound_cocktail", "loud", "lively", "music"],
            "confidence": 0.76,
            "priority": 0.66,
        }
    if any(token in lower for token in ["feedback", "ack", "balanced", "confirmed", "恢复", "反馈", "正常"]):
        return {
            "message_type": "scene_semantic_frame",
            "frame_id": frame_id,
            "timestamp": now_cst(),
            "source_id": "operator_semantic_intervention",
            "space_id": "cooling_zone_01",
            "scene": {
                "situation_id": "operator_feedback",
                "summary": raw,
                "intent_hint": "observe_and_confirm",
                "tags": ["cooling_effect_confirmed", "mood_neutral"],
            },
            "semantics": {"operator_semantic": {"label": raw, "tags": ["feedback"]}},
            "semantic_tags": ["cooling_effect_confirmed", "mood_neutral"],
            "confidence": 0.72,
            "priority": 0.4,
        }
    return {
        "message_type": "scene_semantic_frame",
        "frame_id": frame_id,
        "timestamp": now_cst(),
        "source_id": "operator_semantic_intervention",
        "space_id": "cooling_zone_01",
        "scene": {
            "situation_id": "heat_cooling_loop",
            "summary": raw,
            "intent_hint": "cooling_request",
            "tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
        },
        "semantics": {"operator_semantic": {"label": raw, "tags": ["hot"]}},
        "semantic_tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
        "confidence": 0.76,
        "priority": 0.7,
    }
