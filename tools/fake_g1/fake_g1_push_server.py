#!/usr/bin/env python3
"""Push-mode fake Unitree G1 receiver for Tongyu hub integration tests.

This process runs on the "robot-side computer" (WSL2 in the lab test).  It
accepts JSON DeviceCommand payloads over HTTP, maps high-level scene primitives
to a Unitree-SDK-style execution sequence, simulates the execution, and posts
ACK/progress back to the Tongyu central hub.

It is not a low-level Unitree DDS simulator.  It is a protocol-level stand-in
for the onboard bridge that the robot teammate will later replace with real
Unitree SDK calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CST = timezone(timedelta(hours=8))
ACK_HISTORY: List[Dict[str, Any]] = []
TASK_HISTORY: List[Dict[str, Any]] = []


def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def stable_message_id(prefix: str = "g1push") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def sha256_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def http_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 8.0) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error {url}: {exc.reason}") from exc


def post_ack_to_hub(hub_url: str, ack: Dict[str, Any], enabled: bool) -> Dict[str, Any]:
    if not enabled or not hub_url:
        return {"status": "skipped"}
    return http_json("POST", f"{hub_url.rstrip('/')}/api/robot/ack", ack)


def normalize_device_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Accept either a DeviceCommand or a compact command body."""
    if payload.get("message_type") == "device_command":
        return payload

    if payload.get("command") and isinstance(payload["command"], dict):
        body = payload["command"]
    elif payload.get("type"):
        body = payload
    else:
        body = {
            "type": "g1.unitree_sdk_sequence",
            "params": payload,
        }

    return {
        "message_type": "device_command",
        "message_id": payload.get("message_id", stable_message_id()),
        "timestamp": payload.get("timestamp", now_cst()),
        "source_id": payload.get("source_id", "control_hub"),
        "target_id": payload.get("target_id", "unitree_g1"),
        "target_type": payload.get("target_type", "robot"),
        "verb": "command",
        "command": body,
        "routing": payload.get("routing", {}),
        "ack_required": payload.get("ack_required", True),
        "timeout_ms": payload.get("timeout_ms", 60000),
    }


def sdk_call(seq: int, layer: str, client: str, method: str, args: Dict[str, Any], *, note: str, source: str) -> Dict[str, Any]:
    return {
        "seq": seq,
        "primitive": "unitree_sdk_call",
        "source_primitive": source,
        "layer": layer,
        "client": client,
        "method": method,
        "args": args,
        "note": note,
    }


