"""
Purpose: Per-core training catalog + per-member training records.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22
Input: ``<lab_info>/cores/<core>/lab-mgmt/training/<training_id>.md`` files
       (training catalog) + ``lab_mgmt/members/<handle>.md`` frontmatter's
       ``training:`` list (per-member completion records).
Output: ``TrainingSummary`` per training entry; ``TrainingRecord`` per
        (member, training) completion; ``check_prereqs`` validator for
        Phase 3 booking.

A service in a core's catalog (Phase 2a-c) may declare
``training_required: <training_id>``. Before a member can book that
service, they must have a completed (and non-expired) training record
for the referenced training. This module is the read-side surface +
the validator that Phase 3's booking endpoints call.

Storage layout:

  <lab_info>/cores/<core>/lab-mgmt/training/
    <training_id>.md        — training catalog entry (one per offering)

  <lab_mgmt>/members/<handle>.md
    ---
    handle: '@alice'
    ...
    training:
      - name: itc_basic_training
        completed: 2025-11-15
        by: '@gary'                    # who trained / signed off
        valid_until: 2027-11-15        # optional expiry (auto-computed if absent)
        notes: 'attended Nov 15 cohort'
    ---

Training records live with the member rather than on the core's side
because a member who trains on bioCORE's ITC + genomics-core's
sequencer has one consolidated training history — easier to audit
across cores, easier to refresh on rotation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import parse_file
from .registrar import lab_info_root


TRAINING_SUBDIR = "lab-mgmt/training"


# ---------------------------------------------------------------------------
# Training catalog (per-core)
# ---------------------------------------------------------------------------

@dataclass
class TrainingSummary:
    """One training offering in a core's catalog."""

    slug: str                              # short id, matches filename stem
    name: str                              # display name
    core: str                              # short core id
    description: str = ""
    body: str = ""
    duration_min: int = 30                 # default session length
    refresher_years: int | None = 2        # rotation; None = no expiry
    trainers: list[str] = field(default_factory=list)  # ['@gary', '@vdumeaux']
    location: str = ""                     # where training is delivered
    status: str = "active"                 # active | retired
    created: str = ""
    path: Path | None = None


