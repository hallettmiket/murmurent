"""
Purpose: net-new **personal agents** a member creates for their own work
(#38 item 3).

Distinct from a *fork* of a commons agent (see :mod:`agent_forks`): a personal
agent does not exist in the commons at all. A member authors it for their own
day-to-day computing, or as a bespoke step in a choreography phrase. It is:

  * **kept in the member's personal vault**, under ``agents/`` — so the normal
    ``murmurent vault sync`` commits + pushes it to the member's GitHub (this is
    the "backed up in the user's GH" from the issue), and
  * **installed into ``~/.claude/agents/``** as a symlink into that vault file,
    so Claude Code loads it — while the vault stays the single source of truth.

Because it lives only in this member's vault, it is present in their village
only, never in another member's environment. The commons stays the commons.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import agent_forks as _af
from . import agents as _agents

#: Test/override pin for the vault agents dir (mirrors the phrase-dir env pins).
ENV_PERSONAL_AGENTS_DIR = "MURMURENT_PERSONAL_AGENTS_DIR"

VAULT_AGENTS_SUBDIR = "agents"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


class PersonalAgentError(RuntimeError):
    """Raised when a personal agent cannot be created or removed."""


def vault_agents_dir() -> Path | None:
    """The member's ``<vault>/agents/`` folder, or ``None`` when no vault is
    registered on this machine. Resolved the same way the personal Oracle is
    (``$MURMURENT_PERSONAL_AGENTS_DIR`` overrides, for tests)."""
    pin = os.environ.get(ENV_PERSONAL_AGENTS_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    try:
        from . import oracle_publish as _op  # deferred: optional dashboard dep

        return _op.personal_oracle_dir().parent / VAULT_AGENTS_SUBDIR
    except Exception:  # noqa: BLE001 — no vault registered → no personal-agents home
        return None


def list_personal_agents() -> list[Path]:
    """Every personal-agent file in the member's vault (``*.md``)."""
    d = vault_agents_dir()
    if d is None or not Path(d).is_dir():
        return []
    return sorted(p for p in Path(d).glob("*.md"))


def _scaffold(name: str, description: str, model: str | None,
              tools: list[str] | None) -> str:
    """The seed markdown for a fresh personal agent."""
    lines = ["---", f"name: {name}", "category: member", "freeze: personal"]
    if model:
        lines.append(f"model: {model}")
    # description is single-quoted (YAML) with embedded quotes doubled.
    safe = description.replace("'", "''")
    lines.append(f"description: '{safe}'")
    if tools:
        lines.append("required_tools:")
        lines.extend(f"- {t}" for t in tools)
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(description or "A personal agent.")
    lines.append("")
    lines.append("_This is your own agent — edit this file to shape how it works. "
                 "It lives in your vault and is backed up to your GitHub on "
                 "`murmurent vault sync`; it is not part of the commons._")
    lines.append("")
    return "\n".join(lines)


def _install(canonical: Path) -> str:
    """Symlink ``~/.claude/agents/<name>.md`` → the vault file so CC loads it.
    Falls back to a copy when symlinks aren't available. Returns the method."""
    dest = _af.installed_agents_dir() / canonical.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(canonical)
        return "symlink"
    except OSError:
        dest.write_bytes(canonical.read_bytes())
        return "copy"


def create_personal_agent(
    name: str,
    description: str,
    *,
    model: str | None = None,
    tools: list[str] | None = None,
) -> Path:
    """Create a net-new personal agent in the member's vault + install it.

    Refuses when: there is no vault on this machine; ``name`` isn't a bare
    ``[a-z0-9_]`` slug; ``name`` collides with a commons agent (that would be a
    *fork*, not a personal agent — use ``murmurent agent fork``); or a personal
    agent by that name already exists.

    Returns the path to the vault file (the canonical home).
    """
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise PersonalAgentError(
            f"invalid agent name {name!r} — use lowercase letters, digits, and "
            "underscores (e.g. 'my_helper').")
    if name in _af.commons_agent_names():
        raise PersonalAgentError(
            f"{name!r} is a commons agent — to make your own copy of it, use "
            "`murmurent agent fork {0}` instead.".format(name))

    d = vault_agents_dir()
    if d is None:
        raise PersonalAgentError(
            "no personal vault registered on this machine — create one with "
            "`murmurent vault init` first (personal agents live in your vault so "
            "they're backed up to your GitHub).")
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    canonical = d / f"{name}.md"
    if canonical.exists():
        raise PersonalAgentError(
            f"a personal agent {name!r} already exists at {canonical}.")

    if model is not None and model not in {"fable", "opus", "sonnet", "haiku"}:
        raise PersonalAgentError(
            f"unknown model {model!r} (choose fable|opus|sonnet|haiku).")

    canonical.write_text(_scaffold(name, description, model, tools), encoding="utf-8")
    # Validate it parses as a real agent before installing (fail fast).
    try:
        _agents.load_agent(canonical)
    except Exception as exc:  # noqa: BLE001
        canonical.unlink(missing_ok=True)
        raise PersonalAgentError(f"the scaffolded agent did not validate: {exc}")
    _install(canonical)
    return canonical


def remove_personal_agent(name: str) -> None:
    """Delete a personal agent from the vault and uninstall its CC symlink.
    Never touches a commons agent."""
    name = (name or "").strip().lower()
    if name in _af.commons_agent_names():
        raise PersonalAgentError(f"{name!r} is a commons agent; refusing to remove it.")
    d = vault_agents_dir()
    if d is not None:
        (Path(d) / f"{name}.md").unlink(missing_ok=True)
    dest = _af.installed_agents_dir() / f"{name}.md"
    if dest.is_symlink() or dest.exists():
        dest.unlink()
