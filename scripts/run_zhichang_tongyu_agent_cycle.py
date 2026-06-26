#!/usr/bin/env python3
"""Run a two-scene Zhichang Tongyu Central Agent demo cycle.

The script generates standard semantic frames, posts them to the central hub,
simulates non-robot device ACKs, observes fake-G1 ACKs when a robot URL is
provided, and writes one replayable trajectory JSON package.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CST = timezone(timedelta(hours=8))
AGENT_NAME = "智场同语中枢Agent"
PROTOCOL_VERSION = "zhichang-tongyu-agent-demo.v1"


def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec="milliseconds")


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 12.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error {url}: {exc.reason}") from exc


def semantic_frame_heat(seq: int, *, resolved: bool = False, robot_url: str | None = None) -> dict[str, Any]:
    frame_id = f"ssf_demo_heat_{seq:02d}_{int(time.time() * 1000)}"
    if not resolved:
        frame = {
            "message_type": "scene_semantic_frame",
            "frame_id": frame_id,
            "timestamp": now_cst(),
            "source_id": "simulated_semantic_fusion.v1",
            "space_id": "cooling_zone_01",
            "time_window": {"aggregation": "5s", "mode": "rolling"},
            "scene": {
                "situation_id": "heat_cooling_loop",
                "summary": "空间温度升高，访客表现出热感和轻微不适，需要清凉联动。",
                "intent_hint": "cooling_request",
                "tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
            },
            "semantics": {
                "environment": {"label": "hot", "level": "warning", "values": {"temperature_c": 32.4, "humidity": 0.62}, "tags": ["hot"]},
                "crowd": {"label": "moderate", "level": "normal", "values": {"person_count": 7}, "tags": ["moderate"]},
                "emotion": {"label": "uncomfortable", "level": "watch", "values": {"negative_ratio": 0.34}, "tags": ["mood_unhappy"]},
            },
            "entities": [
                {"id": "visitor_group_01", "type": "person_group", "zone": "cooling_zone_01", "attributes": {"group_size": 3, "heat_gesture": True}}
            ],
            "events": [
                {"type": "thermal_discomfort_detected", "target": "visitor_group_01", "confidence": 0.88}
            ],
            "affordances": [
                {"action": "spray_mist", "target_zone": "cooling_zone_01", "reason": "降低体感温度"},
                {"action": "deliver_ice_water", "target_zone": "cooling_handoff_01", "reason": "补充清凉服务"},
            ],
            "safety": {"level": "normal", "notes": "可执行低速、干运行G1动作包"},
            "raw_refs": [
                {"source": "sim_temperature_grid", "frame": seq},
                {"source": "sim_crowd_emotion_model", "frame": seq},
            ],
            "semantic_tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
            "confidence": 0.89,
            "priority": 0.84,
        }
        if robot_url:
            frame["robot_url"] = robot_url
        return frame
    return {
        "message_type": "scene_semantic_frame",
        "frame_id": frame_id,
        "timestamp": now_cst(),
        "source_id": "simulated_semantic_fusion.v1",
        "space_id": "cooling_zone_01",
        "time_window": {"aggregation": "5s", "mode": "rolling"},
        "scene": {
            "situation_id": "cooling_feedback",
            "summary": "喷雾和递水动作后，热感下降，访客情绪恢复到中性。",
            "intent_hint": "observe_and_confirm",
            "tags": ["cooling_effect_confirmed", "mood_neutral"],
        },
        "semantics": {
            "environment": {"label": "comfortable", "level": "normal", "values": {"temperature_c": 28.1, "humidity": 0.65}, "tags": ["comfortable"]},
            "emotion": {"label": "neutral", "level": "normal", "values": {"negative_ratio": 0.08}, "tags": ["mood_neutral"]},
        },
        "events": [{"type": "cooling_effect_observed", "confidence": 0.81}],
        "affordances": [{"action": "observe", "reason": "确认反馈，不重复触发动作"}],
        "safety": {"level": "normal", "notes": "无需新增机器人动作"},
        "raw_refs": [{"source": "sim_feedback_after_g1_ack", "frame": seq}],
        "semantic_tags": ["cooling_effect_confirmed", "mood_neutral"],
        "confidence": 0.82,
        "priority": 0.42,
    }


def semantic_frame_music(seq: int, *, resolved: bool = False) -> dict[str, Any]:
    frame_id = f"ssf_demo_music_{seq:02d}_{int(time.time() * 1000)}"
    if not resolved:
        return {
            "message_type": "scene_semantic_frame",
            "frame_id": frame_id,
            "timestamp": now_cst(),
            "source_id": "simulated_sound_fusion.v1",
            "space_id": "sound_cocktail_zone_01",
            "time_window": {"aggregation": "8s", "mode": "rolling"},
            "scene": {
                "situation_id": "music_cocktail_loop",
                "summary": "空间里出现多维声音叠加，整体活跃但略显嘈杂，需要转译成音乐鸡尾酒。",
                "intent_hint": "music_cocktail",
                "tags": ["sound_cocktail", "loud", "lively", "music"],
            },
            "semantics": {
                "soundscape": {"label": "lively_noisy", "level": "watch", "values": {"noise_db": 72.6, "tempo_hint_bpm": 92}, "tags": ["loud", "lively"]},
                "crowd": {"label": "active", "level": "normal", "values": {"person_count": 12}, "tags": ["moderate"]},
                "emotion": {"label": "mixed", "level": "normal", "values": {"positive_ratio": 0.47}, "tags": ["mood_mixed"]},
            },
            "events": [{"type": "sound_cocktail_detected", "confidence": 0.86}],
            "affordances": [
                {"action": "play_music_mix", "reason": "把嘈杂转为有节律的音乐层"},
                {"action": "project_sound_wave", "reason": "把声音语义变成可视化"}
            ],
            "safety": {"level": "normal", "notes": "仅触发音响和投影，无机器人移动"},
            "raw_refs": [{"source": "sim_microphone_array", "frame": seq}],
            "semantic_tags": ["sound_cocktail", "loud", "lively", "music"],
            "confidence": 0.86,
            "priority": 0.69,
        }
    return {
        "message_type": "scene_semantic_frame",
        "frame_id": frame_id,
        "timestamp": now_cst(),
        "source_id": "simulated_sound_fusion.v1",
        "space_id": "sound_cocktail_zone_01",
        "time_window": {"aggregation": "8s", "mode": "rolling"},
        "scene": {
            "situation_id": "music_feedback",
            "summary": "音乐和投影介入后，声场更稳定，空间氛围保持活跃。",
            "intent_hint": "observe_and_confirm",
            "tags": ["soundscape_balanced", "mood_bright"],
        },
        "semantics": {
            "soundscape": {"label": "balanced", "level": "normal", "values": {"noise_db": 63.2}, "tags": ["quiet_enough"]},
            "emotion": {"label": "bright", "level": "normal", "values": {"positive_ratio": 0.62}, "tags": ["mood_bright"]},
        },
        "events": [{"type": "soundscape_balance_observed", "confidence": 0.79}],
        "affordances": [{"action": "observe", "reason": "保持当前声画输出，不重复下发"}],
        "safety": {"level": "normal", "notes": "无需新增动作"},
        "raw_refs": [{"source": "sim_feedback_after_media_ack", "frame": seq}],
        "semantic_tags": ["soundscape_balanced", "mood_bright"],
        "confidence": 0.79,
        "priority": 0.38,
    }


def simulate_device_ack(hub_url: str, command: dict[str, Any], status: str = "ok") -> dict[str, Any]:
    body = command.get("command") or {}
    params = body.get("params") or {}
    ack = {
        "message_id": command.get("message_id"),
        "task_id": params.get("task_id"),
        "target_id": command.get("target_id"),
        "target_type": command.get("target_type"),
        "status": status,
        "stage": "simulated_complete",
        "progress": 1.0,
        "executed_steps": ["validate_schema", body.get("type"), "report_ready"],
        "device_time": now_cst(),
        "error": None,
        "telemetry": {
            "executor": "zhichang_tongyu_demo_runner",
            "content_id": params.get("content_id"),
            "zone": params.get("zone"),
        },
        "artifacts": [],
        "simulated": True,
    }
    return http_json("POST", f"{hub_url.rstrip('/')}/api/device/ack", ack)


def wait_for_robot_acks(hub_url: str, message_ids: list[str], timeout_sec: float) -> list[dict[str, Any]]:
    if not message_ids:
        return []
    deadline = time.time() + timeout_sec
    final: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        payload = http_json("GET", f"{hub_url.rstrip('/')}/api/robot/ack/history?limit=100")
        for ack in payload.get("acks", []):
            mid = ack.get("message_id")
            if mid in message_ids:
                final[mid] = ack
        if all(final.get(mid, {}).get("status") in {"ok", "failed", "blocked", "timeout"} for mid in message_ids):
            break
        time.sleep(0.2)
    return [final[mid] for mid in message_ids if mid in final]


def standards_block() -> dict[str, Any]:
    return {
        "input_semantic_contract": {
            "message_type": "scene_semantic_frame",
            "required_fields": ["space_id", "scene", "semantic_tags", "confidence", "priority"],
            "context_admission": [
                "Every accepted SceneSemanticFrame is stored as latest_scene for its space_id.",
                "Before planning, the Agent context window receives latest_scene, recent_runs, last_20_commands, last_20_robot_acks, last_20_device_acks, and retrieved_memory.",
                "Raw sensor data is not required at this boundary; raw_refs keep audit handles when they exist.",
            ],
        },
        "output_tool_contract": {
            "message_type": "device_command",
            "required_fields": ["message_id", "target_id", "target_type", "command.type", "command.params", "routing", "ack_required"],
            "active_tool_types": [
                "spray.scene",
                "g1.unitree_sdk_sequence",
                "speaker.play",
                "projection.play",
            ],
        },
        "memory_contract": {
            "short_term": "latest scene plus recent runs/commands/ACKs in RAM",
            "long_term": "execution_feedback cards persisted to central_hub/data/zhichang_tongyu_agent_memory.jsonl",
            "retrieval": "current frame tokens match memory triggers; compact cards enter context_window.retrieved_memory",
        },
        "trajectory_contract": {
            "file": "zhichang_tongyu_agent_trajectory.json",
            "contains": ["semantic_frames", "agent_runs", "device_commands", "acks", "memory_records", "action_graph", "events"],
        },
    }


def build_action_graph(agent_runs: list[dict[str, Any]], commands: list[dict[str, Any]], acks: list[dict[str, Any]]) -> dict[str, Any]:
    ack_by_message: dict[str, list[dict[str, Any]]] = {}
    for ack in acks:
        ack_by_message.setdefault(str(ack.get("message_id")), []).append(ack)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for run in agent_runs:
        run_id = run.get("run_id")
        frame_id = run.get("frame_id")
        nodes.append({"id": frame_id, "type": "semantic_frame", "status": "observed", "space_id": run.get("space_id")})
        nodes.append({"id": run_id, "type": "agent_run", "status": run.get("status"), "scenario_id": run.get("scenario_id")})
        edges.append({"from": frame_id, "to": run_id, "relation": "enters_context_and_planning"})
    for command in commands:
        cmd_id = command.get("message_id")
        nodes.append({
            "id": cmd_id,
            "type": "device_command",
            "status": (command.get("latest_robot_ack") or command.get("latest_device_ack") or {}).get("status", "issued"),
            "target_id": command.get("target_id"),
            "command_type": (command.get("command") or {}).get("type"),
        })
        if command.get("agent_run_id"):
            edges.append({"from": command.get("agent_run_id"), "to": cmd_id, "relation": "outputs_tool_command"})
        for ack in ack_by_message.get(str(cmd_id), []):
            ack_id = f"ack_{cmd_id}_{ack.get('status')}_{ack.get('stage')}"
            nodes.append({"id": ack_id, "type": "ack", "status": ack.get("status"), "stage": ack.get("stage")})
            edges.append({"from": cmd_id, "to": ack_id, "relation": "feedback"})
    return {"nodes": nodes, "edges": edges}


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    hub_url = args.hub_url.rstrip("/")
    robot_url = None if args.no_robot_push else args.robot_url.rstrip("/")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    health = http_json("GET", f"{hub_url}/api/health")
    events: list[dict[str, Any]] = [{"type": "hub_health", "timestamp": now_cst(), "payload": health}]

    frames = [
        semantic_frame_heat(1, robot_url=robot_url),
        semantic_frame_heat(2, resolved=True),
        semantic_frame_music(3),
        semantic_frame_music(4, resolved=True),
    ]

    semantic_frames: list[dict[str, Any]] = []
    agent_runs: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    simulated_device_acks: list[dict[str, Any]] = []
    observed_robot_acks: list[dict[str, Any]] = []
    context_snapshots: list[dict[str, Any]] = []

    for frame in frames:
        semantic_frames.append(frame)
        events.append({"type": "semantic_frame_generated", "timestamp": now_cst(), "frame_id": frame["frame_id"], "semantic_tags": frame.get("semantic_tags", [])})
        response = http_json("POST", f"{hub_url}/api/scene/semantic/ingest", frame, timeout=args.request_timeout)
        run = response.get("agent_run") or {}
        agent_runs.append(run)
        frame_commands = response.get("commands") or []
        commands.extend(frame_commands)
        events.append({
            "type": "agent_response",
            "timestamp": now_cst(),
            "frame_id": frame["frame_id"],
            "run_id": run.get("run_id"),
            "scenario_id": run.get("scenario_id"),
            "command_count": len(frame_commands),
            "retrieved_memory_count": len((run.get("context_window") or {}).get("retrieved_memory") or []),
        })

        robot_message_ids: list[str] = []
        for command in frame_commands:
            if command.get("target_type") == "robot":
                robot_message_ids.append(str(command.get("message_id")))
                continue
            ack_response = simulate_device_ack(hub_url, command)
            simulated_device_acks.append(ack_response.get("ack") or {})
            events.append({
                "type": "device_ack_simulated",
                "timestamp": now_cst(),
                "message_id": command.get("message_id"),
                "target_id": command.get("target_id"),
                "status": (ack_response.get("ack") or {}).get("status"),
            })

        robot_acks = wait_for_robot_acks(hub_url, robot_message_ids, args.robot_ack_timeout)
        observed_robot_acks.extend(robot_acks)
        for ack in robot_acks:
            events.append({
                "type": "robot_ack_observed",
                "timestamp": now_cst(),
                "message_id": ack.get("message_id"),
                "status": ack.get("status"),
                "stage": ack.get("stage"),
            })

        context = http_json("GET", f"{hub_url}/api/agent/context/{frame.get('space_id')}")
        context_snapshots.append(context)
        events.append({
            "type": "context_snapshot",
            "timestamp": now_cst(),
            "space_id": frame.get("space_id"),
            "retrieved_memory_count": len(((context.get("context") or {}).get("retrieved_memory") or [])),
        })
        time.sleep(args.pause_sec)

    command_history = http_json("GET", f"{hub_url}/api/commands/history?limit=200")
    robot_history = http_json("GET", f"{hub_url}/api/robot/ack/history?limit=200")
    device_history = http_json("GET", f"{hub_url}/api/device/ack/history?limit=200")
    latest_runs = http_json("GET", f"{hub_url}/api/agent/runs/latest?limit=20")
    memory = http_json("GET", f"{hub_url}/api/agent/memory?limit=200")

    all_acks = list(device_history.get("acks") or []) + list(robot_history.get("acks") or [])
    trajectory = {
        "schema_version": PROTOCOL_VERSION,
        "agent_name": AGENT_NAME,
        "generated_at": now_cst(),
        "hub_url": hub_url,
        "robot_url": robot_url,
        "standards": standards_block(),
        "summary": {
            "semantic_frame_count": len(semantic_frames),
            "agent_run_count": len(agent_runs),
            "device_command_count": len(commands),
            "robot_ack_count": len(robot_history.get("acks") or []),
            "device_ack_count": len(device_history.get("acks") or []),
            "long_term_memory_count": memory.get("total"),
            "active_scenarios": ["heat_cooling_loop", "music_cocktail_loop"],
        },
        "semantic_frames": semantic_frames,
        "agent_runs": agent_runs,
        "device_commands": command_history.get("commands") or commands,
        "acks": {
            "robot": robot_history.get("acks") or observed_robot_acks,
            "device": device_history.get("acks") or simulated_device_acks,
        },
        "context_snapshots": context_snapshots,
        "memory_records": memory.get("memories") or [],
        "action_graph": build_action_graph(latest_runs.get("runs") or agent_runs, command_history.get("commands") or commands, all_acks),
        "events": events,
    }

    json_path = output_dir / "zhichang_tongyu_agent_trajectory.json"
    json_path.write_text(json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_lines = [
        "# 智场同语中枢Agent Demo Trajectory",
        "",
        f"- Generated: {trajectory['generated_at']}",
        f"- Semantic frames: {trajectory['summary']['semantic_frame_count']}",
        f"- Agent runs: {trajectory['summary']['agent_run_count']}",
        f"- Device commands: {trajectory['summary']['device_command_count']}",
        f"- Robot ACKs: {trajectory['summary']['robot_ack_count']}",
        f"- Device ACKs: {trajectory['summary']['device_ack_count']}",
        f"- Long-term memory records: {trajectory['summary']['long_term_memory_count']}",
        f"- JSON: `{json_path}`",
        "",
        "## Loop",
        "",
        "SceneSemanticFrame -> context window -> Agent trace -> DeviceCommand -> ACK -> memory/context update.",
    ]
    md_path = output_dir / "zhichang_tongyu_agent_trajectory_summary.md"
    md_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    return {"trajectory_path": str(json_path), "summary_path": str(md_path), "summary": trajectory["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Zhichang Tongyu Central Agent two-scene cycle")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8798")
    parser.add_argument("--robot-url", default="http://127.0.0.1:8731")
    parser.add_argument("--no-robot-push", action="store_true")
    parser.add_argument("--output-dir", default="outputs/zhichang_agent_cycle_demo")
    parser.add_argument("--pause-sec", type=float, default=0.35)
    parser.add_argument("--robot-ack-timeout", type=float, default=10.0)
    parser.add_argument("--request-timeout", type=float, default=12.0)
    args = parser.parse_args()
    result = run_cycle(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
