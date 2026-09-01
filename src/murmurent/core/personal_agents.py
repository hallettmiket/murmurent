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
import tempfile
from pathlib import Path

from . import agent_forks as _af
from . import agents as _agents

#: Test/override pin for the vault agents dir (mirrors the phrase-dir env pins).
ENV_PERSONAL_AGENTS_DIR = "MURMURENT_PERSONAL_AGENTS_DIR"

VAULT_AGENTS_SUBDIR = "agents"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")

VALID_MODELS = {"fable", "opus", "sonnet", "haiku"}

#: Default headline-first verdict vocabulary for a fresh agent (rules/headline_first.md).
DEFAULT_VERDICT = "Done / Failed / Partial"
DEFAULT_PERSONA = "Clear, concise, and professional. You measure; you do not promise."
DEFAULT_OUTPUT = "Markdown — a short report leading with the verdict line, detail after."


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


def _as_lines(value: list[str] | str | None) -> list[str]:
    """Normalise a bullet-list field (a list, or a newline/`;`-separated string)."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\n;]+", value)
    else:
        parts = list(value)
    return [p.strip().lstrip("-• ").strip() for p in parts if str(p).strip()]


def _as_tools(value: list[str] | str | None) -> list[str]:
    """Normalise a tool field (list, or comma/space-separated string) to a list."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\s]+", value)
    else:
        parts = list(value)
    seen: list[str] = []
    for p in parts:
        t = str(p).strip()
        if t and t not in seen:
            seen.append(t)
    return seen


def build_agent_md(
    name: str,
    *,
    role: str,
    responsibilities: list[str] | str | None = None,
    non_goals: str | None = None,
    required_tools: list[str] | str | None = None,
    denied_tools: list[str] | str | None = None,
    persona: str | None = None,
    output_format: str | None = None,
    guardrails: str | None = None,
    example: str | None = None,
    verdict: str | None = None,
    model: str | None = None,
    category: str = "member",
    freeze: str = "personal",
) -> str:
    """Assemble a well-formed, commons-shaped agent markdown document.

    Only ``name`` + ``role`` are load-bearing; every other section defaults so a
    two-field "name it and go" create still yields a usable agent. The body
    always opens with the mandatory ≤200-char headline-first verdict block
    (rules/headline_first.md) and labels each section so the file reads like a
    commons agent, not a stub. Used by both the DEFINE and MODIFY flows.
    """
    role = (role or "A personal agent.").strip()
    verdict = (verdict or DEFAULT_VERDICT).strip()
    req = _as_tools(required_tools)
    den = _as_tools(denied_tools)

    # --- frontmatter (built as a dict, serialised via the shared dumper) ------
    from .frontmatter import dump_document

    meta: dict = {"name": name, "category": category, "freeze": freeze}
    if model:
        meta["model"] = model
    meta["description"] = role
    if req:
        meta["required_tools"] = req
    if den:
        meta["denied_tools"] = den

    # --- body: labelled sections, verdict block first -------------------------
    b: list[str] = [f"# {name}", ""]
    b += [
        "**MANDATORY OUTPUT RULE.** Begin every reply with a single ≤200-char "
        "verdict line in your own voice (e.g. "
        f"`{verdict} — <one-line why>`), then one blank line, then any detail. "
        "See rules/headline_first.md.",
        "",
        role,
        "",
    ]

    resp = _as_lines(responsibilities) or [role]
    b.append("## Your responsibilities")
    b += [f"- {r}" for r in resp]
    b.append("")

    b.append("## Scope & non-goals")
    if non_goals and non_goals.strip():
        b.append(non_goals.strip())
    else:
        b.append("_Out of scope: anything outside the responsibilities above. "
                 "Hand specialised work to the agent that owns it._")
    b.append("")

    b.append("## Tools")
    if req:
        b.append("- **May use:** " + ", ".join(req))
    else:
        b.append("- **May use:** inherits the full tool set (none withheld).")
    if den:
        b.append("- **Must NOT use:** " + ", ".join(den))
    b.append("")

    b.append("## Your personality")
    b.append((persona or DEFAULT_PERSONA).strip())
    b.append("")

    b.append("## Output conventions")
    b.append((output_format or DEFAULT_OUTPUT).strip())
    b.append("")

    if guardrails and guardrails.strip():
        b.append("## Guardrails")
        b.append(guardrails.strip())
        b.append("")

    if example and example.strip():
        b.append("## Example")
        b.append(example.strip())
        b.append("")

    b.append("_This is your own agent — edit this file (or the dashboard's "
             "Modify wizard) to shape how it works. It lives in your vault and "
             "is backed up to your GitHub on `murmurent vault sync`; it is not "
             "part of the commons._")
    b.append("")

    return dump_document(meta, "\n".join(b))


