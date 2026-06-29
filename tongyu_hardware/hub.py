"""Client for the Tongyu central hub hardware APIs."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .http import add_query, http_json


DEFAULT_HUB_URL = "http://192.168.1.50:8798"


def default_hub_url() -> str:
    return os.environ.get("TONGYU_HUB_URL", DEFAULT_HUB_URL).rstrip("/")


class HubClient:
    """HTTP client for central-hub mediated hardware dispatch."""

    def __init__(self, hub_url: str | None = None, *, timeout: float = 8.0) -> None:
        self.hub_url = (hub_url or default_hub_url()).rstrip("/")
        self.timeout = timeout

    def url(self, path: str) -> str:
        return f"{self.hub_url}/{path.lstrip('/')}"

    def health(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/health"), timeout=self.timeout)

    def devices(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/devices"), timeout=self.timeout)

    def register_device(
        self,
        *,
        target_id: str,
        target_type: str,
        client_id: str | None = None,
        ip: str | None = None,
        port: int | None = None,
        transport: str = "http_poll",
        capabilities: list[str] | None = None,
        status: str = "online",
        meta: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return http_json(
            "POST",
            self.url("/api/devices/register"),
            {
                "target_id": target_id,
                "target_type": target_type,
                "client_id": client_id or target_id,
                "ip": ip,
                "port": port,
                "transport": transport,
                "capabilities": capabilities or [],
                "status": status,
                "meta": dict(meta or {}),
            },
            timeout=self.timeout,
        )

    def dispatch_command(
        self,
        command: Mapping[str, Any],
        *,
        robot_url: str | None = None,
        routing_overrides: Mapping[str, Any] | None = None,
        execute: bool = True,
        raw_lan_dry_run: bool = True,
        raw_lan_probe: bool = True,
        allow_raw_lan_send: bool = False,
        scenario_id: str = "hardware_sdk",
        space_id: str = "hardware_sdk",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": dict(command),
            "scenario_id": scenario_id,
            "space_id": space_id,
            "routing_overrides": dict(routing_overrides or {}),
            "execute": execute,
            "raw_lan_dry_run": raw_lan_dry_run,
            "raw_lan_probe": raw_lan_probe,
            "allow_raw_lan_send": allow_raw_lan_send,
        }
        if robot_url:
            payload["robot_url"] = robot_url
        return http_json("POST", self.url("/api/hardware/command"), payload, timeout=self.timeout)

    def dispatch_sequence(
        self,
        action_ids: list[str],
        *,
        robot_url: str | None = None,
        routing_overrides: Mapping[str, Any] | None = None,
        raw_lan_dry_run: bool = True,
        raw_lan_probe: bool = True,
        allow_raw_lan_send: bool = False,
        execute: bool = True,
        scenario_id: str = "hardware_sdk",
        space_id: str = "hardware_sdk",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_ids": action_ids,
            "execute": execute,
            "scenario_id": scenario_id,
            "space_id": space_id,
            "routing_overrides": dict(routing_overrides or {}),
            "raw_lan_dry_run": raw_lan_dry_run,
            "raw_lan_probe": raw_lan_probe,
            "allow_raw_lan_send": allow_raw_lan_send,
        }
        if robot_url:
            payload["robot_url"] = robot_url
        return http_json("POST", self.url("/api/hardware/sequence"), payload, timeout=max(self.timeout, 15.0))

    def poll_commands(self, target_id: str, *, limit: int = 20, after_message_id: str | None = None, command_type: str | None = None) -> dict[str, Any]:
        url = add_query(
            self.url(f"/api/devices/{target_id}/commands"),
            {"limit": limit, "after_message_id": after_message_id, "command_type": command_type},
        )
        return http_json("GET", url, timeout=self.timeout)

    def post_device_ack(self, ack: Mapping[str, Any]) -> dict[str, Any]:
        return http_json("POST", self.url("/api/device/ack"), ack, timeout=self.timeout)

    def post_robot_ack(self, ack: Mapping[str, Any]) -> dict[str, Any]:
        return http_json("POST", self.url("/api/robot/ack"), ack, timeout=self.timeout)

    def ingest_scene_semantic(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        return http_json("POST", self.url("/api/scene/semantic/ingest"), frame, timeout=max(self.timeout, 20.0))
