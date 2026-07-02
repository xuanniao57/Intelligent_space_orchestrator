#!/usr/bin/env python3
"""Tongyu Robot Unified Gateway

Run this on the robot Ubuntu host.  It exposes one stable HTTP interface for
central-hub commands and dispatches them to local robot programs such as:
- Unitree arm/action UDP receiver
- TTS UDP receiver or one-shot TTS binary
- Navigation goal sender
- Camera/video relay process
- Microphone/environment-audio relay process
- ASR/text relay process

The script uses only Python standard library modules.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LOG = logging.getLogger("tongyu_robot_gateway")

PROTOCOL = "tongyu.robot.unified.v1"
DEFAULT_TARGET_ID = "unitree_g1"
DEFAULT_TARGET_TYPE = "robot"
OLD_COMMAND_TYPE = "g1.unitree_sdk_sequence"


DEFAULT_CONFIG: dict[str, Any] = {
    "target_id": DEFAULT_TARGET_ID,
    "target_type": DEFAULT_TARGET_TYPE,
    "client_id": "g1_ubuntu_01",
    "hub_url": "http://192.168.1.50:8798",
    "hub_ip": "192.168.1.50",
    "ack_path": "/api/robot/ack",
    "register_path": "/api/devices/register",
    "host_ip": "192.168.1.172",
    "port": 8731,
    "network_interface": "eth0",
    "log_dir": "./tongyu_gateway_logs",
    "request_timeout_sec": 8.0,
    "stop_timeout_sec": 3.0,
    "env": {},
    "services": {
        # Long-running helper programs.  Edit paths to match your robot host.
        "tts_udp_receiver": {
            "description": "Receive UDP text on 127.0.0.1:7000 and call Unitree TTS.",
            "cmd": [
                "python3",
                "/home/unitree/code/udp_receive_call_tts.py",
                "--port",
                "7000",
                "--tts-bin",
                "/home/unitree/code/g1_tts_once",
                "--network-interface",
                "{network_interface}",
            ],
            "cwd": "/home/unitree/code",
            "autostart": False,
        },
        "arm_udp_receiver": {
            "description": "Receive UDP arm action packets on 127.0.0.1:8888 and call G1ArmActionClient.",
            "cmd": [
                "/home/unitree/code/g1_arm_action_example_udp_eth0",
                "{network_interface}",
                "8888",
            ],
            "cwd": "/home/unitree/code",
            "autostart": False,
        },
        "nav_node": {
            "description": "Optional long-running navigation node / waypoint follower.",
            "cmd": ["python3", "/home/unitree/code/humanoid_waypoint_follower.py"],
            "cwd": "/home/unitree/code",
            "autostart": False,
        },
        "video_relay": {
            "description": "Robot camera video relay back to central hub.",
            "cmd": [
                "python3",
                "/home/unitree/code/camera_forward_to_hub.py",
                "--dst-ip",
                "{hub_ip}",
                "--dst-port",
                "5005",
                "--fps",
                "5",
                "--ttl-sec",
                "{ttl_sec}",
            ],
            "cwd": "/home/unitree/code",
            "autostart": False,
            "ttl_sec": 600,
        },
        "mic_relay": {
            "description": "Forward G1 multicast microphone PCM to the central hub.",
            "cmd": [
                "/home/unitree/code/g1_mic_forward_tcp",
                "--dst-ip",
                "{hub_ip}",
                "--dst-port",
                "6000",
                "--network-interface",
                "{network_interface}",
                "--ttl-sec",
                "{ttl_sec}",
            ],
            "cwd": "/home/unitree/code",
            "autostart": False,
            "ttl_sec": 600,
        },
        "asr_relay": {
            "description": "Subscribe/recognize dialogue speech and post text back to central hub.",
            "cmd": [
                "python3",
                "/home/unitree/code/asr_relay_to_hub.py",
                "--hub-url",
                "{hub_url}",
                "--network-interface",
                "{network_interface}",
            ],
            "cwd": "/home/unitree/code",
            "autostart": False,
            "ttl_sec": 600,
        },
    },
    "routes": {
        # One-shot / short commands.
        "speech.speak": {
            "handler": "udp",
            "description": "Speak text through the local TTS receiver.",
            "ensure_service": "tts_udp_receiver",
            "host": "127.0.0.1",
            "port": 7000,
            "payload": "{text}",
        },
        "motion.arm_action": {
            "handler": "udp",
            "description": "Execute Unitree G1 arm action by id/name/stop packet.",
            "ensure_service": "arm_udp_receiver",
            "host": "127.0.0.1",
            "port": 8888,
            "payload": "{action_packet}",
        },
        "navigation.goto": {
            "handler": "subprocess_once",
            "description": "Send one navigation target to your navigation program.",
            "cmd": [
                "python3",
                "/home/unitree/code/nav_send_goal.py",
                "--x",
                "{x}",
                "--y",
                "{y}",
                "--yaw",
                "{yaw}",
                "--frame",
                "{frame}",
            ],
            "cwd": "/home/unitree/code",
            "timeout_sec": 10.0,
        },
        # Managed services.
        "video.start": {"handler": "service_start", "service": "video_relay", "default_params": {"ttl_sec": 600}},
        "video.stop": {"handler": "service_stop", "service": "video_relay"},
        "video.status": {"handler": "service_status", "service": "video_relay"},
        "audio.mic_start": {"handler": "service_start", "service": "mic_relay", "default_params": {"ttl_sec": 600}},
        "audio.mic_stop": {"handler": "service_stop", "service": "mic_relay"},
        "audio.mic_status": {"handler": "service_status", "service": "mic_relay"},
        "asr.start": {"handler": "service_start", "service": "asr_relay", "default_params": {"ttl_sec": 600}},
        "asr.stop": {"handler": "service_stop", "service": "asr_relay"},
        "asr.status": {"handler": "service_status", "service": "asr_relay"},
        "service.start": {"handler": "service_start", "service": "{service}"},
        "service.stop": {"handler": "service_stop", "service": "{service}"},
        "service.status": {"handler": "service_status", "service": "{service}"},
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return value.format_map(SafeDict(ctx))
    if isinstance(value, list):
        return [str(render_template(v, ctx)) for v in value]
    if isinstance(value, dict):
        return {k: render_template(v, ctx) for k, v in value.items()}
    return value


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


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


def load_config(config_path: str | None) -> dict[str, Any]:
    config = DEFAULT_CONFIG
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config = deep_merge(DEFAULT_CONFIG, user_config)
    return config


@dataclass
class ManagedProcess:
    service: str
    cmd: list[str]
    popen: subprocess.Popen[Any]
    started_at: float
    stdout_path: str
    stderr_path: str
    cwd: str | None = None
    session_id: str | None = None
    expires_at: float | None = None

    def status(self) -> dict[str, Any]:
        rc = self.popen.poll()
        now = time.time()
        return {
            "service": self.service,
            "running": rc is None,
            "pid": self.popen.pid,
            "returncode": rc,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.started_at)),
            "uptime_sec": round(time.time() - self.started_at, 2) if rc is None else None,
            "session_id": self.session_id,
            "expires_at": None if self.expires_at is None else time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.expires_at)),
            "remaining_sec": None if self.expires_at is None or rc is not None else max(0, round(self.expires_at - now, 2)),
            "cmd": self.cmd,
            "cwd": self.cwd,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }


@dataclass
class GatewayState:
    config: dict[str, Any]
    token: str | None = None
    dry_run: bool = False
    started_at: float = field(default_factory=time.time)
    lock: threading.RLock = field(default_factory=threading.RLock)
    processes: dict[str, ManagedProcess] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    command_count: int = 0
    last_command: dict[str, Any] | None = None
    last_ack: dict[str, Any] | None = None
    stop_supervisor: bool = False

    @property
    def log_dir(self) -> Path:
        p = Path(str(self.config.get("log_dir") or "./tongyu_gateway_logs")).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def base_context(self) -> dict[str, Any]:
        return {
            "target_id": self.config.get("target_id", DEFAULT_TARGET_ID),
            "target_type": self.config.get("target_type", DEFAULT_TARGET_TYPE),
            "client_id": self.config.get("client_id", "g1_ubuntu_01"),
            "hub_url": self.config.get("hub_url", ""),
            "hub_ip": self.config.get("hub_ip", ""),
            "host_ip": self.config.get("host_ip", ""),
            "network_interface": self.config.get("network_interface", "eth0"),
            "port": self.config.get("port", 8731),
        }

    def remember(self, record: dict[str, Any]) -> None:
        with self.lock:
            self.history.append(record)
            self.history = self.history[-50:]

    def all_process_status(self) -> dict[str, Any]:
        with self.lock:
            configured = set((self.config.get("services") or {}).keys())
            running = set(self.processes.keys())
            return {
                name: self.service_status(name)
                for name in sorted(configured | running)
            }

    def service_status(self, service: str) -> dict[str, Any]:
        with self.lock:
            mp = self.processes.get(service)
            service_cfg = (self.config.get("services") or {}).get(service)
            if mp is None:
                return {
                    "service": service,
                    "configured": service_cfg is not None,
                    "running": False,
                    "description": (service_cfg or {}).get("description"),
                }
            status = mp.status()
            if status["running"] is False:
                # Keep one status result, then remove stale handle.
                self.processes.pop(service, None)
            status["configured"] = service_cfg is not None
            status["description"] = (service_cfg or {}).get("description")
            return status

    def start_service(self, service: str, params: dict[str, Any] | None = None, *, restart: bool = False) -> dict[str, Any]:
        params = params or {}
        with self.lock:
            old = self.processes.get(service)
            if old and old.popen.poll() is None and not restart:
                return {"status": "already_running", **old.status()}
            if old and old.popen.poll() is None and restart:
                self.stop_service(service)

            service_cfg = (self.config.get("services") or {}).get(service)
            if not service_cfg:
                raise ValueError(f"unknown service: {service}")

            ctx = {**self.base_context(), **params, "service": service}
            cmd = render_template(service_cfg.get("cmd") or [], ctx)
            if not cmd:
                raise ValueError(f"service {service} has empty cmd")
            cwd = render_template(service_cfg.get("cwd"), ctx) if service_cfg.get("cwd") else None
            env = os.environ.copy()
            env.update({str(k): str(render_template(v, ctx)) for k, v in (self.config.get("env") or {}).items()})
            env.update({str(k): str(render_template(v, ctx)) for k, v in (service_cfg.get("env") or {}).items()})

            stdout_path = str(self.log_dir / f"{service}.stdout.log")
            stderr_path = str(self.log_dir / f"{service}.stderr.log")
            if self.dry_run:
                return {
                    "status": "dry_run",
                    "service": service,
                    "cmd": cmd,
                    "cwd": cwd,
                    "stdout_path": stdout_path,
                    "stderr_path": stderr_path,
                }

            ttl = params.get("ttl_sec", service_cfg.get("ttl_sec"))
            ttl_sec = None if ttl in (None, "", 0, "0") else max(1, int(float(ttl)))
            session_id = str(params.get("session_id") or f"{service}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}")
            stdout_f = open(stdout_path, "ab", buffering=0)
            stderr_f = open(stderr_path, "ab", buffering=0)
            popen = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=stdout_f,
                stderr=stderr_f,
                start_new_session=True,
            )
            mp = ManagedProcess(
                service=service,
                cmd=cmd,
                cwd=cwd,
                popen=popen,
                started_at=time.time(),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                session_id=session_id,
                expires_at=None if ttl_sec is None else time.time() + ttl_sec,
            )
            self.processes[service] = mp
            return {"status": "started", **mp.status()}

    def stop_service(self, service: str) -> dict[str, Any]:
        timeout = float(self.config.get("stop_timeout_sec") or 3.0)
        with self.lock:
            mp = self.processes.get(service)
            if not mp:
                return {"status": "not_running", "service": service}
            if mp.popen.poll() is not None:
                self.processes.pop(service, None)
                return {"status": "already_exited", **mp.status()}
            if self.dry_run:
                return {"status": "dry_run_stop", "service": service, "pid": mp.popen.pid}
            try:
                os.killpg(os.getpgid(mp.popen.pid), signal.SIGINT)
                try:
                    mp.popen.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(mp.popen.pid), signal.SIGTERM)
                    try:
                        mp.popen.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        os.killpg(os.getpgid(mp.popen.pid), signal.SIGKILL)
                        mp.popen.wait(timeout=timeout)
            finally:
                status = mp.status()
                self.processes.pop(service, None)
            return {"status": "stopped", **status}

    def stop_expired_services(self) -> list[dict[str, Any]]:
        expired: list[str] = []
        now = time.time()
        with self.lock:
            for service, mp in list(self.processes.items()):
                if mp.expires_at is not None and mp.popen.poll() is None and now >= mp.expires_at:
                    expired.append(service)
        stopped: list[dict[str, Any]] = []
        for service in expired:
            LOG.info("auto-stopping expired service=%s", service)
            stopped.append(self.stop_service(service))
        return stopped


def send_udp(host: str, port: int, payload: str | bytes, *, timeout: float = 2.0) -> dict[str, Any]:
    data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sent = sock.sendto(data, (host, int(port)))
    return {"status": "sent", "transport": "udp", "host": host, "port": int(port), "bytes": sent, "payload_preview": data[:80].decode("utf-8", errors="replace")}


def run_once(route: dict[str, Any], ctx: dict[str, Any], state: GatewayState) -> dict[str, Any]:
    cmd = render_template(route.get("cmd") or [], ctx)
    cwd = render_template(route.get("cwd"), ctx) if route.get("cwd") else None
    timeout = float(route.get("timeout_sec") or state.config.get("request_timeout_sec") or 8.0)
    if not cmd:
        raise ValueError("subprocess_once route has empty cmd")
    if state.dry_run:
        return {"status": "dry_run", "handler": "subprocess_once", "cmd": cmd, "cwd": cwd}
    started = time.time()
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "handler": "subprocess_once",
        "cmd": cmd,
        "cwd": cwd,
        "returncode": completed.returncode,
        "duration_sec": round(time.time() - started, 3),
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def build_ack(payload: dict[str, Any], status: str, stage: str, result: dict[str, Any], error: str | None, state: GatewayState) -> dict[str, Any]:
    command = payload.get("command") or {}
    return {
        "protocol": PROTOCOL,
        "message_id": payload.get("message_id"),
        "task_id": payload.get("task_id") or command.get("task_id"),
        "target_id": payload.get("target_id", state.config.get("target_id", DEFAULT_TARGET_ID)),
        "target_type": payload.get("target_type", state.config.get("target_type", DEFAULT_TARGET_TYPE)),
        "status": status,
        "stage": stage,
        "result": result,
        "error": error,
        "device_time": now_iso(),
        "telemetry": {
            "executor": "tongyu_robot_gateway",
            "gateway_uptime_sec": round(time.time() - state.started_at, 2),
            "command_count": state.command_count,
            "network_interface": state.config.get("network_interface"),
            "dry_run": state.dry_run,
        },
    }


def post_ack(ack: dict[str, Any], state: GatewayState) -> dict[str, Any]:
    hub_url = str(state.config.get("hub_url") or "").rstrip("/")
    ack_path = str(state.config.get("ack_path") or "/api/robot/ack")
    if not hub_url:
        return {"status": "skipped", "reason": "empty hub_url"}
    try:
        return post_json(f"{hub_url}{ack_path}", ack, timeout=float(state.config.get("request_timeout_sec") or 5.0))
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc)}


def normalize_command(payload: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Return route_key, params, protocol_label.

    New payload style:
        {"protocol":"tongyu.robot.unified.v1", "command":{"domain":"speech", "action":"speak", "params":{...}}}

    Old compatible style from g1_bridge_demo.py:
        {"command":{"type":"g1.unitree_sdk_sequence", "params":{"sdk_sequence":[...]}}}
    """
    command = payload.get("command")
    if not isinstance(command, dict):
        raise ValueError("payload.command must be an object")

    # Backward compatibility with the earlier demo bridge.
    if command.get("type") == OLD_COMMAND_TYPE:
        return OLD_COMMAND_TYPE, command.get("params") or {}, "legacy"

    domain = command.get("domain") or command.get("module")
    action = command.get("action") or command.get("name")
    if not domain or not action:
        raise ValueError("command.domain and command.action are required")
    params = command.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("command.params must be an object")
    return f"{domain}.{action}", params, "unified"


