"""Generate a carapace completion spec from the command tree.

The spec is built from the live Click command tree, so it cannot drift from the
CLI. carapace turns one spec into completions for bash, zsh, fish, nushell,
elvish, powershell, tcsh, xonsh and oil.
"""

from __future__ import annotations

from typing import Any

import typer
import yaml

PROGRAM = "yt-dlp-archiver"

# Flag name to carapace action. '$files' and '$directories' are carapace
# built-ins. '$(...)' runs a command and reads 'value<TAB>description' lines.
VALUE_ACTIONS: dict[str, list[str]] = {
    "job": [f"$({PROGRAM} _complete jobs)"],
    "yt-dlp-options": [f"$({PROGRAM} _complete yt-dlp-option-sets)"],
    "options": [f"$({PROGRAM} _complete yt-dlp-option-sets)"],
    "gallery-dl-options": [f"$({PROGRAM} _complete gallery-dl-option-sets)"],
    "config": ["$files"],
    "target-dir": ["$directories"],
}


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _negate(description: str) -> str:
    """Describe the '--no-x' half of a '--x/--no-x' pair.

    Click stores one help string per parameter, which states the positive case.
    """
    if not description:
        return ""
    return f"Do not {description[0].lower()}{description[1:]}"


def _flags(command: Any) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Flag declarations and the value completion for each flag."""
    flags: dict[str, str] = {}
    completion: dict[str, list[str]] = {}
    for param in command.params:
        if getattr(param, "hidden", False) or param.param_type_name != "option":
            continue
        takes_value = not param.is_flag
        description = _first_line(getattr(param, "help", None))
        # carapace marks a value-taking flag with a trailing '='.
        for opt in param.opts:
            flags[f"{opt}=" if takes_value else opt] = description
        for opt in param.secondary_opts:
            flags[opt] = _negate(description)
        if takes_value:
            for opt in param.opts:
                name = opt.lstrip("-")
                action = VALUE_ACTIONS.get(name)
                if action:
                    completion[name] = list(action)
    # Click appends the help option at parse time, so it is not in 'params'.
    flags["--help"] = "Show help and exit."
    return flags, completion


def _command_spec(name: str, command: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"name": name}
    description = _first_line(getattr(command, "help", None))
    if description:
        spec["description"] = description

    flags, flag_completion = _flags(command)
    if flags:
        spec["flags"] = flags
    if flag_completion:
        spec["completion"] = {"flag": flag_completion}

    children = getattr(command, "commands", None) or {}
    subcommands = [
        _command_spec(child_name, child)
        for child_name, child in sorted(children.items())
        if not getattr(child, "hidden", False)
    ]
    if subcommands:
        spec["commands"] = subcommands
    return spec


def carapace_spec(app: typer.Typer) -> dict[str, Any]:
    return _command_spec(PROGRAM, typer.main.get_command(app))


class _NoAliasDumper(yaml.SafeDumper):
    """Repeated values must be written out, not turned into YAML anchors."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def render_carapace(app: typer.Typer) -> str:
    return yaml.dump(
        carapace_spec(app),
        Dumper=_NoAliasDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
