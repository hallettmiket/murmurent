"""
Purpose: ``UserPromptSubmit`` hook that records each prompt given to Claude
         Code in the personal vault, under ``sessions/<date>/<session>.md``,
         with the time, project, repository and commit (issue #292). Nobody
         pastes a prompt into the notebook again.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   The ``UserPromptSubmit`` payload on stdin (``session_id``, ``cwd``,
         ``prompt``).
Output:  Nothing on the quiet path. ``hookSpecificOutput.additionalContext``
         with one line when a prompt was NOT recorded because it matched a
         PHI or secret pattern, so the session knows the record has a gap.

The sessions stream is **personal-vault only**. It is never published to the
lab oracle, and in a protected project the session file is marked
``sensitivity: protected`` so the vault sync keeps it on this machine.

Before a prompt is written it is checked the way outgoing text is checked:
the PHI patterns from :mod:`murmurent.hooks.phi_check` (the explicit ones
always; the date-near-a-name heuristic only in a protected project, where
it is worth its false positives) and the secret detectors from
:mod:`murmurent.core.secret_scan`. A prompt that matches is not written, and
the hook says so.

Failure policy: never block, never raise. A missing vault, an unreadable
project record or a full disk costs one line of record, never the prompt.
``MURMURENT_NO_SESSION_LOG=1`` turns the hook off.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any

ENV_OFF = "MURMURENT_NO_SESSION_LOG"


def _project_and_repo(cwd: str) -> tuple[str, str, str]:
    """``(project, repository, sensitivity)`` for the repository at ``cwd``.
    Empty strings when there is none."""
    project = repository = ""
    sensitivity = "standard"
    try:
        from ..core import cert_projects as _cp
        from ..core import repo as _repo

        pr = _repo.find_project_repo(cwd)
        if pr is None:
            return "", "", sensitivity
        repository = _repo.repo_name(pr.path)
        project = _cp.project_name_for_cwd(cwd) or ""
        if project:
            rec = _cp.get(project)
            if rec is not None and rec.sensitivity:
                sensitivity = rec.sensitivity
    except Exception:  # noqa: BLE001
        pass
    return project, repository, sensitivity


def _commit(cwd: str) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def screen(prompt: str, cwd: str) -> list[str]:
    """Labels of every PHI or secret pattern in ``prompt``; empty when clean."""
    labels: list[str] = []
    try:
        from . import phi_check as _phi

        protected = False
        try:
            protected = _phi._is_protected_project(cwd)
        except Exception:  # noqa: BLE001 - unknown is treated as protected
            protected = True
        if protected:
            hits = _phi._pattern_hits(prompt)
        else:
            hits = [(label, m.group(0)) for label, pat in _phi.PHI_PATTERNS
                    for m in pat.finditer(prompt)]
        labels.extend(sorted({h[0] for h in hits}))
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..core import secret_scan as _ss

        for hit in _ss.scan_text(prompt, "prompt"):
            label = f"secret:{hit.rule}"
            if label not in labels:
                labels.append(label)
    except Exception:  # noqa: BLE001
        pass
    return labels


def evaluate(payload: dict[str, Any], *, now: _dt.datetime | None = None) -> str | None:
    """Record the prompt. Returns a note for the session only when the prompt
    was withheld; ``None`` otherwise (recorded, or nothing to record)."""
    if os.environ.get(ENV_OFF, "").strip() not in ("", "0"):
        return None
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    cwd = str(payload.get("cwd") or os.getcwd())
    session_id = str(payload.get("session_id") or "unknown")
    when = now or _dt.datetime.now()

    from ..core import lab_notebook as _nb

    paths = _nb.resolve_paths()
    if paths is None:
        return None

    labels = screen(prompt, cwd)
    if labels:
        return (
            "murmurent session log: this prompt was not recorded in the vault "
            f"because it matched {', '.join(labels)} pattern(s). The day's session "
            "record has a gap here; de-identify or remove the value if it should be kept."
        )

    project, repository, sensitivity = _project_and_repo(cwd)
    _nb.record_prompt(
        paths,
        session_id=session_id,
        prompt=prompt,
        when=when,
        project=project,
        repository=repository,
        commit=_commit(cwd) if repository else "",
        sensitivity=sensitivity,
    )
    return None


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
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
    try:
        note = evaluate(payload)
    except Exception:  # noqa: BLE001 - a hook that throws blocks the prompt
        return 0
    if note:
        dst.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": note,
            },
        }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
