"""
Purpose: Build per-member dashboard snapshots from lab-mgmt + project repos.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Lab-mgmt repo (members, projects), every local project repo, lab-VM
       refined dirs, and the SEA + deliberation files in each project.
Output: ``DashboardSnapshot`` dataclasses; a markdown renderer that mirrors the
        design's dashboard layout. Used by both ``scripts/generate_dashboard.py``
        and the Streamlit viewer.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import inventory, sea
from .frontmatter import parse_file
from .projects import ProjectSummary, iter_local_projects, load_summary
from .repo import lab_mgmt_repo_root, read_members

PI_HANDLE = "mhallet"

# Yellow / red thresholds for outstanding-analysis escalation, in days since
# operational `complete` without analysis having reached `examined`.
OUTSTANDING_YELLOW_DAYS = 14
OUTSTANDING_RED_DAYS = 60

# Yellow / red thresholds for an upcoming TCPS_2 expiry, in days from today.
CERT_YELLOW_DAYS = 60
CERT_RED_DAYS = 0


@dataclass
class CertStatus:
    """One certification entry on a member profile."""

    name: str
    status: str  # "ok" | "expiring" | "expired" | "missing"
    expires: str | None = None
    note: str = ""


@dataclass
class ProjectComplianceRow:
    """Per-project compliance row in the Security and Compliance panel."""

    project: str
    sensitivity: str
    member_certs: list[CertStatus] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class OutstandingItem:
    """One row of the Outstanding analysis panel."""

    scope: str
    target: str
    project: str
    state: str
    age_days: int | None
    severity: str  # "ok" | "yellow" | "red"


@dataclass
class PeerRow:
    """One peer in the shared-project group panel."""

    handle: str
    full_name: str | None
    role: str
    status: str
    shared_projects: list[str]
    tcps_status: str  # "ok" | "expiring" | "expired" | "missing"


@dataclass
class ExperimentRow:
    """One row of the cross-project experiment browser."""

    project: str
    slug: str
    status: str
    analysis_status: str
    performer: list[str]
    date: str | None


@dataclass
class SeaRow:
    """One row of the cross-project SEA browser."""

    project: str
    id: int
    state: str
    kind: str
    from_handle: str
    to_handle: str
    description: str


@dataclass
class DashboardSnapshot:
    """Everything the markdown writer + Streamlit viewer need to render."""

    member: str
    role: str
    full_name: str | None
    member_status: str
    projects: list[ProjectSummary]
    seas_incoming: list[sea.Sea]
    seas_outgoing: list[sea.Sea]
    outstanding: list[OutstandingItem]
    compliance: list[ProjectComplianceRow]
    inventory_summary: dict[str, list[dict]] = field(default_factory=dict)
    peers: list[PeerRow] = field(default_factory=list)
    all_projects: list[ProjectSummary] = field(default_factory=list)
    all_experiments: list[ExperimentRow] = field(default_factory=list)
    all_seas: list[SeaRow] = field(default_factory=list)
    is_pi: bool = False
    pi_view: dict[str, list] = field(default_factory=dict)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Compliance parsing
# ---------------------------------------------------------------------------


def _parse_certifications(raw: Iterable[str], today: _dt.date) -> list[CertStatus]:
    """Parse the seed's ``"NAME:VALUE"`` cert strings into :class:`CertStatus`."""
    out: list[CertStatus] = []
    seen_names: set[str] = set()
    for entry in raw or []:
        text = str(entry)
        if ":" not in text:
            out.append(CertStatus(name=text, status="missing"))
            continue
        name, value = text.split(":", 1)
        name = name.strip()
        value = value.strip()
        seen_names.add(name)
        if name == "TCPS_2":
            try:
                exp = _dt.date.fromisoformat(value)
            except ValueError:
                out.append(CertStatus(name=name, status="missing", note=value))
                continue
            delta = (exp - today).days
            if delta < CERT_RED_DAYS:
                out.append(CertStatus(name=name, status="expired", expires=value))
            elif delta <= CERT_YELLOW_DAYS:
                out.append(CertStatus(name=name, status="expiring", expires=value))
            else:
                out.append(CertStatus(name=name, status="ok", expires=value))
        else:
            ok_states = {"enrolled", "registered", "verified"}
            status = "ok" if value.lower() in ok_states else "missing"
            out.append(CertStatus(name=name, status=status, note=value))
    if "TCPS_2" not in seen_names:
        out.append(CertStatus(name="TCPS_2", status="missing"))
    return out


