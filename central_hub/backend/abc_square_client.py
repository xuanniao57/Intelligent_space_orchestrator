"""ABC Square live data client.

The API requires HMAC-SHA256 headers for every /api/v1/* request.  This
module keeps credentials in memory only and never logs secret values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CST = timezone(timedelta(hours=8))
DEFAULT_BASE_URL = "http://58.33.91.82:28002"
EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()

API_KEY_NAMES = ("ABC_SQUARE_API_KEY", "CHONGZHI_API_KEY", "SMART_FIELD_API_KEY", "API_KEY")
API_SECRET_NAMES = ("ABC_SQUARE_API_SECRET", "CHONGZHI_API_SECRET", "SMART_FIELD_API_SECRET", "API_SECRET")
BASE_URL_NAMES = ("ABC_SQUARE_BASE_URL", "CHONGZHI_BASE_URL", "SMART_FIELD_BASE_URL")


class ABCSquareAPIError(RuntimeError):
    """Raised when the upstream ABC Square API cannot satisfy a request."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass
class ABCSquareConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_key_name: Optional[str] = None
    api_secret_name: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def status(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "api_secret_configured": bool(self.api_secret),
            "api_key_env": self.api_key_name,
            "api_secret_env": self.api_secret_name,
            "required_env": ["ABC_SQUARE_API_KEY", "ABC_SQUARE_API_SECRET"],
            "fallback_env": {
                "api_key": [name for name in API_KEY_NAMES if name != "ABC_SQUARE_API_KEY"],
                "api_secret": [name for name in API_SECRET_NAMES if name != "ABC_SQUARE_API_SECRET"],
            },
        }


def _candidate_env_files(project_root: Optional[Path]) -> Iterable[Path]:
    seen = set()
    candidates = []
    if project_root:
        candidates.extend([
            project_root / "central_hub" / ".env",
            project_root / ".env",
            project_root.parent / ".env",
        ])
    candidates.append(Path.cwd() / ".env")
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            yield resolved


def _read_env_file(path: Path, names: Iterable[str]) -> Dict[str, str]:
    wanted = set(names)
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in wanted:
                continue
            value = value.strip().strip('"').strip("'")
            if value:
                values[key] = value
    except UnicodeDecodeError:
        for raw_line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in wanted and value.strip():
                values[key] = value.strip().strip('"').strip("'")
    return values


def _first_configured(names: Iterable[str], file_values: Mapping[str, str]) -> tuple[Optional[str], Optional[str]]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value, name
    for name in names:
        value = file_values.get(name)
        if value:
            return value, name
    return None, None


def load_abc_square_config(project_root: Optional[Path] = None) -> ABCSquareConfig:
    names = set(API_KEY_NAMES + API_SECRET_NAMES + BASE_URL_NAMES)
    file_values: Dict[str, str] = {}
    for env_file in _candidate_env_files(project_root):
        file_values.update(_read_env_file(env_file, names))

    base_url, _ = _first_configured(BASE_URL_NAMES, file_values)
    api_key, api_key_name = _first_configured(API_KEY_NAMES, file_values)
    api_secret, api_secret_name = _first_configured(API_SECRET_NAMES, file_values)
    return ABCSquareConfig(
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        api_key=api_key,
        api_secret=api_secret,
        api_key_name=api_key_name,
        api_secret_name=api_secret_name,
    )


def isoformat_cst(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST)
    return value.astimezone(CST).isoformat(timespec="seconds")


def default_hour_window(hours: int = 1) -> tuple[str, str]:
    hours = max(1, min(int(hours), 24 * 7))
    now = datetime.now(CST)
    end = now.replace(minute=0, second=0, microsecond=0)
    if end >= now:
        end = end - timedelta(hours=1)
    start = end - timedelta(hours=hours)
    return isoformat_cst(start), isoformat_cst(end)


class ABCSquareClient:
    def __init__(self, config: Optional[ABCSquareConfig] = None, timeout_sec: float = 8.0):
        self.config = config or load_abc_square_config()
        self.timeout_sec = timeout_sec

    def status(self) -> Dict[str, Any]:
        return self.config.status()

    def health(self) -> Dict[str, Any]:
        return self._get_json("/health", {}, signed=False)

    def fetch_snapshot(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        hours: int = 1,
    ) -> Dict[str, Any]:
        if not self.config.configured:
            raise ABCSquareAPIError("ABC Square API credentials are not configured", status_code=503)
        if not start_time or not end_time:
            start_time, end_time = default_hour_window(hours)

        return {
            "source": "abc_square_api",
            "fetched_at": isoformat_cst(datetime.now(CST)),
            "window": {"start_time": start_time, "end_time": end_time, "timezone": "Asia/Shanghai"},
            "sources": {
                "environment": self.fetch_environment(start_time, end_time),
                "emotions": self.fetch_emotions(start_time, end_time),
                "population": self.fetch_population(start_time, end_time),
            },
        }

    def fetch_environment(self, start_time: str, end_time: str) -> Dict[str, Any]:
        return self._fetch_hourly("/api/v1/sensors/hourly", start_time, end_time, "environment")

    def fetch_emotions(self, start_time: str, end_time: str) -> Dict[str, Any]:
        return self._fetch_hourly("/api/v1/emotions/hourly", start_time, end_time, "all")

    def fetch_population(self, start_time: str, end_time: str) -> Dict[str, Any]:
        return self._fetch_hourly("/api/v1/population/hourly", start_time, end_time, "all")

    def _fetch_hourly(self, path: str, start_time: str, end_time: str, category: str) -> Dict[str, Any]:
        return self._get_json(path, {
            "start_time": start_time,
            "end_time": end_time,
            "category": category,
        }, signed=True)

    def _get_json(self, path: str, params: Mapping[str, Any], signed: bool) -> Dict[str, Any]:
        canonical_query = urlencode(sorted((key, str(value)) for key, value in params.items()))
        url = f"{self.config.base_url}{path}"
        if canonical_query:
            url = f"{url}?{canonical_query}"

        headers = {"Accept": "application/json"}
        if signed:
            headers.update(self._signed_headers("GET", path, canonical_query))

        request = Request(url, method="GET", headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            payload = _safe_json_error(exc)
            message = payload.get("error") if isinstance(payload, dict) else str(payload)
            raise ABCSquareAPIError(message or f"ABC Square API HTTP {exc.code}", exc.code, payload) from exc
        except URLError as exc:
            raise ABCSquareAPIError(f"ABC Square API network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ABCSquareAPIError("ABC Square API request timed out") from exc
        except json.JSONDecodeError as exc:
            raise ABCSquareAPIError("ABC Square API returned non-JSON response") from exc

    def _signed_headers(self, method: str, path: str, canonical_query: str) -> Dict[str, str]:
        if not self.config.configured:
            raise ABCSquareAPIError("ABC Square API credentials are not configured", status_code=503)
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        payload = "\n".join([method.upper(), path, canonical_query, timestamp, nonce, EMPTY_BODY_SHA256])
        signature = hmac.new(
            self.config.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-Key": self.config.api_key,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }


def _safe_json_error(exc: HTTPError) -> Any:
    try:
        raw = exc.read().decode("utf-8")
        return json.loads(raw) if raw else {}
    except Exception:
        return {"error": f"HTTP {exc.code}"}
