"""Client for the Tongyu central hub hardware APIs."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .http import add_query, http_json
from .protocol import new_message_id, new_task_id


DEFAULT_HUB_URL = "http://192.168.1.50:8798"
ROBOT_UNIFIED_PROTOCOL = "tongyu.robot.unified.v1"
DEFAULT_ROBOT_TARGET_ID = "unitree_g1"


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

    def g1_actions(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/g1/actions"), timeout=self.timeout)

    def perception_streams(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/perception/streams"), timeout=self.timeout)

    def vision_status(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/perception/vision/status"), timeout=self.timeout)

    def vision_queue(self, kind: str | None = None, *, limit: int = 20) -> dict[str, Any]:
        path = "/api/perception/vision/queue" if not kind else f"/api/perception/vision/queue/{kind}"
        return http_json("GET", add_query(self.url(path), {"limit": limit}), timeout=self.timeout)

    def audio_status(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/perception/audio/status"), timeout=self.timeout)

    def audio_chunks(self, *, limit: int = 20) -> dict[str, Any]:
        return http_json("GET", add_query(self.url("/api/perception/audio/chunks"), {"limit": limit}), timeout=self.timeout)

    def asr_history(self, *, limit: int = 50) -> dict[str, Any]:
        return http_json("GET", add_query(self.url("/api/perception/asr/history"), {"limit": limit}), timeout=self.timeout)

    def robot_host_health(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return http_json("GET", add_query(self.url("/api/robot-host/health"), {"robot_url": robot_url}), timeout=self.timeout)

    def robot_host_status(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return http_json("GET", add_query(self.url("/api/robot-host/status"), {"robot_url": robot_url}), timeout=self.timeout)

    def build_robot_command(
        self,
        domain: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        target_id: str = DEFAULT_ROBOT_TARGET_ID,
        task_id: str | None = None,
        ack: bool = True,
    ) -> dict[str, Any]:
        return {
            "protocol": ROBOT_UNIFIED_PROTOCOL,
            "message_id": new_message_id("robot_cmd"),
            "task_id": task_id or new_task_id(f"{domain}_{action}"),
            "target_id": target_id,
            "target_type": "robot",
            "ack": ack,
            "command": {
                "domain": domain,
                "action": action,
                "params": dict(params or {}),
            },
        }

    def robot_host_command(
        self,
        domain: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        robot_url: str | None = None,
        target_id: str = DEFAULT_ROBOT_TARGET_ID,
        task_id: str | None = None,
        ack: bool = True,
    ) -> dict[str, Any]:
        payload = self.build_robot_command(domain, action, params, target_id=target_id, task_id=task_id, ack=ack)
        if robot_url:
            payload["robot_url"] = robot_url
        return http_json("POST", self.url("/api/robot-host/command"), payload, timeout=self.timeout)

    def execute_g1_actions(
        self,
        actions: list[str | int] | None = None,
        *,
        action: str | int | None = None,
        test10: bool = False,
        bridge_url: str | None = None,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
        release_after_sec: float = 2.0,
        timeout_sec: float = 10.0,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dry_run": dry_run,
            "real_send": real_send,
            "release_after_sec": release_after_sec,
            "timeout_sec": timeout_sec,
            "test10": test10,
        }
        if actions is not None:
            payload["actions"] = list(actions)
        if action is not None:
            payload["action"] = action
        if bridge_url:
            payload["robot_url"] = bridge_url
        if network_interface:
            payload["network_interface"] = network_interface
        if task_id:
            payload["task_id"] = task_id
        return http_json("POST", self.url("/api/g1/actions/execute"), payload, timeout=max(self.timeout, timeout_sec + 5.0))

    def g1_sessions(self, *, include_all: bool = False) -> dict[str, Any]:
        return http_json(
            "GET",
            add_query(self.url("/api/g1/sessions"), {"all": str(include_all).lower()}),
            timeout=self.timeout,
        )

    def create_g1_session(
        self,
        *,
        owner: str | None = None,
        client_id: str | None = None,
        purpose: str = "manual_g1_control",
        ttl_sec: int = 600,
        idle_timeout_sec: int | None = None,
        mode: str = "central_gateway_lease",
        allowed_proxy_ports: list[int] | None = None,
        dry_run: bool = True,
        real_control: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "owner": owner,
            "client_id": client_id,
            "purpose": purpose,
            "ttl_sec": ttl_sec,
            "idle_timeout_sec": idle_timeout_sec,
            "mode": mode,
            "allowed_proxy_ports": allowed_proxy_ports or [],
            "dry_run": dry_run,
            "real_control": real_control,
        }
        return http_json("POST", self.url("/api/g1/sessions"), payload, timeout=self.timeout)

    def heartbeat_g1_session(self, session_id: str, token: str, *, message: str = "heartbeat") -> dict[str, Any]:
        return http_json(
            "POST",
            self.url(f"/api/g1/sessions/{session_id}/heartbeat"),
            {"message": message},
            timeout=self.timeout,
            headers={"X-Tongyu-Session-Token": token},
        )

    def release_g1_session(self, session_id: str, token: str, *, reason: str = "client_release") -> dict[str, Any]:
        return http_json(
            "DELETE",
            self.url(f"/api/g1/sessions/{session_id}"),
            {"reason": reason},
            timeout=self.timeout,
            headers={"X-Tongyu-Session-Token": token},
        )

    def speaker_library(self) -> dict[str, Any]:
        return http_json("GET", self.url("/api/hardware/speaker/library"), timeout=self.timeout)

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
