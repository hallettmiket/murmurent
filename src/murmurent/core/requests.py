"""
Purpose: Project-join request registry stored in
         ``<lab-mgmt>/requests/<id>.md``. Anyone can file a request to
         join an existing project; the PI approves or declines via the
         dashboard's Requests panel (or the matching CLI commands).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Markdown files with frontmatter, one per request.
Output: ``JoinRequest`` dataclass; lifecycle helpers that mutate it +
        persist back to disk.

Layout::

    <lab-mgmt>/requests/
    ├── 1.md          ← @bob asks to join dcis_sc_tutorial
    ├── 2.md          ← @cassie asks to join bbb_drug_screen
    └── ...

Each file's frontmatter declares: ``id, requester, project, kind,
justification, state, created_at, resolved_at, resolved_by,
decline_reason``. ``state`` is one of ``pending | approved | declined``.

Lifecycle:

  pending  --(approve)-->  approved      (membership added on the way)
  pending  --(decline)-->  declined      (with a reason)

Approval applies the side effect of adding the requester to the
project's ``CHARTER.md`` ``members:`` list and the ``MEMBERS`` file.
Decline only updates the request state.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from .frontmatter import dump_document, parse_file
from .projects import find_project
from .repo import MEMBERS_FILENAME, lab_mgmt_repo_root

REQUESTS_SUBDIR = "requests"
REQUEST_ID_RE = re.compile(r"^(?P<id>\d+)\.md$")
VALID_KINDS: tuple[str, ...] = ("project-join", "project-create")
VALID_STATES: tuple[str, ...] = ("pending", "approved", "declined")
TERMINAL_STATES = frozenset({"approved", "declined"})


class RequestError(ValueError):
    """Base for request lifecycle / state errors."""


class RequestStateError(RequestError):
    """Tried to transition a request that's already terminal."""


class RequestNotFound(RequestError):
    """No matching request file on disk."""


@dataclass
class JoinRequest:
    """One request (project-join or project-create) loaded from disk.

    For ``kind == "project-create"`` the ``project`` field is the
    *proposed* project name (which doesn't exist yet); the additional
    ``proposed_members``, ``proposed_sensitivity``, and
    ``proposed_lead`` fields capture the rest of the spec.
    """

    id: int
    requester: str
    project: str
    kind: str = "project-join"
    justification: str = ""
    state: str = "pending"
    created_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    decline_reason: str | None = None
    body: str = ""
    path: Path | None = None
    # project-create extras (ignored for project-join):
    proposed_members: list[str] | None = None
    proposed_sensitivity: str | None = None
    proposed_lead: str | None = None
    # Phase 16: where the project's git origin should live. Default
    # ``"github"`` preserves the pre-Phase-16 behaviour. ``local_repo_root``
    # is consulted only when kind="local".
    repo_kind: str | None = None
    local_repo_root: str | None = None
    # Item 3 (R2/R3): which registered host this project should live on.
    # Default ``"local"`` preserves pre-R2 behaviour; any other value
    # (e.g. ``"biodatsci"``) routes the approval to ``cmd_new_remote``.
    host: str | None = None
    # 2026-05-15: optional override for the Slack channel name. ``None``
    # → murmurent uses the conventional ``proj-<project>``. Persisted so
    # the PI's approve flow knows what to ask Slack to create.
    slack_channel_name: str | None = None
    # (5) 2026-07: a project is a set of repos + a set of machines. ``machines``
    # is the full host set the project lives on; ``host`` above stays the
    # primary scaffold target (= machines[0]) for the pre-(5) approval path.
    # ``attach_repos`` names existing inventory repos to fold into the project
    # alongside the freshly-scaffolded primary repo (code + manuscript + …).
    machines: list[str] | None = None
    attach_repos: list[str] | None = None
    # (10) inter-group projects: the agreed shared Slack workspace (a group id
    # whose bot token hosts the project channel + cert DMs). Required at filing
    # time when the proposed members span groups; re-validated at approve.
    slack_workspace: str | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "id": self.id,
            "requester": self.requester,
            "project": self.project,
            "kind": self.kind,
            "justification": self.justification,
            "state": self.state,
        }
        for key, value in (
            ("created_at", self.created_at),
            ("resolved_at", self.resolved_at),
            ("resolved_by", self.resolved_by),
            ("decline_reason", self.decline_reason),
            ("proposed_members", self.proposed_members),
            ("proposed_sensitivity", self.proposed_sensitivity),
            ("proposed_lead", self.proposed_lead),
            ("repo_kind", self.repo_kind),
            ("local_repo_root", self.local_repo_root),
            ("host", self.host),
            ("slack_channel_name", self.slack_channel_name),
            ("machines", self.machines),
            ("attach_repos", self.attach_repos),
            ("slack_workspace", self.slack_workspace),
        ):
            if value is not None:
                meta[key] = value
        return meta


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def requests_dir() -> Path:
    """Resolve ``<lab-mgmt>/requests/``."""
    return lab_mgmt_repo_root() / REQUESTS_SUBDIR


