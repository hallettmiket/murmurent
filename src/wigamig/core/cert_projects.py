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
    """One cert-scoped project in a lab's registry — the authoritative project
    record. A project's identity is its certified membership; a ``code_repo``
    (a ``~/repos/<name>`` CHARTER repo) is an *optional* attribute, not what
    defines the project."""

    name: str
    lab: str
    status: str = "active"                 # "active" | "archived"
    created: str = ""
    lead: str = ""                         # project lead handle (defaults to lab PI)
    sensitivity: str = "standard"          # standard | restricted | clinical
    choreography: str | None = None
    code_repo: str = ""                    # optional: linked ~/repos/<name> code repo
    # Where the code repo's working tree lives — so `wigamig reconcile` can find
    # orphaned/unreachable clones from the cert-project registry (this metadata
    # used to live only in the CHARTER-mirror registry). host="local" means this
    # machine at ``code_repo``; a remote host name means the tree is at
    # ``remote_path`` on that host and ``code_repo`` is a local pointer.
    host: str = "local"
    remote_path: str = ""
    slack_channel_id: str = ""             # provisioned in Phase C
    github_repo: str = ""                  # provisioned in Phase C, e.g. "org/name"
    members: tuple[str, ...] = ()          # certified member handles (@-prefixed)
    # One entry per issued project card: {handle, fingerprint, card_id}.
    certs: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "lab": self.lab, "status": self.status,
                "created": self.created, "lead": self.lead,
                "sensitivity": self.sensitivity, "choreography": self.choreography,
                "code_repo": self.code_repo, "host": self.host,
                "remote_path": self.remote_path,
                "slack_channel_id": self.slack_channel_id,
                "github_repo": self.github_repo, "members": list(self.members),
                "certs": [dict(c) for c in self.certs]}


class CertProjectError(RuntimeError):
    """A cert-project registry operation could not be completed (e.g. the
    lab-mgmt repo is missing or its path is a dangling symlink)."""


def registry_dir(env: dict | None = None) -> Path:
    return lab_mgmt_repo_root(env) / REGISTRY_DIR


def _require_writable_root(env: dict | None = None) -> Path:
    """Resolve the lab-mgmt repo root and reject the states that would otherwise
    surface as an opaque ``FileExistsError`` deep in ``mkdir`` — a dangling
    ``~/repos/lab_mgmt`` symlink (from an older layout) or a path occupied by a
    non-directory. A plain-missing root is fine: ``mkdir(parents=True)`` creates
    it (matching pi-init / the create flow)."""
    root = lab_mgmt_repo_root(env)
    # ``exists()`` follows symlinks, so a dangling link reads as missing.
    if root.is_symlink() and not root.exists():
        raise CertProjectError(
            f"lab-mgmt path {root} is a dangling symlink (points to a missing "
            f"target). Fix or remove it, then run `wigamig pi-init <lab>`.")
    if root.exists() and not root.is_dir():
        raise CertProjectError(f"lab-mgmt path {root} is not a directory.")
    return root


def project_path(name: str, env: dict | None = None) -> Path:
    return registry_dir(env) / f"{_safe(name)}.md"


def _parse(path: Path) -> CertProject:
    meta = parse_file(path).meta or {}
    members = tuple(str(m) for m in (meta.get("members") or []))
    certs = tuple(dict(c) for c in (meta.get("certs") or []) if isinstance(c, dict))
    chor = meta.get("choreography")
    return CertProject(
        name=str(meta.get("project") or path.stem),
        lab=str(meta.get("lab") or ""),
        status=str(meta.get("status") or "active").strip().lower() or "active",
        created=str(meta.get("created") or ""),
        lead=str(meta.get("lead") or ""),
        sensitivity=str(meta.get("sensitivity") or "standard").strip().lower() or "standard",
        choreography=str(chor) if chor else None,
        code_repo=str(meta.get("code_repo") or ""),
        host=str(meta.get("host") or "local") or "local",
        remote_path=str(meta.get("remote_path") or ""),
        slack_channel_id=str(meta.get("slack_channel_id") or ""),
        github_repo=str(meta.get("github_repo") or ""),
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
            "created": p.created, "lead": p.lead, "sensitivity": p.sensitivity}
    if p.choreography:
        meta["choreography"] = p.choreography
    if p.code_repo:
        meta["code_repo"] = p.code_repo
    if p.host and p.host != "local":
        meta["host"] = p.host
    if p.remote_path:
        meta["remote_path"] = p.remote_path
    if p.slack_channel_id:
        meta["slack_channel_id"] = p.slack_channel_id
    if p.github_repo:
        meta["github_repo"] = p.github_repo
    meta["members"] = list(p.members)
    meta["certs"] = [dict(c) for c in p.certs]
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return (f"---\n{front}\n---\n\n# {p.name}\n\n"
            "Cert-scoped project (Slack↔CC Phase B). Members are recorded here as "
            "their project cards are issued; the Slack channel + GitHub repo are "
            "provisioned in Phase C.\n")


def _write(p: CertProject, env: dict | None = None) -> Path:
    _require_writable_root(env)
    path = project_path(p.name, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(p), encoding="utf-8")
    return path


