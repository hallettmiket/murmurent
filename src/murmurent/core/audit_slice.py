"""
Purpose: Recent state-changing actions on a core, read from the
         ``lab_info`` git log. Powers the audit-log card on the
         core leader dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Every mutation in ``core.registrar``, ``core.services``,
``core.service_requests`` etc. commits to the ``$MURMURENT_LAB_INFO_ROOT``
git repo with a message starting ``core <core>:``. We rely on that
prefix to filter the log per-core without a separate database.

Defensive design:
  - If lab_info is not a git repo (fresh install, never mutated):
    return an empty list.
  - If git is not on PATH: return empty list with a synthetic
    note line.
  - Never raises — the audit panel must not break the dashboard
    if git itself is misbehaving.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .registrar import lab_info_root


@dataclass
class AuditEntry:
    """One commit on the lab_info ledger that touched ``core``."""

    sha: str                               # short hex
    iso_ts: str                            # ISO8601 UTC
    author: str                            # 'name <email>'
    subject: str                           # commit subject line (post-prefix)


def _git_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"],
                            capture_output=True, check=False)
        return r.returncode == 0
    except (OSError, FileNotFoundError):
        return False


def slice_for_core(
    core: str,
    *, limit: int = 50,
    env: dict[str, str] | None = None,
) -> list[AuditEntry]:
    """Return up to ``limit`` recent commits whose subject matches
    ``core <core>:``. Newest first."""
    if not _git_available():
        return []
    root = lab_info_root(env)
    if not (root / ".git").is_dir():
        return []
    # Match any commit whose subject mentions ``<core>`` as a word.
    # Catches all conventions in use:
    #   - "core biocore: request <rid> -> in_progress"     (service_requests)
    #   - "registrar: add service biocore/itc"             (services)
    #   - "registrar: create core biocore (leader: @gary)" (registrar)
    # Pre-filter at the git layer with a coarse substring grep (cheap)
    # then refine in Python with a word-boundary regex (POSIX ERE
    # doesn't have \b; git --grep doesn't honour Perl regex).
    try:
        r = subprocess.run(
            ["git", "-C", str(root),
             "log", f"-n{max(1, int(limit) * 4)}",  # over-fetch; trim post-regex
             "--grep", core,
             "--format=%h%x09%aI%x09%an <%ae>%x09%s"],
            capture_output=True, text=True, check=False,
        )
    except (OSError, FileNotFoundError):
        return []
    if r.returncode != 0:
        return []
    word_re = _re.compile(rf"(?<![A-Za-z0-9_]){_re.escape(core)}(?![A-Za-z0-9_])")
    prefix_alts = (f"core {core}: ", f"core {core}:")
    out: list[AuditEntry] = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        sha, iso_ts, author, subject = parts
        if not word_re.search(subject):
            continue   # coarse substring match was a false positive
        # Strip the canonical prefix when present so the UI doesn't
        # render it on every row; ``registrar:``-style commits stay
        # as-is so it's clear they were centre-level actions.
        for p in prefix_alts:
            if subject.startswith(p):
                subject = subject[len(p):].lstrip()
                break
        out.append(AuditEntry(
            sha=sha, iso_ts=iso_ts, author=author, subject=subject,
        ))
        if len(out) >= max(1, int(limit)):
            break
    return out


__all__ = ["AuditEntry", "slice_for_core"]
