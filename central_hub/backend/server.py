"""
=============================================================================
同语中枢 (Tongyu Central Hub) — 后端服务器
=============================================================================
实现完整的同语协议栈:
  Layer 1: HTTP + WebSocket 传输层
  Layer 2: 消息信封 (SensorFrame, AgentIntention, DeviceCommand, NegotiationProposal)
  Layer 3: ECA 规则引擎 + 多智能体任务分配
  Layer 4: 语义标签体系 + 空间 Persona

用法:
  python server.py [--port 8798] [--host 0.0.0.0]
=============================================================================
"""

import json
import time
import uuid
import logging
import re
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Mapping
from dataclasses import dataclass, field, asdict
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
from flask_sock import Sock

from abc_square_client import ABCSquareAPIError, ABCSquareClient, load_abc_square_config
from agent_planner import AgentPlanner, SCENARIO_DEFINITIONS
from zhichang_hermes_runtime import ZhichangHermesRuntime, semantic_text_to_frame

# ============================================================
# 配置
# ============================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("tongyu-hub")

CST = timezone(timedelta(hours=8))

app = Flask(__name__, static_folder=None)
CORS(app)
sock = Sock(app)


@app.after_request
def disable_agent_console_cache(response):
    if request.path.startswith("/agent-console") or request.path.startswith("/console"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# WebSocket 客户端列表
ws_clients: List[Any] = []

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = Path(__file__).parent.parent / "data"
PLATFORM_REGISTRY_PATH = DATA_DIR / "platform_registry.json"
GENERATED_MEDIA_DIR = DATA_DIR / "generated_media"
AGENT_MEMORY_PATH = DATA_DIR / "zhichang_tongyu_agent_memory.jsonl"
AGENT_IO_REGISTRY_DIR = DATA_DIR / "agent_io_registry"


def load_json_file(path: Path, fallback: Dict) -> Dict:
    """Load a UTF-8 JSON file without making the server fail if docs are absent."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load %s: %s", path, exc)
        return fallback


def load_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
    except Exception as exc:
        logger.warning("Could not load %s: %s", path, exc)
    return records


PLATFORM_REGISTRY = load_json_file(
    PLATFORM_REGISTRY_PATH,
    {"schema_version": "platform-registry-fallback", "platforms": [], "watchlist": [], "excluded": []},
)

PROJECT_PROGRESS = {
    "positioning": "Human-Agent-Site Collaborative Platform",
    "current_can_do": [
        "Generic Agent planner boundary: SceneSemanticFrame -> context -> public reasoning trace -> DeviceCommand tools",
        "Kimi Coding / Kimi / DeepSeek OpenAI-compatible planner with deterministic offline fallback",
        "Two active demo scenes only: heat cooling loop and music cocktail loop",
        "Unitree G1 push-mode dry-run via g1.unitree_sdk_sequence, plus robot ACK feedback into context",
        "Spray, speaker, projection, and robot commands recorded through the same DeviceCommand envelope",
        "Three-page HTML promo deck served as the current default showcase"
    ],
    "next_attack": [
        "Run LAN test with another laptop as fake robot/device client",
        "Replace demo media content_id with actual local audio/video asset maps on each gateway",
        "Let robot teammate map sdk_sequence adapters to real Unitree SDK2 / ROS2 bridge calls",
        "Add long-horizon memory and scene-effect evaluation after real feedback packets arrive",
        "Measure latency from semantic ingest -> tool plan -> device ACK on campus network"
    ],
    "demo_entrypoints": [
        {"name": "central dashboard", "url": "http://localhost:8798/"},
        {"name": "current 3-page promo deck", "url": "http://localhost:8798/deck"},
        {"name": "heat cooling demo", "url": "POST /api/demo/scenario/heat_cooling_loop"},
        {"name": "music cocktail demo", "url": "POST /api/demo/scenario/music_cocktail_loop"}
    ]
}

DEMO_STORYLINES = [
    {
        "id": "heat_cooling_loop",
        "label": "场景1：热感知 · 清凉联动",
        "feasibility": "current_mvp",
        "source_file": "agent_planner.py",
        "channel": "热环境/人不开心 -> Agent -> 喷雾 + G1递冰水 + 声画提示 -> ACK反馈",
        "sample_frame": {
            "message_type": "scene_semantic_frame",
            "space_id": "cooling_zone_01",
            "source_id": "demo_semantic_fusion",
            "scene": {
                "situation_id": "heat_cooling_loop",
                "summary": "现场温度升高，人群热感增强，部分反馈不开心，需要清凉联动。",
                "intent_hint": "cooling_request",
                "tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"]
            },
            "semantics": {
                "environment": {"label": "热", "level": "warning", "tags": ["hot"]},
                "crowd": {"label": "轻度聚集", "level": "normal", "tags": ["moderate"]},
                "emotion": {"label": "不开心", "level": "watch", "tags": ["mood_unhappy"]}
            },
            "semantic_tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
            "confidence": 0.88,
            "priority": 0.82
        },
        "expected_rules": ["R001_heat_cooling_loop"]
    },
    {
        "id": "music_cocktail_loop",
        "label": "场景2：声音鸡尾酒 · 音乐调和",
        "feasibility": "current_mvp",
        "source_file": "agent_planner.py",
        "channel": "多维声音 -> Agent -> 混音/音乐播放 + 投影声波可视化 -> 反馈评估",
        "sample_frame": {
            "message_type": "scene_semantic_frame",
            "space_id": "sound_cocktail_zone_01",
            "source_id": "demo_sound_fusion",
            "scene": {
                "situation_id": "music_cocktail_loop",
                "summary": "现场多维声音活跃且略显嘈杂，中枢将其调和成音乐鸡尾酒。",
                "intent_hint": "music_cocktail",
                "tags": ["sound_cocktail", "lively", "music"]
            },
            "semantics": {
                "soundscape": {"label": "活跃嘈杂", "level": "watch", "tags": ["loud", "lively"]},
                "crowd": {"label": "活跃", "level": "normal", "tags": ["moderate"]},
                "emotion": {"label": "可调和", "level": "normal", "tags": ["mood_mixed"]}
            },
            "semantic_tags": ["sound_cocktail", "loud", "lively", "music"],
            "confidence": 0.84,
            "priority": 0.68
        },
        "expected_rules": ["R002_music_cocktail_loop"]
    }
]


# ============================================================
# 同语协议数据模型 (Layer 2)
# ============================================================

class Priority(Enum):
    LOW = 0.3
    NORMAL = 0.5
    HIGH = 0.7
    URGENT = 0.9
    CRITICAL = 1.0

class Verb(Enum):
    REQUEST = "request"
    INVITE = "invite"
    ALERT = "alert"
    NEGOTIATE = "negotiate"
    RESPOND = "respond"


@dataclass
class SensorFrame:
    message_type: str = "sensor_frame"
    space_id: str = ""
    timestamp: str = ""
    sensor_values: Dict[str, float] = field(default_factory=dict)
    semantic_tags: List[str] = field(default_factory=list)
    source_device: str = "chongzhi_field"
    priority: float = 0.5

    def generate_tags(self) -> List[str]:
        tags = []
        sv = self.sensor_values
        if sv.get("temperature_c", 25) > 30: tags.append("hot")
        elif sv.get("temperature_c", 25) > 22: tags.append("warm")
        elif sv.get("temperature_c", 25) < 15: tags.append("cold")
        if sv.get("humidity_pct", 50) < 25: tags.append("dry")
        elif sv.get("humidity_pct", 50) > 65: tags.append("wet")
        if sv.get("people_density", 0.1) > 0.6: tags.append("crowded")
        elif sv.get("people_density", 0.1) > 0.3: tags.append("moderate")
        elif sv.get("people_density", 0.1) < 0.1: tags.append("empty")
        if sv.get("plant_water_stress", 0) > 0.6: tags.append("plant_stressed")
        if sv.get("noise_db", 40) > 70: tags.append("loud")
        elif sv.get("noise_db", 40) > 50: tags.append("active")
        self.semantic_tags = tags
        return tags


@dataclass
class SceneSemanticFrame:
    message_type: str = "scene_semantic_frame"
    frame_id: str = ""
    timestamp: str = ""
    source_id: str = "data_analysis_fusion"
    space_id: str = ""
    time_window: Dict[str, Any] = field(default_factory=dict)
    scene: Dict[str, Any] = field(default_factory=dict)
    semantics: Dict[str, Any] = field(default_factory=dict)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    affordances: List[Dict[str, Any]] = field(default_factory=list)
    safety: Dict[str, Any] = field(default_factory=dict)
    raw_refs: List[Dict[str, Any]] = field(default_factory=list)
    semantic_tags: List[str] = field(default_factory=list)
    confidence: float = 0.5
    priority: float = 0.5


@dataclass
class AgentIntention:
    message_type: str = "agent_intention"
    space_id: str = ""
    source_agent: str = "spatial_llm_hub"
    timestamp: str = ""
    situation: str = ""
    emotion: str = "neutral"
    intent: str = ""
    confidence: float = 0.5
    priority: float = 0.5
    target_agents: List[str] = field(default_factory=list)
    suggested_actions: List[Dict] = field(default_factory=list)


@dataclass
class DeviceCommand:
    message_type: str = "device_command"
    message_id: str = ""
    timestamp: str = ""
    source_id: str = "control_hub"
    target_id: str = ""
    target_type: str = ""
    verb: str = "command"
    command: Dict[str, Any] = field(default_factory=dict)
    routing: Dict[str, str] = field(default_factory=dict)
    ack_required: bool = True
    timeout_ms: int = 5000


@dataclass
class NegotiationProposal:
    message_type: str = "negotiation_proposal"
    message_id: str = ""
    timestamp: str = ""
    source_agent: str = ""
    target_agents: List[str] = field(default_factory=list)
    verb: str = "negotiate"
    proposal: Dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"
    timeout_ms: int = 1000


# ============================================================
# ECA 规则引擎 (Layer 3) — 从 eca_engine_demo.py 移植
# ============================================================

class ECARuleEngine:
    def __init__(self):
        self.rules = []
        self.event_log: List[Dict] = []
        self._init_rules()

    def _init_rules(self):
        self.rules = [
            {
                "rule_id": "R001_heat_cooling_loop",
                "description": "热感知 → 喷雾 + G1递冰水 + 声画清凉提示",
                "trigger": {"event": "sensor_frame", "conditions": [
                    {"field": "sensor_values.temperature_c", "op": "gte", "value": 30.0}
                ]},
                "actions": [
                    {"target": "spray_gateway", "type": "spray.scene",
                     "params": {"op": "mist", "zone": "cooling_zone_01", "duration_sec": 45,
                                "intensity": 0.55, "reason": "human_hot"}, "delay_ms": 0},
                    {"target": "unitree_g1", "type": "g1.unitree_sdk_sequence",
                     "params": {"scene_id": "heat_cooling_loop", "speech_cn": "检测到热感升高，我将启动喷雾并递送冰水。",
                                "safety": {"dry_run": True, "speed_limit_mps": 0.25,
                                           "min_human_distance_m": 0.8, "require_debug_mode": True},
                                "sdk_sequence": [
                                    {"seq": 1, "primitive": "unitree_sdk_call", "source_primitive": "safety_check",
                                     "layer": "bridge", "client": "SafetyGuard", "method": "CheckPreconditions",
                                     "args": {"dry_run": True, "min_human_distance_m": 0.8},
                                     "note": "确认调试模式、人距和急停。"},
                                    {"seq": 2, "primitive": "unitree_sdk_call", "source_primitive": "speak",
                                     "layer": "onboard_io", "client": "SpeechAdapter", "method": "Speak",
                                     "args": {"text_cn": "检测到热感升高，我将启动喷雾并递送冰水。"},
                                     "note": "播报动作意图。"},
                                    {"seq": 3, "primitive": "unitree_sdk_call", "source_primitive": "deliver_ice_water",
                                     "layer": "station_tool", "client": "WaterStationAdapter", "method": "DeliverItem",
                                     "args": {"item": "iced_bottled_water", "dry_run_only": True},
                                     "note": "真机阶段映射到取水/递水或人工协作。"},
                                    {"seq": 4, "primitive": "unitree_sdk_call", "source_primitive": "report_ready",
                                     "layer": "bridge", "client": "FeedbackAdapter", "method": "ReportReady",
                                     "args": {"text_cn": "清凉联动已完成，等待中枢复检反馈。"},
                                     "note": "回传可观察结果。"}
                                ]}, "delay_ms": 100},
                    {"target": "speaker_gateway", "type": "speaker.play",
                     "params": {"op": "play", "content_id": "cooling_notice", "volume": 62,
                                "loop": False}, "delay_ms": 150},
                    {"target": "projection_gateway", "type": "projection.play",
                     "params": {"op": "play", "content_id": "cool_wave_visual", "volume": 0,
                                "loop": False}, "delay_ms": 150}
                ],
                "cooldown_ms": 60000, "last_fired": 0
            },
            {
                "rule_id": "R002_music_cocktail_loop",
                "description": "多维声音活跃/嘈杂 → 音乐鸡尾酒 + 投影可视化",
                "trigger": {"event": "sensor_frame", "conditions": [
                    {"field": "sensor_values.noise_db", "op": "gte", "value": 68.0}
                ]},
                "actions": [
                    {"target": "speaker_gateway", "type": "speaker.play",
                     "params": {"op": "play", "content_id": "music_cocktail_lively_to_melodic",
                                "volume": 68, "loop": False,
                                "mix_profile": {"source": "field_soundscape", "tempo_bpm": 92}},
                     "delay_ms": 0},
                    {"target": "projection_gateway", "type": "projection.play",
                     "params": {"op": "play", "content_id": "sound_wave_cocktail_visual",
                                "volume": 0, "loop": False,
                                "visual_profile": "sound_to_waveform_cocktail"},
                     "delay_ms": 100}
                ],
                "cooldown_ms": 60000, "last_fired": 0
            }
        ]

    def evaluate(self, event: Dict) -> List[Dict]:
        now_ms = int(time.time() * 1000)
        matched = []
        for rule in self.rules:
            if rule["trigger"]["event"] != event.get("event_type", event.get("message_type", "")):
                continue
            if now_ms - rule["last_fired"] < rule["cooldown_ms"]:
                continue
            conditions_met = True
            for cond in rule["trigger"]["conditions"]:
                field_val = self._get_field(event, cond["field"])
                op, target = cond["op"], cond["value"]
                if op == "gte" and not (field_val >= target): conditions_met = False
                elif op == "gt" and not (field_val > target): conditions_met = False
                elif op == "lte" and not (field_val <= target): conditions_met = False
                elif op == "lt" and not (field_val < target): conditions_met = False
                elif op == "eq" and not (field_val == target): conditions_met = False
            if conditions_met:
                rule["last_fired"] = now_ms
                matched.append(rule)
                self.event_log.append({
                    "time_ms": now_ms, "rule_id": rule["rule_id"],
                    "description": rule["description"], "event": event
                })
        return matched

    def _get_field(self, event: Dict, field_path: str):
        parts = field_path.split(".")
        val = event
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p, 0)
            else:
                return 0
        return val if val is not None else 0

    def execute_actions(self, rule: Dict, event: Dict) -> List[DeviceCommand]:
        commands = []
        now_ts = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}+08:00"
        for i, action in enumerate(rule["actions"]):
            target = action["target"]
            target_type_map = {
                "unitree_g1": "robot",
                "spray_gateway": "spray_gateway",
                "speaker_gateway": "speaker_gateway",
                "projection_gateway": "projection_gateway",
                "san": "mcu_agent"
            }
            cmd = DeviceCommand(
                message_id=f"cmd_{int(time.time()*1000)}_{i}",
                timestamp=now_ts,
                target_id=target,
                target_type=target_type_map.get(target, "unknown"),
                command={"type": action["type"], "params": action["params"]},
                routing={"mqtt_topic": f"talking_spaces/{target}/command"}
            )
            commands.append(cmd)
        return commands


# ============================================================
# 空间 Persona 管理
# ============================================================

SPACE_PERSONAS = {
    "garden_01": {"name": "花园角", "persona": "calm gardener", "emotion": "peaceful",
                  "concerns": ["植物健康", "湿度", "安静氛围"]},
    "social_circle_01": {"name": "社交圈", "persona": "warm host", "emotion": "welcoming",
                         "concerns": ["参与者体验", "讨论热度", "人流引导"]},
    "parking_01": {"name": "停车区", "persona": "order keeper", "emotion": "vigilant",
                   "concerns": ["停放秩序", "流线边界", "安全"]},
    "showcase_01": {"name": "展示桌", "persona": "patient narrator", "emotion": "engaging",
                    "concerns": ["访客理解", "系统演示", "互动"]},
}


# ============================================================
# 全局状态
# ============================================================

engine = ECARuleEngine()
telemetry_store: Dict[str, Dict] = {}  # space_id -> latest telemetry
semantic_scene_store: Dict[str, Dict] = {}  # space_id -> latest fused scene semantics
command_history: List[Dict] = []
robot_ack_history: List[Dict] = []
device_ack_history: List[Dict] = []
agent_run_store: Dict[str, Dict] = {}
event_stream: List[Dict] = []
simulation_mode: bool = True
connected_devices: Dict[str, Dict] = {}
abc_square_snapshot_store: Dict[str, Dict] = {}
agent_context_store: Dict[str, Dict] = {}
world_state_store: Dict[str, Dict[str, Any]] = {}
event_block_store: List[Dict[str, Any]] = []
EVENT_BLOCK_LAYER_ENABLED = False
agent_memory_store: List[Dict] = load_jsonl_file(AGENT_MEMORY_PATH)
agent_planner = AgentPlanner(ROOT_DIR)
zhichang_hermes = ZhichangHermesRuntime(ROOT_DIR)


def rule_summaries() -> List[Dict]:
    return [{
        "rule_id": r["rule_id"],
        "description": r["description"],
        "cooldown_ms": r["cooldown_ms"],
        "last_fired": r["last_fired"],
        "actions_count": len(r["actions"])
    } for r in engine.rules]


def build_llm_hub_trace(frame: SensorFrame, matched_rules: List[Dict], intentions: List[Dict], commands: List[Dict]) -> List[Dict]:
    """Expose the LLM hub as a traceable pipeline instead of a black box."""
    rules = [rule["rule_id"] for rule in matched_rules]
    return [
        {
            "stage": "perceive",
            "label": "SensorFrame -> semantic tags",
            "output": {"space_id": frame.space_id, "semantic_tags": frame.semantic_tags}
        },
        {
            "stage": "interpret",
            "label": "semantic tags -> situation",
            "output": {"matched_rules": rules, "confidence": 0.85 if rules else 0.5}
        },
        {
            "stage": "decide",
            "label": "situation -> AgentIntention",
            "output": {"intentions": len(intentions), "targets": sorted({t for item in intentions for t in item.get("target_agents", [])})}
        },
        {
            "stage": "actuate",
            "label": "approved intention -> DeviceCommand",
            "output": {"command_count": len(commands), "targets": [cmd.get("target_id") for cmd in commands]}
        }
    ]


def process_sensor_payload(space_id: str, sensor_values: Dict[str, float], source_device: str = "chongzhi_field", priority: float = 0.5) -> Dict:
    """Shared path for API ingest, quick demos, and bridge inputs."""
    frame = SensorFrame(
        space_id=space_id,
        timestamp=datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}+08:00",
        sensor_values=sensor_values,
        source_device=source_device,
        priority=priority
    )
    frame.generate_tags()
    telemetry_store[frame.space_id] = asdict(frame)

    event = {
        "event_type": "sensor_frame",
        "space_id": frame.space_id,
        "timestamp": frame.timestamp,
        "sensor_values": frame.sensor_values,
        "semantic_tags": frame.semantic_tags,
        "priority": frame.priority
    }

    matched_rules = engine.evaluate(event)
    commands = []
    for rule in matched_rules:
        commands.extend([asdict(c) for c in engine.execute_actions(rule, event)])

    if commands:
        command_history.extend(commands)

    intentions = []
    if matched_rules:
        persona = SPACE_PERSONAS.get(frame.space_id, {})
        for rule in matched_rules:
            intention = AgentIntention(
                space_id=frame.space_id,
                timestamp=frame.timestamp,
                situation=rule["rule_id"],
                emotion=persona.get("emotion", "neutral"),
                intent=rule["description"],
                confidence=0.85,
                priority=0.7,
                target_agents=["speaker_gateway", "unitree_g1", "laser_gateway"],
                suggested_actions=rule["actions"]
            )
            intentions.append(asdict(intention))

    result = {
        "frame": asdict(frame),
        "matched_rules": [r["rule_id"] for r in matched_rules],
        "intentions": intentions,
        "commands": commands,
        "command_count": len(commands)
    }
    result["llm_hub_trace"] = build_llm_hub_trace(frame, matched_rules, intentions, commands)
    event_stream.append({"type": "telemetry_ingest", "result": result, "time_ms": int(time.time() * 1000)})
    broadcast("telemetry_update", result)
    return result


def process_discrete_event(event: Dict) -> Dict:
    """Run non-sensor events such as person_detected through the same ECA engine."""
    event = {"timestamp": datetime.now(CST).isoformat(), **event}
    matched_rules = engine.evaluate(event)
    commands = []
    for rule in matched_rules:
        commands.extend([asdict(c) for c in engine.execute_actions(rule, event)])
    if commands:
        command_history.extend(commands)
    result = {
        "event": event,
        "matched_rules": [r["rule_id"] for r in matched_rules],
        "commands": commands,
        "command_count": len(commands),
        "llm_hub_trace": [
            {"stage": "event", "label": "discrete event -> ECA", "output": event},
            {"stage": "actuate", "label": "matched rule -> DeviceCommand", "output": {"command_count": len(commands)}}
        ]
    }
    event_stream.append({"type": "discrete_event_ingest", "result": result, "time_ms": int(time.time() * 1000)})
    broadcast("telemetry_update", result)
    return result


def now_cst_ms() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}+08:00"


def extract_scene_semantic_tags(data: Dict[str, Any]) -> List[str]:
    tags = set()
    scene = data.get("scene") or {}
    semantics = data.get("semantics") or {}
    safety = data.get("safety") or {}

    for tag in data.get("semantic_tags") or scene.get("tags") or []:
        if tag:
            tags.add(str(tag))
    if scene.get("situation_id"):
        tags.add(str(scene["situation_id"]))
    if scene.get("intent_hint"):
        tags.add(str(scene["intent_hint"]))
    for key, value in semantics.items():
        if isinstance(value, dict):
            if value.get("label"):
                tags.add(f"{key}:{value['label']}")
            if value.get("level"):
                tags.add(f"{key}:{value['level']}")
            for tag in value.get("tags") or []:
                tags.add(str(tag))
        elif isinstance(value, str):
            tags.add(f"{key}:{value}")
    if safety.get("level"):
        tags.add(f"safety:{safety['level']}")
    return sorted(tags)


def memory_tokens(value: Any) -> set:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return {item.lower() for item in re.findall(r"[a-zA-Z0-9_\-]+|[\u4e00-\u9fff]+", text)}


def frame_memory_tokens(frame: Optional[Dict[str, Any]]) -> set:
    if not frame:
        return set()
    scene = frame.get("scene") or {}
    tokens = {
        str(frame.get("space_id") or "").lower(),
        str(scene.get("situation_id") or "").lower(),
        str(scene.get("intent_hint") or "").lower(),
    }
    tokens.update(str(item).lower() for item in frame.get("semantic_tags") or [])
    tokens.update(memory_tokens(frame.get("semantics") or {}))
    return {item for item in tokens if item}


def compact_memory_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: record.get(key)
        for key in [
            "memory_id",
            "timestamp",
            "layer",
            "memory_chain",
            "space_id",
            "scenario_id",
            "summary",
            "triggers",
            "evidence",
        ]
        if record.get(key) not in (None, "", [], {})
    }


def retrieve_agent_memory(frame: Optional[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    query = frame_memory_tokens(frame)
    if not query:
        return []
    scored = []
    for record in agent_memory_store:
        record_tokens = memory_tokens(record.get("triggers") or [])
        record_tokens.update(memory_tokens(record.get("summary") or ""))
        record_tokens.update(memory_tokens(record.get("scenario_id") or ""))
        record_tokens.update(memory_tokens(record.get("space_id") or ""))
        overlap = query & record_tokens
        if overlap:
            scored.append((len(overlap), str(record.get("timestamp") or ""), record))
    scored.sort(key=lambda item: (-item[0], item[1]), reverse=False)
    return [compact_memory_record(item[2]) for item in scored[:limit]]


def append_agent_memory(record: Dict[str, Any]) -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    enriched = {
        "schema_version": "zhichang_tongyu_agent_memory.v1",
        "agent_name": "智场同语中枢Agent",
        "memory_id": record.get("memory_id") or f"mem_{int(time.time()*1000)}_{len(agent_memory_store)+1}",
        "timestamp": record.get("timestamp") or datetime.now(CST).isoformat(timespec="seconds"),
        **record,
    }
    agent_memory_store.append(enriched)
    with AGENT_MEMORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched, ensure_ascii=False, default=str) + "\n")
    return enriched


def record_ack_memory(ack: Dict[str, Any], command: Optional[Dict[str, Any]], *, ack_kind: str) -> Optional[Dict[str, Any]]:
    if not command:
        return None
    status = str(ack.get("status") or "").lower()
    if status not in {"ok", "failed", "blocked", "timeout"}:
        return None
    command_body = command.get("command") or {}
    command_type = command_body.get("type")
    scenario_id = command.get("scenario_id")
    space_id = command.get("space_id")
    target_id = command.get("target_id")
    triggers = [
        item
        for item in [
            scenario_id,
            space_id,
            target_id,
            command_type,
            status,
            ack.get("stage"),
            ack_kind,
        ]
        if item
    ]
    summary = (
        f"{scenario_id or 'unknown_scenario'} -> {target_id} / {command_type} "
        f"finished with {status}"
    )
    return append_agent_memory({
        "layer": "execution_feedback",
        "memory_chain": "execution_chain",
        "space_id": space_id,
        "scenario_id": scenario_id,
        "summary": summary,
        "triggers": triggers,
        "evidence": {
            "ack_kind": ack_kind,
            "message_id": ack.get("message_id"),
            "task_id": ack.get("task_id"),
            "target_id": target_id,
            "command_type": command_type,
            "status": status,
            "stage": ack.get("stage"),
            "executed_steps": ack.get("executed_steps", []),
            "simulated": ack.get("simulated", False),
            "error": ack.get("error"),
        },
    })


def _bounded_float(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(0.0, min(1.0, number))


def _scene_text_blob(frame: Mapping[str, Any]) -> str:
    scene = frame.get("scene") or {}
    parts = [
        scene.get("situation_id"),
        scene.get("intent_hint"),
        scene.get("summary"),
        frame.get("semantic_tags"),
        frame.get("semantics"),
        frame.get("events"),
    ]
    return " ".join(json.dumps(part, ensure_ascii=False, default=str) for part in parts if part).lower()


def _is_feedback_frame(frame: Mapping[str, Any]) -> bool:
    text = _scene_text_blob(frame)
    return any(token in text for token in [
        "feedback",
        "ack",
        "confirmed",
        "balanced",
        "effect",
        "mood_neutral",
        "mood_bright",
        "反馈",
        "确认",
        "回落",
    ])


def _infer_scene_id(frame: Mapping[str, Any]) -> str:
    scene = frame.get("scene") or {}
    scene_id = str(scene.get("situation_id") or "").strip()
    text = _scene_text_blob(frame)
    if scene_id in {"heat_cooling_loop", "music_cocktail_loop"}:
        return scene_id
    if any(token in text for token in ["music", "sound", "cocktail", "loud", "音乐", "声音", "鸡尾酒"]):
        return "music_cocktail_loop"
    if any(token in text for token in ["hot", "heat", "cooling", "spray", "ice_water", "热", "清凉", "冰水", "喷雾"]):
        return "heat_cooling_loop"
    if _is_feedback_frame(frame):
        return "observe_only"
    return scene_id or "observe_only"


def record_event_block_candidate(frame: Mapping[str, Any], world_state: Mapping[str, Any]) -> Dict[str, Any]:
    event_block = {
        "event_block_id": f"evt_disabled_{int(time.time()*1000)}_{len(event_block_store)+1}",
        "enabled": EVENT_BLOCK_LAYER_ENABLED,
        "status": "disabled_bypassed",
        "reason": "Event-block scheduling is retained as a future layer, but current Agent loop uses world_state directly.",
        "frame_id": frame.get("frame_id"),
        "space_id": frame.get("space_id"),
        "scene_id": world_state.get("active_scene_id"),
        "created_at": now_cst_ms(),
    }
    event_block_store.append(event_block)
    del event_block_store[:-80]
    return event_block


def update_world_state(frame: Dict[str, Any], context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    context = context or {}
    space_id = frame.get("space_id") or "unknown"
    previous = world_state_store.get(space_id) or {}
    scene = frame.get("scene") or {}
    active_scene_id = _infer_scene_id(frame)
    frame_ids = (previous.get("recent_frame_ids") or []) + [frame.get("frame_id")]
    raw_refs = frame.get("raw_refs") or []
    world_state = {
        "schema_version": "zhichang_tongyu_world_state.v1",
        "space_id": space_id,
        "episode_id": previous.get("episode_id") or f"episode_{space_id}_{int(time.time()*1000)}",
        "updated_at": now_cst_ms(),
        "active_scene_id": active_scene_id,
        "scene_phase": "feedback" if _is_feedback_frame(frame) else "perception",
        "summary": scene.get("summary") or previous.get("summary") or "",
        "intent_hint": scene.get("intent_hint") or "",
        "semantic_tags": frame.get("semantic_tags") or [],
        "confidence": _bounded_float(frame.get("confidence"), 0.5),
        "priority": _bounded_float(frame.get("priority"), 0.5),
        "safety": frame.get("safety") or {},
        "signals": frame.get("semantics") or {},
        "entities": frame.get("entities") or [],
        "affordances": frame.get("affordances") or [],
        "terminal_refs": raw_refs,
        "terminal_count": len(raw_refs),
        "latest_frame_id": frame.get("frame_id"),
        "recent_frame_ids": [item for item in frame_ids if item][-12:],
        "recent_command_count": len(context.get("recent_commands") or []),
        "recent_robot_ack_count": len(context.get("recent_robot_acks") or []),
        "recent_device_ack_count": len(context.get("recent_device_acks") or []),
        "retrieved_memory_count": len(context.get("retrieved_memory") or []),
        "event_block_layer": {
            "enabled": EVENT_BLOCK_LAYER_ENABLED,
            "current_use": "disabled_bypassed",
        },
    }
    world_state_store[space_id] = world_state
    return world_state


def decide_agent_mode(frame: Mapping[str, Any], world_state: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
    priority = _bounded_float(frame.get("priority"), 0.5)
    confidence = _bounded_float(frame.get("confidence"), 0.5)
    scene_phase = world_state.get("scene_phase")
    scene_id = world_state.get("active_scene_id") or "observe_only"
    safety_level = str((frame.get("safety") or {}).get("level") or "normal").lower()
    text = _scene_text_blob(frame)
    failed_feedback = any(
        str(ack.get("status") or "").lower() in {"failed", "blocked", "timeout", "error"}
        for ack in (context.get("recent_robot_acks") or [])[-5:] + (context.get("recent_device_acks") or [])[-5:]
    )
    deep_keywords = ["thinking_required", "deep_plan", "unsafe", "blocked", "failure", "失败", "阻塞", "危险"]
    needs_deep_thinking = (
        safety_level not in {"", "normal", "ok", "safe"}
        or failed_feedback
        or priority >= 0.88
        or confidence < 0.42
        or any(token in text for token in deep_keywords)
    )

    if scene_phase == "feedback" or scene_id == "observe_only" or priority < 0.42:
        model_loop = "skip"
        mode = "fast_feedback"
        thinking = "disabled"
        reason = "Feedback/low-priority frame is handled by the fast rule layer and memory update."
    elif needs_deep_thinking:
        model_loop = "deep_llm"
        mode = "slow_planner"
        thinking = "enabled"
        reason = "Escalated because safety, uncertainty, high priority, or failed feedback requires slower planning."
    else:
        model_loop = "fast_llm"
        mode = "fast_planner"
        thinking = "disabled"
        reason = "Actionable scene enters the Agent tool loop with V4 Flash thinking disabled."

    return {
        "schema_version": "zhichang_tongyu_agent_mode.v1",
        "mode": mode,
        "model_loop": model_loop,
        "thinking": {"type": thinking},
        "reasoning_effort": "high" if thinking == "enabled" else None,
        "target_model": "deepseek-v4-flash",
        "scene_prompt_id": f"{scene_id}.{mode}",
        "event_block_layer_enabled": EVENT_BLOCK_LAYER_ENABLED,
        "reason": reason,
        "signals": {
            "priority": priority,
            "confidence": confidence,
            "scene_phase": scene_phase,
            "safety_level": safety_level,
            "failed_feedback": failed_feedback,
        },
    }


def get_agent_context(space_id: str) -> Dict[str, Any]:
    context = agent_context_store.setdefault(space_id, {
        "space_id": space_id,
        "recent_runs": [],
        "recent_commands": [],
        "recent_robot_acks": [],
        "recent_device_acks": [],
    })
    context["latest_scene"] = semantic_scene_store.get(space_id)
    context["world_state"] = world_state_store.get(space_id)
    context["connected_devices"] = connected_devices
    context["simulation_mode"] = simulation_mode
    context["recent_commands"] = command_history[-20:]
    context["recent_robot_acks"] = robot_ack_history[-20:]
    context["recent_device_acks"] = device_ack_history[-20:]
    context["retrieved_memory"] = retrieve_agent_memory(context.get("latest_scene"), limit=6)
    context["memory_policy"] = {
        "short_term": "latest_scene + recent_runs + last_20_commands + last_20_acks",
        "long_term": str(AGENT_MEMORY_PATH),
        "retrieval": "match current SceneSemanticFrame tokens against memory triggers and compact summaries",
    }
    return context


def normalize_robot_execute_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip().rstrip("/")
    if not url:
        return None
    if url.endswith("/commands"):
        url = url[: -len("/commands")]
    if url.endswith("/api/g1/execute") or url.endswith("/unitree/execute"):
        return url
    return f"{url}/api/g1/execute"


def normalize_gateway_command_url(url: Optional[str], target_type: str = "") -> Optional[str]:
    if not url:
        return None
    if target_type == "robot":
        return normalize_robot_execute_url(url)
    url = str(url).strip().rstrip("/")
    if not url:
        return None
    if url.endswith("/api/command"):
        return url
    return f"{url}/api/command"


def normalize_gateway_health_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip().rstrip("/")
    if not url:
        return None
    if url.endswith("/api/command"):
        return f"{url[: -len('/api/command')]}/health"
    if url.endswith("/health") or url.endswith("/api/status"):
        return url
    return f"{url}/health"


def merge_routing_overrides(
    routing: Dict[str, Any],
    target_id: str,
    target_type: str,
    route_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    route_overrides = route_overrides or {}
    merged = dict(routing or {})
    for key in (target_id, target_type):
        override = route_overrides.get(key)
        if isinstance(override, dict):
            merged.update(override)
            direct_http = normalize_gateway_command_url(override.get("direct_http") or override.get("url"), target_type)
            if direct_http:
                merged["direct_http"] = direct_http
        elif isinstance(override, str):
            direct_http = normalize_gateway_command_url(override, target_type)
            if direct_http:
                merged["direct_http"] = direct_http
    robot_url = route_overrides.get("robot_url")
    if target_type == "robot" and robot_url:
        direct_http = normalize_robot_execute_url(str(robot_url))
        if direct_http:
            merged["direct_http"] = direct_http
    gateway_url_key = {
        "spray_gateway": "spray_url",
        "speaker_gateway": "speaker_url",
        "projection_gateway": "projection_url",
    }.get(target_type)
    if gateway_url_key and route_overrides.get(gateway_url_key):
        direct_http = normalize_gateway_command_url(str(route_overrides[gateway_url_key]), target_type)
        if direct_http:
            merged["direct_http"] = direct_http
    return merged


def default_routing_for_command(target_id: str, target_type: str, command_type: str) -> Dict[str, Any]:
    if target_type == "robot":
        if command_type == "g1.unitree_sdk_sequence":
            return {
                "http_poll": f"/api/devices/{target_id}/commands",
                "ros2_topic": "/talking_spaces/g1/sdk_sequence",
                "mqtt_topic": f"talking_spaces/{target_id}/sdk_sequence",
            }
        return {
            "http_poll": f"/api/devices/{target_id}/commands",
            "ros2_topic": "/talking_spaces/g1/command",
            "mqtt_topic": f"talking_spaces/{target_id}/command",
        }
    if target_type == "spray_gateway":
        return {"http_poll": f"/api/devices/{target_id}/commands", "tcp_endpoint": "12003"}
    if target_type == "speaker_gateway":
        return {"http_poll": f"/api/devices/{target_id}/commands", "tcp_endpoint": "12004"}
    if target_type == "projection_gateway":
        return {"http_poll": f"/api/devices/{target_id}/commands", "tcp_endpoint": "12005"}
    return {"http_poll": f"/api/devices/{target_id}/commands"}


DEFAULT_AGENT_TARGET_IDS = {
    "robot": "unitree_g1",
    "spray_gateway": "spray_gateway",
    "speaker_gateway": "speaker_gateway",
    "projection_gateway": "projection_gateway",
}


def materialize_agent_command(
    planned_command: Dict[str, Any],
    *,
    run_id: str,
    space_id: str,
    scenario_id: str,
    index: int,
    route_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body = planned_command.get("command") if isinstance(planned_command.get("command"), Mapping) else {}
    if not body:
        body = {
            "type": planned_command.get("type") or planned_command.get("command_type") or "unknown",
            "params": planned_command.get("params") or {},
        }
    command_type = body.get("type", "unknown")
    target_type = planned_command.get("target_type", "")
    target_id = planned_command.get("target_id") or DEFAULT_AGENT_TARGET_IDS.get(target_type, "")
    routing = default_routing_for_command(target_id, target_type, command_type)
    routing.update(planned_command.get("routing") or {})
    routing = merge_routing_overrides(routing, target_id, target_type, route_overrides)

    cmd = DeviceCommand(
        message_id=planned_command.get("message_id") or f"cmd_agent_{int(time.time()*1000)}_{index}",
        timestamp=now_cst_ms(),
        target_id=target_id,
        target_type=target_type,
        command={"type": command_type, "params": body.get("params") or {}},
        routing=routing,
        ack_required=planned_command.get("ack_required", True),
        timeout_ms=int(planned_command.get("timeout_ms", 60000)),
    )
    cmd_dict = asdict(cmd)
    cmd_dict["agent_run_id"] = run_id
    cmd_dict["space_id"] = space_id
    cmd_dict["scenario_id"] = scenario_id
    return cmd_dict


def maybe_dispatch_direct_http(command: Dict[str, Any]) -> Dict[str, Any]:
    direct_http = ((command.get("routing") or {}).get("direct_http"))
    if not direct_http:
        return {"message_id": command.get("message_id"), "status": "skipped", "reason": "no direct_http route"}
    raw = json.dumps(command, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        direct_http,
        data=raw,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    timeout = min(max(command.get("timeout_ms", 60000) / 1000.0, 3.0), 30.0)
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
            result = {
                "message_id": command.get("message_id"),
                "status": "ok",
                "transport": "direct_http",
                "url": direct_http,
                "response": payload,
                "robot_response": payload,
            }
            if command.get("target_type") != "robot":
                result["device_response"] = payload
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        result = {
            "message_id": command.get("message_id"),
            "status": "failed",
            "transport": "direct_http",
            "url": direct_http,
            "error": f"HTTP {exc.code}: {body[:500]}",
            "response": payload,
        }
        if command.get("target_type") == "robot":
            result["robot_response"] = payload
        else:
            result["robot_response"] = payload
            result["device_response"] = payload
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        result = {
            "message_id": command.get("message_id"),
            "status": "failed",
            "transport": "direct_http",
            "url": direct_http,
            "error": str(exc),
        }
    event_stream.append({"type": "command_dispatch", "result": result, "time_ms": int(time.time() * 1000)})
    broadcast("command_dispatch", result)
    return result


def record_direct_dispatch_ack(command: Dict[str, Any], dispatch_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if dispatch_result.get("status") not in {"ok", "failed"}:
        return None
    response_payload = dispatch_result.get("response") or dispatch_result.get("robot_response") or {}
    if not isinstance(response_payload, dict):
        return None

    if command.get("target_type") == "robot":
        final_ack = response_payload.get("final_ack")
        if not isinstance(final_ack, dict) or not final_ack.get("message_id"):
            return None
        ack = dict(final_ack)
        ack.setdefault("target_id", command.get("target_id", "unitree_g1"))
        ack.setdefault("status", "ok")
        ack.setdefault("stage", "direct_http_final_ack")
        ack.setdefault("device_time", datetime.now(CST).isoformat())
        ack["transport"] = "direct_http"
        if any(item.get("message_id") == ack.get("message_id") and item.get("stage") == ack.get("stage") for item in robot_ack_history):
            return None
        robot_ack_history.append(ack)
        for context in agent_context_store.values():
            context["recent_robot_acks"] = robot_ack_history[-20:]
        command["latest_robot_ack"] = ack
        memory_record = record_ack_memory(ack, command, ack_kind="robot_ack")
        zhichang_hermes.record_ack(ack, command, memory_record, ack_kind="robot_ack")
        record = {"ack": ack, "memory_record": memory_record}
        event_stream.append({"type": "robot_ack", "result": ack, "memory_record": memory_record, "time_ms": int(time.time() * 1000)})
        broadcast("robot_ack", ack)
        return record

    if not response_payload.get("message_id"):
        return None
    ack = {
        "message_id": response_payload.get("message_id"),
        "task_id": response_payload.get("task_id"),
        "target_id": response_payload.get("target_id", command.get("target_id", "unknown_device")),
        "target_type": response_payload.get("target_type", command.get("target_type")),
        "status": response_payload.get("status", "unknown"),
        "stage": response_payload.get("stage"),
        "progress": response_payload.get("progress"),
        "executed_steps": response_payload.get("executed_steps", []),
        "device_time": response_payload.get("device_time", datetime.now(CST).isoformat()),
        "error": response_payload.get("error"),
        "telemetry": response_payload.get("telemetry", {}),
        "artifacts": response_payload.get("artifacts", []),
        "simulated": bool(response_payload.get("simulated", False)),
        "transport": "direct_http",
        "plug_command": response_payload.get("plug_command"),
        "speaker_command": response_payload.get("speaker_command"),
    }
    if any(item.get("message_id") == ack.get("message_id") and item.get("stage") == ack.get("stage") for item in device_ack_history):
        return None
    device_ack_history.append(ack)
    for context in agent_context_store.values():
        context["recent_device_acks"] = device_ack_history[-20:]
    command["latest_device_ack"] = ack
    memory_record = record_ack_memory(ack, command, ack_kind="device_ack")
    zhichang_hermes.record_ack(ack, command, memory_record, ack_kind="device_ack")
    if ack["target_id"] in connected_devices:
        connected_devices[ack["target_id"]]["last_seen"] = datetime.now(CST).isoformat()
        connected_devices[ack["target_id"]]["status"] = ack["status"]
    record = {"ack": ack, "memory_record": memory_record}
    event_stream.append({"type": "device_ack", "result": ack, "memory_record": memory_record, "time_ms": int(time.time() * 1000)})
    broadcast("device_ack", ack)
    return record


def process_scene_semantic_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Accept fused scene semantics from the data-analysis group.

    This is the handoff point from multi-sensor fusion into the LLM hub. It does
    not assume raw sensor ownership; it preserves source references for audit and
    creates a traceable run envelope for downstream LLM/tool orchestration.
    """
    scene = data.get("scene") or {}
    timestamp = data.get("timestamp") or now_cst_ms()
    frame_id = data.get("frame_id") or f"ssf_{int(time.time()*1000)}"
    space_id = data.get("space_id") or scene.get("space_id") or "unknown"
    confidence = float(data.get("confidence", scene.get("confidence", 0.5)) or 0.5)
    priority = float(data.get("priority", scene.get("priority", 0.5)) or 0.5)

    frame = SceneSemanticFrame(
        frame_id=frame_id,
        timestamp=timestamp,
        source_id=data.get("source_id", "data_analysis_fusion"),
        space_id=space_id,
        time_window=data.get("time_window", {}),
        scene=scene,
        semantics=data.get("semantics", {}),
        entities=data.get("entities", []),
        events=data.get("events", []),
        affordances=data.get("affordances", []),
        safety=data.get("safety", {}),
        raw_refs=data.get("raw_refs", []),
        semantic_tags=extract_scene_semantic_tags(data),
        confidence=confidence,
        priority=priority,
    )
    frame_dict = asdict(frame)
    semantic_scene_store[space_id] = frame_dict

    run_id = f"run_{int(time.time()*1000)}"
    route_overrides = data.get("routing_overrides") or {}
    if data.get("robot_url"):
        route_overrides["robot_url"] = data.get("robot_url")
    context = get_agent_context(space_id)
    world_state = update_world_state(frame_dict, context)
    event_block = record_event_block_candidate(frame_dict, world_state)
    context["world_state"] = world_state
    agent_mode = decide_agent_mode(frame_dict, world_state, context)
    context_window = {
        "latest_scene_frame_id": ((context.get("latest_scene") or {}).get("frame_id")),
        "world_state": world_state,
        "agent_mode": agent_mode,
        "event_block_layer": {
            "enabled": EVENT_BLOCK_LAYER_ENABLED,
            "latest_candidate": event_block,
        },
        "recent_run_count": len(context.get("recent_runs") or []),
        "recent_command_count": len(context.get("recent_commands") or []),
        "recent_robot_ack_count": len(context.get("recent_robot_acks") or []),
        "recent_device_ack_count": len(context.get("recent_device_acks") or []),
        "retrieved_memory": context.get("retrieved_memory") or [],
        "memory_policy": context.get("memory_policy") or {},
    }
    hermes_result = zhichang_hermes.run_turn(
        frame_dict,
        context,
        agent_planner,
        run_id=run_id,
        context_window=context_window,
        agent_mode=agent_mode,
    )
    planner_decision = hermes_result["planner_decision"]
    hermes_turn = hermes_result["hermes_turn"]
    planned_commands = planner_decision.get("commands", [])
    commands = [
        materialize_agent_command(
            planned,
            run_id=run_id,
            space_id=space_id,
            scenario_id=planner_decision.get("scenario_id", "unknown"),
            index=index,
            route_overrides=route_overrides,
        )
        for index, planned in enumerate(planned_commands, start=1)
    ]
    if commands:
        command_history.extend(commands)
    dispatch_results = [maybe_dispatch_direct_http(command) for command in commands]
    zhichang_hermes.record_dispatch(run_id, commands, dispatch_results)
    direct_ack_records = [
        record
        for command, dispatch_result in zip(commands, dispatch_results)
        for record in [record_direct_dispatch_ack(command, dispatch_result)]
        if record
    ]

    trace = zhichang_hermes.legacy_trace(hermes_turn)
    agent_run = {
        "run_id": run_id,
        "frame_id": frame.frame_id,
        "space_id": frame.space_id,
        "status": "planned" if commands else "observed",
        "trace": trace,
        "hermes_turn": hermes_turn,
        "context_window": context_window,
        "world_state": world_state,
        "agent_mode": agent_mode,
        "event_block": event_block,
        "planner": planner_decision.get("provider"),
        "scenario_id": planner_decision.get("scenario_id"),
        "planner_warning": planner_decision.get("planner_warning"),
    }
    agent_run_store[run_id] = agent_run
    context = get_agent_context(space_id)
    context["last_run_id"] = run_id
    context["recent_runs"] = (context.get("recent_runs", []) + [agent_run])[-10:]

    result = {
        "frame": frame_dict,
        "agent_run": agent_run,
        "planner_decision": planner_decision,
        "hermes_turn": hermes_turn,
        "world_state": world_state,
        "agent_mode": agent_mode,
        "event_block": event_block,
        "command_count": len(commands),
        "commands": commands,
        "dispatch_results": dispatch_results,
        "direct_ack_records": direct_ack_records,
        "next_api": "GET /api/commands/history and POST /api/robot/ack or /api/device/ack for feedback",
    }
    event_stream.append({"type": "scene_semantic_ingest", "result": result, "time_ms": int(time.time() * 1000)})
    broadcast("scene_semantic_update", result)
    return result


def load_agent_io_registry() -> Dict[str, Any]:
    """Load editable input semantics and output tool/action definitions."""
    input_registry = load_json_file(
        AGENT_IO_REGISTRY_DIR / "input_semantics.json",
        {"schema_version": "fallback", "semantic_layers": [], "sources": [], "items": [], "assemblies": []},
    )
    output_registry = load_json_file(
        AGENT_IO_REGISTRY_DIR / "output_tools.json",
        {"schema_version": "fallback", "categories": [], "actions": [], "presets": []},
    )
    return {
        "registry_dir": str(AGENT_IO_REGISTRY_DIR),
        "input_semantics": input_registry,
        "output_tools": output_registry,
    }


def _registry_items_by_id(registry: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    items = (((registry.get("input_semantics") or {}).get("items")) or [])
    return {str(item.get("id")): item for item in items if isinstance(item, Mapping) and item.get("id")}


def _registry_actions_by_id(registry: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    actions = (((registry.get("output_tools") or {}).get("actions")) or [])
    return {str(action.get("id")): action for action in actions if isinstance(action, Mapping) and action.get("id")}


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _deep_merge(base: Dict[str, Any], patch: Mapping[str, Any]) -> Dict[str, Any]:
    for key, value in (patch or {}).items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = _json_clone(value)
    return base


def _dedupe_dicts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _infer_scene_from_tags(tags: List[str], fallback: str = "observe_only") -> str:
    joined = " ".join(tags).lower()
    if any(token in joined for token in ["sound", "music", "cocktail", "projection"]):
        return "music_cocktail_loop"
    if any(token in joined for token in ["heat", "hot", "cooling", "human_hot"]):
        return "heat_cooling_loop"
    return fallback


def _input_item_summary(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "label": item.get("label"),
        "layer": item.get("layer"),
        "source_id": item.get("source_id"),
        "summary": item.get("summary"),
        "tags": item.get("tags") or [],
    }


def assemble_scene_frame_from_registry(data: Mapping[str, Any]) -> Dict[str, Any]:
    registry = load_agent_io_registry()
    item_index = _registry_items_by_id(registry)
    raw_ids = data.get("selected_ids") or []
    if not raw_ids and isinstance(data.get("items"), list):
        raw_ids = [item.get("id") if isinstance(item, Mapping) else item for item in data.get("items") or []]
    selected_ids = [str(item_id) for item_id in raw_ids if item_id]
    patches = data.get("item_patches") or {}
    selected_items: List[Dict[str, Any]] = []
    missing_ids: List[str] = []
    for item_id in selected_ids:
        item = item_index.get(item_id)
        if not item:
            missing_ids.append(item_id)
            continue
        cloned = _json_clone(item)
        patch = patches.get(item_id) if isinstance(patches, Mapping) else None
        if isinstance(patch, Mapping):
            _deep_merge(cloned, patch)
        selected_items.append(cloned)

    tags: List[str] = []
    semantics: Dict[str, Any] = {}
    safety: Dict[str, Any] = {"level": "normal"}
    entities: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    affordances: List[Dict[str, Any]] = []
    raw_refs: List[Dict[str, Any]] = []
    summaries: List[str] = []
    layers: List[str] = []
    sources: List[str] = []
    priorities: List[float] = []
    confidences: List[float] = []
    space_id = data.get("space_id")
    situation_id = data.get("situation_id")
    intent_hint = data.get("intent_hint")

    for item in selected_items:
        summaries.append(str(item.get("summary") or item.get("label") or item.get("id")))
        layers.append(str(item.get("layer") or ""))
        sources.append(str(item.get("source_id") or ""))
        tags.extend(str(tag) for tag in (item.get("tags") or []) if tag)
        if item.get("space_id") and not space_id:
            space_id = item.get("space_id")
        if item.get("situation_id"):
            situation_id = item.get("situation_id")
        if item.get("intent_hint"):
            intent_hint = item.get("intent_hint")
        if isinstance(item.get("semantics"), Mapping):
            _deep_merge(semantics, item.get("semantics") or {})
        if isinstance(item.get("safety"), Mapping):
            _deep_merge(safety, item.get("safety") or {})
        entities.extend(_json_clone(item.get("entities") or []))
        events.extend(_json_clone(item.get("events") or []))
        affordances.extend(_json_clone(item.get("affordances") or []))
        raw_refs.extend(_json_clone(item.get("raw_refs") or []))
        priorities.append(_bounded_float(item.get("priority"), 0.5))
        confidences.append(_bounded_float(item.get("confidence"), 0.5))

    custom_text = str(data.get("custom_text") or "").strip()
    if custom_text:
        summaries.append(custom_text)
        semantics["operator_note"] = {"label": custom_text, "role": "input_lab"}

    tags = list(dict.fromkeys(tag for tag in tags if tag))
    if not situation_id:
        situation_id = _infer_scene_from_tags(tags)
    if not intent_hint:
        if situation_id == "heat_cooling_loop":
            intent_hint = "cooling_request"
        elif situation_id == "music_cocktail_loop":
            intent_hint = "music_cocktail"
        else:
            intent_hint = "observe"
    if situation_id and situation_id != "observe_only":
        tags = list(dict.fromkeys(tags + [situation_id, intent_hint]))

    summary = str(data.get("summary") or " / ".join(summaries) or "Manual world state assembly")
    frame = {
        "message_type": "scene_semantic_frame",
        "frame_id": data.get("frame_id") or f"ssf_assembled_{int(time.time()*1000)}",
        "timestamp": data.get("timestamp") or now_cst_ms(),
        "source_id": data.get("source_id") or "input_lab.world_state_assembler",
        "space_id": space_id or ("sound_cocktail_zone_01" if situation_id == "music_cocktail_loop" else "cooling_zone_01"),
        "time_window": data.get("time_window") or {"aggregation": "manual_sequence", "duration_sec": 8},
        "scene": {
            "situation_id": situation_id,
            "summary": summary,
            "intent_hint": intent_hint,
            "tags": tags,
        },
        "semantics": semantics,
        "entities": _dedupe_dicts([item for item in entities if isinstance(item, dict)]),
        "events": _dedupe_dicts([item for item in events if isinstance(item, dict)]),
        "affordances": _dedupe_dicts([item for item in affordances if isinstance(item, dict)]),
        "safety": safety,
        "raw_refs": _dedupe_dicts([item for item in raw_refs if isinstance(item, dict)]),
        "semantic_tags": tags,
        "confidence": round(sum(confidences) / len(confidences), 3) if confidences else _bounded_float(data.get("confidence"), 0.62),
        "priority": round(max(priorities), 3) if priorities else _bounded_float(data.get("priority"), 0.52),
    }
    frame["semantics"]["world_state_assembly"] = {
        "selected_ids": selected_ids,
        "missing_ids": missing_ids,
        "layers": list(dict.fromkeys(item for item in layers if item)),
        "sources": list(dict.fromkeys(item for item in sources if item)),
        "assembly_mode": data.get("assembly_mode") or "manual_ordered_units",
    }
    if data.get("robot_url"):
        frame["robot_url"] = data.get("robot_url")
    if data.get("routing_overrides"):
        frame["routing_overrides"] = data.get("routing_overrides")
    return {
        "frame": frame,
        "selected_items": [_input_item_summary(item) for item in selected_items],
        "missing_ids": missing_ids,
    }


def input_frame_preview(frame: Mapping[str, Any], selected_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    semantics = frame.get("semantics") or {}
    return {
        "frame_id": frame.get("frame_id"),
        "space_id": frame.get("space_id"),
        "situation_id": (frame.get("scene") or {}).get("situation_id"),
        "intent_hint": (frame.get("scene") or {}).get("intent_hint"),
        "summary": (frame.get("scene") or {}).get("summary"),
        "semantic_tags": frame.get("semantic_tags") or [],
        "priority": frame.get("priority"),
        "confidence": frame.get("confidence"),
        "signals": [key for key in semantics.keys() if key != "world_state_assembly"],
        "selected": selected_items,
        "raw_ref_count": len(frame.get("raw_refs") or []),
    }


def _action_summary(action: Mapping[str, Any]) -> Dict[str, Any]:
    command = action.get("command") or {}
    return {
        "id": action.get("id"),
        "label": action.get("label"),
        "category": action.get("category"),
        "target_type": action.get("target_type"),
        "command_type": command.get("type") if isinstance(command, Mapping) else "g1.unitree_sdk_sequence.step",
        "description": action.get("description"),
    }


def _apply_action_param_overrides(command: Dict[str, Any], override: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not override:
        return command
    params = command.setdefault("params", {})
    if isinstance(override.get("params"), Mapping):
        _deep_merge(params, override.get("params") or {})
    for key, value in override.items():
        if key == "params":
            continue
        params[key] = _json_clone(value)
    return command


def compile_output_actions(data: Mapping[str, Any]) -> Dict[str, Any]:
    registry = load_agent_io_registry()
    action_index = _registry_actions_by_id(registry)
    raw_ids = data.get("action_ids") or data.get("selected_ids") or []
    if not raw_ids and isinstance(data.get("actions"), list):
        raw_ids = [item.get("id") if isinstance(item, Mapping) else item for item in data.get("actions") or []]
    action_ids = [str(action_id) for action_id in raw_ids if action_id]
    overrides = data.get("action_overrides") or {}
    run_id = data.get("run_id") or f"manual_output_{int(time.time()*1000)}"
    default_space_id = data.get("space_id") or "output_test_lab"
    default_scenario_id = data.get("scenario_id") or "output_test"
    route_overrides = data.get("routing_overrides") or {}
    if data.get("robot_url"):
        route_overrides["robot_url"] = data.get("robot_url")

    selected_actions: List[Dict[str, Any]] = []
    missing_ids: List[str] = []
    planned_commands: List[Dict[str, Any]] = []
    sdk_steps: List[Dict[str, Any]] = []

    def flush_sdk_steps() -> None:
        if not sdk_steps:
            return
        task_id = f"manual_g1_sdk_{int(time.time()*1000)}"
        sequence = []
        for index, step in enumerate(sdk_steps, start=1):
            cloned = _json_clone(step)
            cloned.setdefault("seq", index)
            cloned.setdefault("step", index)
            sequence.append(cloned)
        planned_commands.append({
            "target_id": "unitree_g1",
            "target_type": "robot",
            "space_id": "cooling_zone_01",
            "scenario_id": "g1_sdk_manual_sequence",
            "ack_required": True,
            "timeout_ms": 60000,
            "command": {
                "type": "g1.unitree_sdk_sequence",
                "params": {
                    "task_id": task_id,
                    "scene_id": "g1_sdk_manual_sequence",
                    "speech_cn": "动作链测试开始。",
                    "safety": {"dry_run": True, "speed_limit_mps": 0.25, "min_human_distance_m": 0.8},
                    "sdk_sequence": sequence,
                },
            },
            "source_action_ids": [item.get("source_action_id") for item in sdk_steps if item.get("source_action_id")],
        })
        sdk_steps.clear()

    for action_id in action_ids:
        action = action_index.get(action_id)
        if not action:
            missing_ids.append(action_id)
            continue
        selected_actions.append(_action_summary(action))
        override = overrides.get(action_id) if isinstance(overrides, Mapping) else None
        if isinstance(action.get("sdk_step"), Mapping):
            step = _json_clone(action.get("sdk_step") or {})
            step["source_action_id"] = action_id
            if isinstance(override, Mapping):
                _deep_merge(step.setdefault("args", {}), override.get("args") or {})
            sdk_steps.append(step)
            continue
        flush_sdk_steps()
        command_body = _json_clone(action.get("command") or {})
        command_body = _apply_action_param_overrides(command_body, override if isinstance(override, Mapping) else None)
        params = command_body.setdefault("params", {})
        task_prefix = str(params.get("task_id") or action_id)
        params["task_id"] = f"{task_prefix}_{int(time.time()*1000)}"
        planned_commands.append({
            "target_id": action.get("target_id"),
            "target_type": action.get("target_type"),
            "space_id": action.get("space_id") or default_space_id,
            "scenario_id": action.get("scenario_id") or default_scenario_id,
            "ack_required": action.get("ack_required", True),
            "timeout_ms": int(action.get("timeout_ms") or (60000 if action.get("target_type") == "robot" else 15000)),
            "command": command_body,
            "source_action_ids": [action_id],
        })
    flush_sdk_steps()

    materialized_commands: List[Dict[str, Any]] = []
    dispatch_results: List[Dict[str, Any]] = []
    direct_ack_records: List[Dict[str, Any]] = []
    for index, planned in enumerate(planned_commands, start=1):
        command = materialize_agent_command(
            planned,
            run_id=run_id,
            space_id=planned.get("space_id") or default_space_id,
            scenario_id=planned.get("scenario_id") or default_scenario_id,
            index=index,
            route_overrides=route_overrides,
        )
        command["manual_test"] = True
        command["source_action_ids"] = planned.get("source_action_ids") or []
        materialized_commands.append(command)
        command_history.append(command)
        dispatch_result = maybe_dispatch_direct_http(command) if data.get("execute", True) else {
            "message_id": command.get("message_id"),
            "status": "prepared",
            "reason": "execute=false",
        }
        dispatch_results.append(dispatch_result)
        ack_record = record_direct_dispatch_ack(command, dispatch_result)
        if ack_record:
            direct_ack_records.append(ack_record)

    chain = [
        {
            "phase": "select",
            "title": "Select registered tools",
            "summary": f"{len(selected_actions)} actions selected from registry.",
            "items": selected_actions,
        },
        {
            "phase": "compile",
            "title": "Compile DeviceCommand chain",
            "summary": f"{len(materialized_commands)} command envelopes prepared.",
            "command_types": [(command.get("command") or {}).get("type") for command in materialized_commands],
        },
    ]
    for command, dispatch_result in zip(materialized_commands, dispatch_results):
        chain.append({
            "phase": "dispatch",
            "title": f"{command.get('target_id')} / {(command.get('command') or {}).get('type')}",
            "summary": dispatch_result.get("status") or "prepared",
            "message_id": command.get("message_id"),
        })
    for record in direct_ack_records:
        ack = record.get("ack") or {}
        chain.append({
            "phase": "ack",
            "title": f"{ack.get('target_id')} ACK",
            "summary": f"{ack.get('status')} / {ack.get('stage')}",
            "message_id": ack.get("message_id"),
        })

    return {
        "run_id": run_id,
        "selected_actions": selected_actions,
        "missing_ids": missing_ids,
        "planned_command_count": len(planned_commands),
        "commands": materialized_commands,
        "dispatch_results": dispatch_results,
        "direct_ack_records": direct_ack_records,
        "chain": chain,
    }


def broadcast(msg_type: str, payload: Dict):
    """向所有 WebSocket 客户端广播消息"""
    envelope = json.dumps({"type": msg_type, "payload": payload, "timestamp": datetime.now(CST).isoformat()})
    dead = []
    for ws in ws_clients:
        try:
            ws.send(envelope)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


def make_abc_square_client() -> ABCSquareClient:
    return ABCSquareClient(load_abc_square_config(ROOT_DIR))


def abc_square_credentials_error(client: ABCSquareClient):
    health_payload = None
    try:
        health_payload = client.health()
    except ABCSquareAPIError as exc:
        health_payload = {"status": "unknown", "message": str(exc)}
    return jsonify({
        "error": "abc_square_credentials_missing",
        "message": "ABC Square business APIs require HMAC credentials.",
        "status": client.status(),
        "health": health_payload,
    }), 503


def abc_square_api_error(exc: ABCSquareAPIError):
    status_code = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
    return jsonify({
        "error": "abc_square_api_error",
        "message": str(exc),
        "status_code": exc.status_code,
        "upstream_payload": exc.payload,
    }), status_code


def request_time_window(data: Optional[Dict] = None) -> Dict[str, Any]:
    data = data or {}
    hours = request.args.get("hours", data.get("hours", 1))
    try:
        hours = max(1, min(int(hours), 24 * 7))
    except (TypeError, ValueError):
        hours = 1
    return {
        "start_time": request.args.get("start_time") or data.get("start_time"),
        "end_time": request.args.get("end_time") or data.get("end_time"),
        "hours": hours,
    }


def build_environment_state_from_abc_snapshot(snapshot: Mapping[str, Any], population_capacity: float = 120.0) -> Dict[str, Any]:
    sources = snapshot.get("sources", {}) if isinstance(snapshot, Mapping) else {}
    env = latest_source_row(sources.get("environment", {}))
    emotions = latest_source_row(sources.get("emotions", {}))
    population = latest_source_row(sources.get("population", {}))

    emotion_counts = emotions.get("emotion_counts") or {}
    total_emotions = as_float(emotions.get("total_emotion_count"), sum(as_float(v) for v in emotion_counts.values()))
    happy_ratio = safe_ratio(emotion_counts, ["happy"], total_emotions)
    stress_ratio = safe_ratio(emotion_counts, ["panic", "sad", "angry", "disgusted"], total_emotions)
    neutral_ratio = safe_ratio(emotion_counts, ["poker-faced", "unknown"], total_emotions)

    people_avg = as_float(population.get("avg_human_in_area"))
    people_max = as_float(population.get("max_human_in_area"), people_avg)
    people_count = max(people_avg, people_max)
    people_density = bounded(people_count / max(float(population_capacity or 1.0), 1.0), 0.0, 1.0)

    temperature = as_float(env.get("temperature"), 25.0)
    humidity = as_float(env.get("humidity"), 50.0)
    noise = as_float(env.get("noise"), 45.0)
    pm25 = as_float(env.get("pm25"))
    pm10 = as_float(env.get("pm10"))
    pressure = as_float(env.get("pressure"), 1013.0)
    wind_power = as_float(env.get("wind_power"))
    comfort_score = compute_comfort_score(temperature, humidity, noise, people_density, stress_ratio, pm25)

    tags = environment_semantic_tags(temperature, humidity, noise, people_density, happy_ratio, stress_ratio, pm25)
    intent_hint = "music_cocktail" if "sound_cocktail" in tags else "cooling_request" if "hot" in tags else "environment_update"
    hour_start = env.get("hour_start") or emotions.get("hour_start") or population.get("hour_start")

    return {
        "space_id": "abc_square_main_hall",
        "hour_start": hour_start,
        "snapshot_window": snapshot.get("window", {}) if isinstance(snapshot, Mapping) else {},
        "sensor_values": {
            "temperature_c": round(temperature, 2),
            "humidity_pct": round(humidity, 2),
            "noise_db": round(noise, 2),
            "pm25": round(pm25, 2),
            "pm10": round(pm10, 2),
            "pressure_hpa": round(pressure, 2),
            "wind_power": round(wind_power, 2),
            "people_count": round(people_count, 2),
            "people_density": round(people_density, 3),
            "mood_happy_ratio": round(happy_ratio, 3),
            "mood_stress_ratio": round(stress_ratio, 3),
            "mood_neutral_ratio": round(neutral_ratio, 3),
            "comfort_score": round(comfort_score, 3),
        },
        "semantic_tags": tags,
        "intent_hint": intent_hint,
        "dominant_mood": dominant_mood(happy_ratio, stress_ratio, neutral_ratio),
        "source_rows": {
            "environment": env,
            "emotions": emotions,
            "population": population,
        },
    }


def latest_source_row(response: Mapping[str, Any]) -> Dict[str, Any]:
    rows = response.get("data") if isinstance(response, Mapping) else None
    if isinstance(rows, list) and rows:
        return rows[-1] or {}
    return {}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def safe_ratio(counts: Mapping[str, Any], keys: List[str], total: float) -> float:
    if total <= 0:
        return 0.0
    return bounded(sum(as_float(counts.get(key)) for key in keys) / total, 0.0, 1.0)


def dominant_mood(happy: float, stress: float, neutral: float) -> str:
    if stress >= max(happy, neutral) and stress >= 0.18:
        return "stressed"
    if happy >= max(stress, neutral) and happy >= 0.25:
        return "happy"
    if neutral >= 0.45:
        return "neutral"
    return "mixed"


def environment_semantic_tags(
    temperature: float,
    humidity: float,
    noise: float,
    density: float,
    happy: float,
    stress: float,
    pm25: float,
) -> List[str]:
    tags: List[str] = []
    if temperature >= 30:
        tags.extend(["hot", "human_hot"])
    elif temperature <= 16:
        tags.append("cold")
    else:
        tags.append("temperate")
    if humidity >= 68:
        tags.append("humid")
    elif humidity <= 30:
        tags.append("dry")
    if noise >= 68:
        tags.extend(["sound_cocktail", "loud"])
    if density >= 0.7:
        tags.append("crowded")
    elif density >= 0.35:
        tags.append("moderate")
    else:
        tags.append("open")
    if stress >= 0.22:
        tags.append("mood_stressed")
    elif happy >= 0.35:
        tags.append("mood_bright")
    if pm25 >= 75:
        tags.append("air_quality_attention")
    return tags


def compute_comfort_score(temperature: float, humidity: float, noise: float, density: float, stress: float, pm25: float) -> float:
    temp_penalty = min(abs(temperature - 24.0) / 16.0, 1.0)
    humidity_penalty = min(abs(humidity - 50.0) / 50.0, 1.0)
    noise_penalty = bounded((noise - 45.0) / 40.0, 0.0, 1.0)
    pm_penalty = bounded(pm25 / 120.0, 0.0, 1.0)
    score = 1.0 - (0.25 * temp_penalty + 0.2 * humidity_penalty + 0.2 * noise_penalty + 0.2 * density + 0.1 * stress + 0.05 * pm_penalty)
    return bounded(score, 0.0, 1.0)


def bounded(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


# ============================================================
# REST API 路由
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "tongyu-central-hub",
        "version": "0.3.0",
        "simulation_mode": simulation_mode,
        "connected_devices": len(connected_devices),
        "rules_loaded": len(engine.rules),
        "event_log_size": len(engine.event_log),
        "platforms_loaded": len(PLATFORM_REGISTRY.get("platforms", [])),
        "capabilities": [
            "telemetry_ingest",
            "generic_agent_planner",
            "kimi_coding_planner_with_fallback",
            "agent_public_reasoning_trace",
            "platform_registry",
            "two_scene_demo",
            "abc_square_live_data",
            "heat_cooling_loop",
            "music_cocktail_loop",
            "unitree_g1_sdk_sequence",
            "scene_semantic_ingest",
            "agent_run_trace",
            "target_command_polling",
            "direct_http_robot_push",
            "generic_device_ack",
            "generated_media_assets"
        ]
    })


@app.route("/api/progress", methods=["GET"])
def get_progress():
    return jsonify(PROJECT_PROGRESS)


@app.route("/api/platforms", methods=["GET"])
def get_platforms():
    return jsonify(PLATFORM_REGISTRY)


@app.route("/api/platforms/benchmark", methods=["GET"])
def get_platform_benchmark():
    items = [{
        "id": item["id"],
        "name": item["name"],
        "domain": item["domain"],
        "venue": item["venue"],
        "github": item["github"],
        "local_status": item["local_status"],
        "tongyu_lesson": item["tongyu_lesson"],
        "bridge_payload": item["bridge_payload"]
    } for item in PLATFORM_REGISTRY.get("platforms", [])]
    return jsonify({"selection_rule": PLATFORM_REGISTRY.get("selection_rule", ""), "platforms": items})


@app.route("/api/storylines", methods=["GET"])
def get_storylines():
    return jsonify({"storylines": DEMO_STORYLINES, "source": "agent_planner.py", "active_scenarios": SCENARIO_DEFINITIONS})


@app.route("/api/abc-square/status", methods=["GET"])
def get_abc_square_status():
    client = make_abc_square_client()
    health_payload = None
    health_error = None
    try:
        health_payload = client.health()
    except ABCSquareAPIError as exc:
        health_error = str(exc)
    return jsonify({
        "status": client.status(),
        "health": health_payload,
        "health_error": health_error,
        "latest_snapshot_cached": bool(abc_square_snapshot_store.get("latest")),
    })


@app.route("/api/abc-square/snapshot", methods=["GET"])
def get_abc_square_snapshot():
    client = make_abc_square_client()
    if not client.config.configured:
        return abc_square_credentials_error(client)
    try:
        window = request_time_window()
        snapshot = client.fetch_snapshot(**window)
    except ABCSquareAPIError as exc:
        return abc_square_api_error(exc)
    abc_square_snapshot_store["latest"] = snapshot
    event_stream.append({"type": "abc_square_snapshot", "result": {"window": snapshot.get("window")}, "time_ms": int(time.time() * 1000)})
    return jsonify(snapshot)


@app.route("/api/abc-square/ingest", methods=["POST"])
def ingest_abc_square_snapshot():
    data = request.get_json(silent=True) or {}
    client = make_abc_square_client()
    if not client.config.configured:
        return abc_square_credentials_error(client)
    try:
        snapshot = client.fetch_snapshot(**request_time_window(data))
        environment_state = build_environment_state_from_abc_snapshot(snapshot, data.get("population_capacity", 120.0))
    except ABCSquareAPIError as exc:
        return abc_square_api_error(exc)

    abc_square_snapshot_store["latest"] = snapshot
    result = process_sensor_payload(
        space_id=data.get("space_id", environment_state.get("space_id", "abc_square_main_hall")),
        sensor_values=environment_state["sensor_values"],
        source_device="abc_square_api",
        priority=data.get("priority", 0.65)
    )
    return jsonify({
        "snapshot": snapshot,
        "environment_state": environment_state,
        "hub_result": result,
    })


@app.route("/api/llm-hub/dossier", methods=["GET"])
def get_llm_hub_dossier():
    return jsonify({
        "progress": PROJECT_PROGRESS,
        "rules": rule_summaries(),
        "storylines": DEMO_STORYLINES,
        "agent_planner": agent_planner.public_status(),
        "agent_contexts": agent_context_store,
        "platform_registry": PLATFORM_REGISTRY,
        "latest_telemetry": telemetry_store,
        "latest_scene_semantics": semantic_scene_store,
        "command_count": len(command_history),
        "device_ack_count": len(device_ack_history),
        "agent_run_count": len(agent_run_store),
        "agent_memory_count": len(agent_memory_store),
        "agent_memory_path": str(AGENT_MEMORY_PATH),
        "abc_square": {
            "status": make_abc_square_client().status(),
            "latest_snapshot_window": (abc_square_snapshot_store.get("latest") or {}).get("window"),
        }
    })


@app.route("/api/agent/config", methods=["GET"])
def get_agent_config():
    return jsonify(agent_planner.public_status())


@app.route("/api/agent/context/<space_id>", methods=["GET"])
def get_agent_context_route(space_id: str):
    return jsonify({"space_id": space_id, "context": get_agent_context(space_id)})


@app.route("/api/agent/world-state", methods=["GET"])
def get_world_states_route():
    return jsonify({
        "world_states": world_state_store,
        "count": len(world_state_store),
        "event_block_layer_enabled": EVENT_BLOCK_LAYER_ENABLED,
    })


@app.route("/api/agent/world-state/<space_id>", methods=["GET"])
def get_world_state_route(space_id: str):
    state = world_state_store.get(space_id)
    if not state:
        return jsonify({"error": "space not found", "space_id": space_id}), 404
    return jsonify({"space_id": space_id, "world_state": state})


@app.route("/api/agent/event-blocks", methods=["GET"])
def get_event_blocks_route():
    limit = max(1, min(request.args.get("limit", 50, type=int), 200))
    return jsonify({
        "enabled": EVENT_BLOCK_LAYER_ENABLED,
        "event_blocks": event_block_store[-limit:],
        "total": len(event_block_store),
    })


@app.route("/api/agent/runtime-policy", methods=["GET"])
def get_agent_runtime_policy_route():
    return jsonify({
        "event_block_layer": {
            "enabled": EVENT_BLOCK_LAYER_ENABLED,
            "current_use": "retained_as_disabled_future_layer",
        },
        "scene_layer": "SceneSemanticFrame streams are aggregated into world_state before model context.",
        "model_layer": {
            "default_model": "deepseek-v4-flash",
            "default_thinking": "disabled",
            "thinking_escalation": [
                "safety level is not normal",
                "recent robot/device feedback failed or blocked",
                "priority >= 0.88",
                "confidence < 0.42",
                "explicit deep_plan/thinking_required semantic tag",
            ],
        },
    })


@app.route("/api/agent/io-registry", methods=["GET"])
def get_agent_io_registry_route():
    registry = load_agent_io_registry()
    return jsonify({
        "registry_dir": registry["registry_dir"],
        "input_semantics": registry["input_semantics"],
        "output_tools": registry["output_tools"],
    })


@app.route("/api/agent/input-test/assemble", methods=["POST"])
def post_input_test_assemble_route():
    data = request.get_json(silent=True) or {}
    assembly = assemble_scene_frame_from_registry(data)
    frame = assembly["frame"]
    preview = input_frame_preview(frame, assembly["selected_items"])
    result = None
    if data.get("run_agent", True):
        result = process_scene_semantic_payload(frame)
    payload = {
        "status": "processed" if result else "assembled",
        "preview": preview,
        "frame": frame,
        "selected_items": assembly["selected_items"],
        "missing_ids": assembly["missing_ids"],
        "result": result,
    }
    event_stream.append({"type": "input_test_assembly", "result": payload, "time_ms": int(time.time() * 1000)})
    broadcast("input_test_assembly", payload)
    return jsonify(payload)


@app.route("/api/agent/output-test/sequence", methods=["POST"])
def post_output_test_sequence_route():
    data = request.get_json(silent=True) or {}
    compiled = compile_output_actions(data)
    status = "sent" if data.get("execute", True) else "prepared"
    payload = {"status": status, **compiled}
    event_stream.append({"type": "output_test_sequence", "result": payload, "time_ms": int(time.time() * 1000)})
    broadcast("device_command", {"commands": compiled["commands"], "dispatch_results": compiled["dispatch_results"], "source": "output_test_sequence"})
    return jsonify(payload)


@app.route("/api/agent/gateway-health", methods=["GET"])
def get_agent_gateway_health():
    gateway_url = request.args.get("url") or request.args.get("gateway_url") or ""
    health_url = normalize_gateway_health_url(gateway_url)
    if not health_url:
        return jsonify({"status": "failed", "error": "url is required"}), 400

    timeout = max(0.5, min(request.args.get("timeout", 2.0, type=float), 8.0))
    smart_plug_ip = request.args.get("smart_plug_ip") or request.args.get("plug_ip") or "192.168.1.156"
    plug_tcp_endpoint = request.args.get("plug_tcp_endpoint") or "192.168.1.50:8080"
    try:
        req = UrlRequest(health_url, method="GET", headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
        plug_status = payload.get("plug") if isinstance(payload, Mapping) else None
        plug_connected = bool(plug_status.get("connected")) if isinstance(plug_status, Mapping) else False
        return jsonify({
            "status": "ok" if plug_connected else "degraded",
            "gateway_reachable": True,
            "gateway_url": str(gateway_url).strip().rstrip("/"),
            "health_url": health_url,
            "command_url": normalize_gateway_command_url(gateway_url, "spray_gateway"),
            "smart_plug": {
                "ip": smart_plug_ip,
                "tcp_endpoint": plug_tcp_endpoint,
                "connected": plug_connected,
                "status": plug_status or {"connected": False},
            },
            "upstream": payload,
        })
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"raw": body}
        return jsonify({
            "status": "failed",
            "gateway_reachable": True,
            "gateway_url": str(gateway_url).strip().rstrip("/"),
            "health_url": health_url,
            "command_url": normalize_gateway_command_url(gateway_url, "spray_gateway"),
            "smart_plug": {
                "ip": smart_plug_ip,
                "tcp_endpoint": plug_tcp_endpoint,
                "connected": False,
            },
            "error": f"HTTP {exc.code}",
            "upstream": payload,
        }), 502
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return jsonify({
            "status": "failed",
            "gateway_reachable": False,
            "gateway_url": str(gateway_url).strip().rstrip("/"),
            "health_url": health_url,
            "command_url": normalize_gateway_command_url(gateway_url, "spray_gateway"),
            "smart_plug": {
                "ip": smart_plug_ip,
                "tcp_endpoint": plug_tcp_endpoint,
                "connected": False,
            },
            "error": str(exc),
        }), 502


@app.route("/api/agent/memory", methods=["GET"])
def get_agent_memory_route():
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    layer = request.args.get("layer")
    scenario_id = request.args.get("scenario_id")
    query = request.args.get("q")
    records = agent_memory_store
    if layer:
        records = [item for item in records if item.get("layer") == layer]
    if scenario_id:
        records = [item for item in records if item.get("scenario_id") == scenario_id]
    if query:
        query_tokens = memory_tokens(query)
        records = [
            item for item in records
            if query_tokens & (memory_tokens(item.get("summary") or "") | memory_tokens(item.get("triggers") or []))
        ]
    return jsonify({
        "agent_name": "智场同语中枢Agent",
        "memory_path": str(AGENT_MEMORY_PATH),
        "memories": [compact_memory_record(item) for item in records[-limit:]],
        "total": len(agent_memory_store),
    })


@app.route("/api/agent/runs/latest", methods=["GET"])
def get_latest_agent_runs():
    limit = request.args.get("limit", 10, type=int)
    runs = list(agent_run_store.values())[-limit:]
    return jsonify({"runs": runs, "total": len(agent_run_store)})


@app.route("/api/hermes/status", methods=["GET"])
def get_hermes_status():
    return jsonify(zhichang_hermes.status())


@app.route("/api/hermes/tools", methods=["GET"])
def get_hermes_tools():
    return jsonify(zhichang_hermes.tools_status())


@app.route("/api/hermes/turns/latest", methods=["GET"])
def get_latest_hermes_turns():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(zhichang_hermes.latest_turns(limit))


@app.route("/api/hermes/conversation", methods=["GET"])
def get_hermes_conversation():
    limit = request.args.get("limit", 80, type=int)
    return jsonify(zhichang_hermes.latest_conversation(limit))


@app.route("/api/hermes/message", methods=["POST"])
def post_hermes_message():
    """Manual semantic text entry for input/output test pages."""
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if data.get("frame"):
        frame = data["frame"]
        zhichang_hermes.record_human_message(text or "manual SceneSemanticFrame", meta={"source": "agent_console_test"})
        result = process_scene_semantic_payload(frame)
        return jsonify({"status": "processed", "message_mode": "frame", "result": result})
    if not text:
        return jsonify({"error": "text or frame is required"}), 400
    mode = data.get("mode") or "physical_semantic"
    message = zhichang_hermes.record_human_message(text, meta={"mode": mode})
    if mode in {"note", "operator_note"}:
        broadcast("hermes_message", message)
        return jsonify({"status": "recorded", "message": message})
    frame = semantic_text_to_frame(text)
    if data.get("space_id"):
        frame["space_id"] = data["space_id"]
    if data.get("robot_url"):
        frame["robot_url"] = data["robot_url"]
    if data.get("routing_overrides"):
        frame["routing_overrides"] = data["routing_overrides"]
    if mode == "output_tool_test":
        text_lower = text.lower()
        scene = frame.setdefault("scene", {})
        if any(token in text_lower for token in ["music", "sound", "projection", "speaker", "音乐", "声音", "投影", "音响", "鸡尾酒"]):
            frame["space_id"] = data.get("space_id") or "sound_cocktail_zone_01"
            scene["situation_id"] = "music_cocktail_loop"
            scene["intent_hint"] = "music_cocktail"
            tags = ["output_tool_test", "music_cocktail", "music", "projection"]
        else:
            frame["space_id"] = data.get("space_id") or "cooling_zone_01"
            scene["situation_id"] = "heat_cooling_loop"
            scene["intent_hint"] = "robot_action_sequence"
            tags = ["output_tool_test", "hot", "cooling_request", "ice_water", "robot_action"]
        scene["summary"] = text
        frame["source_id"] = "operator.output_test"
        frame["semantic_tags"] = list(dict.fromkeys((frame.get("semantic_tags") or []) + tags))
        frame["priority"] = max(_bounded_float(frame.get("priority"), 0.5), 0.72)
        frame["confidence"] = max(_bounded_float(frame.get("confidence"), 0.5), 0.78)
        frame.setdefault("semantics", {})["operator_goal"] = {"label": text, "level": "test", "tags": tags}
    result = process_scene_semantic_payload(frame)
    return jsonify({"status": "processed", "message": message, "frame": frame, "result": result})


@app.route("/api/agent/output-test/command", methods=["POST"])
def post_output_test_command():
    """Send one standard DeviceCommand through the same command envelope used by Agent plans."""
    data = request.get_json(silent=True) or {}
    planned = data.get("command") if isinstance(data.get("command"), dict) else data
    if not isinstance(planned, dict):
        return jsonify({"error": "command object is required"}), 400
    run_id = data.get("run_id") or f"manual_output_{int(time.time()*1000)}"
    space_id = data.get("space_id") or planned.get("space_id") or "output_test_lab"
    scenario_id = data.get("scenario_id") or planned.get("scenario_id") or "output_test"
    route_overrides = data.get("routing_overrides") or {}
    if data.get("robot_url"):
        route_overrides["robot_url"] = data.get("robot_url")
    command = materialize_agent_command(
        planned,
        run_id=run_id,
        space_id=space_id,
        scenario_id=scenario_id,
        index=1,
        route_overrides=route_overrides,
    )
    command["manual_test"] = True
    command_history.append(command)
    dispatch_result = maybe_dispatch_direct_http(command)
    direct_ack_record = record_direct_dispatch_ack(command, dispatch_result)
    event_stream.append({"type": "output_test_command", "result": {"command": command, "dispatch_result": dispatch_result, "direct_ack_record": direct_ack_record}, "time_ms": int(time.time() * 1000)})
    broadcast("device_command", {"command": command, "dispatch_result": dispatch_result, "source": "output_test"})
    return jsonify({"status": "sent", "command": command, "dispatch_result": dispatch_result, "direct_ack_record": direct_ack_record})


@app.route("/api/demo/storyline/<storyline_id>", methods=["POST"])
def run_demo_storyline(storyline_id: str):
    return run_demo_scenario(storyline_id)


@app.route("/api/demo/scenario/<scenario_id>", methods=["POST"])
def run_demo_scenario(scenario_id: str):
    selected = next((item for item in DEMO_STORYLINES if item["id"] == scenario_id), None)
    if selected is None:
        return jsonify({"error": "unknown scenario", "scenario_id": scenario_id}), 404
    for rule in engine.rules:
        if rule["rule_id"] in selected.get("expected_rules", []):
            rule["last_fired"] = 0
    data = request.get_json(silent=True) or {}
    frame = dict(selected["sample_frame"])
    frame.update(data.get("frame_patch") or {})
    if data.get("robot_url"):
        frame["robot_url"] = data["robot_url"]
    if data.get("routing_overrides"):
        frame["routing_overrides"] = data["routing_overrides"]
    result = process_scene_semantic_payload(frame)
    broadcast("demo_scenario", {"scenario": selected, "result": result})
    return jsonify({"scenario": selected, "result": result})


@app.route("/api/telemetry/latest", methods=["GET"])
def get_latest_telemetry():
    return jsonify({"telemetry": telemetry_store, "count": len(telemetry_store)})


@app.route("/api/telemetry/latest/<space_id>", methods=["GET"])
def get_space_telemetry(space_id: str):
    if space_id in telemetry_store:
        return jsonify({"space_id": space_id, "telemetry": telemetry_store[space_id]})
    return jsonify({"error": "space not found", "space_id": space_id}), 404


@app.route("/api/telemetry/ingest", methods=["POST"])
def ingest_telemetry():
    """Layer 1→2: 接收传感器帧，生成语义标签，触发 ECA 评估"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "invalid JSON"}), 400

    result = process_sensor_payload(
        space_id=data.get("space_id", "unknown"),
        sensor_values=data.get("sensor_values", {}),
        source_device=data.get("source_device", "chongzhi_field"),
        priority=data.get("priority", 0.5)
    )
    return jsonify(result)


@app.route("/api/scene/semantic/latest", methods=["GET"])
def get_latest_scene_semantics():
    return jsonify({"scene_semantics": semantic_scene_store, "count": len(semantic_scene_store)})


@app.route("/api/scene/semantic/latest/<space_id>", methods=["GET"])
def get_space_scene_semantics(space_id: str):
    if space_id in semantic_scene_store:
        return jsonify({"space_id": space_id, "scene_semantics": semantic_scene_store[space_id]})
    return jsonify({"error": "space not found", "space_id": space_id}), 404


@app.route("/api/scene/semantic/ingest", methods=["POST"])
def ingest_scene_semantic():
    """Receive fused, high-level scene semantics from the data-analysis group."""
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "invalid JSON"}), 400
    if data.get("message_type") not in (None, "scene_semantic_frame"):
        return jsonify({"error": "unsupported message_type", "expected": "scene_semantic_frame"}), 400
    if not (data.get("space_id") or (data.get("scene") or {}).get("space_id")):
        return jsonify({"error": "space_id is required"}), 400
    return jsonify(process_scene_semantic_payload(data))


@app.route("/api/command", methods=["POST"])
def send_command():
    """Layer 3→4: 下发设备命令"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "invalid JSON"}), 400

    cmd = DeviceCommand(
        message_id=data.get("message_id", f"cmd_{int(time.time()*1000)}"),
        timestamp=datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}+08:00",
        target_id=data.get("target_id", ""),
        target_type=data.get("target_type", ""),
        command=data.get("command", {}),
        routing=data.get("routing", {}),
        ack_required=data.get("ack_required", True)
    )

    cmd_dict = asdict(cmd)
    command_history.append(cmd_dict)

    if simulation_mode:
        # 模拟设备 ack
        ack = {
            "message_id": cmd.message_id,
            "target_id": cmd.target_id,
            "status": "ok",
            "device_time": datetime.now(CST).isoformat(),
            "error": None,
            "simulated": True
        }
    else:
        ack = {"message_id": cmd.message_id, "target_id": cmd.target_id, "status": "pending"}

    broadcast("device_command", {"command": cmd_dict, "ack": ack})
    return jsonify({"command": cmd_dict, "ack": ack})


@app.route("/api/agent/message", methods=["POST"])
def agent_message():
    """Layer 3↔3: 智能体间消息 (request/invite/alert/negotiate/respond)"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "invalid JSON"}), 400

    verb = data.get("verb", "request")
    if verb not in [v.value for v in Verb]:
        return jsonify({"error": f"unknown verb: {verb}"}), 400

    msg = {
        "message_type": "agent_message",
        "message_id": f"msg_{int(time.time()*1000)}",
        "timestamp": datetime.now(CST).isoformat(),
        "source_agent": data.get("source_agent", ""),
        "target_agents": data.get("target_agents", []),
        "verb": verb,
        "content": data.get("content", {}),
        "priority": data.get("priority", 0.5)
    }

    broadcast("agent_message", msg)
    return jsonify({"status": "routed", "message": msg})


@app.route("/api/events", methods=["GET"])
def get_events():
    """获取事件流"""
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"events": event_stream[-limit:], "total": len(event_stream)})


@app.route("/api/commands/history", methods=["GET"])
def get_command_history():
    limit = request.args.get("limit", 50, type=int)
    target_id = request.args.get("target_id")
    command_type = request.args.get("command_type")
    commands = command_history
    if target_id:
        commands = [cmd for cmd in commands if cmd.get("target_id") == target_id]
    if command_type:
        commands = [cmd for cmd in commands if (cmd.get("command") or {}).get("type") == command_type]
    return jsonify({"commands": commands[-limit:], "total": len(commands)})


@app.route("/api/devices/register", methods=["POST"])
def register_device_client():
    """Register or update a LAN hardware client such as spray/speaker/projector/G1."""
    data = request.get_json(silent=True) or {}
    target_id = data.get("target_id")
    if not target_id:
        return jsonify({"error": "target_id is required"}), 400
    connected_devices[target_id] = {
        "target_id": target_id,
        "target_type": data.get("target_type", "unknown"),
        "client_id": data.get("client_id", target_id),
        "ip": data.get("ip") or request.remote_addr,
        "port": data.get("port"),
        "capabilities": data.get("capabilities", []),
        "transport": data.get("transport", "http_poll"),
        "last_seen": datetime.now(CST).isoformat(),
        "status": data.get("status", "online"),
        "meta": data.get("meta", {}),
    }
    event_stream.append({"type": "device_register", "result": connected_devices[target_id], "time_ms": int(time.time() * 1000)})
    broadcast("device_register", connected_devices[target_id])
    return jsonify({"status": "registered", "device": connected_devices[target_id]})


@app.route("/api/devices/<target_id>/commands", methods=["GET"])
def get_device_commands(target_id: str):
    """Hardware clients poll this endpoint and execute commands addressed to them."""
    limit = request.args.get("limit", 20, type=int)
    after_message_id = request.args.get("after_message_id")
    command_type = request.args.get("command_type")
    commands = [cmd for cmd in command_history if cmd.get("target_id") == target_id]
    if command_type:
        commands = [cmd for cmd in commands if (cmd.get("command") or {}).get("type") == command_type]
    if after_message_id:
        for index, command in enumerate(commands):
            if command.get("message_id") == after_message_id:
                commands = commands[index + 1:]
                break
    return jsonify({"target_id": target_id, "commands": commands[-limit:], "total": len(commands)})


@app.route("/api/device/ack", methods=["POST"])
def ingest_device_ack():
    """Receive execution feedback from any LAN hardware client."""
    data = request.get_json(silent=True) or {}
    if not data.get("message_id"):
        return jsonify({"error": "message_id is required"}), 400
    target_id = data.get("target_id", "unknown_device")
    ack = {
        "message_id": data.get("message_id"),
        "task_id": data.get("task_id"),
        "target_id": target_id,
        "target_type": data.get("target_type"),
        "status": data.get("status", "unknown"),
        "stage": data.get("stage"),
        "progress": data.get("progress"),
        "executed_steps": data.get("executed_steps", []),
        "device_time": data.get("device_time", datetime.now(CST).isoformat()),
        "error": data.get("error"),
        "telemetry": data.get("telemetry", {}),
        "artifacts": data.get("artifacts", []),
        "simulated": bool(data.get("simulated", False)),
    }
    device_ack_history.append(ack)
    for context in agent_context_store.values():
        context["recent_device_acks"] = device_ack_history[-20:]
    matched_command = None
    for command in reversed(command_history):
        if command.get("message_id") == ack["message_id"]:
            command["latest_device_ack"] = ack
            matched_command = command
            break
    memory_record = record_ack_memory(ack, matched_command, ack_kind="device_ack")
    zhichang_hermes.record_ack(ack, matched_command, memory_record, ack_kind="device_ack")
    if target_id in connected_devices:
        connected_devices[target_id]["last_seen"] = datetime.now(CST).isoformat()
        connected_devices[target_id]["status"] = ack["status"]
    event_stream.append({"type": "device_ack", "result": ack, "memory_record": memory_record, "time_ms": int(time.time() * 1000)})
    broadcast("device_ack", ack)
    return jsonify({"status": "received", "ack": ack, "memory_record": memory_record})


@app.route("/api/device/ack/history", methods=["GET"])
def get_device_ack_history():
    limit = request.args.get("limit", 50, type=int)
    target_id = request.args.get("target_id")
    acks = device_ack_history
    if target_id:
        acks = [ack for ack in acks if ack.get("target_id") == target_id]
    return jsonify({"acks": acks[-limit:], "total": len(acks)})


@app.route("/api/robot/ack", methods=["POST"])
def ingest_robot_ack():
    """Receive execution feedback from the G1 onboard computer or ROS2 bridge."""
    data = request.get_json(silent=True) or {}
    if not data.get("message_id"):
        return jsonify({"error": "message_id is required"}), 400

    ack = {
        "message_id": data.get("message_id"),
        "task_id": data.get("task_id"),
        "target_id": data.get("target_id", "unitree_g1"),
        "status": data.get("status", "unknown"),
        "stage": data.get("stage"),
        "progress": data.get("progress"),
        "executed_steps": data.get("executed_steps", []),
        "device_time": data.get("device_time", datetime.now(CST).isoformat()),
        "error": data.get("error"),
        "telemetry": data.get("telemetry", {}),
        "simulated": bool(data.get("simulated", False)),
    }
    robot_ack_history.append(ack)
    for context in agent_context_store.values():
        context["recent_robot_acks"] = robot_ack_history[-20:]
    matched_command = None
    for command in reversed(command_history):
        if command.get("message_id") == ack["message_id"]:
            command["latest_robot_ack"] = ack
            matched_command = command
            break
    memory_record = record_ack_memory(ack, matched_command, ack_kind="robot_ack")
    zhichang_hermes.record_ack(ack, matched_command, memory_record, ack_kind="robot_ack")
    event_stream.append({"type": "robot_ack", "result": ack, "memory_record": memory_record, "time_ms": int(time.time() * 1000)})
    broadcast("robot_ack", ack)
    return jsonify({"status": "received", "ack": ack, "memory_record": memory_record})


@app.route("/api/robot/ack/history", methods=["GET"])
def get_robot_ack_history():
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"acks": robot_ack_history[-limit:], "total": len(robot_ack_history)})


@app.route("/api/simulation/toggle", methods=["POST"])
def toggle_simulation():
    global simulation_mode
    data = request.get_json() or {}
    simulation_mode = data.get("enabled", not simulation_mode)
    broadcast("simulation_changed", {"simulation_mode": simulation_mode})
    return jsonify({"simulation_mode": simulation_mode})


@app.route("/api/personas", methods=["GET"])
def get_personas():
    return jsonify({"personas": SPACE_PERSONAS, "count": len(SPACE_PERSONAS)})


@app.route("/api/personas/<space_id>", methods=["GET"])
def get_persona(space_id: str):
    if space_id in SPACE_PERSONAS:
        return jsonify({"space_id": space_id, "persona": SPACE_PERSONAS[space_id]})
    return jsonify({"error": "persona not found"}), 404


@app.route("/api/rules", methods=["GET"])
def get_rules():
    rules_summary = rule_summaries()
    return jsonify({"rules": rules_summary, "count": len(rules_summary)})


# ============================================================
# WebSocket
# ============================================================

@sock.route("/ws")
def ws_endpoint(ws):
    ws_clients.append(ws)
    logger.info(f"WebSocket client connected, total: {len(ws_clients)}")
    try:
        # 发送初始状态
        ws.send(json.dumps({
            "type": "connected",
            "payload": {
                "simulation_mode": simulation_mode,
                "rules_count": len(engine.rules),
                "personas": list(SPACE_PERSONAS.keys()),
                "telemetry_spaces": list(telemetry_store.keys())
            }
        }))
        while True:
            msg = ws.receive()
            if msg is None:
                break
            try:
                data = json.loads(msg)
                logger.info(f"WS received: {data.get('type', 'unknown')}")
                # 处理 WebSocket 消息（如手动触发规则）
                if data.get("type") == "trigger_rule":
                    rule_id = data.get("rule_id", "")
                    logger.info(f"Manual trigger: {rule_id}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.info(f"WebSocket disconnected: {e}")
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)
        logger.info(f"WebSocket client left, total: {len(ws_clients)}")


# ============================================================
# 静态文件服务 (前端)
# ============================================================

FRONTEND_DIR = ROOT_DIR / "frontend"
TALKING_SPACES_DIR = ROOT_DIR / "frontend"
DECK_DIR = ROOT_DIR / "frontend_slides_deck"
AGENT_CONSOLE_DIR = ROOT_DIR / "frontend" / "zhichang_agent_console"

@app.route("/")
def index():
    return redirect("/agent-console", code=302)

@app.route("/deck")
def serve_deck():
    return send_from_directory(str(DECK_DIR), "index.html")

@app.route("/agent-console")
@app.route("/console")
def serve_agent_console():
    return send_from_directory(str(AGENT_CONSOLE_DIR), "index.html")

@app.route("/agent-console/<path:path>")
@app.route("/console/<path:path>")
def serve_agent_console_asset(path: str):
    asset_path = AGENT_CONSOLE_DIR / path
    if asset_path.exists() and asset_path.is_file():
        return send_from_directory(str(AGENT_CONSOLE_DIR), path)
    return send_from_directory(str(AGENT_CONSOLE_DIR), "index.html")

@app.route("/frontend/<path:path>")
def serve_talking_spaces(path: str):
    return send_from_directory(str(TALKING_SPACES_DIR), path)

@app.route("/assets/generated/<path:path>")
def serve_generated_media(path: str):
    GENERATED_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(GENERATED_MEDIA_DIR), path)

@app.route("/<path:path>")
def serve_static(path: str):
    return send_from_directory(str(FRONTEND_DIR), path)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="同语中枢服务器")
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  同语中枢 (Tongyu Central Hub) v0.3.0")
    logger.info(f"  HTTP:  http://{args.host}:{args.port}")
    logger.info(f"  WS:    ws://{args.host}:{args.port}/ws")
    logger.info(f"  Rules: {len(engine.rules)} ECA rules loaded")
    logger.info(f"  Simulation mode: {simulation_mode}")
    logger.info("=" * 60)

    app.run(host=args.host, port=args.port, debug=args.debug)