def dispatch_legacy_sdk_sequence(params: dict[str, Any], state: GatewayState) -> dict[str, Any]:
    """Compatibility shim for g1_bridge_demo.py style sdk_sequence commands.

    It intentionally keeps the old central-hub contract valid while redirecting
    common steps into the new unified routes when possible.
    """
    sdk_sequence = params.get("sdk_sequence") or []
    if not isinstance(sdk_sequence, list):
        raise ValueError("command.params.sdk_sequence must be a list")
    executed: list[dict[str, Any]] = []
    for step in sdk_sequence:
        if not isinstance(step, dict):
            raise ValueError(f"invalid sdk step: {step!r}")
        source = str(step.get("source_primitive") or step.get("primitive") or "unknown")
        client = str(step.get("client") or "")
        method = str(step.get("method") or "")
        args = step.get("args") or {}

        if source == "sleep" or method.lower() == "sleep":
            seconds = max(0.0, min(float(args.get("seconds", 0.5)), 10.0))
            if not state.dry_run:
                time.sleep(seconds)
            executed.append({"source": source, "handler": "sleep", "seconds": seconds})
            continue

        if client in {"AudioClient", "SpeechAdapter"} and method in {"TtsMaker", "Speak"}:
            text = args.get("text") or args.get("text_cn") or args.get("content") or ""
            result = dispatch_route("speech.speak", {"text": text, **args}, state)
            executed.append({"source": source, "redirect": "speech.speak", "result": result})
            continue

        if client == "G1ArmActionClient" and method == "ExecuteAction":
            action_name = args.get("action_name") or args.get("action_map_key")
            action_id = args.get("action_id")
            if action_name:
                packet = f"name:{action_name}"
            else:
                packet = str(action_id)
            result = dispatch_route("motion.arm_action", {"action_packet": packet, **args}, state)
            executed.append({"source": source, "redirect": "motion.arm_action", "result": result})
            continue

        executed.append({"source": source, "handler": "legacy_noop", "client": client, "method": method, "args": args})
    return {"status": "completed", "handler": "legacy_sdk_sequence", "executed_steps": executed}


