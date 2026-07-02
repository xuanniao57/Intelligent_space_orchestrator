"""PC2/G1 RealSense RGB + depth UDP sender.

Run this script on the G1-side PC at 192.168.1.172.
It sends encoded RGB/depth image chunks to the central hub receiver.
"""

from __future__ import annotations

import socket
import struct
import time

import cv2
import numpy as np
import pyrealsense2 as rs


CENTRAL_RECEIVER_IP = "192.168.1.50"
CENTRAL_RECEIVER_PORT = 5005

FPS_SEND = 3
MAX_PACKET_BYTES = 60000
HEADER = struct.Struct("!I B H H")


def send_image(sock: socket.socket, img_bytes: bytes, img_type: int, frame_id: int) -> None:
    """Send one encoded image using the Tongyu chunked UDP vision protocol.

    img_type: 0 = RGB JPEG, 1 = depth PNG.
    """
    total = (len(img_bytes) + MAX_PACKET_BYTES - 1) // MAX_PACKET_BYTES
    if total > 65535:
        raise ValueError("encoded image is too large for uint16 packet count")
    for idx in range(total):
        chunk = img_bytes[idx * MAX_PACKET_BYTES : (idx + 1) * MAX_PACKET_BYTES]
        header = HEADER.pack(frame_id, img_type, idx, total)
        sock.sendto(header + chunk, (CENTRAL_RECEIVER_IP, CENTRAL_RECEIVER_PORT))


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pipeline = rs.pipeline()
    config = rs.config()

    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

    pipeline.start(config)
    align = rs.align(rs.stream.color)

    try:
        frame_id = 0
        interval = 1.0 / FPS_SEND
        last_send = 0.0
        print(f"sending RGB/depth stream to {CENTRAL_RECEIVER_IP}:{CENTRAL_RECEIVER_PORT}")

        while True:
            frames = pipeline.wait_for_frames()
            frames = align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if not color_frame or not depth_frame:
                continue

            now = time.time()
            if now - last_send < interval:
                continue
            last_send = now
            frame_id += 1

            color_img = np.asanyarray(color_frame.get_data())
            depth_img = np.asanyarray(depth_frame.get_data())

            ok_color, color_jpg = cv2.imencode(
                ".jpg",
                color_img,
                [cv2.IMWRITE_JPEG_QUALITY, 70],
            )
            ok_depth, depth_png = cv2.imencode(".png", depth_img)
            if not ok_color or not ok_depth:
                continue

            send_image(sock, color_jpg.tobytes(), 0, frame_id)
            send_image(sock, depth_png.tobytes(), 1, frame_id)

            print(
                f"sent frame {frame_id}: "
                f"rgb={len(color_jpg.tobytes())} bytes, "
                f"depth={len(depth_png.tobytes())} bytes"
            )
    finally:
        pipeline.stop()
        sock.close()


if __name__ == "__main__":
    main()
