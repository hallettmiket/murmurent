"""
Purpose: Build the hi-fi ``DashboardResponse`` from real wigamig data.
         Reuses the existing ``wigamig.core.dashboard`` snapshot for member /
         peers / SEAs / projects, then adds the new fields the redesign
         requires (today, attention, stats, spark, heatmap, notifs, notebook).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``handle`` (Western username) and the local lab-mgmt + project repos.
Output: ``DashboardResponse`` matching ``hifi-data.jsx`` field-for-field.

Where real data isn't wired yet, we return shape-correct placeholders marked
with a TODO comment so a later phase can swap them out without touching the
contract or the JSX panels.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from ..core import dashboard as core_dashboard
from ..core import inventory as inventory_core
from ..core.dashboard import DashboardSnapshot, _load_member_meta, _parse_certifications
from ..core.frontmatter import parse_file
from ..core.projects import ProjectSummary, iter_local_projects, load_summary
from ..core.sea import Sea, iter_seas
from . import audit_log
from . import contract as C

PI_HANDLE = core_dashboard.PI_HANDLE
NOTEBOOK_DIR_NAME = "lab-notebook"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_response(
    handle: str,
    *,
    persona: str = "member",
    today: _dt.date | None = None,
) -> C.DashboardResponse:
    """Assemble the full ``DashboardResponse`` for ``handle``.

    ``persona`` controls how attention queue and compliance heatmap are
    scoped:

    * ``"member"`` (default): attention = my own outstanding work + cert
      gaps; heatmap = projects I'm in.
    * ``"pi"``: attention = lab-wide blockers (peer cert lapses, project
      backlogs); heatmap = every project on disk. Silently coerced to
      ``"member"`` if the handle isn't authorised to view the PI lens
      (handoff: "non-PI users never see the toggle").
    """
    today_d = today or _dt.date.today()
    norm = handle.lstrip("@").lower()
    can_pi = norm == PI_HANDLE.lower()
    effective_persona: str = "pi" if (persona == "pi" and can_pi) else "member"

    snap = core_dashboard.build_snapshot(handle, today=today_d)
    project_summaries = [load_summary(repo) for repo in iter_local_projects()]
    all_seas = list(_iter_all_seas())

    member_block = _identity(snap.member, snap.full_name, snap.role)
    member_block = member_block.model_copy(update={"can_pi": can_pi})

    return C.DashboardResponse(
        today=_today_block(today_d),
        persona=effective_persona,  # type: ignore[arg-type]
        member=member_block,
        pi=_pi_identity(),
        attention=_attention(snap, effective_persona, project_summaries, today_d),
        stats=_stats(
            snap, all_seas, today_d,
            persona=effective_persona, projects=project_summaries,
        ),
        spark=_spark(all_seas, today_d),
        sparkLabels=_spark_labels(today_d),
        projects=_projects(project_summaries, all_seas, today_d),
        peers=_peers(snap),
        seas=_seas(snap, all_seas, today_d),
        experiments=_experiments(snap),
        notifs=_notifs(all_seas, today_d),
        heatmap=_heatmap(project_summaries, today_d, persona=effective_persona, member_handle=norm),
        inventory=_inventory(snap),
        notebook=_notebook(handle, today_d),
    )


def _iter_all_seas():
    """Yield ``(project_name, Sea)`` for every SEA in every local project."""
    for repo in iter_local_projects():
        try:
            summary = load_summary(repo)
        except Exception:
            continue
        for s in iter_seas(repo):
            yield summary.name, s


# ---------------------------------------------------------------------------
# today + identity
# ---------------------------------------------------------------------------


def _today_block(today_d: _dt.date) -> C.TodayBlock:
    return C.TodayBlock(
        iso=today_d.isoformat(),
        pretty=today_d.strftime("%A, %B %-d, %Y"),
        weekday=today_d.strftime("%a"),
        week=int(today_d.strftime("%V")),
    )


# Lab-default contact + location: applied to the PI and used as a fallback
# for any member that hasn't overridden the field on their own profile.
# These mirror the values that used to be hardcoded in ``FooterMeta``.
_LAB_DEFAULT_CONTACT = C.MemberContact(
    email="michael.hallett@example.edu",
    orcid="0000-0001-6738-6786",
    bluesky="@hallettmiket.bsky.social",
    github="hallettmiket",
    osf="osf.io/jz64u",
)
_LAB_DEFAULT_LOCATION = C.MemberLocation(
    office="MSB-360",
    dry_lab="MSB-309A",
    wet_labs="M359A & M433",
    address="1 Example Ave",
    city="London, ON N6A 3K7, Canada",
    department="Schulich School of Dentristy and Medicine · Department of Biochemistry",
)


def _identity(handle: str, full_name: str | None, role: str) -> C.IdentityBlock:
    """Build the current-member ``IdentityBlock`` with frontmatter overrides."""
    profile = _load_member_profile(handle)
    return C.IdentityBlock(
        handle=handle,
        name=full_name or profile.get("full_name") or handle,
        role=role,
        lab=str(profile.get("lab") or "hallett"),
        contact=_merge_contact(profile.get("contact")),
        location=_merge_location(profile.get("location")),
    )


def _pi_identity() -> C.IdentityBlock:
    profile = _load_member_profile(PI_HANDLE)
    full_name = profile.get("full_name")
    return C.IdentityBlock(
        handle=PI_HANDLE,
        name=str(full_name) if full_name else PI_HANDLE,
        role="Principal Investigator",
        lab=str(profile.get("lab") or "hallett"),
        contact=_merge_contact(profile.get("contact")),
        location=_merge_location(profile.get("location")),
    )


def _load_member_profile(handle: str) -> dict:
    """Return the full frontmatter dict for ``members/<handle>.md``."""
    from ..core.repo import lab_mgmt_repo_root as _root

    member_path = _root() / "members" / f"{handle}.md"
    if not member_path.is_file():
        return {}
    try:
        return dict(parse_file(member_path).meta or {})
    except Exception:
        return {}


def _merge_contact(meta: dict | None) -> C.MemberContact:
    """Merge a member's ``contact:`` frontmatter on top of the lab defaults."""
    base = _LAB_DEFAULT_CONTACT.model_dump()
    if isinstance(meta, dict):
        for key in C.MemberContact.model_fields:
            if meta.get(key):
                base[key] = str(meta[key])
    return C.MemberContact(**base)


