"""Lightweight G1 control lease for user-side Python scripts."""

from __future__ import annotations

import threading
import time
from types import TracebackType
from typing import Any

from .hub import HubClient


class G1ControlSession:
    """Lease a G1 control slot from the central hub.

    This does not replace the Unitree SDK. It records and maintains a safety
    lease so the central hub can enforce concurrency and reclaim idle control
    channels. The actual SDK calls can remain in the user's script.
    """

    def __init__(
        self,
        *,
        hub_url: str | None = None,
        owner: str | None = None,
        client_id: str | None = None,
        purpose: str = "manual_g1_control",
        ttl_sec: int = 600,
        idle_timeout_sec: int | None = None,
        heartbeat_interval_sec: float = 5.0,
        dry_run: bool = True,
        real_control: bool = False,
        hub: HubClient | None = None,
    ) -> None:
        self.hub = hub or HubClient(hub_url)
        self.owner = owner
        self.client_id = client_id
        self.purpose = purpose
        self.ttl_sec = ttl_sec
        self.idle_timeout_sec = idle_timeout_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.dry_run = dry_run
        self.real_control = real_control
        self.session: dict[str, Any] | None = None
        self.session_id = ""
        self.token = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "G1ControlSession":
        response = self.hub.create_g1_session(
            owner=self.owner,
            client_id=self.client_id,
            purpose=self.purpose,
            ttl_sec=self.ttl_sec,
            idle_timeout_sec=self.idle_timeout_sec,
            dry_run=self.dry_run,
            real_control=self.real_control,
        )
        self.session = response.get("session") or {}
        self.session_id = str(self.session.get("session_id") or "")
        self.token = str(self.session.get("token") or "")
        if not self.session_id or not self.token:
            raise RuntimeError(f"invalid G1 session response: {response}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="tongyu-g1-session-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close(reason="exception" if exc else "normal_exit")

    def heartbeat(self, message: str = "heartbeat") -> dict[str, Any]:
        if not self.session_id or not self.token:
            raise RuntimeError("G1 session is not active")
        return self.hub.heartbeat_g1_session(self.session_id, self.token, message=message)

    def close(self, *, reason: str = "client_release") -> dict[str, Any] | None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if not self.session_id or not self.token:
            return None
        try:
            return self.hub.release_g1_session(self.session_id, self.token, reason=reason)
        finally:
            self.session_id = ""
            self.token = ""

    def _heartbeat_loop(self) -> None:
        interval = max(2.0, float(self.heartbeat_interval_sec))
        while not self._stop.wait(interval):
            try:
                self.heartbeat()
            except Exception:
                # User code may still clean up in __exit__; avoid killing the
                # user's robot script from a background heartbeat error.
                return


def g1_control_session(**kwargs: Any) -> G1ControlSession:
    return G1ControlSession(**kwargs)