def dispatch_route(route_key: str, params: dict[str, Any], state: GatewayState) -> dict[str, Any]:
    if route_key == OLD_COMMAND_TYPE:
        return dispatch_legacy_sdk_sequence(params, state)

    routes = state.config.get("routes") or {}
    route = routes.get(route_key)
    if not route:
        raise ValueError(f"unsupported route: {route_key}")

    params = {**(route.get("default_params") or {}), **params}
    ctx = {**state.base_context(), **params, "route": route_key}
    handler = str(route.get("handler"))

    # Optional: make sure a daemon exists before sending UDP to it.
    ensure_service = route.get("ensure_service")
    if ensure_service:
        service_name = str(render_template(ensure_service, ctx))
        ensure_result = state.start_service(service_name, params=params, restart=bool(params.get("restart_service", False)))
    else:
        ensure_result = None

    if handler == "udp":
        host = str(render_template(route.get("host", "127.0.0.1"), ctx))
        port = int(render_template(route.get("port", 0), ctx))
        payload = str(render_template(route.get("payload", ""), ctx))
        result = send_udp(host, port, payload, timeout=float(route.get("timeout_sec") or 2.0)) if not state.dry_run else {"status": "dry_run", "transport": "udp", "host": host, "port": port, "payload": payload}
    elif handler == "subprocess_once":
        result = run_once(route, ctx, state)
    elif handler == "service_start":
        service = str(render_template(route.get("service"), ctx))
        result = state.start_service(service, params=params, restart=bool(params.get("restart", False)))
    elif handler == "service_stop":
        service = str(render_template(route.get("service"), ctx))
        result = state.stop_service(service)
    elif handler == "service_status":
        service = str(render_template(route.get("service"), ctx))
        result = state.service_status(service)
    else:
        raise ValueError(f"unsupported handler for route {route_key}: {handler}")

    if ensure_result is not None:
        result = {"ensure_service": ensure_result, "dispatch": result}
    result.setdefault("route", route_key)
    result.setdefault("handler", handler)
    return result