def training_dir(core: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab_info>/cores/<core>/lab-mgmt/training/``."""
    return lab_info_root(env) / "cores" / core / "lab-mgmt" / "training"


def training_path(core: str, slug: str, env: dict[str, str] | None = None) -> Path:
    """Canonical path to a training catalog entry."""
    return training_dir(core, env) / f"{slug}.md"


def iter_trainings(
    core: str,
    *,
    include_retired: bool = False,
    env: dict[str, str] | None = None,
) -> list[TrainingSummary]:
    """Enumerate the training catalog for ``core``. Empty list if no
    training/ dir. Sorts by slug; silently skips unparseable files."""
    tdir = training_dir(core, env)
    if not tdir.is_dir():
        return []
    out: list[TrainingSummary] = []
    for entry in sorted(tdir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        try:
            parsed = parse_file(entry)
        except Exception:
            continue
        meta = parsed.meta or {}
        status = str(meta.get("status") or "active").lower()
        if status == "retired" and not include_retired:
            continue
        slug = str(meta.get("training") or entry.stem)
        # refresher_years can be explicit None (no expiry) or an int.
        refresher_raw = meta.get("refresher_years", 2)
        refresher: int | None
        if refresher_raw is None:
            refresher = None
        else:
            try:
                refresher = int(refresher_raw)
            except (TypeError, ValueError):
                refresher = 2
        out.append(TrainingSummary(
            slug=slug,
            name=str(meta.get("name") or slug),
            core=str(meta.get("core") or core),
            description=str(meta.get("description") or "").strip(),
            body=(parsed.body or "").strip(),
            duration_min=int(meta.get("duration_min") or 30),
            refresher_years=refresher,
            trainers=[str(h) for h in (meta.get("trainers") or [])],
            location=str(meta.get("location") or ""),
            status=status,
            created=str(meta.get("created") or ""),
            path=entry,
        ))
    return out


def get_training(
    core: str,
    slug: str,
    *,
    env: dict[str, str] | None = None,
) -> TrainingSummary | None:
    """Single training lookup by slug."""
    for t in iter_trainings(core, include_retired=True, env=env):
        if t.slug == slug:
            return t
    return None


# ---------------------------------------------------------------------------
# Per-member training records (lives on member.md frontmatter)
# ---------------------------------------------------------------------------

@dataclass
class TrainingRecord:
    """One completed-training row from a member's frontmatter."""

    name: str                              # matches a TrainingSummary slug
    completed: str = ""                    # ISO date (YYYY-MM-DD)
    by: str = ""                           # who signed off (@handle)
    valid_until: str = ""                  # ISO date or "" for no expiry
    notes: str = ""

    def is_current(self, *, today: _dt.date | None = None) -> bool:
        """True iff ``valid_until`` is empty (no expiry) or in the future."""
        if not self.valid_until:
            return True
        today = today or _dt.date.today()
        try:
            until = _dt.date.fromisoformat(self.valid_until)
        except ValueError:
            return True   # malformed — fail open (don't lock people out on a typo)
        return until >= today


def _member_path(handle: str, env: dict[str, str] | None = None) -> Path:
    """Resolve ``<lab_mgmt>/members/<handle>.md``.

    Lab-side training records here are advisory only — service prereqs
    check the core's own training_roster instead (the core is the
    authority on who's trained on the core's instruments)."""
    from .repo import lab_mgmt_repo_root
    return lab_mgmt_repo_root(env) / "members" / f"{handle.lstrip('@')}.md"


# ---------------------------------------------------------------------------
# Per-core training roster (the core is the authority — Gary writes here)
# ---------------------------------------------------------------------------

TRAINING_ROSTER_SUBDIR = "lab-mgmt/training_roster"


def training_roster_dir(
    core: str, env: dict[str, str] | None = None,
) -> Path:
    """``<lab_info>/cores/<core>/lab-mgmt/training_roster/``."""
    return lab_info_root(env) / "cores" / core / "lab-mgmt" / "training_roster"


def _roster_path(
    core: str, handle: str, env: dict[str, str] | None = None,
) -> Path:
    return training_roster_dir(core, env) / f"{handle.lstrip('@')}.md"


def list_core_member_trainings(
    core: str,
    handle: str,
    env: dict[str, str] | None = None,
) -> list[TrainingRecord]:
    """Read ``training:`` from the *core's* per-member roster file.

    This is the canonical source for booking-prereq checks. Returns
    [] when the core has no record for the member (the common case
    on a fresh install)."""
    path = _roster_path(core, handle, env)
    if not path.is_file():
        return []
    try:
        meta = parse_file(path).meta or {}
    except Exception:
        return []
    rows = meta.get("training") or []
    if not isinstance(rows, list):
        return []
    out: list[TrainingRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(TrainingRecord(
            name=str(row.get("name") or "").strip(),
            completed=str(row.get("completed") or ""),
            by=str(row.get("by") or ""),
            valid_until=str(row.get("valid_until") or ""),
            notes=str(row.get("notes") or ""),
        ))
    return [r for r in out if r.name]


def has_completed_on_core(
    core: str,
    handle: str,
    training_slug: str,
    *,
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """True iff ``handle`` has a current record on ``core``'s roster
    for ``training_slug``."""
    for r in list_core_member_trainings(core, handle, env=env):
        if r.name == training_slug and r.is_current(today=today):
            return True
    return False


def record_training(
    *,
    core: str,
    handle: str,
    training_slug: str,
    completed: str,
    by: str,
    valid_until: str = "",
    notes: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    """Gary's "sign-off" action: add (or update) a training record for
    ``handle`` on ``core``'s roster.

    Idempotent: if a record for the same ``training_slug`` already
    exists, it's replaced with the new fields. Commits via lab_info
    git ledger so the audit log captures the sign-off.
    """
    import yaml as _y
    from .registrar import (
        _git_commit_all, _git_init_if_needed, lab_info_root as _root,
    )
    handle_clean = handle.lstrip("@").lower()
    slug_clean = training_slug.strip()
    if not slug_clean:
        raise ValueError("training_slug is required")
    path = _roster_path(core, handle_clean, env)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Merge: read existing rows (if any), replace matching, append new.
    existing = list_core_member_trainings(core, handle_clean, env=env)
    by_name = {r.name: r for r in existing}
    by_name[slug_clean] = TrainingRecord(
        name=slug_clean,
        completed=completed,
        by=by.lstrip("@") and f"@{by.lstrip('@')}" or "",
        valid_until=valid_until,
        notes=notes,
    )
    rows = sorted(by_name.values(), key=lambda r: r.name)
    meta = {
        "member": f"@{handle_clean}",
        "core": core,
        "training": [
            {"name": r.name, "completed": r.completed,
             "by": r.by, "valid_until": r.valid_until,
             **({"notes": r.notes} if r.notes else {})}
            for r in rows
        ],
    }
    yaml_text = _y.safe_dump(meta, sort_keys=False).rstrip()
    body = (
        f"# Training roster — @{handle_clean} (core {core})\n\n"
        f"This file is maintained by the *core* (e.g. {core}'s leader). "
        f"It is the canonical record of which trainings @{handle_clean} "
        f"has completed under {core}'s purview. Booking prereqs are "
        f"checked against this file, not against the member's lab record.\n"
    )
    path.write_text(f"---\n{yaml_text}\n---\n\n{body}", encoding="utf-8")
    root = _root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"core {core}: training_roster +@{handle_clean} "
        f"{slug_clean} (by @{by.lstrip('@')})")
    return path


def list_member_trainings(
    handle: str,
    env: dict[str, str] | None = None,
) -> list[TrainingRecord]:
    """Read ``training:`` from a member's frontmatter. Empty list when
    the field is missing OR the member file doesn't exist (defensive —
    a fresh member with no training records is the common case)."""
    path = _member_path(handle, env)
    if not path.is_file():
        return []
    try:
        meta = parse_file(path).meta or {}
    except Exception:
        return []
    rows = meta.get("training") or []
    if not isinstance(rows, list):
        return []
    out: list[TrainingRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(TrainingRecord(
            name=str(row.get("name") or "").strip(),
            completed=str(row.get("completed") or ""),
            by=str(row.get("by") or ""),
            valid_until=str(row.get("valid_until") or ""),
            notes=str(row.get("notes") or ""),
        ))
    return [r for r in out if r.name]


def has_completed(
    handle: str,
    training_slug: str,
    *,
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """True iff ``handle`` has a current record for ``training_slug``."""
    for r in list_member_trainings(handle, env=env):
        if r.name == training_slug and r.is_current(today=today):
            return True
    return False


# ---------------------------------------------------------------------------
# Service-prereq validator (called by Phase 3 booking)
# ---------------------------------------------------------------------------

@dataclass
class TrainingCheck:
    """Result of validating one (member, service) booking attempt."""

    member: str
    training_slug: str | None              # what the service required, if any
    ok: bool                               # safe to book
    reason: str = ""                       # human-readable when not ok


def check_service_prereqs(
    *,
    member_handle: str,
    service,                               # ServiceSummary
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> TrainingCheck:
    """Decide whether ``member_handle`` is cleared to book ``service``.

    Pass-through when the service declares no training requirement.
    Otherwise verifies the *core's* training_roster has a current
    TrainingRecord whose ``name`` matches ``service.training_required``.
    The member's lab-side file is NOT consulted — the core is the
    authority on its own service prereqs.
    """
    slug = getattr(service, "training_required", None)
    core = getattr(service, "core", "") or ""
    if not slug:
        return TrainingCheck(
            member=member_handle, training_slug=None, ok=True,
            reason="service has no training requirement",
        )
    if core and has_completed_on_core(
        core, member_handle, slug, today=today, env=env,
    ):
        return TrainingCheck(
            member=member_handle, training_slug=slug, ok=True,
        )
    return TrainingCheck(
        member=member_handle, training_slug=slug, ok=False,
        reason=(
            f"@{member_handle.lstrip('@')} has no current record for "
            f"required training {slug!r}; book a training slot first "
            "(or refresh an expired record)."
        ),
    )


__all__ = [
    "TRAINING_SUBDIR", "TRAINING_ROSTER_SUBDIR",
    "TrainingSummary",
    "TrainingRecord",
    "TrainingCheck",
    "training_dir",
    "training_path",
    "iter_trainings",
    "get_training",
    "list_member_trainings",          # lab-side (advisory)
    "list_core_member_trainings",     # core-side (authoritative)
    "training_roster_dir",
    "has_completed",                  # lab-side helper (legacy)
    "has_completed_on_core",          # core-side helper (canonical)
    "record_training",                # leader's sign-off action
    "check_service_prereqs",
]
