"""Perception stream helpers for the Tongyu local hardware SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import socket
import struct
import time
import webbrowser
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


IMAGE_CHUNK_HEADER = struct.Struct("!I B H H")
IMAGE_KIND_BY_TYPE = {
    0: "rgb",
    1: "depth",
}


@dataclass(frozen=True)
class StreamEndpoint:
    """A registered perception stream endpoint."""

    stream_id: str
    label: str
    protocol: str
    host: str
    port: int
    source_host: str | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "label": self.label,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "source_host": self.source_host,
            "note": self.note,
        }


DEFAULT_STREAM_ENDPOINTS = {
    "g1_vision_udp": StreamEndpoint(
        stream_id="g1_vision_udp",
        label="G1 RGB/Depth UDP stream",
        protocol="udp_chunked_image_v1",
        host="0.0.0.0",
        port=5005,
        source_host="192.168.1.172",
        note="PC2 should send RGB/depth chunks to the local hub host on UDP 5005.",
    ),
    "g1_audio_tcp": StreamEndpoint(
        stream_id="g1_audio_tcp",
        label="G1 raw microphone TCP stream",
        protocol="tcp_raw_audio_chunks",
        host="0.0.0.0",
        port=6000,
        source_host="192.168.1.172",
        note="Robot host should connect to the central hub and stream raw audio chunks to TCP 6000.",
    ),
    "g1_asr_text": StreamEndpoint(
        stream_id="g1_asr_text",
        label="G1 dialogue speech-to-text stream",
        protocol="http_json",
        host="192.168.1.50",
        port=8798,
        source_host="192.168.1.172",
        note="Robot host should POST ASR text records with start/end timestamps to /api/perception/asr/text.",
    ),
}


class StreamRegistry:
    """Small local registry so visual/audio streams can be managed together."""

    def __init__(self, endpoints: dict[str, StreamEndpoint] | None = None) -> None:
        self._endpoints = dict(endpoints or DEFAULT_STREAM_ENDPOINTS)

    def list(self) -> list[dict[str, Any]]:
        return [endpoint.as_dict() for endpoint in self._endpoints.values()]

    def get(self, stream_id: str) -> StreamEndpoint:
        return self._endpoints[stream_id]

    def register(self, endpoint: StreamEndpoint) -> None:
        self._endpoints[endpoint.stream_id] = endpoint


@dataclass
class StreamFrame:
    stream_id: str
    frame_id: int
    img_type: int
    kind: str
    source: tuple[str, int]
    payload: bytes
    first_chunk_at: float
    completed_at: float
    chunks_total: int
    bytes_len: int
    decoded: Any = None

    @property
    def assembly_latency_ms(self) -> float:
        return max(0.0, (self.completed_at - self.first_chunk_at) * 1000.0)

    def summary(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "frame_id": self.frame_id,
            "kind": self.kind,
            "img_type": self.img_type,
            "source": f"{self.source[0]}:{self.source[1]}",
            "bytes": self.bytes_len,
            "chunks_total": self.chunks_total,
            "assembly_latency_ms": round(self.assembly_latency_ms, 2),
            "completed_at": self.completed_at,
            "decoded": self.decoded is not None,
        }


@dataclass
class _FrameBuffer:
    frame_id: int
    img_type: int
    total: int
    source: tuple[str, int]
    first_chunk_at: float
    last_chunk_at: float
    chunks: list[bytes | None] = field(default_factory=list)
    received_count: int = 0


class UdpChunkedImageReceiver:
    """Receiver for PC2's current UDP RGB/depth image protocol."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5005,
        stream_id: str = "g1_vision_udp",
        stale_timeout_sec: float = 2.0,
        socket_timeout_sec: float = 0.25,
        max_datagram_size: int = 65535,
    ) -> None:
        self.host = host
        self.port = port
        self.stream_id = stream_id
        self.stale_timeout_sec = stale_timeout_sec
        self.max_datagram_size = max_datagram_size
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(socket_timeout_sec)
        self.socket.bind((host, port))
        self._buffers: dict[tuple[int, int], _FrameBuffer] = {}
        self.frames_completed = 0
        self.packets_received = 0
        self.malformed_packets = 0
        self.stale_frames_dropped = 0
        self.last_frame_at: float | None = None

    def close(self) -> None:
        self.socket.close()

    def __enter__(self) -> "UdpChunkedImageReceiver":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def stats(self) -> dict[str, Any]:
        now = time.time()
        return {
            "stream_id": self.stream_id,
            "host": self.host,
            "port": self.port,
            "frames_completed": self.frames_completed,
            "packets_received": self.packets_received,
            "malformed_packets": self.malformed_packets,
            "stale_frames_dropped": self.stale_frames_dropped,
            "open_buffers": len(self._buffers),
            "last_frame_age_ms": None if self.last_frame_at is None else round((now - self.last_frame_at) * 1000.0, 2),
        }

    def recv_frame(self, timeout_sec: float | None = None, decode: bool = False) -> StreamFrame | None:
        deadline = None if timeout_sec is None else time.time() + timeout_sec
        while True:
            self._drop_stale_buffers()
            if deadline is not None and time.time() >= deadline:
                return None
            try:
                data, addr = self.socket.recvfrom(self.max_datagram_size)
            except socket.timeout:
                if deadline is not None and time.time() >= deadline:
                    return None
                continue
            frame = self._accept_packet(data, addr, decode=decode)
            if frame is not None:
                return frame

    def iter_frames(self, decode: bool = False) -> Iterator[StreamFrame]:
        while True:
            frame = self.recv_frame(timeout_sec=None, decode=decode)
            if frame is not None:
                yield frame

    def _accept_packet(self, data: bytes, addr: tuple[str, int], decode: bool = False) -> StreamFrame | None:
        if len(data) < IMAGE_CHUNK_HEADER.size:
            self.malformed_packets += 1
            return None
        self.packets_received += 1
        try:
            frame_id, img_type, idx, total = IMAGE_CHUNK_HEADER.unpack(data[: IMAGE_CHUNK_HEADER.size])
        except struct.error:
            self.malformed_packets += 1
            return None
        if total <= 0 or idx >= total:
            self.malformed_packets += 1
            return None

        now = time.time()
        key = (frame_id, img_type)
        buffer = self._buffers.get(key)
        if buffer is None:
            buffer = _FrameBuffer(
                frame_id=frame_id,
                img_type=img_type,
                total=total,
                source=addr,
                first_chunk_at=now,
                last_chunk_at=now,
                chunks=[None] * total,
            )
            self._buffers[key] = buffer
        elif buffer.total != total:
            self.malformed_packets += 1
            return None

        if buffer.chunks[idx] is None:
            buffer.received_count += 1
        buffer.chunks[idx] = data[IMAGE_CHUNK_HEADER.size :]
        buffer.last_chunk_at = now

        if buffer.received_count < buffer.total:
            return None

        payload = b"".join(chunk for chunk in buffer.chunks if chunk is not None)
        del self._buffers[key]
        decoded = decode_image(payload, img_type) if decode else None
        frame = StreamFrame(
            stream_id=self.stream_id,
            frame_id=frame_id,
            img_type=img_type,
            kind=IMAGE_KIND_BY_TYPE.get(img_type, f"type_{img_type}"),
            source=buffer.source,
            payload=payload,
            first_chunk_at=buffer.first_chunk_at,
            completed_at=time.time(),
            chunks_total=buffer.total,
            bytes_len=len(payload),
            decoded=decoded,
        )
        self.frames_completed += 1
        self.last_frame_at = frame.completed_at
        return frame

    def _drop_stale_buffers(self) -> None:
        if not self._buffers:
            return
        now = time.time()
        stale_keys = [
            key
            for key, buffer in self._buffers.items()
            if now - buffer.last_chunk_at > self.stale_timeout_sec
        ]
        for key in stale_keys:
            del self._buffers[key]
            self.stale_frames_dropped += 1