def _merge_location(meta: dict | None) -> C.MemberLocation:
    """Merge a member's ``location:`` frontmatter on top of the lab defaults.

    Note: location merging is *per-field*, so a postdoc in a different
    building can override `office` while still inheriting the lab address.
    """
    base = _LAB_DEFAULT_LOCATION.model_dump()
    if isinstance(meta, dict):
        for key in C.MemberLocation.model_fields:
            if meta.get(key):
                base[key] = str(meta[key])
    return C.MemberLocation(**base)


# ---------------------------------------------------------------------------
# Attention queue
# ---------------------------------------------------------------------------


def _attention(
    snap: DashboardSnapshot,
    persona: str,
    projects: list[ProjectSummary],
    today_d: _dt.date,
) -> list[C.AttentionItem]:
    """Derive attention items.

    ``persona == "member"`` (default): user's own outstanding analysis,
    cert gaps on projects they're a member of, lab inventory.

    ``persona == "pi"``: lab-wide compliance lapses (every member's certs
    on every project), project backlog warnings, lab inventory. The PI
    typically does not need their *own* outstanding items in this view —
    those are tracked from the project leads' member-views.
    """
    if persona == "pi":
        return _attention_pi(projects, today_d)
    return _attention_member(snap)


def _attention_member(snap: DashboardSnapshot) -> list[C.AttentionItem]:
    items: list[C.AttentionItem] = []

    for item in snap.outstanding:
        if item.severity == "ok":
            continue
        items.append(
            C.AttentionItem(
                sev=item.severity,
                kind="EXP" if item.scope == "experiment" else "SEA",
                id=str(item.target),
                text=f"{item.scope.title()} {item.target} — {item.state}",
                project=item.project,
                age=f"{item.age_days}d" if item.age_days is not None else "—",
                actions=[["open", ""]],
            )
        )

    for row in snap.compliance:
        for cert in row.member_certs:
            if cert.name != "TCPS_2":
                continue
            if cert.status == "expired":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id="TCPS_2",
                        text="TCPS_2 expired — clinical access blocked",
                        project=row.project,
                        age=f"expired {cert.expires}" if cert.expires else "—",
                        actions=[["renew now", "primary"], ["guide", ""]],
                    )
                )
            elif cert.status == "missing" and row.sensitivity == "clinical":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id="TCPS_2",
                        text="TCPS_2 missing — clinical access blocked",
                        project=row.project,
                        age="—",
                        actions=[["enrol", "primary"]],
                    )
                )
            elif cert.status == "expiring":
                items.append(
                    C.AttentionItem(
                        sev="amber",
                        kind="CERT",
                        id="TCPS_2",
                        text=f"TCPS_2 expires {cert.expires}",
                        project=row.project,
                        age=cert.expires or "—",
                        actions=[["renew", "primary"]],
                    )
                )

    inv = snap.inventory_summary
    for row in inv.get("expired", []):
        items.append(
            C.AttentionItem(
                sev="red",
                kind="INV",
                id=row["name"],
                text=f"{row['name']} expired",
                project="—",
                age=str(row.get("expiry") or "—"),
                actions=[["order", "primary"]],
            )
        )
    for row in inv.get("low", []):
        items.append(
            C.AttentionItem(
                sev="amber",
                kind="INV",
                id=row["name"],
                text=f"{row['name']} {row.get('status', 'low')}",
                project="—",
                age="—",
                actions=[["order", "primary"]],
            )
        )

    return items


