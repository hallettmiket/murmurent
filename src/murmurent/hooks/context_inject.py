"""
Purpose: ``UserPromptSubmit`` hook that prepends murmurent context to the
         user's prompt — the active project, and whether this repo's wiring
         has fallen behind the murmurent that is installed.
Author: Mike Hallett
Date: 2026-05-07
Input: ``UserPromptSubmit`` payload JSON on stdin (CC hook contract).
Output: ``hookSpecificOutput.additionalContext``, or nothing at all when there
        is neither an active project nor anything stale to report.

Two independent blocks, either of which can appear alone:

1. **Project context** — project name + sensitivity tier, the charter's first
   paragraph, the resolved member's role, and the SEAs assigned to or filed by
   them. Requires a CHARTER, so it appears only in project repos.

2. **Readiness notice** — keyed on the ``.murmurent.yaml`` marker instead, so
   it covers every murmurent-ready repo whether or not it is a project. It
   reports exactly one thing: that this repo's ``.claude/agents/`` points into
   a DIFFERENT copy of the commons than the one now installed. Claude Code
   prefers a repo's own agent file over the one in ``~/.claude/agents/``, so in
   that state the repo silently runs an older or foreign version of an agent
   while every other folder on the machine runs the current one.

   Two things are deliberately NOT reported, both of which this hook used to
   report and should not have:

   * **Agents in the commons with no link in this repo.** ``murmurent setup``
     links the whole commons into ``~/.claude/agents/``, which Claude Code
     loads in EVERY directory — so an agent absent from a repo's own
     ``.claude/agents/`` is still perfectly usable there. Saying "2 agents are
     not linked into this repo" implied they were unavailable, which was false,
     and sent the reader off to run a command that changed nothing they could
     observe.
   * **A ``bootstrap_version`` that merely differs from the running version.**
     ``repo_ready.needs_upgrade`` is true after every release, including one
     that changed nothing about this repo, so notifying on it would put a line
     in front of the user on every prompt after every upgrade and teach them to
     ignore the notice.
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
        "murmurent project context (auto-injected):",
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


MARKER = ".murmurent.yaml"


def _find_ready_repo(start: str | None = None) -> Path | None:
    """Nearest ancestor carrying the readiness marker, or None.

    Walks up rather than testing only the cwd, because a session is usually
    opened somewhere inside a repo (``exp/07_thing/``) rather than at its root.
    Stops at the filesystem root and at ``$HOME``, so a marker sitting in a
    home directory cannot make every shell look like a ready repo.
    """
    here = Path(start or os.getcwd()).resolve()
    home = Path.home().resolve()
    for cand in (here, *here.parents):
        if (cand / MARKER).is_file():
            return cand
        if cand == home:
            break
    return None


def _readiness_notice(start: str | None = None) -> str | None:
    """Tell the user when this ready repo's agent links have fallen behind.

    Reports one state: links resolving into a commons other than the installed
    one. On a machine with two murmurent clones that means the repo runs a
    different version of an agent from everywhere else, and nothing says so.

    An agent the commons has and this repo does not is NOT reported: the
    machine-wide links in ``~/.claude/agents/`` make every agent available in
    every directory regardless, so there is nothing for the reader to fix.

    Cheap by construction: two globs over ~14 files each, no network, no git.
    This runs on every prompt submission, so it must never raise and never
    block — every failure path returns None and the prompt goes through
    untouched.
    """
    try:
        repo = _find_ready_repo(start)
        if repo is None:
            return None

        from ..core.commons import commons_root  # noqa: PLC0415

        commons = commons_root()
        if not (commons / "agents").is_dir():
            return None

        linked_dir = repo / ".claude" / "agents"
        foreign: set[Path] = set()
        if linked_dir.is_dir():
            for f in linked_dir.glob("*.md"):
                if not f.is_symlink():
                    continue
                try:
                    root = f.readlink().parent.parent
                except OSError:
                    continue
                if root.resolve() != commons.resolve():
                    foreign.add(root)

        if not foreign:
            return None

        return "\n".join([
            "<system-reminder>",
            "murmurent readiness (auto-injected):",
            "- this folder's agent files point into "
            + ", ".join(str(f) for f in sorted(foreign))
            + f", which is not the murmurent you are running ({commons}). "
              "Claude Code prefers a folder's own agent files, so this folder "
              "is using a different version of those agents from the rest of "
              "the machine.",
            f"- fix: murmurent repo upgrade {repo} --all-agents",
            "</system-reminder>",
        ])
    except Exception:  # noqa: BLE001
        # A hook that throws blocks the prompt. Nothing here is worth that.
        return None


def _resolve_role(at_handle: str, meta: dict[str, Any], members: list[str]) -> str:
    lead = str(meta.get("lead", "")).strip()
    if lead and lead.lstrip("'\"").rstrip("'\"") == at_handle:
        return "lead"
    if at_handle in members or at_handle in (meta.get("members") or []):
        return "member"
    return "non-member"


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    """UserPromptSubmit hook. CC's modern protocol: emit
    ``hookSpecificOutput.additionalContext`` to prepend system context
    to what the model sees; emit nothing to pass the prompt through
    unchanged. The legacy ``{"decision": "modify", "user_prompt": …}``
    form is no longer accepted.
    """
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw = src.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    blocks = [b for b in (_project_summary(), _readiness_notice()) if b]
    if not blocks:
        return 0

    dst.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(blocks),
        },
    }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
