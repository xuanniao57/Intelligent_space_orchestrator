"""Minimal local visualizer for the G1 RGB/depth stream."""

from __future__ import annotations

from tongyu_hardware.streams import run_vision_monitor


if __name__ == "__main__":
    run_vision_monitor(host="0.0.0.0", port=5005)