def _attention_pi(
    projects: list[ProjectSummary], today_d: _dt.date
) -> list[C.AttentionItem]:
    """PI lens: lab-wide cert lapses + project backlogs + inventory."""
    items: list[C.AttentionItem] = []

    # Per-project cert lapses across every member, on every clinical project.
    seen: set[tuple[str, str, str]] = set()  # de-dup (project, peer, cert_status)
    for project in projects:
        if project.sensitivity != "clinical":
            continue
        for raw in project.members:
            peer = raw.lstrip("@").lower()
            _name, _status, raw_certs = _load_member_meta(peer)
            certs = _parse_certifications(raw_certs, today_d)
            tcps = next((c for c in certs if c.name == "TCPS_2"), None)
            if tcps is None:
                continue
            key = (project.name, peer, tcps.status)
            if key in seen:
                continue
            seen.add(key)
            if tcps.status == "expired":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id=f"@{peer}",
                        text=(
                            f"@{peer} TCPS_2 expired — clinical access blocked "
                            f"on {project.name}"
                        ),
                        project=project.name,
                        age=f"expired {tcps.expires}" if tcps.expires else "—",
                        actions=[["nudge", "primary"], ["open profile", ""]],
                    )
                )
            elif tcps.status == "missing":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id=f"@{peer}",
                        text=(
                            f"@{peer} missing TCPS_2 — clinical access blocked "
                            f"on {project.name}"
                        ),
                        project=project.name,
                        age="—",
                        actions=[["nudge", "primary"]],
                    )
                )
            elif tcps.status == "expiring":
                items.append(
                    C.AttentionItem(
                        sev="amber",
                        kind="CERT",
                        id=f"@{peer}",
                        text=f"@{peer} TCPS_2 expires {tcps.expires}",
                        project=project.name,
                        age=tcps.expires or "—",
                        actions=[["nudge", "primary"]],
                    )
                )

    # Project backlog warnings: many open SEAs.
    BACKLOG_AMBER = 5
    BACKLOG_RED = 10
    for project in projects:
        from ..core.repo import CHARTER_FILENAME, ProjectRepo

        repo = ProjectRepo(
            path=project.path,
            charter_path=project.path / CHARTER_FILENAME,
            members_path=None,
        )
        open_count = sum(
            1 for s in iter_seas(repo) if s.state not in {"concluded", "declined"}
        )
        if open_count >= BACKLOG_RED:
            items.append(
                C.AttentionItem(
                    sev="red",
                    kind="PROJ",
                    id=project.name,
                    text=f"{open_count} open SEAs · backlog growing",
                    project=project.name,
                    age="—",
                    actions=[["review", "primary"]],
                )
            )
        elif open_count >= BACKLOG_AMBER:
            items.append(
                C.AttentionItem(
                    sev="amber",
                    kind="PROJ",
                    id=project.name,
                    text=f"{open_count} open SEAs · backlog growing",
                    project=project.name,
                    age="—",
                    actions=[["review", "primary"]],
                )
            )

    # Inventory: same on both lenses (lab-scoped).
    inv_summary = inventory_core
    for item in inv_summary.filter_expired(inv_summary.iter_items()):
        items.append(
            C.AttentionItem(
                sev="red",
                kind="INV",
                id=item.name,
                text=f"{item.name} expired",
                project="—",
                age=str(item.expiry or "—"),
                actions=[["order", "primary"]],
            )
        )
    for item in inv_summary.filter_low(inv_summary.iter_items()):
        items.append(
            C.AttentionItem(
                sev="amber",
                kind="INV",
                id=item.name,
                text=f"{item.name} {item.status}",
                project="—",
                age="—",
                actions=[["order", "primary"]],
            )
        )

    return items