def decode_image(payload: bytes, img_type: int) -> Any:
    cv2, np = _require_cv2_numpy()
    arr = np.frombuffer(payload, dtype=np.uint8)
    flags = cv2.IMREAD_COLOR if img_type == 0 else cv2.IMREAD_UNCHANGED
    return cv2.imdecode(arr, flags)


def depth_to_color(depth: Any) -> Any:
    cv2, _np = _require_cv2_numpy()
    return cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.03), cv2.COLORMAP_JET)


def probe_vision_stream(host: str = "0.0.0.0", port: int = 5005, timeout_sec: float = 5.0) -> dict[str, Any]:
    with UdpChunkedImageReceiver(host=host, port=port) as receiver:
        frame = receiver.recv_frame(timeout_sec=timeout_sec, decode=False)
        result = {
            "status": "timeout" if frame is None else "ok",
            "listen": f"udp://{host}:{port}",
            "timeout_sec": timeout_sec,
            "stats": receiver.stats(),
        }
        if frame is not None:
            result["frame"] = frame.summary()
        return result


def probe_hub_vision_stream(hub_url: str = "http://192.168.1.50:8798", timeout_sec: float = 5.0) -> dict[str, Any]:
    hub_url = hub_url.rstrip("/")
    deadline = time.time() + timeout_sec
    last_status: dict[str, Any] | None = None
    last_error: str | None = None
    while time.time() < deadline:
        try:
            last_status = _read_json_url(f"{hub_url}/api/perception/vision/status", timeout=1.5)
            if last_status.get("latest"):
                return {"status": "ok", "hub_url": hub_url, "vision_status": last_status}
        except (OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    return {
        "status": "timeout",
        "hub_url": hub_url,
        "timeout_sec": timeout_sec,
        "last_error": last_error,
        "vision_status": last_status,
    }


def open_hub_vision_monitor_page(hub_url: str = "http://192.168.1.50:8798") -> dict[str, Any]:
    url = f"{hub_url.rstrip('/')}/vision-monitor"
    opened = webbrowser.open(url)
    return {"status": "opened" if opened else "open_requested", "url": url}


def run_vision_monitor(
    host: str = "0.0.0.0",
    port: int = 5005,
    save_dir: str | None = None,
    show_depth: bool = True,
) -> None:
    cv2, _np = _require_cv2_numpy()
    save_path = Path(save_dir) if save_dir else None
    if save_path:
        save_path.mkdir(parents=True, exist_ok=True)

    last_summary: dict[str, Any] | None = None
    with UdpChunkedImageReceiver(host=host, port=port) as receiver:
        print(f"Listening for G1 vision stream on udp://{host}:{port}. Press ESC or q to quit.")
        while True:
            frame = receiver.recv_frame(timeout_sec=0.05, decode=True)
            if frame is not None:
                last_summary = frame.summary()
                image = frame.decoded
                if image is not None and not (frame.kind == "depth" and not show_depth):
                    window_name = "G1 RGB" if frame.kind == "rgb" else "G1 Depth"
                    display = depth_to_color(image) if frame.kind == "depth" else image
                    _draw_overlay(display, frame, receiver.stats())
                    cv2.imshow(window_name, display)
                    if save_path:
                        suffix = "jpg" if frame.kind == "rgb" else "png"
                        cv2.imwrite(str(save_path / f"{frame.kind}_{frame.frame_id}.{suffix}"), image)
                print(json.dumps({"frame": frame.summary(), "stats": receiver.stats()}, ensure_ascii=False))

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if frame is None and last_summary is None:
                time.sleep(0.01)
    cv2.destroyAllWindows()


def run_hub_vision_monitor(
    hub_url: str = "http://192.168.1.50:8798",
    poll_interval_sec: float = 0.12,
    save_dir: str | None = None,
    show_depth: bool = True,
) -> None:
    cv2, np = _require_cv2_numpy()
    hub_url = hub_url.rstrip("/")
    save_path = Path(save_dir) if save_dir else None
    if save_path:
        save_path.mkdir(parents=True, exist_ok=True)
    last_seen: dict[str, int] = {}
    print(f"Reading G1 vision stream from central hub {hub_url}. Press ESC or q to quit.")

    while True:
        try:
            status = _read_json_url(f"{hub_url}/api/perception/vision/status", timeout=1.5)
        except (OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "hub_error", "error": str(exc)}, ensure_ascii=False))
            status = {"latest": {}}

        latest = status.get("latest") or {}
        for kind in ("rgb", "depth"):
            if kind == "depth" and not show_depth:
                continue
            summary = latest.get(kind)
            if not isinstance(summary, dict):
                continue
            frame_id = int(summary.get("frame_id") or -1)
            if frame_id < 0 or last_seen.get(kind) == frame_id:
                continue
            try:
                raw = _read_bytes_url(f"{hub_url}/api/perception/vision/latest/{kind}?t={time.time()}", timeout=2.0)
            except (OSError, HTTPError, URLError, TimeoutError) as exc:
                print(json.dumps({"status": "image_fetch_error", "kind": kind, "error": str(exc)}, ensure_ascii=False))
                continue
            arr = np.frombuffer(raw, dtype=np.uint8)
            flags = cv2.IMREAD_COLOR if kind == "rgb" else cv2.IMREAD_UNCHANGED
            image = cv2.imdecode(arr, flags)
            if image is None:
                continue
            display = depth_to_color(image) if kind == "depth" else image
            _draw_summary_overlay(display, summary, status)
            cv2.imshow("G1 RGB" if kind == "rgb" else "G1 Depth", display)
            if save_path:
                suffix = "jpg" if kind == "rgb" else "png"
                cv2.imwrite(str(save_path / f"{kind}_{frame_id}.{suffix}"), image)
            last_seen[kind] = frame_id
            print(json.dumps({"frame": summary, "status": {k: v for k, v in status.items() if k != "latest"}}, ensure_ascii=False))

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        time.sleep(poll_interval_sec)
    cv2.destroyAllWindows()


def _draw_overlay(image: Any, frame: StreamFrame, stats: dict[str, Any]) -> None:
    cv2, _np = _require_cv2_numpy()
    text = (
        f"{frame.kind} frame={frame.frame_id} "
        f"source={frame.source[0]} assembly={frame.assembly_latency_ms:.1f}ms "
        f"open={stats['open_buffers']} stale={stats['stale_frames_dropped']}"
    )
    cv2.putText(image, text, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(image, text, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_summary_overlay(image: Any, summary: dict[str, Any], status: dict[str, Any]) -> None:
    cv2, _np = _require_cv2_numpy()
    text = (
        f"{summary.get('kind')} frame={summary.get('frame_id')} "
        f"source={summary.get('source')} assembly={summary.get('assembly_latency_ms')}ms "
        f"age={status.get('last_frame_age_ms')}ms"
    )
    cv2.putText(image, text, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(image, text, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)


def _read_json_url(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _read_bytes_url(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        return response.read()


def _require_cv2_numpy() -> tuple[Any, Any]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Vision stream decoding needs opencv-python and numpy. "
            "Install with: pip install -e .[stream]"
        ) from exc
    return cv2, np
