"""Urban Agents branding shim for the vendored Hermes runtime."""

from __future__ import annotations

import os
from typing import Any


URBAN_AGENTS_LOGO = """[bold #17A398] _   _ ____  ____    _    _   _      _    ____ _____ _   _ _____ ____[/]
[bold #17A398]| | | |  _ \\| __ )  / \\  | \ | |    / \\  / ___| ____| \ | |_   _/ ___|[/]
[#2E86AB]| | | | |_) |  _ \\ / _ \\ |  \| |   / _ \\| |  _|  _| |  \| | | | \\___ \\[/]
[#F6AE2D]| |_| |  _ <| |_) / ___ \\| |\  |  / ___ \\ |_| | |___| |\  | | |  ___) |[/]
[#F26419] \\___/|_| \\_\\____/_/   \\_\\_| \\_| /_/   \\_\\____|_____|_| \\_| |_| |____/[/]"""

URBAN_AGENTS_MARK = """[#17A398]        Urban Agents[/]
[#2E86AB]   spatial reasoning runtime[/]
[#F6AE2D]   grounding · tools · memory[/]"""

DEFAULT_URBAN_SOUL_MD = (
    "You are Urban Agents, an intelligent urban-analysis assistant. "
    "You help users turn urban research and planning questions into grounded, "
    "reviewable workflows with explicit data, spatial units, methods, tools, "
    "artifacts, uncertainty, and reusable memory. Communicate clearly, admit "
    "uncertainty when evidence is incomplete, and treat recalled memories as "
    "professional cues rather than automatic facts."
)

URBAN_AGENTS_WELCOME_TEXT = (
    "Welcome to Urban Agents / Urban-Hermes! Type your message or /help for commands."
)

URBAN_AGENTS_TIP_TEXT = (
    "Reviewer pauses should name time, space, people, assumptions, missing evidence, "
    "and artifact readiness before claims move forward."
)


def format_urban_agents_version_label() -> str:
    try:
        from hermes_cli import __release_date__ as release_date
        from hermes_cli import __version__ as runtime_version
    except Exception:
        return "Urban Agents"
    return f"Urban Agents runtime v{runtime_version} ({release_date})"


def build_urban_agents_compact_banner() -> str:
    return (
        "\n[bold #17A398]Urban Agents[/] "
        "[dim #2E86AB]- urban analysis agent runtime[/]\n"
        f"[dim #F6AE2D]{format_urban_agents_version_label()}[/]\n"
    )


def build_urban_agents_welcome_banner(
    console: Any,
    model: str,
    cwd: str,
    tools: list[dict] | None = None,
    enabled_toolsets: list[str] | None = None,
    session_id: str | None = None,
    get_toolset_for_tool: Any = None,
    context_length: int | None = None,
) -> None:
    from rich.panel import Panel
    from rich.table import Table

    tools = tools or []
    enabled_toolsets = enabled_toolsets or []
    model_short = model.split("/")[-1] if "/" in model else model
    if len(model_short) > 32:
        model_short = model_short[:29] + "..."

    table = Table.grid(padding=(0, 2))
    table.add_column("left", justify="left")
    table.add_column("right", justify="left")

    left_lines = [
        "[bold #17A398]Urban Agents[/]",
        "[#2E86AB]Urban-Hermes runtime[/]",
        f"[dim]Model:[/] [#F6AE2D]{model_short}[/]",
        f"[dim]Workspace:[/] {cwd}",
    ]
    if context_length:
        left_lines.append(f"[dim]Context:[/] {context_length:,} tokens")
    if session_id:
        left_lines.append(f"[dim]Session:[/] {session_id}")

    tool_names = []
    for tool in tools[:24]:
        try:
            tool_names.append(tool["function"]["name"])
        except Exception:
            continue
    if len(tools) > 24:
        tool_names.append(f"+{len(tools) - 24} more")
    right_lines = [
        "[bold #17A398]Enabled Toolsets[/]",
        ", ".join(enabled_toolsets) if enabled_toolsets else "urban, todo, memory",
        "",
        "[bold #17A398]Available Tools[/]",
        ", ".join(tool_names) if tool_names else "No tools listed",
        "",
        "[dim]/help for commands[/]",
    ]

    table.add_row("\n".join(left_lines), "\n".join(right_lines))
    console.print()
    console.print(URBAN_AGENTS_LOGO)
    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold #17A398]{format_urban_agents_version_label()}[/]",
            border_style="#2E86AB",
            padding=(0, 2),
        )
    )


def apply_urban_agents_branding(cli_module: Any | None = None) -> None:
    """Patch user-facing branding while leaving vendored internals intact."""
    os.environ.setdefault("URBAN_HERMES_BRANDING", "1")
    os.environ.setdefault("URBAN_HERMES_WELCOME_TEXT", URBAN_AGENTS_WELCOME_TEXT)
    os.environ.setdefault("URBAN_HERMES_TIP_TEXT", URBAN_AGENTS_TIP_TEXT)

    try:
        import hermes_cli.banner as banner

        banner.HERMES_AGENT_LOGO = URBAN_AGENTS_LOGO
        banner.HERMES_CADUCEUS = URBAN_AGENTS_MARK
        banner.format_banner_version_label = format_urban_agents_version_label
        banner.build_welcome_banner = build_urban_agents_welcome_banner
    except Exception:
        pass

    try:
        import hermes_cli.default_soul as default_soul

        default_soul.DEFAULT_SOUL_MD = DEFAULT_URBAN_SOUL_MD
    except Exception:
        pass

    if cli_module is not None:
        cli_module.HERMES_AGENT_LOGO = URBAN_AGENTS_LOGO
        cli_module.HERMES_CADUCEUS = URBAN_AGENTS_MARK
        cli_module.format_banner_version_label = format_urban_agents_version_label
        cli_module._build_compact_banner = build_urban_agents_compact_banner
        cli_module.build_welcome_banner = build_urban_agents_welcome_banner
