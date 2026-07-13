"""
Purpose: Group-level membership roster. The PI manages the lab's
         active members from here; deactivating a member retains
         their file (and therefore their authored history in audit
         logs, SEAs, projects) but blocks them from running murmurent
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
    fills them in via ``murmurent compliance certify`` later.
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

# Set by ``set_status`` to the path of the decommission report it just
# wrote (or ``None`` for activations). Lets the API endpoint surface the
# path back to the caller without changing set_status's return shape.
last_report_path: "Path | None" = None
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
    email: str = ""  # used to resolve the member's Slack account (users.lookupByEmail)
    github: str = ""  # GitHub login, for repo collaborator management
    slack: str = ""  # the member's Slack username / member id (shown in the Lab members list)
    card_fingerprint: str = ""  # the member's identity-card key fingerprint (revocation index)
    card_id: str = ""           # the issued card's id (revocation index)
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
        email=str(meta.get("email") or "").strip(),
        github=str(meta.get("github") or "").strip().lstrip("@"),
        slack=str(meta.get("slack") or "").strip().lstrip("@"),
        card_fingerprint=str(meta.get("card_fingerprint") or "").strip(),
        card_id=str(meta.get("card_id") or "").strip(),
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
    email: str = "",
    github: str = "",
    slack: str = "",
    card_fingerprint: str = "",
    card_id: str = "",
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
        email=(email or "").strip(),
        github=(github or "").strip().lstrip("@"),
        slack=(slack or "").strip().lstrip("@"),
        card_fingerprint=(card_fingerprint or "").strip(),
        card_id=(card_id or "").strip(),
        certifications=list(certifications or []),
        created=today.isoformat(),
    )
    _write(rec)
    return rec


def upsert_member(
    handle: str,
    *,
    full_name: str | None = None,
    role: str | None = None,
    email: str | None = None,
    github: str | None = None,
    slack: str | None = None,
    card_fingerprint: str | None = None,
    card_id: str | None = None,
    today: _dt.date | None = None,
) -> MemberRecord:
    """Add the member if absent, else update the provided fields (``None`` leaves a
    field unchanged). Re-activates a previously-removed member. This is what card
    issuance calls so the roster stays the single source of truth: a carded member
    always appears in ``members/<handle>.md`` with their email, github, and the
    card's fingerprint/id (the revocation index)."""
    norm = _strip_at(handle)
    p = member_path(norm)
    if not p.is_file():
        return add(handle=norm, full_name=full_name or norm,
                   role=role or "staff", email=email or "", github=github or "",
                   slack=slack or "",
                   card_fingerprint=card_fingerprint or "", card_id=card_id or "",
                   today=today)
    rec = parse_member(p)
    if full_name is not None:
        rec.full_name = full_name.strip() or rec.handle
    if role is not None:
        if role not in VALID_ROLES:
            raise MembershipError(f"role must be one of {VALID_ROLES}; got {role!r}")
        rec.role = role
    if email is not None:
        rec.email = email.strip()
    if github is not None:
        rec.github = github.strip().lstrip("@")
    if slack is not None:
        rec.slack = slack.strip().lstrip("@")
    if card_fingerprint is not None:
        rec.card_fingerprint = card_fingerprint.strip()
    if card_id is not None:
        rec.card_id = card_id.strip()
    rec.status = ACTIVE            # (re-)carding a member makes them active
    rec.deactivated_at = None
    _write(rec)
    return rec


def member_email_map(*, active_only: bool = True) -> dict[str, str]:
    """Return ``{handle: email}`` for members that have an email on file.

    Feeds ``slack_notify.sync_project_channel_members`` (handle→email→Slack
    uid). Members without an email are omitted (they can't be resolved to a
    Slack account until one is recorded)."""
    out: dict[str, str] = {}
    for rec in iter_members(include_inactive=not active_only):
        if rec.email:
            out[rec.handle] = rec.email
    return out


