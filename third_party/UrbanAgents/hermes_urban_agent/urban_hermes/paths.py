"""Path bootstrap for the separate Hermes-Urban adapter."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = REPO_ROOT.parent if REPO_ROOT.name == "paper4_urban_svgagent" else REPO_ROOT
VENDORED_HERMES_ROOT = Path(__file__).resolve().parent / "_vendor" / "hermes_runtime"


def _default_hermes_root() -> Path:
    override = os.getenv("URBAN_HERMES_HERMES_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if VENDORED_HERMES_ROOT.exists():
        return VENDORED_HERMES_ROOT.resolve()
    return (PROJECT_ROOT / "hermes-agent").resolve()


HERMES_ROOT = _default_hermes_root()
_default_paper4_root = REPO_ROOT if (REPO_ROOT / "urban_agent").exists() else PROJECT_ROOT / "paper4_urban_svgagent"
PAPER4_ROOT = Path(os.getenv("URBAN_HERMES_URBAN_AGENT_ROOT", _default_paper4_root)).expanduser().resolve()


def _default_urban_home() -> Path:
    return Path(
        os.getenv("URBAN_AGENTS_HOME")
        or os.getenv("URBAN_AGENT_HOME")
        or REPO_ROOT / ".urban-agent"
    ).expanduser()


def _default_memory_root() -> Path:
    source_runtime = PACKAGE_ROOT / "runtime_memory"
    if source_runtime.exists() or (PACKAGE_ROOT / ".gitignore").exists():
        return source_runtime
    urban_home = _default_urban_home()
    return urban_home / "urban_hermes_memory"


DEFAULT_MEMORY_ROOT = _default_memory_root()
DEFAULT_HERMES_HOME = Path(os.getenv("URBAN_HERMES_HOME") or _default_urban_home() / "urban_hermes_source").expanduser().resolve()


def _seed_dedicated_hermes_home(previous_home: str) -> None:
    """Copy only base configuration into the dedicated Urban-Hermes home.

    Sessions, memory, sandboxes, and state databases intentionally stay
    isolated. This lets the source runtime reuse provider/auth setup without
    mixing experiment traces with another Hermes installation.
    """
    if os.getenv("URBAN_HERMES_COPY_BASE_CONFIG", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    if not previous_home:
        return
    source_home = Path(previous_home).expanduser().resolve()
    if source_home == DEFAULT_HERMES_HOME or not source_home.exists():
        return
    DEFAULT_HERMES_HOME.mkdir(parents=True, exist_ok=True)
    for name in ("config.yaml", ".env", "auth.json"):
        source = source_home / name
        target = DEFAULT_HERMES_HOME / name
        if source.is_file() and not target.exists():
            try:
                shutil.copy2(source, target)
            except OSError:
                pass


def ensure_paths() -> None:
    """Make Hermes and current UrbanAgent sources importable."""
    for path in reversed((HERMES_ROOT, PAPER4_ROOT, PACKAGE_ROOT)):
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    existing_home = os.environ.get("HERMES_HOME", "").strip()
    if existing_home and Path(existing_home).expanduser().resolve() != DEFAULT_HERMES_HOME:
        os.environ.setdefault("URBAN_HERMES_PREVIOUS_HERMES_HOME", existing_home)
    if os.getenv("URBAN_HERMES_ALLOW_EXTERNAL_HERMES_HOME", "").strip().lower() not in {"1", "true", "yes", "on"}:
        _seed_dedicated_hermes_home(existing_home)
        os.environ["HERMES_HOME"] = str(DEFAULT_HERMES_HOME)
    else:
        os.environ.setdefault("HERMES_HOME", str(DEFAULT_HERMES_HOME))
    os.environ.setdefault("URBAN_HERMES_BRANDING", "1")
    os.environ.setdefault("URBAN_HERMES_MEMORY_ROOT", str(DEFAULT_MEMORY_ROOT))
    os.environ.setdefault("URBAN_AGENT_MEMORY_ROOT", str(DEFAULT_MEMORY_ROOT / "urban_agent"))


ensure_paths()
