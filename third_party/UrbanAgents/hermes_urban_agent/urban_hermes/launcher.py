"""Launch Hermes CLI with the urban toolset registered first."""

from __future__ import annotations

import argparse
import os
import re
import sys

from .bootstrap import bootstrap
from .branding import apply_urban_agents_branding
from .paths import ensure_paths


HERMES_COMMANDS = {
    "auth",
    "config",
    "doctor",
    "fallback",
    "login",
    "logout",
    "model",
    "setup",
    "status",
}


def _disable_urban_tools(tool_names: list[str], *, quiet: bool = False) -> list[str]:
    """Remove selected Urban-Hermes tools before the CLI session starts."""
    env_names = [
        item.strip()
        for item in os.getenv("URBAN_HERMES_DISABLED_TOOLS", "").split(",")
        if item.strip()
    ]
    requested = [*env_names, *tool_names]
    if not requested:
        return []

    from tools.registry import registry

    removed: list[str] = []
    for name in dict.fromkeys(requested):
        if not name.startswith("urban_"):
            if not quiet:
                print(f"[urban-hermes] Skipping non-urban tool disable request: {name}")
            continue
        if registry.get_entry(name):
            registry.deregister(name)
            removed.append(name)
        elif not quiet:
            print(f"[urban-hermes] Tool not registered, cannot disable: {name}")
    if removed:
        os.environ["URBAN_HERMES_DISABLED_TOOLS_ACTIVE"] = ",".join(removed)
        if not quiet:
            print(f"[urban-hermes] Disabled urban tools: {', '.join(removed)}")
    return removed


def _run_hermes_command(argv: list[str]) -> None:
    ensure_paths()
    apply_urban_agents_branding()
    old_argv = sys.argv[:]
    old_disable_lazy = os.environ.get("HERMES_DISABLE_LAZY_INSTALLS")
    try:
        if argv and argv[0] == "setup":
            # Hermes setup performs availability probes for optional backends.
            # Those probes can trigger lazy pip installs, which is undesirable
            # during configuration and can stall or crash the setup flow.
            os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
        sys.argv = ["urban-hermes", *argv]
        from hermes_cli.main import main as hermes_command_main

        hermes_command_main()
    finally:
        if old_disable_lazy is None:
            os.environ.pop("HERMES_DISABLE_LAZY_INSTALLS", None)
        else:
            os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = old_disable_lazy
        sys.argv = old_argv


def _patch_plain_output_if_needed(*, force: bool = False) -> None:
    """Avoid prompt_toolkit rendering when Hermes-Urban is driven by pipes.

    Hermes' upstream CLI routes many status lines through prompt_toolkit even in
    some one-shot/resume paths. That is pleasant in a real terminal, but crashes
    under PowerShell piping/automation with NoConsoleScreenBufferError. The
    adapter's experiment mode should remain CLI-native while still being
    non-TTY-safe, so we replace Hermes' colored print helper with a plain writer
    only when stdout is not interactive or the caller explicitly requests it.
    """
    if not force and sys.stdout.isatty() and not os.getenv("URBAN_HERMES_PLAIN"):
        return
    try:
        import cli as hermes_cli_module
    except Exception:
        return

    ansi_re = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def plain_print(text: str = "") -> None:
        rendered = ansi_re.sub("", str(text))
        try:
            sys.stdout.write(rendered + ("\n" if not rendered.endswith("\n") else ""))
            sys.stdout.flush()
        except UnicodeEncodeError:
            sys.stdout.buffer.write((rendered + "\n").encode("utf-8", errors="replace"))
            sys.stdout.flush()

    hermes_cli_module._cprint = plain_print  # type: ignore[attr-defined]


def _configure_windows_native_mode(args: argparse.Namespace) -> None:
    """Keep Hermes-Urban on native Windows tools by default.

    Upstream Hermes' generic file and terminal toolsets execute through Git
    Bash on Windows. That is useful for Unix-like command habits, but urban
    GIS runs usually pass native paths such as D:/... and QGIS .bat files.
    Filtering those generic toolsets makes the model use urban_host_fs,
    urban_host_python, and urban_qgis_process instead of drifting into
    WSL/Git-Bash path repair loops.
    """
    if os.name != "nt" or getattr(args, "allow_wsl_tools", False):
        return

    os.environ.setdefault("URBAN_HERMES_WINDOWS_NATIVE", "1")
    os.environ.setdefault("URBAN_HERMES_AVOID_WSL", "1")
    os.environ.setdefault("TERMINAL_ENV", "local")
    os.environ.setdefault("TERMINAL_LOCAL_PERSISTENT", "false")

    original_toolsets = [item.strip() for item in str(args.toolsets or "").split(",") if item.strip()]
    filtered_toolsets = [item for item in original_toolsets if item not in {"file", "terminal"}]
    if not filtered_toolsets:
        filtered_toolsets = ["urban", "todo", "memory"]
    if filtered_toolsets != original_toolsets:
        args.toolsets = ",".join(filtered_toolsets)
        os.environ["URBAN_HERMES_FILTERED_TOOLSETS"] = ",".join(sorted(set(original_toolsets) - set(filtered_toolsets)))
        if not getattr(args, "quiet", False):
            print(
                "[urban-hermes] Windows-native mode: filtered generic file/terminal toolsets; "
                "use urban_host_fs, urban_host_python, and urban_qgis_process."
            )