def _load_member_meta(handle: str) -> tuple[str | None, str, list[str]]:
    """Return ``(full_name, status, certifications)`` for ``handle`` from lab-mgmt."""
    member_path = lab_mgmt_repo_root() / "members" / f"{handle}.md"
    if not member_path.is_file():
        return None, "unknown", []
    parsed = parse_file(member_path)
    full_name = parsed.meta.get("full_name")
    status = str(parsed.meta.get("status", "active"))
    certs = list(parsed.meta.get("certifications") or [])
    return (str(full_name) if full_name else None), status, certs


# ---------------------------------------------------------------------------
# Outstanding analysis
# ---------------------------------------------------------------------------


def _date_or_none(value) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _classify_outstanding(age_days: int | None) -> str:
    if age_days is None:
        return "ok"
    if age_days >= OUTSTANDING_RED_DAYS:
        return "red"
    if age_days >= OUTSTANDING_YELLOW_DAYS:
        return "yellow"
    return "ok"


def _outstanding_for_member(
    handle: str, projects: Iterable[ProjectSummary], today: _dt.date
) -> list[OutstandingItem]:
    norm = handle.lstrip("@").lower()
    out: list[OutstandingItem] = []
    for project in projects:
        members = [m.lstrip("@").lower() for m in project.members]
        if norm not in members:
            continue
        repo = _project_repo_for(project)
        if repo is None:
            continue
        for s in sea.iter_seas(repo):
            from_ = s.from_handle.lstrip("@").lower()
            to_ = s.to_handle.lstrip("@").lower()
            if norm not in (from_, to_):
                continue
            if s.state in {"concluded", "declined"}:
                continue
            age = None
            if s.completed_at:
                d = _date_or_none(s.completed_at)
                if d:
                    age = (today - d).days
            severity = _classify_outstanding(age)
            if s.state in {"requested", "claimed"}:
                # not yet operationally complete -> not "outstanding analysis"
                continue
            out.append(
                OutstandingItem(
                    scope="sea",
                    target=str(s.id),
                    project=project.name,
                    state=s.state,
                    age_days=age,
                    severity=severity,
                )
            )

        # Experiment-scope outstanding: status complete + analysis_status not
        # concluded.
        for exp_dir in (repo.path / "exp").glob("*_*"):
            notebook = exp_dir / "notebook.md"
            if not notebook.is_file():
                continue
            try:
                parsed = parse_file(notebook)
            except Exception:
                continue
            if parsed.meta.get("status") != "complete":
                continue
            if parsed.meta.get("analysis_status") == "concluded":
                continue
            performer = [str(p).lstrip("@").lower() for p in parsed.meta.get("performer") or []]
            if norm not in performer:
                continue
            age = None
            d = _date_or_none(parsed.meta.get("examined_at") or parsed.meta.get("date"))
            if d:
                age = (today - d).days
            out.append(
                OutstandingItem(
                    scope="experiment",
                    target=exp_dir.name,
                    project=project.name,
                    state=str(parsed.meta.get("analysis_status", "not_started")),
                    age_days=age,
                    severity=_classify_outstanding(age),
                )
            )
    return out


def _project_repo_for(project: ProjectSummary):
    from .repo import CHARTER_FILENAME, MEMBERS_FILENAME, ProjectRepo

    charter = project.path / CHARTER_FILENAME
    members_path = project.path / MEMBERS_FILENAME
    if not charter.is_file():
        return None
    return ProjectRepo(
        path=project.path,
        charter_path=charter,
        members_path=members_path if members_path.is_file() else None,
    )


# ---------------------------------------------------------------------------
# Compliance per-project
# ---------------------------------------------------------------------------


