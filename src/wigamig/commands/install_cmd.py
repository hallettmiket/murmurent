"""
Purpose: Implement ``wigamig install --hooks`` for phase 4. Idempotently merges
         hook + MCP entries into ``~/.claude/settings.json``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI flags from :mod:`wigamig.cli`.
Output: Updated ``~/.claude/settings.json``; returns the path that was edited.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import click

DEFAULT_SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()


HOOK_REGISTRATIONS: list[dict[str, Any]] = [
    {
        # wigamig agent reporter — writes coloured one-line events for
        # PreToolUse(Agent) and SubagentStop to ~/.wigamig/agents.log,
        # which the VSCode BR pane tails. Uses ``command`` rather than
        # ``module`` because the hook is a bash script, not a Python
        # entrypoint.
        "event": "PreToolUse",
        "matcher": "Agent",
        "command": "<WIGAMIG_REPO>/scripts/wigamig_log_agent_event.sh",
        "env": {},
        "label": "wigamig-agent-report-pre",
    },
    {
        "event": "SubagentStop",
        "matcher": None,
        "command": "<WIGAMIG_REPO>/scripts/wigamig_log_agent_event.sh",
        "env": {},
        "label": "wigamig-agent-report-stop",
    },
    {
        "event": "PreToolUse",
        "matcher": "Write|Edit|Bash|NotebookEdit",
        "module": "wigamig.hooks.raw_guard",
        "env": {},
        "label": "wigamig-raw-guard",
    },
    {
        # Refined data + Obsidian notebook are write-once: new files OK,
        # overwriting / deleting existing files denied (lab versioning
        # convention: write file_2.csv, never overwrite file.csv).
        "event": "PreToolUse",
        "matcher": "Write|Edit|Bash|NotebookEdit",
        "module": "wigamig.hooks.protected_paths",
        "env": {},
        "label": "wigamig-protected-paths",
    },
    {
        "event": "PreToolUse",
        "matcher": "Bash|WebFetch|WebSearch|mcp__slack__.*|mcp__claude_ai_Slack__.*",
        "module": "wigamig.hooks.phi_check",
        "env": {"WIGAMIG_PHI_HOOK_MODE": "pre"},
        "label": "wigamig-phi-pre",
    },
    {
        "event": "PostToolUse",
        "matcher": ".*",
        "module": "wigamig.hooks.phi_check",
        "env": {"WIGAMIG_PHI_HOOK_MODE": "post"},
        "label": "wigamig-phi-post",
    },
    {
        "event": "UserPromptSubmit",
        "matcher": ".*",
        "module": "wigamig.hooks.context_inject",
        "env": {},
        "label": "wigamig-context-inject",
    },
    {
        "event": "PostToolUse",
        "matcher": ".*",
        "module": "wigamig.hooks.audit",
        "env": {},
        "label": "wigamig-audit",
    },
]

MCP_REGISTRATIONS: dict[str, dict[str, Any]] = {
    "wigamig-inventory": {
        "command": sys.executable,
        "args": ["-m", "wigamig.mcp.inventory_server"],
        "env": {},
    },
    # Personal + Lab Oracle search/get/list/publish. Uses the same
    # python so the server has access to wigamig.core.* (vault
    # resolution, frontmatter parsing, publish flow).
    "wigamig-oracle": {
        "command": sys.executable,
        "args": ["-m", "wigamig.mcp.oracle_server"],
        "env": {},
    },
}


def _resolve_command(reg: dict[str, Any]) -> str:
    """Render the shell command for a hook registration.

    Two registration shapes are supported:
      - ``module``: a Python module entrypoint — gets ``$PYTHON -m <module>``
        with optional env-var prefixes (the historic shape; covers
        raw_guard, phi_check, audit, etc.).
      - ``command``: a literal shell command — typically a path to a
        bash script. Use ``<WIGAMIG_REPO>`` as a placeholder for the
        wigamig clone root; it's expanded at install time so the
        resulting absolute path is correct on this machine.
    """
    env = reg.get("env") or {}
    if "command" in reg:
        from ..core.repo import wigamig_repo_root
        cmd = str(reg["command"]).replace("<WIGAMIG_REPO>", str(wigamig_repo_root()))
        parts = [f"{k}={v}" for k, v in env.items()] + [cmd]
        return " ".join(parts)
    parts = [f"{k}={v}" for k, v in env.items()]
    parts.extend([sys.executable, "-m", reg["module"]])
    return " ".join(parts)


def _matches_existing(entry: dict[str, Any], reg: dict[str, Any]) -> bool:
    """Decide whether ``entry`` corresponds to ``reg`` (so we can replace it).

    Identity carries through the ``label`` (always present) and the
    body of the command — either the Python module name (``module``
    registrations) or the script path (``command`` registrations).
    """
    # Matcher equality: both ``None`` and missing-key mean "no matcher"
    # for our purposes; treat them as equivalent so we don't fail to
    # match an existing entry just because the old shape stored
    # ``matcher: null`` and the new shape omits the key.
    if (entry.get("matcher") or None) != (reg.get("matcher") or None):
        return False
    body = reg.get("module") or reg.get("command") or ""
    if "<WIGAMIG_REPO>" in body:
        from ..core.repo import wigamig_repo_root
        body = body.replace("<WIGAMIG_REPO>", str(wigamig_repo_root()))
    hooks = entry.get("hooks") or []
    for h in hooks:
        cmd = h.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        if body and body in cmd:
            return True
        if reg.get("label") and reg["label"] in cmd:
            return True
    return False


def _ensure_hook(settings: dict[str, Any], reg: dict[str, Any]) -> bool:
    """Ensure ``reg`` is present under ``settings.hooks[reg.event]``.

    Returns True if anything changed.

    The ``matcher`` key is only emitted when the registration carries
    a non-None value. CC's settings parser rejects ``matcher: null``
    (``Expected strings, but received null``), and events like
    ``SubagentStop`` and ``Stop`` don't conceptually have a matcher —
    they fire on every occurrence. Omitting the key is the right
    encoding for matcher-less hooks.
    """
    hooks = settings.setdefault("hooks", {})
    bucket = hooks.setdefault(reg["event"], [])
    new_entry: dict[str, Any] = {
        "hooks": [
            {
                "type": "command",
                "command": _resolve_command(reg),
                "name": reg["label"],
            }
        ],
    }
    matcher = reg.get("matcher")
    if matcher is not None:
        new_entry["matcher"] = matcher
    # Preserve insertion order for diff stability: when an entry has
    # both matcher and hooks, put matcher first to match the existing
    # on-disk shape.
    if "matcher" in new_entry:
        new_entry = {"matcher": new_entry["matcher"], "hooks": new_entry["hooks"]}
    for i, entry in enumerate(bucket):
        if _matches_existing(entry, reg):
            if entry == new_entry:
                return False
            bucket[i] = new_entry
            return True
    bucket.append(new_entry)
    return True


def _ensure_mcp(settings: dict[str, Any]) -> bool:
    """Ensure each entry in ``MCP_REGISTRATIONS`` is in ``settings.mcpServers``."""
    changed = False
    servers = settings.setdefault("mcpServers", {})
    for name, spec in MCP_REGISTRATIONS.items():
        if servers.get(name) != spec:
            servers[name] = spec
            changed = True
    return changed


def cmd_install(
    *,
    hooks: bool = False,
    settings_path: Path | None = None,
    backup: bool = True,
) -> Path:
    """Install hooks + MCP servers into the CC settings file."""
    if not hooks:
        raise click.ClickException("phase 4 supports --hooks only (full install lands in phase 5).")
    target = settings_path or DEFAULT_SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    settings: dict[str, Any] = {}
    if target.is_file():
        try:
            settings = json.loads(target.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"could not parse existing {target}: {exc}; back it up and retry."
            )

    if backup and target.is_file():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))

    changed = False
    for reg in HOOK_REGISTRATIONS:
        if _ensure_hook(settings, reg):
            changed = True
    if _ensure_mcp(settings):
        changed = True

    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if changed:
        click.echo(f"Installed wigamig hooks + MCP into {target}")
    else:
        click.echo(f"{target}: no changes (already installed).")
    return target