def set_status(
    handle: str, status: str, *, today: _dt.date | None = None,
    by_handle: str | None = None,
):
    """Flip a member's ``status:``. Refuses to deactivate the PI.

    When ``status == INACTIVE`` a decommission report is written to
    ``~/.murmurent/decommissions/`` listing the things tied to this
    member that the user may want to clean up by hand (personal vault,
    project memberships, slack DMs, signing key, etc.). The member file
    on disk is preserved — only the status flag flips. Reactivation
    via ``set_status(..., ACTIVE)`` is the reverse, no report.

    The report path (when written) is stashed on the module attribute
    ``last_report_path`` so the API endpoint can surface it back to the
    caller without changing this function's return type.
    """
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

    global last_report_path
    last_report_path = None
    if status == INACTIVE:
        from .decommission import CleanupItem, DecommissionRecord, write_report
        from .projects import iter_local_projects, load_summary

        items: list[CleanupItem] = []
        # Project memberships — list each project where this handle appears,
        # since the PI may want to remove them from project MEMBERS files.
        for repo in iter_local_projects():
            try:
                summary = load_summary(repo)
            except Exception:
                continue
            if any(m.lstrip("@").lower() == norm for m in summary.members):
                items.append(CleanupItem(
                    path=f"projects/{summary.name}/MEMBERS",
                    note=f"{summary.name} lists @{norm} as a member — remove if you want them dropped from the project.",
                ))
        items.append(CleanupItem(
            path=f"keys/{norm}.age",
            note="age signing key on lab-mgmt — rotate if compromised; otherwise leave so historical signatures verify.",
        ))
        items.append(CleanupItem(
            path=f"slack: @{norm}",
            note="Slack workspace membership — out of scope for murmurent; remove via Slack admin if needed.",
        ))
        actor = (by_handle or "system").lstrip("@")
        last_report_path = write_report(DecommissionRecord(
            kind="user",
            name=norm,
            decommissioned_by=f"@{actor}",
            cleanup_items=items,
            extra_meta={"role": rec.role, "deactivated_at": rec.deactivated_at or ""},
        ))
    return rec


def set_lab_sudo(handle: str, grant: bool) -> Path:
    """Grant or revoke the ``lab_sudo`` flag on a member's frontmatter.

    Murmurent-level "lab security admin" flag — gates access to the
    ``/security`` dashboard route. **Not OS-level sudo** — the OS sudo
    grant for the Tier 2 root-owned ACL dump script is a separate
    one-time sysadmin action (see docs/security-dashboard.md).

    Merges into ``<lab-mgmt>/members/<handle>.md`` frontmatter without
    disturbing other fields (contact, location, lab, certifications, …).
    When ``grant=False`` and the flag was set, the key is removed
    entirely rather than written as ``false`` — keeps frontmatter
    minimal.

    Raises :class:`MembershipError` if the member file doesn't exist.
    Caller is responsible for checking that ``handle`` is in the same
    lab as the granting PI and that the PI is actually the PI; this
    function trusts its input.
    """
    from .frontmatter import dump_document, parse_file
    norm = _strip_at(handle)
    path = member_path(norm)
    if not path.is_file():
        raise MembershipError(f"member file not found: {path}")
    parsed = parse_file(path)
    meta = dict(parsed.meta or {})
    if grant:
        meta["lab_sudo"] = True
    else:
        meta.pop("lab_sudo", None)
    path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
    return path


def lab_sudo_handles() -> list[str]:
    """Return all member handles with ``lab_sudo: true`` set.

    The PI is **not** included implicitly — call sites that want
    "everyone authorised to view /security including the PI" need to
    add ``pi_handle()`` to the result themselves. This function only
    reports the explicitly-granted set so the PI grant UI can show
    "you've granted lab_sudo to N members" accurately.
    """
    from .frontmatter import parse_file
    out: list[str] = []
    for rec in iter_members(include_inactive=False):
        try:
            meta = parse_file(rec.path).meta or {}
        except Exception:
            continue
        if meta.get("lab_sudo"):
            out.append(rec.handle)
    return out


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
    if rec.email:
        meta["email"] = rec.email
    if rec.github:
        meta["github"] = rec.github
    if rec.slack:
        meta["slack"] = rec.slack
    if rec.card_fingerprint:
        meta["card_fingerprint"] = rec.card_fingerprint
    if rec.card_id:
        meta["card_id"] = rec.card_id
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