def _compliance_rows(
    handle: str, projects: Iterable[ProjectSummary], member_certs: list[CertStatus]
) -> list[ProjectComplianceRow]:
    norm = handle.lstrip("@").lower()
    rows: list[ProjectComplianceRow] = []
    for project in projects:
        members = [m.lstrip("@").lower() for m in project.members]
        if norm not in members:
            continue
        notes: list[str] = []
        if project.sensitivity == "clinical":
            tcps = next((c for c in member_certs if c.name == "TCPS_2"), None)
            if tcps is None or tcps.status == "missing":
                notes.append("TCPS_2 missing — would block clinical access in production.")
            elif tcps.status == "expired":
                notes.append(f"TCPS_2 expired on {tcps.expires}.")
            elif tcps.status == "expiring":
                notes.append(f"TCPS_2 expires soon ({tcps.expires}).")
        rows.append(
            ProjectComplianceRow(
                project=project.name,
                sensitivity=project.sensitivity,
                member_certs=list(member_certs),
                notes=notes,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------


def build_snapshot(handle: str, *, today: _dt.date | None = None) -> DashboardSnapshot:
    """Assemble a :class:`DashboardSnapshot` for ``handle``."""
    today_d = today or _dt.date.today()
    norm_handle = handle.lstrip("@").lower()
    is_pi = norm_handle == PI_HANDLE.lower()

    full_name, member_status, raw_certs = _load_member_meta(norm_handle)
    member_certs = _parse_certifications(raw_certs, today_d)

    projects_all = [load_summary(repo) for repo in iter_local_projects()]
    member_projects = [
        p for p in projects_all if norm_handle in {m.lstrip("@").lower() for m in p.members}
    ]

    seas_incoming: list[sea.Sea] = []
    seas_outgoing: list[sea.Sea] = []
    for project in member_projects:
        repo = _project_repo_for(project)
        if repo is None:
            continue
        seas = sea.iter_seas(repo)
        seas_incoming.extend(sea.filter_for_member(seas, norm_handle, direction="incoming"))
        seas_outgoing.extend(sea.filter_for_member(seas, norm_handle, direction="outgoing"))

    role = (
        "lead"
        if any(p.lead.lstrip("@").lower() == norm_handle for p in member_projects)
        else "member"
    )
    outstanding = _outstanding_for_member(norm_handle, member_projects, today_d)
    compliance = _compliance_rows(norm_handle, member_projects, member_certs)

    inventory_summary = _inventory_summary()

    peers = _peers_for_member(norm_handle, member_projects, today_d)
    all_experiments = _all_experiments(projects_all)
    all_seas = _all_seas(projects_all)

    pi_view: dict[str, list] = {}
    if is_pi:
        pi_view = _build_pi_view(projects_all, today_d)

    return DashboardSnapshot(
        member=norm_handle,
        role=role if member_projects else "non-member",
        full_name=full_name,
        member_status=member_status,
        projects=member_projects,
        seas_incoming=seas_incoming,
        seas_outgoing=seas_outgoing,
        outstanding=outstanding,
        compliance=compliance,
        inventory_summary=inventory_summary,
        peers=peers,
        all_projects=list(projects_all),
        all_experiments=all_experiments,
        all_seas=all_seas,
        is_pi=is_pi,
        pi_view=pi_view,
        generated_at=today_d.isoformat(),
    )


def _peers_for_member(
    handle: str, member_projects: Iterable[ProjectSummary], today: _dt.date
) -> list[PeerRow]:
    """Build the group panel: anyone who shares a project with ``handle``."""
    norm = handle.lstrip("@").lower()
    project_list = list(member_projects)
    by_handle: dict[str, list[str]] = {}
    for project in project_list:
        for raw in project.members:
            peer = raw.lstrip("@").lower()
            if peer == norm:
                continue
            by_handle.setdefault(peer, []).append(project.name)

    rows: list[PeerRow] = []
    for peer, projects in sorted(by_handle.items()):
        full_name, status, raw_certs = _load_member_meta(peer)
        certs = _parse_certifications(raw_certs, today)
        # Read role from the lab-mgmt member file (if present).
        role = _peer_role(peer)
        tcps = next((c for c in certs if c.name == "TCPS_2"), None)
        rows.append(
            PeerRow(
                handle=peer,
                full_name=full_name,
                role=role,
                status=status,
                shared_projects=sorted(set(projects)),
                tcps_status=tcps.status if tcps else "missing",
            )
        )
    return rows


def _peer_role(handle: str) -> str:
    """Return the ``role`` field from ``members/<handle>.md`` (``unknown`` if missing)."""
    member_path = lab_mgmt_repo_root() / "members" / f"{handle}.md"
    if not member_path.is_file():
        return "unknown"
    parsed = parse_file(member_path)
    return str(parsed.meta.get("role", "unknown"))


def _all_experiments(projects: Iterable[ProjectSummary]) -> list[ExperimentRow]:
    """Walk every project's ``exp/`` and return one row per experiment."""
    rows: list[ExperimentRow] = []
    for project in projects:
        exp_root = project.path / "exp"
        if not exp_root.is_dir():
            continue
        for exp_dir in sorted(exp_root.glob("*_*")):
            notebook = exp_dir / "notebook.md"
            if not notebook.is_file():
                continue
            try:
                parsed = parse_file(notebook)
            except Exception:
                continue
            performer = [str(p) for p in (parsed.meta.get("performer") or [])]
            rows.append(
                ExperimentRow(
                    project=project.name,
                    slug=exp_dir.name,
                    status=str(parsed.meta.get("status", "planned")),
                    analysis_status=str(parsed.meta.get("analysis_status", "not_started")),
                    performer=performer,
                    date=parsed.meta.get("date") if parsed.meta.get("date") else None,
                )
            )
    return rows


def _all_seas(projects: Iterable[ProjectSummary]) -> list[SeaRow]:
    """Walk every project's ``seas/`` and return one row per SEA."""
    rows: list[SeaRow] = []
    for project in projects:
        repo = _project_repo_for(project)
        if repo is None:
            continue
        for s in sea.iter_seas(repo):
            rows.append(
                SeaRow(
                    project=project.name,
                    id=s.id,
                    state=s.state,
                    kind=s.kind,
                    from_handle=s.from_handle,
                    to_handle=s.to_handle,
                    description=s.description,
                )
            )
    return rows


def _inventory_summary() -> dict[str, list[dict]]:
    """Return low / expired / expiring lists for the dashboard panel."""
    items = inventory.iter_items()
    return {
        "low": [_inv_row(i) for i in inventory.filter_low(items)],
        "expired": [_inv_row(i) for i in inventory.filter_expired(items)],
        "expiring": [_inv_row(i) for i in inventory.filter_expiring(items, within_days=30)],
    }


def _inv_row(item: inventory.InventoryItem) -> dict:
    return {
        "name": item.name,
        "status": item.status,
        "expiry": item.expiry,
        "qty": item.qty,
        "unit": item.unit,
    }


def _build_pi_view(projects: Iterable[ProjectSummary], today: _dt.date) -> dict[str, list]:
    """Build the PI-only across-all-clinical-projects compliance grid."""
    grid: list[dict] = []
    for project in projects:
        if project.sensitivity != "clinical":
            continue
        for handle in project.members:
            norm = handle.lstrip("@").lower()
            full_name, _status, raw_certs = _load_member_meta(norm)
            certs = _parse_certifications(raw_certs, today)
            tcps = next((c for c in certs if c.name == "TCPS_2"), None)
            grid.append(
                {
                    "project": project.name,
                    "member": handle,
                    "full_name": full_name,
                    "tcps_status": tcps.status if tcps else "missing",
                    "tcps_expires": tcps.expires if tcps else None,
                }
            )
    return {"clinical_compliance": grid}


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(snapshot: DashboardSnapshot) -> str:
    """Render ``snapshot`` to the markdown layout the design specifies."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"member: '@{snapshot.member}'")
    lines.append(f"generated_at: {snapshot.generated_at}")
    lines.append(f"is_pi: {str(snapshot.is_pi).lower()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Dashboard for @{snapshot.member}")
    if snapshot.full_name:
        lines.append(f"_{snapshot.full_name}_")
    lines.append("")

    lines.append("## Identity")
    lines.append(f"- handle: @{snapshot.member}")
    lines.append(f"- role across projects: {snapshot.role}")
    lines.append(f"- status: {snapshot.member_status}")
    lines.append("")

    lines.append("## Projects")
    if not snapshot.projects:
        lines.append("- _none_")
    else:
        for p in snapshot.projects:
            lines.append(
                f"- **{p.name}** — sensitivity: {p.sensitivity}; "
                f"lead: {p.lead}; "
                f"choreography: {p.choreography or '—'}"
            )
    lines.append("")

    lines.append("## SEAs")
    lines.append("### Incoming")
    if not snapshot.seas_incoming:
        lines.append("- _none_")
    else:
        for s in snapshot.seas_incoming:
            lines.append(f"- #{s.id} ({s.state}) — from {s.from_handle}: {s.description}")
    lines.append("")
    lines.append("### Outgoing")
    if not snapshot.seas_outgoing:
        lines.append("- _none_")
    else:
        for s in snapshot.seas_outgoing:
            lines.append(f"- #{s.id} ({s.state}) — to {s.to_handle}: {s.description}")
    lines.append("")

    lines.append("## Outstanding analysis")
    lines.append("_What does each result *mean*?_")
    if not snapshot.outstanding:
        lines.append("- _none_")
    else:
        for item in snapshot.outstanding:
            badge = {"red": "🔴", "yellow": "🟡", "ok": "⚪"}.get(item.severity, "⚪")
            age = f"{item.age_days}d" if item.age_days is not None else "—"
            lines.append(
                f"- {badge} {item.scope} {item.target} ({item.project}) — "
                f"state: {item.state}; age since complete: {age}"
            )
    lines.append("")

    lines.append("## Security and compliance")
    if not snapshot.compliance:
        lines.append("- _no per-project compliance rows; not in any project_")
    for row in snapshot.compliance:
        lines.append(f"### {row.project} ({row.sensitivity})")
        for cert in row.member_certs:
            badge = {"ok": "✓", "expiring": "🟡", "expired": "🔴", "missing": "🔴"}[cert.status]
            extra = f" (expires {cert.expires})" if cert.expires else ""
            lines.append(f"- {badge} {cert.name}{extra}")
        for note in row.notes:
            lines.append(f"  - ⚠️  {note}")
        lines.append("")

    lines.append("## Inventory (group)")
    inv = snapshot.inventory_summary
    if inv.get("low"):
        lines.append("### Low / out")
        for r in inv["low"]:
            lines.append(f"- {r['name']} ({r['status']})")
    if inv.get("expired"):
        lines.append("### Expired")
        for r in inv["expired"]:
            lines.append(f"- {r['name']} (expiry {r.get('expiry')})")
    if inv.get("expiring"):
        lines.append("### Expiring within 30 days")
        for r in inv["expiring"]:
            lines.append(f"- {r['name']} (expiry {r.get('expiry')})")
    if not any(inv.values()):
        lines.append("- _all in stock; nothing expiring soon_")
    lines.append("")

    if snapshot.is_pi:
        lines.append("## PI view: clinical compliance grid")
        grid = snapshot.pi_view.get("clinical_compliance", [])
        if not grid:
            lines.append("- _no clinical projects_")
        else:
            lines.append("| project | member | TCPS_2 | expiry |")
            lines.append("|---|---|---|---|")
            for row in grid:
                badge = {
                    "ok": "✓",
                    "expiring": "🟡",
                    "expired": "🔴",
                    "missing": "🔴",
                }[row["tcps_status"]]
                lines.append(
                    f"| {row['project']} | {row['member']} | {badge} {row['tcps_status']} "
                    f"| {row.get('tcps_expires') or '—'} |"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_member_dashboard(handle: str, *, today: _dt.date | None = None) -> Path:
    """Build the snapshot for ``handle`` and write to lab-mgmt/dashboards."""
    snapshot = build_snapshot(handle, today=today)
    target = lab_mgmt_repo_root() / "dashboards" / f"{snapshot.member}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(snapshot), encoding="utf-8")
    return target


def render_outstanding(snapshot: DashboardSnapshot) -> str:
    """Render only the Outstanding analysis section as a terminal-friendly summary."""
    lines = ["Outstanding analysis"]
    if not snapshot.outstanding:
        lines.append("  (none)")
    else:
        for item in snapshot.outstanding:
            badge = {"red": "RED", "yellow": "YEL", "ok": "OK "}.get(item.severity, "OK ")
            age = f"{item.age_days}d" if item.age_days is not None else "—"
            lines.append(
                f"  [{badge}] {item.scope} {item.target} ({item.project}) "
                f"state={item.state} age={age}"
            )
    return "\n".join(lines) + "\n"