def validate_agent_text(text: str) -> None:
    """Raise if ``text`` is not a valid agent markdown (frontmatter + schema).

    Writes to a scratch temp file and runs the real ``agents.load_agent``
    validator, so a builder bug is caught before anything touches the vault.
    """
    with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        tmp = Path(fh.name)
    try:
        _agents.load_agent(tmp)
    finally:
        tmp.unlink(missing_ok=True)


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
    responsibilities: list[str] | str | None = None,
    non_goals: str | None = None,
    denied_tools: list[str] | str | None = None,
    persona: str | None = None,
    output_format: str | None = None,
    guardrails: str | None = None,
    example: str | None = None,
    verdict: str | None = None,
) -> Path:
    """Create a net-new personal agent in the member's vault + install it.

    ``name`` + ``description`` (the one-line role) are the only required inputs —
    everything else defaults, preserving the "name it and go" speed. The optional
    keyword fields feed the richer DEFINE wizard (issue #84 item 2): scope &
    non-goals, tool grants/denials, persona, output format, guardrails, a worked
    example, and the headline-first verdict vocabulary.

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

    if model is not None and model not in VALID_MODELS:
        raise PersonalAgentError(
            f"unknown model {model!r} (choose fable|opus|sonnet|haiku).")

    text = build_agent_md(
        name,
        role=description,
        responsibilities=responsibilities,
        non_goals=non_goals,
        required_tools=tools,
        denied_tools=denied_tools,
        persona=persona,
        output_format=output_format,
        guardrails=guardrails,
        example=example,
        verdict=verdict,
        model=model,
    )
    # Validate it parses as a real agent before installing (fail fast).
    try:
        validate_agent_text(text)
    except Exception as exc:  # noqa: BLE001
        raise PersonalAgentError(f"the scaffolded agent did not validate: {exc}")
    canonical.write_text(text, encoding="utf-8")
    _install(canonical)
    return canonical


def relink_vault_agents() -> dict:
    """Materialise this member's vault agents into ``~/.claude/agents/``.

    The multi-machine half of agent sync (issue #80): after a vault ff-pull on
    another machine, the agent files exist in the vault but Claude Code has
    nothing to load. This re-links them, matching the original installs:

    * ``<vault>/agents/<name>.md``       → symlink  (as ``create_personal_agent``)
    * ``<vault>/agent_forks/<name>.md``  → hardlink (as ``fork_agent``; plain
      copy when the vault sits on another device)

    Also runs the one-time legacy ``~/.murmurent/agent_forks/`` migration first.
    Idempotent (safe to run repeatedly) and non-destructive: a local working
    copy whose bytes diverged from the vault fork is left alone and reported
    under ``skipped`` rather than clobbered. With no vault registered it
    degrades to a harmless no-op over the legacy fork home.
    """
    out: dict = {"vault_agents": None, "forks_dir": None, "migrated": None,
                 "personal": [], "forks": [], "skipped": []}

    try:
        out["migrated"] = _af.migrate_legacy_forks()
    except Exception as exc:  # noqa: BLE001 — migration is best-effort
        out["migrated"] = {"migrated": False, "detail": str(exc)}

    commons = _af.commons_agent_names()

    # 1) net-new personal agents → symlinks into ~/.claude/agents/
    d = vault_agents_dir()
    out["vault_agents"] = str(d) if d is not None else None
    for canonical in list_personal_agents():
        name = canonical.stem
        if name in commons:
            out["skipped"].append({
                "name": name,
                "reason": "shares a commons agent's name — a fork belongs in "
                          "agent_forks/, not agents/"})
            continue
        out["personal"].append({"name": name, "method": _install(canonical)})

    # 2) forks → hardlinks into ~/.claude/agents/ (survive setup.sh re-runs)
    fdir = _af.forks_dir()
    out["forks_dir"] = str(fdir)
    if fdir.is_dir():
        for canonical in sorted(fdir.glob("*.md")):
            name = canonical.stem
            dest = _af.installed_agents_dir() / canonical.name
            if dest.exists() and not dest.is_symlink():
                try:
                    same_inode = os.stat(dest).st_ino == os.stat(canonical).st_ino
                except OSError:
                    same_inode = False
                if same_inode:
                    out["forks"].append({"name": name, "method": "already-linked"})
                    continue
                if dest.read_bytes() != canonical.read_bytes():
                    out["skipped"].append({
                        "name": name,
                        "reason": f"local copy at {dest} differs from the vault "
                                  f"fork — reconcile them, then re-run (or "
                                  f"`murmurent agent fork {name} --force`)"})
                    continue
            out["forks"].append(
                {"name": name, "method": _af._install_working_copy(canonical, dest)})
    return out


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