def execute_payload(payload: dict[str, Any], state: GatewayState) -> tuple[dict[str, Any], int]:
    target_id = payload.get("target_id")
    expected_target = state.config.get("target_id", DEFAULT_TARGET_ID)
    if target_id and target_id != expected_target:
        return {"error": f"unsupported target_id: {target_id}"}, 400

    with state.lock:
        state.command_count += 1
        state.last_command = payload

    route_key = "unknown"
    try:
        route_key, params, protocol_label = normalize_command(payload)
        result = dispatch_route(route_key, params, state)
        ack = build_ack(payload, "ok", route_key, result, None, state)
        status_code = 200
    except Exception as exc:  # noqa: BLE001 - gateway must report errors to hub.
        LOG.exception("command failed")
        result = {"status": "failed", "traceback": traceback.format_exc(limit=4)}
        ack = build_ack(payload, "failed", route_key, result, str(exc), state)
        status_code = 500

    ack_post = post_ack(ack, state) if bool(payload.get("ack", True)) else {"status": "skipped", "reason": "payload.ack=false"}
    ack["ack_post_result"] = ack_post
    with state.lock:
        state.last_ack = ack
        state.remember({"time": now_iso(), "payload": payload, "ack": ack})
    return {"status": "accepted" if ack["status"] == "ok" else "failed", "route": route_key, "ack": ack}, status_code


