"""Register Hermes-Urban tools and expose a small bootstrap API."""

from __future__ import annotations

from .paths import ensure_paths


def bootstrap() -> list[str]:
    """Register the urban toolset in Hermes' tool registry."""
    ensure_paths()
    from .tools import register_all_urban_tools

    return register_all_urban_tools()


if __name__ == "__main__":
    print("\n".join(bootstrap()))
