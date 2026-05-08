"""
Purpose: Group-level membership roster. The PI manages the lab's
         active members from here; deactivating a member retains
         their file (and therefore their authored history in audit
         logs, SEAs, projects) but blocks them from running wigamig
         actions.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``<lab-mgmt>/members/<handle>.md`` (one markdown file per
       lab member, with ``status: active | inactive`` frontmatter).
Output: ``MemberRecord`` dataclass + add / set_status / is_active /
        iter_members helpers.

Design:
  - ``add(handle, full_name, role)`` creates a fresh member file with
    ``status: active``. Certifications start empty; the new member
    fills them in via ``wigamig compliance certify`` later.
  - ``set_status(handle, "inactive")`` flips the status flag without
    deleting anything. ``set_status(handle, "active")`` reactivates.
  - ``is_active(handle)`` is the authorisation primitive — call sites
    check this before running any action that should be blocked for
    deactivated members.
  - The PI cannot be deactivated (would break the lab). The PI handle
    is read fresh from ``<lab-mgmt>/lab.md`` per call.

Rationale for "deactivate, don't delete":
  - Deletion would leave dangling references in audit logs, SEAs that
    have ``from: @<handle>``, project MEMBERS, dashboards. We prefer
    historical fidelity. A 'tombstone' status keeps the trail intact.
  - Reactivation is a one-line change instead of "recreate from
    scratch" — useful for sabbaticals, leaves of absence.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import dump_document, parse_file
from .lab import pi_handle
from .repo import lab_mgmt_repo_root

MEMBERS_SUBDIR = "members"
ACTIVE = "active"
INACTIVE = "inactive"
VALID_STATUSES: tuple[str, ...] = (ACTIVE, INACTIVE)
VALID_ROLES: tuple[str, ...] = (
    "pi",
    "postdoc",
    "student",
    "research_assistant",
    "staff",
    "collaborator",
)


class MembershipError(ValueError):
    """Schema or state error in membership management."""


class MemberNotFound(MembershipError):
    """No matching member file on disk."""


class MemberAlreadyExists(MembershipError):
    """add() called for a handle that already has a member file."""


class CannotDeactivatePI(MembershipError):
    """The PI must remain active. Rotate via lab.md if you need a new PI."""


@dataclass
class MemberRecord:
    """One member parsed from disk."""

    handle: str  # bare, no @
    full_name: str
    role: str
    status: str
    certifications: list[str] = field(default_factory=list)
    created: str | None = None
    deactivated_at: str | None = None
    body: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def members_dir() -> Path:
    return lab_mgmt_repo_root() / MEMBERS_SUBDIR


def member_path(handle: str) -> Path:
    return members_dir() / f"{_strip_at(handle)}.md"


def parse_member(path: Path) -> MemberRecord:
    parsed = parse_file(path)
    meta = parsed.meta or {}
    handle_raw = str(meta.get("handle") or path.stem)
    return MemberRecord(
        handle=_strip_at(handle_raw),
        full_name=str(meta.get("full_name") or _strip_at(handle_raw)),
        role=str(meta.get("role") or "staff"),
        status=str(meta.get("status") or ACTIVE),
        certifications=[str(c) for c in (meta.get("certifications") or [])],
        created=str(meta.get("created")) if meta.get("created") else None,
        deactivated_at=str(meta.get("deactivated_at")) if meta.get("deactivated_at") else None,
        body=parsed.body,
        path=path,
    )


def iter_members(*, include_inactive: bool = True) -> list[MemberRecord]:
    """Return every member on disk (sorted by handle).

    Pass ``include_inactive=False`` to filter to active members only.
    """
    out: list[MemberRecord] = []
    d = members_dir()
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.md")):
        try:
            rec = parse_member(path)
        except Exception:
            continue
        if not include_inactive and rec.status != ACTIVE:
            continue
        out.append(rec)
    return out


def get(handle: str) -> MemberRecord:
    path = member_path(handle)
    if not path.is_file():
        raise MemberNotFound(f"no member: @{_strip_at(handle)}")
    return parse_member(path)


def is_active(handle: str) -> bool:
    """``True`` only when the member file exists *and* status is active."""
    try:
        rec = get(handle)
    except MemberNotFound:
        return False
    return rec.status == ACTIVE


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def add(
    *,
    handle: str,
    full_name: str,
    role: str = "staff",
    certifications: list[str] | None = None,
    today: _dt.date | None = None,
) -> MemberRecord:
    """Create a new member file with ``status: active``."""
    norm = _strip_at(handle)
    if not norm or not norm.replace("_", "").replace("-", "").isalnum():
        raise MembershipError(
            f"handle must be alphanumeric+underscore/dash; got {handle!r}"
        )
    if role not in VALID_ROLES:
        raise MembershipError(f"role must be one of {VALID_ROLES}; got {role!r}")
    path = member_path(norm)
    if path.is_file():
        raise MemberAlreadyExists(f"@{norm} already exists at {path}")
    today = today or _dt.date.today()

    rec = MemberRecord(
        handle=norm,
        full_name=full_name.strip() or norm,
        role=role,
        status=ACTIVE,
        certifications=list(certifications or []),
        created=today.isoformat(),
    )
    _write(rec)
    return rec


def set_status(
    handle: str, status: str, *, today: _dt.date | None = None
) -> MemberRecord:
    """Flip a member's ``status:``. Refuses to deactivate the PI."""
    if status not in VALID_STATUSES:
        raise MembershipError(f"status must be one of {VALID_STATUSES}; got {status!r}")
    norm = _strip_at(handle)
    rec = get(norm)
    if status == INACTIVE and norm == pi_handle().lower():
        raise CannotDeactivatePI(
            "Cannot deactivate the PI. Rotate via <lab-mgmt>/lab.md first."
        )
    today = today or _dt.date.today()
    rec.status = status
    rec.deactivated_at = today.isoformat() if status == INACTIVE else None
    _write(rec)
    return rec


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _strip_at(h: str) -> str:
    return str(h or "").strip().lstrip("@").lower()


def _write(rec: MemberRecord) -> Path:
    """Persist ``rec`` to ``<lab-mgmt>/members/<handle>.md``."""
    d = members_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = member_path(rec.handle)
    body = rec.body or _default_body(rec)
    meta: dict = {
        "handle": f"@{rec.handle}",
        "full_name": rec.full_name,
        "role": rec.role,
        "status": rec.status,
    }
    if rec.certifications:
        meta["certifications"] = list(rec.certifications)
    if rec.created:
        meta["created"] = rec.created
    if rec.deactivated_at:
        meta["deactivated_at"] = rec.deactivated_at
    path.write_text(dump_document(meta, body), encoding="utf-8")
    rec.path = path
    return path


def _default_body(rec: MemberRecord) -> str:
    return (
        f"# @{rec.handle}\n\n"
        f"Profile for **{rec.full_name}** ({rec.role}).\n\n"
        "Edit this file to record interests, current projects, and any\n"
        "non-credentialing context. All compliance state is in the\n"
        "`certifications:` frontmatter.\n"
    )
