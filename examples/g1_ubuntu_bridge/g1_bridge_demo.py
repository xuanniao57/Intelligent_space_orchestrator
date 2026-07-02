#!/usr/bin/env python3
"""Minimal Unitree G1 bridge demo for Tongyu central hub integration.

This script intentionally uses only the Python standard library so it can run
on a fresh Ubuntu robot computer before the real Unitree SDK adapter is ready.
It receives Tongyu DeviceCommand JSON, dry-runs each sdk_sequence step, and
posts an ACK back to the central hub.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


LOG = logging.getLogger("g1_bridge_demo")
TARGET_ID = "unitree_g1"
TARGET_TYPE = "robot"
COMMAND_TYPE = "g1.unitree_sdk_sequence"


class BridgeState:
    def __init__(self, *, hub_url: str, dry_run: bool, register: bool, network_interface: str) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.dry_run = dry_run
        self.register = register
        self.network_interface = network_interface
        self.started_at = time.time()
        self.command_count = 0
        self.last_command: dict[str, Any] | None = None
        self.last_ack: dict[str, Any] | None = None
        self.arm_client: Any | None = None
        self.action_map: dict[str, Any] | None = None


def post_json(url: str, payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        if not body:
            return {"status_code": response.status}
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            result = {"body": body}
        result.setdefault("status_code", response.status)
        return result


def make_ack(
    payload: dict[str, Any],
    *,
    status: str,
    stage: str,
    progress: float,
    executed_steps: list[str],
    error: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    command = payload.get("command") or {}
    params = command.get("params") or {}
    ack = {
        "message_id": payload.get("message_id"),
        "task_id": params.get("task_id"),
        "target_id": payload.get("target_id", TARGET_ID),
        "target_type": payload.get("target_type", TARGET_TYPE),
        "status": status,
        "stage": stage,
        "progress": progress,
        "executed_steps": executed_steps,
        "simulated": dry_run,
        "device_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "telemetry": {
            "executor": "g1_ubuntu_bridge_demo",
            "control_mode": "dry_run" if dry_run else "unitree_sdk2_adapter",
            "network_interface": payload.get("network_interface"),
            "sdk_step_count": len(params.get("sdk_sequence") or []),
        },
    }
    if error:
        ack["error"] = error
    return ack


def ensure_arm_client(state: BridgeState):
    if state.arm_client is not None:
        return state.arm_client, state.action_map or {}
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient, action_map

    ChannelFactoryInitialize(0, state.network_interface)
    client = G1ArmActionClient()
    client.SetTimeout(10.0)
    client.Init()
    state.arm_client = client
    state.action_map = action_map
    return client, action_map


def execute_sdk_step(step: dict[str, Any], state: BridgeState) -> str:
    """Dispatch one Tongyu SDK step.

    Replace the TODO blocks with real Unitree SDK calls on the robot computer.
    The central hub contract stays the same.
    """
    source = str(step.get("source_primitive") or step.get("primitive") or "unknown")
    client = str(step.get("client") or "")
    method = str(step.get("method") or "")
    args = step.get("args") or {}
    LOG.info("step=%s source=%s client=%s method=%s args=%s", step.get("seq") or step.get("step"), source, client, method, args)

    if source == "sleep" or method.lower() == "sleep":
        seconds = float(args.get("seconds", 0.5))
        time.sleep(max(0.0, min(seconds, 10.0)))
        return source

    if state.dry_run:
        return source

    if client == "SafetyGuard" and method == "CheckPreconditions":
        # Check debug mode, emergency stop, battery, human distance, and floor clearance.
        return source
    if client in {"AudioClient", "SpeechAdapter"} and method in {"TtsMaker", "Speak"}:
        # Example: Unitree audio/TTS client speaks args["text_cn"].
        return source
    if client in {"LocoClient", "SportClient"}:
        # Example: high-level velocity or waypoint movement.
        return source
    if client == "G1ArmActionClient" and method == "ExecuteAction":
        arm_client, action_map = ensure_arm_client(state)
        action_name = str(args.get("action_name") or args.get("action_map_key") or "").strip()
        action_id = args.get("action_id")
        sdk_action = action_map.get(action_name) if action_name else None
        if sdk_action is None:
            sdk_action = int(action_id)
        arm_client.ExecuteAction(sdk_action)
        return source
    if client == "FeedbackAdapter" and method == "ReportReady":
        return source

    LOG.warning("unknown real-sdk step, leaving as no-op: %s.%s", client, method)
    return source


def execute_command(payload: dict[str, Any], state: BridgeState) -> tuple[dict[str, Any], int]:
    command = payload.get("command")
    if not isinstance(command, dict):
        return {"error": "payload.command must be an object"}, 400
    if command.get("type") != COMMAND_TYPE:
        return {"error": f"unsupported command.type: {command.get('type')}"}, 400
    if payload.get("target_id", TARGET_ID) != TARGET_ID:
        return {"error": f"unsupported target_id: {payload.get('target_id')}"}, 400

    params = command.get("params") or {}
    sdk_sequence = params.get("sdk_sequence") or []
    if not isinstance(sdk_sequence, list):
        return {"error": "payload.command.params.sdk_sequence must be a list"}, 400

    state.command_count += 1
    state.last_command = payload
    executed_steps: list[str] = []

    try:
        for step in sdk_sequence:
            if not isinstance(step, dict):
                raise ValueError(f"invalid sdk step: {step!r}")
            executed_steps.append(execute_sdk_step(step, state))
        ack = make_ack(
            payload,
            status="ok",
            stage="report_ready",
            progress=1.0,
            executed_steps=executed_steps,
            dry_run=state.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - bridge must report failures to hub.
        LOG.exception("failed to execute command")
        ack = make_ack(
            payload,
            status="failed",
            stage="bridge_error",
            progress=0.0,
            executed_steps=executed_steps,
            error=str(exc),
            dry_run=state.dry_run,
        )

    ack_url = f"{state.hub_url}/api/robot/ack"
    try:
        ack_result = post_json(ack_url, ack)
        LOG.info("ACK posted to %s: %s", ack_url, ack_result)
    except (urllib.error.URLError, TimeoutError) as exc:
        ack_result = {"status": "failed", "error": str(exc)}
        LOG.warning("failed to post ACK to %s: %s", ack_url, exc)

    state.last_ack = ack
    return {
        "status": "accepted",
        "dry_run": state.dry_run,
        "message_id": payload.get("message_id"),
        "task_id": params.get("task_id"),
        "executed_steps": executed_steps,
        "ack": ack,
        "final_ack": ack,
        "ack_post_result": ack_result,
    }, 200


def make_handler(state: BridgeState) -> type[BaseHTTPRequestHandler]:
    class G1BridgeHandler(BaseHTTPRequestHandler):
        server_version = "TongyuG1BridgeDemo/0.1"

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            if self.path == "/health":
                self._send_json(
                    {
                        "status": "ok",
                        "service": "tongyu-g1-ubuntu-bridge-demo",
                        "target_id": TARGET_ID,
                        "command_type": COMMAND_TYPE,
                        "dry_run": state.dry_run,
                        "hub_url": state.hub_url,
                        "network_interface": state.network_interface,
                        "command_count": state.command_count,
                        "uptime_sec": round(time.time() - state.started_at, 2),
                    }
                )
                return
            if self.path == "/last":
                self._send_json({"last_command": state.last_command, "last_ack": state.last_ack})
                return
            self._send_json({"error": "not found", "path": self.path}, 404)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            if self.path != "/api/g1/execute":
                self._send_json({"error": "not found", "path": self.path}, 404)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"invalid json: {exc}"}, 400)
                return
            result, status = execute_command(payload, state)
            self._send_json(result, status)

        def log_message(self, fmt: str, *args: Any) -> None:
            LOG.info("%s - %s", self.address_string(), fmt % args)

    return G1BridgeHandler


def register_device(state: BridgeState, *, host_ip: str, port: int) -> None:
    payload = {
        "target_id": TARGET_ID,
        "target_type": TARGET_TYPE,
        "client_id": "g1_ubuntu_01",
        "ip": host_ip,
        "port": port,
        "transport": "http_push",
        "capabilities": [COMMAND_TYPE],
        "status": "online",
    }
    try:
        result = post_json(f"{state.hub_url}/api/devices/register", payload)
        LOG.info("registered to hub: %s", result)
    except Exception as exc:  # noqa: BLE001 - startup can continue without registry.
        LOG.warning("device register failed: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tongyu Unitree G1 Ubuntu bridge demo")
    parser.add_argument("--host", default="0.0.0.0", help="bind host, default 0.0.0.0")
    parser.add_argument("--port", type=int, default=8731, help="bind port, default 8731")
    parser.add_argument("--hub-url", default="http://192.168.1.50:8798", help="central hub base URL")
    parser.add_argument("--host-ip", default="192.168.1.172", help="Ubuntu LAN IP for optional hub registration")
    parser.add_argument("--network-interface", default="eth0", help="Unitree SDK network interface on PC2, used with --real-sdk")
    parser.add_argument("--real-sdk", action="store_true", help="disable dry-run placeholders and enter SDK adapter hooks")
    parser.add_argument("--register", action="store_true", help="register this robot bridge to central hub on startup")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = BridgeState(hub_url=args.hub_url, dry_run=not args.real_sdk, register=args.register, network_interface=args.network_interface)
    if args.register:
        register_device(state, host_ip=args.host_ip, port=args.port)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    LOG.info("G1 bridge listening on http://%s:%s dry_run=%s hub=%s", args.host, args.port, state.dry_run, state.hub_url)
    LOG.info("health: curl http://127.0.0.1:%s/health", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
