#!/usr/bin/env python3
"""Tongyu central-side one-command robot controller.

Run this on the central hub computer. It sends unified HTTP commands to the
robot Ubuntu gateway (`tongyu-robot-gateway`). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

PROTOCOL = "tongyu.robot.unified.v1"
DEFAULT_TARGET_ID = "unitree_g1"


def now_task_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}"


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, *, token: str | None = None, timeout: float = 8.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["X-Tongyu-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(body) if body else {}
            except json.JSONDecodeError:
                result = {"body": body}
            result.setdefault("status_code", resp.status)
            return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body) if body else {}
        except json.JSONDecodeError:
            result = {"body": body}
        result["status_code"] = exc.code
        return result


def build_payload(domain: str, action: str, params: dict[str, Any], *, target_id: str, task_id: str | None = None, ack: bool = True) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "message_id": str(uuid.uuid4()),
        "task_id": task_id or now_task_id(f"{domain}_{action}"),
        "target_id": target_id,
        "target_type": "robot",
        "ack": ack,
        "command": {
            "domain": domain,
            "action": action,
            "params": params,
        },
    }


def post_command(args: argparse.Namespace, domain: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = build_payload(domain, action, params, target_id=args.target_id, task_id=getattr(args, "task_id", None), ack=not getattr(args, "no_ack", False))
    return request_json("POST", args.robot_url.rstrip("/") + "/api/robot/command", payload, token=args.token, timeout=args.timeout)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Central-side one-command interface for Tongyu robot gateway")
    parser.add_argument("--robot-url", default="http://192.168.1.172:8731", help="Robot Ubuntu gateway URL")
    parser.add_argument("--target-id", default=DEFAULT_TARGET_ID, help="Robot target id")
    parser.add_argument("--token", help="Optional X-Tongyu-Token shared token")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds")
    parser.add_argument("--task-id", help="Optional task id")
    parser.add_argument("--no-ack", action="store_true", help="Ask robot gateway not to post ACK back to hub")

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="Check gateway health")
    sub.add_parser("status", help="Get all managed service status")
    sub.add_parser("last", help="Get last command/ack")

    p = sub.add_parser("speak", help="Text to speech on robot")
    p.add_argument("text")
    p.add_argument("--speaker-id", default="0")

    p = sub.add_parser("action", help="Execute G1 arm/action command")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--id", dest="action_id", type=int, help="SDK action id, e.g. 11")
    g.add_argument("--name", dest="action_name", help="SDK action_map name")
    g.add_argument("--packet", help="Raw packet to existing UDP action receiver, e.g. stop / 99 / name:xxx")
    p.add_argument("--release", action="store_true", help="Convenience: send 99 release packet")
    p.add_argument("--stop", action="store_true", help="Convenience: send stop packet")

    p = sub.add_parser("nav", help="Send navigation target")
    p.add_argument("--x", required=True, type=float)
    p.add_argument("--y", required=True, type=float)
    p.add_argument("--yaw", default=0.0, type=float)
    p.add_argument("--frame", default="map")

    p = sub.add_parser("video-start", help="Start robot camera video relay")
    p.add_argument("--ttl-sec", type=int, default=600)
    sub.add_parser("video-stop", help="Stop robot camera video relay")
    sub.add_parser("video-status", help="Check video relay status")
    p = sub.add_parser("mic-start", help="Start robot microphone/environment-audio relay")
    p.add_argument("--ttl-sec", type=int, default=600)
    sub.add_parser("mic-stop", help="Stop robot microphone/environment-audio relay")
    sub.add_parser("mic-status", help="Check microphone relay status")
    p = sub.add_parser("asr-start", help="Start ASR/dialogue text relay")
    p.add_argument("--ttl-sec", type=int, default=600)
    sub.add_parser("asr-stop", help="Stop ASR/dialogue text relay")
    sub.add_parser("asr-status", help="Check ASR relay status")

    p = sub.add_parser("service-start", help="Start any configured service by name")
    p.add_argument("service")
    p.add_argument("--restart", action="store_true")
    p = sub.add_parser("service-stop", help="Stop any configured service by name")
    p.add_argument("service")
    p = sub.add_parser("service-status", help="Check any configured service by name")
    p.add_argument("service")

    p = sub.add_parser("send-json", help="Send a raw JSON payload file; use - for stdin")
    p.add_argument("path")

    args = parser.parse_args()
    base = args.robot_url.rstrip("/")

    if args.cmd == "health":
        print_json(request_json("GET", base + "/health", token=args.token, timeout=args.timeout))
    elif args.cmd == "status":
        print_json(request_json("GET", base + "/api/robot/status", token=args.token, timeout=args.timeout))
    elif args.cmd == "last":
        print_json(request_json("GET", base + "/last", token=args.token, timeout=args.timeout))
    elif args.cmd == "speak":
        print_json(post_command(args, "speech", "speak", {"text": args.text, "speaker_id": str(args.speaker_id)}))
    elif args.cmd == "action":
        if args.stop:
            packet = "stop"
        elif args.release:
            packet = "99"
        elif args.packet is not None:
            packet = args.packet
        elif args.action_name:
            packet = f"name:{args.action_name}"
        elif args.action_id is not None:
            packet = str(args.action_id)
        else:
            raise SystemExit("action requires --id, --name, --packet, --release, or --stop")
        print_json(post_command(args, "motion", "arm_action", {"action_packet": packet, "action_id": args.action_id, "action_name": args.action_name or ""}))
    elif args.cmd == "nav":
        print_json(post_command(args, "navigation", "goto", {"x": str(args.x), "y": str(args.y), "yaw": str(args.yaw), "frame": args.frame}))
    elif args.cmd.startswith("video-"):
        params = {"ttl_sec": args.ttl_sec} if args.cmd == "video-start" else {}
        print_json(post_command(args, "video", args.cmd.split("-", 1)[1], params))
    elif args.cmd.startswith("mic-"):
        action = {"start": "mic_start", "stop": "mic_stop", "status": "mic_status"}[args.cmd.split("-", 1)[1]]
        params = {"ttl_sec": args.ttl_sec} if args.cmd == "mic-start" else {}
        print_json(post_command(args, "audio", action, params))
    elif args.cmd.startswith("asr-"):
        params = {"ttl_sec": args.ttl_sec} if args.cmd == "asr-start" else {}
        print_json(post_command(args, "asr", args.cmd.split("-", 1)[1], params))
    elif args.cmd == "service-start":
        print_json(post_command(args, "service", "start", {"service": args.service, "restart": args.restart}))
    elif args.cmd == "service-stop":
        print_json(post_command(args, "service", "stop", {"service": args.service}))
    elif args.cmd == "service-status":
        print_json(post_command(args, "service", "status", {"service": args.service}))
    elif args.cmd == "send-json":
        if args.path == "-":
            payload = json.load(sys.stdin)
        else:
            with open(args.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        print_json(request_json("POST", base + "/api/robot/command", payload, token=args.token, timeout=args.timeout))


if __name__ == "__main__":
    main()
