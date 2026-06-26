"""Install a small bridge plugin for Hermes' memory-provider discovery."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import HERMES_ROOT, PACKAGE_ROOT, ensure_paths


def install() -> dict[str, str]:
    ensure_paths()
    from hermes_constants import get_hermes_home

    hermes_home = get_hermes_home()
    plugin_dir = hermes_home / "plugins" / "urban_memory"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    init_file = plugin_dir / "__init__.py"
    init_file.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"adapter_root = Path({str(PACKAGE_ROOT)!r})\n"
        "if str(adapter_root) not in sys.path:\n"
        "    sys.path.insert(0, str(adapter_root))\n"
        "from urban_hermes.memory_provider import UrbanMemoryProvider, register\n"
        "__all__ = ['UrbanMemoryProvider', 'register']\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        "name: urban_memory\n"
        "version: 0.1.0\n"
        "description: Urban Agents feedback, place, research-design, method, and artifact memory provider.\n",
        encoding="utf-8",
    )
    return {
        "plugin_dir": str(plugin_dir),
        "init_file": str(init_file),
        "hermes_root": str(HERMES_ROOT),
        "next_step": "Set memory.provider: urban_memory in .urban-agent/urban_hermes/config.yaml, or instantiate UrbanMemoryProvider directly.",
    }


def main() -> None:
    print(json.dumps(install(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
