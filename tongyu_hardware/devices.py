"""High-level device clients for Tongyu hardware."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

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

PROJECTION_PLAYBACK_ACTIONS = {
    ("library_vertical", "play"): "lan_cmd_015",
    ("library_vertical", "pause"): "lan_cmd_016",
    ("library_vertical", "resume"): "lan_cmd_017",
    ("library_vertical", "stop"): "lan_cmd_018",
    ("library_vertical", "volume_up"): "lan_cmd_035",
    ("library_vertical", "volume_down"): "lan_cmd_036",
    ("library_vertical", "mute"): "lan_cmd_037",
    ("library_vertical", "unmute"): "lan_cmd_038",
    ("library_horizontal", "play"): "lan_cmd_023",
    ("library_horizontal", "pause"): "lan_cmd_024",
    ("library_horizontal", "resume"): "lan_cmd_025",
    ("library_horizontal", "stop"): "lan_cmd_033",
    ("library_horizontal", "volume_up"): "lan_cmd_026",
    ("library_horizontal", "volume_down"): "lan_cmd_034",
    ("library_horizontal", "mute"): "lan_cmd_039",
    ("library_horizontal", "unmute"): "lan_cmd_040",
    ("d_wall", "play"): "lan_cmd_027",
    ("d_wall", "pause"): "lan_cmd_028",
    ("d_wall", "resume"): "lan_cmd_029",
    ("d_wall", "stop"): "lan_cmd_030",
    ("d_wall", "volume_up"): "lan_cmd_031",
    ("d_wall", "volume_down"): "lan_cmd_032",
    ("d_wall", "mute"): "lan_cmd_041",
    ("d_wall", "unmute"): "lan_cmd_042",
}

G1_BASIC_CHAIN = ["g1_safety_check", "g1_speak_notice", "g1_move_probe", "g1_report_ready"]

G1_ARM_ACTIONS = {
    "release arm": 0,
    "shake hand": 1,
    "high five": 2,
    "hug": 3,
    "high wave": 4,
    "clap": 5,
    "face wave": 6,
    "left kiss": 7,
    "heart": 8,
    "right heart": 9,
    "hands up": 10,
    "x-ray": 11,
    "right hand up": 12,
    "reject": 13,
    "right kiss": 14,
    "two-hand kiss": 15,
}

G1_RELEASE_AFTER_ACTIONS = {
    "shake hand",
    "high five",
    "hug",
    "heart",
    "right heart",
    "hands up",
    "x-ray",
    "right hand up",
    "reject",
}

G1_TEST_ACTIONS_10 = [
    "release arm",
    "shake hand",
    "high five",
    "high wave",
    "clap",
    "face wave",
    "heart",
    "right heart",
    "hands up",
    "right hand up",
]


def _resolve_g1_arm_action(action: str | int) -> tuple[str, int]:
    if isinstance(action, int) or str(action).strip().isdigit():
        action_id = int(action)
        for name, mapped_id in G1_ARM_ACTIONS.items():
            if mapped_id == action_id:
                return name, action_id
        raise KeyError(f"unknown G1 arm action id: {action}")
    name = str(action).strip().lower().replace("_", " ")
    if name not in G1_ARM_ACTIONS:
        raise KeyError(f"unknown G1 arm action: {action}")
    return name, G1_ARM_ACTIONS[name]


def _g1_arm_step(action_name: str, action_id: int) -> dict[str, Any]:
    return {
        "primitive": "unitree_sdk_call",
        "source_primitive": "arm_action",
        "layer": "unitree_arm",
        "client": "G1ArmActionClient",
        "method": "ExecuteAction",
        "args": {
            "action_name": action_name,
            "action_id": action_id,
            "action_map_key": action_name,
        },
    }


def _g1_sleep_step(seconds: float) -> dict[str, Any]:
    return {
        "primitive": "unitree_sdk_call",
        "source_primitive": "sleep",
        "layer": "bridge",
        "client": "BridgeRuntime",
        "method": "Sleep",
        "args": {"seconds": seconds},
    }


def _g1_safety_step(safety: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "primitive": "unitree_sdk_call",
        "source_primitive": "safety_check",
        "layer": "bridge",
        "client": "SafetyGuard",
        "method": "CheckPreconditions",
        "args": dict(safety or {"dry_run": True, "min_human_distance_m": 0.8, "speed_limit_mps": 0.25}),
    }


def _g1_report_ready_step() -> dict[str, Any]:
    return {
        "primitive": "unitree_sdk_call",
        "source_primitive": "report_ready",
        "layer": "feedback",
        "client": "FeedbackAdapter",
        "method": "ReportReady",
        "args": {"status": "ready"},
    }


def _number_steps(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    numbered = []
    for seq, step in enumerate(steps, start=1):
        cloned = dict(step)
        cloned.setdefault("seq", seq)
        cloned.setdefault("step", seq)
        numbered.append(cloned)
    return numbered


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

    def playback(self, screen: str, action: str, *, real_send: bool = False, direct: bool = False) -> dict[str, Any]:
        action_id = PROJECTION_PLAYBACK_ACTIONS[(screen, action)]
        if direct:
            return send_registry_command(action_id, dry_run=not real_send)
        return self.hub.dispatch_sequence(
            [action_id],
            raw_lan_dry_run=not real_send,
            allow_raw_lan_send=real_send,
            raw_lan_probe=True,
            scenario_id="projection_playback_control",
            space_id="field_lan_control",
        )


class SpeakerClient:
    def __init__(self, hub: HubClient, *, gateway_url: str | None = None) -> None:
        self.hub = hub
        self.gateway_url = gateway_url.rstrip("/") if gateway_url else None

    def _routing_overrides(self) -> dict[str, Any]:
        if not self.gateway_url:
            return {}
        return {"speaker_gateway": {"direct_http": self.gateway_url}}

    def library(self) -> dict[str, Any]:
        return self.hub.speaker_library()

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
        return self.hub.dispatch_command(
            command,
            routing_overrides=self._routing_overrides(),
            execute=execute,
            scenario_id="speaker_control",
            space_id="sound_cocktail_zone_01",
        )

    def stop(self, *, task_id: str | None = None, execute: bool = True) -> dict[str, Any]:
        command = device_command(
            target_id="speaker_gateway",
            target_type="speaker_gateway",
            command_type="speaker.stop",
            params={"task_id": task_id or new_task_id("speaker_stop"), "op": "stop"},
            timeout_ms=15000,
        )
        return self.hub.dispatch_command(
            command,
            routing_overrides=self._routing_overrides(),
            execute=execute,
            scenario_id="speaker_control",
            space_id="sound_cocktail_zone_01",
        )


class G1Client:
    def __init__(self, hub: HubClient, *, robot_url: str = "http://192.168.1.172:8731") -> None:
        self.hub = hub
        self.robot_url = robot_url.rstrip("/")

    def action_table(self) -> dict[str, Any]:
        return self.hub.g1_actions()

    def gateway_health(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_health(robot_url=robot_url or self.robot_url)

    def gateway_status(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_status(robot_url=robot_url or self.robot_url)

    def speak(self, text: str, *, speaker_id: str = "0", robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command(
            "speech",
            "speak",
            {"text": text, "speaker_id": speaker_id},
            robot_url=robot_url or self.robot_url,
        )

    def gateway_arm_action(
        self,
        action: str | int | None = None,
        *,
        packet: str | None = None,
        robot_url: str | None = None,
    ) -> dict[str, Any]:
        if packet is None:
            if action is None:
                raise ValueError("action or packet is required")
            if isinstance(action, int) or str(action).strip().isdigit():
                action_name, action_id = _resolve_g1_arm_action(int(action))
                packet = str(action_id)
            else:
                action_name, action_id = _resolve_g1_arm_action(str(action))
                packet = f"name:{action_name}"
        else:
            action_name, action_id = "", None
        return self.hub.robot_host_command(
            "motion",
            "arm_action",
            {"action_packet": packet, "action_name": action_name, "action_id": action_id},
            robot_url=robot_url or self.robot_url,
        )

    def navigate(
        self,
        *,
        x: float,
        y: float,
        yaw: float = 0.0,
        frame: str = "map",
        robot_url: str | None = None,
    ) -> dict[str, Any]:
        return self.hub.robot_host_command(
            "navigation",
            "goto",
            {"x": str(x), "y": str(y), "yaw": str(yaw), "frame": frame},
            robot_url=robot_url or self.robot_url,
        )

    def video_start(self, *, ttl_sec: int = 600, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("video", "start", {"ttl_sec": ttl_sec}, robot_url=robot_url or self.robot_url)

    def video_stop(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("video", "stop", {}, robot_url=robot_url or self.robot_url)

    def video_status(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("video", "status", {}, robot_url=robot_url or self.robot_url)

    def mic_start(self, *, ttl_sec: int = 600, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("audio", "mic_start", {"ttl_sec": ttl_sec}, robot_url=robot_url or self.robot_url)

    def mic_stop(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("audio", "mic_stop", {}, robot_url=robot_url or self.robot_url)

    def mic_status(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("audio", "mic_status", {}, robot_url=robot_url or self.robot_url)

    def asr_start(self, *, ttl_sec: int = 600, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("asr", "start", {"ttl_sec": ttl_sec}, robot_url=robot_url or self.robot_url)

    def asr_stop(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("asr", "stop", {}, robot_url=robot_url or self.robot_url)

    def asr_status(self, *, robot_url: str | None = None) -> dict[str, Any]:
        return self.hub.robot_host_command("asr", "status", {}, robot_url=robot_url or self.robot_url)

    def execute_arm_actions(
        self,
        actions: Sequence[str | int],
        *,
        bridge_url: str | None = None,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
        release_after_sec: float = 2.0,
        timeout_sec: float = 10.0,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        return self.hub.execute_g1_actions(
            list(actions),
            bridge_url=bridge_url or self.robot_url,
            network_interface=network_interface,
            dry_run=dry_run,
            real_send=real_send,
            release_after_sec=release_after_sec,
            timeout_sec=timeout_sec,
            task_id=task_id,
        )

    def basic_test(
        self,
        *,
        robot_url: str | None = None,
        execute: bool = True,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
    ) -> dict[str, Any]:
        actions = ["release arm", "high wave", "shake hand"]
        if not execute:
            return self._prepared_g1_action_payload(actions, bridge_url=robot_url or self.robot_url, network_interface=network_interface, dry_run=dry_run, real_send=real_send)
        return self.execute_arm_actions(actions, bridge_url=robot_url or self.robot_url, network_interface=network_interface, dry_run=dry_run, real_send=real_send, task_id=new_task_id("g1_basic"))

    def sdk_sequence(
        self,
        sdk_sequence: list[Mapping[str, Any]],
        *,
        speech_cn: str = "动作链测试开始。",
        robot_url: str | None = None,
        task_id: str | None = None,
        safety: Mapping[str, Any] | None = None,
        execute: bool = True,
    ) -> dict[str, Any]:
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

    def available_arm_actions(self) -> dict[str, int]:
        return dict(G1_ARM_ACTIONS)

    def arm_action(
        self,
        action: str | int,
        *,
        release_after_sec: float | None = None,
        robot_url: str | None = None,
        task_id: str | None = None,
        safety: Mapping[str, Any] | None = None,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
        execute: bool = False,
    ) -> dict[str, Any]:
        action_name, action_id = _resolve_g1_arm_action(action)
        release_delay = 2.0 if release_after_sec is None and action_name in G1_RELEASE_AFTER_ACTIONS else (release_after_sec or 0)
        if execute:
            return self.execute_arm_actions(
                [action_name],
                bridge_url=robot_url or self.robot_url,
                network_interface=network_interface,
                dry_run=dry_run,
                real_send=real_send,
                release_after_sec=release_delay,
                task_id=task_id or new_task_id(f"g1_arm_{action_id}"),
            )
        return self._prepared_g1_action_payload(
            [action_name],
            bridge_url=robot_url or self.robot_url,
            network_interface=network_interface,
            dry_run=dry_run,
            real_send=real_send,
            release_after_sec=release_delay,
            task_id=task_id or new_task_id(f"g1_arm_{action_id}"),
        )

    def _legacy_arm_action_sequence(
        self,
        action: str | int,
        *,
        release_after_sec: float | None = None,
        robot_url: str | None = None,
        task_id: str | None = None,
        safety: Mapping[str, Any] | None = None,
        execute: bool = False,
    ) -> dict[str, Any]:
        action_name, action_id = _resolve_g1_arm_action(action)
        steps: list[Mapping[str, Any]] = [_g1_safety_step(safety), _g1_arm_step(action_name, action_id)]
        release_delay = 2.0 if release_after_sec is None and action_name in G1_RELEASE_AFTER_ACTIONS else release_after_sec
        if release_delay is not None and release_delay > 0 and action_name != "release arm":
            steps.append(_g1_sleep_step(release_delay))
            steps.append(_g1_arm_step("release arm", G1_ARM_ACTIONS["release arm"]))
        steps.append(_g1_report_ready_step())
        return self.sdk_sequence(
            _number_steps(steps),
            speech_cn=f"G1 动作测试：{action_name}",
            robot_url=robot_url,
            task_id=task_id or new_task_id(f"g1_arm_{action_id}"),
            safety=safety,
            execute=execute,
        )

    def test_arm_actions_10(
        self,
        *,
        actions: Sequence[str | int] | None = None,
        release_after_sec: float = 2.0,
        robot_url: str | None = None,
        task_id: str | None = None,
        safety: Mapping[str, Any] | None = None,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
        execute: bool = False,
    ) -> dict[str, Any]:
        selected = list(actions or G1_TEST_ACTIONS_10)
        if execute:
            return self.execute_arm_actions(
                selected,
                bridge_url=robot_url or self.robot_url,
                network_interface=network_interface,
                dry_run=dry_run,
                real_send=real_send,
                release_after_sec=release_after_sec,
                task_id=task_id or new_task_id("g1_arm_test10"),
            )
        return self._prepared_g1_action_payload(
            selected,
            bridge_url=robot_url or self.robot_url,
            network_interface=network_interface,
            dry_run=dry_run,
            real_send=real_send,
            release_after_sec=release_after_sec,
            task_id=task_id or new_task_id("g1_arm_test10"),
        )

    def _legacy_test_arm_actions_10(
        self,
        *,
        actions: Sequence[str | int] | None = None,
        release_after_sec: float = 2.0,
        robot_url: str | None = None,
        task_id: str | None = None,
        safety: Mapping[str, Any] | None = None,
        execute: bool = False,
    ) -> dict[str, Any]:
        selected = list(actions or G1_TEST_ACTIONS_10)
        steps: list[Mapping[str, Any]] = [_g1_safety_step(safety)]
        resolved: list[dict[str, Any]] = []
        for action in selected:
            action_name, action_id = _resolve_g1_arm_action(action)
            resolved.append({"name": action_name, "id": action_id})
            steps.append(_g1_arm_step(action_name, action_id))
            if release_after_sec > 0 and action_name in G1_RELEASE_AFTER_ACTIONS:
                steps.append(_g1_sleep_step(release_after_sec))
                steps.append(_g1_arm_step("release arm", G1_ARM_ACTIONS["release arm"]))
        steps.append(_g1_report_ready_step())
        result = self.sdk_sequence(
            _number_steps(steps),
            speech_cn="G1 十项动作测试开始。",
            robot_url=robot_url,
            task_id=task_id or new_task_id("g1_arm_test10"),
            safety=safety,
            execute=execute,
        )
        result["selected_arm_actions"] = resolved
        return result

    def _prepared_g1_action_payload(
        self,
        actions: Sequence[str | int],
        *,
        bridge_url: str | None = None,
        network_interface: str | None = None,
        dry_run: bool = True,
        real_send: bool = False,
        release_after_sec: float = 2.0,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = []
        for action in actions:
            name, action_id = _resolve_g1_arm_action(action)
            resolved.append({"name": name, "id": action_id})
        return {
            "status": "prepared",
            "target": "central_hub",
            "endpoint": "/api/g1/actions/execute",
            "bridge_url": bridge_url or self.robot_url,
            "command_type": "g1.unitree_action",
            "task_id": task_id,
            "actions": resolved,
            "network_interface": network_interface,
            "dry_run": dry_run,
            "real_send": real_send,
            "release_after_sec": release_after_sec,
        }


class TongyuHardware:
    """Convenience facade for all current Tongyu hardware capabilities."""

    def __init__(
        self,
        hub_url: str | None = None,
        *,
        spray_gateway_url: str | None = None,
        speaker_gateway_url: str | None = None,
        g1_robot_url: str = "http://192.168.1.172:8731",
        timeout: float = 8.0,
    ) -> None:
        self.hub = HubClient(hub_url, timeout=timeout)
        self.spray = SprayClient(self.hub, gateway_url=spray_gateway_url or os.environ.get("TONGYU_SPRAY_GATEWAY_URL"))
        self.lights = LightsClient(self.hub)
        self.projection = ProjectionClient(self.hub)
        self.speaker = SpeakerClient(self.hub, gateway_url=speaker_gateway_url or os.environ.get("TONGYU_SPEAKER_GATEWAY_URL"))
        self.g1 = G1Client(self.hub, robot_url=g1_robot_url)

    def health(self) -> dict[str, Any]:
        return self.hub.health()
