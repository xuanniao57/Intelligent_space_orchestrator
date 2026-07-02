"""Command-line smoke tests for the Tongyu hardware SDK."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .devices import TongyuHardware
from .hub import DEFAULT_HUB_URL


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tongyu hardware SDK quickstart")
    parser.add_argument("--hub-url", default=os.environ.get("TONGYU_HUB_URL", DEFAULT_HUB_URL))
    parser.add_argument("--spray-gateway-url", default=os.environ.get("TONGYU_SPRAY_GATEWAY_URL"))
    parser.add_argument("--speaker-gateway-url", default=os.environ.get("TONGYU_SPEAKER_GATEWAY_URL"))
    parser.add_argument("--g1-robot-url", default=os.environ.get("TONGYU_G1_ROBOT_URL", "http://192.168.1.172:8731"))
    parser.add_argument("--stream-host", default=os.environ.get("TONGYU_VISION_STREAM_HOST", "0.0.0.0"))
    parser.add_argument("--stream-port", type=int, default=int(os.environ.get("TONGYU_VISION_STREAM_PORT", "5005")))
    parser.add_argument("--stream-timeout", type=float, default=float(os.environ.get("TONGYU_VISION_STREAM_TIMEOUT", "5.0")))
    parser.add_argument("--stream-save-dir", default=os.environ.get("TONGYU_VISION_STREAM_SAVE_DIR"))
    parser.add_argument("--no-depth", action="store_true", help="do not render the depth window in vision-monitor")
    parser.add_argument("--direct-udp", action="store_true", help="listen to UDP directly instead of reading frames from the central hub")
    parser.add_argument("--opencv-window", action="store_true", help="use OpenCV imshow windows instead of the browser monitor")
    parser.add_argument("--execute", action="store_true", help="dispatch direct HTTP / polling device commands")
    parser.add_argument("--real-send", action="store_true", help="send physical LAN payloads or real G1 SDK actions")
    parser.add_argument("--content-id", default="audio_01_music_cocktail_loop")
    parser.add_argument("--video-id", default="video_01_sound_wave_visual")
    parser.add_argument("--projector", default="library_vertical", choices=["library_vertical", "library_horizontal", "d_wall"])
    parser.add_argument("--screen", default="library_vertical", choices=["library_vertical", "library_horizontal", "d_wall"])
    parser.add_argument("--playback", default="play", choices=["play", "pause", "resume", "stop", "volume_up", "volume_down", "mute", "unmute"])
    parser.add_argument("--state", default="on", choices=["on", "off"])
    parser.add_argument("--g1-action", default="shake hand")
    parser.add_argument("--g1-action-packet", default=None)
    parser.add_argument("--text", default="你好，我已收到中枢命令。")
    parser.add_argument("--speaker-id", default="0")
    parser.add_argument("--nav-x", type=float, default=0.0)
    parser.add_argument("--nav-y", type=float, default=0.0)
    parser.add_argument("--nav-yaw", type=float, default=0.0)
    parser.add_argument("--nav-frame", default="map")
    parser.add_argument("--queue-kind", default="rgb", choices=["rgb", "depth"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--release-after-sec", type=float, default=None)
    parser.add_argument("--owner", default=os.environ.get("USER") or os.environ.get("USERNAME") or "unknown")
    parser.add_argument("--ttl-sec", type=int, default=600)
    parser.add_argument("--idle-timeout-sec", type=int, default=90)
    parser.add_argument(
        "action",
        choices=[
            "health",
            "stream-list",
            "vision-probe",
            "vision-monitor",
            "vision-queue",
            "audio-status",
            "audio-chunks",
            "asr-history",
            "robot-gateway-health",
            "robot-gateway-status",
            "robot-speak",
            "robot-action",
            "robot-nav",
            "robot-video-start",
            "robot-video-stop",
            "robot-video-status",
            "robot-mic-start",
            "robot-mic-stop",
            "robot-mic-status",
            "robot-asr-start",
            "robot-asr-stop",
            "robot-asr-status",
            "g1-session-dryrun",
            "g1-session-real",
            "spray-mist",
            "spray-stop",
            "light-blue",
            "light-off",
            "speaker-play",
            "speaker-stop",
            "speaker-library",
            "projection-play",
            "projection-stop",
            "projection-power",
            "projection-playback",
            "g1-action-table",
            "g1-basic",
            "g1-arm-action",
            "g1-arm-test10",
            "g1-arm-test16",
        ],
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    hw = TongyuHardware(
        args.hub_url,
        spray_gateway_url=args.spray_gateway_url,
        speaker_gateway_url=args.speaker_gateway_url,
        g1_robot_url=args.g1_robot_url,
    )

    if args.action == "health":
        print_json(hw.health())
    elif args.action == "stream-list":
        if args.direct_udp:
            from .streams import StreamRegistry

            print_json({"streams": StreamRegistry().list()})
        else:
            print_json(hw.hub.perception_streams())
    elif args.action == "vision-probe":
        if args.direct_udp:
            from .streams import probe_vision_stream

            print_json(probe_vision_stream(host=args.stream_host, port=args.stream_port, timeout_sec=args.stream_timeout))
        else:
            from .streams import probe_hub_vision_stream

            print_json(probe_hub_vision_stream(hub_url=args.hub_url, timeout_sec=args.stream_timeout))
    elif args.action == "vision-monitor":
        if args.direct_udp:
            from .streams import run_vision_monitor

            run_vision_monitor(
                host=args.stream_host,
                port=args.stream_port,
                save_dir=args.stream_save_dir,
                show_depth=not args.no_depth,
            )
        elif not args.opencv_window:
            from .streams import open_hub_vision_monitor_page, probe_hub_vision_stream

            print_json(open_hub_vision_monitor_page(hub_url=args.hub_url))
            print_json(probe_hub_vision_stream(hub_url=args.hub_url, timeout_sec=args.stream_timeout))
        else:
            from .streams import run_hub_vision_monitor

            run_hub_vision_monitor(
                hub_url=args.hub_url,
                save_dir=args.stream_save_dir,
                show_depth=not args.no_depth,
            )
    elif args.action == "vision-queue":
        print_json(hw.hub.vision_queue(args.queue_kind, limit=args.limit))
    elif args.action == "audio-status":
        print_json(hw.hub.audio_status())
    elif args.action == "audio-chunks":
        print_json(hw.hub.audio_chunks(limit=args.limit))
    elif args.action == "asr-history":
        print_json(hw.hub.asr_history(limit=args.limit))
    elif args.action == "robot-gateway-health":
        print_json(hw.g1.gateway_health(robot_url=args.g1_robot_url))
    elif args.action == "robot-gateway-status":
        print_json(hw.g1.gateway_status(robot_url=args.g1_robot_url))
    elif args.action == "robot-speak":
        print_json(hw.g1.speak(args.text, speaker_id=args.speaker_id, robot_url=args.g1_robot_url))
    elif args.action == "robot-action":
        print_json(hw.g1.gateway_arm_action(args.g1_action, packet=args.g1_action_packet, robot_url=args.g1_robot_url))
    elif args.action == "robot-nav":
        print_json(hw.g1.navigate(x=args.nav_x, y=args.nav_y, yaw=args.nav_yaw, frame=args.nav_frame, robot_url=args.g1_robot_url))
    elif args.action == "robot-video-start":
        print_json(hw.g1.video_start(ttl_sec=args.ttl_sec, robot_url=args.g1_robot_url))
    elif args.action == "robot-video-stop":
        print_json(hw.g1.video_stop(robot_url=args.g1_robot_url))
    elif args.action == "robot-video-status":
        print_json(hw.g1.video_status(robot_url=args.g1_robot_url))
    elif args.action == "robot-mic-start":
        print_json(hw.g1.mic_start(ttl_sec=args.ttl_sec, robot_url=args.g1_robot_url))
    elif args.action == "robot-mic-stop":
        print_json(hw.g1.mic_stop(robot_url=args.g1_robot_url))
    elif args.action == "robot-mic-status":
        print_json(hw.g1.mic_status(robot_url=args.g1_robot_url))
    elif args.action == "robot-asr-start":
        print_json(hw.g1.asr_start(ttl_sec=args.ttl_sec, robot_url=args.g1_robot_url))
    elif args.action == "robot-asr-stop":
        print_json(hw.g1.asr_stop(robot_url=args.g1_robot_url))
    elif args.action == "robot-asr-status":
        print_json(hw.g1.asr_status(robot_url=args.g1_robot_url))
    elif args.action == "g1-session-dryrun":
        print_json(hw.hub.create_g1_session(owner=args.owner, ttl_sec=args.ttl_sec, idle_timeout_sec=args.idle_timeout_sec, dry_run=True, real_control=False))
    elif args.action == "g1-session-real":
        print_json(hw.hub.create_g1_session(owner=args.owner, ttl_sec=args.ttl_sec, idle_timeout_sec=args.idle_timeout_sec, dry_run=False, real_control=True))
    elif args.action == "spray-mist":
        print_json(hw.spray.mist(execute=args.execute))
    elif args.action == "spray-stop":
        print_json(hw.spray.stop(execute=args.execute))
    elif args.action == "light-blue":
        print_json(hw.lights.blue(real_send=args.real_send))
    elif args.action == "light-off":
        print_json(hw.lights.off(real_send=args.real_send))
    elif args.action == "speaker-play":
        print_json(hw.speaker.play(content_id=args.content_id, slot=1, loop=True, execute=args.execute))
    elif args.action == "speaker-stop":
        print_json(hw.speaker.stop(execute=args.execute))
    elif args.action == "speaker-library":
        print_json(hw.speaker.library())
    elif args.action == "projection-play":
        print_json(hw.projection.play(content_id=args.video_id, slot=1, loop=True, execute=args.execute))
    elif args.action == "projection-stop":
        print_json(hw.projection.stop(execute=args.execute))
    elif args.action == "projection-power":
        print_json(hw.projection.power(args.projector, args.state, real_send=args.real_send))
    elif args.action == "projection-playback":
        print_json(hw.projection.playback(args.screen, args.playback, real_send=args.real_send))
    elif args.action == "g1-action-table":
        print_json(hw.g1.action_table())
    elif args.action == "g1-basic":
        print_json(hw.g1.basic_test(execute=args.execute, robot_url=args.g1_robot_url))
    elif args.action == "g1-arm-action":
        print_json(hw.g1.arm_action(args.g1_action, release_after_sec=args.release_after_sec, execute=args.execute, robot_url=args.g1_robot_url))
    elif args.action == "g1-arm-test10":
        print_json(hw.g1.test_arm_actions_10(execute=args.execute, robot_url=args.g1_robot_url))
    elif args.action == "g1-arm-test16":
        print_json(hw.g1.test_arm_actions_10(
            actions=[
                "release arm",
                "shake hand",
                "high five",
                "hug",
                "high wave",
                "clap",
                "face wave",
                "left kiss",
                "heart",
                "right heart",
                "hands up",
                "x-ray",
                "right hand up",
                "reject",
                "right kiss",
                "two-hand kiss",
            ],
            execute=args.execute,
            robot_url=args.g1_robot_url,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
