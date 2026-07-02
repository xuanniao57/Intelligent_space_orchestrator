"""Generic LLM-agent planner for the Tongyu Central Hub.

The planner keeps the Agent framework generic: it receives a fused
SceneSemanticFrame plus short-term context, asks an OpenAI-compatible LLM for a
tool plan when credentials are available, and falls back to deterministic
scenario skills so lab demos can keep running offline.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen


CST = timezone(timedelta(hours=8))

ALLOWED_COMMAND_TYPES = {
    "g1.unitree_sdk_sequence",
    "spray.scene",
    "spray.stop",
    "speaker.play",
    "speaker.stop",
    "speaker.speak",
    "projection.play",
    "projection.stop",
    "projection.show_scene",
    "lan.raw_command",
    "lan.wol",
}

ALLOWED_TARGET_TYPES = {"robot", "spray_gateway", "speaker_gateway", "projection_gateway", "lan_control_gateway"}

SCENARIO_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "heat_cooling_loop",
        "name_cn": "热感知 · 清凉联动",
        "intent": "cool_down_people",
        "trigger_tags": ["hot", "overheating", "human_hot", "mood_unhappy", "cooling_request"],
        "tools": ["spray.scene", "g1.unitree_sdk_sequence", "speaker.play", "projection.play", "lan.raw_command"],
    },
    {
        "id": "music_cocktail_loop",
        "name_cn": "声音鸡尾酒 · 音乐调和",
        "intent": "music_cocktail",
        "trigger_tags": ["sound_cocktail", "music", "loud", "lively", "active_soundscape"],
        "tools": ["speaker.play", "projection.play", "lan.raw_command", "lan.wol"],
    },
]


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: Optional[str]
    api_key_env: Optional[str]
    base_url_env: Optional[str]
    model_env: Optional[str]
    timeout_sec: float = 12.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def public_status(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "api_key_env": self.api_key_env,
            "base_url_env": self.base_url_env,
            "model_env": self.model_env,
        }


def now_cst_ms() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}+08:00"


def _candidate_env_files(project_root: Path) -> Iterable[Path]:
    candidates = [
        project_root / ".env",
        project_root / "central_hub" / ".env",
        project_root.parent / ".env",
        Path.cwd() / ".env",
    ]
    extra_env = os.getenv("TONGYU_ENV_FILE")
    if extra_env:
        candidates.insert(0, Path(extra_env))
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            yield resolved


def _read_env_values(paths: Iterable[Path]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                values.setdefault(key.strip(), value)
    return values


def _first_configured(names: Iterable[str], file_values: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value, name
    for name in names:
        value = file_values.get(name)
        if value:
            return value, name
    return None, None


def _first_configured_file_first(names: Iterable[str], file_values: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    for name in names:
        value = file_values.get(name)
        if value:
            return value, name
    for name in names:
        value = os.getenv(name)
        if value:
            return value, name
    return None, None


def _normalize_provider_name(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None
    normalized = provider.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "kimi-code": "kimi-coding",
        "kimi-coder": "kimi-coding",
        "moonshot-coding": "kimi-coding",
        "deepseek-v4": "deepseek",
        "deepseek-v4-pro": "deepseek",
        "deepseek-v4-flash": "deepseek",
    }
    return aliases.get(normalized, normalized)


def _apply_llm_preference(configs: List[LLMConfig], file_values: Mapping[str, str]) -> List[LLMConfig]:
    preferred_provider, provider_env = _first_configured_file_first(("TONGYU_HERMES_PROVIDER", "LLM_PROVIDER"), file_values)
    preferred_model, model_env = _first_configured_file_first(("TONGYU_HERMES_MODEL", "LLM_MODEL"), file_values)
    provider = _normalize_provider_name(preferred_provider)
    if not provider and not preferred_model:
        return configs

    base = next((item for item in configs if item.provider == provider), None) if provider else None
    if base is None and preferred_model:
        model_lower = preferred_model.lower()
        if "deepseek" in model_lower:
            base = next((item for item in configs if item.provider == "deepseek"), None)
        elif "kimi" in model_lower or "moonshot" in model_lower:
            base = next((item for item in configs if item.provider in {"kimi-coding", "kimi"}), None)
    if base is None:
        return configs

    preferred = LLMConfig(
        provider=base.provider,
        model=(preferred_model or base.model),
        base_url=base.base_url,
        api_key=base.api_key,
        api_key_env=base.api_key_env,
        base_url_env=base.base_url_env,
        model_env=model_env or base.model_env,
        timeout_sec=base.timeout_sec,
    )
    deduped = [
        item
        for item in configs
        if not (item.provider == preferred.provider and item.model == preferred.model)
    ]
    return [preferred] + deduped


def load_llm_configs(project_root: Path) -> List[LLMConfig]:
    file_values = _read_env_values(_candidate_env_files(project_root))

    providers = [
        (
            "kimi-coding",
            ("KIMI_CODE_API_KEY",),
            ("KIMI_CODE_API_BASE", "KIMI_CODE_BASE_URL"),
            ("KIMI_CODE_MODEL",),
        ),
        (
            "kimi",
            ("KIMI_API_KEY",),
            ("KIMI_BASE_URL", "KIMI_API_BASE"),
            ("KIMI_MODEL",),
        ),
        (
            "deepseek",
            ("DEEPSEEK_API_KEY", "Deepseek_API_KEY"),
            ("DEEPSEEK_BASE_URL", "Deepseek_API_BASE"),
            ("DEEPSEEK_MODEL", "Deepseek_MODEL"),
        ),
    ]
    configs: List[LLMConfig] = []
    for provider, key_names, base_names, model_names in providers:
        api_key, api_key_env = _first_configured(key_names, file_values)
        base_url, base_url_env = _first_configured(base_names, file_values)
        model, model_env = _first_configured(model_names, file_values)
        if api_key and base_url and model:
            configs.append(
                LLMConfig(
                    provider=provider,
                    model=model,
                    base_url=base_url.rstrip("/"),
                    api_key=api_key,
                    api_key_env=api_key_env,
                    base_url_env=base_url_env,
                    model_env=model_env,
                )
            )

    if configs:
        return _apply_llm_preference(configs, file_values)

    return [
        LLMConfig(
            provider="deterministic-fallback",
            model="fallback-rules",
            base_url="",
            api_key=None,
            api_key_env=None,
            base_url_env=None,
            model_env=None,
        )
    ]


def load_llm_config(project_root: Path) -> LLMConfig:
    return load_llm_configs(project_root)[0]


class AgentPlanner:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.file_values = _read_env_values(_candidate_env_files(self.project_root))
        self.configs = load_llm_configs(project_root)
        self.config = self.configs[0]
        self.disabled = os.getenv("TONGYU_AGENT_DISABLE_LLM", "").lower() in {"1", "true", "yes"}

    def public_status(self) -> Dict[str, Any]:
        status = self.config.public_status()
        status["candidate_providers"] = [config.public_status() for config in self.configs]
        status["disabled_by_env"] = self.disabled
        status["scenario_count"] = len(SCENARIO_DEFINITIONS)
        status["scenarios"] = SCENARIO_DEFINITIONS
        return status

    def plan(self, frame: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        attempts: List[Dict[str, Any]] = []
        normalized: Dict[str, Any] = {}
        preferred_config = self.configs[0]

        if not self.disabled:
            for config in self.configs:
                if not config.configured:
                    continue
                self.config = config
                try:
                    decision = self._plan_with_llm(frame, context)
                    normalized = self._normalize_decision(decision, source="llm")
                    attempts.append({**config.public_status(), "status": "ok", "command_count": len(normalized["commands"])})
                    if normalized["commands"]:
                        normalized["provider"] = {**config.public_status(), "attempts": attempts}
                        return normalized
                    normalized["planner_warning"] = f"{config.provider} returned no executable commands; trying fallback planner."
                except Exception as exc:
                    attempts.append({**config.public_status(), "status": "failed", "error": str(exc)[:500]})
                    normalized = {"planner_warning": f"{config.provider} planner failed: {exc}"}
        else:
            attempts.append({"provider": "disabled-by-env", "status": "skipped"})

        self.config = preferred_config

        fallback = self._fallback_plan(frame, context)
        if attempts:
            failed = [f"{item.get('provider')}={item.get('status')}" for item in attempts]
            fallback["planner_warning"] = (
                f"LLM provider chain did not produce executable commands ({'; '.join(failed)}); "
                "deterministic fallback used."
            )
            if normalized.get("planner_warning"):
                fallback["planner_warning"] += f" Last warning: {normalized['planner_warning']}"
        fallback["provider"] = {
            "provider": "deterministic-fallback",
            "model": "fallback-rules",
            "preferred_provider": preferred_config.public_status(),
            "attempts": attempts,
        }
        return fallback

    def _plan_with_llm(self, frame: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "scene_semantic_frame": frame,
                            "agent_context": context,
                            "allowed_scenarios": SCENARIO_DEFINITIONS,
                            "allowed_command_types": sorted(ALLOWED_COMMAND_TYPES),
                            "allowed_target_types": sorted(ALLOWED_TARGET_TYPES),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.15,
            "max_tokens": 2200,
        }
        if "deepseek" in f"{self.config.provider} {self.config.model} {self.config.base_url}".lower():
            thinking_type = (
                os.getenv("TONGYU_DEEPSEEK_THINKING_DEFAULT")
                or self.file_values.get("TONGYU_DEEPSEEK_THINKING_DEFAULT")
                or os.getenv("DEEPSEEK_EXEC_THINKING")
                or self.file_values.get("DEEPSEEK_EXEC_THINKING")
                or "disabled"
            ).strip().lower()
            if thinking_type not in {"enabled", "disabled"}:
                thinking_type = "disabled"
            payload["thinking"] = {"type": thinking_type}
            if thinking_type == "enabled":
                payload["thinking"]["reasoning_effort"] = (
                    os.getenv("TONGYU_DEEPSEEK_REASONING_EFFORT")
                    or self.file_values.get("TONGYU_DEEPSEEK_REASONING_EFFORT")
                    or os.getenv("DEEPSEEK_REASONING_EFFORT")
                    or self.file_values.get("DEEPSEEK_REASONING_EFFORT")
                    or "high"
                ).strip().lower()
        endpoint = self._chat_completion_endpoint()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = UrlRequest(
            endpoint,
            data=raw,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        try:
            with urlopen(req, timeout=self.config.timeout_sec) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {exc.code} from {self.config.provider}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"network error from {self.config.provider}: {exc.reason}") from exc

        content = self._extract_message_content(data)
        return self._extract_json_object(content)

    def _chat_completion_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _system_prompt(self) -> str:
        return (
            "你是 Tongyu 智场控制中枢里的通用 Agent planner。"
            "你不直接控制底层电机，只能输出高层 DeviceCommand 工具调用。"
            "当前展示只允许两个场景：热感知清凉联动、声音鸡尾酒音乐调和。"
            "请只返回一个 JSON 对象，不要 Markdown。"
            "JSON schema: {scenario_id, situation, intent, confidence, priority, "
            "public_reasoning_trace: [{stage,label,output}], commands:[{target_id,target_type,command:{type,params},routing?,ack_required?,timeout_ms?}]}. "
            "public_reasoning_trace 是面向展示的简短可解释轨迹，不要输出私密思维链。"
            "机器人命令优先使用 g1.unitree_sdk_sequence，且必须先 SafetyGuard.CheckPreconditions，再执行 speak/运动/工具，最后 FeedbackAdapter.ReportReady。"
            "安全约束默认 dry_run=true, speed_limit_mps<=0.25, min_human_distance_m>=0.8。"
        )

    def _extract_message_content(self, response: Mapping[str, Any]) -> str:
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _extract_json_object(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object")
        return parsed

    def _normalize_decision(self, decision: Mapping[str, Any], source: str) -> Dict[str, Any]:
        commands = []
        for command in decision.get("commands") or []:
            normalized = self._normalize_command(command)
            if normalized:
                commands.append(normalized)
        return {
            "source": source,
            "scenario_id": str(decision.get("scenario_id") or "unknown"),
            "situation": str(decision.get("situation") or ""),
            "intent": str(decision.get("intent") or ""),
            "confidence": _float(decision.get("confidence"), 0.65),
            "priority": _float(decision.get("priority"), 0.5),
            "public_reasoning_trace": _normalize_trace(decision.get("public_reasoning_trace")),
            "commands": commands,
        }

    def _normalize_command(self, command: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        target_type = str(command.get("target_type") or "")
        target_id = str(command.get("target_id") or "")
        body = command.get("command") or {}
        if not isinstance(body, Mapping):
            return None
        command_type = str(body.get("type") or "")
        if target_type not in ALLOWED_TARGET_TYPES or command_type not in ALLOWED_COMMAND_TYPES:
            return None
        if not target_id:
            return None
        return {
            "target_id": target_id,
            "target_type": target_type,
            "command": {"type": command_type, "params": dict(body.get("params") or {})},
            "routing": dict(command.get("routing") or {}),
            "ack_required": bool(command.get("ack_required", True)),
            "timeout_ms": int(_float(command.get("timeout_ms"), 60000)),
        }

    def _fallback_plan(self, frame: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        scenario_id = detect_scenario(frame)
        latest_robot_ack = _latest_problem_ack(context)
        if latest_robot_ack:
            return self._fallback_recovery_plan(frame, latest_robot_ack)
        if scenario_id == "music_cocktail_loop":
            return self._music_cocktail_plan(frame)
        if scenario_id == "heat_cooling_loop":
            return self._heat_cooling_plan(frame)
        return {
            "source": "deterministic-fallback",
            "scenario_id": "observe_only",
            "situation": "no_supported_demo_scenario_detected",
            "intent": "observe_and_wait",
            "confidence": 0.45,
            "priority": _float(frame.get("priority"), 0.4),
            "public_reasoning_trace": [
                {"stage": "observe", "label": "场景语义已入库", "output": {"space_id": frame.get("space_id")}},
                {"stage": "gate", "label": "当前 demo 只开放两个场景", "output": {"allowed": [s["id"] for s in SCENARIO_DEFINITIONS]}},
            ],
            "commands": [],
        }

    def _heat_cooling_plan(self, frame: Mapping[str, Any]) -> Dict[str, Any]:
        zone = str(frame.get("space_id") or "cooling_zone_01")
        task_id = f"heat_cooling_{int(time.time() * 1000)}"
        speech = "检测到现场热感升高，我将启动清凉联动，并递送冰水。"
        commands = [
            {
                "target_id": "spray_gateway",
                "target_type": "spray_gateway",
                "command": {
                    "type": "spray.scene",
                    "params": {
                        "task_id": task_id,
                        "op": "mist",
                        "zone": zone,
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
                        "scene_id": "heat_cooling_loop",
                        "request_text": "热感知清凉联动：喷雾并递冰水",
                        "speech_cn": speech,
                        "safety": _default_robot_safety(),
                        "sdk_sequence": [
                            _sdk_call(1, "bridge", "SafetyGuard", "CheckPreconditions", "safety_check", {
                                "dry_run": True,
                                "require_debug_mode": True,
                                "min_human_distance_m": 0.8,
                            }, "先确认急停、调试模式和人距。"),
                            _sdk_call(2, "onboard_io", "SpeechAdapter", "Speak", "speak", {"text_cn": speech}, "播报中枢意图。"),
                            _sdk_call(3, "unitree_high_level", "SportClient", "MoveByWaypoint", "navigate_to_water_station", {
                                "target": "hydration_station_01",
                                "speed_limit_mps": 0.25,
                                "dry_run_velocity_hint": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0},
                            }, "联调阶段保持零速度或安全小幅运动。"),
                            _sdk_call(4, "station_tool", "WaterStationAdapter", "DeliverItem", "deliver_ice_water", {
                                "item": "iced_bottled_water",
                                "handoff_zone": "cooling_handoff_01",
                                "dry_run_only": True,
                            }, "真机阶段映射到取水/递水或人工协作。"),
                            _sdk_call(5, "bridge", "FeedbackAdapter", "ReportReady", "report_ready", {
                                "text_cn": "清凉联动已完成，等待中枢复检情绪和热感反馈。"
                            }, "回传可观察结果。"),
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
                    "params": {
                        "task_id": task_id,
                        "op": "play",
                        "content_id": "cooling_notice",
                        "volume": 62,
                        "loop": False,
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
                        "content_id": "cool_wave_visual",
                        "volume": 0,
                        "loop": False,
                    },
                },
                "ack_required": True,
                "timeout_ms": 15000,
            },
        ]
        return {
            "source": "deterministic-fallback",
            "scenario_id": "heat_cooling_loop",
            "situation": "human_hot_or_unhappy",
            "intent": "cool_down_people",
            "confidence": 0.82,
            "priority": max(0.7, _float(frame.get("priority"), 0.7)),
            "public_reasoning_trace": [
                {"stage": "L1", "label": "多源采样", "output": {"space_id": zone, "tags": frame.get("semantic_tags", [])}},
                {"stage": "L2", "label": "语义转换", "output": {"situation": "人热 / 不开心"}},
                {"stage": "L3", "label": "工具规划", "output": {"tools": ["喷雾", "G1递冰水", "扬声器", "投影"]}},
                {"stage": "L4", "label": "等待反馈", "output": {"expected_feedback": "热感下降、情绪改善、机器人ACK"}},
            ],
            "commands": commands,
        }

    def _music_cocktail_plan(self, frame: Mapping[str, Any]) -> Dict[str, Any]:
        zone = str(frame.get("space_id") or "sound_cocktail_zone_01")
        task_id = f"music_cocktail_{int(time.time() * 1000)}"
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
                        "mix_profile": {
                            "source": "field_soundscape",
                            "mood": "lively_to_melodic",
                            "tempo_bpm": 92,
                        },
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
        return {
            "source": "deterministic-fallback",
            "scenario_id": "music_cocktail_loop",
            "situation": "lively_noisy_soundscape",
            "intent": "music_cocktail",
            "confidence": 0.8,
            "priority": max(0.6, _float(frame.get("priority"), 0.6)),
            "public_reasoning_trace": [
                {"stage": "L1", "label": "多维声音采样", "output": {"space_id": zone, "tags": frame.get("semantic_tags", [])}},
                {"stage": "L2", "label": "声音语义转换", "output": {"situation": "嘈杂 / 活跃"}},
                {"stage": "L3", "label": "音乐鸡尾酒工具链", "output": {"tools": ["混音", "扬声器", "投影可视化"]}},
                {"stage": "L4", "label": "等待反馈", "output": {"expected_feedback": "情绪共鸣、噪声协调、设备ACK"}},
            ],
            "commands": commands,
        }

    def _fallback_recovery_plan(self, frame: Mapping[str, Any], ack: Mapping[str, Any]) -> Dict[str, Any]:
        task_id = f"recovery_{int(time.time() * 1000)}"
        speech = "收到机器人反馈，当前动作受阻，我将暂停移动并等待重新规划。"
        return {
            "source": "deterministic-fallback",
            "scenario_id": "feedback_recovery",
            "situation": f"last_robot_ack_{ack.get('status')}",
            "intent": "pause_and_replan",
            "confidence": 0.78,
            "priority": max(0.75, _float(frame.get("priority"), 0.7)),
            "public_reasoning_trace": [
                {"stage": "feedback", "label": "机器人反馈进入上下文", "output": {"status": ack.get("status"), "stage": ack.get("stage"), "error": ack.get("error")}},
                {"stage": "safety", "label": "失败/阻塞优先安全处理", "output": {"action": "pause_and_replan"}},
            ],
            "commands": [
                {
                    "target_id": "unitree_g1",
                    "target_type": "robot",
                    "command": {
                        "type": "g1.unitree_sdk_sequence",
                        "params": {
                            "task_id": task_id,
                            "scene_id": "feedback_recovery",
                            "speech_cn": speech,
                            "safety": _default_robot_safety(),
                            "sdk_sequence": [
                                _sdk_call(1, "bridge", "SafetyGuard", "CheckPreconditions", "safety_check", {
                                    "dry_run": True,
                                    "min_human_distance_m": 0.8,
                                }, "先确认安全再处理失败反馈。"),
                                _sdk_call(2, "onboard_io", "SpeechAdapter", "Speak", "speak", {"text_cn": speech}, "明确进入暂停和重新规划。"),
                                _sdk_call(3, "bridge", "FeedbackAdapter", "ReportReady", "report_ready", {
                                    "text_cn": "已暂停移动，等待新的路径或人工确认。"
                                }, "让中枢知道恢复动作已完成。"),
                            ],
                        },
                    },
                    "ack_required": True,
                    "timeout_ms": 60000,
                }
            ],
        }


def detect_scenario(frame: Mapping[str, Any]) -> str:
    scene = frame.get("scene") or {}
    situation_id = str(scene.get("situation_id") or "").lower()
    intent_hint = str(scene.get("intent_hint") or "").lower()
    semantic_tags = {str(item).lower() for item in frame.get("semantic_tags") or []}
    if (
        intent_hint in {"observe_and_confirm", "observe_only"}
        or situation_id.endswith("_feedback")
        or semantic_tags & {"cooling_effect_confirmed", "soundscape_balanced", "mood_neutral", "mood_bright"}
    ):
        return "observe_only"
    haystack = " ".join(
        str(item)
        for item in [
            frame.get("semantic_tags"),
            scene.get("situation_id"),
            scene.get("summary"),
            scene.get("intent_hint"),
            frame.get("semantics"),
            frame.get("events"),
            frame.get("affordances"),
        ]
    ).lower()
    values = _collect_numeric_values(frame)
    temperature = values.get("temperature_c") or values.get("temperature") or values.get("temp_c")
    noise = values.get("noise_db") or values.get("sound_db")

    if any(token in haystack for token in ["music", "音乐", "声音鸡尾酒", "sound_cocktail", "lively", "嘈杂", "活跃"]):
        return "music_cocktail_loop"
    if noise is not None and noise >= 68 and "hot" not in haystack and "热" not in haystack:
        return "music_cocktail_loop"
    if any(token in haystack for token in ["hot", "overheat", "cooling", "冰水", "喷雾", "清凉", "人热", "不开心", "热"]):
        return "heat_cooling_loop"
    if temperature is not None and temperature >= 30:
        return "heat_cooling_loop"
    return "observe_only"


def _collect_numeric_values(value: Any, prefix: str = "") -> Dict[str, float]:
    values: Dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            values.update(_collect_numeric_values(item, str(key)))
    elif isinstance(value, list):
        for item in value:
            values.update(_collect_numeric_values(item, prefix))
    else:
        try:
            values[prefix] = float(value)
        except (TypeError, ValueError):
            pass
    return values


def _latest_problem_ack(context: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for ack in reversed(context.get("recent_robot_acks") or []):
        if ack.get("status") in {"failed", "blocked", "timeout"}:
            return ack
    return None


def _default_robot_safety() -> Dict[str, Any]:
    return {
        "dry_run": True,
        "speed_limit_mps": 0.25,
        "min_human_distance_m": 0.8,
        "require_debug_mode": True,
        "allow_hot_liquid_contact": False,
    }


def _sdk_call(
    seq: int,
    layer: str,
    client: str,
    method: str,
    source_primitive: str,
    args: Dict[str, Any],
    note: str,
) -> Dict[str, Any]:
    return {
        "seq": seq,
        "primitive": "unitree_sdk_call",
        "source_primitive": source_primitive,
        "layer": layer,
        "client": client,
        "method": method,
        "args": args,
        "note": note,
    }


def _normalize_trace(trace: Any) -> List[Dict[str, Any]]:
    if not isinstance(trace, list):
        return []
    normalized = []
    for item in trace[:8]:
        if isinstance(item, Mapping):
            normalized.append({
                "stage": str(item.get("stage") or ""),
                "label": str(item.get("label") or ""),
                "output": item.get("output") if isinstance(item.get("output"), Mapping) else {"value": item.get("output")},
            })
    return normalized


def _float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
