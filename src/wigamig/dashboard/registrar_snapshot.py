"""
Purpose: Build the ``RegistrarResponse`` payload for the
         ``/api/registrar/dashboard`` endpoint.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-12
Input: A registrar's handle (``@mhallet`` in dev) and the registry at
       ``$WIGAMIG_LAB_INFO_ROOT/_registry.yaml`` plus each lab's own
       ``lab.md`` + ``members/*.md`` files.
Output: A :class:`~wigamig.dashboard.contract.RegistrarResponse`.

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
    members: list[C.RegistrarMemberRow] = []
    unresolved = not lab_path.is_dir()
    reason = f"core path does not exist: {lab_path}" if unresolved else None
    if not unresolved:
        members = _load_members_for(lab_path)
    return C.RegistrarCoreRow(
        name=entry.name,
        display_name=entry.name.title() + " Core",
        pi=entry.pi,
        status=entry.status,  # type: ignore[arg-type]
        created=entry.created,
        lab_mgmt_path=str(lab_path),
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

    return C.RegistrarResponse(
        registrar_handle=f"@{handle.lstrip('@')}",
        today=_today_block(today_d),
        labs=lab_rows,
        cores=core_rows,
        collaborations=collab_rows,
        stats=C.RegistrarStats(
            total_labs=sum(1 for l in lab_rows if l.status == "active"),
            total_cores=sum(1 for c in core_rows if c.status == "active"),
            total_collaborations=sum(1 for x in collab_rows if x.status == "active"),
            total_members=len(seen),
        ),
    )
