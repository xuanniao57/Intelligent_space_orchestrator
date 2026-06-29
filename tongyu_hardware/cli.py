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
    parser.add_argument("--g1-robot-url", default=os.environ.get("TONGYU_G1_ROBOT_URL", "http://192.168.1.104:8731"))
    parser.add_argument("--execute", action="store_true", help="dispatch direct HTTP / polling device commands")
    parser.add_argument("--real-send", action="store_true", help="send physical LAN payloads")
    parser.add_argument("--content-id", default="audio_01_music_cocktail_loop")
    parser.add_argument("--video-id", default="video_01_sound_wave_visual")
    parser.add_argument("--projector", default="library_vertical", choices=["library_vertical", "library_horizontal", "d_wall"])
    parser.add_argument("--state", default="on", choices=["on", "off"])
    parser.add_argument(
        "action",
        choices=[
            "health",
            "spray-mist",
            "spray-stop",
            "light-blue",
            "light-off",
            "speaker-play",
            "speaker-stop",
            "projection-play",
            "projection-stop",
            "projection-power",
            "g1-basic",
        ],
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    hw = TongyuHardware(
        args.hub_url,
        spray_gateway_url=args.spray_gateway_url,
        g1_robot_url=args.g1_robot_url,
    )

    if args.action == "health":
        print_json(hw.health())
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
    elif args.action == "projection-play":
        print_json(hw.projection.play(content_id=args.video_id, slot=1, loop=True, execute=args.execute))
    elif args.action == "projection-stop":
        print_json(hw.projection.stop(execute=args.execute))
    elif args.action == "projection-power":
        print_json(hw.projection.power(args.projector, args.state, real_send=args.real_send))
    elif args.action == "g1-basic":
        print_json(hw.g1.basic_test(execute=args.execute))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
