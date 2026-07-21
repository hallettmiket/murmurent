"""
Purpose: FastAPI app for the hi-fi dashboard. Serves the data contract at
         ``GET /api/dashboard`` and the static React/JSX assets from
         ``docs/designer_dashboard/`` so the existing hi-fi HTML can be
         opened straight from the browser.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``MURMURENT_USER`` environment variable (or ``?user=`` query param)
       to scope the snapshot to a member.
Output: JSON + static files. Served via uvicorn.

Run::

    murmurent dashboard --hifi          # defaults to localhost:8770
    murmurent dashboard --hifi --port 8888

Open `http://localhost:8770/` in a browser.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.identity import resolve as resolve_identity
from ..core.repo import lab_mgmt_repo_root
from . import contract as C
from . import notebook_actions
from . import request_actions
from . import sea_actions
from . import snapshot as snap_mod


class NotebookEditBody(BaseModel):
    """Optional JSON body for ``POST /api/notebook/edit``."""

    date: str | None = None  # ISO date; defaults to today


class NewSeaBody(BaseModel):
    """JSON body for ``POST /api/sea/{project}/new``."""

    to_target: str
    kind: str  # "skill" | "experiment" | "analysis"
    description: str


class JoinRequestBody(BaseModel):
    """JSON body for ``POST /api/request/join``."""

    project: str
    justification: str = ""


class CreateProjectRequestBody(BaseModel):
    """JSON body for ``POST /api/request/create-project``."""

    project: str
    proposed_members: list[str] = []
    sensitivity: str = "standard"
    proposed_lead: str | None = None
    justification: str = ""
    # Phase 16: repo destination. Default preserves the existing GitHub
    # path. ``local_repo_root`` is consulted only when kind="local" —
    # it defaults to ``<lab_base>/<git_repos_subpath>`` resolved
    # server-side from machine + lab settings.
    repo_kind: C.RepoDestination = "github"
    local_repo_root: str | None = None
    # Item 3 (R2/R3): which registered host this project should live on.
    # Defaults to "local" (this laptop); set to "lab-server" (or any name
    # in ~/.murmurent/hosts.yaml) to scaffold the project on that machine.
    host: str = "local"
    # 2026-05-15: optional override for the auto-derived Slack channel
    # name. ``None`` / "" → murmurent defaults to ``proj-<project>``.
    # Useful when the lab already has a channel that doesn't follow
    # the convention, or wants a different name at create time.
    slack_channel_name: str | None = None
    # (5) 2026-07: a project is a set of repos + a set of machines. ``machines``
    # is the full host set the project lives on (``host`` is derived from the
    # first when set). ``attach_repos`` names existing inventory repos to fold
    # into the project alongside the freshly-scaffolded primary repo.
    machines: list[str] = []
    attach_repos: list[str] = []
    # (10) inter-group projects: the agreed shared Slack workspace. REQUIRED
    # (validated server-side) when the proposed members span groups.
    slack_workspace: str | None = None


class ProjectMemberBody(BaseModel):
    """JSON body for ``POST /api/project/{project}/members`` — add a member.
    ``enrollment`` is the PoP fallback for keyless/external members."""

    handle: str
    enrollment: dict | None = None
    dm: bool = True


class AddMemberBody(BaseModel):
    """JSON body for ``POST /api/members``."""

    handle: str
    full_name: str
    role: str = "staff"


class IssueMemberCardBody(BaseModel):
    """JSON body for ``POST /api/members/issue-card`` — the cert-gated add flow.

    The PI pastes the member's enrollment request (their proof-of-possession:
    a public key + a signature proving they hold the matching private key). The
    server verifies it and issues a signed member card, which is what actually
    puts the member on the roster with a certificate."""

    enrollment: dict                                  # the member's PoP request
    group: str | None = None                          # lab to add them to (default: current lab)
    dm: bool = True                                   # try to DM the bundle on Slack


class ProjectRepoBody(BaseModel):
    """JSON body for ``POST /api/project/{project}/repos`` — assign a repo to a
    project (code / manuscript / data / infra)."""

    repo_name: str
    role: str = "code"
    path: str = ""
    host: str = "local"
    remote_path: str = ""
    remote_url: str = ""
    overleaf: bool = False


class WorkspaceLaunchBody(BaseModel):
    """JSON body for ``POST /api/workspace/launch``."""

    project: str
    agents: list[str] = []
    sea_id: int | None = None


class WorkspaceInitializeBody(BaseModel):
    """JSON body for ``POST /api/workspace/initialize`` (install wizard)."""

    member: str                                # ``@handle`` of the installer
    project: str
    machine_type: str                          # "laptop" | "lab_server"
    hostname: str | None = None
    username: str                              # local OS account on the machine
    has_direct_access: bool = True
    lab_base: str
    raw_path: str
    refined_path: str
    notebook_path: str
    ssh_remote: str | None = None
    mount_point: str | None = None
    infra_components: list[str] = []
    agents: list[str] = []
    # One-shot clone-and-adopt for a brand-new repo (Repos panel "+ install"
    # on a row with a GitHub origin but no clone anywhere yet). When
    # ``clone_if_missing`` is true and the local clone is absent, the
    # server runs ``git clone <repo_url> ~/repos/<project>`` before
    # projectizing. For SSH installs, ``repo_url`` (when given) overrides
    # the value derived from CHARTER — which won't exist yet for a
    # never-adopted repo.
    repo_url: str | None = None
    clone_if_missing: bool = False


class MachineSettingsBody(BaseModel):
    """JSON body for ``POST /api/machine/settings``."""

    machine_name: str | None = None
    wigamig_base: str | None = None
    obsidian_vault_path: str | None = None
    obsidian_vault_name: str | None = None
    notebook_subfolder: str = "lab-notebook"
    oracle_subfolder: str = "oracle"
    lab_base: str | None = None


class MemberSettingsBody(BaseModel):
    """JSON body for ``POST /api/member/settings``.

    Flat — the same shape the modal already sends. The endpoint maps
    these onto nested ``contact:`` / ``location:`` blocks in the member's
    lab-mgmt frontmatter.
    """

    # Handles — per-person, machine-independent. ``official_handle`` (e.g. a
    # Western netname) and ``slack_handle`` persist to the top level of the
    # member frontmatter (``official_handle`` and ``slack``, the roster
    # fields). The murmurent handle is the file's ``handle`` (read-only);
    # GitHub is ``github`` below.
    official_handle: str | None = None
    slack_handle: str | None = None
    # Contact
    email: str | None = None
    orcid: str | None = None
    bluesky: str | None = None
    github: str | None = None
    osf: str | None = None
    website: str | None = None
    # Location
    office: str | None = None
    dry_lab: str | None = None
    wet_labs: str | None = None
    address: str | None = None
    city: str | None = None
    department: str | None = None
    # Legacy Obsidian fields — accepted for backwards-compat (the old
    # modal still posts them) but silently ignored: those moved to
    # ``POST /api/machine/settings`` because they are per-machine.
    obsidian_vault_path: str | None = None
    obsidian_vault_name: str | None = None
    notebook_subfolder: str | None = None
    oracle_subfolder: str | None = None
    # Phase 3 (2026-05-15): per-provider usernames. ``None`` = "don't
    # touch"; ``{}`` clears all; values with empty strings drop that
    # specific provider's login. Keys must match an entry in the lab's
    # ``git_providers`` list, but we don't enforce that at the
    # endpoint — the lab list can grow over time and stale member
    # entries are harmless until cleaned up.
    git_logins: dict[str, str] | None = None


class GitProviderBody(BaseModel):
    """One git provider entry in the ``POST /api/lab/settings`` body."""

    id: str
    kind: str = "github"
    label: str = ""
    target: str = ""


class LabSettingsBody(BaseModel):
    """JSON body for ``POST /api/lab/settings`` (PI-only)."""

    name: str | None = None                          # short id, e.g. "hallett"
    display_name: str | None = None                  # e.g. "Hallett Lab"
    pi_handle: str | None = None                     # ``@handle``
    website: str | None = None
    admins: list[str] | None = None
    lab_base: str | None = None                      # host:/path/to/wigamig
    # Phase 2 (2026-05-15): lab's menu of git providers. ``None`` means
    # "don't touch"; an empty list means "clear the list".
    git_providers: list[GitProviderBody] | None = None
    github_org: str | None = None                    # legacy: single GitHub org
    git_repos_subpath: str | None = None             # default "repos"
    # Slack wiring — the lab's workspace + shareable invite link. The PI's
    # Slack workspace IS the lab's, so these live in Lab settings. ``None`` =
    # don't touch, empty string = clear.
    slack_workspace: str | None = None               # workspace id, e.g. TDUD7D20Y
    slack_invite_url: str | None = None              # shareable join link
    # Storage locations (2026-07-06): notebooks + Obsidian each get a machine +
    # path; ``lab_base`` remains the files umbrella. ``None`` = don't touch,
    # empty string = clear.
    notebook_host: str | None = None
    notebook_path: str | None = None
    obsidian_host: str | None = None
    obsidian_path: str | None = None
    # Deprecated: still accepted for backwards-compat but ignored on output.
    notebook_large_files_path: str | None = None
    lab_oracle_vault: str | None = None


class RegistrarLabCreateBody(BaseModel):
    """JSON body for ``POST /api/registrar/lab`` (Phase B)."""

    name: str                                        # short ID, lowercase + _
    display_name: str
    pi_handle: str                                   # Western netname, with or without @
    pi_full_name: str | None = None
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    institution: str | None = None
    department: str | None = None


class RegistrarLabEditBody(BaseModel):
    """JSON body for ``POST /api/registrar/lab/{name}/edit`` (Phase C).

    Every field is optional; ``None`` means "don't touch", an empty
    string means "clear this field". ``name`` is not editable.
    """

    display_name: str | None = None
    pi_handle: str | None = None
    pi_full_name: str | None = None
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    institution: str | None = None
    department: str | None = None


class RegistrarCoreCreateBody(BaseModel):
    """JSON body for ``POST /api/registrar/core`` (Phase E).

    Mirrors the lab create body except the lead's field is called
    ``leader_handle`` (cores have core-leaders, not PIs).
    """

    name: str
    display_name: str
    leader_handle: str
    leader_full_name: str | None = None
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    institution: str | None = None
    department: str | None = None


class RegistrarCoreEditBody(BaseModel):
    """JSON body for ``POST /api/registrar/core/{name}/edit``."""

    display_name: str | None = None
    leader_handle: str | None = None
    leader_full_name: str | None = None
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    institution: str | None = None
    department: str | None = None


class RegistrarCollabCreateBody(BaseModel):
    """JSON body for ``POST /api/registrar/collaboration`` (Phase D)."""

    name: str                                  # short ID, lowercase + _
    pis: list[str]                             # >=2 @handles
    groups: list[str]                          # >=2 lab/core short IDs
    member_subset: dict[str, list[str]] = {}   # group -> [@handles]
    oracle_vault: str | None = None            # defaults to "wigamig_collab_<name>"


class RegistrarCollabEditBody(BaseModel):
    """JSON body for ``POST /api/registrar/collaboration/{name}/edit``."""

    pis: list[str] | None = None
    groups: list[str] | None = None
    member_subset: dict[str, list[str]] | None = None
    oracle_vault: str | None = None


class HostAddBody(BaseModel):
    """JSON body for ``POST /api/hosts`` (Item 3 R4, dashboard host CRUD)."""

    name: str
    ssh_host: str
    remote_user: str = ""
    project_root: str = "~/repos"
    # ``wigamig_base`` is the canonical 2026-05-14 name for the per-machine
    # murmurent umbrella. ``lab_vm_root`` is kept as an alias on input for
    # backwards-compat with older clients; new code writes ``wigamig_base``.
    wigamig_base: str | None = None
    lab_vm_root: str = "~/wigamig"
    vault_root: str = "~/Obsidian"
    # Personal-vault subfolders + lab-vault clone path on this machine
    # (issue #25). Optional; conventions apply when omitted.
    oracle_subfolder: str = "oracle"
    notebook_subfolder: str = "lab-notebook"
    lab_vault_root: str = ""
    mount_point: str = ""
    description: str = ""
    scan_dirs: list[str] = []


class HostScanDirsBody(BaseModel):
    """JSON body for ``PATCH /api/hosts/{name}/scan-dirs``."""

    scan_dirs: list[str]


class HostUpdateBody(BaseModel):
    """JSON body for ``PATCH /api/hosts/{name}`` — the Machines editor. Any
    field left ``None`` is unchanged. Mirrors the Add-machine field set (minus
    the immutable ``name``): ``ssh_host`` + ``remote_user`` (connection),
    ``lab_vm_root`` (Files root), ``vault_root`` (Obsidian), ``description``,
    and ``scan_dirs`` (Repo location(s))."""

    ssh_host: str | None = None
    remote_user: str | None = None
    lab_vm_root: str | None = None
    vault_root: str | None = None
    # Issue #25: personal-vault subfolders + the lab-mgmt clone path on this
    # machine (the remote-machine editor's LAB-vault location field).
    oracle_subfolder: str | None = None
    notebook_subfolder: str | None = None
    lab_vault_root: str | None = None
    description: str | None = None
    scan_dirs: list[str] | None = None


class AdoptCloneBody(BaseModel):
    """JSON body for ``POST /api/inventory/adopt``.

    Makes an existing git clone (a ``• clone`` row in the Repo
    Inventory) **murmurent-ready**: readiness marker + commons agent
    symlinks + CLAUDE.md stub. No project fields — adoption doesn't
    create a project; the New Project flow attaches ready repos.

    ``host`` defaults to ``"local"``; a registered SSH host name runs
    the bootstrap on the remote over one batched SSH session.
    """

    clone_path: str                # absolute path on the target host
    lab: str = ""                  # owning lab slug (default: this machine's)
    agents: list[str] = []         # commons agents to symlink (empty = none)
    host: str = "local"            # "local" or a registered SSH host name


class UpgradeCloneBody(BaseModel):
    """JSON body for ``POST /api/inventory/upgrade``.

    Brings an ALREADY-ready repo up to the current murmurent release: converts a
    legacy ``CHARTER.md`` bootstrap to the marker, migrates the marker schema,
    re-links commons agents, re-stamps ``bootstrap_version``.

    Agent *content* updates never need this — ``.claude/agents/*.md`` are
    symlinks into the commons clone, so editing an agent there reaches every
    ready repo already. This is for *structural* drift: a new agent shipped in a
    release, or a marker-schema bump.
    """

    clone_path: str                # absolute path (local only — see the handler)
    add_agents: list[str] = []     # commons agents to ADD to the existing links
    all_agents: bool = False       # link every commons agent (new ones included)


class LoginSelectBody(BaseModel):
    """JSON body for ``POST /api/login/select``.

    The login landing page posts the (handle, role) the user picked.
    Server validates the role is one they actually hold, logs the
    transition to ``~/.murmurent/role_audit.log``, and returns the URL
    the client should navigate to (``/dashboard`` or ``/registrar``).
    """

    handle: str
    role: str  # "member" | "pi" | "registrar"
    remember_user: bool = False


class AuthenticateBody(BaseModel):
    """JSON body for ``POST /api/login/authenticate`` (session auth)."""

    handle: str = ""
    secret: str = ""


class RegistrarProfileBody(BaseModel):
    """JSON body for ``POST /api/registrar/profile``.

    Partial-POST safe: ``None`` means "don't touch", empty string
    clears. Same semantics as the member-settings endpoint.
    """

    full_name: str | None = None
    title: str | None = None
    email: str | None = None
    orcid: str | None = None
    website: str | None = None
    github: str | None = None
    office: str | None = None
    address: str | None = None
    city: str | None = None
    department: str | None = None
    institution: str | None = None


class ProposeCollaborationBody(BaseModel):
    """JSON body for ``POST /api/collaboration/propose`` (item #9).

    A PI of any lab fills this in to propose a new cross-group
    collaboration. The registrar approves/declines via the registrar
    dashboard's pending-requests panel.
    """

    proposed_name: str
    proposed_groups: list[str]
    proposed_pis: list[str]
    proposed_member_subset: dict[str, list[str]] = {}
    proposed_oracle_vault: str | None = None
    justification: str = ""


class DeclineCollabRequestBody(BaseModel):
    """JSON body for ``POST /api/registrar/collaboration_request/<id>/decline``."""

    reason: str = ""


class LinkSlackChannelBody(BaseModel):
    """JSON body for ``POST /api/project/<name>/link_slack_channel``.

    Manual escape hatch when the bot lacks ``channels:read`` and can't
    auto-discover an existing channel by name. The PI pastes the
    channel ID; murmurent writes it to CHARTER.md.
    """

    channel_id: str


class CatalogEntryBody(BaseModel):
    """JSON body for ``POST /api/sea_catalog`` (upsert)."""

    slug: str
    title: str
    kind: str  # skill | experiment | analysis
    contact: str  # @handle
    description: str = ""
    turnaround_days: int | None = None
    prerequisites: list[str] = []
    accepting: bool = True


class InboundActionBody(BaseModel):
    """JSON body for ``POST /api/inbound-sea/{id}/{accept|decline}``."""

    routed_to: str | None = None  # required for accept
    reason: str | None = None     # required for decline


class SimulateInboundBody(BaseModel):
    """For testing the receptionist flow without a real second group."""

    catalog_slug: str
    from_group: str
    from_handle: str
    from_pi: str = ""
    description: str = ""


class RequestActionBody(BaseModel):
    """JSON body for ``POST /api/request/{id}/{action}``."""

    reason: str | None = None


class SeaActionBody(BaseModel):
    """Optional JSON body for SEA action endpoints.

    Both fields are optional at the schema level; the underlying action
    layer enforces ``complete`` needs ``delivery`` and ``decline`` needs
    ``reason``.
    """

    delivery: str | None = None
    reason: str | None = None


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATIC_DIR = REPO_ROOT / "docs" / "designer_dashboard"


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    from .. import __version__ as _mm_version

    app = FastAPI(
        title="murmurent dashboard",
        description="Hi-fi murmurent group dashboard.",
        version=_mm_version,
    )

    # Version-skew guard: the dashboard serves its JSX fresh from disk, so
    # after a `git pull` the BROWSER can be newer than the PYTHON process
    # and call API routes this server doesn't have yet. The stock 404 body
    # ("Not Found") then surfaces in panels looking like a data error
    # (issue #19: "add member ... responds with 'not found'"). Rewrite the
    # bare route-miss 404 on /api/ paths to say what to actually do.
    # Endpoint-raised 404s carry their own detail and pass through as-is.
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    @app.exception_handler(_StarletteHTTPException)
    async def _http_exc_with_skew_hint(request: Request, exc: _StarletteHTTPException):
        detail = exc.detail
        if (exc.status_code == 404 and detail == "Not Found"
                and request.url.path.startswith("/api/")):
            detail = (
                "this dashboard server has no such endpoint — murmurent was "
                "probably updated after the dashboard started. Restart it "
                "(`murmurent dashboard --hifi`) and reload the page.")
        return JSONResponse({"detail": detail}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None) or None)

    # Opt-in session auth (see dashboard/auth.py). When a dashboard secret
    # is configured, every mutating request must carry a valid signed
    # session cookie — except the public allowlist (login, first-run
    # bootstrap, the public join form). With no secret configured this is a
    # no-op, so the laptop/dev flow and the test suite are unchanged.
    @app.middleware("http")
    async def _auth_gate(request: Request, call_next):
        from . import auth as _auth
        secret = _auth.configured_secret()
        if secret and _auth.request_needs_session(request.method, request.url.path):
            token = request.cookies.get(_auth.COOKIE_NAME, "")
            if _auth.verify_token(token, secret) is None:
                return JSONResponse(
                    {"detail": "authentication required — POST /api/login/authenticate "
                               "with the dashboard secret to obtain a session."},
                    status_code=401,
                )
        return await call_next(request)

    # Weekly repo-inventory refresh. Murmurent-internal cron: at startup
    # we check the cached report's mtime; if it's stale, fire a fresh
    # scan in a daemon thread so the user's first dashboard load isn't
    # blocked on SSH + ``gh repo list``. The scan writes to
    # ``~/.murmurent/inventory/`` and the dashboard reads from there.
    @app.on_event("startup")
    def _schedule_inventory_refresh() -> None:  # pragma: no cover (timing)
        import logging as _logging
        import threading
        _log = _logging.getLogger(__name__)
        try:
            from ..core import repo_inventory as _inv
            from ..core import hosts as _hosts
            if not _inv.report_is_stale(_inv.latest_report_path()):
                return
            def _run() -> None:
                try:
                    lab = snap_mod._current_lab_settings()
                    host_names = [h.name for h in _hosts.read().values()]
                    _inv.scan_and_cache(
                        github_org=lab.github_org,
                        host_names=host_names,
                    )
                    _log.info("repo inventory: weekly refresh complete")
                except Exception as exc:  # noqa: BLE001 — best-effort
                    _log.warning("repo inventory background scan failed: %s", exc)
            threading.Thread(target=_run, name="murmurent-inventory-refresh", daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            _log.warning("could not schedule inventory refresh: %s", exc)

    @app.get("/api/dashboard", response_model=C.DashboardResponse)
    def get_dashboard(
        user: str = Query("", description="Override the resolved user (Western username)."),
        persona: str = Query(
            "member",
            description=(
                "Lens to render. 'pi' is silently downgraded to 'member' if the "
                "resolved user isn't authorised to see it."
            ),
            pattern="^(member|pi)$",
        ),
    ) -> C.DashboardResponse:
        handle = (user or "").strip().lstrip("@")
        if not handle:
            identity = resolve_identity(allow_unknown=True)
            handle = identity.handle if identity.source != "unknown" else ""
        if not handle:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No user resolved. Set $MURMURENT_USER or pass ?user=<handle>."
                ),
            )
        # NETNAME ENFORCEMENT: if THIS machine has an imported identity card, the
        # signed-in netname must match its owner. Changing ~/.murmurent/user to an
        # arbitrary netname must NOT grant access — murmurent refuses.
        from ..core import identity_card as _idcard
        _owner = _idcard.machine_netname()
        if _owner and handle.lstrip("@").lower() != _owner:
            raise HTTPException(
                status_code=403,
                detail=(f"This machine is registered to @{_owner}. You signed in as "
                        f"@{handle.lstrip('@')} — access refused. Restore "
                        "~/.murmurent/user, or import your own identity card "
                        "(`murmurent identity-import`)."),
            )
        # CARD VERIFICATION: if this machine holds a signed identity card, it must
        # still verify — chain to the pinned centre root, not expired, not revoked
        # (when a CRL is available), not tampered. A bad card is refused even when
        # ~/.murmurent/user matches (identity attestation; live authz stays on the
        # registry below). No card / no anchor → falls through untouched.
        try:
            from ..core import issuance as _iss
            _cstatus, _creason = _iss.verify_local_identity()
        except Exception:
            _cstatus, _creason = ("no_card", "")
        if _cstatus == "reject":
            raise HTTPException(
                status_code=403,
                detail=(f"Your murmurent identity card failed verification "
                        f"({_creason}). It may be expired or revoked — ask your "
                        "PI/mayor to re-issue it (`murmurent import-card`)."),
            )
        # Cross-lab scoping: look up which lab this handle belongs to via the
        # registrar registry and point lab_mgmt_repo_root() at that lab's
        # lab-mgmt repo for the duration of the request. Falls through to
        # the default (single-lab install) when the registry doesn't claim
        # this handle.
        from ..core import registrar as _registrar
        from ..core import centre_init as _ci_gate
        from ..core.repo import use_lab_mgmt_root
        # resolve_viewer_lab_mgmt (not the bare lookup): it additionally
        # upgrades a card-import stub to the member's real lab_mgmt clone once
        # one exists, so a member whose card predates that fix stops seeing a
        # roster of just themselves — without hand-editing lab_mgmt_path.
        match = _registrar.resolve_viewer_lab_mgmt(handle)
        # SCOPING GATE: in ANY initialised centre, the ONLY valid identities are
        # those the centre registry claims (a member/PI/leader of a registered
        # group) or a registrar. A netname that isn't claimed gets NO dashboard —
        # there is no fallback to a default/demo lab-mgmt (which used to leak an
        # unknown netname into a stale 'hallett'/'allie' lab). Legacy installs
        # with NO centre at all (no centre.md) still fall through as before.
        if match is None and not _registrar.is_registrar(handle):
            try:
                _centre_live = _ci_gate.is_initialised()
            except Exception:
                _centre_live = False
            if _centre_live:
                raise HTTPException(
                    status_code=403,
                    detail=(f"@{handle.lstrip('@')} is not registered in this centre. "
                            "You must be a member, PI/leader, or registrar of a group "
                            "here to open a dashboard. If this is wrong, ask your "
                            "centre's mayor to add you."),
                )
        with use_lab_mgmt_root(match[1] if match else None):
            return snap_mod.build_response(handle, persona=persona)

    @app.get("/api/sea/{project}/{sea_id}")
    def get_sea(project: str, sea_id: int) -> dict:
        """Return one SEA's full payload (frontmatter + markdown body)."""
        from ..core import sea as sea_core
        from ..core.projects import find_project as _find_project

        repo = _find_project(project)
        if repo is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project}")
        path = sea_core.sea_path(repo, sea_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"SEA #{sea_id} not found in {project}")
        s = sea_core.parse_sea(path)
        return {
            "id": s.id,
            "project": project,
            "from": s.from_handle,
            "to": s.to_handle,
            "kind": s.kind,
            "state": s.state,
            "description": s.description,
            "claimed_at": s.claimed_at,
            "completed_at": s.completed_at,
            "examined_at": s.examined_at,
            "concluded_at": s.concluded_at,
            "delivery": s.delivery,
            "decline_reason": s.decline_reason,
            "body": s.body,
        }

    @app.post("/api/sea/{project}/new")
    def post_new_sea(
        project: str,
        body: NewSeaBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """File a new SEA in ``project``. Anyone in the project can call.

        The SEA goes into ``requested`` state with ``from_handle = actor``,
        ``to_handle = body.to_target``. The recipient claims it from there.
        """
        from ..commands import sea_cmd as _sea_cmd
        from ..core import sea as sea_core
        from ..core.projects import find_project as _find_project

        actor = _resolve_actor(user)
        _require_active(actor)
        if body.kind not in sea_core.VALID_KINDS:
            raise HTTPException(
                status_code=422,
                detail=f"kind must be one of {sea_core.VALID_KINDS}",
            )
        if not body.to_target.strip():
            raise HTTPException(status_code=422, detail="to_target is required")
        if not body.description.strip():
            raise HTTPException(status_code=422, detail="description is required")
        if _find_project(project) is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project}")

        try:
            new_sea = _sea_cmd.cmd_request(
                project_name=project,
                to_target=body.to_target.lstrip("@"),
                kind=body.kind,
                description=body.description,
                from_handle=actor,
            )
        except Exception as exc:  # click.ClickException + others
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "project": project, "sea": {
            "id": new_sea.id,
            "from": new_sea.from_handle,
            "to": new_sea.to_handle,
            "kind": new_sea.kind,
            "state": new_sea.state,
            "description": new_sea.description,
        }}

    @app.post("/api/sea/{project}/{sea_id}/{action}")
    def sea_action(
        project: str,
        sea_id: int,
        action: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
        body: SeaActionBody = Body(default_factory=SeaActionBody),
    ) -> dict:
        """Apply a SEA lifecycle action (claim / complete / examine / conclude / decline / reopen).

        Auth: ``user`` (or env-resolved identity) must be authorised for the
        action — see :mod:`sea_actions` for the matrix. Returns the updated
        SEA payload on success; HTTP 403 / 404 / 409 / 422 on failure.
        """
        actor = _resolve_actor(user)
        _require_active(actor)

        try:
            result = sea_actions.apply_action(
                project=project,
                sea_id=sea_id,
                action=action,
                actor=actor,
                delivery=body.delivery,
                reason=body.reason,
            )
        except sea_actions.SeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except sea_actions.SeaForbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except sea_actions.SeaConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except sea_actions.SeaBadRequest as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        from . import slack_notify as _notify
        _notify.sea_state_change(
            project=result.project,
            sea_id=result.sea.id,
            actor=actor,
            action=action,
            description=result.sea.description or "",
            new_state=result.sea.state,
        )

        return {
            "ok": True,
            "project": result.project,
            "sea": {
                "id": result.sea.id,
                "from": result.sea.from_handle,
                "to": result.sea.to_handle,
                "kind": result.sea.kind,
                "state": result.sea.state,
                "description": result.sea.description,
                "claimed_at": result.sea.claimed_at,
                "completed_at": result.sea.completed_at,
                "examined_at": result.sea.examined_at,
                "concluded_at": result.sea.concluded_at,
                "delivery": result.sea.delivery,
                "decline_reason": result.sea.decline_reason,
            },
        }

    @app.get("/api/decommissions")
    def list_decommission_reports(
        kind: str = Query("", description="Filter by entity kind (project/machine/user/installation/sea)."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """List decommission reports on this machine, newest first.

        PI-only — the report dir is per-machine local state, so this is
        scoped to "what's been decommissioned from murmurent on the
        computer running the dashboard." Reports are NOT pulled
        cross-machine; each laptop / lab server has its own history.
        """
        from ..core import decommission as _deco
        from ..core.frontmatter import parse_file as _pf

        _require_pi(user)
        kind_filter = (kind or "").strip().lower() or None
        rows: list[dict] = []
        for path in _deco.list_reports(kind=kind_filter):
            meta: dict = {}
            try:
                parsed = _pf(path)
                meta = parsed.meta or {}
            except Exception:
                pass
            rows.append({
                "file": path.name,
                "kind": meta.get("kind") or "unknown",
                "name": meta.get("name") or path.stem,
                "decommissioned_by": meta.get("decommissioned_by") or "",
                "decommissioned_at": meta.get("decommissioned_at") or "",
                "reversible": bool(meta.get("reversible", True)),
            })
        return {"reports": rows}

    @app.get("/api/decommissions/{filename}")
    def get_decommission_report(
        filename: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Return one decommission report's body so the UI can preview it.

        Rejects any filename containing a path separator or ``..`` — the
        only legitimate values come from /api/decommissions which always
        returns plain filenames inside the report dir.
        """
        from ..core import decommission as _deco

        _require_pi(user)
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="invalid report filename")
        path = _deco._decommission_dir() / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"no report {filename!r}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"file": filename, "body": text}

    @app.post("/api/sea/{project}/{sea_id}/archive")
    def archive_sea_endpoint(
        project: str,
        sea_id: int,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Soft-delete a SEA: hide it from active queues, preserve the file.

        Orthogonal to the existing decline/conclude lifecycle — archive
        is for "this SEA is no longer relevant and should stop appearing
        in dashboards" regardless of where it sits in the workflow. PI
        only. Reversible via the matching unarchive endpoint.
        """
        from ..core import sea as sea_core
        from ..core.projects import find_project as _find_project
        from ..core import decommission as _deco

        actor = _require_pi(user)
        repo = _find_project(project)
        if repo is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project}")
        path = sea_core.sea_path(repo, sea_id)
        if not path.is_file():
            raise HTTPException(status_code=404,
                                detail=f"SEA #{sea_id} not found in {project}")
        s = sea_core.parse_sea(path)
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        s.archived = True
        s.archived_at = now
        s.archived_by = f"@{actor}"
        sea_core.write_sea(repo, s)
        report = _deco.write_report(_deco.DecommissionRecord(
            kind="sea",
            name=f"{project}_{sea_id}",
            decommissioned_by=f"@{actor}",
            cleanup_items=[
                _deco.CleanupItem(
                    path=str(path),
                    note="SEA file preserved; flagged archived in frontmatter. Delete only if you're sure.",
                ),
            ],
            extra_meta={"project": project, "sea_id": str(sea_id),
                        "state": s.state, "kind": s.kind},
        ))
        return {"ok": True, "report": str(report), "archived": True}

    @app.post("/api/sea/{project}/{sea_id}/unarchive")
    def unarchive_sea_endpoint(
        project: str,
        sea_id: int,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Bring a previously-archived SEA back into active queues."""
        from ..core import sea as sea_core
        from ..core.projects import find_project as _find_project

        _require_pi(user)
        repo = _find_project(project)
        if repo is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project}")
        path = sea_core.sea_path(repo, sea_id)
        if not path.is_file():
            raise HTTPException(status_code=404,
                                detail=f"SEA #{sea_id} not found in {project}")
        s = sea_core.parse_sea(path)
        s.archived = False
        s.archived_at = None
        s.archived_by = None
        sea_core.write_sea(repo, s)
        return {"ok": True, "archived": False}

    @app.post("/api/request/join")
    def request_join(
        body: JoinRequestBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """File a project-join request. Anyone can call this."""
        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            result = request_actions.file_join_request(
                actor=actor, project=body.project, justification=body.justification
            )
        except request_actions.RequestMissing as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except request_actions.RequestForbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except request_actions.RequestBadRequest as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        from . import slack_notify as _notify
        _notify.project_request(kind="join", project=body.project, actor=actor)
        return _request_response(result.request)

    @app.post("/api/request/create-project")
    def request_create_project(
        body: CreateProjectRequestBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Propose a new project (anyone can; PI approves to scaffold)."""
        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            result = request_actions.file_create_request(
                actor=actor,
                project=body.project,
                proposed_members=body.proposed_members,
                sensitivity=body.sensitivity,
                proposed_lead=body.proposed_lead,
                justification=body.justification,
                repo_kind=body.repo_kind,
                local_repo_root=body.local_repo_root,
                host=body.host,
                slack_channel_name=body.slack_channel_name,
                machines=body.machines,
                attach_repos=body.attach_repos,
                slack_workspace=body.slack_workspace,
            )
        except request_actions.RequestForbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except request_actions.RequestBadRequest as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return _request_response(result.request)

    @app.post("/api/request/{request_id}/{action}")
    def request_action(
        request_id: int,
        action: str,
        body: RequestActionBody = Body(default_factory=RequestActionBody),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Approve or decline a project-join request. PI only."""
        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            result = request_actions.apply_action(
                request_id=request_id, action=action, actor=actor, reason=body.reason
            )
        except request_actions.RequestMissing as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except request_actions.RequestForbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except request_actions.RequestConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except request_actions.RequestBadRequest as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        req = result.request
        probes: list[dict] = []
        if action == "approve" and req.kind == "project-create":
            import logging as _logging
            from ..core import cert_provision as _cprov
            from ..core import project_members as _pm
            from ..core import project_provision as _pp
            from ..core.preflight import Probe as _Probe
            from ..core.repo import lab_mgmt_repo_root as _lmgmt
            _log = _logging.getLogger(__name__)
            # (8) PRIVATE Slack channel via the cert-provision path (was the
            # public create_project_channel). Membership is synced to the
            # project's CERTIFIED members from here on; the workspace token
            # comes from resolve_project_slack (owning lab, or the agreed
            # shared workspace for inter-group projects). Best-effort: the
            # approval must succeed even when Slack is offline/scopeless.
            try:
                slack_out = _cprov.provision_slack(req.project)
                if slack_out.get("ok") and slack_out.get("channel_id"):
                    probes.append(_Probe(
                        name="slack channel (private)", status="ok",
                        detail=f"channel id {slack_out['channel_id']}",
                        required=False,
                    ).to_dict())
                else:
                    probes.append(_Probe(
                        name="slack channel (private)", status="warn",
                        detail=str(slack_out.get("detail")
                                   or slack_out.get("error")
                                   or "channel not created — provision later from the panel"),
                        required=False,
                    ).to_dict())
            except Exception as slack_exc:  # noqa: BLE001
                _log.warning("private-channel provisioning failed for %s: %s",
                             req.project, slack_exc)
                probes.append(_Probe(
                    name="slack channel (private)", status="warn",
                    detail=str(slack_exc), required=False,
                ).to_dict())

            # (7) Project certificates: the creator (lead) gets the delegation
            # card; when the PI IS the creator, every roster-keyed member is
            # carded + DM'd right now. Best-effort — cert failures surface as
            # probes, never block the approval (re-issue from the panel).
            try:
                lab_name = snap_mod._current_lab_settings().name or ""
                certs_out = _pm.create_project_certs(
                    req.project, lab=lab_name,
                    lead=(req.proposed_lead or req.requester),
                    members=list(req.proposed_members or []))
                issued_n = len(certs_out.get("issued") or [])
                waiting = certs_out.get("awaiting_lead") or []
                pending = certs_out.get("pending_enrollment") or []
                errors = certs_out.get("errors") or []
                detail_bits = [f"{issued_n} member card(s) issued"]
                if waiting:
                    detail_bits.append(f"{len(waiting)} awaiting the lead's machine")
                if pending:
                    detail_bits.append(f"{len(pending)} need enrollment")
                if errors:
                    detail_bits.append(f"{len(errors)} error(s): "
                                       + "; ".join(e.get("detail", "") for e in errors))
                probes.append(_Probe(
                    name="project certificates",
                    status="ok" if not errors else "warn",
                    detail=" · ".join(detail_bits), required=False,
                ).to_dict())
            except Exception as cert_exc:  # noqa: BLE001
                _log.warning("project-cert issuance failed for %s: %s",
                             req.project, cert_exc)
                probes.append(_Probe(
                    name="project certificates", status="warn",
                    detail=str(cert_exc), required=False,
                ).to_dict())

            # Provision the git origin. Phase 4: resolve the project's
            # ``repo_kind`` (which is now a provider id) against the
            # lab's git_providers list. Falls back to the legacy
            # github/local synthesized provider when the id matches
            # those literals — keeps pre-refactor charters working.
            from ..core import git_providers as _gpr2
            local_repo = Path(f"~/repos/{req.project}").expanduser()
            kind_or_id = req.repo_kind or "github"
            lab_settings = snap_mod._current_lab_settings()
            provider = _gpr2.find_provider(
                [_pp._GP.GitProvider(**p.model_dump()) for p in lab_settings.git_providers],
                kind_or_id,
            )
            ctx = _pp.ProvisionContext(
                project=req.project,
                local_repo=local_repo,
                kind=kind_or_id,
                org=lab_settings.github_org,
                bare_repo_path=(
                    Path(req.local_repo_root).expanduser() / f"{req.project}.git"
                    if kind_or_id == "local" and req.local_repo_root else None
                ),
                members=list(req.proposed_members or []),
                lab_mgmt_root=_lmgmt(),
                provider=provider,
                provider_id=kind_or_id,
            )
            try:
                probes.extend(p.to_dict() for p in _pp.provision_project_remote(ctx))
            except Exception as exc:  # noqa: BLE001
                _log.warning("remote provisioning failed for %s: %s", req.project, exc)
                probes.append(_Probe(
                    name="remote provisioning", status="fail",
                    detail=str(exc), required=True,
                ).to_dict())
        response = _request_response(result.request)
        if probes:
            from ..core import preflight as _pf2
            from ..core.preflight import Probe as _Probe2
            response["probes"] = probes
            response["overall"] = _pf2.overall_status(
                [_Probe2(**p) for p in probes]
            )
        return response

    def _request_response(req) -> dict:
        return {
            "ok": True,
            "request": {
                "id": req.id,
                "requester": req.requester,
                "project": req.project,
                "state": req.state,
                "justification": req.justification,
                "created_at": req.created_at,
                "resolved_at": req.resolved_at,
                "resolved_by": req.resolved_by,
                "decline_reason": req.decline_reason,
            },
        }

    # -----------------------------------------------------------------
    # Workspace launcher (Phase 14)
    # -----------------------------------------------------------------

    @app.post("/api/workspace/launch")
    def workspace_launch(
        body: WorkspaceLaunchBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Open VSCode + per-agent iTerm windows for a project.

        For local projects: spawns ``scripts/start_workspace.sh`` which
        opens VSCode (multi-root) + iTerm windows. For **remote** projects
        (host != local — the working tree lives on lab-server or similar),
        the laptop can't start agent shells over there; we just launch
        VSCode in Remote-SSH mode via the ``vscode-remote://`` URL and let
        the user open agent terminals inside VSCode themselves.

        Pass ``project`` (the basename of a project under ``~/repos``) and
        ``agents`` (used only for local projects). Optionally ``sea_id``.
        """
        import os
        import subprocess
        from ..core.repo import murmurent_repo_root
        from ..core.projects import (
            find_project as _find_project,
            project_path,
            read_remote_pointer,
        )
        from . import workspace_file as _workspace_file

        actor = _resolve_actor(user)
        _require_active(actor)

        if _find_project(body.project) is None:
            raise HTTPException(status_code=404, detail=f"project not found: {body.project}")

        # ---- Remote project: VSCode Remote-SSH launch ----
        # Two routing sources, in priority order:
        #   1. Installation manifest at ~/.murmurent/installations/<project>.yaml
        #      with ``ssh_remote`` set. This is the canonical "this machine
        #      installed mp1 on lab-server" signal — written by
        #      workspace_initialize. Wins because the user may have a local
        #      working tree AND a remote install for the same project.
        #   2. Legacy ``.murmurent-remote-pointer`` marker in the local clone
        #      (the older "pure-remote pointer" design). Still honoured for
        #      back-compat with projects scaffolded before installations
        #      manifests existed.
        host_name: str | None = None
        remote_path: str | None = None
        from .snapshot import INSTALLATIONS_DIR as _INST_DIR
        manifest_path = _INST_DIR / f"{body.project}.yaml"
        if manifest_path.is_file():
            try:
                import yaml as _yaml_lp
                m = _yaml_lp.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except (OSError, _yaml_lp.YAMLError):
                m = {}
            ssh_r = (m.get("ssh_remote") or "").strip() if isinstance(m, dict) else ""
            if ssh_r:
                host_name = ssh_r
                # Resolve the per-project working clone path on the remote.
                # The host's ``project_root`` is the parent dir ("~/repos"
                # by convention); the project basename gives us the leaf.
                from ..core import hosts as _hosts_lp
                try:
                    h = _hosts_lp.resolve(ssh_r)
                    project_root = h.project_root or "~/repos"
                except Exception:
                    project_root = "~/repos"
                rp = f"{project_root.rstrip('/')}/{body.project}"
                # VSCode Remote-SSH needs an absolute path — tildes don't
                # expand. Use the ``remote_home`` we captured at install
                # time (e.g. /home/UWO/the_pi on lab-server, which the
                # Ubuntu-default /home/<user> heuristic would have got
                # wrong). Fall back to leaving the tilde if no manifest
                # data (legacy installs).
                rh = (m.get("remote_home") or "").strip() if isinstance(m, dict) else ""
                if rh and rp.startswith("~/"):
                    rp = f"{rh.rstrip('/')}/" + rp[2:]
                remote_path = rp

        if host_name is None:
            pointer = read_remote_pointer(project_path(body.project))
            if pointer is not None:
                host_name, remote_path = pointer

        if host_name is not None:
            from ..core import hosts as _hosts
            try:
                host = _hosts.resolve(host_name)
                ssh_host = host.ssh_host or host_name
            except _hosts.HostNotFound:
                ssh_host = host_name
            vscode_url = f"vscode-remote://ssh-remote+{ssh_host}{remote_path}"
            # Prefer the ``code`` CLI directly with ``--folder-uri`` —
            # works without LaunchServices having to register the
            # ``vscode-remote://`` scheme. Fall back to ``open`` only
            # when ``code`` isn't found (Linux without the install, or
            # an old VSCode that didn't bundle the CLI). The launcher
            # path inside the app bundle is the canonical place — the
            # PATH-installed ``code`` shim points back to it.
            import shutil as _sh
            launched = False
            launch_err: str | None = None
            code_bin: str | None = None
            for cand in (
                "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code",
                _sh.which("code") or "",
            ):
                if cand and Path(cand).is_file():
                    code_bin = cand
                    break
            if code_bin:
                try:
                    subprocess.Popen(  # noqa: S603
                        [code_bin, "--folder-uri", vscode_url, "--new-window"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    launched = True
                except OSError as exc:
                    launch_err = f"code launcher failed: {exc}"
            else:
                # Last resort: try the URL handler. On macOS this errors
                # with kLSApplicationNotFoundErr when no app claims the
                # scheme — surface that so the UI can suggest the fix.
                try:
                    res = subprocess.run(  # noqa: S603
                        ["open", vscode_url],
                        capture_output=True, text=True, timeout=10,
                    )
                    if res.returncode == 0:
                        launched = True
                    else:
                        launch_err = (res.stderr or res.stdout or "").strip()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    launch_err = str(exc)
            return {
                "ok": True,
                "project": body.project,
                "host": host_name,
                "remote_path": remote_path,
                "vscode_url": vscode_url,
                "launched": launched,
                "launcher": code_bin or "open",
                "error": launch_err,
                "note": (
                    f"Project lives on {host_name} — launched VSCode Remote-SSH."
                    if launched else
                    "Could not launch VSCode automatically. Open VSCode manually "
                    "and paste this into the command palette: 'Remote-SSH: Connect "
                    f"to Host…' then enter '{ssh_host}', then File > Open Folder "
                    f"and enter '{remote_path}'. Or copy: {vscode_url}"
                ),
            }

        # ---- Local project: open via scripts/open_murmurent.sh ----
        # The newer launcher (2026-05-17) detects monitors via JXA+AppKit
        # and positions the window at 80% of the chosen display
        # (external if attached, else laptop). It does NOT spawn iTerm
        # agent-tail windows — that role moved into VSCode's BR pane
        # via the murmurent agent-reporter hook. The old
        # start_workspace.sh remains in the tree for the iTerm-windows
        # workflow but is no longer the dashboard's default.
        project_dir = project_path(body.project)
        script = murmurent_repo_root() / "scripts" / "open_murmurent.sh"
        if not script.is_file():
            raise HTTPException(status_code=500, detail=f"launcher missing: {script}")

        cmd: list[str] = [str(script), str(project_dir)]
        try:
            subprocess.Popen(  # noqa: S603 — args are list, never shelled
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"launcher failed: {exc}")

        return {
            "ok": True,
            "project": body.project,
            "project_dir": str(project_dir),
            "launcher": str(script),
            "agents": body.agents,
            "sea_id": body.sea_id,
            "cmd": cmd,
            "note": (
                "Launched via open_murmurent.sh — VSCode opens at 80% of "
                "the chosen display. Arrange the 4 quadrants once and "
                "VSCode persists the layout per folder."
            ),
        }

    @app.post("/api/workspace/initialize")
    def workspace_initialize(
        body: WorkspaceInitializeBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Provision a project on this machine: mkdir immutable/append_only + manifest.

        Runs a preflight first — the user wanted to see green/yellow/red
        rows for "is the project here", "can I reach the SSH host", "are
        immutable/append_only/notebook present (mkdir if not)", "any unresolved
        issues on the prior manifest". The manifest is **only** written
        when no required probe fails; otherwise the response carries the
        probes and a 422 so the UI can show what to fix.
        """
        import datetime as _dt
        import yaml as _yaml
        from .snapshot import INSTALLATIONS_DIR
        from ..core import preflight as _pf
        from ..core.preflight import Probe as _Probe

        actor = _resolve_actor(user)
        _require_active(actor)

        probes: list[_Probe] = []

        # Validate project exists. For local installs the working tree
        # must already be on this machine; for SSH installs the tree
        # lives on the remote (remote_install will clone it if missing),
        # so we don't require a local dir — projectize will write the
        # lab_mgmt entry + manifest pointing at the remote path, and
        # the SSH-side CHARTER write happens via projectize's SSH
        # branch (-> remote_adopt.adopt_remote_clone).
        from ..core.projects import project_path as _pp
        if not body.ssh_remote and not _pp(body.project).is_dir():
            # One-shot "clone-then-adopt-then-install" path: triggered by
            # the Repos panel "+ install" button on a row that has a
            # GitHub origin but no clone on this host yet. Without this
            # branch the user would have to git-clone manually then
            # adopt then install — three round-trips for the common
            # "give me this repo on my laptop" case.
            if body.clone_if_missing and body.repo_url:
                import subprocess as _sp
                target = _pp(body.project)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _sp.run(
                        ["git", "clone", body.repo_url, str(target)],
                        check=True, capture_output=True, text=True,
                    )
                    probes.append(_Probe(
                        name="clone", status="ok",
                        detail=f"cloned {body.repo_url} into {target}",
                        required=True,
                    ))
                except _sp.CalledProcessError as exc:
                    stderr = (exc.stderr or "").strip().replace("\n", " ")[:300]
                    probes.append(_Probe(
                        name="clone", status="fail",
                        detail=f"git clone failed: {stderr}",
                        required=True,
                    ))
                    return {
                        "ok": False,
                        "project": body.project,
                        "overall": "fail",
                        "probes": [p.to_dict() for p in probes],
                        "manifest": None,
                    }
            else:
                raise HTTPException(status_code=404, detail=f"project not found: {body.project}")
        if body.ssh_remote:
            probes.append(_Probe(
                name="project", status="ok",
                detail=f"SSH install on {body.ssh_remote} (remote tree)",
                required=True,
            ))
        else:
            probes.append(_Probe(
                name="project", status="ok",
                detail=f"local clone at {_pp(body.project)}", required=True,
            ))

        # Carry forward any unresolved issues from a previous installation
        # on this machine — installing on top of an unresolved issue is
        # almost always a mistake (e.g. last install couldn't reach the
        # SSH mount; user fixes it and re-installs).
        prior_manifest = INSTALLATIONS_DIR / f"{body.project}.yaml"
        if prior_manifest.is_file():
            try:
                prior = _yaml.safe_load(prior_manifest.read_text(encoding="utf-8")) or {}
            except (OSError, _yaml.YAMLError):
                prior = {}
            open_issues = [i for i in (prior.get("issues") or []) if i]
            if open_issues:
                probes.append(_Probe(
                    name="prior issues", status="warn",
                    detail=f"{len(open_issues)} unresolved on prior install: " + "; ".join(map(str, open_issues[:3])),
                    required=False,
                ))
            else:
                probes.append(_Probe(
                    name="prior issues", status="ok",
                    detail="no unresolved issues on prior install", required=False,
                ))

        # Remote install: one batched SSH session does murmurent probe +
        # mkdir raw/refined/notebook + git-clone-if-missing. Combined
        # with the user's ControlMaster socket, this is typically zero
        # additional auth handshakes — matters on lab-server where 3
        # failed auths costs 30 minutes. See core.remote_install.
        if body.ssh_remote:
            from ..core import hosts as _hosts
            from ..core import remote_install as _ri
            try:
                host_obj = _hosts.resolve(body.ssh_remote)
            except Exception:
                host_obj = _hosts.Host(
                    name=body.ssh_remote, kind="ssh", ssh_host=body.ssh_remote,
                    remote_user="", project_root="~/repos", lab_vm_root=body.lab_base or "~/wigamig",
                    vault_root="~/Obsidian", mount_point=body.mount_point or "",
                    description="ad-hoc workspace_initialize target",
                )
            # Derive the canonical GitHub URL for this project from the
            # lab's settings. Sensitive projects (kind=local) bypass this
            # by leaving repo_url blank — the user's existing manual
            # workflow for those is preserved until the local-bare-repo
            # remote-clone path lands.
            from ..core.frontmatter import parse_file as _parse_charter
            repo_url: str | None = None
            kind = "github"
            try:
                charter = Path(f"~/repos/{body.project}/CHARTER.md").expanduser()
                if charter.is_file():
                    meta = _parse_charter(charter).meta or {}
                    kind = str(meta.get("repo_kind") or "github")
            except Exception:
                kind = "github"
            # Explicit override from the request body wins. Used by the
            # Repos panel's clone-and-adopt path where the CHARTER doesn't
            # exist yet on the remote — we know the URL from the GitHub
            # row, no need to derive it.
            if body.repo_url:
                repo_url = body.repo_url
            elif kind == "github":
                # Derive the canonical GitHub URL from the lab's settings.
                # Fail safe: with no configured org we must NOT build a
                # URL against a stranger's org — refuse with a clear error.
                # (Raised outside the charter-parse try above so it isn't
                # masked to repo_url=None.)
                org = snap_mod._current_lab_settings().github_org or ""
                if not org:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "no GitHub org configured — set github_org in lab.md "
                            "before installing a GitHub-backed project, or pass "
                            "repo_url explicitly."
                        ),
                    )
                repo_url = f"git@github.com:{org}/{body.project}.git"

            targets = _ri.InstallTargets(
                project=body.project,
                raw_path=body.raw_path,
                refined_path=body.refined_path,
                notebook_path=body.notebook_path,
                repo_url=repo_url,
                agents=list(body.agents or []),
            )
            for p in _ri.install(host_obj, targets):
                probes.append(p)

        # Local immutable + append-only dirs. These exist either way (the
        # dashboard writes the manifest locally even for SSH installs), but
        # they're only the *user's* data dirs when has_direct_access=True.
        raw_proj = Path(body.raw_path).expanduser() / body.project
        refined_proj = Path(body.refined_path).expanduser() / body.project
        if body.has_direct_access or not body.ssh_remote:
            for label, path in (("immutable", raw_proj), ("append_only", refined_proj)):
                probes.append(_pf._ensure_dir(path, label=label, required=False))

        # NOTE: bootstrap + manifest + lab_mgmt registry are now all
        # done in one go by core.projectize.make_wigamig_project, called
        # below after the overall-status check. The previous separate
        # bootstrap_local() call here was removed because projectize
        # does the same work; doing it twice would re-sweep symlinks
        # for no benefit.

        # If any required probe failed, refuse to write the manifest —
        # the user asked for "all issues attended to before final
        # installation". Return probes so the UI can render them.
        overall = _pf.overall_status(probes)
        if overall == "fail":
            return {
                "ok": False,
                "project": body.project,
                "overall": overall,
                "probes": [p.to_dict() for p in probes],
                "manifest": None,
            }

        # Pluck the remote ``$HOME`` out of the probes if the install
        # script printed one (only the SSH path does). Used at launch
        # time to expand ``~/repos/<project>`` into an absolute path for
        # VSCode Remote-SSH — lab-server's home is /home/UWO/<user>, not
        # the Ubuntu-default /home/<user>, so we can't hardcode it.
        remote_home: str | None = None
        for p in probes:
            if p.name == "homedir" and p.status == "ok" and p.detail:
                remote_home = p.detail.strip()
                break
        # All the side effects (CHARTER if missing, lab_mgmt registry,
        # installation manifest, .claude/agents bootstrap) flow through
        # projectize so the install + adopt endpoints can't drift.
        # Reads existing CHARTER if present — workspace_initialize
        # required the project to exist at line ~1211, so the CHARTER
        # is guaranteed to be there. The project lead/members/sens are
        # parsed from CHARTER inside the (charter exists → skip)
        # branch; we still pass them so projectize has them for the
        # registry entry when the registry doesn't yet exist.
        from ..core import projectize as _proj
        from ..core.frontmatter import parse_file as _pcharter
        from ..core.projects import project_path as _pp_for_proj
        # When ssh_remote is set, clone_path passed into projectize is
        # the path *on the remote host* (used in the SSH script's
        # ``$DEST=``). For local installs it's the laptop path. The
        # registry's ``path:`` field will reflect whichever we pass;
        # the registry's ``remote_path:`` field is computed inside
        # projectize from remote_home.
        if body.ssh_remote:
            from ..core import hosts as _hosts_for_clone
            try:
                _h = _hosts_for_clone.resolve(body.ssh_remote)
                _proot = (_h.project_root or "~/repos").rstrip("/")
            except _hosts_for_clone.HostNotFound:
                _proot = "~/repos"
            clone_dir = Path(f"{_proot}/{body.project}")
        else:
            clone_dir = _pp_for_proj(body.project)
        charter_path = clone_dir / "CHARTER.md"
        try:
            meta = _pcharter(charter_path).meta or {} if charter_path.is_file() else {}
        except Exception:
            meta = {}
        lead_from_charter = str(meta.get("lead") or body.member).strip().strip("'\"") or body.member
        members_from_charter = list(meta.get("members") or [body.member])
        sens_from_charter = str(meta.get("sensitivity") or "standard")

        try:
            pres = _proj.make_wigamig_project(
                clone_path=clone_dir,
                project=body.project,
                lead=lead_from_charter,
                members=members_from_charter,
                sensitivity=sens_from_charter,
                description="",
                agents=list(body.agents or []),
                member=body.member,
                machine_type=body.machine_type,
                hostname=body.hostname or "",
                username=body.username,
                has_direct_access=body.has_direct_access,
                lab_base=body.lab_base,
                raw_path=body.raw_path,
                refined_path=body.refined_path,
                notebook_path=body.notebook_path,
                ssh_remote=body.ssh_remote,
                remote_home=remote_home,
                mount_point=body.mount_point,
                infra_components=list(body.infra_components or []),
                # Tests monkeypatch INSTALLATIONS_DIR on snapshot.py;
                # honour it here so the manifest lands in the test
                # filesystem, not the real ~/.murmurent.
                installations_dir=INSTALLATIONS_DIR,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"projectize failed: {exc}")
        probes.extend(pres.probes)

        return {
            "ok": True,
            "project": body.project,
            "manifest": str(pres.manifest_path) if pres.manifest_path else None,
            "registry": str(pres.registry_path) if pres.registry_path else None,
            "raw_dir": str(raw_proj),
            "refined_dir": str(refined_proj),
            "overall": overall,
            "probes": [p.to_dict() for p in probes],
        }

    # -----------------------------------------------------------------
    # Settings: machine (per-machine), member (per-person), lab (PI-only)
    # -----------------------------------------------------------------

    @app.post("/api/machine/settings")
    def save_machine_settings(body: MachineSettingsBody) -> dict:
        """Persist per-machine settings and report folder preflight.

        Not gated on identity: the file is in the user's home dir, so
        the OS already enforces who can write it. After writing, runs
        the wigamig_base + Obsidian-vault probes so the UI can render
        green/yellow/red rows for the user (auto-creates the standard
        subfolders if they're missing).

        Refuses outright (HTTP 422) if ``wigamig_base`` points inside a
        protected lab-VM subtree (``/data/lab_vm/raw|refined``) — those
        paths are governed by the raw_guard / protected_paths hooks and
        re-routing writes through murmurent would bypass them.
        """
        from . import machine_settings as _ms
        from ..core import preflight as _pf

        blocked = _pf.is_lab_vm_protected(body.wigamig_base or "")
        if blocked:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"wigamig_base cannot be set under {blocked} — that subtree "
                    "is protected by lab policy. Use /data/lab_vm itself, or a "
                    "different parent."
                ),
            )

        path = _ms.write(C.MachineSettings(**body.model_dump()))
        probes = _pf.probe_wigamig_base(body.wigamig_base)
        probes.append(_pf.probe_obsidian_vault(body.obsidian_vault_path, label="personal vault"))
        # Lab (group) vault = the lab-mgmt clone (issue #25). Probe its oracle/
        # dir so the folder-check confirms the group vault resolves + is
        # readable on this machine. Best-effort: never fail the save on it.
        try:
            from ..core.repo import lab_mgmt_repo_root as _lmr
            _lab_clone = _lmr()
            probes.append(
                _pf.probe_obsidian_vault(str(_lab_clone), label="lab vault (lab-mgmt clone)")
            )
        except Exception:
            pass
        return {
            "ok": True,
            "path": str(path),
            "overall": _pf.overall_status(probes),
            "probes": [p.to_dict() for p in probes],
        }

    @app.post("/api/member/settings")
    def save_member_settings(
        body: MemberSettingsBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Write the member's contact + location fields back to lab-mgmt.

        Edits ``<lab-mgmt>/members/<actor>.md`` frontmatter. Preserves
        the body, ``handle``/``full_name``/``role``/``status``/``lab``/
        ``certifications``/``obsidian``/``created`` and any other
        unknown keys. Per-machine Obsidian fields posted by older
        clients are silently dropped — they belong on machine.yaml.
        """
        from ..core.frontmatter import parse_file, dump_document
        from ..core.repo import use_lab_mgmt_root as _use_lab_mgmt_root
        from ..core import registrar as _reg

        actor = _resolve_actor(user)

        # Scope resolution to the ACTING viewer's own lab, so on a shared,
        # multi-lab dashboard the edit lands on their roster and never the
        # machine-default lab (#32/#33). No-op on a single-lab install, and an
        # explicit ``MURMURENT_LAB_MGMT_REPO`` operator pin always wins (mirrors
        # the resolver: env var outranks the registry net).
        import os as _os
        _scoped = (None if _os.environ.get("MURMURENT_LAB_MGMT_REPO")
                   else _reg.resolve_viewer_lab_mgmt(actor))
        with _use_lab_mgmt_root(_scoped[1] if _scoped else None):
            _require_active(actor)

            # Only modify fields the request actually sent — a partial POST
            # like ``{"email": "x"}`` must not nuke the user's other contact
            # info. ``model_fields_set`` distinguishes "omitted" from
            # "explicitly null", which a plain dict from body.model_dump()
            # cannot.
            sent = body.model_fields_set
            contact_keys = ("email", "orcid", "bluesky", "github", "osf", "website")
            location_keys = ("office", "dry_lab", "wet_labs", "address", "city", "department")

            # Members hold the roster clone READ-ONLY by design (the PI/leader is
            # the only writer, so member-side `git pull --ff-only` never
            # conflicts). Committing a member's edit to that clone leaves an
            # unpushable local commit that diverges it and breaks the next pull
            # (#34). So a non-writer's edit is STAGED to their own profile.yaml
            # (the PI applies it on the next reconcile); only the writer edits
            # the roster clone directly below.
            try:
                from ..core.lab import pi_handle as _pi_handle
                is_writer = actor.lower() == _pi_handle().lower()
            except Exception:  # noqa: BLE001 — no resolvable PI ⇒ treat as non-writer
                is_writer = False

            if not is_writer:
                from ..core import member_profile as _mp
                edits: dict = {
                    "contact": {k: getattr(body, k) for k in contact_keys if k in sent},
                    "location": {k: getattr(body, k) for k in location_keys if k in sent},
                }
                if "official_handle" in sent:
                    edits["official_handle"] = body.official_handle
                if "slack_handle" in sent:
                    edits["slack"] = body.slack_handle
                if "git_logins" in sent and body.git_logins is not None:
                    edits["git_logins"] = body.git_logins
                path = _mp.stage_roster_profile(actor, edits)
                return {
                    "ok": True, "staged": True, "path": str(path),
                    "message": (
                        "Saved to your profile. Members hold the lab roster "
                        "read-only, so this doesn't touch it — your PI applies "
                        "it to the roster on the next sync."
                    ),
                    "probes": [],
                }

            return _save_member_settings_to_roster(
                body, actor, sent, contact_keys, location_keys,
                parse_file, dump_document,
            )

    def _save_member_settings_to_roster(
        body, actor, sent, contact_keys, location_keys, parse_file, dump_document,
    ) -> dict:
        """Writer (PI/leader) path: edit ``members/<actor>.md`` + commit/push.

        Only ever reached for the roster's sole writer — a member's edit is
        staged to their own profile.yaml before this runs (see #34)."""
        member_path = lab_mgmt_repo_root() / "members" / f"{actor}.md"
        if not member_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"member file not found: {member_path}",
            )

        parsed = parse_file(member_path)
        meta = dict(parsed.meta or {})

        def _merge(block_name: str, fields: dict) -> None:
            existing = meta.get(block_name)
            block = dict(existing) if isinstance(existing, dict) else {}
            for k, v in fields.items():
                if v is None or (isinstance(v, str) and not v.strip()):
                    block.pop(k, None)
                else:
                    block[k] = v
            if block:
                meta[block_name] = block
            else:
                meta.pop(block_name, None)

        _merge("contact", {k: getattr(body, k) for k in contact_keys if k in sent})
        _merge("location", {k: getattr(body, k) for k in location_keys if k in sent})

        # Handles that live at the top level of the frontmatter (the roster
        # model owns them, so writing them here keeps the roster + dashboard in
        # sync). ``slack_handle`` maps onto the roster's ``slack`` key; the
        # murmurent handle is the file's ``handle`` (never edited here).
        def _set_top(key: str, value) -> None:
            if value is None or (isinstance(value, str) and not value.strip()):
                meta.pop(key, None)
            else:
                meta[key] = value.strip().lstrip("@") if isinstance(value, str) else value

        if "official_handle" in sent:
            _set_top("official_handle", body.official_handle)
        if "slack_handle" in sent:
            _set_top("slack", body.slack_handle)

        # Phase 3: per-provider git_logins map. Replaces the flat
        # ``contact.github`` for new code, but we keep contact.github
        # in sync with git_logins["github"] so legacy readers keep
        # working through the migration.
        if "git_logins" in sent and body.git_logins is not None:
            from ..core import git_providers as _gpr
            existing = meta.get("git_logins") if isinstance(meta.get("git_logins"), dict) else {}
            merged = dict(existing or {})
            for k, v in body.git_logins.items():
                if v is None or (isinstance(v, str) and not v.strip()):
                    merged.pop(k, None)
                else:
                    merged[str(k)] = str(v).strip().lstrip("@")
            cleaned = _gpr.dump_logins(merged)
            if cleaned:
                meta["git_logins"] = cleaned
            else:
                meta.pop("git_logins", None)
            # Mirror github login back into contact.github for legacy
            # readers (the JSX still surfaces it as a contact link).
            gh = cleaned.get("github")
            contact_block = meta.get("contact") if isinstance(meta.get("contact"), dict) else {}
            contact_block = dict(contact_block or {})
            if gh:
                contact_block["github"] = gh
            elif "github" in (existing or {}):
                contact_block.pop("github", None)
            if contact_block:
                meta["contact"] = contact_block
            else:
                meta.pop("contact", None)

        try:
            member_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}")

        # Commit + push so re-seeds / pulls don't silently overwrite
        # the save. Best-effort: a push failure leaves the local commit
        # in place and surfaces a yellow probe. See git_persist for
        # why each step can degrade independently.
        from ..core import git_persist as _gp
        probes = _gp.commit_and_push(
            member_path, message=f"profile: @{actor}", push=True,
        )
        return {
            "ok": True, "path": str(member_path),
            "probes": [p.to_dict() for p in probes],
        }

    def _scoped_to_viewer(fn):
        """Pin lab_mgmt resolution to the ACTING viewer's own lab for the whole
        request, so roster/security endpoints act on the viewer's roster and
        never the machine-default lab on a shared, multi-lab dashboard (#32/#33).

        Reads the actor from the handler's standard ``user`` query kwarg and
        wraps the call in ``use_lab_mgmt_root(resolve_viewer_lab_mgmt(actor))``.
        A no-op when the viewer isn't registry-claimed (single-lab install →
        override ``None`` → normal resolution, which the registry net already
        makes correct for the machine owner). Kept fully isolated: any
        resolution hiccup falls back to unscoped rather than 500-ing the route.

        The wrapper runs the handler in the SAME call (hence same thread), which
        is what makes the thread-local override reliable under FastAPI's sync
        threadpool. ``functools.wraps`` preserves the original signature so
        FastAPI's dependency introspection is unaffected.
        """
        import functools

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            import os
            from ..core import registrar as _reg
            from ..core.repo import use_lab_mgmt_root as _use
            # An explicit ``MURMURENT_LAB_MGMT_REPO`` is a deliberate operator pin
            # to ONE lab (a single-lab install, or a test harness). Honour it —
            # per-viewer scoping only applies on a genuine multi-lab machine,
            # which never sets that env var. This mirrors the resolver, where the
            # env var (step 2) outranks the registry net (step 4).
            if os.environ.get("MURMURENT_LAB_MGMT_REPO"):
                return fn(*args, **kwargs)
            scoped = None
            try:
                actor = _resolve_actor(kwargs.get("user", "") or "")
                scoped = _reg.resolve_viewer_lab_mgmt(actor)
            except Exception:  # noqa: BLE001 — never let scoping break the route
                scoped = None
            with _use(scoped[1] if scoped else None):
                return fn(*args, **kwargs)

        return wrapper

    @app.post("/api/lab/settings")
    @_scoped_to_viewer
    def save_lab_settings(
        body: LabSettingsBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Write lab-wide settings to ``<lab-mgmt>/lab.md`` frontmatter (PI only).

        Preserves the body, ``lab:`` (the short ID), ``created:``,
        ``institution``, ``department``, and any other unknown keys.
        Only the fields explicitly present in the body are updated.
        """
        from ..core.frontmatter import parse_file, dump_document

        _require_pi(user)

        lab_path = lab_mgmt_repo_root() / "lab.md"
        if not lab_path.is_file():
            raise HTTPException(status_code=404, detail=f"lab.md not found at {lab_path}")

        parsed = parse_file(lab_path)
        meta = dict(parsed.meta or {})

        # Map LabSettings keys onto lab.md frontmatter keys. ``name`` in
        # the contract is the short ID (lab); ``display_name`` is the
        # human label. The current lab.md uses ``name:`` for the display
        # label, so we keep that for backwards compat: store display in
        # ``name`` and the short ID in ``lab``.
        updates: dict[str, object] = {}
        if body.name is not None:
            updates["lab"] = body.name
        if body.display_name is not None:
            updates["name"] = body.display_name
        if body.pi_handle is not None:
            pi = body.pi_handle.strip()
            updates["pi"] = pi if pi.startswith("@") else f"@{pi}"
        if body.website is not None:
            updates["website"] = body.website or None
        if body.lab_base is not None:
            updates["lab_base"] = body.lab_base or None
        if body.notebook_host is not None:
            updates["notebook_host"] = body.notebook_host or None
        if body.notebook_path is not None:
            updates["notebook_path"] = body.notebook_path or None
        if body.obsidian_host is not None:
            updates["obsidian_host"] = body.obsidian_host or None
        if body.obsidian_path is not None:
            updates["obsidian_path"] = body.obsidian_path or None
        if body.notebook_large_files_path is not None:
            updates["notebook_large_files_path"] = body.notebook_large_files_path or None
        if body.lab_oracle_vault is not None:
            updates["lab_oracle_vault"] = body.lab_oracle_vault or None
        if body.admins is not None:
            updates["admins"] = list(body.admins)
        if body.github_org is not None:
            updates["github_org"] = body.github_org or None
        if body.git_repos_subpath is not None:
            updates["git_repos_subpath"] = body.git_repos_subpath or None
        if body.slack_workspace is not None:
            updates["slack_workspace"] = body.slack_workspace or None
        if body.slack_invite_url is not None:
            updates["slack_invite_url"] = body.slack_invite_url or None
        if body.git_providers is not None:
            # Validate kinds + ids before persisting. An empty list
            # explicitly clears the providers block (so the resolver
            # falls back to deriving from github_org).
            from ..core import git_providers as _gpr
            for entry in body.git_providers:
                if not entry.id.strip():
                    raise HTTPException(status_code=422, detail="git_providers[*].id is required")
                if entry.kind not in _gpr.VALID_KINDS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"git_providers[*].kind must be one of {_gpr.VALID_KINDS}",
                    )
            seen_ids: set[str] = set()
            for entry in body.git_providers:
                if entry.id in seen_ids:
                    raise HTTPException(
                        status_code=422,
                        detail=f"duplicate git_provider id: {entry.id}",
                    )
                seen_ids.add(entry.id)
            providers = [
                _gpr.GitProvider(
                    id=e.id.strip(), kind=e.kind, label=e.label, target=e.target,
                )
                for e in body.git_providers
            ]
            # Empty providers list explicitly clears the block so the
            # resolver falls back to deriving from github_org. The
            # generic loop below treats ``None`` as "drop key"; non-empty
            # lists are written as-is.
            updates["git_providers"] = _gpr.dump_providers(providers) if providers else None

        for k, v in updates.items():
            if v in (None, ""):
                meta.pop(k, None)
            else:
                meta[k] = v

        try:
            lab_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}")

        from ..core import git_persist as _gp
        probes = _gp.commit_and_push(
            lab_path, message="lab settings update", push=True,
        )
        return {
            "ok": True, "path": str(lab_path),
            "probes": [p.to_dict() for p in probes],
        }

    # -----------------------------------------------------------------
    # Master folders on the lab server (lab_base/{raw,refined,...})
    # -----------------------------------------------------------------

    def _resolve_lab_base() -> tuple[str, str | None]:
        """Return ``(lab_name, lab_base)`` for the current viewer's lab.

        Reads ``lab.md`` via the dashboard helpers — same source the
        settings modal uses. Used by both endpoints so we never disagree
        on which lab we're talking about.
        """
        # Cheap lookup: read the current lab's name then its settings.
        lab_name = ""  # resolved from the viewer's lab.md via the request override
        try:
            ls = snap_mod._lab_settings(lab_name)
            return lab_name, ls.lab_base
        except Exception:
            return lab_name, None

    @app.get("/api/lab/master_folders")
    def get_master_folders(
        refresh: bool = Query(False, description="Re-probe over SSH; otherwise return cached status."),
    ) -> dict:
        """Return the master-folders status for the current lab.

        Default mode reads the cache so the dashboard's persistent
        green-light pill loads instantly. ``?refresh=true`` forces a
        fresh SSH probe (no mkdir — that takes an explicit POST).
        """
        from ..core import master_folders as _mf
        lab_name, lab_base = _resolve_lab_base()
        if refresh:
            result = _mf.run(lab_base, create=False)
            _mf.cache_save(lab_name, result)
            return {"lab": lab_name, "from_cache": False, **result}
        cached = _mf.cached_summary(lab_name)
        if cached is None:
            # Never probed yet — return a minimal shape the UI can
            # render as "click to check".
            return {
                "lab": lab_name, "from_cache": True,
                "host": None, "path": lab_base,
                "overall": "unknown",
                "checked": None,
                "probes": [],
            }
        return {"lab": lab_name, "from_cache": True, **cached, "probes": []}

    @app.post("/api/lab/master_folders/init")
    def post_master_folders_init(
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Create any missing master folders on the lab server.

        PI-only — directory creation on a shared multi-user machine is
        not a member-level operation. Idempotent: re-running on an
        already-bootstrapped lab returns all-green probes with no side
        effects.
        """
        from ..core import master_folders as _mf
        _require_pi(user)
        lab_name, lab_base = _resolve_lab_base()
        result = _mf.run(lab_base, create=True)
        _mf.cache_save(lab_name, result)
        return {"lab": lab_name, "from_cache": False, **result}

    # -----------------------------------------------------------------
    # Repo inventory — cross-machine + GitHub git-repo audit
    # -----------------------------------------------------------------

    def _inventory_host_names() -> list[str]:
        """Return every registered host name (incl. ``local``).

        Hosts that haven't been registered via Member Profile → ⚙
        machines aren't scanned — lab-server-style remotes need an
        explicit ssh_host alias to reach them.
        """
        try:
            from ..core import hosts as _hosts
            return [h.name for h in _hosts.read().values()]
        except Exception:
            return ["local"]

    @app.get("/api/inventory/repos")
    def get_inventory(
        refresh: bool = Query(False, description="Run a fresh scan instead of returning the cached report."),
    ) -> dict:
        """Return the cross-machine + GitHub repo inventory.

        Default mode reads the most recent cached report from
        ``~/.murmurent/inventory/`` so the panel loads instantly. Pass
        ``?refresh=true`` to force a live re-scan — that hits ``gh
        repo list`` plus one SSH session per registered host. The
        result is also written to the cache so subsequent reads are
        cheap.
        """
        from ..core import repo_inventory as _inv
        lab_settings = snap_mod._current_lab_settings()
        # Empty org is intentional: scan_and_cache -> list_github_repos("")
        # returns a "no GitHub org configured" error into report.errors
        # rather than querying a stranger's org.
        org = lab_settings.github_org

        cached_path = _inv.latest_report_path()
        if refresh or cached_path is None:
            report = _inv.scan_and_cache(
                github_org=org,
                host_names=_inventory_host_names(),
            )
            return {"from_cache": False, **report.to_dict()}
        cached = _inv.load_report(cached_path)
        if cached is None:
            # Cache corrupt — re-scan rather than fail the request.
            report = _inv.scan_and_cache(
                github_org=org,
                host_names=_inventory_host_names(),
            )
            return {"from_cache": False, **report.to_dict()}
        return {"from_cache": True, "cache_path": str(cached_path), **cached}

    @app.post("/api/inventory/repos/refresh")
    def post_inventory_refresh() -> dict:
        """Explicit live re-scan. Same as GET with ?refresh=true; kept
        as a separate POST so the JSX can disable the button while it
        runs without worrying about caching.
        """
        from ..core import repo_inventory as _inv
        lab_settings = snap_mod._current_lab_settings()
        # Empty org is intentional — see the GET handler above.
        org = lab_settings.github_org
        report = _inv.scan_and_cache(
            github_org=org,
            host_names=_inventory_host_names(),
        )
        return {"from_cache": False, **report.to_dict()}

    @app.post("/api/inventory/adopt")
    def post_inventory_adopt(
        body: AdoptCloneBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Make an existing git clone (local or SSH host) murmurent-READY.

        Thin HTTP wrapper over :func:`core.adopt.adopt_clone` — the same
        chokepoint ``murmurent repo adopt`` uses. Adoption bootstraps the
        REPO only (readiness marker + commons agents); it does NOT create
        a project — attach ready repos to a project via the New Project
        flow (a project = a set of repos + a set of members). Refusals
        arrive as :class:`core.adopt.AdoptError` and map onto HTTP
        statuses via ``core.adopt.ERROR_HTTP_STATUS``.
        """
        from ..core import adopt as _adopt

        try:
            outcome = _adopt.adopt_clone(
                clone_path=body.clone_path,
                lab=(body.lab or "").strip(),
                agents=list(body.agents or []) or None,
                host=body.host or "local",
            )
        except _adopt.AdoptError as exc:
            raise HTTPException(
                status_code=_adopt.ERROR_HTTP_STATUS.get(exc.code, 500),
                detail=str(exc),
            ) from exc
        return outcome.to_dict()

    @app.post("/api/inventory/upgrade")
    def post_inventory_upgrade(
        body: UpgradeCloneBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Bring a murmurent-READY repo up to the current murmurent release.

        HTTP twin of ``murmurent repo upgrade``, over the same
        :func:`core.repo_ready.upgrade` chokepoint so the two surfaces can't
        drift. Local only: ``repo_ready`` works on the filesystem; upgrading a
        remote clone would need the SSH path built first. (Remote adopts now
        stamp the ``.murmurent.yaml`` marker directly, so they land ready.)
        """
        from pathlib import Path as _P

        from ..core import adopt as _adopt
        from ..core import repo_ready as _rr

        clone = _P(body.clone_path).expanduser()
        st = _adopt.adoption_status(str(clone))
        # Upgrade is for repos that are ALREADY marker-ready OR carry a legacy
        # CHARTER.md bootstrap that wants a one-time marker stamp (issue #28).
        # A plain clone wants adopt instead. Say which, rather than a bare 4xx.
        if not (st.ready or st.legacy_charter):
            raise HTTPException(
                status_code=409,
                detail=(f"{clone} is not murmurent-ready ({st.verdict}) — "
                        f"adopt it first, then upgrade."),
            )
        try:
            probes = _rr.upgrade(
                clone,
                add_agents=list(body.add_agents or []) or None,
                all_agents=bool(body.all_agents),
            )
        except Exception as exc:  # noqa: BLE001 — surface the reason, not a 500
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        after = _adopt.adoption_status(str(clone))
        return {
            "clone_path": str(clone),
            "verdict": after.verdict,
            "bootstrap_version": after.bootstrap_version,
            "probes": [p.to_dict() for p in probes],
        }

    # -----------------------------------------------------------------
    # Membership (PI-only roster mgmt)
    # -----------------------------------------------------------------

    @app.get("/api/members/roster-info")
    def get_roster_info() -> dict:
        """Freshness of this machine's lab_mgmt roster clone — the Lab
        Members panel's "as of <date>" stamp. Read-only, any persona."""
        from ..core import roster_sync as _rs
        return _rs.roster_info().to_dict()

    @app.post("/api/members/refresh")
    def post_members_refresh() -> dict:
        """Pull the lab_mgmt clone (--ff-only) so the roster reflects
        what the PI last pushed — the Lab Members panel's update button.
        Any persona: members refresh their read-only clone; a failure
        comes back as ``ok: false`` + detail, never a 5xx (the panel
        keeps rendering the cached roster with its stamp)."""
        from ..core import roster_sync as _rs
        return _rs.pull_lab_mgmt().to_dict()

    # -----------------------------------------------------------------
    # Personal vault (murmurent_vault) freshness + ff-only pull (issue #25 §3)
    # -----------------------------------------------------------------

    @app.get("/api/vault/info")
    def get_vault_info() -> dict:
        """Freshness of this machine's personal-vault clone — the Personal
        Oracle panel's "as of <date>" stamp. Read-only, any persona."""
        from ..core import vault_sync as _vs
        return _vs.vault_info().to_dict()

    @app.post("/api/vault/refresh")
    def post_vault_refresh() -> dict:
        """Pull the personal vault (--ff-only) so a stale clone reflects what
        another machine last pushed — the Personal Oracle panel's update
        button. Never a 5xx: a failed pull comes back ``ok: false`` + detail
        (mirrors ``/api/members/refresh``)."""
        from ..core import vault_sync as _vs
        return _vs.pull_personal_vault().to_dict()

    @app.post("/api/members")
    @_scoped_to_viewer
    def add_member_endpoint(
        body: AddMemberBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Add a new member to the lab roster. PI only."""
        from ..core import membership as _m
        from . import audit_log as _audit

        actor = _require_pi(user)
        try:
            rec = _m.add(handle=body.handle, full_name=body.full_name, role=body.role)
        except _m.MemberAlreadyExists as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _m.MembershipError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _audit.write_event(
                actor=actor, kind="member.add", project="",
                target=f"member/{rec.handle}",
                summary=f"@{actor} added @{rec.handle} ({rec.role})",
            )
        except OSError:
            pass
        from . import slack_notify as _notify
        _notify.member_added(handle=rec.handle, full_name=rec.full_name, role=rec.role)
        return {"ok": True, "member": {
            "handle": rec.handle, "full_name": rec.full_name,
            "role": rec.role, "status": rec.status, "created": rec.created,
        },
            # Roster changes auto-commit+push (members receive the roster
            # via git pull) — surface the probes so a failed push is seen.
            "git": [p.to_dict() for p in _m.last_persist_probes],
        }

    @app.post("/api/members/issue-card")
    @_scoped_to_viewer
    def issue_member_card_endpoint(
        body: IssueMemberCardBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Cert-gated add: verify the member's enrollment (proof-of-possession),
        sign a member card with the PI's key, record it in the issuance ledger,
        stamp the roster, and return the bundle to send back to the member.

        This is the ONLY way the dashboard should add a member — it guarantees a
        member on the roster actually holds a certificate (unlike the legacy
        free-form ``POST /api/members``)."""
        from ..core import issuance as _iss
        from ..core import group_reconcile as _gr
        from . import audit_log as _audit
        import json as _json

        actor = _require_pi(user)

        # Group resolution lives in issuance: blank means "the group this
        # PI leads", read from their own identity card. The old fallback
        # to the lab settings *name* passed a display name ("Bioinformatics
        # Lab") where the card holds the slug ("bioinformatics") — issue #16.
        group = (body.group or "").strip() or None

        enrollment = body.enrollment or {}
        payload = enrollment.get("payload") if isinstance(enrollment, dict) else None
        if not isinstance(payload, dict) or not payload.get("pubkey"):
            raise HTTPException(
                status_code=422,
                detail="enrollment is not a valid request (missing payload.pubkey) — "
                       "paste the exact JSON the member sent from `murmurent enroll`")
        handle = str(payload.get("handle") or "").lstrip("@")
        if not handle:
            raise HTTPException(status_code=422, detail="enrollment has no handle")

        try:
            bundle = _iss.issue_member_card(handle, enrollment=enrollment, group=group)
        except _iss.IssuanceError as exc:
            # PoP failure / not-your-group / missing PI card → 422 with the reason.
            raise HTTPException(status_code=422, detail=str(exc))

        # Adopt the group issuance actually resolved (slug from the PI's
        # card) — the audit line, Slack DM routing, and response all key
        # off it.
        group = bundle["member_card"]["payload"].get("group") or group or ""
        subj = bundle["member_card"]["payload"]["subject"]
        # Tell the PI exactly what trust root the member must pin (self-rooted
        # standalone lab → the PI's own key; centre lab → centre-pin flow).
        pi_p = bundle["pi_card"]["payload"]
        self_rooted = (pi_p.get("issuer") or {}).get("fingerprint") == pi_p["subject"]["fingerprint"]
        if self_rooted:
            import_hint = (f"murmurent import-card bundle.json "
                           f"--trust-root {pi_p['subject']['pubkey']}")
        else:
            import_hint = ("murmurent centre-pin <centre> && "
                           "murmurent import-card bundle.json")

        try:
            _audit.write_event(
                actor=actor, kind="member.issue_card", project="",
                target=f"member/{handle}",
                summary=f"@{actor} issued a member card to @{handle} ({group})",
            )
        except OSError:
            pass

        dm_ok, dm_detail = False, "not attempted"
        if body.dm:
            member_email = str(payload.get("email") or "")
            member_slack = str(payload.get("slack") or "")
            dm_text = (
                f"Your murmurent member ID for '{group}' is ready — your signed "
                f"bundle.json is attached to this message. Download it, then run:"
                f"\n\n    {import_hint}")
            dm_ok, dm_detail = _gr.send_group_dm(
                group, text=dm_text, slack=member_slack, email=member_email,
                file_content=_json.dumps(bundle, indent=2), file_name="bundle.json")

        return {
            "ok": True,
            "handle": handle,
            "group": group,
            "fingerprint": subj.get("fingerprint", ""),
            "bundle": bundle,
            "import_hint": import_hint,
            "dm": {"sent": dm_ok, "detail": dm_detail},
        }

    @app.get("/api/members/audit")
    @_scoped_to_viewer
    def members_audit_endpoint(
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Run the member-certificate audit (read-only). Returns every member's
        standing plus the flagged (non-valid) subset. PI only."""
        from ..core import member_audit as _ma

        _require_pi(user)
        statuses = _ma.audit()
        flagged = [s for s in statuses if not s.valid]
        return {
            "ok": True,
            "centre": _ma.resolve_centre(),
            "members": [
                {"handle": s.handle, "full_name": s.full_name, "role": s.role,
                 "status": s.status, "cert": s.cert, "detail": s.detail,
                 "is_pi": s.is_pi}
                for s in statuses
            ],
            "flagged": [
                {"handle": s.handle, "full_name": s.full_name, "role": s.role,
                 "status": s.status, "cert": s.cert, "detail": s.detail}
                for s in flagged
            ],
            "counts": {
                "total": len(statuses),
                "flagged": len(flagged),
                "valid": sum(1 for s in statuses if s.valid),
            },
        }

    @app.post("/api/members/audit/notify")
    @_scoped_to_viewer
    def members_audit_notify_endpoint(
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Run the audit and DM the PI the list of members lacking a valid
        certificate. Never removes anyone — removal stays a PI-confirmed action.
        PI only."""
        from ..core import member_audit as _ma
        from ..core import group_reconcile as _gr
        from ..core import membership as _m

        pi = _require_pi(user)
        group = snap_mod._current_lab_settings().name or ""
        flagged = _ma.findings()
        if not flagged:
            return {"ok": True, "flagged": 0, "notified": False,
                    "detail": "all members hold a valid certificate"}

        lines = "\n".join(
            f"  • @{s.handle} ({s.role}) — {s.detail}" for s in flagged)
        text = (
            f":rotating_light: *Member certificate audit — {group or 'your lab'}*\n"
            f"{len(flagged)} member(s) do not hold a valid identity certificate:\n\n"
            f"{lines}\n\n"
            "Review them on the dashboard (Lab members → Audit). Nobody has been "
            "removed automatically — deactivate any that shouldn't have access.\n\n"
            "All worship me and I will let you serve me.")
        pi_email = ""
        try:
            pi_email = _m.get(pi).email
        except Exception:  # noqa: BLE001
            pass
        ok, detail = _gr.send_group_dm(group, text=text, email=pi_email) if group \
            else (False, "no group configured")
        return {"ok": True, "flagged": len(flagged), "notified": ok, "detail": detail}

    def _fetch_and_consume_tier2(host_obj, *, lab_vm_root: str | None) -> list:
        """SSH to the host, tar the latest snapshot dir, untar locally,
        feed it through the Tier 2 consumer. Returns ``list[Finding]``.

        Returns an empty list (silently) when no snapshot exists yet —
        the dashboard then just shows Tier 1 plus the
        ``POSIX-NOT-AUTHORITATIVE-01`` info hint that points the PI at
        the ``Run sudo dump`` button.
        """
        import tarfile, tempfile, io as _io
        from ..core import remote as _remote
        from ..core import security_tier2 as _t2
        from pathlib import Path as _P

        remote = _remote.Remote(host_obj)
        # Tar the latest snapshot dir from the remote. ``tar -C base/.snapshot
        # -cf - latest/`` lets the latest symlink resolve to the real dir
        # via ``-h``; we ship a small archive (single MB scale) over ssh.
        #
        # Snapshot lives on **local disk** at /var/lib/murmurent/.snapshot
        # (script v4+) — the NAS NFSv4 ACLs deny root write under
        # /data/lab_vm even via the v4 mount, so the snapshot can't live
        # on the the NAS share. The mount path stays standard FHS
        # (/var/lib/murmurent) so a sysadmin can find it without a docs trip.
        snapshot_base = "/var/lib/murmurent/.snapshot"
        # **Sentinel-bracketed base64 stream**.
        #
        # ``bash -lc`` runs ~/.bashrc, which on lab-server's Anaconda
        # install (and many user setups) emits text to stdout before our
        # ``tar`` runs — ``(base)``, ``Last login:``, MOTD residue, etc.
        # Python's ``b64decode`` silently SKIPS invalid characters in
        # default mode, so those prefix bytes don't crash the decode —
        # they corrupt it. The decoded stream then starts with whatever
        # ``base, login, …`` happened to base64-decode to, instead of
        # the gzip magic ``\x1f\x8b``.
        #
        # Wrap the real output in unique sentinels so Python can extract
        # only the bytes between them. Use ``validate=True`` on the
        # decode + verify gzip magic so any future corruption surfaces
        # immediately rather than as a downstream tar error.
        BEGIN = "__WIGAMIG_TAR_BEGIN__"
        END = "__WIGAMIG_TAR_END__"
        cmd = (
            f"if [ -e {snapshot_base}/latest ]; then "
            f"echo {BEGIN}; "
            f"tar -C {snapshot_base} -hczf - latest | base64; "
            f"echo {END}; "
            f"else echo NO_SNAPSHOT >&2; exit 12; fi"
        )
        try:
            # Generous timeout — compressing + streaming a few hundred
            # MB of ACL dumps takes longer than the original 120 s.
            res = remote.run(cmd, check=False, timeout=600)
        except _remote.RemoteError:
            return []
        if res.returncode != 0 or not res.stdout:
            return []
        try:
            text = res.stdout
            begin_at = text.find(BEGIN)
            end_at = text.find(END)
            if begin_at < 0 or end_at < 0 or end_at < begin_at:
                import sys as _s
                print(f"[tier2] sentinels missing in stdout "
                      f"(begin={begin_at}, end={end_at})", file=_s.stderr)
                return []
            b64 = "".join(text[begin_at + len(BEGIN):end_at].split())
            import base64 as _b64
            raw = _b64.b64decode(b64, validate=True)
            if raw[:2] != b"\x1f\x8b":
                import sys as _s
                print(f"[tier2] decoded stream isn't gzip "
                      f"(first 8 bytes: {raw[:8]!r}, len={len(raw)})", file=_s.stderr)
                return []
            data = _io.BytesIO(raw)
            with tempfile.TemporaryDirectory() as td:
                # **tarslip defence (CVE-2007-4559)**: ``extractall(filter=...)``
                # rejects absolute paths, ``..`` traversal, dangerous link
                # targets, etc. Added in Python 3.12; the ``data`` filter is
                # the safest preset (refuses devices, FIFOs, setuid bits, and
                # any path that would escape ``td``).
                #
                # Without the filter, a compromised root on the remote could
                # ship a tar that writes to absolute paths on the laptop —
                # exactly the kind of foothold this audit is supposed to
                # prevent. With the filter, the worst a malicious snapshot
                # can do is land arbitrary file *content* inside the temp
                # dir we then read; it can't escape.
                with tarfile.open(fileobj=data, mode="r:gz") as tf:
                    try:
                        tf.extractall(td, filter="data")
                    except TypeError:
                        # Python < 3.12: re-implement the data filter
                        # manually rather than fall back to unsafe extract.
                        _safe_extract(tf, td)
                snap_dir = _P(td) / "latest"
                if not snap_dir.is_dir():
                    return []
                t2 = _t2.consume_snapshot(
                    snap_dir, host=host_obj.name,
                    lab_vm_root=(lab_vm_root or "/data/lab_vm"),
                )
                return t2.findings
        except Exception as exc:
            # Log to stderr (dashboard terminal) so silent failures
            # don't masquerade as "no tier 2 findings".
            import sys, traceback
            print(f"[tier2 fetch] {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return []

    def _safe_extract(tf, dest_dir: str) -> None:
        """Backport of tarfile's ``data`` filter for Python < 3.12.

        Refuses members whose resolved path escapes ``dest_dir`` (the
        classic tarslip pattern) plus device / FIFO / setuid entries.
        Symlinks are allowed only if their target also lands inside
        ``dest_dir`` after resolution.
        """
        import os.path as _osp
        dest_real = _osp.realpath(dest_dir)
        for member in tf.getmembers():
            # No devices, FIFOs, sockets — only regular files, dirs, symlinks.
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                continue
            # Strip setuid/setgid/sticky from the member mode.
            member.mode &= 0o777
            target = _osp.realpath(_osp.join(dest_dir, member.name))
            if not (target == dest_real or target.startswith(dest_real + os.sep)):
                continue  # tarslip — skip silently
            if member.issym() or member.islnk():
                # Resolve the link target the same way; refuse if it escapes.
                link_target = _osp.realpath(_osp.join(_osp.dirname(target), member.linkname))
                if not (link_target == dest_real or link_target.startswith(dest_real + os.sep)):
                    continue
            tf.extract(member, dest_dir)

    @app.get("/api/security/findings")
    @_scoped_to_viewer
    def security_findings_endpoint(
        host: str = Query(..., description="Registered host name."),
        refresh: bool = Query(False, description="Re-run the scan now."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Return security findings for ``host``.

        Default behaviour: read the latest cached JSONL from
        ``~/.murmurent/security/<host>/latest.jsonl``. With ``refresh=1``
        runs a fresh scan over SSH first (can take 20s+ on lab-server).

        Gated by ``lab_sudo`` (set via ``/api/members/<h>/lab_sudo``) or
        by being the PI. Regular members hit /api/security/personal for
        their own slice instead.
        """
        from ..core import hosts as _hosts
        from ..core import membership as _m
        from ..core import security_remote as _sr
        from ..core.security_findings import read_jsonl
        from pathlib import Path as _P
        import datetime as _dt2

        actor = _resolve_actor(user)
        _require_active(actor)
        # Gate: PI or lab_sudo
        try:
            rec = _m.get(actor)
            meta = _m.parse_member(rec.path).path  # ensure record exists
        except Exception:
            raise HTTPException(status_code=403, detail="member not found")
        is_pi = actor.lower() == _m.pi_handle().lower()
        from ..core.frontmatter import parse_file as _pf
        meta_dict = _pf(rec.path).meta or {}
        if not (is_pi or bool(meta_dict.get("lab_sudo"))):
            raise HTTPException(
                status_code=403,
                detail="lab_sudo required (ask your PI to grant via the LabSudoPanel)",
            )

        try:
            host_obj = _hosts.resolve(host)
        except _hosts.HostNotFound:
            raise HTTPException(status_code=404, detail=f"host not registered: {host}")

        persist_dir = _P.home() / ".murmurent" / "security" / host
        latest_path = persist_dir / "latest.jsonl"
        if refresh:
            # Resolve lab from the actor's frontmatter so the scanner
            # knows which Unix group to expect (HOME-REPO-PRIVATE-01 etc.).
            lab_group = ""
            lab = str(meta_dict.get("lab") or "")
            if lab:
                lab_group = f"labgroup{lab}lab"  # convention; may not always apply
            opts = _sr.ScanOptions(
                lab_vm_root=host_obj.lab_vm_root or None,
                projects_root=host_obj.project_root or None,
                lab_group=lab_group or None,
            )
            res = _sr.scan(host_obj, opts, timeout=600)
            if not res.ssh_ok:
                raise HTTPException(status_code=502, detail=f"ssh failed: {res.ssh_error}")
            # Tier 2 merge: if the host has a snapshot dir (left by the
            # ``Run sudo dump`` button), pull it down via SSH and feed
            # its contents through the Tier 2 consumer. Failures are
            # reported as warnings — Tier 1 results still ship.
            tier2_findings: list = []
            try:
                tier2_findings = _fetch_and_consume_tier2(host_obj, lab_vm_root=host_obj.lab_vm_root)
                import sys as _s
                print(f"[tier2] consumer returned {len(tier2_findings)} findings", file=_s.stderr)
            except Exception as _exc:
                import sys as _s, traceback as _tb
                print(f"[tier2] outer exception: {type(_exc).__name__}: {_exc}", file=_s.stderr)
                _tb.print_exc(file=_s.stderr)
            # Persist
            persist_dir.mkdir(parents=True, exist_ok=True)
            date = _dt2.datetime.utcnow().strftime("%Y-%m-%d")
            target = persist_dir / f"{date}.jsonl"
            from ..core.security_findings import write_jsonl as _wj
            _wj(target, res.findings + tier2_findings)
            try:
                if latest_path.is_symlink() or latest_path.exists():
                    latest_path.unlink()
                latest_path.symlink_to(target.name)
            except OSError:
                pass
            # **Rollup Tier 1 + Tier 2 together** so the table doesn't
            # show one row per file from raw/refined (which crashed the
            # browser at hundreds of thousands of findings).
            from ..core.security_findings import rollup_by_directory
            findings = rollup_by_directory(res.findings + tier2_findings)
            import sys as _s
            print(f"[tier2] merged: {len(res.findings)} tier1 + {len(tier2_findings)} tier2 "
                  f"→ {len(findings)} after rollup", file=_s.stderr)
            generated_at = _dt2.datetime.utcnow().isoformat() + "Z"
            source = "live" + (" + tier2" if tier2_findings else "")
            progress = res.progress
        else:
            findings = read_jsonl(latest_path)
            try:
                mtime = latest_path.stat().st_mtime if latest_path.exists() else 0
                generated_at = _dt2.datetime.utcfromtimestamp(mtime).isoformat() + "Z" if mtime else ""
            except OSError:
                generated_at = ""
            source = "cache"
            progress = []
        # **Hard cap** on the response so the browser doesn't OOM even
        # in pathological cases (e.g. a future rule that emits per-file
        # without rollup support). Surfaces the cap as one final info
        # finding so the UI tells the user something was truncated.
        MAX_FINDINGS_IN_RESPONSE = 2000
        truncated = 0
        if len(findings) > MAX_FINDINGS_IN_RESPONSE:
            truncated = len(findings) - MAX_FINDINGS_IN_RESPONSE
            findings = findings[:MAX_FINDINGS_IN_RESPONSE]
        out = [f.to_dict() for f in findings]
        if truncated:
            from ..core.security_findings import Finding, SEVERITY_INFO
            out.append(Finding(
                severity=SEVERITY_INFO, category="meta",
                rule="RESPONSE-TRUNCATED-01",
                host=host, path=f"<{truncated} findings dropped>",
                current_state=f"{len(out)} returned, {truncated} dropped",
                expected_state=f"≤ {MAX_FINDINGS_IN_RESPONSE} findings",
                suggested_fix="check ~/.murmurent/security/<host>/<date>.jsonl for the full set",
                detected_at=generated_at or "",
            ).to_dict())
        return {
            "ok": True,
            "host": host,
            "generated_at": generated_at,
            "source": source,
            "findings": out,
            "progress": progress,
        }

    @app.post("/api/security/dump")
    @_scoped_to_viewer
    def security_dump_endpoint(
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Trigger the Tier-2 root-owned snapshot on a registered host.

        Runs ``ssh <host> sudo -n /opt/murmurent/lab_sec_dump.sh``. The
        ``-n`` flag means "fail rather than prompt for a password" — if
        the sudoers entry isn't installed, the caller gets a clear
        actionable error instead of a hang.

        On success, the snapshot lives at
        ``<host>:/data/lab_vm/wigamig/.snapshot/<UTC-date>/`` and is
        group-readable for the lab. The next call to
        ``GET /api/security/findings`` picks it up automatically (the
        scan path also reads the snapshot when present and merges Tier 2
        findings with Tier 1).
        """
        from ..core import hosts as _hosts
        from ..core import membership as _m
        from ..core import remote as _remote
        from ..core.frontmatter import parse_file as _pf

        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            rec = _m.get(actor)
        except _m.MemberNotFound:
            raise HTTPException(status_code=403, detail="member not found")
        is_pi = actor.lower() == _m.pi_handle().lower()
        meta = _pf(rec.path).meta or {}
        if not (is_pi or bool(meta.get("lab_sudo"))):
            raise HTTPException(status_code=403, detail="lab_sudo required")

        host_name = str(body.get("host") or "").strip()
        if not host_name:
            raise HTTPException(status_code=422, detail="host required")
        try:
            host_obj = _hosts.resolve(host_name)
        except _hosts.HostNotFound:
            raise HTTPException(status_code=404, detail=f"host not registered: {host_name}")

        remote = _remote.Remote(host_obj)
        try:
            res = remote.run(
                "sudo -n /opt/murmurent/lab_sec_dump.sh",
                check=False, timeout=600,
            )
        except _remote.RemoteError as exc:
            raise HTTPException(status_code=502, detail=f"ssh failed: {exc}")

        # ``sudo -n`` returns 1 + "a password is required" message on
        # stderr when the sudoers entry isn't installed. Translate to a
        # clear actionable error.
        if "password is required" in (res.stderr or "").lower():
            return {
                "ok": False,
                "error": "sudoers entry not installed on " + host_name,
                "remediation": (
                    "Ask your sysadmin to install "
                    "/etc/sudoers.d/murmurent_sec_dump from the template at "
                    "scripts/sudoers.d/murmurent_sec_dump in this repo. "
                    "See docs/security-dashboard.md#tier-2-setup."
                ),
                "stderr": res.stderr.strip()[:500],
            }
        if not res.ok:
            return {
                "ok": False,
                "error": f"lab_sec_dump.sh exited with rc={res.returncode}",
                "stderr": (res.stderr or "").strip()[:1000],
                "stdout": (res.stdout or "").strip()[:1000],
            }
        return {
            "ok": True,
            "host": host_name,
            "stdout": (res.stdout or "").strip(),
            "note": "Snapshot written. Click 'Re-scan (live)' to merge "
                    "Tier 2 findings into the table.",
        }

    @app.post("/api/security/agent_review")
    @_scoped_to_viewer
    def security_agent_review_endpoint(
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Run the LLM-driven security review on a project.

        Body: ``{project: str, host: str = "local", categories: [str]}``.
        ``categories`` defaults to all three (code/secrets/cc) when omitted.

        Same gate as /api/security/findings: PI or ``lab_sudo``. Merges
        the resulting findings into the host's daily JSONL with
        ``source="agent"`` so the dashboard table shows them inline
        alongside deterministic rows.

        Output: ``{ok, findings: [...], meta: {...}, errors: [...]}``.
        """
        from ..core import membership as _m
        from ..core import projects as _proj
        from ..core import security_agent_review as _agent
        from ..core.frontmatter import parse_file as _pf
        from ..core.security_findings import (
            read_jsonl, write_jsonl, rollup_by_directory,
        )
        from pathlib import Path as _P
        import datetime as _dt2

        actor = _resolve_actor(user)
        _require_active(actor)
        # PI-or-lab_sudo gate, same as findings endpoint.
        try:
            rec = _m.get(actor)
        except _m.MemberNotFound:
            raise HTTPException(status_code=403, detail="member not found")
        is_pi = actor.lower() == _m.pi_handle().lower()
        meta = _pf(rec.path).meta or {}
        if not (is_pi or bool(meta.get("lab_sudo"))):
            raise HTTPException(status_code=403, detail="lab_sudo required")

        project_name = str(body.get("project") or "").strip()
        if not project_name:
            raise HTTPException(status_code=422, detail="project required")
        host = str(body.get("host") or "local").strip()
        cats = body.get("categories") or list(_agent.CATEGORIES)
        if not isinstance(cats, list):
            raise HTTPException(status_code=422, detail="categories must be a list")

        # Resolve the project's working-tree path on the laptop. For
        # remote-only projects this would need an SSH-side review path;
        # MVP only handles local clones.
        proj_path = _proj.project_path(project_name)
        if not proj_path.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"project clone not found locally at {proj_path}",
            )

        try:
            res = _agent.review_project(
                proj_path, host=host, categories=cats,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # Persist into the host's findings file so the main table picks
        # them up. Use merge-by-id semantics: drop any prior agent-source
        # findings for this project + category set, then append the new
        # ones. Deterministic findings are preserved untouched.
        date = _dt2.datetime.utcnow().strftime("%Y-%m-%d")
        target = _P.home() / ".murmurent" / "security" / host / f"{date}.jsonl"
        existing = read_jsonl(target) if target.is_file() else []
        kept = [
            f for f in existing
            if not (f.source == "agent"
                    and f.project == project_name
                    and f.category in cats)
        ]
        # Run rollup again across the union so the table stays tidy.
        merged = rollup_by_directory(kept + res.findings)
        write_jsonl(target, merged)
        latest = target.parent / "latest.jsonl"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(target.name)
        except OSError:
            pass

        return {
            "ok": True,
            "findings": [f.to_dict() for f in res.findings],
            "meta": {
                "model": res.meta.model,
                "input_tokens": res.meta.input_tokens,
                "output_tokens": res.meta.output_tokens,
                "cache_hits": res.meta.cache_hits,
                "cache_misses": res.meta.cache_misses,
                "cost_estimate_usd": round(res.meta.cost_estimate_usd(), 4),
            },
            "errors": res.errors,
        }

    @app.get("/api/security/personal")
    def security_personal_endpoint(
        host: str = Query(..., description="Registered host name."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Return only the calling user's own findings (member dashboard
        view). No lab_sudo gate; readable by any active member.

        Filtering: ``owner_handle == @<actor>``. Findings without an
        ``owner_handle`` (e.g. ``POSIX-NOT-AUTHORITATIVE-01``) are
        excluded so members don't see lab-wide context they can't act on.
        """
        from ..core.security_findings import read_jsonl
        from pathlib import Path as _P

        actor = _resolve_actor(user)
        _require_active(actor)
        latest_path = _P.home() / ".murmurent" / "security" / host / "latest.jsonl"
        all_findings = read_jsonl(latest_path)
        mine = [f.to_dict() for f in all_findings
                if f.owner_handle and f.owner_handle.lstrip("@").lower() == actor.lower()]
        return {"ok": True, "host": host, "findings": mine}

    @app.post("/api/members/{handle}/lab_sudo")
    @_scoped_to_viewer
    def member_lab_sudo_endpoint(
        handle: str,
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Grant or revoke the ``lab_sudo`` flag on a lab member.

        PI-only. ``lab_sudo`` is the wigamig-level flag that gates the
        ``/security`` dashboard route. **Not** OS-level sudo on the
        target host — see docs/security-dashboard.md#tier-2-setup for
        the separate sysadmin grant flow.

        Request body: ``{"grant": true|false}``.
        """
        from ..core import membership as _m
        from . import audit_log as _audit

        actor = _require_pi(user)
        grant = bool(body.get("grant", False))
        try:
            path = _m.set_lab_sudo(handle, grant)
        except _m.MembershipError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        verb = "granted" if grant else "revoked"
        try:
            _audit.write_event(
                actor=actor, kind=f"member.lab_sudo.{verb}", project="",
                target=f"member/{handle.lstrip('@')}",
                summary=f"@{actor} {verb} lab_sudo for @{handle.lstrip('@')}",
            )
        except OSError:
            pass
        return {
            "ok": True,
            "handle": handle.lstrip("@"),
            "lab_sudo": grant,
            "path": str(path),
        }

    @app.post("/api/members/{handle}/{action}")
    @_scoped_to_viewer
    def member_status_endpoint(
        handle: str,
        action: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Activate / deactivate a member. PI only."""
        from ..core import membership as _m
        from . import audit_log as _audit

        actor = _require_pi(user)
        if action not in {"activate", "deactivate"}:
            raise HTTPException(status_code=422, detail=f"unknown action: {action}")
        new_status = _m.ACTIVE if action == "activate" else _m.INACTIVE
        try:
            rec = _m.set_status(handle, new_status, by_handle=actor)
        except _m.MemberNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _m.CannotDeactivatePI as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _m.MembershipError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _audit.write_event(
                actor=actor, kind=f"member.{action}d", project="",
                target=f"member/{rec.handle}",
                summary=f"@{actor} {action}d @{rec.handle}",
            )
        except OSError:
            pass
        report = getattr(_m, "last_report_path", None)
        return {
            "ok": True,
            "handle": rec.handle,
            "status": rec.status,
            "report": str(report) if report else None,
        }

    # -----------------------------------------------------------------
    # Project provisioning (GitHub / Slack / installation dirs)
    # -----------------------------------------------------------------

    @app.post("/api/project/{project}/provision/slack")
    def provision_slack(
        project: str,
        channel_name: str = Query("", description="Optional Slack channel name override; defaults to proj-<project>."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Create the Slack channel for a project. PI only. Idempotent.

        ``channel_name`` (optional) overrides the wigamig-conventional
        ``proj-<project>`` default — useful when the lab already has a
        channel with a different name. Empty / omitted → uses the
        stored ``slack_channel_name`` in CHARTER.md if present, else
        the default. Validation: lowercase letters / digits / ``-`` /
        ``_``, max 80 chars, must start with letter or digit.

        When the channel already exists but the bot lacks the
        ``channels:read`` scope to enumerate it, returns a structured
        409 with ``recoverable=true`` so the UI can show the "Link
        existing channel" affordance (paste the channel ID manually).
        """
        actor = _require_pi(user)
        from . import slack_notify as _notify
        override = channel_name.strip() if channel_name else None
        if override is not None:
            cleaned = _notify.normalize_channel_name(override)
            if cleaned is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"channel_name {override!r} isn't a valid Slack channel name. "
                        "Use lowercase letters / digits / '-' / '_'; max 80 chars; "
                        "must start with a letter or digit."
                    ),
                )
            override = cleaned
        try:
            channel_id = _notify.create_project_channel(project, channel_name=override)
        except _notify.SlackScopeError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "slack_scope_missing",
                    "needed": exc.needed,
                    "message": str(exc),
                    "recoverable": True,
                    "hint": (
                        f"Paste the channel ID for #{override or _notify.default_channel_name(project)} "
                        "into the 'Link existing channel' field."
                    ),
                },
            )
        if not channel_id:
            raise HTTPException(status_code=500, detail="Slack channel creation failed — check server logs")
        _notify._post(channel_id, f":rocket: Project `{project}` channel ready.")
        return {"ok": True, "channel_id": channel_id, "channel_name": override or _notify.default_channel_name(project)}

    @app.post("/api/project/{project}/link_slack_channel")
    def link_slack_channel(
        project: str,
        body: LinkSlackChannelBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Persist a known Slack channel ID for ``project`` to CHARTER.md.

        Useful when the bot can't enumerate channels (no ``channels:read``
        scope) but the user already knows the ID. Validates the ID
        looks like a Slack ID (C/G/D prefix + alphanumerics) — doesn't
        round-trip the API since the whole point of this path is that
        the API can't see the channel from the bot's side. The dashboard
        will start using the ID immediately; if it's wrong, posting will
        fail and the user can re-link.
        """
        from . import slack_notify as _notify
        import re as _re

        _require_pi(user)
        channel_id = (body.channel_id or "").strip()
        if not _re.match(r"^[CGD][A-Z0-9]{6,}$", channel_id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "channel_id must look like a Slack channel ID "
                    "(C... / G... / D... followed by 6+ alphanumerics). "
                    "Find it in Slack via channel settings → 'Copy link'."
                ),
            )
        _notify._write_charter_channel_id(project, channel_id)
        return {"ok": True, "channel_id": channel_id, "linked": True}

    @app.post("/api/project/{project}/provision/github")
    def provision_github(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Create the project's remote and push. PI only. Idempotent retry.

        Kind is read from the project's ``CHARTER.md`` frontmatter
        (``repo_kind: github|local``). Endpoint name kept for URL
        back-compat; the action is now kind-aware.
        """
        import subprocess
        from ..core.frontmatter import parse_file as _pf
        from ..commands import project_cmd as _project_cmd

        _require_pi(user)
        local_repo = Path(f"~/repos/{project}").expanduser()
        if not (local_repo / ".git").is_dir():
            raise HTTPException(status_code=404, detail=f"No local git repo at {local_repo}")
        try:
            subprocess.check_output(
                ["git", "-C", str(local_repo), "remote", "get-url", "origin"],
                stderr=subprocess.DEVNULL,
            )
            raise HTTPException(status_code=409, detail="Remote already configured")
        except subprocess.CalledProcessError:
            pass

        # Read repo_kind from CHARTER.md. Default to "github" for projects
        # created before Phase 16, which never persisted the field.
        charter = local_repo / "CHARTER.md"
        kind = "github"
        local_repo_root: str | None = None
        if charter.is_file():
            meta = _pf(charter).meta or {}
            kind = str(meta.get("repo_kind") or "github")
            local_repo_root = meta.get("local_repo_root") or None

        try:
            if kind == "local":
                if not local_repo_root:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Project '{project}' is configured for a private "
                            "bare-repo remote (repo_kind=local) but CHARTER.md "
                            "is missing the local_repo_root field that names "
                            "where bare repos live on this machine. Either "
                            "add `local_repo_root: <path>` to CHARTER.md (e.g. "
                            "`local_repo_root: /data/lab_vm/wigamig/repos` on "
                            "the lab server), or change `repo_kind:` to "
                            "`github` to use a GitHub remote instead. The "
                            "SSH-mounted bare-repo flow for laptop users is "
                            "not wired up yet — it lands with the cross-lab "
                            "multi-machine work."
                        ),
                    )
                bare = Path(local_repo_root).expanduser() / f"{project}.git"
                url = _project_cmd.ensure_remote(
                    local_repo, project, kind="local", bare_repo_path=bare,
                )
                return {"ok": True, "kind": "local", "remote": url}
            # kind="github"
            org = snap_mod._current_lab_settings().github_org or ""
            if not org:
                # Fail safe: never provision into a stranger's org.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "no GitHub org configured — set github_org in lab.md "
                        "before provisioning a GitHub remote."
                    ),
                )
            url = _project_cmd.ensure_remote(
                local_repo, project, kind="github", org=org,
            )
            if url is None:
                raise HTTPException(
                    status_code=500,
                    detail="'gh' CLI not found — install from https://cli.github.com/",
                )
            return {"ok": True, "kind": "github", "remote": url, "repo": f"{org}/{project}"}
        except HTTPException:
            raise
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode(errors="replace") or str(exc)
            raise HTTPException(status_code=500, detail=f"provisioning failed: {detail}")
        except Exception as exc:  # noqa: BLE001 — surface to the user
            raise HTTPException(status_code=500, detail=f"provisioning failed: {exc}")

    @app.post("/api/project/{project}/sync_remote")
    def sync_project_remote(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Run the full provisioning pipeline with traffic-light progress.

        Idempotent re-run of the work done at approve-time: verify the
        GitHub repo, push main, sync each project member as a
        collaborator. PI-only because it issues GitHub-side membership
        changes. Returns the same ``{probes, overall}`` shape the
        machine-settings endpoint uses, so the UI renders rows the same
        way.
        """
        from ..core import preflight as _pf
        from ..core import project_provision as _pp
        from ..core.frontmatter import parse_file as _parse
        from ..core.repo import lab_mgmt_repo_root as _lmgmt

        _require_pi(user)
        local_repo = Path(f"~/repos/{project}").expanduser()
        if not (local_repo / ".git").is_dir():
            raise HTTPException(status_code=404, detail=f"No local git repo at {local_repo}")

        # Pull repo_kind + members from CHARTER.md so the panel can
        # re-sync without re-collecting the inputs the user already gave.
        charter = local_repo / "CHARTER.md"
        kind = "github"
        local_repo_root: str | None = None
        members: list[str] = []
        if charter.is_file():
            meta = _parse(charter).meta or {}
            kind = str(meta.get("repo_kind") or "github")
            local_repo_root = meta.get("local_repo_root") or None
            members = [str(m) for m in (meta.get("members") or [])]

        from ..core import git_providers as _gpr3
        lab_settings = snap_mod._current_lab_settings()
        provider = _gpr3.find_provider(
            [_pp._GP.GitProvider(**p.model_dump()) for p in lab_settings.git_providers],
            kind,
        )
        ctx = _pp.ProvisionContext(
            project=project,
            local_repo=local_repo,
            kind=kind,
            # Empty org fails safe in provision_project_remote (emits a
            # "no GitHub org configured" probe instead of using a
            # stranger's org).
            org=lab_settings.github_org,
            bare_repo_path=(
                Path(local_repo_root).expanduser() / f"{project}.git"
                if kind == "local" and local_repo_root else None
            ),
            members=members,
            lab_mgmt_root=_lmgmt(),
            provider=provider,
            provider_id=kind,
        )
        probes = _pp.provision_project_remote(ctx)
        return {
            "ok": True,
            "project": project,
            "overall": _pf.overall_status(probes),
            "probes": [p.to_dict() for p in probes],
        }

    @app.delete("/api/installations/{project}")
    def delete_installation(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Disconnect a per-machine installation manifest.

        Removes ``~/.murmurent/installations/<project>.yaml`` (a wigamig-
        local pointer, not user data) and writes a decommission report
        listing the on-machine paths (raw/, refined/, notebook/) that
        the user may want to inspect or clean up. No files in those
        directories are touched.
        """
        import yaml
        from .snapshot import INSTALLATIONS_DIR
        from ..core import decommission as _deco

        manifest_path = INSTALLATIONS_DIR / f"{project}.yaml"
        if not manifest_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"no installation manifest for {project!r} on this machine",
            )
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            data = {}
        actor = (user or "").strip().lstrip("@") or "unknown"

        items: list[_deco.CleanupItem] = []
        if isinstance(data, dict):
            machine = (
                data.get("hostname")
                or ("this laptop" if data.get("machine_type") == "laptop" else "(unknown host)")
            )
            for k, severity in (
                ("raw_path", "private"),
                ("refined_path", "private"),
                ("notebook_path", "review"),
            ):
                v = data.get(k)
                if v:
                    items.append(_deco.CleanupItem(
                        path=f"{machine}:{v}",
                        note=f"{k.replace('_path','')} dir on the target machine. murmurent won't delete data here.",
                        severity=severity,
                    ))
            if data.get("ssh_remote") and data.get("mount_point"):
                items.append(_deco.CleanupItem(
                    path=str(data.get("mount_point")),
                    note=f"sshfs mount pointing at {data.get('ssh_remote')}; unmount if you no longer need it.",
                ))
        report = _deco.write_report(_deco.DecommissionRecord(
            kind="installation",
            name=project,
            decommissioned_by=f"@{actor}",
            cleanup_items=items,
            extra_meta={"machine": str(data.get("hostname") or "local"),
                        "member": str(data.get("member") or "")},
        ))
        manifest_path.unlink()
        # Return cleanup items inline so the UI can render a structured
        # "what you need to delete by hand" popup instead of just
        # pointing the user at the report file.
        return {
            "ok": True,
            "removed": project,
            "report": str(report),
            "cleanup_items": [
                {"path": i.path, "note": i.note, "severity": i.severity}
                for i in items
            ],
        }

    @app.post("/api/project/{project}/sync_slack_members")
    @_scoped_to_viewer
    def sync_project_slack_members(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Invite every project member to the project's Slack channel.

        Reads the project's members list from CHARTER.md + MEMBERS, looks
        up each member's email in their lab_mgmt profile, resolves the
        email to a Slack user_id, and invites the diff (members not
        already in the channel). PI only — but anyone whose membership
        in this project would be visible to them can call without harm
        because the action is idempotent. Returns a breakdown so the UI
        can show ✓/already/✗ per member.
        """
        from ..core import projects as _projects
        from ..core import membership as _mem
        from . import slack_notify as _notify

        actor = _require_pi(user)
        repo = _projects.find_project(project)
        if repo is None:
            raise HTTPException(status_code=404, detail=f"no project named {project!r}")
        summary = _projects.load_summary(repo)
        handles = [h.lstrip("@") for h in summary.members]
        email_map: dict[str, str] = {}
        for h in handles:
            try:
                rec = _mem.get(h)
            except _mem.MemberNotFound:
                continue
            email = ""
            # The MemberRecord doesn't pre-extract email; pull from the
            # member file's frontmatter directly. This keeps the
            # membership module schema-narrow.
            if rec.path and rec.path.is_file():
                try:
                    from ..core.frontmatter import parse_file as _pf
                    meta = (_pf(rec.path).meta or {})
                    contact = meta.get("contact") or {}
                    if isinstance(contact, dict):
                        email = str(contact.get("email") or "")
                except Exception:
                    email = ""
            if email:
                email_map[h.lower()] = email
        result = _notify.sync_project_channel_members(
            project, handles, member_email_map=email_map,
        )
        result["actor"] = actor
        return result

    @app.post("/api/project/{project}/archive")
    def archive_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Soft-delete (decommission) a project. PI only.

        Files on disk are NOT touched. The project's CHARTER.md frontmatter
        flips to ``status: archived`` with a timestamp; a markdown report
        is written to ``~/.murmurent/decommissions/`` listing what the user
        may want to clean up manually (working clone, GitHub repo, Slack
        channel, lab-base raw/refined dirs, etc.). Reversible via
        ``unarchive``.
        """
        from ..core import projects as _projects

        actor = _require_pi(user)
        try:
            report = _projects.archive_project(project, by_handle=actor)
        except _projects.ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "report": str(report)}

    @app.post("/api/project/{project}/delete")
    def delete_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """(9) Unified project delete. PI only (revocation needs the CRL-signing
        key, so the crypto enforces this regardless of HTTP authz).

        Revokes every project certificate (lead + members, one CRL bump),
        archives the private Slack channel, drops GitHub collaborators, flips
        the registry (and CHARTER, when one exists) to ``archived``, and writes
        a decommission report. The project disappears from the dashboard
        entirely; NO data files are deleted. Recovery is CLI-only
        (``murmurent project-unarchive`` — certs stay revoked, re-issue)."""
        from ..core import issuance as _iss
        from ..core import projects as _projects
        from ..core import revocation as _rev

        actor = _require_pi(user)
        out: dict = {"ok": True, "project": project}
        cert_deleted = False
        try:
            res = _iss.delete_project(project, by_handle=actor)
            out.update({"group": res["group"], "revoked": res["revoked"],
                        "report": res.get("report")})
            cert_deleted = True
        except (_iss.IssuanceError, _rev.RevocationError) as exc:
            out["cert_delete_error"] = str(exc)
        # CHARTER-backed projects also flip their charter status so the
        # snapshot's charter path hides them too.
        try:
            report = _projects.archive_project(project, by_handle=actor)
            out.setdefault("report", str(report))
            out["charter_archived"] = True
        except _projects.ProjectNotFound:
            out["charter_archived"] = False
        except Exception as exc:  # noqa: BLE001
            out["charter_archived"] = False
            out["charter_error"] = str(exc)
        if not cert_deleted and not out.get("charter_archived"):
            raise HTTPException(
                status_code=404,
                detail=out.get("cert_delete_error")
                or f"no project named {project!r}")
        return out

    @app.post("/api/project/{project}/cert-delete")
    def cert_delete_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """PI-only "remove project" for a cert-project: revoke every project card
        (the CRL) and archive the registry record. The Slack channel + GitHub repo
        teardown is a later phase; this handles the identity layer."""
        from ..core import issuance as _iss
        from ..core import revocation as _rev

        _require_pi(user)
        try:
            out = _iss.delete_project(project)
        except _iss.IssuanceError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except _rev.RevocationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "group": out["group"], "revoked": out["revoked"]}

    @app.post("/api/project/{project}/provision")
    def provision_cert_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """PI-only: provision a cert-project's private Slack channel + GitHub repo
        and sync both to its certified members. No-ops gracefully (reports
        missing_token / no_github_org) without a Slack token / gh."""
        from ..core import cert_provision as _cprov

        _require_pi(user)
        try:
            slack = _cprov.provision_slack(project)
            github = _cprov.provision_github(project)
        except _cprov.CertProvisionError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "slack": slack, "github": github}

    @app.post("/api/project/{project}/repos")
    def add_project_repo_endpoint(
        project: str,
        body: ProjectRepoBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """PI-only: assign a repo (code / manuscript / data / infra) to a cert
        project. Idempotent by repo name. This is how a project gains its
        manuscript repo (role=manuscript, overleaf=true) alongside its code repo."""
        from ..core import cert_projects as _cp

        _require_pi(user)
        role = (body.role or "code").strip().lower()
        if role not in _cp.VALID_REPO_ROLES:
            raise HTTPException(status_code=400,
                                detail=f"role must be one of {_cp.VALID_REPO_ROLES}")
        try:
            cp = _cp.add_repo(project, role=role, repo_name=body.repo_name,
                              host=body.host or "local", path=body.path,
                              remote_path=body.remote_path, remote_url=body.remote_url,
                              overleaf=bool(body.overleaf))
        except _cp.CertProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        # An Overleaf manuscript repo cloned locally gets the pull-first CLAUDE.md
        # note so any CC session in it follows the manuscript rules. Best-effort.
        note_written = False
        if role == "manuscript" and bool(body.overleaf) and (body.host or "local") == "local" \
                and body.path:
            from ..core import project_cc_init as _cci
            note_written = _cci.write_overleaf_manuscript_note(
                body.path, project=project, repo_name=body.repo_name)
        return {"ok": True, "project": project, "overleaf_note": note_written,
                "repos": [r.to_dict() for r in cp.repos]}

    @app.delete("/api/project/{project}/repos/{repo_name}")
    def remove_project_repo_endpoint(
        project: str,
        repo_name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """PI-only: detach a repo from a cert project. Only the project record
        changes — the clone on disk is left alone. 404 if the project or the
        named repo doesn't exist."""
        from ..core import cert_projects as _cp

        _require_pi(user)
        try:
            cp = _cp.remove_repo(project, repo_name)
        except _cp.CertProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "project": project,
                "repos": [r.to_dict() for r in cp.repos]}

    @app.post("/api/project/{project}/reconcile")
    def reconcile_cert_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
        check: bool = Query(False, description="Report drift only; make no changes."),
    ) -> dict:
        """PI-only: reconcile a cert-project's Slack channel + GitHub repo
        membership to its certified members. ``check=true`` reports drift only."""
        from ..core import cert_provision as _cprov

        _require_pi(user)
        try:
            slack = _cprov.reconcile_slack(project, apply=not check)
            github = _cprov.reconcile_github(project, apply=not check)
        except _cprov.CertProvisionError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "check": check, "slack": slack, "github": github}

    @app.post("/api/project/{project}/members")
    def add_project_member_endpoint(
        project: str,
        body: ProjectMemberBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """(7) Add a member to a project. Lead or PI only (UI gate — the crypto
        gate is that only the machine holding the delegated lead key can sign).

        One click when the member's pubkey is on the roster: their project card
        is issued, DM'd over the project's Slack workspace, and they're invited
        to the private channel. A keyless/external member returns
        ``{"ok": false, "error": "no_recorded_key"}`` — re-call with their PoP
        ``enrollment`` (they run `murmurent enroll --project <p>`)."""
        from ..core import issuance as _iss
        from ..core import project_members as _pm

        _require_project_lead(project, user)
        handle = body.handle.strip().lstrip("@")
        if not handle:
            raise HTTPException(status_code=422, detail="handle is required")
        try:
            out = _pm.add_member(project, handle, enrollment=body.enrollment,
                                 dm=body.dm)
        except (_iss.IssuanceError, _pm.ProjectMemberError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Don't ship the full bundle back to the browser unless the DM failed
        # (then the lead needs it to hand over manually).
        if out.get("ok") and (out.get("dm") or {}).get("sent"):
            out.pop("bundle", None)
        return out

    @app.delete("/api/project/{project}/members/{handle}")
    def remove_project_member_endpoint(
        project: str,
        handle: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """(7)/(8) Remove a member: revoke their project card (CRL), drop them
        from the registry, kick them from the private channel, drop GitHub
        access. Lead or PI only; refuses to remove the lead."""
        from ..core import issuance as _iss
        from ..core import project_members as _pm
        from ..core import revocation as _rev

        _require_project_lead(project, user)
        try:
            return _pm.remove_member(project, handle)
        except _pm.ProjectMemberError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except (_iss.IssuanceError, _rev.RevocationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/project/{project}/issue-certs")
    def issue_project_certs_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Batch-issue project cards to every UNCERTIFIED member with a roster
        key — the lead's one-click after importing their delegation card (the
        creator≠PI flow). Lead or PI only."""
        from ..core import cert_projects as _cp
        from ..core import issuance as _iss
        from ..core import project_members as _pm

        _require_project_lead(project, user)
        cp = _cp.get(project)
        if cp is None:
            raise HTTPException(status_code=404,
                                detail=f"no cert-project named {project!r}")
        certified = {str(c.get("handle") or "").lstrip("@").lower()
                     for c in cp.certs}
        pending = [m for m in cp.members
                   if m.lstrip("@").lower() not in certified]
        results: list[dict] = []
        for m in pending:
            try:
                out = _pm.add_member(project, m.lstrip("@"))
            except (_iss.IssuanceError, _pm.ProjectMemberError) as exc:
                results.append({"handle": m, "ok": False, "detail": str(exc)})
                continue
            results.append({"handle": m, "ok": bool(out.get("ok")),
                            "error": out.get("error"),
                            "dm": out.get("dm")})
        return {"ok": True, "project": project,
                "issued": [r for r in results if r.get("ok")],
                "failed": [r for r in results if not r.get("ok")]}

    @app.post("/api/project/{project}/provision/install")
    def provision_install(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Create raw/ and refined/ installation dirs for a project. Never overwrites existing dirs."""
        actor = _resolve_actor(user)
        _require_active(actor)
        from ..core import lab_vm as _lv
        raw = _lv.project_raw_dir(project)
        refined = _lv.project_refined_dir(project)
        created: list[str] = []
        for d in (raw, refined):
            if not d.is_dir():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))
        return {"ok": True, "created": created, "already_existed": [str(d) for d in (raw, refined) if d not in [Path(x) for x in created]]}

    # -----------------------------------------------------------------
    # Hosts (Item 3 R3 — install-target registry)
    # -----------------------------------------------------------------

    def _host_row(h) -> dict:
        return {
            "name": h.name,
            "kind": h.kind,
            "ssh_host": h.ssh_host,
            "remote_user": h.remote_user,
            "project_root": h.project_root,
            # ``wigamig_base`` is the canonical 2026-05-14 name; ``lab_vm_root``
            # is the legacy field still persisted under the old key in
            # ``~/.murmurent/hosts.yaml``. Expose both so the UI can use the new
            # name while older code that reads ``lab_vm_root`` keeps working.
            "wigamig_base": h.lab_vm_root,
            "lab_vm_root": h.lab_vm_root,
            "vault_root": h.vault_root,
            # Issue #25: personal-vault subfolders + lab-mgmt clone path so the
            # machine cards + editors resolve both vaults' locations remotely.
            "oracle_subfolder": h.oracle_subfolder,
            "notebook_subfolder": h.notebook_subfolder,
            "lab_vault_root": h.lab_vault_root,
            "mount_point": h.mount_point,
            "description": h.description,
            "scan_dirs": list(h.scan_dirs),
            "is_remote": h.is_remote(),
        }

    @app.get("/api/hosts")
    def get_hosts() -> dict:
        """Return the registered install hosts so the New Project modal
        can populate its host dropdown. The 'local' host is always present.
        """
        from ..core import hosts as _hosts
        return {"hosts": [_host_row(h) for h in _hosts.read().values()]}

    @app.post("/api/hosts")
    def post_host(body: HostAddBody) -> dict:
        """Register a new SSH host. Refuses duplicates.

        Item 3 R4: dashboard equivalent of ``murmurent host add`` so the
        user can register lab-server without dropping to a terminal.
        """
        from ..core import hosts as _hosts
        # Accept either ``wigamig_base`` (new canonical name) or
        # ``lab_vm_root`` (legacy). Prefer the new name when both are set.
        wb = body.wigamig_base if body.wigamig_base is not None else body.lab_vm_root
        host = _hosts.Host(
            name=body.name,
            kind="ssh" if body.ssh_host else "local",
            ssh_host=body.ssh_host,
            remote_user=body.remote_user,
            project_root=body.project_root,
            lab_vm_root=wb,
            vault_root=body.vault_root,
            oracle_subfolder=body.oracle_subfolder or "oracle",
            notebook_subfolder=body.notebook_subfolder or "lab-notebook",
            lab_vault_root=body.lab_vault_root,
            mount_point=body.mount_point,
            description=body.description,
            scan_dirs=tuple(body.scan_dirs),
        )
        try:
            _hosts.add(host)
        except _hosts.HostAlreadyExists as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except _hosts.HostError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "host": _host_row(host)}

    @app.delete("/api/hosts/{name}")
    def delete_host(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Disconnect a host (machine) from murmurent.

        The host's row in ``~/.murmurent/hosts.yaml`` is removed (that file
        is a local-only registry — removing the row doesn't touch
        anything on the actual machine). A decommission report is
        written to ``~/.murmurent/decommissions/`` listing the paths on
        that machine the user may want to clean up by hand (wigamig_base
        directories, vault, etc.). ``local`` cannot be removed.

        PI only — decommissioning a host is destructive (writes a report,
        drops the registry row) and must be attributed to a real actor, not
        the silent ``unknown`` default the actor label used to fall back to.
        """
        from ..core import hosts as _hosts
        from ..core import decommission as _deco

        actor = _require_pi(user).lstrip("@")

        # Capture host details BEFORE removal so the report has data.
        try:
            host = _hosts.resolve(name)
        except _hosts.HostNotFound:
            host = None
        except _hosts.HostError:
            host = None

        try:
            _hosts.remove(name)
        except _hosts.HostNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except _hosts.HostError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items: list[_deco.CleanupItem] = []
        if host is not None:
            ssh_target = (host.ssh_host or name) if host.is_remote else None
            if ssh_target:
                items.append(_deco.CleanupItem(
                    path=f"{host.remote_user + '@' if host.remote_user else ''}{ssh_target}",
                    note="SSH target — murmurent no longer reaches this machine, but your ~/.ssh/config entry is untouched.",
                ))
            if host.project_root:
                items.append(_deco.CleanupItem(
                    path=f"{ssh_target or 'localhost'}:{host.project_root}",
                    note="wigamig_base / project root on the host. Working clones live here. Inspect before deleting.",
                    severity="private",
                ))
            if host.lab_vm_root:
                items.append(_deco.CleanupItem(
                    path=f"{ssh_target or 'localhost'}:{host.lab_vm_root}",
                    note="Lab-VM root on the host (raw/, refined/). Usually retained — review per data policy.",
                    severity="private",
                ))
            if host.vault_root:
                items.append(_deco.CleanupItem(
                    path=f"{ssh_target or 'localhost'}:{host.vault_root}",
                    note="Obsidian vault path on the host (personal oracle / notebooks).",
                ))
        report = _deco.write_report(_deco.DecommissionRecord(
            kind="machine",
            name=name,
            decommissioned_by=f"@{actor}",
            cleanup_items=items,
            extra_meta={"host_kind": host.kind if host else ""},
        ))
        return {"ok": True, "removed": name, "report": str(report)}

    @app.patch("/api/hosts/{name}/scan-dirs")
    def patch_host_scan_dirs(name: str, body: HostScanDirsBody) -> dict:
        """Replace ``name``'s ``scan_dirs`` list. Each entry is either a
        ``$HOME``-relative path (``repos``, ``work/clones``) or absolute
        (``/srv/projects``). The repo-inventory scanner picks up the
        change on the next run.
        """
        from ..core import hosts as _hosts
        try:
            updated = _hosts.update_scan_dirs(name, body.scan_dirs)
        except _hosts.HostNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except _hosts.HostError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "host": _host_row(updated)}

    @app.patch("/api/hosts/{name}")
    def patch_host(name: str, body: HostUpdateBody) -> dict:
        """Update a machine's editable fields from the dashboard Machines
        editor — the same set the Add form writes (connection, Files root,
        Obsidian vault, description, Repo locations). Any field left ``None``
        is unchanged; ``name``/``kind`` are immutable."""
        from ..core import hosts as _hosts
        try:
            updated = _hosts.update_host(
                name,
                ssh_host=body.ssh_host,
                remote_user=body.remote_user,
                lab_vm_root=body.lab_vm_root,
                vault_root=body.vault_root,
                oracle_subfolder=body.oracle_subfolder,
                notebook_subfolder=body.notebook_subfolder,
                lab_vault_root=body.lab_vault_root,
                description=body.description,
                scan_dirs=(tuple(body.scan_dirs) if body.scan_dirs is not None else None),
            )
        except _hosts.HostNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except _hosts.HostError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "host": _host_row(updated)}

    @app.post("/api/hosts/{name}/test")
    def post_host_test(name: str) -> dict:
        """Run the four probes against a registered host.

        Each probe returns ``ok``, ``warn``, or ``fail``:
          - ssh (required): can we authenticate non-interactively?
          - murmurent (required): is `murmurent --version` reachable on host?
          - lab_vm (warn-only): do /data/lab_vm/{raw,refined} exist?
          - gh_auth (warn-only): is `gh auth status` happy?

        Returns a structured dict the UI can render row-by-row.
        """
        from ..core import hosts as _hosts
        from ..core import remote as _remote
        try:
            host = _hosts.resolve(name)
        except _hosts.HostNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        results: list[dict] = []
        remote = _remote.Remote(host)

        # Local hosts skip ssh — they're always reachable.
        if host.is_remote():
            res = remote.probe()
            results.append({
                "name": "ssh",
                "status": "ok" if res.ok else "fail",
                "detail": res.stderr.strip() or ("connected" if res.ok else "connection failed"),
                "required": True,
            })
            if not res.ok:
                # No point running the rest — they'll all time out.
                return {"host": name, "overall": "fail", "probes": results}
        else:
            results.append({"name": "ssh", "status": "ok", "detail": "local host", "required": True})

        try:
            version = remote.murmurent_version()
            results.append({
                "name": "murmurent",
                "status": "ok",
                "detail": version,
                "required": True,
            })
        except _remote.RemoteError as exc:
            err_text = exc.stderr.strip() or str(exc)
            results.append({
                "name": "murmurent",
                "status": "fail",
                "detail": f"{err_text} — run scripts/install_remote.sh {name}",
                "required": True,
            })

        # lab_vm dirs (warn-only)
        lab_vm = host.lab_vm_root
        try:
            res = remote.run(
                f"test -d {lab_vm}/raw && test -d {lab_vm}/refined",
                check=False, timeout=10,
            )
            results.append({
                "name": "lab_vm",
                "status": "ok" if res.ok else "warn",
                "detail": (
                    f"{lab_vm}/{{raw,refined}} present" if res.ok else
                    f"{lab_vm}/{{raw,refined}} missing — murmurent will mkdir on first project"
                ),
                "required": False,
            })
        except _remote.RemoteError as exc:
            results.append({
                "name": "lab_vm", "status": "warn",
                "detail": str(exc), "required": False,
            })

        # gh auth (warn-only)
        try:
            res = remote.run(
                "command -v gh >/dev/null 2>&1 && gh auth status 2>&1",
                check=False, timeout=15,
            )
            results.append({
                "name": "gh_auth",
                "status": "ok" if res.ok else "warn",
                "detail": (
                    "authenticated" if res.ok else
                    "run `gh auth login` on the host before --repo-kind github"
                ),
                "required": False,
            })
        except _remote.RemoteError as exc:
            results.append({
                "name": "gh_auth", "status": "warn",
                "detail": str(exc), "required": False,
            })

        required_failed = any(p["status"] == "fail" and p["required"] for p in results)
        overall = "fail" if required_failed else "ok"
        return {"host": name, "overall": overall, "probes": results}

    # -----------------------------------------------------------------
    # Login / role-selection landing (Item 1)
    # -----------------------------------------------------------------
    #
    # The Mac app icon launches the server and opens "/" — the login
    # landing page. Once the user picks a role, the page calls
    # POST /api/login/select which records the choice in the local
    # role_audit.log and redirects the browser into either /dashboard
    # (member or PI persona) or /registrar (registrar role).
    #
    # Role authority sources:
    #   - "member": handle exists in lab-mgmt/members/<handle>.md
    #               (any one of the registered labs)
    #   - "pi":     handle equals the active lab's PI_HANDLE (lab.md:pi)
    #   - "registrar": handle is listed in _registry.yaml:registrars:
    #                  (or, fallback, in the local ~/.murmurent/registrar
    #                   sentinel — legacy single-registrar installs)
    # Each /api/login/select call is appended to ~/.murmurent/role_audit.log
    # with timestamp, source IP, and whether the role was granted.

    def _resolve_roles(handle: str) -> dict[str, object]:
        from ..core import membership as _mem
        from ..core import registrar as _reg
        from ..core.repo import use_lab_mgmt_root

        norm = (handle or "").strip().lstrip("@").lower()
        if not norm:
            return {
                "handle": "",
                "is_member": False,
                "is_pi": False,
                "is_registrar": False,
                "pi_lab": None,
                "registrar_centres": [],
                "default_role": "member",
            }
        # Find which lab/core this handle belongs to (PI OR member). The
        # registry walk supports multi-lab logins — @core_lead is recognised
        # as PI of the core_lead lab even though @the_pi's lab_mgmt is the
        # default on this machine.
        match = _reg.resolve_viewer_lab_mgmt(norm)
        lab_name = match[0] if match else None
        lab_mgmt_override = match[1] if match else None

        with use_lab_mgmt_root(lab_mgmt_override):
            # member? — checked against the matched lab's members/ dir
            try:
                rec = _mem.get(norm)
                is_member = rec.status == _mem.ACTIVE
            except _mem.MemberNotFound:
                is_member = False
        # pi? — the handle leads a registered active group, LAB OR CORE.
        # A PI leads either a lab or a core; the lens is the same either
        # way (issue #18) — there is no separate core-leader login. Both
        # entry kinds carry their leader in the ``pi:`` field, so one
        # walk over labs + cores covers both.
        pi_lab_name: str | None = None
        try:
            _reg_now = _reg.read_registry()
            for _g in [*_reg_now.labs, *_reg_now.cores]:
                if _g.status == "active" and _g.pi.lstrip("@").lower() == norm:
                    pi_lab_name = _g.name
                    break
        except Exception:
            pass
        is_pi_role = pi_lab_name is not None
        # registrar? (centre-level — independent of lab)
        is_reg = _reg.is_registrar(norm)
        # default lens: highest privilege the user holds
        if is_reg:
            default = "registrar"
        elif is_pi_role:
            default = "pi"
        else:
            default = "member"  # members + unknown handles alike
        return {
            "handle": norm,
            "is_member": is_member,
            "is_pi": is_pi_role,
            "is_registrar": is_reg,
            "pi_lab": pi_lab_name or lab_name or None,
            "registrar_centres": _reg.registrars() or (
                [_reg.registrar_handle()] if _reg.registrar_handle() else []
            ),
            "default_role": default,
        }

    @app.get("/api/core/dashboard")
    def core_dashboard(
        core: str = Query(..., description="Short core id (e.g. 'biocore')."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Minimal data payload for the Core Dashboard at /core.

        Per docs/cores_plan.md §10 — Phase 1 ships the shell with
        ``identity`` + ``members`` panels. Later phases (2-5) add
        services, requests, calendar, deliverables, invoices.

        Gating: any authenticated murmurent member can fetch a core's
        public-shape data (name, leader, capabilities, contact, member
        roster). Mutating endpoints (member add/remove, fee edits) are
        gated separately to ``core_leader`` of THIS core or the
        registrar.
        """
        from ..core import registrar as _reg
        from ..core.frontmatter import parse_file as _pf

        core = (core or "").strip()
        if not core:
            raise HTTPException(status_code=422, detail="core required")
        actor = _resolve_actor(user)
        # Look up the core in the registrar's registry.
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")

        # Parse the core's own lab-mgmt/lab.md for the richer
        # frontmatter (capabilities, contact, etc.) — the centre
        # registry only carries the index summary.
        lab_md = Path(entry.lab_mgmt_path) / "lab.md"
        meta = {}
        body = ""
        if lab_md.is_file():
            parsed = _pf(lab_md)
            meta = parsed.meta or {}
            body = parsed.body or ""

        # Member roster — read the core's lab-mgmt/members/.
        members_dir = Path(entry.lab_mgmt_path) / "members"
        members: list[dict] = []
        if members_dir.is_dir():
            for mf in sorted(members_dir.glob("*.md")):
                try:
                    mmeta = (_pf(mf).meta or {})
                except Exception:
                    continue
                members.append({
                    "handle": str(mmeta.get("handle") or f"@{mf.stem}").lstrip("@"),
                    "full_name": str(mmeta.get("full_name") or mf.stem),
                    "role": str(mmeta.get("role") or "member"),
                    "status": str(mmeta.get("status") or "active"),
                })

        leader_handle = entry.pi.lstrip("@")
        is_leader = actor.lower() == leader_handle.lower()
        # Centre-wide registrar always has implicit leader rights too.
        is_registrar_role = _reg.is_registrar(actor) if actor else False
        viewer_can_admin = bool(is_leader or is_registrar_role)

        return {
            "ok": True,
            "core": {
                "name": entry.name,
                "display_name": str(meta.get("name") or entry.name),
                "kind": "core",
                "leader": entry.pi,
                "status": entry.status,
                "created": entry.created,
                "institution": meta.get("institution") or None,
                "department": meta.get("department") or None,
                "github_org": meta.get("github_org") or None,
                "slack_workspace": meta.get("slack_workspace") or None,
                "oracle_vault": meta.get("lab_oracle_vault") or None,
                "website": meta.get("website") or None,
                "contact": meta.get("contact") or {},
                "capabilities": list(meta.get("capabilities") or []),
                "service_modes": list(meta.get("service_modes") or []),
                "data_root": meta.get("data_root") or None,
                "description": (body or "").strip()[:500] or None,
            },
            "members": members,
            "viewer": {
                "handle": actor,
                "is_leader": is_leader,
                "is_registrar": is_registrar_role,
                "can_admin": viewer_can_admin,
            },
        }

    @app.get("/api/core/{core}/services")
    def core_services_list(
        core: str,
        include_retired: bool = Query(False, description="Include retired services."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """List a core's service catalog. Phase 2b of the cores rollout
        (docs/cores_plan.md §11). Readable by any authenticated murmurent
        member — a service catalog is the core's outward face; gating
        view is the wrong default. Mutation goes through the editor
        endpoints in Phase 2c."""
        from ..core import services as _svc
        from ..core import registrar as _reg
        reg = _reg.read_registry()
        if not any(c.name == core for c in reg.cores):
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        catalog = _svc.iter_services(core, include_retired=include_retired)
        return {
            "ok": True,
            "core": core,
            "count": len(catalog),
            "services": [
                {
                    "slug": s.slug,
                    "name": s.name,
                    "core": s.core,
                    "capability": s.capability,
                    "mode": s.mode,
                    "description": s.description,
                    "equipment": s.equipment,
                    "location": s.location,
                    "duration_default_min": s.duration_default_min,
                    "duration_max_min": s.duration_max_min,
                    "training_required": s.training_required,
                    "prerequisites": s.prerequisites,
                    "fee": {
                        "unit": s.fee.unit,
                        "tiers": s.fee.tiers,
                        "modifiers": s.fee.modifiers,
                    },
                    "data_deliverable": s.data_deliverable,
                    "contact": s.contact,
                    "status": s.status,
                    "created": s.created,
                }
                for s in catalog
            ],
        }

    @app.get("/api/core/{core}/training")
    def core_training_list(
        core: str,
        include_retired: bool = Query(False, description="Include retired trainings."),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """List a core's training catalog. Phase 2d. Readable by any
        authenticated murmurent member — training requirements gate
        bookings, so members need to see what's required + how to
        complete it."""
        from ..core import training as _t
        from ..core import registrar as _reg
        reg = _reg.read_registry()
        if not any(c.name == core for c in reg.cores):
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        catalog = _t.iter_trainings(core, include_retired=include_retired)
        return {
            "ok": True,
            "core": core,
            "count": len(catalog),
            "trainings": [
                {
                    "slug": t.slug,
                    "name": t.name,
                    "core": t.core,
                    "description": t.description,
                    "duration_min": t.duration_min,
                    "refresher_years": t.refresher_years,
                    "trainers": t.trainers,
                    "location": t.location,
                    "status": t.status,
                    "created": t.created,
                }
                for t in catalog
            ],
        }

    @app.get("/api/core/{core}/training_roster")
    def core_training_roster(
        core: str,
        user: str = Query(""),
    ) -> dict:
        """List every member the core has trained, with their records.
        Leader/registrar gated."""
        from ..core import registrar as _reg
        from ..core import training as _t
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        roster_dir = _t.training_roster_dir(core)
        rows: list[dict] = []
        if roster_dir.is_dir():
            for path in sorted(roster_dir.glob("*.md")):
                handle = path.stem
                trainings = _t.list_core_member_trainings(core, handle)
                rows.append({
                    "handle": f"@{handle}",
                    "trainings": [
                        {"name": r.name, "completed": r.completed,
                         "by": r.by, "valid_until": r.valid_until,
                         "is_current": r.is_current(),
                         "notes": r.notes}
                        for r in trainings
                    ],
                })
        return {"core": core, "members": rows}

    @app.post("/api/core/{core}/training/{slug}/record")
    def core_training_record(
        core: str, slug: str,
        body: dict,
        user: str = Query("", description="Trainer (must be leader or registrar)."),
    ) -> dict:
        """Leader signs a member off as trained.

        Body:
          - ``member`` (required): @handle of the trainee.
          - ``completed`` (required): ISO date the session happened.
          - ``valid_until`` (optional): ISO date the cert expires;
            defaults to ``completed`` + refresher_years (from the
            training catalog entry).
          - ``notes`` (optional): free text appended to the record.
        """
        import datetime as _dt2
        from ..core import registrar as _reg
        from ..core import training as _t
        from . import slack_notify as _notify
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        t = _t.get_training(core, slug)
        if t is None:
            raise HTTPException(status_code=404,
                detail=f"training not found: {core}/{slug}")
        member = str((body or {}).get("member") or "").strip()
        completed = str((body or {}).get("completed") or "").strip()
        if not member or not completed:
            raise HTTPException(status_code=422,
                detail="body.member and body.completed are required")
        valid_until = str((body or {}).get("valid_until") or "").strip()
        if not valid_until and t.refresher_years:
            try:
                d = _dt2.date.fromisoformat(completed)
                valid_until = (
                    d.replace(year=d.year + int(t.refresher_years))
                ).isoformat()
            except ValueError:
                pass
        path = _t.record_training(
            core=core, handle=member, training_slug=slug,
            completed=completed, by=actor,
            valid_until=valid_until,
            notes=str((body or {}).get("notes") or ""),
        )
        return {
            "ok": True, "core": core, "training_slug": slug,
            "member": member.lstrip("@").lower(),
            "completed": completed, "valid_until": valid_until,
            "path": str(path),
        }

    @app.post("/api/core/{core}/training/{slug}/request")
    def core_training_request(
        core: str, slug: str,
        body: dict | None = None,
        user: str = Query("", description="Member asking for training."),
    ) -> dict:
        """Member asks a trainer to schedule a session for ``slug``.

        No persistence — Slack message to #claude-test is the artifact;
        the trainer replies inline, runs the session, then adds the
        ``training:`` entry to the member's frontmatter to clear the
        prereq for future bookings.

        Body (optional):
          - ``note``: free-text "when works for you?" type message.
        """
        from ..core import registrar as _reg
        from ..core import training as _t
        from . import slack_notify as _notify
        body = body or {}
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        if not any(c.name == core for c in reg.cores):
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        t = _t.get_training(core, slug)
        if t is None:
            raise HTTPException(
                status_code=404,
                detail=f"training not found: {core}/{slug}",
            )
        try:
            _notify.core_training_requested(
                core=core, training_slug=t.slug, training_name=t.name,
                requester=f"@{actor}",
                trainers=list(t.trainers or []),
                location=t.location or "",
                duration_min=int(t.duration_min or 0),
                note=str(body.get("note") or ""),
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "core": core, "training_slug": t.slug,
            "trainers": t.trainers, "location": t.location,
            "duration_min": t.duration_min,
        }

    @app.get("/api/core/{core}/services/{slug}/can_book")
    def core_service_can_book(
        core: str, slug: str,
        member: str = Query(..., description="Member handle to check."),
    ) -> dict:
        """Phase 2d helper: does ``member`` satisfy the training
        prerequisites for ``core/<slug>``? Used by Phase 3's booking
        UI to greying-out the Book button when prereqs are missing.

        Returns ``{ok, reason, training_slug}``. ``ok=true`` means
        the member is cleared to book; ``ok=false`` means they need
        to complete the named training first (the reason is
        UI-presentable text)."""
        from ..core import services as _svc
        from ..core import training as _t
        from ..core import registrar as _reg
        reg = _reg.read_registry()
        if not any(c.name == core for c in reg.cores):
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        svc = _svc.get_service(core, slug)
        if svc is None:
            raise HTTPException(status_code=404, detail=f"service not found: {slug}")
        check = _t.check_service_prereqs(
            member_handle=member, service=svc,
        )
        return {
            "ok": check.ok,
            "training_slug": check.training_slug,
            "reason": check.reason,
        }

    @app.get("/api/cores/services")
    def list_cores_services(
        member: str = Query("", description="Member handle to evaluate prereqs against."),
    ) -> dict:
        """Cross-core service catalog for the member-browse panel.

        Returns one ``services`` array with all active services across
        all cores. When ``member`` is provided, each row carries a
        ``can_book`` block from training.check_service_prereqs so the
        UI can grey out the Book button without a second round-trip.
        """
        from ..core import registrar as _reg
        from ..core import services as _svc
        from ..core import training as _t
        from ..core.frontmatter import parse_file as _pf2
        out: list[dict] = []
        try:
            reg = _reg.read_registry()
            cores = list(reg.cores)
        except Exception:
            cores = []
        # display_name lives in each core's lab-mgmt/lab.md frontmatter,
        # not the registry index. Cache per-call.
        _display_cache: dict[str, str] = {}
        def _disp(core_entry) -> str:
            if core_entry.name in _display_cache:
                return _display_cache[core_entry.name]
            d = core_entry.name
            try:
                lab_md = Path(core_entry.lab_mgmt_path) / "lab.md"
                if lab_md.is_file():
                    meta = (_pf2(lab_md).meta or {})
                    d = str(meta.get("name") or core_entry.name)
            except Exception:
                pass
            _display_cache[core_entry.name] = d
            return d
        for core in cores:
            for svc in _svc.iter_services(core.name):
                if (svc.status or "active").lower() != "active":
                    continue
                row = {
                    "core": core.name,
                    "core_display_name": _disp(core),
                    "slug": svc.slug,
                    "name": svc.name,
                    "capability": svc.capability,
                    "mode": svc.mode,
                    "description": svc.description,
                    "location": svc.location,
                    "duration_default_min": svc.duration_default_min,
                    "training_required": svc.training_required,
                    "fee": {
                        "unit": svc.fee.unit,
                        "tiers": dict(svc.fee.tiers),
                        "modifiers": dict(svc.fee.modifiers),
                    },
                    "leader": core.pi,
                }
                if member:
                    check = _t.check_service_prereqs(
                        member_handle=member, service=svc,
                    )
                    row["can_book"] = {
                        "ok": check.ok,
                        "reason": check.reason,
                        "training_slug": check.training_slug,
                    }
                out.append(row)
        return {"services": out}

    @app.get("/api/member/{handle}/requests")
    def list_member_requests(
        handle: str,
        include_terminal: bool = Query(False),
    ) -> dict:
        """A member's bookings across every core they've requested from.

        Drives the 'My bookings' sub-section of the member dashboard.
        ``include_terminal=true`` reveals cancelled + completed history
        (default: only live requests).
        """
        from ..core import registrar as _reg
        from ..core import service_requests as _sr
        handle_lc = handle.lstrip("@").lower()
        out: list[dict] = []
        try:
            reg = _reg.read_registry()
            cores = [c.name for c in reg.cores]
        except Exception:
            cores = []
        for core in cores:
            for req in _sr.iter_requests(
                core, requester=f"@{handle_lc}",
                include_terminal=include_terminal,
            ):
                out.append({
                    "core": core,
                    "request_id": req.request_id,
                    "service": req.service,
                    "state": req.state,
                    "slot": {
                        "start": req.booked_slot.start,
                        "end": req.booked_slot.end,
                        "calendar_event_id": req.booked_slot.calendar_event_id,
                    },
                    "fee_at_booking": {
                        "tier": req.fee_at_booking.tier,
                        "total": req.fee_at_booking.total,
                        "unit": req.fee_at_booking.unit,
                    },
                    "requester_lab": req.requester_lab,
                    "created": req.created,
                    "updated": req.updated,
                })
        # Sort: live requests first (by slot.start asc), then terminal
        # (most-recently-updated first when included).
        live = [r for r in out if r["state"] not in ("completed", "cancelled")]
        term = [r for r in out if r["state"] in ("completed", "cancelled")]
        live.sort(key=lambda r: r["slot"]["start"] or "")
        term.sort(key=lambda r: r["updated"] or "", reverse=True)
        return {"member": f"@{handle_lc}", "requests": live + term}

    @app.post("/api/core/{core}/services/{slug}/book")
    def core_service_book(
        core: str, slug: str,
        body: dict,
        user: str = Query("", description="Booking actor; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Book a slot on ``core/<slug>`` for the calling member.

        Body:
          - ``slot``: ``{start, end, calendar_event_id?}`` (required —
            this endpoint always lands the request in ``scheduled``;
            the Calendar event ID is filled in by Phase 3c after the
            MCP create succeeds, or supplied directly when the caller
            already has one).
          - ``requester``: handle to book for. Defaults to the actor;
            non-self bookings are only allowed for core leaders /
            registrars (e.g. leader fronts a slot for a member who
            can't reach the dashboard).
          - ``requester_lab``: lab slug for billing. Defaults to the
            calling lab (``lab.load_lab_config().lab``).
          - ``tier``: fee tier key. Defaults to the first tier on the
            service. Must be present in ``service.fee.tiers`` when
            the service prices anything.
          - ``modifiers``: list of modifier keys to multiply through.
          - ``notes``: free-text brief for the core staff.

        Gates: actor must be active; training prereq must pass (the
        same check the dashboard greys the Book button with); service
        must exist and be ``active``. Fee is snapshotted at booking
        time via :func:`services.quote_fee` so later catalog edits
        don't retroactively repricing live bookings.
        """
        from ..core import lab as _lab
        from ..core import registrar as _reg
        from ..core import service_requests as _sr
        from ..core import services as _svc
        from ..core import training as _t
        from . import slack_notify as _notify

        actor = _resolve_actor(user)
        _require_active(actor)

        reg = _reg.read_registry()
        if not any(c.name == core for c in reg.cores):
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        svc = _svc.get_service(core, slug)
        if svc is None:
            raise HTTPException(status_code=404, detail=f"service not found: {slug}")
        if (svc.status or "active").lower() != "active":
            raise HTTPException(
                status_code=422,
                detail=f"service {slug!r} is not active (status={svc.status!r}).",
            )

        slot_in = body.get("slot") or {}
        start = str(slot_in.get("start") or "").strip()
        end = str(slot_in.get("end") or "").strip()
        if not start or not end:
            raise HTTPException(
                status_code=422,
                detail="slot.start and slot.end are required (ISO8601 with tz).",
            )

        requester_raw = str(body.get("requester") or actor).strip()
        requester = requester_raw.lstrip("@").lower()
        if requester != actor.lower():
            # Booking on behalf of someone else requires leader/registrar.
            entry = next((c for c in reg.cores if c.name == core), None)
            is_leader = bool(entry) and entry.pi.lstrip("@").lower() == actor.lower()
            if not (is_leader or _reg.is_registrar(actor)):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"@{actor} cannot book on behalf of @{requester}; "
                        "only the core leader or a registrar can proxy-book."
                    ),
                )

        requester_lab = str(
            body.get("requester_lab") or _lab.load_lab_config().lab
        ).strip().lower()
        if not requester_lab:
            raise HTTPException(status_code=422, detail="requester_lab is required")

        # Phase 6c: validate requester_lab against the centre roster +
        # external customers. Unknown labs are allowed by default
        # (warning surfaced in response) so brand-new collaborators can
        # book before paperwork lands; the registrar can promote them
        # afterwards. Pass body.strict_lab=true to refuse unknowns.
        from ..core import lab_roster as _roster
        lab_resolution = _roster.resolve(requester_lab)
        lab_warning = ""
        if lab_resolution.kind == _roster.KIND_UNKNOWN:
            if bool(body.get("strict_lab")):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"requester_lab {requester_lab!r} is not in the "
                        "centre lab roster or external_customers/. "
                        "Register it via /api/registrar/external_customers "
                        "before booking, or omit strict_lab to proceed "
                        "with a warning."
                    ),
                )
            lab_warning = (
                f"requester_lab {requester_lab!r} is not registered; "
                "billing + data delivery may need manual routing."
            )

        check = _t.check_service_prereqs(
            member_handle=f"@{requester}", service=svc,
        )
        if not check.ok:
            raise HTTPException(status_code=422, detail=check.reason)

        # Overlap check: refuse if another scheduled/in_progress request
        # on the same service's [start, end) intersects ours. Two ranges
        # overlap iff (start < other.end) AND (other.start < end).
        import datetime as _dt2
        try:
            new_start = _dt2.datetime.fromisoformat(start)
            new_end   = _dt2.datetime.fromisoformat(end)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="slot.start / slot.end must be ISO8601 with timezone offset",
            )
        if new_end <= new_start:
            raise HTTPException(
                status_code=422, detail="slot.end must be after slot.start",
            )
        # override_conflict=true lets the leader/registrar force-book
        # when the override is intentional (e.g. proxy-booking on behalf
        # of a member who already cleared it with the other party).
        # Silently ignored for regular members.
        entry_for_perm = next((c for c in reg.cores if c.name == core), None)
        is_leader_or_reg = (
            entry_for_perm is not None
            and (entry_for_perm.pi.lstrip("@").lower() == actor.lower()
                 or _reg.is_registrar(actor))
        )
        if not (bool(body.get("override_conflict")) and is_leader_or_reg):
            for other in _sr.iter_requests(core, include_terminal=False):
                if other.service != slug:
                    continue
                if not (other.booked_slot.start and other.booked_slot.end):
                    continue
                try:
                    o_start = _dt2.datetime.fromisoformat(other.booked_slot.start)
                    o_end   = _dt2.datetime.fromisoformat(other.booked_slot.end)
                except ValueError:
                    continue
                if new_start < o_end and o_start < new_end:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"slot conflicts with {other.requester}'s "
                            f"{other.state} booking on {slug!r} "
                            f"{other.booked_slot.start} → {other.booked_slot.end}. "
                            "Pick a different time or pass "
                            "override_conflict=true (leader/registrar only)."
                        ),
                    )

        # Fee snapshot: default to the first tier when caller didn't pick.
        tier = str(body.get("tier") or "").strip()
        modifiers = list(body.get("modifiers") or [])
        fee_snap: _sr.FeeSnapshot
        if svc.fee.tiers:
            if not tier:
                tier = sorted(svc.fee.tiers.keys())[0]
            try:
                quote = _svc.quote_fee(svc, tier=tier, modifiers=modifiers)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            fee_snap = _sr.FeeSnapshot(
                tier=str(quote["tier"]),
                unit=str(quote["unit"]),
                base=float(quote["base"]),
                modifiers_applied=list(quote["modifiers_applied"]),
                total=float(quote["total"]),
            )
        else:
            fee_snap = _sr.FeeSnapshot()

        # Synchronous Google Calendar create (Phase 3c). Never blocks the
        # booking: when the leader hasn't run `murmurent core-calendar-auth`
        # yet, or the API call fails, we record the event_id as "" and
        # surface a warning in the response. The leader can retry later
        # from their inbox.
        from ..core import calendar_google as _cal
        calendar_event_id = str(slot_in.get("calendar_event_id") or "")
        calendar_html_link = ""
        calendar_warning = ""
        if not calendar_event_id and _cal.is_connected(core):
            try:
                evt = _cal.create_event(
                    core=core,
                    summary=f"{svc.name} — @{requester}",
                    description=(
                        f"Booking via murmurent dashboard.\n"
                        f"Core: {core}  Service: {slug}\n"
                        f"Requester: @{requester} ({requester_lab} lab)\n"
                        f"Notes: {str(body.get('notes') or '')}"
                    ),
                    start_iso=start, end_iso=end,
                )
                calendar_event_id = evt.id
                calendar_html_link = evt.html_link
            except _cal.CalendarError as exc:
                calendar_warning = str(exc)
        elif not calendar_event_id:
            calendar_warning = (
                f"calendar not connected for core {core!r}; "
                f"ask the leader to run: murmurent core-calendar-auth --core {core}"
            )

        slot = _sr.BookingSlot(
            start=start, end=end,
            calendar_event_id=calendar_event_id,
        )
        try:
            req = _sr.create_request(
                core=core, service=slug,
                requester=f"@{requester}", requester_lab=requester_lab,
                booked_slot=slot, fee_at_booking=fee_snap,
                notes=str(body.get("notes") or ""),
            )
        except _sr.RequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        try:
            _notify.core_request_booked(
                core=core, slug=slug, request_id=req.request_id,
                requester=f"@{requester}", actor=actor,
                start=start, end=end, total=fee_snap.total,
            )
        except Exception:  # noqa: BLE001 - Slack must never block a booking
            pass

        return {
            "ok": True,
            "core": core,
            "service": slug,
            "request_id": req.request_id,
            "state": req.state,
            "requester": req.requester,
            "requester_lab": req.requester_lab,
            "slot": {
                "start": req.booked_slot.start,
                "end": req.booked_slot.end,
                "calendar_event_id": req.booked_slot.calendar_event_id,
            },
            "fee_at_booking": {
                "tier": fee_snap.tier,
                "unit": fee_snap.unit,
                "base": fee_snap.base,
                "modifiers_applied": fee_snap.modifiers_applied,
                "total": fee_snap.total,
            },
            "calendar": {
                "event_id": calendar_event_id,
                "html_link": calendar_html_link,
                "warning": calendar_warning,
            },
            "lab_resolution": {
                "kind": lab_resolution.kind,
                "display_name": lab_resolution.display_name,
                "warning": lab_warning,
            },
            "path": str(req.path),
        }

    # ------------------------------------------------------------------
    # Phase 5b: per-job file delivery endpoints
    # ------------------------------------------------------------------

    def _require_job_actor(
        core: str, job_id: str, user: str, *, write: bool = False,
    ):
        """Resolve actor + job, gate per direction.

        - write=True  → only leader or registrar may write
        - write=False → requester (job's requester_lab), leader, registrar

        Returns (actor, manifest_dict). 404 on unknown core/job, 403 on
        permission failure.
        """
        from ..core import jobs as _jobs
        from ..core import lab as _lab
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        manifest = _jobs.read_manifest(core, job_id)
        if manifest is None:
            raise HTTPException(status_code=404,
                detail=f"job not found: {core}/{job_id}")
        is_leader = entry.pi.lstrip("@").lower() == actor.lower()
        is_reg = _reg.is_registrar(actor)
        if write:
            if not (is_leader or is_reg):
                raise HTTPException(status_code=403,
                    detail=(f"@{actor} is not the leader of {core!r} "
                            "or a registrar."))
            return actor, manifest
        # Read path: also let the requester's lab read.
        actor_lab = _lab.load_lab_config().lab.lower()
        job_lab = str(manifest.get("requester_lab") or "").lower()
        is_requester_lab = bool(actor_lab) and actor_lab == job_lab
        if not (is_leader or is_reg or is_requester_lab):
            raise HTTPException(status_code=403,
                detail=(f"@{actor} ({actor_lab}) is not in the requesting "
                        f"lab ({job_lab}), the leader, nor a registrar."))
        return actor, manifest

    @app.get("/api/core/{core}/jobs/{job_id}/manifest")
    def core_job_manifest(
        core: str, job_id: str,
        user: str = Query(""),
    ) -> dict:
        actor, manifest = _require_job_actor(core, job_id, user)
        return {"ok": True, "manifest": manifest}

    @app.get("/api/core/{core}/jobs/{job_id}/files")
    def core_job_files(
        core: str, job_id: str,
        user: str = Query(""),
    ) -> dict:
        from ..core import jobs as _jobs
        actor, _ = _require_job_actor(core, job_id, user)
        rows = _jobs.list_files(core, job_id)
        return {
            "ok": True, "core": core, "job_id": job_id,
            "files": [
                {"relpath": r.relpath, "size_bytes": r.size_bytes}
                for r in rows
            ],
        }

    @app.post("/api/core/{core}/jobs/{job_id}/files")
    def core_job_upload(
        core: str, job_id: str,
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Upload one file into a job dir. Leader/registrar only.

        Body:
          - ``relpath``: required, must resolve inside the job dir
            (no '..', no absolute). Convention: ``raw/...`` for
            instrument outputs, ``refined/...`` for deliverables.
          - ``content_base64``: required; the bytes to write.

        Multipart upload deferred to a later phase — JSON+base64 keeps
        the dashboard implementation trivial and works fine for the
        typical ITC/CD/microscope output sizes (~10MB).
        """
        import base64
        from ..core import jobs as _jobs
        actor, _ = _require_job_actor(core, job_id, user, write=True)
        relpath = str((body or {}).get("relpath") or "").strip()
        b64 = (body or {}).get("content_base64")
        if not relpath:
            raise HTTPException(status_code=422,
                detail="body.relpath is required")
        if not b64:
            raise HTTPException(status_code=422,
                detail="body.content_base64 is required")
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:
            raise HTTPException(status_code=422,
                detail="body.content_base64 is not valid base64")
        try:
            p = _jobs.write_file(core, job_id, relpath, data)
        except _jobs.JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "ok": True, "core": core, "job_id": job_id,
            "relpath": relpath,
            "size_bytes": len(data),
            "path": str(p),
        }

    @app.get("/api/core/{core}/jobs/{job_id}/bundle")
    def core_job_bundle(
        core: str, job_id: str,
        user: str = Query(""),
        max_bytes: int = Query(100 * 1024 * 1024),
        exclude_manifest: bool = Query(False),
    ):
        """Phase 7b: download the whole job dir as tar.gz. Leader,
        registrar, and requester-lab may all pull. Refuses bundles
        larger than ``max_bytes`` (default 100MB)."""
        from fastapi.responses import Response
        from ..core import jobs as _jobs
        actor, _ = _require_job_actor(core, job_id, user)
        try:
            blob = _jobs.bundle_job_tarball(
                core, job_id, exclude_manifest=exclude_manifest,
            )
        except _jobs.JobError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if len(blob) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(f"bundle is {len(blob)} bytes (> max {max_bytes}); "
                         "increase ?max_bytes= or use per-file downloads."),
            )
        return Response(
            content=blob,
            media_type="application/gzip",
            headers={"Content-Disposition":
                     f"attachment; filename=\"{job_id}.tar.gz\""},
        )

    @app.get("/api/core/{core}/jobs/{job_id}/files/{relpath:path}")
    def core_job_download(
        core: str, job_id: str, relpath: str,
        user: str = Query(""),
        max_bytes: int = Query(50 * 1024 * 1024,
            description="Refuse downloads larger than this (default 50MB)."),
    ):
        from fastapi.responses import Response
        from ..core import jobs as _jobs
        actor, _ = _require_job_actor(core, job_id, user)
        try:
            p = _jobs.safe_resolve(core, job_id, relpath)
        except _jobs.JobError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if not p.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        try:
            size = p.stat().st_size
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if size > max_bytes:
            raise HTTPException(status_code=413,
                detail=f"file too large ({size} > {max_bytes} bytes); "
                        "pass a larger ?max_bytes= or use the MCP bundle tool.")
        data = p.read_bytes()
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition":
                     f"attachment; filename=\"{p.name}\""},
        )

    @app.get("/api/lab/{lab}/core_charges")
    def lab_core_charges(
        lab: str,
        month: str = Query("", description="YYYY-MM; defaults to current month."),
    ) -> dict:
        """Phase 4d: aggregate a requesting lab's charges across every
        core for one month. Drives the PI 'Core charges this month'
        panel. No write side; safe for any viewer (the data only shows
        their lab's spend).
        """
        import datetime as _dt2
        from ..core import invoices as _inv
        from ..core import registrar as _reg
        lab_lc = lab.lstrip("@").lower()
        if not month:
            now = _dt2.datetime.now(_dt2.timezone.utc)
            month = f"{now.year:04d}-{now.month:02d}"
        try:
            reg = _reg.read_registry()
            cores = list(reg.cores)
        except Exception:
            cores = []
        per_core: list[dict] = []
        grand_total = 0.0
        grand_unconfirmed = 0
        for core in cores:
            try:
                invs = _inv.gather_invoices(core=core.name, month=month)
            except _inv.InvoiceError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            mine = next((i for i in invs if i.lab == lab_lc), None)
            if mine is None or not mine.lines:
                continue
            per_core.append({
                "core": core.name,
                "lines": len(mine.lines),
                "unconfirmed": mine.unconfirmed_count,
                "subtotal": mine.subtotal,
            })
            grand_total += mine.subtotal
            grand_unconfirmed += mine.unconfirmed_count
        return {
            "lab": lab_lc, "month": month,
            "cores": per_core,
            "total": round(grand_total, 2),
            "unconfirmed": grand_unconfirmed,
        }

    @app.get("/api/core/{core}/audit")
    def core_audit_slice(
        core: str,
        limit: int = Query(50),
        user: str = Query(""),
    ) -> dict:
        """Phase 8a: recent state-changing actions on this core, read
        from the lab_info git log. Leader/registrar gated."""
        from ..core import audit_slice as _audit
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        rows = _audit.slice_for_core(core, limit=limit)
        return {
            "core": core,
            "entries": [
                {"sha": r.sha, "iso_ts": r.iso_ts,
                 "author": r.author, "subject": r.subject}
                for r in rows
            ],
        }

    @app.get("/api/core/{core}/deliverables")
    def core_deliverables(
        core: str,
        limit: int = Query(50),
        include_terminal: bool = Query(True),
        user: str = Query(""),
    ) -> dict:
        """Phase 8b: cross-job deliverable status. Leader/registrar."""
        from ..core import deliverables as _dlv
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        rows = _dlv.overview(core=core, limit=limit,
                              include_terminal=include_terminal)
        return {
            "core": core,
            "rows": [
                {"job_id": r.job_id, "service": r.service,
                 "requester": r.requester, "requester_lab": r.requester_lab,
                 "state": r.state, "slot_start": r.slot_start,
                 "file_count": r.file_count,
                 "bytes_total": r.bytes_total,
                 "last_upload_at": r.last_upload_at,
                 "last_access_at": r.last_access_at,
                 "accessed_by": r.accessed_by}
                for r in rows
            ],
        }

    @app.get("/api/core/{core}/invoices/{month}/preview")
    def core_invoice_preview(
        core: str, month: str,
        finalised: bool = Query(False),
        user: str = Query(""),
    ) -> dict:
        """Dry-run invoice aggregation for a core/month (Phase 4c).

        Leader/registrar gated. Returns one entry per requesting lab
        with subtotal + unconfirmed count so the dashboard can render
        a summary before the user commits to writing files.
        """
        from ..core import invoices as _inv
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        try:
            invs = _inv.gather_invoices(
                core=core, month=month,
                include_unconfirmed=not finalised,
            )
        except _inv.InvoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "core": core, "month": month,
            "labs": [
                {"lab": i.lab, "lines": len(i.lines),
                 "unconfirmed": i.unconfirmed_count,
                 "subtotal": i.subtotal}
                for i in invs
            ],
            "total": round(sum(i.subtotal for i in invs), 2),
            "unconfirmed": sum(i.unconfirmed_count for i in invs),
        }

    @app.post("/api/core/{core}/invoices/{month}/generate")
    def core_invoice_generate(
        core: str, month: str,
        body: dict | None = None,
        user: str = Query(""),
    ) -> dict:
        """Write per-lab CSV + MD + summary under
        <lab_info>/cores/<core>/lab-mgmt/invoices/<month>/.

        body.finalised=true excludes rows whose actual_charge is
        unconfirmed (used for end-of-month sign-off). Leader / registrar.
        """
        from ..core import invoices as _inv
        from ..core import registrar as _reg
        from ..core.frontmatter import parse_file as _pf
        body = body or {}
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        if not (entry.pi.lstrip("@").lower() == actor.lower()
                or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not the leader of {core!r} or a registrar.")
        try:
            invs = _inv.gather_invoices(
                core=core, month=month,
                include_unconfirmed=not bool(body.get("finalised")),
            )
        except _inv.InvoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not invs:
            return {"ok": True, "core": core, "month": month,
                    "labs": [], "total": 0.0, "written": []}
        core_display = core
        try:
            lab_md = Path(entry.lab_mgmt_path) / "lab.md"
            if lab_md.is_file():
                core_display = str((_pf(lab_md).meta or {}).get("name") or core)
        except Exception:
            pass
        paths = _inv.write_invoices(
            core=core, month=month, invoices=invs,
            core_display=core_display,
        )
        return {
            "ok": True, "core": core, "month": month,
            "labs": [i.lab for i in invs],
            "total": round(sum(i.subtotal for i in invs), 2),
            "written": [str(p) for p in paths],
        }

    @app.get("/api/core/{core}/requests")
    def core_list_requests(
        core: str,
        state: str = Query("", description="Filter by state (requested/scheduled/in_progress/...)."),
        include_terminal: bool = Query(True, description="Include completed/cancelled in default view."),
        user: str = Query("", description="Actor (must be leader or registrar)."),
    ) -> dict:
        """Inbox view of every request on a core. Gated to the core
        leader OR a registrar so members can't peek at each other's
        bookings via this surface.

        Default sort: live first (scheduled, in_progress) by slot.start
        asc, then terminal (completed, cancelled) by updated desc.
        """
        from ..core import registrar as _reg
        from ..core import service_requests as _sr
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        is_leader = entry.pi.lstrip("@").lower() == actor.lower()
        is_reg = _reg.is_registrar(actor)
        if not (is_leader or is_reg):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"@{actor} is not the leader of core {core!r} or a registrar."
                ),
            )
        kwargs = {"include_terminal": include_terminal}
        if state:
            kwargs["state"] = state
        rows = []
        for req in _sr.iter_requests(core, **kwargs):
            rows.append({
                "request_id": req.request_id,
                "service": req.service,
                "requester": req.requester,
                "requester_lab": req.requester_lab,
                "state": req.state,
                "slot": {
                    "start": req.booked_slot.start,
                    "end": req.booked_slot.end,
                    "calendar_event_id": req.booked_slot.calendar_event_id,
                },
                "fee_at_booking": {
                    "tier": req.fee_at_booking.tier,
                    "total": req.fee_at_booking.total,
                    "unit": req.fee_at_booking.unit,
                },
                "notes": req.notes,
                "created": req.created,
                "updated": req.updated,
            })
        live = [r for r in rows if r["state"] not in ("completed", "cancelled")]
        term = [r for r in rows if r["state"] in ("completed", "cancelled")]
        live.sort(key=lambda r: r["slot"]["start"] or "")
        term.sort(key=lambda r: r["updated"] or "", reverse=True)
        return {"core": core, "requests": live + term,
                "counts": {"live": len(live), "terminal": len(term)}}

    def _require_request_actor(
        core: str, request_id: str, user: str, *, admin_only: bool = False,
    ) -> tuple[str, "Any"]:  # noqa: F821 - RequestSummary forward ref
        """Resolve actor + request, gate on the request's permission set.

        When ``admin_only`` is True: only core leader OR registrar may
        act (used for ``advance`` — the requester doesn't get to mark
        their own job in_progress / completed).

        When False: requester (self), core leader, and registrar all pass
        (used for ``cancel`` and ``reschedule``).

        Raises 404 / 403 with actionable messages.
        """
        from ..core import registrar as _reg
        from ..core import service_requests as _sr
        actor = _resolve_actor(user)
        _require_active(actor)
        reg = _reg.read_registry()
        entry = next((c for c in reg.cores if c.name == core), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        req = _sr.get_request(core, request_id)
        if req is None:
            raise HTTPException(
                status_code=404, detail=f"request not found: {core}/{request_id}",
            )
        is_leader = entry.pi.lstrip("@").lower() == actor.lower()
        is_reg = _reg.is_registrar(actor)
        is_requester = req.requester.lstrip("@").lower() == actor.lower()
        if admin_only:
            if not (is_leader or is_reg):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"@{actor} is not the leader of core {core!r} or a "
                        "registrar; only they may advance a request."
                    ),
                )
        else:
            if not (is_leader or is_reg or is_requester):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"@{actor} is neither the requester @{req.requester.lstrip('@')} "
                        f"nor the leader of core {core!r} nor a registrar."
                    ),
                )
        return actor, req

    @app.post("/api/core/{core}/requests/{request_id}/advance")
    def core_request_advance(
        core: str, request_id: str,
        body: dict | None = None,
        user: str = Query("", description="Actor handle."),
    ) -> dict:
        """Move a request to the next state. Leader-only.

        Default progression: scheduled -> in_progress -> completed.
        ``body.to_state`` can override (must still be a legal transition).
        ``body.note`` is appended to the request body as a timestamped
        audit entry.
        """
        from ..core import service_requests as _sr
        from . import slack_notify as _notify
        body = body or {}
        actor, req = _require_request_actor(core, request_id, user, admin_only=True)
        # Default: pick the "forward" transition (the non-cancel one).
        to_state = str(body.get("to_state") or "").strip().lower()
        if not to_state:
            allowed = _sr.ALLOWED_TRANSITIONS.get(req.state, set())
            forward = allowed - {_sr.STATE_CANCELLED}
            if not forward:
                raise HTTPException(
                    status_code=422,
                    detail=f"request is in terminal state {req.state!r}",
                )
            to_state = sorted(forward)[0]
        try:
            updated = _sr.transition_request(
                core=core, request_id=request_id,
                to_state=to_state, note=str(body.get("note") or ""),
            )
        except _sr.RequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _notify.core_request_advanced(
                core=core, request_id=request_id,
                from_state=req.state, to_state=to_state,
                requester=req.requester, actor=actor,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "core": core, "request_id": request_id,
            "from_state": req.state, "state": updated.state,
        }

    @app.post("/api/core/{core}/requests/{request_id}/cancel")
    def core_request_cancel(
        core: str, request_id: str,
        body: dict | None = None,
        user: str = Query("", description="Actor handle."),
    ) -> dict:
        """Cancel a request. Requester / leader / registrar may all act.

        Side effect: deletes the calendar event (best-effort — never
        blocks the cancel). The request file flips to ``cancelled`` and
        the body gets a timestamped audit note.
        """
        from ..core import calendar_google as _cal
        from ..core import service_requests as _sr
        from . import slack_notify as _notify
        body = body or {}
        actor, req = _require_request_actor(core, request_id, user)
        calendar_warning = ""
        evt_id = req.booked_slot.calendar_event_id
        if evt_id and _cal.is_connected(core):
            try:
                _cal.delete_event(core, evt_id)
            except _cal.CalendarError as exc:
                calendar_warning = str(exc)
        try:
            _sr.transition_request(
                core=core, request_id=request_id,
                to_state=_sr.STATE_CANCELLED,
                note=str(body.get("note") or f"cancelled by @{actor}"),
            )
        except _sr.RequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _notify.core_request_cancelled(
                core=core, request_id=request_id,
                requester=req.requester, actor=actor,
                reason=str(body.get("note") or ""),
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "core": core, "request_id": request_id,
            "state": _sr.STATE_CANCELLED,
            "calendar": {"warning": calendar_warning,
                         "deleted_event_id": evt_id if not calendar_warning else ""},
        }

    @app.patch("/api/core/{core}/requests/{request_id}/actual_charge")
    def core_request_actual_charge(
        core: str, request_id: str,
        body: dict,
        user: str = Query("", description="Actor handle (leader or registrar)."),
    ) -> dict:
        """Phase 4a: leader confirms the final billable charge for a
        request (typically called after `advance` to ``in_progress`` or
        ``completed`` but allowed in any state).

        Body:
          - ``total``: required float — the dollar amount the lab will
            be invoiced.
          - ``tier``, ``unit``, ``base``, ``modifiers_applied``:
            optional; default to the booking-time snapshot when omitted.
          - ``note``: free-text justification (overtime, sample rerun,
            …) appended to the audit trail.
        """
        from ..core import service_requests as _sr
        from . import slack_notify as _notify
        actor, req = _require_request_actor(
            core, request_id, user, admin_only=True,
        )
        if "total" not in (body or {}):
            raise HTTPException(
                status_code=422, detail="body.total is required",
            )
        try:
            total = float(body["total"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="body.total must be a number",
            )
        if total < 0:
            raise HTTPException(
                status_code=422, detail="body.total must be >= 0",
            )
        booking_fee = req.fee_at_booking
        charge = _sr.FeeSnapshot(
            tier=str(body.get("tier") or booking_fee.tier),
            unit=str(body.get("unit") or booking_fee.unit),
            base=float(body.get("base") if body.get("base") is not None
                       else booking_fee.base),
            modifiers_applied=list(
                body.get("modifiers_applied")
                if body.get("modifiers_applied") is not None
                else booking_fee.modifiers_applied
            ),
            total=total,
        )
        try:
            updated = _sr.set_actual_charge(
                core=core, request_id=request_id,
                charge=charge, confirmed_by=actor,
                note=str(body.get("note") or ""),
            )
        except _sr.RequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _notify.core_request_charge_confirmed(
                core=core, request_id=request_id,
                requester=req.requester, actor=actor,
                booked_total=booking_fee.total, actual_total=total,
                note=str(body.get("note") or ""),
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "core": core, "request_id": request_id,
            "fee_at_booking_total": booking_fee.total,
            "actual_charge": {
                "tier": charge.tier, "unit": charge.unit,
                "base": charge.base, "total": charge.total,
                "modifiers_applied": charge.modifiers_applied,
            },
            "actual_charge_confirmed_by": updated.actual_charge_confirmed_by,
            "actual_charge_confirmed_at": updated.actual_charge_confirmed_at,
        }

    @app.post("/api/core/{core}/requests/{request_id}/reschedule")
    def core_request_reschedule(
        core: str, request_id: str,
        body: dict,
        user: str = Query("", description="Actor handle."),
    ) -> dict:
        """Replace a request's slot. Requester / leader / registrar.

        Body: ``{slot: {start, end, calendar_event_id?}}``. If a calendar
        event exists for the current slot, it's deleted; a new one is
        created against the new slot (best-effort, fail-open). State is
        unchanged (still ``scheduled`` / ``in_progress``).
        """
        from ..core import calendar_google as _cal
        from ..core import service_requests as _sr
        from ..core import services as _svc
        from . import slack_notify as _notify
        actor, req = _require_request_actor(core, request_id, user)
        if req.state in _sr.TERMINAL_STATES:
            raise HTTPException(
                status_code=422,
                detail=f"request is in terminal state {req.state!r}",
            )
        slot_in = (body or {}).get("slot") or {}
        start = str(slot_in.get("start") or "").strip()
        end = str(slot_in.get("end") or "").strip()
        if not start or not end:
            raise HTTPException(
                status_code=422,
                detail="slot.start and slot.end are required",
            )
        # Calendar rotation: delete old, create new (best-effort).
        calendar_warning = ""
        new_event_id = str(slot_in.get("calendar_event_id") or "")
        new_html_link = ""
        old_event_id = req.booked_slot.calendar_event_id
        if _cal.is_connected(core):
            if old_event_id:
                try:
                    _cal.delete_event(core, old_event_id)
                except _cal.CalendarError as exc:
                    calendar_warning = f"(old event delete) {exc}"
            if not new_event_id:
                svc = _svc.get_service(core, req.service)
                summary = (
                    f"{svc.name if svc else req.service} — {req.requester}"
                )
                try:
                    evt = _cal.create_event(
                        core=core, summary=summary,
                        description=(
                            f"Rescheduled via murmurent dashboard.\n"
                            f"Request: {request_id}\n"
                            f"Requester: {req.requester} ({req.requester_lab})"
                        ),
                        start_iso=start, end_iso=end,
                    )
                    new_event_id = evt.id
                    new_html_link = evt.html_link
                except _cal.CalendarError as exc:
                    calendar_warning = (
                        (calendar_warning + " ; " if calendar_warning else "")
                        + f"(new event create) {exc}"
                    )
        new_slot = _sr.BookingSlot(
            start=start, end=end, calendar_event_id=new_event_id,
        )
        try:
            _sr.update_booking_slot(
                core=core, request_id=request_id, booked_slot=new_slot,
            )
        except _sr.RequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            _notify.core_request_rescheduled(
                core=core, request_id=request_id,
                requester=req.requester, actor=actor,
                old_start=req.booked_slot.start, new_start=start,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "core": core, "request_id": request_id,
            "slot": {"start": start, "end": end,
                     "calendar_event_id": new_event_id},
            "calendar": {"warning": calendar_warning,
                         "html_link": new_html_link},
        }

    def _require_core_admin(core: str, user: str) -> str:
        """Return the actor handle if they're allowed to mutate ``core``'s
        catalog (the core's leader OR a centre registrar). 403 otherwise.
        """
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            reg = _reg.read_registry()
            entry = next((c for c in reg.cores if c.name == core), None)
        except Exception:
            entry = None
        if entry is None:
            raise HTTPException(status_code=404, detail=f"core not found: {core}")
        is_leader = entry.pi.lstrip("@").lower() == actor.lower()
        is_reg = _reg.is_registrar(actor)
        if not (is_leader or is_reg):
            raise HTTPException(
                status_code=403,
                detail=f"@{actor} is not the leader of core {core!r} or a registrar.",
            )
        return actor

    @app.post("/api/core/{core}/services")
    def core_service_create(
        core: str,
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Add a service to the core's catalog. Gated to core leader OR
        registrar. Body matches the ServiceSummary fields (slug, name,
        capability, mode, equipment, fee, prerequisites, …).
        Phase 2c of the cores rollout (docs/cores_plan.md §11)."""
        from ..core import services as _svc
        from . import slack_notify as _notify
        actor = _require_core_admin(core, user)
        slug = str(body.get("slug") or "").strip()
        name = str(body.get("name") or "").strip()
        if not slug or not name:
            raise HTTPException(status_code=422, detail="slug and name are required")
        try:
            path = _svc.create_service(
                core=core, slug=slug, name=name,
                capability=str(body.get("capability") or ""),
                mode=str(body.get("mode") or "independent_data_collection"),
                description=str(body.get("description") or ""),
                body=str(body.get("body") or ""),
                equipment=body.get("equipment") or {},
                location=str(body.get("location") or ""),
                duration_default_min=int(body.get("duration_default_min") or 60),
                duration_max_min=int(body.get("duration_max_min") or 240),
                training_required=body.get("training_required") or None,
                prerequisites=list(body.get("prerequisites") or []),
                fee=body.get("fee") or {},
                data_deliverable=body.get("data_deliverable") or {},
                contact=body.get("contact") or {},
                status=str(body.get("status") or "active"),
            )
        except _svc.ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _notify.core_service_added(
            core=core, slug=slug, name=name, actor=actor,
        )
        return {"ok": True, "core": core, "slug": slug, "path": str(path)}

    @app.patch("/api/core/{core}/services/{slug}")
    def core_service_update(
        core: str, slug: str,
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Partial update of a service. Body is a {field: value} dict
        merged into the frontmatter (top-level keys replaced wholesale —
        send full sub-dicts for ``fee``, ``equipment``, etc.)."""
        from ..core import services as _svc
        from . import slack_notify as _notify
        actor = _require_core_admin(core, user)
        try:
            _svc.update_service(core=core, slug=slug, patch=body or {})
        except _svc.ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _notify.core_service_updated(
            core=core, slug=slug,
            fields=list((body or {}).keys()), actor=actor,
        )
        return {"ok": True, "core": core, "slug": slug,
                "fields_changed": list((body or {}).keys())}

    @app.post("/api/core/{core}/services/{slug}/archive")
    def core_service_archive(
        core: str, slug: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Flip a service to status=retired. File preserved."""
        from ..core import services as _svc
        from . import slack_notify as _notify
        actor = _require_core_admin(core, user)
        try:
            _svc.archive_service(core=core, slug=slug)
        except _svc.ServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _notify.core_service_archived(core=core, slug=slug, actor=actor)
        return {"ok": True, "core": core, "slug": slug, "status": "retired"}

    @app.get("/api/login/resolve")
    def get_login_resolve(
        user: str = Query("", description="Western netname to resolve roles for"),
    ) -> dict:
        """Return the role flags for ``user`` so the landing page knows
        which radio buttons to render. No state change."""
        handle = (user or "").strip().lstrip("@")
        if not handle:
            identity = resolve_identity(allow_unknown=True)
            handle = identity.handle if identity.source != "unknown" else ""
        return _resolve_roles(handle)

    @app.get("/api/lab/public")
    def get_lab_public() -> dict:
        """This install's lab identity — no auth, no PII. Used by the login
        page + top bar so they show the REAL lab (never a hardcoded one)."""
        try:
            ls = snap_mod._current_lab_settings()
            name = ls.name or ""
            return {
                "name": name,
                "display_name": ls.display_name or name,
                "kind": ls.kind or "lab",
            }
        except Exception:
            return {"name": "", "display_name": "", "kind": "lab"}

    @app.post("/api/login/select")
    def post_login_select(body: LoginSelectBody, request: Request) -> dict:
        """Validate (handle, role), audit-log, and return the next URL.

        The client is responsible for following the returned URL — we
        don't 302 here so that the JSON contract stays inspectable from
        tests and the page can show a friendly error on rejection.
        """
        from ..core import role_audit

        handle = (body.handle or "").strip().lstrip("@").lower()
        role = (body.role or "").strip().lower()
        if not handle:
            raise HTTPException(status_code=400, detail="handle is required")
        if role not in role_audit.VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role must be one of {sorted(role_audit.VALID_ROLES)}",
            )
        client_host = request.client.host if request.client else "unknown"
        roles = _resolve_roles(handle)
        allowed = bool(roles[f"is_{role}"]) if role != "member" else True
        # Members are not gated server-side (unknown handles still get
        # the member lens — they just won't see any projects). PI and
        # registrar both require an authoritative match.
        if not allowed:
            role_audit.record(
                handle=handle, role=role, source=client_host,
                allowed=False, reason=f"not_{role}",
            )
            raise HTTPException(
                status_code=403,
                detail=f"@{handle} is not authorised for role '{role}'.",
            )
        role_audit.record(
            handle=handle, role=role, source=client_host, allowed=True,
        )
        if body.remember_user:
            # NEVER persist a netname this machine's identity card doesn't own.
            # Members are not role-gated above (any handle gets the member lens),
            # so without this guard a typo'd/other netname would overwrite the
            # real ~/.murmurent/user and every no-?user= load would then resolve
            # to the wrong (or an unknown → refused → fake-data) identity.
            from ..core import identity_card as _idcard
            _owner = _idcard.machine_netname()
            if _owner and handle.lstrip("@").lower() != _owner:
                role_audit.record(
                    handle=handle, role=role, source=client_host,
                    allowed=False, reason="remember_user_not_owner",
                )
            else:
                try:
                    pref = Path.home() / ".murmurent" / "user"
                    pref.parent.mkdir(parents=True, exist_ok=True)
                    pref.write_text(handle + "\n", encoding="utf-8")
                except OSError:
                    pass  # not fatal — they can still proceed this session

        if role == "registrar":
            next_url = f"/registrar?user={handle}"
        elif role == "pi":
            # Lab PIs and core PIs alike — one PI lens (issue #18). The
            # /core page remains reachable from the dashboard for core
            # operations; it just isn't a login destination.
            next_url = f"/dashboard?user={handle}&persona=pi"
        else:
            next_url = f"/dashboard?user={handle}&persona=member"
        return {
            "ok": True,
            "handle": handle,
            "role": role,
            "next": next_url,
        }

    @app.get("/api/login/auth-status")
    def get_auth_status() -> dict:
        """Whether the dashboard requires a session (secret configured)."""
        from . import auth as _auth
        return {"auth_enabled": _auth.auth_enabled(),
                "cookie": _auth.COOKIE_NAME}

    @app.post("/api/login/authenticate")
    def post_login_authenticate(body: AuthenticateBody) -> JSONResponse:
        """Exchange the dashboard secret for a signed session cookie.

        Only meaningful when a secret is configured. The handle is recorded
        (and role-resolved from the registry) but, under the shared-secret
        model, is self-asserted — accountability comes from the audit log.
        Returns 401 on a bad/absent secret; 400 if auth isn't enabled.
        """
        from . import auth as _auth
        secret = _auth.configured_secret()
        if not secret:
            raise HTTPException(
                status_code=400,
                detail="dashboard auth is not enabled (no secret configured).",
            )
        if not _auth.check_secret(body.secret):
            raise HTTPException(status_code=401, detail="invalid dashboard secret")
        handle = (body.handle or "").strip().lstrip("@").lower()
        if not handle:
            raise HTTPException(status_code=400, detail="handle is required")
        roles = _resolve_roles(handle)
        role = ("registrar" if roles.get("is_registrar")
                else "pi" if roles.get("is_pi")
                else "member")
        token = _auth.mint_token(handle, role, secret)
        resp = JSONResponse({"ok": True, "handle": handle, "role": role})
        resp.set_cookie(
            _auth.COOKIE_NAME, token, max_age=_auth.DEFAULT_TTL,
            httponly=True, samesite="lax", path="/",
        )
        return resp

    @app.post("/api/login/logout")
    def post_login_logout() -> JSONResponse:
        """Clear the session cookie."""
        from . import auth as _auth
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(_auth.COOKIE_NAME, path="/")
        return resp

    # -----------------------------------------------------------------
    # SEA catalog (Phase 10)
    # -----------------------------------------------------------------

    def _resolve_actor(user: str) -> str:
        actor = (user or "").strip().lstrip("@")
        if not actor:
            identity = resolve_identity(allow_unknown=True)
            actor = identity.handle if identity.source != "unknown" else ""
        if not actor:
            raise HTTPException(status_code=400, detail="No actor resolved")
        return actor

    def _require_active(actor: str) -> None:
        """403 if ``actor`` is in members/ but flagged inactive.

        Unknown handles (no member file) are allowed through — the
        PI can be running on a fresh checkout before any members are
        seeded.
        """
        from ..core import membership as _m
        try:
            rec = _m.get(actor)
        except _m.MemberNotFound:
            return
        if rec.status != _m.ACTIVE:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"@{actor} is inactive in <lab-mgmt>/members/. "
                    f"Ask the PI to reactivate before running murmurent actions."
                ),
            )

    def _require_pi(user: str) -> str:
        from ..core.lab import pi_handle as _pi
        actor = _resolve_actor(user)
        _require_active(actor)
        if actor.lower() != _pi().lower():
            raise HTTPException(
                status_code=403,
                detail=f"only the lab PI (@{_pi()}) can perform this action",
            )
        return actor

    def _require_project_lead(project: str, user: str) -> str:
        """The actor must be the project's LEAD or the lab PI. This is the UI
        gate only — the crypto is the real one (project cards can only be
        signed by the machine holding the delegated lead key)."""
        from ..core import cert_projects as _cp
        from ..core.lab import pi_handle as _pi
        actor = _resolve_actor(user)
        _require_active(actor)
        cp = _cp.get(project)
        lead = (cp.lead if cp else "").lstrip("@").lower()
        try:
            pi = _pi().lower()
        except Exception:  # noqa: BLE001
            pi = ""
        if actor.lower() not in {lead, pi} or not actor:
            raise HTTPException(
                status_code=403,
                detail=f"only the project lead (@{lead or '?'}) or the lab PI "
                       f"can manage {project!r} membership")
        return actor

    @app.post("/api/sea_catalog")
    def catalog_upsert(
        body: CatalogEntryBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Create or update a catalog entry. PI only."""
        from ..core import sea_catalog as _catalog
        actor = _require_pi(user)
        try:
            entry = _catalog.upsert(
                slug=body.slug,
                title=body.title,
                kind=body.kind,
                contact=body.contact,
                description=body.description,
                turnaround_days=body.turnaround_days,
                prerequisites=body.prerequisites,
                accepting=body.accepting,
            )
        except _catalog.CatalogError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "entry": entry.to_meta()}

    @app.post("/api/sea_catalog/{slug}/{action}")
    def catalog_action(
        slug: str,
        action: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Toggle accepting (enable/disable) or remove (delete). PI only."""
        from ..core import sea_catalog as _catalog
        _require_pi(user)
        try:
            if action == "enable":
                entry = _catalog.set_accepting(slug, accepting=True)
                return {"ok": True, "accepting": True, "entry": entry.to_meta()}
            if action == "disable":
                entry = _catalog.set_accepting(slug, accepting=False)
                return {"ok": True, "accepting": False, "entry": entry.to_meta()}
            if action == "delete":
                _catalog.delete(slug)
                return {"ok": True, "deleted": True, "slug": slug}
        except _catalog.CatalogNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _catalog.CatalogError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        raise HTTPException(status_code=422, detail=f"unknown action: {action}")

    # -----------------------------------------------------------------
    # Inbound cross-group SEA requests (receptionist)
    # -----------------------------------------------------------------

    @app.post("/api/inbound-sea/_simulate")
    def inbound_simulate(body: SimulateInboundBody) -> dict:
        """Test hook: file a fake inbound request as if it came from
        another group's MCP. Used by the smoke test + tutorial."""
        from ..core import cross_group as _xg

        try:
            req = _xg.file_inbound(
                catalog_slug=body.catalog_slug,
                from_group=body.from_group,
                from_handle=body.from_handle,
                from_pi=body.from_pi,
                description=body.description,
            )
        except _xg.CrossGroupError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "request": req.to_meta()}

    @app.post("/api/inbound-sea/{request_id}/{action}")
    def inbound_action(
        request_id: int,
        action: str,
        body: InboundActionBody = Body(default_factory=InboundActionBody),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Accept or decline an inbound cross-group SEA. PI only."""
        from ..core import cross_group as _xg

        _require_pi(user)
        path = _xg.inbound_path(request_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"inbound #{request_id} not found")
        req = _xg.parse_inbound(path)

        try:
            if action == "accept":
                if not body.routed_to:
                    raise HTTPException(
                        status_code=422,
                        detail="accept requires routed_to (which member will own it)",
                    )
                _xg.accept_inbound(req, routed_to=body.routed_to)
            elif action == "decline":
                if not body.reason:
                    raise HTTPException(status_code=422, detail="decline requires a reason")
                _xg.decline_inbound(req, reason=body.reason)
            else:
                raise HTTPException(status_code=422, detail=f"unknown action: {action}")
        except _xg.CrossGroupError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _xg.write_inbound(req)
        return {"ok": True, "request": req.to_meta()}

    @app.post("/api/oracle/{slug}/{action}")
    @_scoped_to_viewer
    def oracle_approve_decline(
        slug: str,
        action: str,
        body: SeaActionBody = Body(default_factory=SeaActionBody),
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Approve or decline a draft oracle entry. PI only."""
        from ..core import slack_distill as _distill

        actor = _require_pi(user)

        path = lab_mgmt_repo_root() / "oracle" / f"{slug}"
        # Allow callers to pass either "<slug>" or "<slug>.md".
        if not path.suffix:
            path = path.with_suffix(".md")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"oracle entry not found: {slug}")
        if not _distill.is_draft(path):
            raise HTTPException(
                status_code=409,
                detail=f"oracle entry {slug!r} is not a draft.",
            )
        try:
            if action == "approve":
                _distill.approve_draft(path, approver=actor)
            elif action == "decline":
                if not body.reason:
                    raise HTTPException(status_code=422, detail="decline requires reason")
                _distill.decline_draft(path, reason=body.reason)
            else:
                raise HTTPException(status_code=422, detail=f"unknown action: {action}")
        except _distill.DistillError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        # Notify Slack after successful approve/decline
        try:
            parsed = _distill._parse_oracle(path)
            title = (parsed.meta or {}).get("title", slug)
        except Exception:
            title = slug
        from . import slack_notify as _notify
        _notify.oracle_approval(slug=slug, action=action, actor=actor, title=str(title))

        return {"ok": True, "slug": slug, "action": action}

    @app.post("/api/oracle/process")
    def oracle_process(
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Trigger a (stubbed) oracle distillation pass.

        v1: writes an audit row noting the request and counts the inputs
        the real distiller would consume (recent SEA conclusions, recent
        notebook entries, recent slack mirrors when those land in
        Phase 9). The actual distillation pipeline is the design in
        ``docs/slack_integration.md`` — wire-up lands in a follow-up.
        """
        from . import audit_log as _audit
        from ..core import sea as sea_core
        from ..core.projects import iter_local_projects, load_summary

        actor = _resolve_actor(user)
        _require_active(actor)

        recent_concluded = 0
        for repo in iter_local_projects():
            for s in sea_core.iter_seas(repo):
                if s.state == "concluded":
                    recent_concluded += 1

        try:
            _audit.write_event(
                actor=actor,
                kind="oracle.process_requested",
                project="",
                target="oracle/",
                summary=(
                    f"@{actor} requested oracle distillation "
                    f"({recent_concluded} concluded SEAs available as input)"
                ),
            )
        except OSError:
            pass

        return {
            "ok": True,
            "queued": True,
            "stub": True,
            "inputs": {"concluded_seas": recent_concluded},
            "next": (
                "Distillation pipeline lands in a follow-up "
                "(see docs/slack_integration.md). For now, run "
                "`murmurent publish <path> --to oracle` manually."
            ),
        }

    @app.post("/api/agents/{name}/{action}")
    def agent_toggle(
        name: str,
        action: str,
        model: str | None = Query(
            None,
            description="When action='set_model', the new model shorthand (opus|sonnet|haiku).",
        ),
    ) -> dict:
        """Manage a personal agent's frontmatter.

        Actions:
          - ``enable`` / ``disable`` — flip the ``disabled:`` flag
          - ``set_model`` — pick a model shorthand (``opus|sonnet|haiku``)

        Frozen agents (centre-controlled) cannot be modified here; they
        require a PR against the agents/ registry.
        """
        from ..core import agents as agents_core
        from ..core.repo import murmurent_repo_root

        VALID_MODELS = {"opus", "sonnet", "haiku"}
        if action not in {"enable", "disable", "set_model"}:
            raise HTTPException(status_code=422, detail=f"unknown action: {action}")
        if action == "set_model" and (not model or model not in VALID_MODELS):
            raise HTTPException(
                status_code=422,
                detail=f"set_model needs ?model={'|'.join(sorted(VALID_MODELS))}",
            )

        registry_dir = murmurent_repo_root() / "agents"
        try:
            registry = agents_core.load_registry(registry_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        match = next((a for a in registry if a.name == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"agent not found: {name}")
        if match.freeze == "frozen":
            raise HTTPException(
                status_code=403,
                detail=(
                    f"agent {name!r} is frozen (centre-controlled). "
                    f"Modify via PR against agents/{name}.md."
                ),
            )

        path = match.path
        if path is None:
            raise HTTPException(status_code=500, detail="agent path missing")
        from ..core.frontmatter import dump_document, parse_file
        parsed = parse_file(path)
        if action in {"enable", "disable"}:
            parsed.meta["disabled"] = action == "disable"
        elif action == "set_model":
            parsed.meta["model"] = model
        path.write_text(dump_document(parsed.meta, parsed.body), encoding="utf-8")
        return {
            "ok": True,
            "name": name,
            "disabled": bool(parsed.meta.get("disabled", False)),
            "model": parsed.meta.get("model"),
        }

    @app.post("/api/notebook/edit")
    def notebook_edit(
        body: NotebookEditBody = Body(default_factory=NotebookEditBody),
    ) -> dict:
        """Open the daily-note for ``body.date`` (default today) in the editor.

        Single-user, localhost: the API runs on the user's machine, so
        spawning an editor process is fine. Creates the file with a small
        template if it doesn't exist yet.
        """
        try:
            result = notebook_actions.open_entry(date_iso=body.date)
        except notebook_actions.NotebookEditorNotAvailable as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {
            "ok": True,
            "path": str(result.path),
            "cmd": result.cmd,
            "created": result.created,
        }

    # -----------------------------------------------------------------
    # Registrar (Phase A, read-only). Gated on is_registrar(); the
    # registrar's handle is the first line of ``~/.murmurent/registrar``.
    # -----------------------------------------------------------------

    @app.get("/api/registrar/dashboard", response_model=C.RegistrarResponse)
    def get_registrar_dashboard(
        user: str = Query("", description="Override the resolved user (Western username)."),
    ) -> C.RegistrarResponse:
        from ..core import registrar as _reg
        from . import registrar_snapshot as _reg_snap

        actor = _resolve_actor(user)
        if not _reg.is_registrar(actor):
            raise HTTPException(
                status_code=403,
                detail=(
                    "registrar role required; declare your handle in "
                    f"{_reg.REGISTRAR_SENTINEL} to act as registrar."
                ),
            )
        return _reg_snap.build_registrar_response(actor)

    @app.post("/api/registrar/lab")
    def registrar_create_lab(
        body: RegistrarLabCreateBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Phase B: registrar creates a new lab.

        Scaffolds the lab's lab-mgmt structure, registers it in
        ``_registry.yaml``, and commits the change to the registrar's
        git-backed data directory. Enforces the one-PI-per-lab/core
        invariant.
        """
        from ..core import registrar as _reg

        actor = _resolve_actor(user)
        if not _reg.is_registrar(actor):
            raise HTTPException(status_code=403, detail="registrar role required")

        try:
            entry = _reg.create_lab(
                name=body.name,
                display_name=body.display_name,
                pi_handle=body.pi_handle,
                pi_full_name=body.pi_full_name,
                slack_workspace=body.slack_workspace,
                github_org=body.github_org,
                oracle_vault=body.oracle_vault,
                institution=body.institution,
                department=body.department,
            )
        except _reg.InvalidLabName as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except (_reg.LabAlreadyExists, _reg.PIAlreadyLeadsAnother) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return {
            "ok": True,
            "lab": {
                "name": entry.name,
                "pi": entry.pi,
                "lab_mgmt_path": entry.lab_mgmt_path,
                "created": entry.created,
            },
        }

    def _require_registrar(user: str) -> str:
        """Resolve the actor and refuse unless they're the registrar."""
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        if not _reg.is_registrar(actor):
            raise HTTPException(status_code=403, detail="registrar role required")
        return actor

    def _lab_entry_to_dict(entry) -> dict:
        return {
            "name": entry.name,
            "pi": entry.pi,
            "lab_mgmt_path": entry.lab_mgmt_path,
            "status": entry.status,
            "slack_workspace": entry.slack_workspace,
            "github_org": entry.github_org,
            "oracle_vault": entry.oracle_vault,
        }

    @app.post("/api/registrar/lab/{name}/archive")
    def registrar_archive_lab(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Soft-delete a lab: ``status -> archived``. Files are preserved."""
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.archive_lab(name)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "lab": _lab_entry_to_dict(entry)}

    @app.post("/api/registrar/lab/{name}/unarchive")
    def registrar_unarchive_lab(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Restore an archived lab: ``status -> active``.

        Refuses if the lab's PI now leads another active lab/core.
        """
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.unarchive_lab(name)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "lab": _lab_entry_to_dict(entry)}

    def _core_entry_to_dict(entry) -> dict:
        return {
            "name": entry.name,
            "leader": entry.pi,            # surfaced under the right label
            "lab_mgmt_path": entry.lab_mgmt_path,
            "status": entry.status,
            "slack_workspace": entry.slack_workspace,
            "github_org": entry.github_org,
            "oracle_vault": entry.oracle_vault,
        }

    @app.post("/api/registrar/core")
    def registrar_create_core(
        body: RegistrarCoreCreateBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Phase E: registrar creates a new core."""
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.create_core(
                name=body.name,
                display_name=body.display_name,
                leader_handle=body.leader_handle,
                leader_full_name=body.leader_full_name,
                slack_workspace=body.slack_workspace,
                github_org=body.github_org,
                oracle_vault=body.oracle_vault,
                institution=body.institution,
                department=body.department,
            )
        except _reg.InvalidLabName as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except (_reg.LabAlreadyExists, _reg.PIAlreadyLeadsAnother) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "core": _core_entry_to_dict(entry)}

    @app.post("/api/registrar/core/{name}/archive")
    def registrar_archive_core(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.archive_core(name)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "core": _core_entry_to_dict(entry)}

    @app.post("/api/registrar/core/{name}/unarchive")
    def registrar_unarchive_core(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.unarchive_core(name)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "core": _core_entry_to_dict(entry)}

    @app.post("/api/registrar/core/{name}/edit")
    def registrar_edit_core(
        name: str,
        body: RegistrarCoreEditBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        sent = body.model_fields_set
        kwargs = {k: getattr(body, k) for k in type(body).model_fields if k in sent}
        try:
            entry = _reg.update_core_metadata(name, **kwargs)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "core": _core_entry_to_dict(entry)}

    @app.post("/api/core/{core}/settings")
    def core_settings_update(
        core: str,
        body: RegistrarCoreEditBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Core-leader equivalent of ``POST /api/lab/settings``.

        Lets the core's **leader** (not only the centre registrar) edit their
        own core's metadata. Delegates to the same ``update_core_metadata`` as
        the registrar edit route; only the authorisation differs
        (``_require_core_admin`` = leader OR registrar).
        """
        from ..core import registrar as _reg
        _require_core_admin(core, user)
        sent = body.model_fields_set
        kwargs = {k: getattr(body, k) for k in type(body).model_fields if k in sent}
        try:
            entry = _reg.update_core_metadata(core, **kwargs)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "core": _core_entry_to_dict(entry)}

    # ---- Per-core member CRUD (cores Phase 1d) -----------------------
    @app.post("/api/registrar/core/{name}/members")
    def registrar_add_core_member(
        name: str,
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Add a staff member to a core. Body: {handle, full_name, role}.
        ``role`` defaults to 'staff'. Registrar-only."""
        from ..core import registrar as _reg
        from ..core.membership import MembershipError
        from . import slack_notify as _notify
        _require_registrar(user)
        handle = str(body.get("handle") or "").strip()
        if not handle:
            raise HTTPException(status_code=422, detail="handle required")
        full_name = body.get("full_name") or None
        role = str(body.get("role") or "staff").strip() or "staff"
        try:
            path = _reg.add_core_member(
                core_name=name, handle=handle,
                full_name=full_name, role=role,
            )
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except MembershipError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _notify.core_member_added(
            core=name, handle=handle.lstrip("@"),
            full_name=full_name or handle.lstrip("@"),
            role=role,
        )
        return {"ok": True, "core": name, "handle": handle.lstrip("@"),
                "path": str(path)}

    @app.post("/api/registrar/core/{name}/members/{handle}/remove")
    def registrar_remove_core_member(
        name: str, handle: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Soft-remove (status=inactive) a core member. Refuses to remove
        the current leader. Registrar-only."""
        from ..core import registrar as _reg
        from . import slack_notify as _notify
        _require_registrar(user)
        try:
            changed = _reg.remove_core_member(core_name=name, handle=handle)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if changed:
            _notify.core_member_removed(core=name, handle=handle.lstrip("@"))
        return {"ok": True, "core": name, "handle": handle.lstrip("@"),
                "changed": changed}

    @app.post("/api/registrar/core/{name}/leader")
    def registrar_rotate_core_leader(
        name: str,
        body: dict,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Rotate a core's leader. Body: {handle, full_name (optional)}.
        Old leader demoted to ``staff`` and kept on the roster.
        Refuses if the new handle already leads another active group.
        Registrar-only."""
        from ..core import registrar as _reg
        from . import slack_notify as _notify
        _require_registrar(user)
        new_handle = str(body.get("handle") or "").strip()
        if not new_handle:
            raise HTTPException(status_code=422, detail="handle required")
        new_full_name = body.get("full_name") or None
        # Snapshot the old leader before rotation so we can include it
        # in the Slack ping.
        try:
            existing_reg = _reg.read_registry()
        except Exception:
            existing_reg = None
        old_handle = ""
        if existing_reg:
            for c in existing_reg.cores:
                if c.name == name:
                    old_handle = c.pi.lstrip("@")
                    break
        try:
            entry = _reg.rotate_core_leader(
                core_name=name, new_handle=new_handle,
                new_full_name=new_full_name,
            )
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        new_h = new_handle.lstrip("@")
        if old_handle and old_handle != new_h:
            _notify.core_leader_rotated(
                core=name, old_handle=old_handle, new_handle=new_h,
            )
        return {"ok": True, "core": name, "leader": entry.pi}

    def _collab_entry_to_dict(entry) -> dict:
        return {
            "name": entry.name,
            "pis": list(entry.pis),
            "groups": list(entry.groups),
            "member_subset": dict(entry.member_subset),
            "oracle_vault": entry.oracle_vault,
            "status": entry.status,
            "created": entry.created,
        }

    @app.post("/api/registrar/collaboration")
    def registrar_create_collaboration(
        body: RegistrarCollabCreateBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Phase D: registrar creates a cross-group collaboration."""
        from ..core import registrar as _reg

        _require_registrar(user)
        try:
            entry = _reg.create_collaboration(
                name=body.name,
                pis=body.pis,
                groups=body.groups,
                member_subset=body.member_subset,
                oracle_vault=body.oracle_vault,
            )
        except _reg.InvalidLabName as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except _reg.CollaborationAlreadyExists as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.InvalidCollaboration as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "collaboration": _collab_entry_to_dict(entry)}

    @app.post("/api/registrar/collaboration/{name}/archive")
    def registrar_archive_collaboration(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.archive_collaboration(name)
        except _reg.CollaborationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "collaboration": _collab_entry_to_dict(entry)}

    @app.post("/api/registrar/collaboration/{name}/unarchive")
    def registrar_unarchive_collaboration(
        name: str,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        try:
            entry = _reg.unarchive_collaboration(name)
        except _reg.CollaborationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.InvalidCollaboration as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "collaboration": _collab_entry_to_dict(entry)}

    @app.post("/api/registrar/collaboration/{name}/edit")
    def registrar_edit_collaboration(
        name: str,
        body: RegistrarCollabEditBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        from ..core import registrar as _reg
        _require_registrar(user)
        sent = body.model_fields_set
        kwargs = {k: getattr(body, k) for k in type(body).model_fields if k in sent}
        try:
            entry = _reg.update_collaboration(name, **kwargs)
        except _reg.CollaborationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.InvalidCollaboration as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "collaboration": _collab_entry_to_dict(entry)}

    # ── Collaboration request flow (PI proposes → registrar approves) ──
    #
    # The earlier ``/api/registrar/collaboration`` endpoint above creates
    # a collab unilaterally — registrar-driven. Item #9 in the 2026-05-14
    # testing list flipped that ownership: PIs should propose; the
    # registrar approves or declines. Requests live in
    # ``~/.murmurent/lab_info/collaboration_requests/`` (centre-scoped,
    # shared with the registrar). On approval the existing
    # ``create_collaboration`` is invoked so all the invariants run.

    @app.post("/api/collaboration/propose")
    def propose_collaboration(
        body: ProposeCollaborationBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """File a new collaboration request. Any PI may call this."""
        from ..core import collaboration_requests as _creq

        actor = _require_pi(user)
        try:
            req = _creq.file_request(
                requester=actor,
                proposed_name=body.proposed_name,
                proposed_groups=body.proposed_groups,
                proposed_pis=body.proposed_pis,
                proposed_member_subset=body.proposed_member_subset or {},
                proposed_oracle_vault=body.proposed_oracle_vault,
                justification=body.justification,
            )
        except _creq.CollabRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "id": req.id, "state": req.state}

    @app.get("/api/collaboration/requests")
    def list_collaboration_requests(
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """List collab requests. Registrar sees everything; a PI sees
        their own + any where they're a named partner. Members see only
        approved/declined records that involve their lab (read-only)."""
        from ..core import collaboration_requests as _creq
        from ..core import registrar as _reg

        handle = (user or "").strip().lstrip("@").lower()
        all_requests = _creq.iter_requests()
        is_registrar = _reg.is_registrar(handle) if handle else False
        rows: list[dict] = []
        for r in all_requests:
            requester_norm = (r.requester or "").lstrip("@").lower()
            partner_pis = {p.lstrip("@").lower() for p in r.proposed_pis}
            visible = (
                is_registrar
                or handle == requester_norm
                or handle in partner_pis
            )
            if not visible:
                continue
            rows.append({
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
        return {"requests": rows}

    @app.post("/api/registrar/collaboration_request/{req_id}/approve")
    def approve_collaboration_request(
        req_id: int,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Registrar approves a pending collab request → creates the
        collaboration entry in _registry.yaml via the existing flow."""
        from ..core import collaboration_requests as _creq
        from ..core import registrar as _reg

        actor = _require_registrar(user)
        try:
            entry = _creq.approve(req_id, by_handle=actor)
        except _creq.CollabRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _creq.CollabRequestStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "collaboration": _collab_entry_to_dict(entry)}

    @app.post("/api/registrar/collaboration_request/{req_id}/decline")
    def decline_collaboration_request(
        req_id: int,
        body: DeclineCollabRequestBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Registrar declines a pending collab request with a reason."""
        from ..core import collaboration_requests as _creq

        actor = _require_registrar(user)
        try:
            req = _creq.decline(req_id, by_handle=actor, reason=body.reason)
        except _creq.CollabRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _creq.CollabRequestStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "state": req.state}

    @app.post("/api/registrar/profile")
    def registrar_edit_profile(
        body: RegistrarProfileBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Update the registrar's centre-level profile.

        Writes to ``$MURMURENT_LAB_INFO_ROOT/registrar.md`` frontmatter.
        Partial-POST: only fields present in the body are touched;
        empty string clears a field.
        """
        from ..core import registrar as _reg

        _require_registrar(user)
        sent = body.model_fields_set
        updates = {k: getattr(body, k) for k in type(body).model_fields if k in sent}
        path = _reg.write_profile(updates)
        return {"ok": True, "path": str(path)}

    @app.post("/api/registrar/lab/{name}/edit")
    def registrar_edit_lab(
        name: str,
        body: RegistrarLabEditBody,
        user: str = Query("", description="Actor handle; falls back to $MURMURENT_USER."),
    ) -> dict:
        """Update lab metadata (display_name, PI handoff, slack, github, …).

        Renames are not supported. PI handoff re-enforces the
        one-PI-per-active-lab/core invariant.
        """
        from ..core import registrar as _reg
        _require_registrar(user)
        # Forward only fields the request actually sent (model_fields_set)
        # so a partial POST doesn't blank untouched values.
        sent = body.model_fields_set
        kwargs = {k: getattr(body, k) for k in _reg._EDITABLE_FIELDS if k in sent}
        try:
            entry = _reg.update_lab_metadata(name, **kwargs)
        except _reg.LabNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _reg.PIAlreadyLeadsAnother as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _reg.RegistrarError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "lab": _lab_entry_to_dict(entry)}

    # ------------------------------------------------------------------
    # Phase 6e: external customers CRUD (registrar-only)
    # ------------------------------------------------------------------

    def _cust_to_dict(c) -> dict:
        return {
            "id": c.id, "name": c.name, "kind": c.kind,
            "billing_contact": c.billing_contact,
            "billing_address": c.billing_address,
            "po_number": c.po_number, "tax_id": c.tax_id,
            "contact_name": c.contact_name, "status": c.status,
            "created": c.created,
            "path": str(c.path) if c.path else "",
        }

    @app.get("/api/registrar/external_customers")
    def list_external_customers(
        include_archived: bool = Query(False),
        user: str = Query(""),
    ) -> dict:
        from ..core import external_customers as _ec
        _require_registrar(user)
        return {
            "customers": [
                _cust_to_dict(c)
                for c in _ec.iter_customers(include_archived=include_archived)
            ],
        }

    @app.post("/api/registrar/external_customers")
    def create_external_customer(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        from ..core import external_customers as _ec
        _require_registrar(user)
        try:
            p = _ec.create_customer(
                id=str((body or {}).get("id") or ""),
                name=str((body or {}).get("name") or ""),
                kind=str((body or {}).get("kind") or "industry"),
                billing_contact=str((body or {}).get("billing_contact") or ""),
                billing_address=str((body or {}).get("billing_address") or ""),
                po_number=str((body or {}).get("po_number") or ""),
                tax_id=str((body or {}).get("tax_id") or ""),
                contact_name=str((body or {}).get("contact_name") or ""),
                notes=str((body or {}).get("notes") or ""),
            )
        except _ec.ExternalCustomerError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "id": str((body or {}).get("id") or "").lower(),
                "path": str(p)}

    @app.patch("/api/registrar/external_customers/{cust_id}")
    def update_external_customer(
        cust_id: str, body: dict,
        user: str = Query(""),
    ) -> dict:
        from ..core import external_customers as _ec
        _require_registrar(user)
        try:
            _ec.update_customer(id=cust_id, patch=body or {})
        except _ec.ExternalCustomerError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "id": cust_id}

    @app.post("/api/registrar/external_customers/{cust_id}/archive")
    def archive_external_customer(
        cust_id: str,
        user: str = Query(""),
    ) -> dict:
        from ..core import external_customers as _ec
        _require_registrar(user)
        try:
            _ec.archive_customer(id=cust_id)
        except _ec.ExternalCustomerError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "id": cust_id, "status": "archived"}

    @app.get("/api/lab_roster/resolve")
    def lab_roster_resolve(
        lab: str = Query(..., description="Lab id to resolve."),
    ) -> dict:
        """Public read: tells the dashboard whether a lab id is known.
        Used by the booking-modal client-side validator + the registrar
        UI's external-customer overlap check."""
        from ..core import lab_roster as _roster
        res = _roster.resolve(lab)
        return {
            "lab": res.name, "kind": res.kind,
            "display_name": res.display_name,
            "pi_or_contact": res.pi_or_contact,
            "billing_meta": res.billing_meta,
        }

    # ------------------------------------------------------------------
    # Common tools registry (centre-wide catalog of SEAs/skills/routines)
    # Any lab submits; owner_lab or registrar edits + archives.
    # ------------------------------------------------------------------

    def _sea_to_dict(t) -> dict:
        return {
            "slug": t.slug, "name": t.name, "kind": t.kind,
            "owner_lab": t.owner_lab,
            "description": t.description,
            "install": t.install, "url": t.url,
            "tags": list(t.tags), "status": t.status,
            "created": t.created,
            "notes": t.notes,
            "path": str(t.path) if t.path else "",
        }

    def _is_owner_or_registrar(actor: str, owner_lab: str) -> bool:
        """True iff actor is the PI of ``owner_lab`` or a registrar."""
        from ..core import registrar as _reg
        if _reg.is_registrar(actor):
            return True
        try:
            entries = _reg.read_registry().labs
        except Exception:
            return False
        entry = next((e for e in entries if e.name == owner_lab.lower()), None)
        return bool(entry and entry.pi.lstrip("@").lower() == actor.lower())

    @app.get("/api/common_seas")
    def public_list_common_seas(
        kind: str = Query("", description="Filter: sea|skill|routine|mcp|dataset"),
        owner_lab: str = Query("", description="Filter: lab id"),
        tag: str = Query("", description="Filter: single tag"),
        include_deprecated: bool = Query(False),
    ) -> dict:
        """Public catalog — every member's dashboard reads this."""
        from ..core import common_seas as _cs
        rows = _cs.iter_seas(
            include_deprecated=include_deprecated,
            kind=kind or None,
            owner_lab=owner_lab or None,
            tag=tag or None,
        )
        return {"seas": [_sea_to_dict(t) for t in rows]}

    @app.get("/api/common_seas/{slug}")
    def public_get_common_sea(slug: str) -> dict:
        from ..core import common_seas as _cs
        t = _cs.get_sea(slug)
        if t is None:
            raise HTTPException(status_code=404,
                                detail=f"common tool not found: {slug}")
        return _sea_to_dict(t)

    @app.post("/api/registrar/common_seas")
    def create_common_sea(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Submit a tool. Any active member of any lab may submit on
        behalf of their own lab; only registrars may submit on behalf
        of another lab (e.g. for migration / cleanup)."""
        from ..core import common_seas as _cs
        from ..core import lab as _lab
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        owner_lab = str((body or {}).get("owner_lab") or "").strip().lower()
        if not owner_lab:
            # Default to the calling member's lab.
            try:
                owner_lab = _lab.load_lab_config().lab.lower()
            except Exception:
                owner_lab = ""
        if not owner_lab:
            raise HTTPException(status_code=422,
                detail="owner_lab is required (and can't be inferred)")
        # Submitting on behalf of someone else's lab requires registrar.
        try:
            local_lab = _lab.load_lab_config().lab.lower()
        except Exception:
            local_lab = ""
        if owner_lab != local_lab and not _reg.is_registrar(actor):
            raise HTTPException(status_code=403,
                detail=(f"@{actor} can submit only on behalf of "
                        f"their own lab ({local_lab!r}); registrar "
                        "required to submit for {owner_lab!r}."))
        try:
            p = _cs.create_sea(
                slug=str((body or {}).get("slug") or ""),
                name=str((body or {}).get("name") or ""),
                kind=str((body or {}).get("kind") or ""),
                owner_lab=owner_lab,
                description=str((body or {}).get("description") or ""),
                install=str((body or {}).get("install") or ""),
                url=str((body or {}).get("url") or ""),
                tags=list((body or {}).get("tags") or []),
                notes=str((body or {}).get("notes") or ""),
            )
        except _cs.CommonSeaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True,
                "slug": str((body or {}).get("slug") or "").lower(),
                "owner_lab": owner_lab, "path": str(p)}

    @app.patch("/api/registrar/common_seas/{slug}")
    def patch_common_sea(
        slug: str, body: dict,
        user: str = Query(""),
    ) -> dict:
        """Edit a tool. Owner_lab's PI or registrar only."""
        from ..core import common_seas as _cs
        actor = _resolve_actor(user)
        _require_active(actor)
        existing = _cs.get_sea(slug)
        if existing is None:
            raise HTTPException(status_code=404,
                detail=f"common tool not found: {slug}")
        if not _is_owner_or_registrar(actor, existing.owner_lab):
            raise HTTPException(status_code=403,
                detail=(f"@{actor} is neither the PI of {existing.owner_lab!r} "
                        "nor a registrar."))
        try:
            _cs.update_sea(slug=slug, patch=body or {})
        except _cs.CommonSeaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "slug": slug}

    @app.post("/api/registrar/common_seas/{slug}/archive")
    def archive_common_sea_endpoint(
        slug: str,
        user: str = Query(""),
    ) -> dict:
        """Mark a tool deprecated. Owner_lab's PI or registrar only."""
        from ..core import common_seas as _cs
        actor = _resolve_actor(user)
        _require_active(actor)
        existing = _cs.get_sea(slug)
        if existing is None:
            raise HTTPException(status_code=404,
                detail=f"common tool not found: {slug}")
        if not _is_owner_or_registrar(actor, existing.owner_lab):
            raise HTTPException(status_code=403,
                detail=(f"@{actor} is neither the PI of {existing.owner_lab!r} "
                        "nor a registrar."))
        try:
            _cs.archive_sea(slug=slug)
        except _cs.CommonSeaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "slug": slug, "status": "deprecated"}

    # ------------------------------------------------------------------
    # Broadcasts (item 3 of post-smoke design)
    # ------------------------------------------------------------------

    def _can_broadcast(actor: str) -> bool:
        """PIs / registrars may broadcast. Members may not. v1 flattens
        admin → registrar (no separate admin concept in the registry today)."""
        from ..core import lab as _lab
        from ..core import registrar as _reg
        try:
            if _reg.is_registrar(actor):
                return True
        except Exception:
            pass
        try:
            return _lab.pi_handle().lower() == actor.lower()
        except Exception:
            return False

    @app.post("/api/broadcast")
    def post_broadcast(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Send a centre-wide broadcast. PI / registrar only."""
        from ..core import broadcasts as _bc
        actor = _resolve_actor(user)
        _require_active(actor)
        if not _can_broadcast(actor):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not a PI or registrar; "
                       "broadcasts are gated to centre-level roles.")
        audience = str((body or {}).get("audience") or "").strip().lower()
        message = str((body or {}).get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="message is required")
        try:
            b = _bc.send_broadcast(
                audience=audience, message=message, sender=actor,
                tags=list((body or {}).get("tags") or []),
            )
        except _bc.BroadcastError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "ok": True,
            "iso_ts": b.iso_ts,
            "audience": b.audience,
            "channel_id": b.channel_id,
            "sender": b.sender,
            "message_link": b.message_link,
        }

    @app.get("/api/broadcast/recent")
    def recent_broadcasts(
        limit: int = Query(20),
    ) -> dict:
        """Public read of recent broadcasts (anyone in the centre can
        audit who broadcast what to whom)."""
        from ..core import broadcasts as _bc
        rows = _bc.iter_recent(limit=limit)
        return {
            "broadcasts": [
                {"iso_ts": b.iso_ts, "audience": b.audience,
                 "channel_id": b.channel_id, "sender": b.sender,
                 "message": b.message, "message_link": b.message_link,
                 "tags": list(b.tags)}
                for b in rows
            ],
        }

    # ------------------------------------------------------------------
    # Centre projects (centre_cable_guy front door, item 0)
    # ------------------------------------------------------------------

    def _project_to_dict(r) -> dict:
        return {
            "name": r.name,
            "primary_lab": r.primary_lab,
            "members": list(r.members),
            "machines": list(r.machines),
            "github_org": r.github_org,
            "github_repo": r.github_repo,
            "slack_channel_id": r.slack_channel_id,
            "description": r.description,
            "created": r.created,
            "path": str(r.path) if r.path else "",
        }

    @app.get("/api/centre/projects")
    def centre_projects_list(user: str = Query("")) -> dict:
        from ..core import centre_provision as _cp
        return {"projects": [_project_to_dict(r) for r in _cp.iter_projects()]}

    @app.get("/api/centre/projects/{name}")
    def centre_projects_get(name: str) -> dict:
        from ..core import centre_provision as _cp
        r = _cp.get_project(name)
        if r is None:
            raise HTTPException(status_code=404, detail=f"project not found: {name}")
        return _project_to_dict(r)

    @app.post("/api/centre/projects")
    def centre_projects_upsert(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Declare or update a project's centre-side record. PI of the
        primary_lab or registrar may write."""
        from ..core import centre_provision as _cp
        from ..core import lab as _lab
        from ..core import registrar as _reg
        actor = _resolve_actor(user)
        _require_active(actor)
        primary_lab = str((body or {}).get("primary_lab") or "").strip().lower()
        if not primary_lab:
            raise HTTPException(status_code=422, detail="primary_lab is required")
        try:
            local_lab = _lab.load_lab_config().lab.lower()
        except Exception:
            local_lab = ""
        is_pi_of_primary = (
            local_lab == primary_lab
            and _lab.pi_handle().lower() == actor.lower()
        )
        if not (is_pi_of_primary or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not PI of {primary_lab!r} nor a registrar.")
        try:
            p = _cp.upsert_project(
                name=str((body or {}).get("name") or ""),
                primary_lab=primary_lab,
                members=list((body or {}).get("members") or []),
                machines=list((body or {}).get("machines") or []),
                github_org=str((body or {}).get("github_org") or ""),
                github_repo=str((body or {}).get("github_repo") or ""),
                description=str((body or {}).get("description") or ""),
            )
        except _cp.CentreProvisionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _cp.append_log(project=str((body or {}).get("name")),
                        actor=actor, action="upsert",
                        detail=f"members={len(list((body or {}).get('members') or []))}")
        return {"ok": True, "path": str(p)}

    @app.post("/api/centre/projects/{name}/reconcile")
    def centre_projects_reconcile(
        name: str, body: dict | None = None,
        user: str = Query(""),
    ) -> dict:
        """Pure-diff reconcile. Caller passes the actual state (Slack
        members / GitHub collaborators / FS ACL per machine); the
        endpoint returns the deltas. Wiring the actual-fetch (slack
        API, gh api, ssh+sudo) lives in the dashboard/centre_cable_guy
        — keeping the diff pure here makes the surface trivially
        testable + offline-runnable."""
        from ..core import centre_provision as _cp
        from ..core import registrar as _reg
        from ..core import lab as _lab
        actor = _resolve_actor(user)
        _require_active(actor)
        try:
            local_lab = _lab.load_lab_config().lab.lower()
        except Exception:
            local_lab = ""
        r = _cp.get_project(name)
        if r is None:
            raise HTTPException(status_code=404, detail=f"project not found: {name}")
        is_pi_of_primary = (
            local_lab == r.primary_lab
            and _lab.pi_handle().lower() == actor.lower()
        )
        if not (is_pi_of_primary or _reg.is_registrar(actor)):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not PI of {r.primary_lab!r} nor a registrar.")
        body = body or {}
        try:
            deltas = _cp.reconcile_project(
                project=name,
                slack_actual_members=body.get("slack_actual_members"),
                github_actual_collaborators=body.get("github_actual_collaborators"),
                fs_actual_acl=body.get("fs_actual_acl"),
            )
        except _cp.CentreProvisionError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "project": name,
            "deltas": [
                {"kind": d.kind, "severity": d.severity,
                 "summary": d.summary, "apply_hint": d.apply_hint}
                for d in deltas
            ],
        }

    # ------------------------------------------------------------------
    # Centre bootstrap (mayor flow, item 2 of post-smoke design)
    # ------------------------------------------------------------------

    def _centre_profile_to_dict(p) -> dict:
        return {
            "name": p.name,
            "institution": p.institution,
            "founding_mayor": f"@{p.founding_mayor}",
            "unique_name": p.unique_name,
            "join_email": p.join_email,
            "age_recipient": getattr(p, "age_recipient", "") or "",
            "slack_workspace": p.slack_workspace,
            "slack_invite_url": getattr(p, "slack_invite_url", "") or "",
            "github_org": p.github_org,
            "data_server": p.data_server,
            "server_host": p.server_host,
            "server_account": p.server_account,
            "cc_install_path": p.cc_install_path,
            "obsidian_vault": p.obsidian_vault,
            "mayor_root": p.mayor_root,
            "public_hub": p.public_hub,
            "raw_root": p.raw_root,
            "refined_root": p.refined_root,
            "created": p.created,
            "path": str(p.path) if p.path else "",
        }

    @app.get("/api/centre/profile")
    def get_centre_profile() -> dict:
        """Public read. 404 when no centre exists → triggers mayor wizard."""
        from ..core import centre_init as _ci
        profile = _ci.read_centre()
        if profile is None:
            raise HTTPException(status_code=404, detail="centre not initialised")
        return _centre_profile_to_dict(profile)

    @app.post("/api/centre/init")
    def post_centre_init(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Bootstrap the centre. Only callable when no centre exists.

        The user running the server becomes the founding mayor → first
        registrar (unless ``body.mayor`` overrides). Once the centre
        exists, this endpoint returns 409 forever.
        """
        from ..core import centre_init as _ci
        if _ci.is_initialised():
            raise HTTPException(
                status_code=409,
                detail="centre already initialised; use /api/centre/profile PATCH to edit.",
            )
        # Mayor resolution: explicit body > query user > $MURMURENT_USER.
        mayor = str((body or {}).get("mayor") or "").strip()
        if not mayor:
            try:
                mayor = _resolve_actor(user)
            except HTTPException:
                mayor = ""
        if not mayor:
            raise HTTPException(status_code=422,
                detail="mayor handle required (body.mayor or ?user=)")
        try:
            b = body or {}
            profile = _ci.init_centre(
                name=str(b.get("name") or ""),
                institution=str(b.get("institution") or ""),
                founding_mayor=mayor,
                unique_name=str(b.get("unique_name") or ""),
                join_email=str(b.get("join_email") or ""),
                slack_workspace=str(b.get("slack_workspace") or ""),
                github_org=str(b.get("github_org") or ""),
                data_server=str(b.get("data_server") or ""),
                server_host=str(b.get("server_host") or ""),
                server_account=str(b.get("server_account") or ""),
                cc_install_path=str(b.get("cc_install_path") or ""),
                obsidian_vault=str(b.get("obsidian_vault") or ""),
                mayor_root=str(b.get("mayor_root") or ""),
                public_hub=str(b.get("public_hub") or ""),
                raw_root=str(b.get("raw_root") or ""),
                refined_root=str(b.get("refined_root") or ""),
                # Server-mode default: skip the per-machine sentinel
                # write (Tyler's laptop did it; the server doesn't need
                # the OS-user-as-registrar identity since auth comes
                # via _registry.yaml).
                write_sentinel=bool(b.get("write_sentinel", False)),
            )
        except _ci.CentreAlreadyInitialised as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except _ci.CentreInitError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        # Best-effort: generate the age keypair now so the centre is
        # immediately join-ready (members can send encrypted join requests).
        # Non-fatal — if age isn't installed or a key already exists, skip it;
        # the mayor can run `murmurent centre-age-keygen` later. The public key
        # is stamped on the profile; the private key stays local.
        try:
            from ..core import age_crypto as _age
            if _age.age_available() and not _age.default_key_path().exists():
                recipient = _age.keygen()
                _ci.update_centre({"age_recipient": recipient})
                profile = _ci.read_centre() or profile
        except Exception:
            pass
        return {"ok": True, "profile": _centre_profile_to_dict(profile)}

    # ------------------------------------------------------------------
    # Join requests (item 2f) — public submit + registrar approve/decline
    # ------------------------------------------------------------------

    def _join_request_to_dict(r) -> dict:
        return {
            "id": r.id,
            "id_str": f"{r.id:04d}",
            "kind": r.kind,
            "state": r.state,
            "requester_email": r.requester_email,
            "proposed_name": r.proposed_name,
            "proposed_pi": r.proposed_pi,
            "institution_affiliation": r.institution_affiliation,
            "justification": r.justification,
            "proposed_members": list(r.proposed_members),
            "created_at": r.created_at,
            "resolved_at": r.resolved_at,
            "resolved_by": r.resolved_by,
            "decline_reason": r.decline_reason,
            "probes": list(r.probes),
        }

    @app.get("/api/centre/join_requests")
    def list_join_requests(
        state: str = Query(""),
        user: str = Query(""),
    ) -> dict:
        """Registrar lists all; anyone else sees their own only (matched
        by requester_email)."""
        from ..core import join_requests as _jr
        from ..core import registrar as _R
        actor = ""
        try:
            actor = _resolve_actor(user)
        except HTTPException:
            actor = ""
        is_reg = actor and _R.is_registrar(actor)
        rows = _jr.iter_requests(state=state or None)
        if not is_reg:
            # Filter to the actor's email if we can resolve it from
            # membership; otherwise return [] (the form posts back the
            # confirmation in the response, no need to expose all
            # requests anonymously).
            return {"join_requests": []}
        return {"join_requests": [_join_request_to_dict(r) for r in rows]}

    @app.post("/api/centre/join_requests")
    def post_join_request(body: dict) -> dict:
        """Public submission endpoint. No auth. Rate-limit on the
        reverse proxy in production (caddy/nginx).
        """
        from ..core import join_requests as _jr
        body = body or {}
        try:
            req = _jr.file_request(
                kind=str(body.get("kind") or ""),
                requester_email=str(body.get("requester_email") or ""),
                proposed_name=str(body.get("proposed_name") or ""),
                proposed_pi=str(body.get("proposed_pi") or ""),
                institution_affiliation=str(body.get("institution_affiliation") or ""),
                justification=str(body.get("justification") or ""),
                proposed_members=list(body.get("proposed_members") or []),
            )
        except _jr.JoinRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "id": req.id,
                "id_str": f"{req.id:04d}",
                "state": req.state,
                "message": "Your request is queued; the registrar will "
                            "reach out at "
                            f"{req.requester_email} once decided."}

    @app.post("/api/registrar/join_request/{req_id}/approve")
    def approve_join_request(
        req_id: int,
        body: dict | None = None,
        user: str = Query(""),
    ) -> dict:
        from ..core import join_requests as _jr
        from ..core import registrar as _R
        actor = _resolve_actor(user)
        _require_active(actor)
        if not _R.is_registrar(actor):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not a registrar.")
        body = body or {}
        try:
            r = _jr.approve(
                req_id=req_id, actor=actor,
                provision=bool(body.get("provision", True)),
            )
        except _jr.JoinRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _jr.JoinRequestStateError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except _jr.JoinRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "request": _join_request_to_dict(r)}

    @app.post("/api/registrar/join_request/{req_id}/decline")
    def decline_join_request(
        req_id: int,
        body: dict,
        user: str = Query(""),
    ) -> dict:
        from ..core import join_requests as _jr
        from ..core import registrar as _R
        actor = _resolve_actor(user)
        _require_active(actor)
        if not _R.is_registrar(actor):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not a registrar.")
        reason = str((body or {}).get("reason") or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail="reason is required")
        try:
            r = _jr.decline(req_id=req_id, actor=actor, reason=reason)
        except _jr.JoinRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except _jr.JoinRequestStateError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except _jr.JoinRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "request": _join_request_to_dict(r)}

    @app.get("/api/registrar/join_request/{req_id}/probes")
    def get_join_request_probes(
        req_id: int,
        user: str = Query(""),
    ) -> dict:
        """Long-poll endpoint for the registrar UI to watch provisioning
        progress on an approved request."""
        from ..core import join_requests as _jr
        from ..core import registrar as _R
        actor = _resolve_actor(user)
        if not _R.is_registrar(actor):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not a registrar.")
        try:
            r = _jr.get_request(req_id)
        except _jr.JoinRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"state": r.state, "probes": list(r.probes)}

    @app.patch("/api/centre/profile")
    def patch_centre_profile(
        body: dict,
        user: str = Query(""),
    ) -> dict:
        """Edit centre metadata after bootstrap. Registrar only.

        ``founding_mayor`` is immutable — silently dropped if present
        in the patch.
        """
        from ..core import centre_init as _ci
        actor = _resolve_actor(user)
        _require_active(actor)
        from ..core import registrar as _R
        if not _R.is_registrar(actor):
            raise HTTPException(status_code=403,
                detail=f"@{actor} is not a registrar.")
        try:
            profile = _ci.update_centre(body or {})
        except _ci.CentreInitError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "profile": _centre_profile_to_dict(profile)}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/environment/local_user")
    def environment_local_user() -> dict[str, str]:
        """Return the OS account name on the machine running the dashboard.

        Used by the installation wizard to prefill the "Local OS account"
        field when the target machine is the user's laptop — disambiguates
        from the Western netname, which is a separate concept.
        """
        import getpass
        return {"local_user": getpass.getuser()}

    @app.get("/api/environment/this_machine")
    def environment_this_machine() -> dict[str, str]:
        """Return identifying info for the machine running the dashboard.

        Used by the Machines block in Member Profile to highlight the
        current host. ``short_hostname`` is the bare name (e.g. "lab-server"
        on the lab server, "mike-mbp" on a laptop), suitable for matching
        against the user's machine list.
        """
        import getpass
        import platform
        import socket
        full = ""
        try:
            full = socket.gethostname()
        except OSError:
            full = platform.node() or ""
        short = full.split(".", 1)[0] if full else ""
        return {
            "local_user": getpass.getuser(),
            "hostname": full,
            "short_hostname": short,
            "kind": "laptop" if short and not short.endswith("server") else "host",
            "platform": platform.system().lower(),
        }

    if STATIC_DIR.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static",
        )

        # The HTML uses ``assets/<file>`` for logos. Mount that subdir at
        # ``/assets`` so relative paths in the HTML resolve.
        assets_dir = STATIC_DIR / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        # Cache-Control: no-cache means the browser must revalidate every
        # request before reusing a cached copy. Required for our HTML
        # routes because (a) ``/`` switched from dashboard to login in
        # Item 1 — without revalidation, returning users would see the
        # old cached dashboard when navigating to ``/`` and think the
        # "↺ switch" link did nothing, and (b) the embedded JSX evolves
        # frequently; we never want a hard-cached HTML pinning users to
        # stale script references.
        _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

        _AUTH_MODAL_TAG = '<script src="/static/auth-modal.js"></script>'

        def _html_page(filename: str) -> HTMLResponse:
            """Serve a dashboard HTML file with the session-login modal
            injected before </body>. The modal is inert unless the server
            challenges a mutating request with 401 (auth enabled).

            Also injects a subtle "which murmurent installation am I in" badge
            (top-right) on every page once a centre exists, so no page leaves
            the reader guessing which centre they're looking at."""
            html = (STATIC_DIR / filename).read_text(encoding="utf-8")

            # Single-source version: pages carry a {{MM_VERSION}} placeholder
            # rather than a hardcoded "v1.0.0" that drifted from __version__.
            html = html.replace("{{MM_VERSION}}", _mm_version)

            # Installation badge — best-effort; absent before a centre exists.
            try:
                from ..core import centre_init as _ci
                _centre = _ci.read_centre()
            except Exception:
                _centre = None
            if _centre is not None and getattr(_centre, "name", ""):
                import html as _htmllib
                import re as _re
                _label = _htmllib.escape(_centre.name)
                _inst = _htmllib.escape(_centre.institution or "")
                _badge = (
                    '<div id="wigamig-centre-badge" title="' + _label
                    + (' &middot; ' + _inst if _inst else '') + '" '
                    'style="position:fixed;top:6px;right:12px;z-index:9998;'
                    'font:600 11px/1.5 system-ui,-apple-system,sans-serif;'
                    'color:#4a5568;background:rgba(255,255,255,.9);'
                    'border:1px solid #dfe3ea;border-radius:11px;padding:2px 9px;'
                    'pointer-events:none;box-shadow:0 1px 2px rgba(0,0,0,.06);">'
                    'murmurent &middot; ' + _label + '</div>'
                )
                if _re.search(r"<body[^>]*>", html):
                    html = _re.sub(r"<body[^>]*>",
                                   lambda m: m.group(0) + "\n" + _badge,
                                   html, count=1)
                else:
                    html = _badge + html

            if _AUTH_MODAL_TAG not in html:
                if "</body>" in html:
                    html = html.replace("</body>", _AUTH_MODAL_TAG + "\n</body>", 1)
                else:
                    html = html + "\n" + _AUTH_MODAL_TAG
            return HTMLResponse(html, headers=_NO_CACHE)

        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            """Login landing page — always shown at app launch so the
            user explicitly picks their role for this session."""
            return _html_page("login.html")

        @app.get("/dashboard", response_class=HTMLResponse)
        def dashboard_index() -> HTMLResponse:
            """Member / PI dashboard. Reached from the login page with
            ``?user=<handle>&persona=member|pi``.

            One dashboard for every group: a lab and a core each have a
            PI, and the PI's dashboard describes THEIR group. The page is
            group-kind-aware (``lab_settings.kind`` flips the labels to
            "Core members", "Core settings", …) rather than a separate
            destination — issue #18. Core-service operations additionally
            live at /core?core=<name> until they're folded in.
            """
            return _html_page("Murmurent Dashboard Hi-Fi.html")

        @app.get("/registrar", response_class=HTMLResponse)
        def registrar_index() -> HTMLResponse:
            """Phase A registrar dashboard — separate route from the lab UI."""
            return _html_page("registrar.html")

        @app.get("/join", response_class=HTMLResponse)
        def join_index() -> HTMLResponse:
            """Public join form — no auth. Anyone at the institution can
            submit a lab/core/admin/pi join request from here. Item 2h."""
            return _html_page("join.html")

        @app.get("/core", response_class=HTMLResponse)
        def core_index() -> HTMLResponse:
            """Phase 1 core-leader dashboard — analogue of /dashboard
            for a service core. Gated server-side by /api/core/dashboard
            (the page calls it; non-core-leaders get a 403 + empty
            render). Per docs/cores_plan.md §10.
            """
            return _html_page("core.html")

        @app.get("/security", response_class=HTMLResponse)
        def security_index() -> HTMLResponse:
            """Per-lab security dashboard. Gated by ``lab_sudo`` (set by
            PI from the LabSudoPanel) or by being the PI. Pulls findings
            from ``~/.murmurent/security/<host>/latest.jsonl``.
            See docs/security-dashboard.md for the rule catalog.
            """
            return HTMLResponse(
                (STATIC_DIR / "security.html").read_text(encoding="utf-8"),
                headers=_NO_CACHE,
            )

        # The hi-fi HTML loads its sibling JSX files via relative paths
        # (``<script src="hifi-data.jsx">`` etc.). Serve them at root so the
        # browser's relative resolution finds them without rewriting the HTML.
        for asset in ("hifi-data.jsx", "hifi-notebook.jsx", "hifi-app.jsx"):
            _register_static_alias(app, asset, STATIC_DIR / asset)

        @app.get("/favicon.ico")
        def favicon():
            # 204 = "No Content" — body MUST be empty. Returning
            # ``JSONResponse({}, status_code=204)`` was a protocol
            # violation: the response carried Content-Length=2 (for
            # ``{}``) but uvicorn refuses to ship a body on 204, so
            # the bytes-sent vs Content-Length mismatch crashed every
            # favicon request. ``Response(status_code=204)`` sends
            # the right empty body with Content-Length=0.
            from fastapi.responses import Response
            return Response(status_code=204)

    else:  # pragma: no cover

        @app.get("/")
        def missing_static() -> JSONResponse:
            return JSONResponse(
                {"error": f"static dir not found at {STATIC_DIR}"},
                status_code=500,
            )

    return app


def _register_static_alias(app: FastAPI, url_name: str, file_path: Path) -> None:
    """Register ``GET /<url_name>`` to serve ``file_path`` (closure-safe).

    Served ``no-cache, must-revalidate`` so the browser re-fetches the JSX on
    every reload — edits to the dashboard show up on a normal refresh instead of
    requiring a hard reload. FileResponse still sets Last-Modified/ETag, so an
    unchanged file returns a cheap 304.
    """

    @app.get(f"/{url_name}", include_in_schema=False)
    def _serve(_path: str = file_path.as_posix()) -> FileResponse:
        return FileResponse(_path, media_type="text/babel",
                            headers={"Cache-Control": "no-cache, must-revalidate"})


# Module-level app for ``uvicorn murmurent.dashboard.server:app``.
app = create_app()


def main(host: str = "127.0.0.1", port: int = 8770) -> None:  # pragma: no cover
    """Run the server with uvicorn (used by the CLI launcher)."""
    import uvicorn

    uvicorn.run("murmurent.dashboard.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
