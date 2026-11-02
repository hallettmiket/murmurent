"""
Purpose: The projects one person is involved with, across every group they
        belong to, for the dashboard and ``murmurent project list``.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-27
Input: The identity card (which groups), each group's records repo
       (``cert_projects/``), and the project cards held on this machine.
Output: :class:`VisibleProject` rows, one per project the person can see.

A person sees a project when it lists them (as member or lead), or when they
hold a project card for it; the PI of a group sees every project of that
group as well (#259). A project hosted in another lab's records, which the
member's machine may not hold, is shown from that lab's records when they
are on this machine, else from the summary the card bundle carries (team,
repositories, channel, as of the day the card was issued); the row says
"hosted by" that lab.
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
    # For a card-sourced project: what the bundle's summary says (#259).
    repos: tuple[dict, ...] = ()
    slack_workspace: str = ""
    slack_channel_id: str = ""
    as_of: str = ""          # the summary's date; '' when read from records


def _declared_lab(root: Path) -> str:
    """The group a records repo declares in ``lab.md`` (``lab:``), or ''."""
    try:
        from .frontmatter import parse_file as _parse_file

        meta = _parse_file(root / "lab.md").meta or {}
    except Exception:  # noqa: BLE001 - an unreadable lab.md means unknown
        return ""
    return str(meta.get("lab") or "").strip()


def _declared_pi(root: Path) -> str:
    """The PI a records repo declares in ``lab.md`` (``pi:``), bare, or ''."""
    try:
        from .frontmatter import parse_file as _parse_file

        meta = _parse_file(root / "lab.md").meta or {}
    except Exception:  # noqa: BLE001
        return ""
    return str(meta.get("pi") or "").strip().lstrip("@").lower()


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


def _card_projects(norm: str) -> list[tuple[str, str, dict]]:
    """``(lab, project, summary)`` for every project card bundle this machine
    holds; ``summary`` is the bundle's ``project_summary`` or ``{}``."""
    try:
        from .issuance import cards_dir

        bundles = sorted(cards_dir().glob("*_project_*.json"))
    except OSError:
        return []
    out: list[tuple[str, str, dict]] = []
    for p in bundles:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload = (b.get("project_card") or {}).get("payload") or {}
        subject = str((payload.get("subject") or {}).get("handle") or "").lstrip("@").lower()
        lab, _, project = str(payload.get("group") or "").partition("/")
        if project and (not subject or subject == norm):
            summary = b.get("project_summary") if isinstance(b.get("project_summary"), dict) else {}
            out.append((lab, project, summary))
    return out


def _host_records(lab: str) -> Path | None:
    """The records repo of ``lab`` on this machine, from the registry, or None."""
    if not lab:
        return None
    try:
        from . import registrar as _reg

        reg = _reg.read_registry()
        entry = next((g for g in [*reg.labs, *reg.cores]
                      if str(g.name).lower() == lab.lower()), None)
    except Exception:  # noqa: BLE001
        return None
    if entry is None or not entry.lab_mgmt_path:
        return None
    root = Path(str(entry.lab_mgmt_path)).expanduser()
    return root if root.is_dir() else None


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
        is_pi = bool(norm) and _declared_pi(root) == norm
        with _repo.use_lab_mgmt_root(root):
            records = _cp.iter_projects()
        for cp in records:
            if cp.name in out:
                continue
            lab = cp.lab or group
            on_it = (any(m.lstrip("@").lower() == norm for m in cp.members)
                     or str(cp.lead or "").lstrip("@").lower() == norm)
            # A member sees the projects they are on; the PI sees every
            # project of their group as well (#259).
            if not (on_it or (is_pi and lab and lab.lower() in mine)):
                continue
            out[cp.name] = VisibleProject(
                name=cp.name, lab=lab, lead=cp.lead, status=cp.status,
                sensitivity=cp.sensitivity, members=tuple(cp.members),
                on_it=on_it, source="records", record=cp)
    for lab, project, summary in _card_projects(norm):
        if project in out:
            continue
        # The host lab's records, when this machine holds them, are fresher
        # than the summary the card carried.
        host = _host_records(lab)
        if host is not None:
            with _repo.use_lab_mgmt_root(host):
                cp = _cp.get(project)
            if cp is not None:
                out[project] = VisibleProject(
                    name=cp.name, lab=cp.lab or lab, lead=cp.lead, status=cp.status,
                    sensitivity=cp.sensitivity, members=tuple(cp.members),
                    on_it=True, source="records", record=cp)
                continue
        members = tuple(str(m) for m in (summary.get("members") or [])) or \
            ((f"@{norm}",) if norm else ())
        out[project] = VisibleProject(
            name=project, lab=str(summary.get("lab") or lab), lead=str(summary.get("lead") or ""),
            status=str(summary.get("status") or "active"),
            sensitivity=str(summary.get("sensitivity") or "standard"),
            members=members, on_it=True, source="card",
            repos=tuple(dict(r) for r in (summary.get("repos") or []) if isinstance(r, dict)),
            slack_workspace=str(summary.get("slack_workspace") or ""),
            slack_channel_id=str(summary.get("slack_channel_id") or ""),
            as_of=str(summary.get("as_of") or ""))
    return list(out.values())


__all__ = ["VisibleProject", "visible_projects", "viewer_group_paths"]
