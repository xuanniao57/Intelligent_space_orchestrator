"""Protocol helpers for Tongyu DeviceCommand envelopes."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


CST = timezone(timedelta(hours=8))


def now_cst() -> str:
    """Return an ISO timestamp with +08:00 timezone."""
    return datetime.now(CST).isoformat(timespec="milliseconds")


def new_message_id(prefix: str = "cmd_sdk") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def new_task_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def device_command(
    *,
    target_id: str,
    target_type: str,
    command_type: str,
    params: Mapping[str, Any] | None = None,
    message_id: str | None = None,
    routing: Mapping[str, Any] | None = None,
    ack_required: bool = True,
    timeout_ms: int = 15000,
    source_id: str = "tongyu_hardware_sdk",
    **extra: Any,
) -> dict[str, Any]:
    """Build the standard DeviceCommand envelope used by the hub and clients."""
    command = {
        "message_type": "device_command",
        "message_id": message_id or new_message_id(),
        "timestamp": now_cst(),
        "source_id": source_id,
        "target_id": target_id,
        "target_type": target_type,
        "verb": "command",
        "command": {
            "type": command_type,
            "params": dict(params or {}),
        },
        "routing": dict(routing or {}),
        "ack_required": ack_required,
        "timeout_ms": int(timeout_ms),
    }
    command.update(extra)
    return command


def deep_merge(base: dict[str, Any], patch: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge nested dictionaries and return the mutated base."""
    if not patch:
        return base
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base
