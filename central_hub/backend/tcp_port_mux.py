#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCP port multiplexer for the field deployment.

The physical site wants one externally visible endpoint:

    192.168.1.50:8798

HTTP/WebSocket traffic should still reach the central Flask hub, while the
GemeOpen smart plug connects to the same port using a raw TCP JSON stream. This
small proxy keeps that external contract and routes traffic by peer IP/protocol:

    browser/client HTTP -> 127.0.0.1:8799
    smart plug TCP      -> 127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from typing import Iterable, Optional, Tuple


HTTP_PREFIXES = (
    b"GET ",
    b"POST ",
    b"PUT ",
    b"PATCH ",
    b"DELETE ",
    b"HEAD ",
    b"OPTIONS ",
    b"CONNECT ",
)


def parse_peer_ips(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def is_http_payload(data: bytes) -> bool:
    if not data:
        return False
    upper = data[:16].upper()
    return upper.startswith(HTTP_PREFIXES)


def close_quietly(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class PortMultiplexer:
    def __init__(
        self,
        listen: Tuple[str, int],
        http_target: Tuple[str, int],
        plug_target: Tuple[str, int],
        plug_peer_ips: Iterable[str],
        peek_timeout: float = 1.2,
    ) -> None:
        self.listen = listen
        self.http_target = http_target
        self.plug_target = plug_target
        self.plug_peer_ips = set(plug_peer_ips)
        self.peek_timeout = peek_timeout
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(self.listen)
            server.listen(128)
            logging.info(
                "listening on %s:%s; http -> %s:%s; plug -> %s:%s; plug peers=%s",
                self.listen[0],
                self.listen[1],
                self.http_target[0],
                self.http_target[1],
                self.plug_target[0],
                self.plug_target[1],
                ",".join(sorted(self.plug_peer_ips)) or "any non-http",
            )
            while not self._stop.is_set():
                client, address = server.accept()
                thread = threading.Thread(target=self.handle_client, args=(client, address), daemon=True)
                thread.start()

    def handle_client(self, client: socket.socket, address: Tuple[str, int]) -> None:
        peer_ip = address[0]
        initial = b""
        route = "plug" if peer_ip in self.plug_peer_ips else None

        if route is None:
            client.settimeout(self.peek_timeout)
            try:
                initial = client.recv(4096)
            except socket.timeout:
                initial = b""
            except OSError as exc:
                logging.warning("failed to read from %s:%s: %s", address[0], address[1], exc)
                close_quietly(client)
                return
            finally:
                client.settimeout(None)
            route = "http" if is_http_payload(initial) or not initial else "plug"

        target = self.plug_target if route == "plug" else self.http_target
        try:
            upstream = socket.create_connection(target, timeout=5.0)
        except OSError as exc:
            logging.warning(
                "failed to connect %s peer %s:%s to %s:%s: %s",
                route,
                address[0],
                address[1],
                target[0],
                target[1],
                exc,
            )
            close_quietly(client)
            return

        logging.info("%s:%s -> %s -> %s:%s", address[0], address[1], route, target[0], target[1])
        try:
            if initial:
                upstream.sendall(initial)
            t1 = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
            t2 = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        finally:
            close_quietly(client)
            close_quietly(upstream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tongyu 8798 HTTP/raw-TCP multiplexer")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8798)
    parser.add_argument("--http-target-host", default="127.0.0.1")
    parser.add_argument("--http-target-port", type=int, default=8799)
    parser.add_argument("--plug-target-host", default="127.0.0.1")
    parser.add_argument("--plug-target-port", type=int, default=8080)
    parser.add_argument("--plug-peer-ips", default="192.168.1.156")
    parser.add_argument("--peek-timeout", type=float, default=1.2)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    mux = PortMultiplexer(
        listen=(args.listen_host, args.listen_port),
        http_target=(args.http_target_host, args.http_target_port),
        plug_target=(args.plug_target_host, args.plug_target_port),
        plug_peer_ips=parse_peer_ips(args.plug_peer_ips),
        peek_timeout=args.peek_timeout,
    )
    mux.serve_forever()


if __name__ == "__main__":
    main()