def _install_runtime_prompt(args: argparse.Namespace) -> None:
    """Inject the Urban-Hermes workflow contract as a system prompt.

    The memory provider can also contribute these instructions when configured
    globally, but dogfood experiments should not depend on a user's
    ~/.hermes/config.yaml. Keep this prompt generic and task-shaped rather than
    case-specific.
    """
    if os.getenv("URBAN_HERMES_DISABLE_RUNTIME_PROMPT"):
        return
    toolsets = {item.strip() for item in str(args.toolsets or "").split(",") if item.strip()}
    if "urban" not in toolsets:
        return
    parts: list[str] = []
    skill_prompt = os.path.join(os.path.dirname(__file__), "urban_skill_prompt.md")
    try:
        with open(skill_prompt, "r", encoding="utf-8") as handle:
            parts.append(handle.read().strip())
    except OSError:
        pass
    try:
        from .memory_provider import UrbanMemoryProvider

        parts.append(UrbanMemoryProvider().system_prompt_block())
    except Exception:
        pass
    if parts:
        runtime_prompt = "\n\n".join(part for part in parts if part).strip()
        existing = os.getenv("URBAN_HERMES_SYSTEM_PROMPT", "").strip()
        combined = "\n\n".join(
            part for part in (existing, runtime_prompt) if part
        ).strip()
        os.environ["URBAN_HERMES_SYSTEM_PROMPT"] = combined

        # Also feed the contract through Hermes' native ephemeral prompt path.
        # This makes the source-runtime instructions visible to the agent before
        # session creation, instead of relying only on a later vendored-CLI hook.
        existing_ephemeral = os.getenv("HERMES_EPHEMERAL_SYSTEM_PROMPT", "").strip()
        if combined and combined not in existing_ephemeral:
            os.environ["HERMES_EPHEMERAL_SYSTEM_PROMPT"] = "\n\n".join(
                part for part in (existing_ephemeral, combined) if part
            ).strip()


def main(argv: list[str] | None = None) -> None:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] in HERMES_COMMANDS:
        _run_hermes_command(raw_args)
        return

    parser = argparse.ArgumentParser(description="Launch Urban Agents with the Urban-Hermes runtime and urban toolset registered.")
    parser.add_argument("query", nargs="?", help="Optional one-shot query. If omitted, Hermes starts interactively.")
    parser.add_argument("--toolsets", default="urban,todo,memory,delegation,file,terminal", help="Comma-separated Hermes toolsets.")
    parser.add_argument("--provider", default=None, help="Provider override.")
    parser.add_argument("--model", default=None, help="Model override.")
    parser.add_argument("--max-turns", type=int, default=None, help="Maximum tool-calling turns for one-shot mode.")
    parser.add_argument("--skills", default=None, help="Comma-separated Hermes skills to preload.")
    parser.add_argument("--list-tools", action="store_true", help="List available tools and exit.")
    parser.add_argument("--list-toolsets", action="store_true", help="List available toolsets and exit.")
    parser.add_argument("--quiet", action="store_true", help="Pass quiet mode through to the Urban Agents CLI.")
    parser.add_argument("--compact", action="store_true", help="Pass compact display mode through to the Urban Agents CLI.")
    parser.add_argument("--resume", default=None, help="Resume a previous Urban Agents session id.")
    parser.add_argument("--ignore-user-config", action="store_true", help="Pass through to Hermes CLI.")
    parser.add_argument("--plain", action="store_true", help="Force plain non-prompt_toolkit output for scripted runs.")
    parser.add_argument("--yolo", action="store_true", help="Bypass Hermes dangerous-command approval prompts for this process.")
    parser.add_argument("--allow-wsl-tools", action="store_true", help="Keep upstream generic file/terminal toolsets on Windows. By default Hermes-Urban filters them to avoid Git Bash/WSL path issues.")
    parser.add_argument("--disable-urban-tool", action="append", default=[], help="Remove a registered Urban-Hermes tool before starting the CLI session; intended for ablation runs.")
    args = parser.parse_args(argv)

    ensure_paths()
    bootstrap()
    _disable_urban_tools(args.disable_urban_tool, quiet=args.quiet)
    _configure_windows_native_mode(args)
    _install_runtime_prompt(args)

    if args.yolo:
        os.environ["HERMES_YOLO_MODE"] = "1"

    _patch_plain_output_if_needed(force=args.plain)

    import cli as hermes_cli_module

    apply_urban_agents_branding(hermes_cli_module)

    hermes_cli_module.main(
        query=args.query,
        toolsets=args.toolsets,
        provider=args.provider,
        model=args.model,
        max_turns=args.max_turns,
        skills=args.skills,
        list_tools=args.list_tools,
        list_toolsets=args.list_toolsets,
        quiet=args.quiet,
        compact=args.compact,
        resume=args.resume,
        ignore_user_config=args.ignore_user_config,
    )


if __name__ == "__main__":
    main()
