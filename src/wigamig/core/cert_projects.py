"""
Purpose: the lab-scoped registry of CERT PROJECTS — lightweight cert-scoped
collaborations (a private Slack channel + GitHub repo + certified members) that a
PI runs inside their lab. Distinct from the CHARTER-based code-project model in
``core/projects.py``: a cert project need not have a ``~/repos/<name>`` repo (its
GitHub repo is provisioned later, in the Slack↔CC Phase C), so it can't derive
from a CHARTER. Records live in their OWN directory to avoid colliding with the
CHARTER mirror at ``<lab-mgmt>/projects/``.

Author: Mike Hallett (with Claude Code)
Input: the lab-mgmt repo (``lab_mgmt_repo_root``) — one markdown file per project
       under ``cert_projects/<name>.md`` with YAML frontmatter.
Output: ``CertProject`` records + add/update/list/status helpers.

The identity for a cert project's members is the project-scoped card
(``group == "<lab>/<project>"``) issued by ``issuance.issue_project_card``; that
function upserts this registry as a side effect, so the registry mirrors the
cards actually issued. ``revoke_project`` (PI-only delete) archives the record.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .frontmatter import parse_file
from .repo import lab_mgmt_repo_root

REGISTRY_DIR = "cert_projects"


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(name or ""))


def _norm(handle: str) -> str:
    return str(handle or "").strip().lstrip("@").lower()


@dataclass
class CertProject:
    """One cert-scoped project in a lab's registry."""

    name: str
    lab: str
    status: str = "active"                 # "active" | "archived"
    created: str = ""
    members: tuple[str, ...] = ()          # certified member handles (@-prefixed)
    # One entry per issued project card: {handle, fingerprint, card_id}.
    certs: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "lab": self.lab, "status": self.status,
                "created": self.created, "members": list(self.members),
                "certs": [dict(c) for c in self.certs]}


def registry_dir(env: dict | None = None) -> Path:
    return lab_mgmt_repo_root(env) / REGISTRY_DIR


def project_path(name: str, env: dict | None = None) -> Path:
    return registry_dir(env) / f"{_safe(name)}.md"


def _parse(path: Path) -> CertProject:
    meta = parse_file(path).meta or {}
    members = tuple(str(m) for m in (meta.get("members") or []))
    certs = tuple(dict(c) for c in (meta.get("certs") or []) if isinstance(c, dict))
    return CertProject(
        name=str(meta.get("project") or path.stem),
        lab=str(meta.get("lab") or ""),
        status=str(meta.get("status") or "active").strip().lower() or "active",
        created=str(meta.get("created") or ""),
        members=members,
        certs=certs,
    )


def get(name: str, env: dict | None = None) -> CertProject | None:
    p = project_path(name, env)
    return _parse(p) if p.is_file() else None


def iter_projects(env: dict | None = None) -> list[CertProject]:
    d = registry_dir(env)
    if not d.is_dir():
        return []
    out: list[CertProject] = []
    for f in sorted(d.glob("*.md")):
        try:
            out.append(_parse(f))
        except Exception:  # noqa: BLE001 — a malformed entry shouldn't hide the rest
            continue
    return out


def projects_for_member(handle: str, env: dict | None = None) -> list[CertProject]:
    """Active cert projects whose member list contains ``handle`` (used by the
    dashboard's member lens)."""
    norm = _norm(handle)
    return [p for p in iter_projects(env)
            if p.status == "active" and any(_norm(m) == norm for m in p.members)]


def _render(p: CertProject) -> str:
    meta = {"project": p.name, "lab": p.lab, "status": p.status,
            "created": p.created, "members": list(p.members),
            "certs": [dict(c) for c in p.certs]}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return (f"---\n{front}\n---\n\n# {p.name}\n\n"
            "Cert-scoped project (Slack↔CC Phase B). Members are recorded here as "
            "their project cards are issued; the Slack channel + GitHub repo are "
            "provisioned in Phase C.\n")


def _write(p: CertProject, env: dict | None = None) -> Path:
    path = project_path(p.name, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(p), encoding="utf-8")
    return path


def upsert(name: str, *, lab: str, member: str | None = None,
           cert: dict | None = None, status: str | None = None,
           today: str | None = None, env: dict | None = None) -> CertProject:
    """Create or update a cert project. Optionally add a certified ``member``
    (with their ``cert`` = {handle, fingerprint, card_id}). Idempotent: a member
    already present is de-duplicated and their cert entry replaced. Called by
    ``issuance.issue_project_card`` so the registry mirrors issued cards."""
    today = today or _dt.date.today().isoformat()
    cur = get(name, env)
    if cur is None:
        cur = CertProject(name=str(name), lab=str(lab), status="active", created=today)
    members = list(cur.members)
    certs = [dict(c) for c in cur.certs]
    if member:
        at = member if str(member).startswith("@") else f"@{str(member).lstrip('@')}"
        if not any(_norm(m) == _norm(at) for m in members):
            members.append(at)
        if cert:
            certs = [c for c in certs if _norm(c.get("handle")) != _norm(at)]
            entry = {"handle": at, **{k: cert[k] for k in ("fingerprint", "card_id")
                                      if k in cert}}
            certs.append(entry)
    updated = CertProject(
        name=cur.name, lab=cur.lab or str(lab),
        status=(status or cur.status), created=cur.created or today,
        members=tuple(members), certs=tuple(certs))
    _write(updated, env)
    return updated


def set_status(name: str, status: str, *, env: dict | None = None) -> CertProject | None:
    """Flip a cert project's lifecycle status (``active``/``archived``). Missing
    project is a no-op returning None."""
    cur = get(name, env)
    if cur is None:
        return None
    updated = CertProject(name=cur.name, lab=cur.lab, status=str(status).strip().lower(),
                          created=cur.created, members=cur.members, certs=cur.certs)
    _write(updated, env)
    return updated


__all__ = ["CertProject", "REGISTRY_DIR", "registry_dir", "project_path", "get",
           "iter_projects", "projects_for_member", "upsert", "set_status"]
