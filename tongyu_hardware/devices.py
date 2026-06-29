"""High-level device clients for Tongyu hardware."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .hub import HubClient
from .lan import send_registry_command
from .protocol import device_command, new_task_id


LIGHT_ACTIONS = {
    "blue": "lan_cmd_008",
    "green": "lan_cmd_009",
    "white": "lan_cmd_010",
    "amber": "lan_cmd_011",
    "alternate": "lan_cmd_022",
    "alternating": "lan_cmd_022",
    "off": "lan_cmd_007",
}

PROJECTOR_POWER_ACTIONS = {
    ("library_vertical", "on"): "lan_cmd_012",
    ("library_horizontal", "on"): "lan_cmd_013",
    ("d_wall", "on"): "lan_cmd_014",
    ("library_vertical", "off"): "lan_cmd_019",
    ("library_horizontal", "off"): "lan_cmd_020",
    ("d_wall", "off"): "lan_cmd_021",
}

G1_BASIC_CHAIN = ["g1_safety_check", "g1_speak_notice", "g1_move_probe", "g1_report_ready"]


class SprayClient:
    def __init__(self, hub: HubClient, *, gateway_url: str | None = None) -> None:
        self.hub = hub
        self.gateway_url = gateway_url.rstrip("/") if gateway_url else None

    def _routing_overrides(self) -> dict[str, Any]:
        if not self.gateway_url:
            return {}
        return {"spray_gateway": {"direct_http": self.gateway_url}}

    def mist(self, *, zone: str = "cooling_zone_01", duration_sec: int = 20, intensity: float = 0.45, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="spray_gateway",
            target_type="spray_gateway",
            command_type="spray.scene",
            params={
                "task_id": task_id or new_task_id("spray_mist"),
                "op": "mist",
                "zone": zone,
                "duration_sec": duration_sec,
                "intensity": intensity,
            },
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(
            command,
            routing_overrides=self._routing_overrides(),
            execute=execute,
            scenario_id="spray_control",
            space_id=zone,
        )

    def stop(self, *, zone: str = "cooling_zone_01", task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="spray_gateway",
            target_type="spray_gateway",
            command_type="spray.stop",
            params={"task_id": task_id or new_task_id("spray_stop"), "op": "stop", "zone": zone},
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(
            command,
            routing_overrides=self._routing_overrides(),
            execute=execute,
            scenario_id="spray_control",
            space_id=zone,
        )


class LightsClient:
    def __init__(self, hub: HubClient) -> None:
        self.hub = hub

    def set_color(self, color: str, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        action_id = LIGHT_ACTIONS[color]
        if direct:
            return send_registry_command(action_id, dry_run=not real_send)
        return self.hub.dispatch_sequence(
            [action_id],
            raw_lan_dry_run=not real_send,
            allow_raw_lan_send=real_send,
            raw_lan_probe=False,
            scenario_id="light_control",
            space_id="field_lan_control",
        )

    def blue(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("blue", real_send=real_send, direct=direct)

    def green(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("green", real_send=real_send, direct=direct)

    def white(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("white", real_send=real_send, direct=direct)

    def amber(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("amber", real_send=real_send, direct=direct)

    def alternate(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("alternate", real_send=real_send, direct=direct)

    def off(self, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        return self.set_color("off", real_send=real_send, direct=direct)


class ProjectionClient:
    def __init__(self, hub: HubClient) -> None:
        self.hub = hub

    def play(self, *, content_id: str, slot: int | None = None, loop: bool = False, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {
            "task_id": task_id or new_task_id("projection_play"),
            "op": "play",
            "content_id": content_id,
            "loop": loop,
        }
        if slot is not None:
            params["slot"] = slot
        command = device_command(
            target_id="projection_gateway",
            target_type="projection_gateway",
            command_type="projection.play",
            params=params,
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(command, execute=execute, scenario_id="projection_control", space_id="projection_zone")

    def stop(self, *, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="projection_gateway",
            target_type="projection_gateway",
            command_type="projection.stop",
            params={"task_id": task_id or new_task_id("projection_stop"), "op": "stop"},
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(command, execute=execute, scenario_id="projection_control", space_id="projection_zone")

    def power(self, projector: str, state: str, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        action_id = PROJECTOR_POWER_ACTIONS[(projector, state)]
        if direct:
            return send_registry_command(action_id, dry_run=not real_send)
        return self.hub.dispatch_sequence(
            [action_id],
            raw_lan_dry_run=not real_send,
            allow_raw_lan_send=real_send,
            raw_lan_probe=True,
            scenario_id="projector_power_control",
            space_id="field_lan_control",
        )


class SpeakerClient:
    def __init__(self, hub: HubClient) -> None:
        self.hub = hub

    def play(self, *, content_id: str, volume: float | int = 0.62, loop: bool = False, slot: int | None = None, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {
            "task_id": task_id or new_task_id("speaker_play"),
            "op": "play",
            "content_id": content_id,
            "volume": volume,
            "loop": loop,
        }
        if slot is not None:
            params["slot"] = slot
        command = device_command(
            target_id="speaker_gateway",
            target_type="speaker_gateway",
            command_type="speaker.play",
            params=params,
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(command, execute=execute, scenario_id="speaker_control", space_id="sound_cocktail_zone_01")

    def stop(self, *, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="speaker_gateway",
            target_type="speaker_gateway",
            command_type="speaker.stop",
            params={"task_id": task_id or new_task_id("speaker_stop"), "op": "stop"},
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(command, execute=execute, scenario_id="speaker_control", space_id="sound_cocktail_zone_01")


class G1Client:
    def __init__(self, hub: HubClient, *, robot_url: str = "http://192.168.1.104:8731") -> None:
        self.hub = hub
        self.robot_url = robot_url.rstrip("/")

    def basic_test(self, *, robot_url: str | None = None, execute: bool = True) -> dict[str, Any]:
        return self.hub.dispatch_sequence(
            G1_BASIC_CHAIN,
            robot_url=robot_url or self.robot_url,
            execute=execute,
            scenario_id="g1_sdk_basic_test",
            space_id="cooling_zone_01",
        )

    def sdk_sequence(self, sdk_sequence: list[Mapping[str, Any]], *, speech_cn: str = "动作链测试开始。", robot_url: str | None = None, task_id: str | None = None, safety: Mapping[str, Any] | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="unitree_g1",
            target_type="robot",
            command_type="g1.unitree_sdk_sequence",
            params={
                "task_id": task_id or new_task_id("g1_sdk"),
                "scene_id": "hardware_sdk_g1_sequence",
                "speech_cn": speech_cn,
                "safety": dict(safety or {"dry_run": True, "speed_limit_mps": 0.25, "min_human_distance_m": 0.8}),
                "sdk_sequence": [dict(step) for step in sdk_sequence],
            },
            timeout_ms=60000,
        )
        return self.hub.dispatch_command(command, robot_url=robot_url or self.robot_url, execute=execute, scenario_id="g1_sdk_sequence", space_id="cooling_zone_01")


class TongyuHardware:
    """Convenience facade for all current Tongyu hardware capabilities."""

    def __init__(
        self,
        hub_url: str | None = None,
        *,
        spray_gateway_url: str | None = None,
        g1_robot_url: str = "http://192.168.1.104:8731",
        timeout: float = 8.0,
    ) -> None:
        self.hub = HubClient(hub_url, timeout=timeout)
        self.spray = SprayClient(self.hub, gateway_url=spray_gateway_url or os.environ.get("TONGYU_SPRAY_GATEWAY_URL"))
        self.lights = LightsClient(self.hub)
        self.projection = ProjectionClient(self.hub)
        self.speaker = SpeakerClient(self.hub)
        self.g1 = G1Client(self.hub, robot_url=g1_robot_url)

    def health(self) -> dict[str, Any]:
        return self.hub.health()
