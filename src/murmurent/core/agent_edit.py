"""
Purpose: MODIFY an existing, editable agent (issue #84 item 3).

The DEFINE flow (:mod:`personal_agents`) authors a net-new agent. This module is
the other half: editing an agent that already exists — a member's own personal
agent, or a commons agent the member wants to tailor. It composes the pieces that
already exist rather than inventing new storage:

  * **editability gate** — a ``freeze: frozen`` agent and the guardian set
    (``security_guard``, ``adversary``, ``conscience``, plus any commons agent
    that withholds an egress tool) are NEVER editable. Editing them is exactly
    what the item-8 integrity audit exists to catch, so we refuse up front with a
    clear message rather than letting a weakening edit through.
  * **fork-on-first-edit** — editing a *commons* agent must not touch the
    commons. The first save forks it via :func:`agent_forks.fork_agent`, so the
    canonical editable copy lands in the vault-tracked ``<vault>/agent_forks/``
    (issue #80) and rides ``murmurent vault sync`` across machines. A *personal*
    agent is edited in place in ``<vault>/agents/``.
  * **save-time integrity** — every save runs
    :func:`personal_audit.assess_agent_edit` (the same deterministic item-8
    checks) against the proposed text: guardrail weakening, tool widening, safety
    removal. ``block``-severity findings are hard regressions and refuse the
    save; ``warn`` findings are returned for the UI to surface.

The wizard field set matches DEFINE; ``name`` / ``category`` / ``freeze`` are
locked (renaming is a new agent; a member does not un-freeze).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from . import agent_forks as _af
from . import agents as _agents
from . import personal_agents as _pa
from . import personal_audit as _audit
from .frontmatter import parse_file
from .security_findings import SEVERITY_BLOCK

#: The guardian agents that are never editable (mirrors the item-8 audit).
GUARDIAN_AGENTS = _audit.GUARDIAN_AGENTS

#: Frontmatter fields the MODIFY wizard locks (not user-editable).
LOCKED_FIELDS = ("name", "category", "freeze")


class AgentEditError(RuntimeError):
    """Raised when an agent cannot be modified (unknown / frozen / guardian / bad save)."""


class AgentNotEditableError(AgentEditError):
    """Raised specifically when an agent is frozen or a guardian — a 403, not a 422."""


@dataclass(frozen=True)
class AgentLocator:
    name: str
    origin: str          # "commons" | "personal"
    path: Path           # the file to read current values from
    freeze: str
    guardian: bool


def _locate(name: str) -> AgentLocator | None:
    """Find an agent by name, preferring the commons origin, then the vault.

    Returns ``None`` when no such agent exists on this machine.
    """
    name = (name or "").strip().lower()
    commons_path = _af.commons_agent_path(name)
    if commons_path.is_file():
        meta = parse_file(commons_path).meta or {}
        return AgentLocator(
            name=name, origin="commons", path=commons_path,
            freeze=str(meta.get("freeze") or "").strip().lower(),
            guardian=_audit._is_guardian(name, meta),
        )
    d = _pa.vault_agents_dir()
    if d is not None:
        p = Path(d) / f"{name}.md"
        if p.is_file():
            meta = parse_file(p).meta or {}
            return AgentLocator(
                name=name, origin="personal", path=p,
                freeze=str(meta.get("freeze") or "").strip().lower(),
                guardian=_audit._is_guardian(name, meta),
            )
    return None


def editability(name: str) -> dict:
    """Whether ``name`` may be modified, and why not if it can't.

    ``{exists, editable, reason, frozen, guardian, origin}``. A frozen or guardian
    agent is reported ``editable: False`` with a member-facing ``reason``.
    """
    loc = _locate(name)
    if loc is None:
        return {"exists": False, "editable": False,
                "reason": f"no agent named {name!r} is installed on this machine.",
                "frozen": False, "guardian": False, "origin": None}
    frozen = loc.freeze == "frozen"
    if frozen:
        reason = (f"agent {loc.name!r} is frozen and can't be edited — it is "
                  "centre-controlled; propose a change via PR against "
                  f"agents/{loc.name}.md.")
    elif loc.guardian:
        reason = (f"agent {loc.name!r} is a guardian (security / audit) agent and "
                  "can't be edited — weakening a guardian is exactly what the "
                  "integrity audit is built to prevent.")
    else:
        reason = ""
    return {"exists": True, "editable": not (frozen or loc.guardian),
            "reason": reason, "frozen": frozen, "guardian": loc.guardian,
            "origin": loc.origin}


def _diff_vs_commons(name: str) -> str:
    """Unified diff of the current working copy vs the commons original.

    Empty string when there is no commons origin (a net-new personal agent) or
    the two are identical. Drives the MODIFY "diff-vs-commons" pane.
    """
    commons_path = _af.commons_agent_path(name)
    if not commons_path.is_file():
        return ""
    installed = _af.installed_agents_dir() / f"{name}.md"
    current_path = installed if installed.is_file() else commons_path
    commons_text = commons_path.read_text(encoding="utf-8").splitlines(keepends=True)
    current_text = current_path.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = difflib.unified_diff(
        commons_text, current_text,
        fromfile=f"commons/{name}.md", tofile=f"yours/{name}.md")
    return "".join(diff)


def edit_context(name: str) -> dict:
    """Everything the MODIFY wizard needs to open: editability gate, the current
    field values (pre-fill), the locked-field list, and the diff-vs-commons pane.
    """
    gate = editability(name)
    if not gate["exists"]:
        raise AgentEditError(gate["reason"])
    loc = _locate(name)
    assert loc is not None
    rec = _agents.load_agent(loc.path)
    parsed = parse_file(loc.path)
    ctx = {
        "name": rec.name,
        "editable": gate["editable"],
        "reason": gate["reason"],
        "frozen": gate["frozen"],
        "guardian": gate["guardian"],
        "origin": loc.origin,
        "locked_fields": list(LOCKED_FIELDS),
        "fields": {
            "role": rec.description,
            "model": parsed.meta.get("model") or "",
            "required_tools": list(rec.required_tools),
            "denied_tools": list(rec.denied_tools),
            "category": rec.category,
            "freeze": rec.freeze,
            # The full current body, so the wizard can pre-fill / show it. Section
            # reverse-parsing is intentionally not attempted (brittle); the body
            # is offered raw for advanced edits.
            "body": parsed.body,
        },
        "diff_vs_commons": _diff_vs_commons(name),
    }
    return ctx


def save_edit(name: str, *, handle: str = "", allow_warn: bool = True,
              **fields) -> dict:
    """Assemble + validate + integrity-check + write a modified agent.

    ``fields`` are the DEFINE/MODIFY wizard fields (``role``, ``responsibilities``,
    ``non_goals``, ``required_tools``, ``denied_tools``, ``persona``,
    ``output_format``, ``guardrails``, ``example``, ``verdict``, ``model``).
    ``name`` / ``category`` / ``freeze`` are locked and taken from the existing
    agent.

    Flow:
      1. gate on editability — refuse a frozen / guardian agent (403-shaped);
      2. assemble the new markdown (reusing the DEFINE builder) and validate it;
      3. run the item-8 save-time integrity check; a ``block`` finding is a hard
         regression that refuses the save; ``warn`` findings are returned;
      4. fork-on-first-edit for a commons agent, or write in place for a personal
         agent, then re-install the working copy into ``~/.claude/agents/``.

    Returns ``{ok, name, path, origin, forked, warnings}``.
    """
    gate = editability(name)
    if not gate["exists"]:
        raise AgentEditError(gate["reason"])
    if not gate["editable"]:
        raise AgentNotEditableError(gate["reason"])

    loc = _locate(name)
    assert loc is not None
    rec = _agents.load_agent(loc.path)

    model = fields.get("model")
    if model in ("", None):
        model = None
    elif model not in _pa.VALID_MODELS:
        raise AgentEditError(
            f"unknown model {model!r} (choose fable|opus|sonnet|haiku).")

    # (2) assemble against the LOCKED name/category/freeze of the existing agent.
    proposed = _pa.build_agent_md(
        rec.name,
        role=fields.get("role") or rec.description,
        responsibilities=fields.get("responsibilities"),
        non_goals=fields.get("non_goals"),
        required_tools=fields.get("required_tools"),
        denied_tools=fields.get("denied_tools"),
        persona=fields.get("persona"),
        output_format=fields.get("output_format"),
        guardrails=fields.get("guardrails"),
        example=fields.get("example"),
        verdict=fields.get("verdict"),
        model=model,
        category=rec.category,
        freeze=rec.freeze,
    )
    try:
        _pa.validate_agent_text(proposed)
    except Exception as exc:  # noqa: BLE001
        raise AgentEditError(f"the modified agent did not validate: {exc}")

    # (3) item-8 save-time integrity — block on a hard regression.
    findings = _audit.assess_agent_edit(rec.name, proposed, handle=handle)
    blocks = [f for f in findings if f.severity == SEVERITY_BLOCK]
    warnings = [
        {"rule": f.rule, "severity": f.severity, "detail": f.current_state,
         "expected": f.expected_state}
        for f in findings if f.severity != SEVERITY_BLOCK
    ]
    if blocks:
        detail = "; ".join(f.current_state for f in blocks)
        raise AgentEditError(
            f"refusing to save — this edit is a hard integrity regression: {detail}")
    if warnings and not allow_warn:
        detail = "; ".join(w["detail"] for w in warnings)
        raise AgentEditError(
            f"refusing to save — integrity warnings (pass allow_warn to override): "
            f"{detail}")

    # (4) fork-on-first-edit (commons) or write-in-place (personal).
    forked = False
    if loc.origin == "commons":
        installed = _af.installed_agents_dir() / f"{name}.md"
        if installed.is_symlink() or name not in _af.load_manifest()["forks"]:
            _af.fork_agent(name, force=True)  # snapshot commons, land in vault forks
            forked = True
        canonical = _af.forks_dir() / f"{name}.md"
        canonical.write_text(proposed, encoding="utf-8")
        _af._install_working_copy(canonical, installed)
        out_path = canonical
    else:  # personal — edit the vault file in place
        canonical = loc.path
        canonical.write_text(proposed, encoding="utf-8")
        _pa._install(canonical)
        out_path = canonical

    return {"ok": True, "name": rec.name, "path": str(out_path),
            "origin": loc.origin, "forked": forked, "warnings": warnings}
