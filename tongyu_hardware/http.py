"""Small stdlib HTTP JSON client."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HardwareHttpError(RuntimeError):
    """Raised when an HTTP request fails."""


def http_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: float = 8.0,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request_headers.update(headers or {})
    request = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HardwareHttpError(f"HTTP {exc.code} {url}: {raw[:800]}") from exc
    except URLError as exc:
        raise HardwareHttpError(f"Network error {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise HardwareHttpError(f"Invalid JSON from {url}: {exc}") from exc


def add_query(url: str, params: Mapping[str, Any]) -> str:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    if not query:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{query}"
