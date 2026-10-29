"""
Purpose: The projects one person is involved with, across every group they
        belong to, for the dashboard and ``murmurent project list``.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-27
Input: The identity card (which groups), each group's records repo
       (``cert_projects/``), and the project cards held on this machine.
Output: :class:`VisibleProject` rows, one per project the person can see.

A person sees a project when it is one of their own group's projects (it is
recorded in that group's records repo), or when it lists them, or when they
hold a project card for it. The last case is what shows a member of a
cross-lab project the project hosted in another lab's records, which their
machine does not hold: the card alone names it, so the row says "hosted by"
that lab and carries no repos or team list.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import repo as _repo
from .cert_projects import CertProject


@dataclass(frozen=True)
class VisibleProject:
    """One project the viewer can see, and why."""

    name: str
    lab: str                 # the group whose project it is
    lead: str = ""
    status: str = "active"
    sensitivity: str = "standard"
    members: tuple[str, ...] = ()
    on_it: bool = False      # the viewer is listed, or holds a project card
    source: str = "records"  # "records" (a group's cert_projects/) | "card"
    record: CertProject | None = field(default=None, compare=False)


def _declared_lab(root: Path) -> str:
    """The group a records repo declares in ``lab.md`` (``lab:``), or ''."""
    try:
        from .frontmatter import parse_file as _parse_file

        meta = _parse_file(root / "lab.md").meta or {}
    except Exception:  # noqa: BLE001 - an unreadable lab.md means unknown
        return ""
    return str(meta.get("lab") or "").strip()


def viewer_group_paths(handle: str, env: dict | None = None) -> list[tuple[str, Path]]:
    """``(group, records repo path)`` for every group ``handle`` belongs to.

    The machine owner's identity card lists their groups; each one's records
    repo is at its canonical path. Anyone else is looked up in the registry
    (one group). An explicit ``MURMURENT_LAB_MGMT_REPO``, or a machine with
    neither card nor registry, gives the single repo the resolver returns.
    """
    norm = (handle or "").strip().lstrip("@").lower()
    env = os.environ if env is None else env
    explicit = env.get("MURMURENT_LAB_MGMT_REPO")
    if not explicit:
        try:
            from . import identity_card as _ic

            card = _ic.local_card()
        except Exception:  # noqa: BLE001
            card = None
        if card and str(card.get("netname") or "").lower() == norm:
            groups = _repo.owner_groups()
            if groups:
                return [(g.group, g.path) for g in groups]
        try:
            from . import registrar as _reg

            match = _reg.lab_mgmt_path_for_handle(norm)
        except Exception:  # noqa: BLE001
            match = None
        if match:
            return [(match[0], Path(match[1]).expanduser())]
    root = _repo.lab_mgmt_repo_root()
    return [(_declared_lab(root), root)]


def _card_projects(norm: str) -> list[tuple[str, str]]:
    """``(lab, project)`` for every project card bundle this machine holds."""
    try:
        from .issuance import cards_dir

        bundles = sorted(cards_dir().glob("*_project_*.json"))
    except OSError:
        return []
    out: list[tuple[str, str]] = []
    for p in bundles:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload = (b.get("project_card") or {}).get("payload") or {}
        subject = str((payload.get("subject") or {}).get("handle") or "").lstrip("@").lower()
        lab, _, project = str(payload.get("group") or "").partition("/")
        if project and (not subject or subject == norm):
            out.append((lab, project))
    return out


def visible_projects(handle: str, env: dict | None = None) -> list[VisibleProject]:
    """Every project ``handle`` can see, deduplicated by name, records first."""
    norm = (handle or "").strip().lstrip("@").lower()
    groups = viewer_group_paths(handle, env)
    mine = {g.lower() for g, _p in groups if g}
    out: dict[str, VisibleProject] = {}
    from . import cert_projects as _cp

    for group, root in groups:
        if not root.is_dir():
            continue
        with _repo.use_lab_mgmt_root(root):
            records = _cp.iter_projects()
        for cp in records:
            if cp.name in out:
                continue
            lab = cp.lab or group
            on_it = any(m.lstrip("@").lower() == norm for m in cp.members)
            if not (on_it or (lab and lab.lower() in mine)):
                continue
            out[cp.name] = VisibleProject(
                name=cp.name, lab=lab, lead=cp.lead, status=cp.status,
                sensitivity=cp.sensitivity, members=tuple(cp.members),
                on_it=on_it, source="records", record=cp)
    for lab, project in _card_projects(norm):
        if project not in out:
            out[project] = VisibleProject(
                name=project, lab=lab, members=(f"@{norm}",) if norm else (),
                on_it=True, source="card")
    return list(out.values())


__all__ = ["VisibleProject", "visible_projects", "viewer_group_paths"]
