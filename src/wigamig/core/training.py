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
    trainers: list[str] = field(default_factory=list)  # ['@gary', '@core_lead']
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
    """Resolve ``<lab_mgmt>/members/<handle>.md``."""
    from .repo import lab_mgmt_repo_root
    return lab_mgmt_repo_root(env) / "members" / f"{handle.lstrip('@')}.md"


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
    Otherwise verifies the member has a current TrainingRecord whose
    ``name`` matches ``service.training_required``.
    """
    slug = getattr(service, "training_required", None)
    if not slug:
        return TrainingCheck(
            member=member_handle, training_slug=None, ok=True,
            reason="service has no training requirement",
        )
    if has_completed(member_handle, slug, today=today, env=env):
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
    "TRAINING_SUBDIR",
    "TrainingSummary",
    "TrainingRecord",
    "TrainingCheck",
    "training_dir",
    "training_path",
    "iter_trainings",
    "get_training",
    "list_member_trainings",
    "has_completed",
    "check_service_prereqs",
]
