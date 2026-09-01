"""
Purpose: Build the ``RegistrarResponse`` payload for the
         ``/api/registrar/dashboard`` endpoint.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-12
Input: A registrar's handle (``@the_pi`` in dev) and the registry at
       ``$MURMURENT_LAB_INFO_ROOT/_registry.yaml`` plus each lab's own
       ``lab.md`` + ``members/*.md`` files.
Output: A :class:`~murmurent.dashboard.contract.RegistrarResponse`.

The registrar reads each lab through a pointer. The lab's own
``lab-mgmt`` repo is the source of truth for its membership and
metadata; this module just follows the pointer and renders the
read-only summary the registrar dashboard cares about.

Hard rule: this module must NEVER reach into a lab's notebooks,
oracles, SEAs, deliberations, or inventory. Visibility into those is
the lab's own dashboard's job — the registrar sees groups as opaque
units.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from ..core import compliance as _compliance
from ..core import registrar as _reg
from ..core.frontmatter import parse_file
from . import contract as C


def _today_block(today_d: _dt.date) -> C.TodayBlock:
    """Wrapper around the lab snapshot's ``_today_block``.

    Imported inline so a unit test can monkeypatch lab-snapshot helpers
    to assert the registrar code path never invokes them — we want a
    test failure if anything in this module starts reaching into
    lab-private data accidentally.
    """
    from . import snapshot as _lab_snap
    return _lab_snap._today_block(today_d)


def _summarise_certs(certs: list) -> str:
    """One-line summary of a member's certification list.

    Phase A keeps this terse: count of present certs vs declared.
    Phase F may expand with expiry colours, but the registrar shouldn't
    duplicate the lab's compliance panel.
    """
    if not certs:
        return "—"
    return f"{len(certs)} on file"


def _load_members_for(lab_mgmt_path: Path) -> list[C.RegistrarMemberRow]:
    """Walk ``<lab_mgmt>/members/*.md`` and render a registrar row each.

    Skips files we can't parse. Returns members sorted alphabetically
    by handle for stable rendering.
    """
    members_dir = lab_mgmt_path / "members"
    if not members_dir.is_dir():
        return []
    rows: list[C.RegistrarMemberRow] = []
    for md in sorted(members_dir.glob("*.md")):
        try:
            meta = parse_file(md).meta or {}
        except Exception:
            continue
        handle = str(meta.get("handle") or f"@{md.stem}")
        certs = meta.get("certifications") or []
        status = str(meta.get("status") or "active")
        if status not in ("active", "inactive"):
            status = "active"
        rows.append(
            C.RegistrarMemberRow(
                handle=handle,
                full_name=str(meta.get("full_name") or ""),
                role=str(meta.get("role") or "member"),
                member_status=status,  # type: ignore[arg-type]
                cert_summary=_summarise_certs(certs if isinstance(certs, list) else []),
            )
        )
    return rows


def _coerce_lab(entry: _reg.LabEntry) -> C.RegistrarLabRow:
    """Follow the registry pointer and render the row.

    A broken pointer (path missing or unreadable lab.md) is surfaced as
    ``unresolved=True`` so the registrar sees the problem instead of
    the whole dashboard 500ing.
    """
    lab_path = Path(entry.lab_mgmt_path).expanduser()
    display_name = entry.name.title() + " Lab"
    members: list[C.RegistrarMemberRow] = []
    unresolved = False
    reason: str | None = None
    if not lab_path.is_dir():
        unresolved = True
        reason = f"lab_mgmt_path does not exist: {lab_path}"
    else:
        lab_md = lab_path / "lab.md"
        if lab_md.is_file():
            try:
                meta = parse_file(lab_md).meta or {}
                display_name = str(meta.get("name") or display_name)
            except Exception as exc:
                unresolved = True
                reason = f"lab.md unparseable: {exc}"
        else:
            unresolved = True
            reason = f"no lab.md at {lab_md}"
        members = _load_members_for(lab_path)

    return C.RegistrarLabRow(
        name=entry.name,
        display_name=display_name,
        pi=entry.pi,
        status=entry.status,  # type: ignore[arg-type]
        created=entry.created,
        lab_mgmt_path=str(lab_path),
        slack_workspace=entry.slack_workspace,
        github_org=entry.github_org,
        oracle_vault=entry.oracle_vault,
        members=members,
        member_count=len(members),
        unresolved=unresolved,
        unresolved_reason=reason,
    )


def _coerce_core(entry: _reg.CoreEntry) -> C.RegistrarCoreRow:
    lab_path = Path(entry.lab_mgmt_path).expanduser()
    display_name = entry.name.title() + " Core"
    members: list[C.RegistrarMemberRow] = []
    unresolved = False
    reason: str | None = None
    if not lab_path.is_dir():
        unresolved = True
        reason = f"core path does not exist: {lab_path}"
    else:
        # Cores write their metadata to ``lab.md`` (shared filename for
        # plumbing reasons) — the frontmatter declares ``core:`` instead
        # of ``lab:``. We honour either short-ID field for parity.
        lab_md = lab_path / "lab.md"
        if lab_md.is_file():
            try:
                meta = parse_file(lab_md).meta or {}
                display_name = str(meta.get("name") or display_name)
            except Exception as exc:
                unresolved = True
                reason = f"core lab.md unparseable: {exc}"
        else:
            unresolved = True
            reason = f"no lab.md at {lab_md}"
        members = _load_members_for(lab_path)

    return C.RegistrarCoreRow(
        name=entry.name,
        display_name=display_name,
        leader=entry.pi,
        status=entry.status,  # type: ignore[arg-type]
        created=entry.created,
        lab_mgmt_path=str(lab_path),
        slack_workspace=entry.slack_workspace,
        github_org=entry.github_org,
        oracle_vault=entry.oracle_vault,
        members=members,
        member_count=len(members),
        unresolved=unresolved,
        unresolved_reason=reason,
    )


def _coerce_collab(entry: _reg.CollaborationEntry) -> C.RegistrarCollaborationRow:
    return C.RegistrarCollaborationRow(
        name=entry.name,
        pis=list(entry.pis),
        groups=list(entry.groups),
        member_subset=dict(entry.member_subset),
        oracle_vault=entry.oracle_vault,
        status=entry.status,  # type: ignore[arg-type]
        created=entry.created,
    )


def _build_cert_panel(reg: _reg.Registry, today_d: _dt.date) -> C.RegistrarCertPanel:
    """Walk every ACTIVE lab + core; render the centre-wide cert table.

    For each group we load that group's own ``compliance.md`` (falling
    back to the global default set when absent) so we honour each lab's
    audience choices. Per-member status is computed by
    ``compliance.compute_member_status`` — the exact same logic the
    lab-internal dashboard uses, just aggregated across every group.
    """
    rows: list[C.RegistrarMemberCertRow] = []
    # Discovered cert specs, deduped by code. First lab that declares
    # a given code wins; later labs that declare the same code with
    # a different cadence/audience are tolerated silently (the value
    # actually applied to each member is computed against THEIR lab's
    # config — only the column header is shared).
    cert_specs_by_code: dict[str, C.TrainingCertSpec] = {}

    # Aggregate counters
    handles_with_issues: set[str] = set()
    handles_total: set[str] = set()
    expired_count = 0
    expiring_count = 0
    missing_count = 0

    def _walk_group(name: str, display: str, kind: str, lab_path: Path) -> None:
        nonlocal expired_count, expiring_count, missing_count
        if not lab_path.is_dir():
            return
        config = _compliance.load_config_at(lab_path / "compliance.md")
        for s in config.required:
            if s.code not in cert_specs_by_code:
                cert_specs_by_code[s.code] = C.TrainingCertSpec(
                    code=s.code, name=s.name, short=s.short,
                    cadence_years=s.cadence_years,
                    audience=s.audience,  # type: ignore[arg-type]
                )
        members_dir = lab_path / "members"
        if not members_dir.is_dir():
            return
        for md in sorted(members_dir.glob("*.md")):
            try:
                meta = parse_file(md).meta or {}
            except Exception:
                continue
            handle = str(meta.get("handle") or f"@{md.stem}")
            full_name = str(meta.get("full_name") or "")
            role = str(meta.get("role") or "member")
            member_status_raw = str(meta.get("status") or "active")
            member_status = member_status_raw if member_status_raw in ("active", "inactive") else "active"
            raw_certs = meta.get("certifications") or []
            if not isinstance(raw_certs, list):
                raw_certs = [raw_certs]
            statuses = _compliance.compute_member_status(
                handle=handle.lstrip("@"),
                member_certs=[str(x) for x in raw_certs],
                config=config,
                today=today_d,
            )
            cells: list[C.RegistrarCertCell] = []
            has_expired = has_expiring = has_missing = False
            for cs in statuses:
                cells.append(
                    C.RegistrarCertCell(
                        code=cs.code,
                        status=cs.status,  # type: ignore[arg-type]
                        expires=cs.expires,
                    )
                )
                if cs.status == "expired":
                    expired_count += 1
                    has_expired = True
                elif cs.status == "expiring":
                    expiring_count += 1
                    has_expiring = True
                elif cs.status == "missing":
                    missing_count += 1
                    has_missing = True
            handle_key = handle.lower().lstrip("@")
            handles_total.add(handle_key)
            if has_expired or has_expiring or has_missing:
                handles_with_issues.add(handle_key)
            rows.append(
                C.RegistrarMemberCertRow(
                    group=name, group_display=display, group_kind=kind,  # type: ignore[arg-type]
                    handle=handle,
                    full_name=full_name, role=role,
                    member_status=member_status,  # type: ignore[arg-type]
                    certs=cells,
                    has_expired=has_expired,
                    has_expiring=has_expiring,
                    has_missing=has_missing,
                )
            )

    for lab in reg.labs:
        if lab.status != "active":
            continue
        _walk_group(lab.name, lab.name.title() + " Lab", "lab", Path(lab.lab_mgmt_path))
    for core in reg.cores:
        if core.status != "active":
            continue
        _walk_group(core.name, core.name.title() + " Core", "core", Path(core.lab_mgmt_path))

    return C.RegistrarCertPanel(
        aggregate=C.RegistrarCertAggregate(
            members_total=len(handles_total),
            members_with_issues=len(handles_with_issues),
            expired_count=expired_count,
            expiring_count=expiring_count,
            missing_count=missing_count,
        ),
        rows=rows,
        cert_specs=list(cert_specs_by_code.values()),
    )


def build_registrar_response(
    handle: str,
    *,
    today: _dt.date | None = None,
) -> C.RegistrarResponse:
    """Assemble the registrar dashboard payload.

    Caller is responsible for the ``is_registrar`` gate — this function
    builds a fresh snapshot from disk and does not enforce permissions.
    """
    today_d = today or _dt.date.today()
    reg = _reg.read_registry()

    lab_rows = [_coerce_lab(l) for l in reg.labs]
    core_rows = [_coerce_core(c) for c in reg.cores]
    collab_rows = [_coerce_collab(x) for x in reg.collaborations]

    # Total unique members across all labs (case-insensitive on handle).
    seen: set[str] = set()
    for row in lab_rows + core_rows:
        for m in row.members:
            seen.add(m.handle.lower().lstrip("@"))

    # Registrar's own contact / location, from <lab_info_root>/registrar.md.
    profile_meta = _reg.read_profile()
    profile = C.RegistrarProfile(
        handle=f"@{handle.lstrip('@')}",
        full_name=str(profile_meta.get("full_name") or ""),
        title=str(profile_meta.get("title") or ""),
        email=profile_meta.get("email") or None,
        orcid=profile_meta.get("orcid") or None,
        website=profile_meta.get("website") or None,
        github=profile_meta.get("github") or None,
        office=profile_meta.get("office") or None,
        address=profile_meta.get("address") or None,
        city=profile_meta.get("city") or None,
        department=profile_meta.get("department") or None,
        institution=profile_meta.get("institution") or None,
    )

    # Item #9: PI-proposed collaboration requests. Surfaced as loose
    # dicts in the registrar payload so the centre's pending queue is
    # visible alongside live collaborations.
    from ..core import collaboration_requests as _creq
    collab_req_rows: list[dict] = []
    for r in _creq.iter_requests():
        collab_req_rows.append({
            "id": r.id,
            "requester": r.requester,
            "proposed_name": r.proposed_name,
            "proposed_groups": list(r.proposed_groups),
            "proposed_pis": list(r.proposed_pis),
            "proposed_member_subset": {k: list(v) for k, v in r.proposed_member_subset.items()},
            "proposed_oracle_vault": r.proposed_oracle_vault,
            "justification": r.justification,
            "state": r.state,
            "created_at": r.created_at,
            "resolved_at": r.resolved_at,
            "resolved_by": r.resolved_by,
            "decline_reason": r.decline_reason,
        })

    return C.RegistrarResponse(
        registrar_handle=f"@{handle.lstrip('@')}",
        today=_today_block(today_d),
        profile=profile,
        labs=lab_rows,
        cores=core_rows,
        collaborations=collab_rows,
        collaboration_requests=collab_req_rows,
        stats=C.RegistrarStats(
            total_labs=sum(1 for l in lab_rows if l.status == "active"),
            total_cores=sum(1 for c in core_rows if c.status == "active"),
            total_collaborations=sum(1 for x in collab_rows if x.status == "active"),
            total_members=len(seen),
        ),
        certs=_build_cert_panel(reg, today_d),
    )