def request_path(req_id: int) -> Path:
    """Resolve ``<lab-mgmt>/requests/<id>.md``."""
    return requests_dir() / f"{req_id}.md"


def parse_request(path: Path) -> JoinRequest:
    """Parse one request markdown file."""
    parsed = parse_file(path)
    meta = parsed.meta
    proposed_members = meta.get("proposed_members")
    if proposed_members is not None and not isinstance(proposed_members, list):
        proposed_members = list(proposed_members)

    def _opt_list(value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        s = str(value).strip()
        return [s] if s else None

    return JoinRequest(
        id=int(meta["id"]),
        requester=str(meta["requester"]),
        project=str(meta["project"]),
        kind=str(meta.get("kind", "project-join")),
        justification=str(meta.get("justification", "")),
        state=str(meta.get("state", "pending")),
        created_at=_opt_str(meta.get("created_at")),
        resolved_at=_opt_str(meta.get("resolved_at")),
        resolved_by=_opt_str(meta.get("resolved_by")),
        decline_reason=_opt_str(meta.get("decline_reason")),
        proposed_members=proposed_members,
        proposed_sensitivity=_opt_str(meta.get("proposed_sensitivity")),
        proposed_lead=_opt_str(meta.get("proposed_lead")),
        repo_kind=_opt_str(meta.get("repo_kind")),
        local_repo_root=_opt_str(meta.get("local_repo_root")),
        host=_opt_str(meta.get("host")),
        slack_channel_name=_opt_str(meta.get("slack_channel_name")),
        machines=_opt_list(meta.get("machines")),
        attach_repos=_opt_list(meta.get("attach_repos")),
        slack_workspace=_opt_str(meta.get("slack_workspace")),
        body=parsed.body,
        path=path,
    )


def iter_requests() -> list[JoinRequest]:
    """Return every request on disk, ordered by integer id."""
    out: list[JoinRequest] = []
    rdir = requests_dir()
    if not rdir.is_dir():
        return out
    for child in rdir.iterdir():
        m = REQUEST_ID_RE.match(child.name)
        if not m:
            continue
        try:
            out.append(parse_request(child))
        except Exception:
            continue
    out.sort(key=lambda r: r.id)
    return out


def next_request_id() -> int:
    used = [r.id for r in iter_requests()]
    return (max(used) + 1) if used else 1


def render_request(req: JoinRequest) -> str:
    """Render a request to its on-disk markdown form."""
    body = req.body or _default_body(req)
    return dump_document(req.to_meta(), body)


def write_request(req: JoinRequest) -> Path:
    """Persist ``req`` to ``<lab-mgmt>/requests/<id>.md``."""
    rdir = requests_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    path = request_path(req.id)
    path.write_text(render_request(req), encoding="utf-8")
    req.path = path
    return path


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def file_request(
    *,
    requester: str,
    project: str,
    justification: str = "",
    today: _dt.date | None = None,
) -> JoinRequest:
    """File a new project-join request and persist it.

    Refuses if the requester is already a member of the project (so the
    PI's queue doesn't fill with duplicates).
    """
    today = today or _dt.date.today()
    repo = find_project(project)
    if repo is None:
        raise RequestError(f"project not found: {project}")
    norm = requester.lstrip("@").lower()
    if repo.members_path and repo.members_path.is_file():
        existing = {
            line.strip().lstrip("@").lower()
            for line in repo.members_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        if norm in existing:
            raise RequestError(f"@{norm} is already a member of {project}")
    # Also refuse if there's already a pending request from the same person.
    for existing_req in iter_requests():
        if (
            existing_req.state == "pending"
            and existing_req.project == project
            and existing_req.requester.lstrip("@").lower() == norm
        ):
            raise RequestError(
                f"@{norm} already has a pending join request for {project} "
                f"(#{existing_req.id})"
            )

    req = JoinRequest(
        id=next_request_id(),
        requester=_at(requester),
        project=project,
        kind="project-join",
        justification=justification,
        state="pending",
        created_at=today.isoformat(),
    )
    write_request(req)
    return req


def approve(
    req: JoinRequest,
    *,
    approver: str,
    today: _dt.date | None = None,
) -> JoinRequest:
    """Mark the request approved and apply the appropriate side effect.

    For ``project-join``: adds the requester to the existing project's
    MEMBERS file + CHARTER frontmatter.

    For ``project-create``: scaffolds a brand-new project repo with the
    proposed members, sensitivity, and lead. The requester is added to
    members automatically (otherwise they couldn't see what they
    proposed).
    """
    if req.state in TERMINAL_STATES:
        raise RequestStateError(
            f"request #{req.id} is already {req.state}; cannot approve."
        )
    today = today or _dt.date.today()
    if req.kind == "project-create":
        # Re-run the inter-group workspace gate: rosters may have changed
        # between filing and approval, so approval also fails closed.
        _require_workspace_if_inter_group(
            list(req.proposed_members or []), req.slack_workspace or "")
        _create_project_from_request(req)
    else:
        _add_to_project_members(req.project, req.requester)
    req.state = "approved"
    req.resolved_at = today.isoformat()
    req.resolved_by = _at(approver)
    return req


def file_create_request(
    *,
    requester: str,
    project: str,
    proposed_members: list[str],
    sensitivity: str = "standard",
    proposed_lead: str | None = None,
    justification: str = "",
    today: _dt.date | None = None,
    repo_kind: str = "github",
    local_repo_root: str | None = None,
    host: str = "local",
    slack_channel_name: str | None = None,
    machines: list[str] | None = None,
    attach_repos: list[str] | None = None,
    slack_workspace: str | None = None,
) -> JoinRequest:
    """File a ``project-create`` request.

    Refuses if a project with that name already exists locally.

    A project is a set of repos + a set of machines. ``machines`` is the
    full host set; ``host`` (the primary scaffold target) is derived from
    ``machines[0]`` when a set is given. ``attach_repos`` names existing
    inventory repos to fold in alongside the freshly-scaffolded repo.

    ``slack_workspace`` names the group whose Slack workspace hosts the
    project. REQUIRED when the proposed members span multiple groups
    (inter-group project) — the groups must decide on a shared workspace
    BEFORE the project can exist; filing fails otherwise.
    """
    today = today or _dt.date.today()
    if find_project(project) is not None:
        raise RequestError(f"project already exists: {project}")
    if not project.replace("_", "").isalnum():
        raise RequestError(
            f"project name must be alphanumeric + underscore; got {project!r}"
        )
    norm_members = [_at(m) for m in proposed_members if m.strip()]
    if _at(requester) not in norm_members:
        norm_members.insert(0, _at(requester))
    if not norm_members:
        raise RequestError("project-create needs at least one member")
    norm_machines = [m.strip() for m in (machines or []) if m and m.strip()]
    if norm_machines:
        # The primary scaffold target is the first machine in the set; the
        # rest are recorded so the approval flow can extend the project onto
        # them (project = set of machines).
        host = norm_machines[0]
    norm_attach = [r.strip() for r in (attach_repos or []) if r and r.strip()]
    norm_ws = (slack_workspace or "").strip()
    _require_workspace_if_inter_group(norm_members, norm_ws)
    # No duplicate-pending check here — multiple people might propose related
    # projects and the PI sorts it out.

    req = JoinRequest(
        id=next_request_id(),
        requester=_at(requester),
        project=project,
        kind="project-create",
        justification=justification,
        state="pending",
        created_at=today.isoformat(),
        proposed_members=norm_members,
        proposed_sensitivity=sensitivity,
        proposed_lead=_at(proposed_lead) if proposed_lead else _at(requester),
        repo_kind=repo_kind or "github",
        local_repo_root=local_repo_root,
        host=(host or "local"),
        slack_channel_name=(slack_channel_name.strip() if isinstance(slack_channel_name, str) and slack_channel_name.strip() else None),
        machines=norm_machines or None,
        attach_repos=norm_attach or None,
        slack_workspace=norm_ws or None,
    )
    write_request(req)
    return req


def _require_workspace_if_inter_group(members: list[str], workspace: str) -> None:
    """Hard gate for inter-group projects: members spanning multiple groups
    MUST name an agreed shared Slack workspace (with a resolvable bot token)
    or the project definition halts. Single-group projects pass untouched."""
    try:
        from . import cert_provision as _cprov
        inter = _cprov.is_inter_group(members)
    except Exception:  # noqa: BLE001 — no roster ⇒ can't classify ⇒ don't block
        return
    if not inter:
        return
    if not workspace:
        raise RequestError(
            "project members span multiple groups — the groups must decide on "
            "a shared Slack workspace before an inter-group project can be "
            "created. Pick one (certificates + the project channel go through "
            "it) and make sure its bot token exists at "
            "~/.config/murmurent/groups/<workspace>/slack-token.")
    try:
        from . import group_reconcile as _gr
        token = _gr.resolve_group_slack_token(workspace) or ""
    except Exception:  # noqa: BLE001
        token = ""
    if not token:
        raise RequestError(
            f"no Slack bot token for shared workspace '{workspace}' — expected "
            f"$MURMURENT_GROUP_SLACK_TOKEN or "
            f"~/.config/murmurent/groups/{workspace}/slack-token. Run "
            f"`murmurent group-slack-setup {workspace}` first.")


def _create_project_from_request(req: JoinRequest) -> None:
    """Run the actual registration for an approved project-create request."""
    if req.kind != "project-create":
        return
    # A project is a set of EXISTING repos + machines + members. When the
    # request names its repo set (the dashboard flow), no new repo is
    # scaffolded — the project is registered over the clones the user
    # already has (folders come from the machine's Repo location dirs).
    if req.attach_repos:
        _register_project_from_repos(req)
        _stamp_slack_workspace(req)
        return
    members_csv = ",".join(req.proposed_members or [])
    sensitivity = req.proposed_sensitivity or "standard"
    lead = req.proposed_lead or req.requester
    description = req.justification or f"Proposed by {req.requester}."
    # Legacy/CLI path (no repo set named): reuse the CLI command's logic —
    # it scaffolds a fresh repo with charter, MEMBERS file, lab-VM dirs,
    # and the lab-mgmt registry entry.
    from ..commands import project_cmd as _project_cmd
    host = (req.host or "local").strip() or "local"
    if host != "local":
        # Item 3 (R3): remote install. The dispatcher SSHes the host,
        # scaffolds there, and leaves a local pointer dir + lab-mgmt entry.
        _project_cmd.cmd_new_remote(
            req.project,
            host_name=host,
            members_csv=members_csv,
            description=description,
            sensitivity=sensitivity,
            lead=lead,
            skip_github=True,
        )
        _stamp_slack_workspace(req)
        return
    _project_cmd.cmd_new(
        req.project,
        charter_path=None,
        members_csv=members_csv,
        description=description,
        sensitivity=sensitivity,
        choreography=None,
        reb_number=None,
        reb_expires=None,
        data_residency=None,
        lead=lead,
        skip_github=True,  # PI / dashboard does the push after approval
        repo_kind=req.repo_kind or "github",
        local_repo_root=req.local_repo_root,
    )
    _stamp_slack_workspace(req)


def _repo_clone_location(name: str, preferred_host: str) -> tuple[str, str]:
    """(host, path) of an existing clone of ``name``, from the cached repo
    inventory — preferring ``preferred_host``, then ``local``. Falls back to
    the conventional ``~/repos/<name>`` on the preferred host when the cache
    has no answer (fresh install, stale cache)."""
    try:
        from . import repo_inventory as _inv
        cached = _inv.latest_report_path()
        if cached is not None:
            report = _inv.load_report(cached) or {}
            for row in report.get("rows") or []:
                if str(row.get("name") or "") != name:
                    continue
                clones = row.get("clones") or []
                for want in (preferred_host, "local"):
                    for c in clones:
                        if str(c.get("host") or "") == want and c.get("path"):
                            return want, str(c["path"])
                if clones and clones[0].get("path"):
                    return (str(clones[0].get("host") or "local"),
                            str(clones[0]["path"]))
    except Exception:  # noqa: BLE001 — cache is an optimisation, never a gate
        pass
    return preferred_host or "local", str(Path.home() / "repos" / name)


def _register_project_from_repos(req: JoinRequest) -> None:
    """Register an approved project over its EXISTING repos (no scaffolding).

    Writes the authoritative cert-project record: metadata + the repo set
    (each repo resolved to a clone the requester already has, via the repo
    inventory) + the member list (uncertified — project cards certify them
    at the next step of the approve flow)."""
    from . import cert_projects as _cp
    try:
        from .lab import load_lab_config
        lab = load_lab_config().lab or ""
    except Exception:  # noqa: BLE001
        lab = ""
    lead = req.proposed_lead or req.requester
    _cp.upsert(req.project, lab=lab, lead=_at(lead),
               sensitivity=req.proposed_sensitivity or "standard")
    preferred = (req.host or "local").strip() or "local"
    for rname in req.attach_repos or []:
        host, path = _repo_clone_location(rname, preferred)
        # Role heuristic: manuscript repos are usually named so; everything
        # else defaults to code. Editable later from the project's repo list.
        role = "manuscript" if "manuscript" in rname.lower() else "code"
        _cp.add_repo(req.project, repo_name=rname, role=role,
                     host=host, path=path,
                     overleaf=(role == "manuscript"))
    for m in req.proposed_members or []:
        _cp.upsert(req.project, lab=lab, member=m)


def _stamp_slack_workspace(req: JoinRequest) -> None:
    """Record the agreed shared workspace on the cert project (best-effort —
    the scaffold registered the project; this annotates where its Slack
    lives so provisioning + cert DMs use the right token)."""
    if not req.slack_workspace:
        return
    try:
        from . import cert_projects as _cp
        cur = _cp.get(req.project)
        if cur is not None:
            _cp.upsert(req.project, lab=cur.lab,
                       slack_workspace=req.slack_workspace)
    except Exception:  # noqa: BLE001
        pass


def decline(
    req: JoinRequest,
    *,
    decliner: str,
    reason: str,
    today: _dt.date | None = None,
) -> JoinRequest:
    """Mark the request declined with a reason."""
    if req.state in TERMINAL_STATES:
        raise RequestStateError(
            f"request #{req.id} is already {req.state}; cannot decline."
        )
    if not reason:
        raise RequestError("decline requires a reason")
    today = today or _dt.date.today()
    req.state = "declined"
    req.resolved_at = today.isoformat()
    req.resolved_by = _at(decliner)
    req.decline_reason = reason
    return req


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _at(handle: str) -> str:
    h = handle.strip()
    return h if h.startswith("@") else f"@{h}"


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


def _default_body(req: JoinRequest) -> str:
    return (
        f"# Project-join request #{req.id}\n\n"
        f"**{req.requester}** asks to join **{req.project}**.\n\n"
        f"## Justification\n\n{req.justification or '_(none provided)_'}\n"
    )


def _add_to_project_members(project_name: str, handle: str) -> None:
    """Append ``handle`` to the project's CHARTER members list and MEMBERS file.

    Idempotent: if the handle is already there, this is a no-op. Mirrors
    what ``project_cmd.cmd_admit`` does, without the click dependencies,
    so the API can call it directly.
    """
    repo = find_project(project_name)
    if repo is None:
        raise RequestError(f"project not found: {project_name}")
    norm_handle = _at(handle)

    parsed = parse_file(repo.charter_path)
    members = [str(h) for h in parsed.meta.get("members") or []]
    if norm_handle not in members:
        members.append(norm_handle)
        parsed.meta["members"] = members
        repo.charter_path.write_text(
            dump_document(parsed.meta, parsed.body), encoding="utf-8"
        )

    members_path = repo.path / MEMBERS_FILENAME
    if members_path.is_file():
        existing_lines = members_path.read_text(encoding="utf-8").splitlines()
        existing_handles = {
            line.strip().lstrip("@").lower()
            for line in existing_lines
            if line.strip() and not line.strip().startswith("#")
        }
    else:
        existing_lines = ["# Project members (one handle per line)"]
        existing_handles = set()

    if norm_handle.lstrip("@").lower() not in existing_handles:
        existing_lines.append(norm_handle)
        members_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")


def filter_pending(reqs: Iterable[JoinRequest]) -> list[JoinRequest]:
    return [r for r in reqs if r.state == "pending"]


def filter_for_requester(reqs: Iterable[JoinRequest], handle: str) -> list[JoinRequest]:
    norm = handle.lstrip("@").lower()
    return [r for r in reqs if r.requester.lstrip("@").lower() == norm]
