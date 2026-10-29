"""
Purpose: Implement ``murmurent install --hooks`` for phase 4. Idempotently merges
         hook + MCP entries into ``~/.claude/settings.json``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI flags from :mod:`murmurent.cli`.
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
        # murmurent agent reporter — writes coloured one-line events for
        # PreToolUse(Agent) and SubagentStop to ~/.murmurent/agents.log,
        # which the VSCode BR pane tails. Uses ``command`` rather than
        # ``module`` because the hook is a bash script, not a Python
        # entrypoint.
        "event": "PreToolUse",
        "matcher": "Agent",
        "command": "bash <MURMURENT_COMMONS>/scripts/murmurent_log_agent_event.sh",
        "env": {},
        "label": "murmurent-agent-report-pre",
    },
    {
        "event": "SubagentStop",
        "matcher": None,
        "command": "bash <MURMURENT_COMMONS>/scripts/murmurent_log_agent_event.sh",
        "env": {},
        "label": "murmurent-agent-report-stop",
    },
    {
        "event": "PreToolUse",
        "matcher": "Write|Edit|Bash|NotebookEdit",
        "module": "murmurent.hooks.raw_guard",
        "env": {},
        "label": "murmurent-raw-guard",
    },
    {
        # Refined data + Obsidian notebook are write-once: new files OK,
        # overwriting / deleting existing files denied (lab versioning
        # convention: write file_2.csv, never overwrite file.csv).
        "event": "PreToolUse",
        "matcher": "Write|Edit|Bash|NotebookEdit",
        "module": "murmurent.hooks.protected_paths",
        "env": {},
        "label": "murmurent-protected-paths",
    },
    {
        "event": "PreToolUse",
        "matcher": "Bash|WebFetch|WebSearch|mcp__slack__.*|mcp__claude_ai_Slack__.*",
        "module": "murmurent.hooks.phi_check",
        "env": {"MURMURENT_PHI_HOOK_MODE": "pre"},
        "label": "murmurent-phi-pre",
    },
    {
        "event": "PostToolUse",
        "matcher": ".*",
        "module": "murmurent.hooks.phi_check",
        "env": {"MURMURENT_PHI_HOOK_MODE": "post"},
        "label": "murmurent-phi-post",
    },
    {
        "event": "UserPromptSubmit",
        "matcher": ".*",
        "module": "murmurent.hooks.context_inject",
        "env": {},
        "label": "murmurent-context-inject",
    },
    {
        "event": "PostToolUse",
        "matcher": ".*",
        "module": "murmurent.hooks.audit",
        "env": {},
        "label": "murmurent-audit",
    },
    {
        # Harvests the "## Gap register" table out of conscience reports under
        # outputs/conscience/ into ~/.murmurent/edid_gaps/ (append-only, per member) and
        # regenerates a local ranked register, so the EDID pool learns what
        # it is missing from reviews that needed something rather than from
        # someone remembering. Never writes docs/edid_resources.md — only the
        # bookworm, with a person's approval, changes what may be cited.
        "event": "PostToolUse",
        "matcher": "Write|Edit|NotebookEdit",
        "module": "murmurent.hooks.conscience_gaps",
        "env": {},
        "label": "murmurent-conscience-gaps",
    },
    # The personal vault follows you between machines without a button:
    # brought in when a session starts, sent as soon as a session writes a
    # note in it, and checked at the end of each reply. Notes marked protected
    # or restricted are never sent. See murmurent.hooks.vault_sync.
    {
        "event": "SessionStart",
        "matcher": None,
        "module": "murmurent.hooks.vault_sync",
        "env": {},
        "label": "murmurent-vault-sync-start",
    },
    {
        "event": "PostToolUse",
        "matcher": "Write|Edit|MultiEdit|NotebookEdit|mcp__murmurent-oracle__.*",
        "module": "murmurent.hooks.vault_sync",
        "env": {},
        "label": "murmurent-vault-sync-write",
    },
    {
        "event": "Stop",
        "matcher": None,
        "module": "murmurent.hooks.vault_sync",
        "env": {},
        "label": "murmurent-vault-sync-stop",
    },
]

MCP_REGISTRATIONS: dict[str, dict[str, Any]] = {
    "murmurent-inventory": {
        "command": sys.executable,
        "args": ["-m", "murmurent.mcp.inventory_server"],
        "env": {},
    },
    # Personal + Lab Oracle search/get/list/publish. Uses the same
    # python so the server has access to murmurent.core.* (vault
    # resolution, frontmatter parsing, publish flow).
    "murmurent-oracle": {
        "command": sys.executable,
        "args": ["-m", "murmurent.mcp.oracle_server"],
        "env": {},
    },
    # Per-job deliverable reader for core services. Members of a
    # requesting lab pull their job files through this MCP from any
    # CC session connected to the lab server (Phases 5d + 7).
    "murmurent-core-data": {
        "command": sys.executable,
        "args": ["-m", "murmurent.mcp.core_data_server"],
        "env": {},
    },
    # Arbitrary reference files (PDFs, spreadsheets, protocols, images,
    # text) under a vault's murmurent_data/ folder — list + read on
    # demand. Distinct from the Oracle (schema-validated markdown facts).
    "murmurent-data": {
        "command": sys.executable,
        "args": ["-m", "murmurent.mcp.data_server"],
        "env": {},
    },
}


def _expand_placeholders(text: str) -> str:
    """Replace ``<MURMURENT_COMMONS>`` with this machine's commons root.

    Resolved through :func:`commons_root` rather than the clone path, because a
    ``uv tool install`` has no clone: the hook used to point at
    ``~/repos/murmurent/scripts/``, which did not exist there (#159).
    """
    if "<MURMURENT_COMMONS>" not in text:
        return text
    from ..core.commons import commons_root
    return text.replace("<MURMURENT_COMMONS>", str(commons_root()))


def _resolve_command(reg: dict[str, Any]) -> str:
    """Render the shell command for a hook registration.

    Two registration shapes are supported:
      - ``module``: a Python module entrypoint — gets ``$PYTHON -m <module>``
        with optional env-var prefixes (the historic shape; covers
        raw_guard, phi_check, audit, etc.).
      - ``command``: a literal shell command — typically a path to a
        bash script. Use ``<MURMURENT_COMMONS>`` as a placeholder for the
        commons root (a clone, or the copy inside the installed package);
        it's expanded at install time so the resulting absolute path is
        correct on this machine.
    """
    env = reg.get("env") or {}
    if "command" in reg:
        cmd = _expand_placeholders(str(reg["command"]))
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
    body = _expand_placeholders(reg.get("module") or reg.get("command") or "")
    hooks = entry.get("hooks") or []
    for h in hooks:
        # The label is written as the hook's ``name``. Matching on it lets a
        # re-install replace an entry whose path has since moved (a clone path
        # on a machine that now runs from the package) instead of leaving the
        # broken one in place beside the new one.
        if reg.get("label") and h.get("name") == reg["label"]:
            return True
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


#: Environment settings murmurent sets in ``settings.json`` for every member,
#: unless the member has already chosen a value. The feedback survey interrupts
#: a working session to ask for a rating; the lab asked for it off (#154).
DEFAULT_ENV: dict[str, str] = {
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
}


def _ensure_env(settings: dict[str, Any]) -> bool:
    """Add each ``DEFAULT_ENV`` entry to ``settings.env`` if it is not there.

    A value the member already set is left alone, even if it differs: this is
    a default, not a policy. Returns True if anything changed.
    """
    env = settings.setdefault("env", {})
    changed = False
    for key, value in DEFAULT_ENV.items():
        if key not in env:
            env[key] = value
            changed = True
    return changed


def _ensure_mcp(settings: dict[str, Any]) -> bool:
    """Ensure each entry in ``MCP_REGISTRATIONS`` is in ``settings.mcpServers``.

    Kept for back-compat: prior murmurent releases wrote MCPs to
    ``~/.claude/settings.json``. Claude Code actually reads them from
    ``~/.claude.json`` (see :func:`_ensure_mcp_claude_json`), so this
    function's writes are effectively no-ops for runtime — but other
    tooling may still inspect ~/.claude/settings.json, so we keep
    populating it.
    """
    changed = False
    servers = settings.setdefault("mcpServers", {})
    for name, spec in MCP_REGISTRATIONS.items():
        if servers.get(name) != spec:
            servers[name] = spec
            changed = True
    return changed


def _ensure_mcp_claude_json() -> bool:
    """Write MCP entries to ``~/.claude.json`` so Claude Code actually
    picks them up. Without this, ``claude mcp list`` doesn't see our
    servers and members can't reach the murmurent MCPs.

    Idempotent. Preserves any entries the user added by hand (e.g.
    slack). Writes at user scope (top-level ``mcpServers`` key).
    """
    target = Path.home() / ".claude.json"
    data: dict[str, Any] = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
    servers = data.setdefault("mcpServers", {})
    changed = False
    for name, spec in MCP_REGISTRATIONS.items():
        if servers.get(name) != spec:
            servers[name] = spec
            changed = True
    if changed:
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
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
    if _ensure_env(settings):
        changed = True
    if _ensure_mcp(settings):
        changed = True
    # ALSO write MCP entries to ~/.claude.json — that's where Claude Code
    # actually reads from. (~/.claude/settings.json's mcpServers block
    # is a legacy murmurent convention that CC ignores at runtime.)
    if _ensure_mcp_claude_json():
        changed = True

    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if changed:
        click.echo(f"Installed murmurent hooks + MCP into {target}")
    else:
        click.echo(f"{target}: no changes (already installed).")
    return target