def upsert(name: str, *, lab: str, member: str | None = None,
           cert: dict | None = None, status: str | None = None,
           lead: str | None = None, sensitivity: str | None = None,
           choreography: str | None = None, code_repo: str | None = None,
           host: str | None = None, remote_path: str | None = None,
           slack_channel_id: str | None = None, github_repo: str | None = None,
           today: str | None = None, env: dict | None = None) -> CertProject:
    """Create or update a cert project. Optionally add a certified ``member``
    (with their ``cert`` = {handle, fingerprint, card_id}) and/or set project
    metadata. Any metadata argument left ``None`` keeps its current value, so a
    metadata-free membership upsert (from ``issue_project_card``) never clobbers a
    project's sensitivity/lead/etc. Idempotent: a member already present is
    de-duplicated and their cert entry replaced."""
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
    _keep = lambda new, old: old if new is None else new  # noqa: E731
    updated = CertProject(
        name=cur.name, lab=cur.lab or str(lab),
        status=(status or cur.status), created=cur.created or today,
        lead=_keep(lead, cur.lead),
        sensitivity=(str(sensitivity).strip().lower() if sensitivity else cur.sensitivity),
        choreography=_keep(choreography, cur.choreography),
        code_repo=_keep(code_repo, cur.code_repo),
        host=_keep(host, cur.host), remote_path=_keep(remote_path, cur.remote_path),
        slack_channel_id=_keep(slack_channel_id, cur.slack_channel_id),
        github_repo=_keep(github_repo, cur.github_repo),
        members=tuple(members), certs=tuple(certs))
    _write(updated, env)
    return updated


def register_from_summary(summary, *, code_repo: str = "", host: str = "local",
                          remote_path: str = "", env: dict | None = None,
                          today: str | None = None) -> str:
    """Upsert a cert-project from a CHARTER ``ProjectSummary`` (or any object with
    ``name``/``lab``/``status``/``lead``/``sensitivity``/``choreography``/
    ``members``). ``host``/``remote_path`` record where the clone lives (for
    reconcile). Members are recorded UNCERTIFIED (no cert entries) — issuing
    project cards certifies them later. Idempotent. Returns the project name."""
    lab = getattr(summary, "lab", "") or ""
    upsert(summary.name, lab=lab, status=getattr(summary, "status", "active"),
           lead=getattr(summary, "lead", ""),
           sensitivity=getattr(summary, "sensitivity", "standard"),
           choreography=getattr(summary, "choreography", None),
           code_repo=code_repo, host=host, remote_path=remote_path,
           today=today, env=env)
    cur = get(summary.name, env)
    existing = {_norm(m) for m in (cur.members if cur else ())}
    for m in getattr(summary, "members", ()):
        if _norm(m) not in existing:
            upsert(summary.name, lab=lab, member=m, today=today, env=env)
    return summary.name


def backfill_from_charter(*, env: dict | None = None,
                          today: str | None = None) -> list[str]:
    """Populate the cert-project registry from existing CHARTER code-projects, so
    the authoritative store reflects projects that predate the cert model. For
    each ``~/repos/<name>`` with a CHARTER.md, upsert a cert-project carrying its
    name/lab/sensitivity/lead/members and a ``code_repo`` link. Idempotent — a
    project already in the registry keeps its (authoritative) membership; only
    absent metadata is filled. Returns the names touched."""
    from . import projects as _proj                       # lazy: avoid import cycle
    touched: list[str] = []
    for repo in _proj.iter_local_projects(env):
        try:
            s = _proj.load_summary(repo)
        except Exception:  # noqa: BLE001
            continue
        # A remote-pointer project's tree lives on another host; capture that so
        # reconcile can reach it. Local projects → host="local".
        host, remote_path = "local", ""
        pointer = _proj.read_remote_pointer(repo.path)
        if pointer is not None:
            host, remote_path = pointer
        register_from_summary(s, code_repo=str(repo.path), host=host,
                              remote_path=remote_path, env=env, today=today)
        touched.append(s.name)
    return touched


def project_name_for_cwd(start=None, env: dict | None = None) -> str | None:
    """Resolve the project name for the repo containing ``start`` (default cwd) —
    from its CHARTER.md ``project`` field, else the repo dir name. None if not
    inside a project repo."""
    from . import repo as _repo
    pr = _repo.find_project_repo(start)
    if pr is None:
        return None
    try:
        from .frontmatter import parse_file as _pf
        name = (_pf(pr.charter_path).meta or {}).get("project")
        if name:
            return str(name)
    except Exception:  # noqa: BLE001
        pass
    return pr.path.name


def slack_channel_for(name: str, env: dict | None = None) -> str:
    """The provisioned Slack channel id for cert-project ``name``. Empty string if
    the project isn't registered or has no channel yet."""
    cp = get(name, env)
    return cp.slack_channel_id if cp else ""


def set_status(name: str, status: str, *, env: dict | None = None) -> CertProject | None:
    """Flip a cert project's lifecycle status (``active``/``archived``). Missing
    project is a no-op returning None."""
    cur = get(name, env)
    if cur is None:
        return None
    from dataclasses import replace
    updated = replace(cur, status=str(status).strip().lower())
    _write(updated, env)
    return updated


__all__ = ["CertProject", "CertProjectError", "REGISTRY_DIR", "registry_dir",
           "project_path", "get", "iter_projects", "projects_for_member", "upsert",
           "set_status", "register_from_summary", "backfill_from_charter"]