# ---------------------------------------------------------------------------
# Stat strip
# ---------------------------------------------------------------------------


def _stats(
    snap: DashboardSnapshot,
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
    *,
    persona: str = "member",
    projects: list[ProjectSummary] | None = None,
) -> C.StatStrip:
    attn = _attention(snap, persona, projects or [], today_d)
    red = sum(1 for a in attn if a.sev == "red")
    amber = sum(1 for a in attn if a.sev == "amber")
    ok = sum(1 for a in attn if a.sev == "ok")

    closed_this_week, delta_pct = _seas_closed_this_week(all_seas, today_d)

    cert_expired = 0
    cert_expiring = 0
    cert_missing = 0
    seen: set[tuple[str, str]] = set()
    for row in snap.compliance:
        for cert in row.member_certs:
            key = (row.project, cert.name)
            if key in seen:
                continue
            seen.add(key)
            if cert.status == "expired":
                cert_expired += 1
            elif cert.status == "expiring":
                cert_expiring += 1
            elif cert.status == "missing":
                cert_missing += 1

    inv = snap.inventory_summary
    inv_expired = len(inv.get("expired", []))
    inv_low = len(inv.get("low", []))
    inv_exp30 = len(inv.get("expiring", []))

    nb = _notebook_stats(snap.member, today_d)

    return C.StatStrip(
        attention=C.AttentionStats(red=red, amber=amber, ok=ok),
        seas=C.SeasStats(
            **{
                "closedThisWeek": closed_this_week,
                "deltaPct": delta_pct,
                "in": len(snap.seas_incoming),
                "out": len(snap.seas_outgoing),
            }
        ),
        compliance=C.ComplianceStats(
            expired=cert_expired, expiring=cert_expiring, missing=cert_missing
        ),
        inventory=C.InventoryStats(expired=inv_expired, low=inv_low, expiring30=inv_exp30),
        notebook=nb,
    )


def _seas_closed_this_week(
    all_seas: list[tuple[str, Sea]], today_d: _dt.date
) -> tuple[int, int]:
    """Return (closed_this_week, delta_pct_vs_4week_avg)."""
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    prior_start = week_start - _dt.timedelta(weeks=4)

    this_week = 0
    prior_4_weeks = 0
    for _name, s in all_seas:
        if s.state != "concluded":
            continue
        when = _date_or_none(s.concluded_at)
        if when is None:
            continue
        if week_start <= when <= today_d:
            this_week += 1
        elif prior_start <= when < week_start:
            prior_4_weeks += 1

    avg_prior = prior_4_weeks / 4 if prior_4_weeks else 0
    if avg_prior == 0:
        delta_pct = 0 if this_week == 0 else 100
    else:
        delta_pct = round((this_week - avg_prior) / avg_prior * 100)
    return this_week, delta_pct