def register_device(state: GatewayState, *, host_ip: str, port: int) -> dict[str, Any]:
    hub_url = str(state.config.get("hub_url") or "").rstrip("/")
    register_path = str(state.config.get("register_path") or "/api/devices/register")
    if not hub_url:
        return {"status": "skipped", "reason": "empty hub_url"}
    payload = {
        "protocol": PROTOCOL,
        "target_id": state.config.get("target_id", DEFAULT_TARGET_ID),
        "target_type": state.config.get("target_type", DEFAULT_TARGET_TYPE),
        "client_id": state.config.get("client_id", "g1_ubuntu_01"),
        "ip": host_ip,
        "port": port,
        "transport": "http_push",
        "command_endpoint": "/api/robot/command",
        "legacy_endpoint": "/api/g1/execute",
        "capabilities": sorted((state.config.get("routes") or {}).keys()),
        "services": sorted((state.config.get("services") or {}).keys()),
        "status": "online",
        "device_time": now_iso(),
    }
    try:
        return post_json(f"{hub_url}{register_path}", payload, timeout=float(state.config.get("request_timeout_sec") or 5.0))
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc), "payload": payload}


def make_handler(state: GatewayState) -> type[BaseHTTPRequestHandler]:
    class GatewayHandler(BaseHTTPRequestHandler):
        server_version = "TongyuRobotGateway/1.0"

        def _auth_ok(self) -> bool:
            if not state.token:
                return True
            return self.headers.get("X-Tongyu-Token") == state.token

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            if not self._auth_ok():
                self._send_json({"error": "unauthorized"}, 401)
                return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/health":
                self._send_json({
                    "status": "ok",
                    "protocol": PROTOCOL,
                    "service": "tongyu_robot_gateway",
                    "target_id": state.config.get("target_id", DEFAULT_TARGET_ID),
                    "target_type": state.config.get("target_type", DEFAULT_TARGET_TYPE),
                    "hub_url": state.config.get("hub_url"),
                    "network_interface": state.config.get("network_interface"),
                    "dry_run": state.dry_run,
                    "command_count": state.command_count,
                    "uptime_sec": round(time.time() - state.started_at, 2),
                    "capabilities": sorted((state.config.get("routes") or {}).keys()),
                })
                return
            if path in {"/api/robot/status", "/status"}:
                self._send_json({
                    "status": "ok",
                    "protocol": PROTOCOL,
                    "target_id": state.config.get("target_id", DEFAULT_TARGET_ID),
                    "command_count": state.command_count,
                    "processes": state.all_process_status(),
                    "last_ack": state.last_ack,
                })
                return
            if path in {"/last", "/api/robot/last"}:
                self._send_json({"last_command": state.last_command, "last_ack": state.last_ack, "history_tail": state.history[-5:]})
                return
            if path in {"/api/robot/service", "/service"}:
                service = (query.get("name") or [""])[0]
                self._send_json(state.service_status(service) if service else {"error": "missing ?name=SERVICE"}, 200 if service else 400)
                return
            self._send_json({"error": "not found", "path": self.path}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if not self._auth_ok():
                self._send_json({"error": "unauthorized"}, 401)
                return
            path = urllib.parse.urlparse(self.path).path
            if path not in {"/api/robot/command", "/api/g1/execute", "/command"}:
                self._send_json({"error": "not found", "path": self.path}, 404)
                return
            try:
                payload = self._read_json()
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"invalid json: {exc}"}, 400)
                return
            result, status = execute_payload(payload, state)
            self._send_json(result, status)

        def log_message(self, fmt: str, *args: Any) -> None:
            LOG.info("%s - %s", self.address_string(), fmt % args)

    return GatewayHandler


