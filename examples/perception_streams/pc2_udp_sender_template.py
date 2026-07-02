"""PC2-side template for sending encoded RGB/depth frames to the local hub."""

from __future__ import annotations

import socket
import struct


TARGET_IP = "192.168.1.50"
TARGET_PORT = 5005
MAX_PAYLOAD_BYTES = 60000
HEADER = struct.Struct("!I B H H")


def send_encoded_image(
    sock: socket.socket,
    frame_id: int,
    img_type: int,
    encoded_bytes: bytes,
    target_ip: str = TARGET_IP,
    target_port: int = TARGET_PORT,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> None:
    chunks = [
        encoded_bytes[pos : pos + max_payload_bytes]
        for pos in range(0, len(encoded_bytes), max_payload_bytes)
    ]
    total = len(chunks)
    if total > 65535:
        raise ValueError("encoded image is too large for uint16 chunk count")
    for idx, chunk in enumerate(chunks):
        header = HEADER.pack(frame_id, img_type, idx, total)
        sock.sendto(header + chunk, (target_ip, target_port))


def demo_send_test_frame() -> None:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[:, :, 1] = 180
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("failed to encode demo image")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        send_encoded_image(sock, frame_id=1, img_type=0, encoded_bytes=encoded.tobytes())


if __name__ == "__main__":
    demo_send_test_frame()
