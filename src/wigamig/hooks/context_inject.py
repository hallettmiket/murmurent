"""
Purpose: ``UserPromptSubmit`` hook that prepends a wigamig project-context
         ``<system-reminder>`` to the user's prompt.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``UserPromptSubmit`` payload JSON on stdin (CC hook contract).
Output: ``{"decision": "modify", "user_prompt": "<reminder>\n\n<original>"}``
        or ``{"decision": "allow"}`` if no active project.

The reminder includes:
- project name + sensitivity tier,
- charter first paragraph,
- the resolved member's role,
- active SEAs assigned-to or filed-by the member.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import IO, Any

from ..core.frontmatter import parse_file
from ..core.identity import resolve as resolve_identity
from ..core.repo import find_project_repo, read_members
from ..core.sea import filter_for_member, iter_seas


def _project_summary(start: str | None = None) -> str | None:
    repo = find_project_repo(start or os.getcwd())
    if repo is None:
        return None
    try:
        parsed = parse_file(repo.charter_path)
    except Exception:
        return None
    sensitivity = parsed.meta.get("sensitivity", "?")
    name = parsed.meta.get("project", repo.path.name)
    body = parsed.body.strip()
    first_para = body.split("\n\n", 1)[0] if body else ""
    members = read_members(repo.members_path) if repo.members_path else []
    identity = resolve_identity(allow_unknown=True)
    role = _resolve_role(identity.at_handle, parsed.meta, members)
    seas = iter_seas(repo)
    incoming = filter_for_member(seas, identity.handle, direction="incoming")
    outgoing = filter_for_member(seas, identity.handle, direction="outgoing")

    lines = [
        "<system-reminder>",
        "wigamig project context (auto-injected):",
        f"- project: {name} (sensitivity: {sensitivity})",
        f"- you: {identity.at_handle} ({role})",
    ]
    if first_para:
        cleaned = first_para.replace("\n", " ").strip()
        if len(cleaned) > 240:
            cleaned = cleaned[:237] + "..."
        lines.append(f"- charter: {cleaned}")
    if incoming:
        lines.append(
            "- SEAs assigned to you: " + ", ".join(f"#{s.id} ({s.state})" for s in incoming)
        )
    if outgoing:
        lines.append("- SEAs you filed: " + ", ".join(f"#{s.id} ({s.state})" for s in outgoing))
    if not (incoming or outgoing):
        lines.append("- SEAs: none for you in this project")
    lines.append("</system-reminder>")
    return "\n".join(lines)


def _resolve_role(at_handle: str, meta: dict[str, Any], members: list[str]) -> str:
    lead = str(meta.get("lead", "")).strip()
    if lead and lead.lstrip("'\"").rstrip("'\"") == at_handle:
        return "lead"
    if at_handle in members or at_handle in (meta.get("members") or []):
        return "member"
    return "non-member"


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw = src.read()
    if not raw.strip():
        dst.write(json.dumps({"decision": "allow"}))
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        dst.write(json.dumps({"decision": "allow"}))
        return 0
    if not isinstance(payload, dict):
        dst.write(json.dumps({"decision": "allow"}))
        return 0

    summary = _project_summary()
    if summary is None:
        dst.write(json.dumps({"decision": "allow"}))
        return 0

    original = payload.get("user_prompt") or payload.get("prompt") or ""
    new_prompt = summary + "\n\n" + str(original)
    dst.write(json.dumps({"decision": "modify", "user_prompt": new_prompt}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