def primitive_to_sdk_step(primitive: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """Map Tongyu scene primitives to an SDK-adapter-shaped dry-run call.

    The method names are intentionally adapter-facing, not a promise that every
    call exists verbatim in Unitree's SDK.  Robot teammates should map these to
    their chosen Unitree SDK2 / ROS2 implementation.
    """
    seq = int(primitive.get("seq", 1))
    name = primitive.get("primitive", "unknown")

    if name == "navigate":
        target = primitive.get("target") or task.get("station_id") or "unknown_target"
        return sdk_call(
            seq,
            "unitree_high_level",
            "LocoClient",
            "SetVelocity",
            {
                "target": target,
                "speed_limit_mps": task.get("safety", {}).get("speed_limit_mps", 0.25),
                "min_human_distance_m": task.get("safety", {}).get("min_human_distance_m", 0.8),
                "dry_run_velocity_hint": {"vx": 0.12, "vy": 0.0, "omega": 0.0, "duration": 1.0},
            },
            note="Real bridge should translate target waypoint to safe high-level locomotion.",
            source=name,
        )
    if name == "speak":
        return sdk_call(
            seq,
            "onboard_io",
            "AudioClient",
            "TtsMaker",
            {"text_cn": primitive.get("text_cn") or task.get("speech_cn") or "", "speaker_id": 0},
            note="Use onboard speaker/TTS if available; otherwise log or forward to external speaker.",
            source=name,
        )
    if name == "prepare_recipe":
        return sdk_call(
            seq,
            "station_tool",
            "StationToolAdapter",
            "PrepareItem",
            {
                "recipe_id": primitive.get("recipe_id") or (task.get("recipe") or {}).get("recipe_id"),
                "ingredients": primitive.get("ingredients") or (task.get("recipe") or {}).get("ingredients", []),
                "station_id": task.get("station_id"),
            },
            note="For real G1, keep station actions guarded; station may be button-style or human-supervised.",
            source=name,
        )
    if name == "assemble_light_meal":
        return sdk_call(
            seq,
            "station_tool",
            "LightMealAdapter",
            "Assemble",
            {"name_cn": primitive.get("name_cn"), "ingredients": primitive.get("ingredients", [])},
            note="Optional light-meal station adapter.",
            source=name,
        )
    if name == "seal_and_label":
        return sdk_call(
            seq,
            "station_tool",
            "StationToolAdapter",
            "SealAndLabel",
            {"label_cn": primitive.get("label_cn") or (task.get("recipe") or {}).get("name_cn")},
            note="Can be replaced by screen/voice feedback during early real-robot tests.",
            source=name,
        )
    if name == "handoff":
        return sdk_call(
            seq,
            "unitree_high_level",
            "LocoClient",
            "SetVelocity",
            {
                "target": primitive.get("target") or task.get("handoff_zone"),
                "speed_limit_mps": task.get("safety", {}).get("speed_limit_mps", 0.25),
                "dry_run_velocity_hint": {"vx": 0.0, "vy": 0.0, "omega": 0.0, "duration": 1.0},
                "handoff_text_cn": primitive.get("text_cn", ""),
            },
            note="Move or orient toward handoff zone; real bridge may only speak during safe dry-run.",
            source=name,
        )
    return sdk_call(
        seq,
        "bridge",
        "UnknownPrimitiveAdapter",
        "LogOnly",
        {"primitive": primitive},
        note="Unknown primitive. Fake G1 logs it; real bridge should reject or map explicitly.",
        source=name,
    )


def command_to_task(command: Dict[str, Any]) -> Dict[str, Any]:
    body = command.get("command") or {}
    command_type = body.get("type", "g1.unitree_sdk_sequence")
    params = body.get("params") or {}
    message_id = command.get("message_id") or stable_message_id()

    base = {
        "message_id": message_id,
        "task_id": params.get("task_id", message_id),
        "command_type": command_type,
        "speech_cn": params.get("speech_cn", ""),
        "station_id": params.get("station_id"),
        "handoff_zone": params.get("handoff_zone"),
        "safety": params.get("unitree_g1_profile") or params.get("safety") or {},
        "recipe": params.get("recipe") or {},
        "space_state": params.get("space_state") or {},
        "source_command": command,
    }

    if command_type == "g1.unitree_sdk_sequence":
        sdk_sequence = params.get("sdk_sequence") or params.get("steps") or []
        base["task_type"] = "unitree_sdk_sequence"
        base["sdk_sequence"] = sdk_sequence
        return base

    if command_type == "g1.motion_primitive":
        primitives = params.get("steps", [])
        base["task_type"] = "motion_primitive"
        base["primitives"] = primitives
        base["sdk_sequence"] = [primitive_to_sdk_step(step, base) for step in primitives]
        return base

    if command_type == "g1.action":
        primitive = {
            "seq": 1,
            "primitive": params.get("action", "legacy_action"),
            "text_cn": params.get("speech"),
            "raw_params": params,
        }
        base["task_type"] = "legacy_g1_action"
        base["primitives"] = [primitive]
        base["sdk_sequence"] = [primitive_to_sdk_step(primitive, base)]
        return base

    base["task_type"] = "unknown_command"
    base["sdk_sequence"] = [
        sdk_call(
            1,
            "bridge",
            "UnknownCommandAdapter",
            "LogOnly",
            {"command_type": command_type, "params": params},
            note="Unknown command type. Fake G1 logs it; real bridge should reject or map explicitly.",
            source="unknown_command",
        )
    ]
    return base


def ack_payload(
    task: Dict[str, Any],
    *,
    status: str,
    stage: str,
    progress: float,
    executed_steps: List[str],
    simulated: bool,
    sdk_trace: List[Dict[str, Any]],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "message_id": task.get("message_id"),
        "task_id": task.get("task_id"),
        "target_id": "unitree_g1",
        "status": status,
        "stage": stage,
        "progress": round(progress, 3),
        "executed_steps": executed_steps,
        "device_time": now_cst(),
        "error": error,
        "simulated": simulated,
        "telemetry": {
            "executor": "fake_g1_push_server",
            "host": socket.gethostname(),
            "control_mode": "unitree_sdk_protocol_simulation",
            "battery": 0.82,
            "nearest_human_distance_m": 1.2,
            "sdk_trace": sdk_trace,
            "feedback_schema_version": "tongyu.g1.ack.v1",
        },
    }


def execute_sdk_step(step: Dict[str, Any], delay_sec: float) -> Tuple[str, Dict[str, Any]]:
    seq = step.get("seq", "?")
    primitive = step.get("primitive", "unitree_sdk_call")
    layer = step.get("layer", "bridge")
    client = step.get("client", "Adapter")
    method = step.get("method", "Run")
    args = step.get("args", {})
    stage = step.get("source_primitive") or primitive
    trace = {
        "seq": seq,
        "stage": stage,
        "sdk_call": f"{layer}.{client}.{method}",
        "args": args,
        "sim_result": "ok",
    }
    print(f"[{now_cst()}] sdk step {seq}: {trace['sdk_call']} args={json.dumps(args, ensure_ascii=False)}", flush=True)
    time.sleep(delay_sec)
    return str(stage), trace


def execute_task(task: Dict[str, Any], hub_url: str, post_ack: bool, step_delay: float) -> Dict[str, Any]:
    sdk_sequence = task.get("sdk_sequence") or []
    if not sdk_sequence:
        sdk_sequence = [
            sdk_call(
                1,
                "bridge",
                "EmptyTaskAdapter",
                "Noop",
                {},
                note="No sdk_sequence was provided.",
                source="noop",
            )
        ]

    print("=" * 78, flush=True)
    print(f"[{now_cst()}] accepted command message_id={task.get('message_id')} type={task.get('command_type')}", flush=True)
    if task.get("speech_cn"):
        print(f"speech={task.get('speech_cn')}", flush=True)
    if task.get("recipe"):
        print(f"recipe={(task.get('recipe') or {}).get('name_cn')} id={(task.get('recipe') or {}).get('recipe_id')}", flush=True)

    acks: List[Dict[str, Any]] = []
    sdk_trace: List[Dict[str, Any]] = []
    executed: List[str] = []

    first_ack = ack_payload(
        task,
        status="accepted",
        stage="accepted",
        progress=0.0,
        executed_steps=executed,
        simulated=True,
        sdk_trace=sdk_trace,
    )
    acks.append(first_ack)
    ACK_HISTORY.append(first_ack)
    post_ack_to_hub(hub_url, first_ack, post_ack)

    total = max(len(sdk_sequence), 1)
    for index, step in enumerate(sdk_sequence, start=1):
        stage = step.get("source_primitive") or step.get("primitive", "sdk_step")
        running_ack = ack_payload(
            task,
            status="running",
            stage=str(stage),
            progress=(index - 1) / total,
            executed_steps=executed,
            simulated=True,
            sdk_trace=sdk_trace,
        )
        acks.append(running_ack)
        ACK_HISTORY.append(running_ack)
        post_ack_to_hub(hub_url, running_ack, post_ack)
        executed_stage, trace = execute_sdk_step(step, step_delay)
        executed.append(executed_stage)
        sdk_trace.append(trace)

    final_ack = ack_payload(
        task,
        status="ok",
        stage=executed[-1] if executed else "done",
        progress=1.0,
        executed_steps=executed,
        simulated=True,
        sdk_trace=sdk_trace,
    )
    acks.append(final_ack)
    ACK_HISTORY.append(final_ack)
    hub_response = post_ack_to_hub(hub_url, final_ack, post_ack)
    print(f"[{now_cst()}] final ACK status=ok hub_response={hub_response.get('status')}", flush=True)
    return {"acks": acks, "final_ack": final_ack, "sdk_trace": sdk_trace, "hub_response": hub_response}


class FakeG1Handler(BaseHTTPRequestHandler):
    server_version = "TongyuFakeG1/0.2"

    def _json_response(self, payload: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{now_cst()}] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._json_response({
                "status": "ok",
                "service": "tongyu-fake-g1-push-server",
                "host": socket.gethostname(),
                "endpoints": ["/health", "/api/g1/execute", "/api/g1/ack/history", "/api/g1/last"],
                "hub_url": self.server.hub_url,  # type: ignore[attr-defined]
                "post_ack": self.server.post_ack,  # type: ignore[attr-defined]
            })
            return
        if self.path.startswith("/api/g1/ack/history"):
            limit = 50
            self._json_response({"acks": ACK_HISTORY[-limit:], "total": len(ACK_HISTORY)})
            return
        if self.path.startswith("/api/g1/last"):
            self._json_response({"tasks": TASK_HISTORY[-5:], "acks": ACK_HISTORY[-10:]})
            return
        self._json_response({"error": "not_found", "path": self.path}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if not (self.path.startswith("/api/g1/execute") or self.path.startswith("/unitree/execute")):
            self._json_response({"error": "not_found", "path": self.path}, status=404)
            return

        try:
            payload = self._read_json()
            command = normalize_device_command(payload)
            task = command_to_task(command)
            task["received_json_sha256"] = sha256_json(command)
            TASK_HISTORY.append(task)
            result = execute_task(
                task,
                hub_url=self.server.hub_url,  # type: ignore[attr-defined]
                post_ack=self.server.post_ack,  # type: ignore[attr-defined]
                step_delay=self.server.step_delay,  # type: ignore[attr-defined]
            )
            self._json_response({
                "status": "ok",
                "received_at": now_cst(),
                "task": {
                    "message_id": task.get("message_id"),
                    "task_id": task.get("task_id"),
                    "command_type": task.get("command_type"),
                    "sdk_sequence": task.get("sdk_sequence"),
                    "received_json_sha256": task.get("received_json_sha256"),
                },
                "final_ack": result["final_ack"],
                "ack_count": len(result["acks"]),
            })
        except Exception as exc:  # Keep the fake receiver friendly during lab tests.
            print(f"[ERROR] execute failed: {exc}", file=sys.stderr, flush=True)
            self._json_response({"status": "error", "error": str(exc), "time": now_cst()}, status=500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Push-mode fake G1 HTTP receiver")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host")
    parser.add_argument("--port", type=int, default=8731, help="Listen port")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8798", help="Tongyu central hub URL for ACK POST")
    parser.add_argument("--step-delay", type=float, default=0.4, help="Delay per simulated SDK step")
    parser.add_argument("--post-ack", action="store_true", default=True, help="POST ACK/progress to hub")
    parser.add_argument("--no-post-ack", action="store_false", dest="post_ack", help="Do not POST ACK/progress to hub")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), FakeG1Handler)
    server.hub_url = args.hub_url  # type: ignore[attr-defined]
    server.post_ack = args.post_ack  # type: ignore[attr-defined]
    server.step_delay = args.step_delay  # type: ignore[attr-defined]

    print(f"Fake G1 push server listening on http://{args.host}:{args.port}", flush=True)
    print(f"Hub ACK target: {args.hub_url} post_ack={args.post_ack}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Interrupted", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