def _date_or_none(value) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _notebook_stats(handle: str, today_d: _dt.date) -> C.NotebookStats:
    folder = _notebook_folder(handle)
    if not folder.is_dir():
        return C.NotebookStats(entriesThisWeek=0, lastWritten="never")
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    files = sorted(folder.glob("*.md"))
    entries_this_week = 0
    last_written: _dt.date | None = None
    for f in files:
        try:
            d = _dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d >= week_start and d <= today_d:
            entries_this_week += 1
        if last_written is None or d > last_written:
            last_written = d
    if last_written is None:
        last = "never"
    elif last_written == today_d:
        last = "today"
    elif last_written == today_d - _dt.timedelta(days=1):
        last = "yesterday"
    else:
        last = last_written.isoformat()
    return C.NotebookStats(entriesThisWeek=entries_this_week, lastWritten=last)


# ---------------------------------------------------------------------------
# Sparkline (12 weekly counts of concluded SEAs)
# ---------------------------------------------------------------------------


def _spark(all_seas: list[tuple[str, Sea]], today_d: _dt.date) -> list[int]:
    counts = [0] * 12
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    for _name, s in all_seas:
        if s.state != "concluded":
            continue
        when = _date_or_none(s.concluded_at)
        if when is None:
            continue
        delta_weeks = (week_start - (when - _dt.timedelta(days=when.weekday()))).days // 7
        if 0 <= delta_weeks < 12:
            idx = 11 - delta_weeks
            counts[idx] += 1
    return counts


def _spark_labels(today_d: _dt.date) -> list[str]:
    week = int(today_d.strftime("%V"))
    return [f"w{((week - i - 1) % 53) + 1}" for i in range(11, -1, -1)]


# ---------------------------------------------------------------------------
# Projects + peers + SEAs + experiments
# ---------------------------------------------------------------------------


def _projects(
    projects: list[ProjectSummary],
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
) -> list[C.ProjectRow]:
    rows: list[C.ProjectRow] = []
    for p in projects:
        open_seas = 0
        last_activity: _dt.date | None = None
        for name, s in all_seas:
            if name != p.name:
                continue
            if s.state not in {"concluded", "declined"}:
                open_seas += 1
            for ts in (s.concluded_at, s.examined_at, s.completed_at, s.claimed_at):
                d = _date_or_none(ts)
                if d and (last_activity is None or d > last_activity):
                    last_activity = d
        rows.append(
            C.ProjectRow(
                name=p.name,
                sens=p.sensitivity,  # type: ignore[arg-type]
                lead=p.lead,
                choreo=p.choreography,
                members=len(p.members),
                openSeas=open_seas,
                lastActivity=_humanize(last_activity, today_d),
            )
        )
    return rows


def _humanize(when: _dt.date | None, today_d: _dt.date) -> str:
    if when is None:
        return "—"
    delta = (today_d - when).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 7:
        return f"{delta}d ago"
    if delta < 30:
        return f"{delta // 7}w ago"
    return when.isoformat()


def _peers(snap: DashboardSnapshot) -> list[C.PeerRow]:
    return [
        C.PeerRow(
            handle=p.handle,
            name=p.full_name or p.handle,
            role=p.role,
            tcps=p.tcps_status if p.tcps_status in {"ok", "expiring", "missing"} else "missing",
            shared=len(p.shared_projects),
        )
        for p in snap.peers
    ]


def _seas(
    snap: DashboardSnapshot,
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
) -> list[C.SeaRow]:
    norm = snap.member.lower()
    # Index timestamps by (project_name, sea_id) so we don't re-walk per row.
    ts_index: dict[tuple[str, int], str] = {}
    for name, s in all_seas:
        for ts in (s.completed_at, s.claimed_at, s.examined_at, s.concluded_at):
            d = _date_or_none(ts)
            if d:
                ts_index[(name, s.id)] = f"{(today_d - d).days}d"
                break

    rows: list[C.SeaRow] = []
    for row in snap.all_seas:
        if row.state == "declined":
            continue
        from_ = row.from_handle.lstrip("@").lower()
        to_ = row.to_handle.lstrip("@").lower()
        if norm == to_:
            direction: C.SeaDir = "in"
            who = row.from_handle
        elif norm == from_:
            direction = "out"
            who = row.to_handle
        else:
            continue
        rows.append(
            C.SeaRow(
                id=row.id,
                dir=direction,
                state=row.state,  # type: ignore[arg-type]
                kind=row.kind,  # type: ignore[arg-type]
                who=who,
                project=row.project,
                desc=row.description,
                age=ts_index.get((row.project, row.id), "—"),
            )
        )
    return rows