def start_service_supervisor(state: GatewayState) -> threading.Thread:
    def loop() -> None:
        while not state.stop_supervisor:
            try:
                state.stop_expired_services()
            except Exception as exc:  # noqa: BLE001
                LOG.warning("service supervisor error: %s", exc)
            time.sleep(1.0)

    thread = threading.Thread(target=loop, name="tongyu-service-supervisor", daemon=True)
    thread.start()
    return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Tongyu robot unified gateway for Ubuntu robot host")
    parser.add_argument("--config", help="JSON config path. Omit to use built-in defaults.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host, default 0.0.0.0")
    parser.add_argument("--port", type=int, help="Bind port. Overrides config port.")
    parser.add_argument("--hub-url", help="Central hub base URL. Overrides config hub_url.")
    parser.add_argument("--host-ip", help="Robot Ubuntu LAN IP for optional registration. Overrides config host_ip.")
    parser.add_argument("--network-interface", help="Unitree SDK network interface, e.g. eth0/wlan0. Overrides config.")
    parser.add_argument("--token", help="Optional shared token required in X-Tongyu-Token header.")
    parser.add_argument("--dry-run", action="store_true", help="Print/return what would be executed, without launching processes.")
    parser.add_argument("--register", action="store_true", help="Register this gateway to central hub on startup.")
    parser.add_argument("--autostart", action="store_true", help="Start services marked autostart=true in config.")
    parser.add_argument("--dump-default-config", action="store_true", help="Print built-in default config and exit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dump_default_config:
        print(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
        return

    config = load_config(args.config)
    if args.port:
        config["port"] = args.port
    if args.hub_url:
        config["hub_url"] = args.hub_url.rstrip("/")
        try:
            parsed = urllib.parse.urlparse(config["hub_url"])
            if parsed.hostname:
                config["hub_ip"] = parsed.hostname
        except Exception:
            pass
    if args.host_ip:
        config["host_ip"] = args.host_ip
    if args.network_interface:
        config["network_interface"] = args.network_interface

    state = GatewayState(config=config, token=args.token, dry_run=args.dry_run)
    start_service_supervisor(state)

    if args.autostart:
        for service, service_cfg in (config.get("services") or {}).items():
            if service_cfg.get("autostart"):
                try:
                    LOG.info("autostart service=%s result=%s", service, state.start_service(service))
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("autostart failed service=%s error=%s", service, exc)

    if args.register:
        reg_result = register_device(state, host_ip=str(config.get("host_ip")), port=int(config.get("port")))
        LOG.info("register result: %s", reg_result)

    server = ThreadingHTTPServer((args.host, int(config.get("port") or 8731)), make_handler(state))
    LOG.info("Tongyu robot gateway listening on http://%s:%s dry_run=%s", args.host, config.get("port"), state.dry_run)
    LOG.info("health: curl http://127.0.0.1:%s/health", config.get("port"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopping gateway")
    finally:
        state.stop_supervisor = True
        for service in list(state.processes.keys()):
            try:
                state.stop_service(service)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("failed to stop service=%s: %s", service, exc)
        server.server_close()


if __name__ == "__main__":
    main()
