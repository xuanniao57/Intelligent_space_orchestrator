"""Atomic LAN control helpers for UDP/TCP/WOL hardware commands."""

from __future__ import annotations

import json
import re
import socket
import time
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "central_hub"
    / "data"
    / "agent_io_registry"
    / "lan_control_tools.json"
)


def normalize_hex(payload: str) -> str:
    compact = re.sub(r"[^0-9A-Fa-f]", "", str(payload or ""))
    if len(compact) % 2:
        raise ValueError("HEX payload length must be even")
    if compact and not re.fullmatch(r"[0-9A-Fa-f]+", compact):
        raise ValueError("HEX payload contains non-hex characters")
    return compact


def payload_bytes(payload: str, payload_format: str = "STR", encoding: str = "utf-8") -> bytes:
    fmt = str(payload_format or "STR").upper()
    if fmt == "HEX":
        return bytes.fromhex(normalize_hex(payload))
    if fmt == "STR":
        return str(payload or "").encode(encoding)
    raise ValueError(f"unsupported payload_format: {payload_format}")


def tcp_probe(host: str, port: int, timeout: float = 1.0) -> dict[str, Any]:
    started = time.time()
    with socket.create_connection((host, int(port)), timeout=timeout):
        pass
    return {"ok": True, "probe": "tcp_connect", "latency_ms": round((time.time() - started) * 1000, 2)}


def send_tcp(
    host: str,
    port: int,
    payload: str,
    *,
    payload_format: str = "STR",
    timeout: float = 3.0,
    repeat_count: int = 1,
    delay_ms: int = 0,
) -> dict[str, Any]:
    raw = payload_bytes(payload, payload_format)
    repeat = max(1, min(int(repeat_count), 5))
    delay = max(0.0, min(float(delay_ms) / 1000.0, 2.0))
    for index in range(repeat):
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.sendall(raw)
        if delay and index < repeat - 1:
            time.sleep(delay)
    return {"ok": True, "transport": "tcp", "endpoint": f"{host}:{port}", "bytes_len": len(raw), "repeat_count": repeat}


def send_udp(
    host: str,
    port: int,
    payload: str,
    *,
    payload_format: str = "HEX",
    repeat_count: int = 1,
    delay_ms: int = 0,
) -> dict[str, Any]:
    raw = payload_bytes(payload, payload_format)
    repeat = max(1, min(int(repeat_count), 5))
    delay = max(0.0, min(float(delay_ms) / 1000.0, 2.0))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for index in range(repeat):
            sock.sendto(raw, (host, int(port)))
            if delay and index < repeat - 1:
                time.sleep(delay)
    return {"ok": True, "transport": "udp", "endpoint": f"{host}:{port}", "bytes_len": len(raw), "repeat_count": repeat}


def normalize_mac(mac: str) -> str:
    compact = re.sub(r"[^0-9A-Fa-f]", "", str(mac or ""))
    if len(compact) != 12:
        raise ValueError("MAC must contain 12 hex characters")
    return compact.upper()


def send_wol(mac: str, *, broadcast: str = "255.255.255.255", port: int = 9) -> dict[str, Any]:
    compact = normalize_mac(mac)
    raw = bytes.fromhex("FF" * 6 + compact * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(raw, (broadcast, int(port)))
    return {"ok": True, "transport": "wol", "broadcast": f"{broadcast}:{port}", "bytes_len": len(raw)}


def load_lan_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def registry_commands(path: str | Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    return list(load_lan_registry(path).get("commands") or [])


def find_command(command_id: str, path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    for command in registry_commands(path):
        if command.get("id") == command_id:
            return command
    raise KeyError(f"LAN command not found: {command_id}")


def send_registry_command(
    command_id: str,
    *,
    path: str | Path = DEFAULT_REGISTRY_PATH,
    dry_run: bool = True,
    probe: bool = True,
) -> dict[str, Any]:
    command = find_command(command_id, path)
    protocol = str(command.get("protocol") or "").upper()
    payload = str(command.get("payload") or "")
    payload_format = str(command.get("format") or command.get("payload_format") or "STR").upper()
    host = str(command.get("host") or "")
    port = command.get("port")
    raw = payload_bytes(payload, payload_format)
    base = {
        "command_id": command_id,
        "label": command.get("label"),
        "protocol": protocol,
        "endpoint": f"{host}:{port}" if host and port else "",
        "payload_format": payload_format,
        "bytes_len": len(raw),
        "dry_run": dry_run,
    }
    if dry_run:
        if protocol == "TCP" and probe:
            base["probe_result"] = tcp_probe(host, int(port))
        elif protocol == "UDP":
            base["probe_result"] = {"ok": True, "probe": "udp_no_payload"}
        return {**base, "ok": True, "payload_sent": False}
    if payload.upper().startswith("WOL#"):
        return {**base, **send_wol(payload.split("#", 1)[1]), "payload_sent": True}
    if protocol == "UDP":
        return {**base, **send_udp(host, int(port), payload, payload_format=payload_format, repeat_count=command.get("repeat_count") or 1, delay_ms=command.get("delay_ms") or 0), "payload_sent": True}
    if protocol == "TCP":
        return {**base, **send_tcp(host, int(port), payload, payload_format=payload_format, repeat_count=command.get("repeat_count") or 1, delay_ms=command.get("delay_ms") or 0), "payload_sent": True}
    raise ValueError(f"unsupported protocol: {protocol}")
