"""Start the Urban Agent frontend and then enter the Urban-Hermes CLI.

Run from the repository root:

    python scripts/start_urban_agent_workspace.py --toolsets urban,todo,memory,delegation

Any unknown arguments are forwarded to ``python -m urban_hermes.launcher``.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from urllib.parse import quote
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = ROOT / "hermes_urban_agent"
DEFAULT_STATE = "experiments/case2_process_materials_rerun_20260527_020009/route_tree_frontend_state.json"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


def _start_static_server(port: int) -> ThreadingHTTPServer | None:
    if _port_is_open(port):
        print(f"[urban-agent] Frontend server already available on http://localhost:{port}")
        return None
    handler = partial(QuietStaticHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, name="urban-agent-frontend", daemon=True)
    thread.start()
    print(f"[urban-agent] Frontend server started on http://localhost:{port}")
    return server


def _frontend_url(port: int, state: str) -> str:
    base = f"http://localhost:{port}/frontend/urban_hermes_route_viewer/index.html"
    if not state:
        return base
    return f"{base}?state={quote(state.replace(os.sep, '/'), safe='/._-:')}"


def _cli_env(port: int) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    paths = [str(ADAPTER_ROOT)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["URBAN_HERMES_FRONTEND_PORT"] = str(port)
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start the Urban Agent route-state frontend and launch Urban-Hermes CLI.",
        add_help=True,
    )
    parser.add_argument("--port", type=int, default=8017, help="Frontend HTTP port.")
    parser.add_argument("--state", default=DEFAULT_STATE, help="Route frontend state path to open first.")
    parser.add_argument("--no-browser", action="store_true", help="Start services without opening a browser tab.")
    args, cli_args = parser.parse_known_args(argv)

    server = _start_static_server(args.port)
    url = _frontend_url(args.port, args.state)
    print(f"[urban-agent] Frontend URL: {url}")
    if not args.no_browser:
        webbrowser.open(url)

    command = [sys.executable, "-m", "urban_hermes.launcher", *cli_args]
    print(f"[urban-agent] CLI command: {' '.join(command)}")
    print("[urban-agent] During a run, urban_route_tree will print matching frontend_url values.")
    try:
        return subprocess.call(command, cwd=str(ROOT), env=_cli_env(args.port))
    finally:
        if server is not None:
            server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
