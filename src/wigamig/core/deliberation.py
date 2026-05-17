"""
Purpose: Render and update finalisation-choreography deliberation documents.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Scope (`sea` / `experiment` / `project`), target id, agent roster,
       project repo path.
Output: Markdown text for new deliberations; updated frontmatter on `examine`
        and `conclude` transitions.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Iterable

from .frontmatter import dump_document, parse_file
from .repo import ProjectRepo

DELIBERATION_SUBDIR = "deliberations"
VALID_SCOPES: tuple[str, ...] = ("sea", "experiment", "project")
DEFAULT_AGENT_ROSTER: tuple[str, ...] = (
    "bookworm",
    "blacksmith",
    "adversary",
    "artist",
    "conscience",
    "lawyer",
    "oracle",
    "security_guard",
)
VALID_ANALYSIS_STATES: tuple[str, ...] = ("not_started", "examined", "concluded")


def deliberation_path(repo: ProjectRepo, scope: str, target: str) -> Path:
    """Return the deliberation file path for ``scope`` + ``target``."""
    if scope == "project":
        return repo.path / DELIBERATION_SUBDIR / "project.md"
    if scope == "sea":
        return repo.path / DELIBERATION_SUBDIR / "sea" / f"{target}.md"
    if scope == "experiment":
        return repo.path / DELIBERATION_SUBDIR / "exp" / f"{target}.md"
    raise ValueError(f"unknown scope: {scope!r}; must be one of {VALID_SCOPES!r}")


def _today() -> str:
    return _dt.date.today().isoformat()


def render_deliberation(
    *,
    scope: str,
    target: str,
    operational_status: str,
    agent_roster: Iterable[str] = DEFAULT_AGENT_ROSTER,
    members: Iterable[str] = (),
    analysis_status: str = "not_started",
    examined_at: str | None = None,
    concluded_at: str | None = None,
) -> str:
    """Render a fresh deliberation document with empty agent + member sections."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"unknown scope: {scope!r}")
    if analysis_status not in VALID_ANALYSIS_STATES:
        raise ValueError(f"unknown analysis_status: {analysis_status!r}")

    meta: dict[str, Any] = {
        "scope": scope,
        "target": target,
        "operational_status": operational_status,
        "analysis_status": analysis_status,
    }
    if examined_at is not None:
        meta["examined_at"] = examined_at
    if concluded_at is not None:
        meta["concluded_at"] = concluded_at

    body_lines: list[str] = []
    body_lines.append(f"# Deliberation: {scope} {target}")
    body_lines.append("")
    body_lines.append(
        "_Agent and member sections begin empty. The squad fills each in during "
        "`examine`, then drafts the attempted statement during `conclude`._"
    )
    body_lines.append("")
    body_lines.append("## Agent contributions")
    for agent in agent_roster:
        body_lines.append("")
        body_lines.append(f"### {agent}")
        body_lines.append("")
        body_lines.append("_(invoke the agent in your CC session and paste its contribution here)_")
    body_lines.append("")
    body_lines.append("## Member reflections")
    member_list = list(members)
    if member_list:
        for member in member_list:
            body_lines.append("")
            body_lines.append(f"### {member}")
            body_lines.append("")
            body_lines.append("_(squad member reflection)_")
    else:
        body_lines.append("")
        body_lines.append("_(add one subsection per squad member)_")
    body_lines.append("")
    body_lines.append("## Group oracle context")
    body_lines.append("")
    body_lines.append("- _(novel / extends / contradicts existing findings)_")
    body_lines.append("")
    body_lines.append("## Attempted statement")
    body_lines.append("")
    body_lines.append(
        "_(filled in during conclude — claim, partial findings, explicit non-consensus, artefact reference, or next steps)_"
    )
    body_lines.append("")
    body_lines.append("## Caveats and dissent")
    body_lines.append("")
    body_lines.append("- _(none yet)_")
    body_lines.append("")
    body_lines.append("## Approval log")
    body_lines.append("")
    body_lines.append("- _(populated as squad members approve)_")
    body_lines.append("")
    body = "\n".join(body_lines)
    return dump_document(meta, body)


REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Agent contributions",
    "## Member reflections",
    "## Group oracle context",
    "## Attempted statement",
    "## Caveats and dissent",
    "## Approval log",
)


def assert_sections_present(text: str, *, context: str = "") -> None:
    """Raise ``ValueError`` if any required deliberation section is missing.

    Used by ``conclude`` as a guardrail before sealing the deliberation.
    """
    missing = [h for h in REQUIRED_SECTIONS if h not in text]
    if missing:
        suffix = f" in {context}" if context else ""
        raise ValueError(
            f"Deliberation document missing required section(s){suffix}: " f"{', '.join(missing)}"
        )


def update_status(path: Path, *, analysis_status: str) -> None:
    """Update ``analysis_status`` (+ examined_at / concluded_at) on a deliberation."""
    if analysis_status not in VALID_ANALYSIS_STATES:
        raise ValueError(f"unknown analysis_status: {analysis_status!r}")
    parsed = parse_file(path)
    parsed.meta["analysis_status"] = analysis_status
    today = _today()
    if analysis_status == "examined":
        parsed.meta["examined_at"] = today
    elif analysis_status == "concluded":
        parsed.meta.setdefault("examined_at", today)
        parsed.meta["concluded_at"] = today
    path.write_text(dump_document(parsed.meta, parsed.body), encoding="utf-8")