def _experiments(snap: DashboardSnapshot) -> list[C.ExperimentRow]:
    rows: list[C.ExperimentRow] = []
    for e in snap.all_experiments:
        rows.append(
            C.ExperimentRow(
                project=e.project,
                folder=e.slug,
                status=e.status,
                analysis=e.analysis_status,
                performer=e.performer[0] if e.performer else "—",
                date=str(e.date) if e.date else "—",
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Notifications (TODO: pull from audit log; for now, derive from recent SEAs)
# ---------------------------------------------------------------------------


def _notifs(all_seas: list[tuple[str, Sea]], today_d: _dt.date) -> list[C.Notif]:
    """Build the notifications feed.

    Prefers the lab-mgmt audit chain when it has any rows (Phase 5+).
    Falls back to deriving notifs from SEA state-change timestamps so a
    fresh setup with no audit history still surfaces something useful.
    """
    if audit_log.has_any_events(today=today_d):
        return _notifs_from_audit(today_d)
    return _notifs_from_sea_timestamps(all_seas, today_d)


def _notifs_from_audit(today_d: _dt.date) -> list[C.Notif]:
    """Read the most recent rows from ``<lab-mgmt>/audit/`` and format them."""
    now = _dt.datetime.combine(today_d, _dt.time(23, 59, 59), _dt.timezone.utc)
    events = audit_log.read_recent(days=14, limit=10, today=today_d)
    return [
        C.Notif(time=audit_log.humanize(e.ts, now=now), text=e.summary)
        for e in events
    ]


def _notifs_from_sea_timestamps(
    all_seas: list[tuple[str, Sea]], today_d: _dt.date
) -> list[C.Notif]:
    """Pre-Phase-5 fallback: derive notifs from SEA file timestamps."""
    events: list[tuple[_dt.date, str, str]] = []
    for name, s in all_seas:
        for state, ts in (
            ("claimed", s.claimed_at),
            ("complete", s.completed_at),
            ("examined", s.examined_at),
            ("concluded", s.concluded_at),
        ):
            d = _date_or_none(ts)
            if d is None:
                continue
            events.append(
                (
                    d,
                    "today" if d == today_d else d.isoformat(),
                    f"{s.to_handle if state in {'claimed', 'complete'} else s.from_handle} "
                    f"{state} SEA #{s.id} ({name})",
                )
            )
    events.sort(key=lambda r: r[0], reverse=True)
    return [C.Notif(time=time, text=text) for _d, time, text in events[:5]]


# ---------------------------------------------------------------------------
# Compliance heatmap
# ---------------------------------------------------------------------------


def _heatmap(
    projects: list[ProjectSummary],
    today_d: _dt.date,
    *,
    persona: str = "member",
    member_handle: str = "",
) -> C.Heatmap:
    """Per-project × per-member compliance grid.

    ``persona == "member"``: rows restricted to projects the user is on;
    member axis is the union of those projects' members.

    ``persona == "pi"``: every project + every member across the lab.
    """
    if persona == "member" and member_handle:
        norm = member_handle.lstrip("@").lower()
        scoped = [
            p for p in projects
            if any(m.lstrip("@").lower() == norm for m in p.members)
        ]
        if scoped:
            projects = scoped
    member_set: list[str] = []
    for p in projects:
        for m in p.members:
            if m not in member_set:
                member_set.append(m)
    rows: list[C.HeatmapRow] = []
    for p in projects:
        cells: list[C.HeatCell] = []
        project_members = set(p.members)
        for m in member_set:
            if m not in project_members:
                cells.append("na")
                continue
            handle = m.lstrip("@").lower()
            _name, _status, raw_certs = _load_member_meta(handle)
            certs = _parse_certifications(raw_certs, today_d)
            tcps = next((c for c in certs if c.name == "TCPS_2"), None)
            if tcps is None or tcps.status == "missing":
                cells.append("mis")
            elif tcps.status == "expired":
                cells.append("exp")
            elif tcps.status == "expiring":
                cells.append("amb")
            else:
                cells.append("ok")
        rows.append(C.HeatmapRow(project=p.name, sens=p.sensitivity, cells=cells))  # type: ignore[arg-type]
    return C.Heatmap(members=member_set, rows=rows)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def _inventory(snap: DashboardSnapshot) -> C.InventoryBlock:
    inv = snap.inventory_summary

    def _row(r: dict) -> C.InventoryItem:
        qty = r.get("qty")
        unit = r.get("unit")
        qty_str = f"{qty} {unit}" if qty is not None and unit else (str(qty) if qty is not None else None)
        return C.InventoryItem(
            name=r["name"],
            expiry=str(r.get("expiry") or "—"),
            qty=qty_str,
        )

    items = list(inventory_core.iter_items())
    in_stock_reagents = sum(1 for i in items if i.status == "in_stock")
    total_reagents = len(items)
    # Kits are a subset; without a tagged "kit" type, default to half/half
    # proxy. TODO: add a `kind:` field to inventory items.
    kits_in_stock = sum(1 for i in items if i.unit == "rxn" or "kit" in i.name)
    kits_total = max(kits_in_stock, sum(1 for i in items if "kit" in i.name) or 1)

    return C.InventoryBlock(
        expired=[_row(r) for r in inv.get("expired", [])],
        low=[_row(r) for r in inv.get("low", [])],
        expiring=[_row(r) for r in inv.get("expiring", [])],
        stock=C.InventoryStock(
            reagents=[in_stock_reagents, max(total_reagents, in_stock_reagents)],
            kits=[kits_in_stock, kits_total],
        ),
    )


# ---------------------------------------------------------------------------
# Notebook (Obsidian-style daily notes)
# ---------------------------------------------------------------------------


def _notebook_folder(handle: str) -> Path:
    """Resolve ``~/lab-notebook/`` for ``handle``.

    Per the handoff: notebook storage is per-user, read from each user's home
    directory. For the smoke test we honour ``$WIGAMIG_NOTEBOOK_DIR`` to
    redirect; otherwise ``~/lab-notebook/``.
    """
    import os

    override = os.environ.get("WIGAMIG_NOTEBOOK_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / NOTEBOOK_DIR_NAME


def _notebook(handle: str, today_d: _dt.date) -> C.NotebookBlock:
    folder = _notebook_folder(handle)
    days = _notebook_days(folder, today_d)
    today_entry = _notebook_today(folder, today_d)
    yesterday = _notebook_yesterday(folder, today_d)
    return C.NotebookBlock(
        folder=f"{NOTEBOOK_DIR_NAME}/",
        days=days,
        today=today_entry,
        yesterday_excerpt=yesterday,
    )


def _notebook_days(folder: Path, today_d: _dt.date) -> list[C.NotebookDay]:
    if not folder.is_dir():
        return _empty_week(today_d)
    rows: list[C.NotebookDay] = []
    for offset in range(7):
        d = today_d - _dt.timedelta(days=offset)
        path = folder / f"{d.isoformat()}.md"
        word_count = 0
        has_entry = path.is_file()
        if has_entry:
            try:
                word_count = len(path.read_text(encoding="utf-8").split())
            except OSError:
                word_count = 0
        rows.append(
            C.NotebookDay(
                iso=d.isoformat(),
                weekday=d.strftime("%a"),
                word_count=word_count,
                has_entry=has_entry,
                is_today=(d == today_d),
            )
        )
    return rows


def _empty_week(today_d: _dt.date) -> list[C.NotebookDay]:
    return [
        C.NotebookDay(
            iso=(today_d - _dt.timedelta(days=offset)).isoformat(),
            weekday=(today_d - _dt.timedelta(days=offset)).strftime("%a"),
            word_count=0,
            has_entry=False,
            is_today=(offset == 0),
        )
        for offset in range(7)
    ]


def _notebook_today(folder: Path, today_d: _dt.date) -> C.NotebookToday:
    """Parse ``folder/<today>.md`` into the discriminated content tree.

    TODO: swap this for a real markdown→block-tree parser. For now, return
    an empty content list with the right shape so the JSX panel can render
    a friendly empty state.
    """
    path = folder / f"{today_d.isoformat()}.md"
    title = today_d.strftime("%-d %B %Y")
    if not path.is_file():
        return C.NotebookToday(
            iso=today_d.isoformat(),
            title=title,
            tags=[],
            links_seas=[],
            links_exp=[],
            content=[
                C.NbHeading(kind="h4", text="No entry yet"),
                C.NbParagraph(
                    kind="p",
                    text=(
                        "Create your daily note at "
                        f"`~/{NOTEBOOK_DIR_NAME}/{today_d.isoformat()}.md` "
                        "to log today's plan, decisions, and links to SEAs."
                    ),
                ),
            ],
        )

    try:
        parsed = parse_file(path)
    except Exception:
        return C.NotebookToday(
            iso=today_d.isoformat(),
            title=title,
            tags=[],
            links_seas=[],
            links_exp=[],
            content=[C.NbParagraph(kind="p", text="(could not parse front-matter)")],
        )

    tags = [str(t) for t in parsed.meta.get("tags", []) or []]
    links_seas = [int(x) for x in parsed.meta.get("links_seas", []) or [] if str(x).isdigit()]
    links_exp = [str(x) for x in parsed.meta.get("links_exp", []) or []]
    blocks = _parse_markdown_blocks(parsed.body)
    return C.NotebookToday(
        iso=today_d.isoformat(),
        title=title,
        tags=tags,
        links_seas=links_seas,
        links_exp=links_exp,
        content=blocks,
    )


def _notebook_yesterday(folder: Path, today_d: _dt.date) -> C.NotebookYesterday:
    yest = today_d - _dt.timedelta(days=1)
    path = folder / f"{yest.isoformat()}.md"
    title = yest.strftime("%-d %B %Y")
    if not path.is_file():
        return C.NotebookYesterday(
            iso=yest.isoformat(),
            title=title,
            excerpt="(no entry yesterday)",
        )
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        body = ""
    excerpt_lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    excerpt = " ".join(excerpt_lines)[:280]
    return C.NotebookYesterday(iso=yest.isoformat(), title=title, excerpt=excerpt or "—")


def _parse_markdown_blocks(body: str):
    """Minimal markdown → block-tree.

    Supports H4, paragraph (with [[wikilinks]]), task ``- [ ] / - [x]``,
    bullet list, blockquote, fenced code. Anything else collapses to a
    paragraph. This is a pragmatic parser — the redesign explicitly
    constrains the notebook to these block kinds (see HANDOFF.md).
    """
    blocks: list = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            buf: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            blocks.append(C.NbCode(kind="code", text="\n".join(buf)))
            continue
        if stripped.startswith("#### "):
            blocks.append(C.NbHeading(kind="h4", text=stripped[5:]))
            i += 1
            continue
        if stripped.startswith(("- [ ]", "- [x]", "- [X]")):
            done = stripped[3].lower() == "x"
            text = stripped[6:].strip()
            blocks.append(C.NbTask(kind="task", done=done, text=text))
            i += 1
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(C.NbList(kind="list", items=items))
            continue
        if stripped.startswith("> "):
            buf2: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf2.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(C.NbBlockquote(kind="blockquote", text=" ".join(buf2)))
            continue
        # Default: paragraph (consume contiguous non-blank, non-special lines).
        buf3: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "- ", "> ", "```"))
        ):
            buf3.append(lines[i].strip())
            i += 1
        blocks.append(C.NbParagraph(kind="p", text=" ".join(buf3)))
    return blocks
