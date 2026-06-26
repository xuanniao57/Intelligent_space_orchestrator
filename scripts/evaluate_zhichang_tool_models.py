#!/usr/bin/env python3
"""Evaluate model tool-calling fit for the Zhichang Tongyu central agent.

This script intentionally tests the model as a physical-world agent, not as a
generic coding assistant. It reads the project-level env file, exposes the
registered zhichang Hermes tools, runs a compact tool loop, and writes a JSON
report with latency and domain-tool quality signals.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "central_hub" / "backend"
DEFAULT_ENV_PATH = PROJECT_ROOT.parent / ".env"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT.parent / "tasks" / "2026-06-24_kimi-agent-fake-g1-demo" / "logs"
CST = timezone(timedelta(hours=8))

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@dataclass
class EvalTarget:
    label: str
    provider: str
    model: str
    base_url: str
    api_key: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def public(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
        }


def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec="milliseconds")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def first_value(values: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name) or values.get(name)
        if value:
            return value
    return default


def build_targets(values: dict[str, str]) -> list[EvalTarget]:
    deepseek_key = first_value(values, "DEEPSEEK_API_KEY", "Deepseek_API_KEY")
    deepseek_base = first_value(values, "DEEPSEEK_BASE_URL", "Deepseek_API_BASE", default="https://api.deepseek.com")
    return [
        EvalTarget(
            label="kimi-coding",
            provider="kimi-coding",
            model=first_value(values, "KIMI_CODE_MODEL", default="kimi-for-coding"),
            base_url=first_value(values, "KIMI_CODE_API_BASE", "KIMI_CODE_BASE_URL"),
            api_key=first_value(values, "KIMI_CODE_API_KEY"),
        ),
        EvalTarget(
            label="deepseek-v4-pro",
            provider="deepseek",
            model=first_value(values, "DEEPSEEK_MODEL", "Deepseek_MODEL", default="deepseek-v4-pro"),
            base_url=deepseek_base,
            api_key=deepseek_key,
        ),
        EvalTarget(
            label="deepseek-v4-flash",
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url=deepseek_base,
            api_key=deepseek_key,
        ),
    ]


def semantic_frame_heat() -> dict[str, Any]:
    frame_id = f"ssf_eval_heat_{int(time.time() * 1000)}"
    return {
        "message_type": "scene_semantic_frame",
        "frame_id": frame_id,
        "timestamp": now_cst(),
        "source_id": "eval_semantic_fusion.v1",
        "space_id": "cooling_zone_01",
        "time_window": {"aggregation": "5s", "mode": "rolling"},
        "scene": {
            "situation_id": "heat_cooling_loop",
            "summary": "现场温度升高，访客出现热感和轻微不适，需要清凉联动。",
            "intent_hint": "cooling_request",
            "tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
        },
        "semantics": {
            "environment": {
                "label": "hot",
                "level": "warning",
                "values": {"temperature_c": 33.1, "humidity": 0.61},
                "tags": ["hot"],
            },
            "crowd": {
                "label": "moderate",
                "level": "normal",
                "values": {"person_count": 9},
                "tags": ["moderate"],
            },
            "emotion": {
                "label": "uncomfortable",
                "level": "watch",
                "values": {"negative_ratio": 0.32},
                "tags": ["mood_unhappy"],
            },
        },
        "entities": [
            {
                "id": "visitor_group_01",
                "type": "person_group",
                "zone": "cooling_zone_01",
                "attributes": {"group_size": 3, "heat_gesture": True},
            }
        ],
        "events": [{"type": "thermal_discomfort_detected", "target": "visitor_group_01", "confidence": 0.88}],
        "affordances": [
            {"action": "spray_mist", "target_zone": "cooling_zone_01", "reason": "降低体感温度"},
            {"action": "deliver_ice_water", "target_zone": "cooling_handoff_01", "reason": "补充清凉服务"},
        ],
        "safety": {"level": "normal", "notes": "允许低速、干运行 G1 动作包。"},
        "semantic_tags": ["hot", "human_hot", "mood_unhappy", "cooling_request"],
        "confidence": 0.9,
        "priority": 0.86,
    }


def build_context(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "latest_scene": frame,
        "recent_runs": [],
        "recent_commands": [],
        "recent_robot_acks": [],
        "recent_device_acks": [],
        "retrieved_memory": [
            {
                "memory_id": "mem_heat_loop_policy",
                "content": "Heat scenes should prefer misting, G1 low-speed ice-water delivery, calm audio, and cool-wave projection.",
                "scenario_id": "heat_cooling_loop",
            }
        ],
        "memory_policy": {
            "short_term": "last scene frames, commands, ACK status",
            "long_term": "scenario policy and execution feedback summaries",
        },
    }


def build_messages(frame: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    system = build_system_prompt()
    user = build_user_payload(frame, context)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_system_prompt() -> str:
    return (
        "You are the Zhichang Tongyu Central Agent inside a Hermes-style agent runtime. "
        "You are not a coding assistant in this evaluation. Physical semantic input is already normalized as SceneSemanticFrame. "
        "Use the provided zhichang_* tools to reason and execute. "
        "For this scene, call tools in a practical linear loop: observe scene, retrieve context, select scene policy, "
        "plan device commands, then emit each planned DeviceCommand. "
        "Do not invent unrelated office/coding tools. Final answer must be compact JSON with scenario_id, command_types, and rationale."
    )


def build_user_payload(frame: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "Run one central-agent turn for the physical scene. Use zhichang tools before final answer.",
        "scene_semantic_frame": frame,
        "runtime_context": context,
        "quality_expectation": {
            "must_use_domain_tools": True,
            "expected_scenario_id": "heat_cooling_loop",
            "expected_tools": [
                "zhichang_observe_scene",
                "zhichang_retrieve_context",
                "zhichang_select_scene_policy",
                "zhichang_plan_device_commands",
                "zhichang_emit_device_command",
            ],
        },
    }


def build_hermes_prompt(frame: dict[str, Any], context: dict[str, Any]) -> str:
    return json.dumps(build_user_payload(frame, context), ensure_ascii=False, indent=2)


def safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def execute_tool(runtime: Any, name: str, args: dict[str, Any]) -> tuple[str, Any]:
    raw = runtime.registry.dispatch(name, args)
    return raw, safe_json_loads(raw)


def extract_command_types(tool_results: list[dict[str, Any]]) -> list[str]:
    command_types: list[str] = []
    for item in tool_results:
        parsed = item.get("parsed_result") or {}
        result = parsed.get("result") if isinstance(parsed, dict) else None
        if item.get("name") == "zhichang_plan_device_commands" and isinstance(result, dict):
            for command in result.get("command_blueprints") or []:
                command_type = ((command.get("command") or {}).get("type"))
                if command_type and command_type not in command_types:
                    command_types.append(command_type)
        if item.get("name") == "zhichang_emit_device_command" and isinstance(result, dict):
            command_type = result.get("command_type")
            if command_type and command_type not in command_types:
                command_types.append(command_type)
    return command_types


def score_result(tool_calls: list[str], command_types: list[str], final_text: str) -> tuple[int, list[str]]:
    expected_tools = [
        "zhichang_observe_scene",
        "zhichang_retrieve_context",
        "zhichang_select_scene_policy",
        "zhichang_plan_device_commands",
        "zhichang_emit_device_command",
    ]
    expected_commands = ["spray.scene", "g1.unitree_sdk_sequence", "speaker.play", "projection.play"]
    notes: list[str] = []
    score = 0
    for name in expected_tools:
        if name in tool_calls:
            score += 1
        else:
            notes.append(f"missing tool: {name}")
    if "heat_cooling_loop" in final_text or "heat_cooling_loop" in json.dumps(command_types):
        score += 1
    else:
        notes.append("final response did not preserve heat_cooling_loop")
    for command_type in expected_commands:
        if command_type in command_types:
            score += 1
        else:
            notes.append(f"missing command type: {command_type}")
    if len(tool_calls) >= 5 and len(command_types) >= 3:
        score += 1
    else:
        notes.append("tool loop did not fully reach physical command emission")
    return min(score, 10), notes


def evaluate_target(target: EvalTarget, runtime: Any, tools: list[dict[str, Any]], request_timeout: float, max_iterations: int) -> dict[str, Any]:
    return evaluate_target_with_hermes_agent(target, request_timeout, max_iterations)


def evaluate_target_with_hermes_agent(target: EvalTarget, request_timeout: float, max_iterations: int) -> dict[str, Any]:
    from run_agent import AIAgent

    frame = semantic_frame_heat()
    context = build_context(frame)
    tool_results: list[dict[str, Any]] = []
    tool_call_names: list[str] = []
    final_text = ""
    status = "unknown"
    error = None

    def tool_start(call_id: str, name: str, args: dict[str, Any]) -> None:
        tool_call_names.append(name)
        tool_results.append(
            {
                "iteration": None,
                "id": call_id,
                "name": name,
                "arguments": args,
                "parsed_result": None,
                "state": "started",
            }
        )

    def tool_complete(call_id: str, name: str, args: dict[str, Any], result: Any) -> None:
        parsed = safe_json_loads(str(result))
        for item in reversed(tool_results):
            if item.get("id") == call_id and item.get("name") == name and item.get("state") == "started":
                item["parsed_result"] = parsed
                item["state"] = "completed"
                break
        else:
            tool_call_names.append(name)
            tool_results.append(
                {
                    "iteration": None,
                    "id": call_id,
                    "name": name,
                    "arguments": args,
                    "parsed_result": parsed,
                    "state": "completed",
                }
            )

    def run_agent() -> str:
        agent = AIAgent(
            provider=target.provider,
            api_key=target.api_key,
            base_url=target.base_url,
            model=target.model,
            max_iterations=max_iterations,
            tool_delay=0,
            enabled_toolsets=["zhichang"],
            quiet_mode=True,
            save_trajectories=False,
            skip_context_files=True,
            skip_memory=False,
            session_id=f"zhichang_eval_{uuid.uuid4().hex[:8]}",
            ephemeral_system_prompt=build_system_prompt(),
            tool_start_callback=tool_start,
            tool_complete_callback=tool_complete,
            max_tokens=1600,
        )
        return agent.chat(build_hermes_prompt(frame, context))

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_agent)
        try:
            final_text = future.result(timeout=request_timeout)
            status = "completed"
        except concurrent.futures.TimeoutError:
            status = "timeout"
            error = f"Timed out after {request_timeout}s"
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            status = "api_error"
            error = f"{type(exc).__name__}: {str(exc)[:1200]}"

    command_types = extract_command_types(tool_results)
    score, notes = score_result(tool_call_names, command_types, final_text)
    if error:
        notes.insert(0, error)
        if not tool_call_names:
            score = 0
    return {
        "target": target.public(),
        "agent_mode": "hermes-agent",
        "status": status,
        "score_10": score,
        "quality_notes": notes[:12],
        "total_latency_sec": round(time.perf_counter() - started, 3),
        "request_latencies_sec": [],
        "api_request_count": None,
        "tool_call_count": len(tool_call_names),
        "tool_calls": tool_call_names,
        "command_types": command_types,
        "final_preview": str(final_text)[:1200],
        "tool_results": tool_results,
    }


def summarize_for_console(result: dict[str, Any]) -> str:
    target = result["target"]
    notes = "; ".join(result.get("quality_notes") or []) or "ok"
    return (
        f"{target['label']} | model={target['model']} | status={result['status']} | "
        f"latency={result['total_latency_sec']}s | score={result['score_10']}/10 | "
        f"tools={result['tool_calls']} | commands={result['command_types']} | notes={notes}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--targets", default="kimi-coding,deepseek-v4-pro,deepseek-v4-flash")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-iterations", type=int, default=7)
    args = parser.parse_args()

    values = read_env(args.env)
    selected = {item.strip() for item in args.targets.split(",") if item.strip()}
    targets = [target for target in build_targets(values) if target.label in selected]

    from zhichang_hermes_runtime import ZhichangHermesRuntime

    runtime = ZhichangHermesRuntime(PROJECT_ROOT)
    if not runtime.available:
        raise RuntimeError(f"Zhichang Hermes runtime unavailable: {runtime.import_error}")
    tools = runtime.tool_defs
    if not tools:
        raise RuntimeError("No zhichang tool definitions available")

    report = {
        "report_id": f"zhichang_model_tool_eval_{uuid.uuid4().hex[:8]}",
        "generated_at": now_cst(),
        "env_path": str(args.env),
        "project_root": str(PROJECT_ROOT),
        "tool_names": [tool["function"]["name"] for tool in tools],
        "results": [],
    }

    print(f"Using env: {args.env}")
    print(f"Registered tools: {report['tool_names']}")
    for target in targets:
        if not target.configured:
            result = {
                "target": target.public(),
                "status": "not_configured",
                "score_10": 0,
                "quality_notes": ["missing api key, base url, or model"],
                "total_latency_sec": 0,
                "request_latencies_sec": [],
                "api_request_count": 0,
                "tool_call_count": 0,
                "tool_calls": [],
                "command_types": [],
                "final_preview": "",
                "tool_results": [],
            }
        else:
            print(f"Testing {target.label} / {target.model} ...", flush=True)
            result = evaluate_target(target, runtime, tools, args.timeout, args.max_iterations)
        report["results"].append(result)
        print(summarize_for_console(result), flush=True)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{report['report_id']}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
