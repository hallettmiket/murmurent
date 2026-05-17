"""
Purpose: FastAPI app for the hi-fi dashboard. Serves the data contract at
         ``GET /api/dashboard`` and the static React/JSX assets from
         ``docs/designer_dashboard/`` so the existing hi-fi HTML can be
         opened straight from the browser.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``WIGAMIG_USER`` environment variable (or ``?user=`` query param)
       to scope the snapshot to a member.
Output: JSON + static files. Served via uvicorn.

Run::

    wigamig dashboard --hifi          # defaults to localhost:8770
    wigamig dashboard --hifi --port 8888

Open `http://localhost:8770/` in a browser.
"""

from __future__ import annotations

import datetime as _dt
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
    # Defaults to "local" (this laptop); set to "biodatsci" (or any name
    # in ~/.wigamig/hosts.yaml) to scaffold the project on that machine.
    host: str = "local"
    # 2026-05-15: optional override for the auto-derived Slack channel
    # name. ``None`` / "" → wigamig defaults to ``proj-<project>``.
    # Useful when the lab already has a channel that doesn't follow
    # the convention, or wants a different name at create time.
    slack_channel_name: str | None = None


class AddMemberBody(BaseModel):
    """JSON body for ``POST /api/members``."""

    handle: str
    full_name: str
    role: str = "staff"


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


class MachineSettingsBody(BaseModel):
    """JSON body for ``POST /api/machine/settings``."""

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
    # wigamig umbrella. ``lab_vm_root`` is kept as an alias on input for
    # backwards-compat with older clients; new code writes ``wigamig_base``.
    wigamig_base: str | None = None
    lab_vm_root: str = "~/wigamig"
    vault_root: str = "~/Obsidian"
    mount_point: str = ""
    description: str = ""
    scan_dirs: list[str] = []


class HostScanDirsBody(BaseModel):
    """JSON body for ``PATCH /api/hosts/{name}/scan-dirs``."""

    scan_dirs: list[str]


class AdoptCloneBody(BaseModel):
    """JSON body for ``POST /api/inventory/adopt``.

    Promotes an existing local git clone (one that shows up as
    ``• clone`` in the Repo Inventory) into a wigamig project by
    writing a CHARTER.md and bootstrapping ``.claude/agents/``. Local
    hosts only for v1 — remote adopt would need an SSH equivalent
    of the charter writer.
    """

    clone_path: str                # absolute path on this machine
    project: str                   # CHARTER project name
    lead: str                      # e.g. "@mhallet"
    members: list[str]             # at least one handle
    sensitivity: str = "standard"  # standard | restricted | clinical
    description: str = ""
    choreography: str | None = None
    agents: list[str] = []
    # Clinical-only fields. Required when sensitivity == "clinical";
    # render_charter() will raise if they're missing.
    reb_number: str | None = None
    reb_expires: str | None = None
    data_residency: str | None = None


class LoginSelectBody(BaseModel):
    """JSON body for ``POST /api/login/select``.

    The login landing page posts the (handle, role) the user picked.
    Server validates the role is one they actually hold, logs the
    transition to ``~/.wigamig/role_audit.log``, and returns the URL
    the client should navigate to (``/dashboard`` or ``/registrar``).
    """

    handle: str
    role: str  # "member" | "pi" | "registrar"
    remember_user: bool = False


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
    channel ID; wigamig writes it to CHARTER.md.
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
    app = FastAPI(
        title="wigamig dashboard",
        description="Hi-fi Hallett Lab dashboard — Western University.",
        version="0.1.0",
    )

    # Weekly repo-inventory refresh. Wigamig-internal cron: at startup
    # we check the cached report's mtime; if it's stale, fire a fresh
    # scan in a daemon thread so the user's first dashboard load isn't
    # blocked on SSH + ``gh repo list``. The scan writes to
    # ``~/.wigamig/inventory/`` and the dashboard reads from there.
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
                    lab = snap_mod._lab_settings("hallett")
                    host_names = [h.name for h in _hosts.read().values()]
                    _inv.scan_and_cache(
                        github_org=lab.github_org or "hallettmiket",
                        host_names=host_names,
                    )
                    _log.info("repo inventory: weekly refresh complete")
                except Exception as exc:  # noqa: BLE001 — best-effort
                    _log.warning("repo inventory background scan failed: %s", exc)
            threading.Thread(target=_run, name="wigamig-inventory-refresh", daemon=True).start()
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
                    "No user resolved. Set $WIGAMIG_USER or pass ?user=<handle>."
                ),
            )
        # Cross-lab scoping: look up which lab this handle belongs to via the
        # registrar registry and point lab_mgmt_repo_root() at that lab's
        # lab-mgmt repo for the duration of the request. Falls through to
        # the default (single-lab install) when the registry doesn't claim
        # this handle.
        from ..core import registrar as _registrar
        from ..core.repo import use_lab_mgmt_root
        match = _registrar.lab_mgmt_path_for_handle(handle)
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """List decommission reports on this machine, newest first.

        PI-only — the report dir is per-machine local state, so this is
        scoped to "what's been decommissioned from wigamig on the
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
            from . import slack_notify as _notify
            from ..core import project_provision as _pp
            from ..core.preflight import Probe as _Probe
            from ..core.repo import lab_mgmt_repo_root as _lmgmt
            _log = _logging.getLogger(__name__)
            # Create Slack channel. Best-effort: the project-approval flow
            # must succeed even when the Slack bot lacks scopes or is
            # offline — the PI can link an existing channel later via
            # /api/project/<name>/link_slack_channel.
            try:
                ch = _notify.create_project_channel(
                    req.project, channel_name=req.slack_channel_name,
                )
                if ch:
                    # create_project_channel persists id+name internally;
                    # no need to re-write here.
                    _notify._post(ch, f":rocket: Project `{req.project}` approved! Welcome to the channel.")
                    probes.append(_Probe(
                        name="slack channel", status="ok",
                        detail=f"channel id {ch}", required=False,
                    ).to_dict())
                else:
                    probes.append(_Probe(
                        name="slack channel", status="warn",
                        detail="slack returned no channel id — link an existing one from the panel",
                        required=False,
                    ).to_dict())
            except _notify.SlackScopeError as scope_exc:
                _log.warning("Slack scope issue during project-approve: %s", scope_exc)
                probes.append(_Probe(
                    name="slack channel", status="warn",
                    detail=f"slack scope: {scope_exc}", required=False,
                ).to_dict())

            # Provision the git origin. Phase 4: resolve the project's
            # ``repo_kind`` (which is now a provider id) against the
            # lab's git_providers list. Falls back to the legacy
            # github/local synthesized provider when the id matches
            # those literals — keeps pre-refactor charters working.
            from ..core import git_providers as _gpr2
            local_repo = Path(f"~/repos/{req.project}").expanduser()
            kind_or_id = req.repo_kind or "github"
            lab_settings = snap_mod._lab_settings("hallett")
            provider = _gpr2.find_provider(
                [_pp._GP.GitProvider(**p.model_dump()) for p in lab_settings.git_providers],
                kind_or_id,
            )
            ctx = _pp.ProvisionContext(
                project=req.project,
                local_repo=local_repo,
                kind=kind_or_id,
                org=lab_settings.github_org or "hallettmiket",
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Open VSCode + per-agent iTerm windows for a project.

        For local projects: spawns ``scripts/start_workspace.sh`` which
        opens VSCode (multi-root) + iTerm windows. For **remote** projects
        (host != local — the working tree lives on biodatsci or similar),
        the laptop can't start agent shells over there; we just launch
        VSCode in Remote-SSH mode via the ``vscode-remote://`` URL and let
        the user open agent terminals inside VSCode themselves.

        Pass ``project`` (the basename of a project under ``~/repos``) and
        ``agents`` (used only for local projects). Optionally ``sea_id``.
        """
        import os
        import subprocess
        from ..core.repo import wigamig_repo_root
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
        #   1. Installation manifest at ~/.wigamig/installations/<project>.yaml
        #      with ``ssh_remote`` set. This is the canonical "this machine
        #      installed mp1 on biodatsci" signal — written by
        #      workspace_initialize. Wins because the user may have a local
        #      working tree AND a remote install for the same project.
        #   2. Legacy ``.wigamig-remote-pointer`` marker in the local clone
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
                # time (e.g. /home/UWO/mhallet on biodatsci, which the
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

        # ---- Local project: existing multi-root + iTerm flow ----
        if not body.agents:
            raise HTTPException(status_code=422, detail="at least one agent required")

        script = wigamig_repo_root() / "scripts" / "start_workspace.sh"
        if not script.is_file():
            raise HTTPException(status_code=500, detail=f"launcher missing: {script}")

        project_dir = project_path(body.project)
        agents_csv = ",".join(body.agents)
        cmd: list[str] = [str(script), str(project_dir), agents_csv]
        if body.sea_id is not None:
            cmd.append(str(body.sea_id))

        # Generate the multi-root .code-workspace file so VSCode opens
        # with repo + refined/ + notebook + Oracle visible together.
        # Failures here are non-fatal — fall back to opening just the repo.
        workspace_path: str | None = None
        try:
            member_profile = snap_mod._load_member_profile(actor)
            settings = snap_mod._member_settings(member_profile)
            lab_name = str(member_profile.get("lab") or "hallett")
            lab_settings = snap_mod._lab_settings(lab_name)
            written = _workspace_file.write_workspace_file(
                project=body.project,
                obsidian_vault_path=settings.obsidian_vault_path,
                notebook_subfolder=settings.notebook_subfolder,
                oracle_subfolder=settings.oracle_subfolder,
                lab_oracle_vault=lab_settings.lab_oracle_vault,
            )
            workspace_path = str(written)
        except Exception:
            # Best-effort — never block the launch on a workspace-file glitch.
            workspace_path = None

        sub_env = os.environ.copy()
        if workspace_path:
            sub_env["WIGAMIG_WORKSPACE_FILE"] = workspace_path

        try:
            subprocess.Popen(  # noqa: S603 — args are list, never shelled
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                env=sub_env,
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"launcher failed: {exc}")

        return {
            "ok": True,
            "project": body.project,
            "project_dir": str(project_dir),
            "workspace_file": workspace_path,
            "agents": body.agents,
            "sea_id": body.sea_id,
            "cmd": cmd,
        }

    @app.post("/api/workspace/initialize")
    def workspace_initialize(
        body: WorkspaceInitializeBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Provision a project on this machine: mkdir raw/refined + write manifest.

        Runs a preflight first — the user wanted to see green/yellow/red
        rows for "is the project here", "can I reach the SSH host", "are
        raw/refined/notebook present (mkdir if not)", "any unresolved
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

        # Validate project exists locally before scribbling any state.
        from ..core.projects import project_path as _pp
        if not _pp(body.project).is_dir():
            raise HTTPException(status_code=404, detail=f"project not found: {body.project}")
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

        # Remote install: one batched SSH session does wigamig probe +
        # mkdir raw/refined/notebook + git-clone-if-missing. Combined
        # with the user's ControlMaster socket, this is typically zero
        # additional auth handshakes — matters on biodatsci where 3
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
            try:
                charter = Path(f"~/repos/{body.project}/CHARTER.md").expanduser()
                kind = "github"
                if charter.is_file():
                    meta = _parse_charter(charter).meta or {}
                    kind = str(meta.get("repo_kind") or "github")
                if kind == "github":
                    org = snap_mod._lab_settings("hallett").github_org or "hallettmiket"
                    repo_url = f"git@github.com:{org}/{body.project}.git"
            except Exception:
                repo_url = None

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

        # Local raw + refined dirs. These exist either way (the dashboard
        # writes the manifest locally even for SSH installs), but they're
        # only the *user's* data dirs when has_direct_access=True.
        raw_proj = Path(body.raw_path).expanduser() / body.project
        refined_proj = Path(body.refined_path).expanduser() / body.project
        if body.has_direct_access or not body.ssh_remote:
            for label, path in (("raw", raw_proj), ("refined", refined_proj)):
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
        # VSCode Remote-SSH — biodatsci's home is /home/UWO/<user>, not
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
                # filesystem, not the real ~/.wigamig.
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
        re-routing writes through wigamig would bypass them.
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
        probes.append(_pf.probe_obsidian_vault(body.obsidian_vault_path))
        return {
            "ok": True,
            "path": str(path),
            "overall": _pf.overall_status(probes),
            "probes": [p.to_dict() for p in probes],
        }

    @app.post("/api/member/settings")
    def save_member_settings(
        body: MemberSettingsBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Write the member's contact + location fields back to lab-mgmt.

        Edits ``<lab-mgmt>/members/<actor>.md`` frontmatter. Preserves
        the body, ``handle``/``full_name``/``role``/``status``/``lab``/
        ``certifications``/``obsidian``/``created`` and any other
        unknown keys. Per-machine Obsidian fields posted by older
        clients are silently dropped — they belong on machine.yaml.
        """
        from ..core.frontmatter import parse_file, dump_document

        actor = _resolve_actor(user)
        _require_active(actor)

        member_path = lab_mgmt_repo_root() / "members" / f"{actor}.md"
        if not member_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"member file not found: {member_path}",
            )

        parsed = parse_file(member_path)
        meta = dict(parsed.meta or {})

        # Only modify fields the request actually sent — a partial POST
        # like ``{"email": "x"}`` must not nuke the user's other contact
        # info. ``model_fields_set`` distinguishes "omitted" from
        # "explicitly null", which a plain dict from body.model_dump()
        # cannot.
        sent = body.model_fields_set
        contact_keys = ("email", "orcid", "bluesky", "github", "osf", "website")
        location_keys = ("office", "dry_lab", "wet_labs", "address", "city", "department")

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

    @app.post("/api/lab/settings")
    def save_lab_settings(
        body: LabSettingsBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        lab_name = "hallett"  # placeholder; today's dashboard is single-lab
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        machines aren't scanned — biodatsci-style remotes need an
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
        ``~/.wigamig/inventory/`` so the panel loads instantly. Pass
        ``?refresh=true`` to force a live re-scan — that hits ``gh
        repo list`` plus one SSH session per registered host. The
        result is also written to the cache so subsequent reads are
        cheap.
        """
        from ..core import repo_inventory as _inv
        lab_settings = snap_mod._lab_settings("hallett")
        org = lab_settings.github_org or "hallettmiket"

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
        lab_settings = snap_mod._lab_settings("hallett")
        org = lab_settings.github_org or "hallettmiket"
        report = _inv.scan_and_cache(
            github_org=org,
            host_names=_inventory_host_names(),
        )
        return {"from_cache": False, **report.to_dict()}

    @app.post("/api/inventory/adopt")
    def post_inventory_adopt(
        body: AdoptCloneBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Adopt an existing local git clone as a wigamig project.

        Delegates to :func:`core.projectize.make_wigamig_project` so the
        clone ends up in **all three** dashboard panels (Repos shows
        ✓ wigamig, Projects gets a lab_mgmt registry entry, Installations
        gets a manifest pointing at this machine).

        Refuses when:
          - clone_path isn't inside ``~/repos/`` (escape guard)
          - clone_path isn't a git working tree
          - a CHARTER.md already exists (don't silently overwrite —
            user should edit by hand, or remove and re-adopt)

        Defaults to this machine's settings for raw/refined/notebook
        paths (read from ``~/.wigamig/machine.yaml``). The Repos-panel
        adopt modal doesn't ask the user for those — they're a
        per-machine setting, not a per-project decision.
        """
        import os
        from ..core import projectize as _proj
        from . import machine_settings as _ms

        clone = Path(body.clone_path).expanduser().resolve()
        repos_root = (Path.home() / "repos").resolve()
        try:
            clone.relative_to(repos_root)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"clone_path must live under {repos_root} (got {clone})",
            )
        if not (clone / ".git").exists():
            raise HTTPException(
                status_code=400,
                detail=f"not a git working tree: {clone}",
            )
        if (clone / "CHARTER.md").exists():
            raise HTTPException(
                status_code=409,
                detail=(f"{clone / 'CHARTER.md'} already exists — "
                        "edit by hand instead of re-adopting"),
            )

        # Pull this-machine defaults from machine.yaml so the manifest
        # carries real paths, not adopt-modal-was-too-lazy-to-ask blanks.
        try:
            ms = _ms.load()
        except Exception:
            ms = None
        actor = (user or os.environ.get("WIGAMIG_USER", "")).strip().lstrip("@") or body.lead.lstrip("@")
        wb = ((ms.wigamig_base if ms else None) or "~/wigamig").rstrip("/")

        try:
            result = _proj.make_wigamig_project(
                clone_path=clone,
                project=body.project,
                lead=body.lead,
                members=body.members,
                sensitivity=body.sensitivity,
                description=body.description,
                choreography=body.choreography,
                agents=list(body.agents or []),
                reb_number=body.reb_number,
                reb_expires=body.reb_expires,
                data_residency=body.data_residency,
                member=actor,
                machine_type="laptop",
                hostname=os.uname().nodename,
                username=os.environ.get("USER", ""),
                has_direct_access=True,
                lab_base=wb,
                raw_path=f"{wb}/raw",
                refined_path=f"{wb}/refined",
                notebook_path=f"{wb}/lab_notebooks",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"projectize failed: {exc}") from exc

        # If charter validation failed projectize reports it via a probe
        # with status=fail+required=True; surface as 422 like before.
        charter_probe = next((p for p in result.probes if p.name == "charter"), None)
        if charter_probe and charter_probe.status == "fail":
            raise HTTPException(status_code=422, detail=charter_probe.detail)

        return {
            "ok": True,
            "project": body.project,
            "clone_path": str(clone),
            "registry_path": str(result.registry_path) if result.registry_path else None,
            "manifest_path": str(result.manifest_path) if result.manifest_path else None,
            "probes": [p.to_dict() for p in result.probes],
        }

    # -----------------------------------------------------------------
    # Membership (PI-only roster mgmt)
    # -----------------------------------------------------------------

    @app.post("/api/members")
    def add_member_endpoint(
        body: AddMemberBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        }}

    @app.post("/api/members/{handle}/{action}")
    def member_status_endpoint(
        handle: str,
        action: str,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
            org = snap_mod._lab_settings("hallett").github_org or "hallettmiket"
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        lab_settings = snap_mod._lab_settings("hallett")
        provider = _gpr3.find_provider(
            [_pp._GP.GitProvider(**p.model_dump()) for p in lab_settings.git_providers],
            kind,
        )
        ctx = _pp.ProvisionContext(
            project=project,
            local_repo=local_repo,
            kind=kind,
            org=lab_settings.github_org or "hallettmiket",
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Disconnect a per-machine installation manifest.

        Removes ``~/.wigamig/installations/<project>.yaml`` (a wigamig-
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
                        note=f"{k.replace('_path','')} dir on the target machine. wigamig won't delete data here.",
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
    def sync_project_slack_members(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Soft-delete (decommission) a project. PI only.

        Files on disk are NOT touched. The project's CHARTER.md frontmatter
        flips to ``status: archived`` with a timestamp; a markdown report
        is written to ``~/.wigamig/decommissions/`` listing what the user
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

    @app.post("/api/project/{project}/unarchive")
    def unarchive_project_endpoint(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Bring a previously-archived project back to active. PI only."""
        from ..core import projects as _projects

        _require_pi(user)
        try:
            _projects.unarchive_project(project)
        except _projects.ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True}

    @app.post("/api/project/{project}/provision/install")
    def provision_install(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
            # ``~/.wigamig/hosts.yaml``. Expose both so the UI can use the new
            # name while older code that reads ``lab_vm_root`` keeps working.
            "wigamig_base": h.lab_vm_root,
            "lab_vm_root": h.lab_vm_root,
            "vault_root": h.vault_root,
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

        Item 3 R4: dashboard equivalent of ``wigamig host add`` so the
        user can register biodatsci without dropping to a terminal.
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Disconnect a host (machine) from wigamig.

        The host's row in ``~/.wigamig/hosts.yaml`` is removed (that file
        is a local-only registry — removing the row doesn't touch
        anything on the actual machine). A decommission report is
        written to ``~/.wigamig/decommissions/`` listing the paths on
        that machine the user may want to clean up by hand (wigamig_base
        directories, vault, etc.). ``local`` cannot be removed.
        """
        from ..core import hosts as _hosts
        from ..core import decommission as _deco

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

        actor = (user or "").strip().lstrip("@") or "unknown"
        items: list[_deco.CleanupItem] = []
        if host is not None:
            ssh_target = (host.ssh_host or name) if host.is_remote else None
            if ssh_target:
                items.append(_deco.CleanupItem(
                    path=f"{host.remote_user + '@' if host.remote_user else ''}{ssh_target}",
                    note="SSH target — wigamig no longer reaches this machine, but your ~/.ssh/config entry is untouched.",
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

    @app.post("/api/hosts/{name}/test")
    def post_host_test(name: str) -> dict:
        """Run the four probes against a registered host.

        Each probe returns ``ok``, ``warn``, or ``fail``:
          - ssh (required): can we authenticate non-interactively?
          - wigamig (required): is `wigamig --version` reachable on host?
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
            version = remote.wigamig_version()
            results.append({
                "name": "wigamig",
                "status": "ok",
                "detail": version,
                "required": True,
            })
        except _remote.RemoteError as exc:
            err_text = exc.stderr.strip() or str(exc)
            results.append({
                "name": "wigamig",
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
                    f"{lab_vm}/{{raw,refined}} missing — wigamig will mkdir on first project"
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
    #                  (or, fallback, in the local ~/.wigamig/registrar
    #                   sentinel — legacy single-registrar installs)
    # Each /api/login/select call is appended to ~/.wigamig/role_audit.log
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
        # registry walk supports multi-lab logins — @vdumeaux is recognised
        # as PI of the vdumeaux lab even though @mhallet's lab_mgmt is the
        # default on this machine.
        match = _reg.lab_mgmt_path_for_handle(norm)
        lab_name = match[0] if match else None
        lab_mgmt_override = match[1] if match else None

        with use_lab_mgmt_root(lab_mgmt_override):
            # member? — checked against the matched lab's members/ dir
            try:
                rec = _mem.get(norm)
                is_member = rec.status == _mem.ACTIVE
            except _mem.MemberNotFound:
                is_member = False
            # pi? — read the matched lab's lab.md:pi field
            try:
                from ..core import dashboard as _dash
                pi_handle_now = _dash._pi_handle().lstrip("@").lower()
            except Exception:
                pi_handle_now = ""
        is_pi_role = bool(pi_handle_now) and norm == pi_handle_now
        # registrar? (centre-level — independent of lab)
        is_reg = _reg.is_registrar(norm)
        # default lens: highest privilege the user holds
        if is_reg:
            default = "registrar"
        elif is_pi_role:
            default = "pi"
        elif is_member:
            default = "member"
        else:
            default = "member"  # unknown handle — still let them try
        return {
            "handle": norm,
            "is_member": is_member,
            "is_pi": is_pi_role,
            "is_registrar": is_reg,
            "pi_lab": lab_name or pi_handle_now or None,
            "registrar_centres": _reg.registrars() or (
                [_reg.registrar_handle()] if _reg.registrar_handle() else []
            ),
            "default_role": default,
        }

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
            try:
                pref = Path.home() / ".wigamig" / "user"
                pref.parent.mkdir(parents=True, exist_ok=True)
                pref.write_text(handle + "\n", encoding="utf-8")
            except OSError:
                pass  # not fatal — they can still proceed this session

        if role == "registrar":
            next_url = f"/registrar?user={handle}"
        elif role == "pi":
            next_url = f"/dashboard?user={handle}&persona=pi"
        else:
            next_url = f"/dashboard?user={handle}&persona=member"
        return {
            "ok": True,
            "handle": handle,
            "role": role,
            "next": next_url,
        }

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
                    f"Ask the PI to reactivate before running wigamig actions."
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

    @app.post("/api/sea_catalog")
    def catalog_upsert(
        body: CatalogEntryBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
    def oracle_approve_decline(
        slug: str,
        action: str,
        body: SeaActionBody = Body(default_factory=SeaActionBody),
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
                "`wigamig publish <path> --to oracle` manually."
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
        from ..core.repo import wigamig_repo_root

        VALID_MODELS = {"opus", "sonnet", "haiku"}
        if action not in {"enable", "disable", "set_model"}:
            raise HTTPException(status_code=422, detail=f"unknown action: {action}")
        if action == "set_model" and (not model or model not in VALID_MODELS):
            raise HTTPException(
                status_code=422,
                detail=f"set_model needs ?model={'|'.join(sorted(VALID_MODELS))}",
            )

        registry_dir = wigamig_repo_root() / "agents"
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
    # registrar's handle is the first line of ``~/.wigamig/registrar``.
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
    # ``~/.wigamig/lab_info/collaboration_requests/`` (centre-scoped,
    # shared with the registrar). On approval the existing
    # ``create_collaboration`` is invoked so all the invariants run.

    @app.post("/api/collaboration/propose")
    def propose_collaboration(
        body: ProposeCollaborationBody,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Update the registrar's centre-level profile.

        Writes to ``$WIGAMIG_LAB_INFO_ROOT/registrar.md`` frontmatter.
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
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
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
        current host. ``short_hostname`` is the bare name (e.g. "biodatsci"
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

        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            """Login landing page — always shown at app launch so the
            user explicitly picks their role for this session."""
            return HTMLResponse(
                (STATIC_DIR / "login.html").read_text(encoding="utf-8"),
                headers=_NO_CACHE,
            )

        @app.get("/dashboard", response_class=HTMLResponse)
        def dashboard_index() -> HTMLResponse:
            """Member / PI lab dashboard. Reached from the login page
            with ``?user=<handle>&persona=member|pi``."""
            return HTMLResponse(
                (STATIC_DIR / "Wigamig Dashboard Hi-Fi.html").read_text(encoding="utf-8"),
                headers=_NO_CACHE,
            )

        @app.get("/registrar", response_class=HTMLResponse)
        def registrar_index() -> HTMLResponse:
            """Phase A registrar dashboard — separate route from the lab UI."""
            return HTMLResponse(
                (STATIC_DIR / "registrar.html").read_text(encoding="utf-8"),
                headers=_NO_CACHE,
            )

        # The hi-fi HTML loads its sibling JSX files via relative paths
        # (``<script src="hifi-data.jsx">`` etc.). Serve them at root so the
        # browser's relative resolution finds them without rewriting the HTML.
        for asset in ("hifi-data.jsx", "hifi-notebook.jsx", "hifi-app.jsx"):
            _register_static_alias(app, asset, STATIC_DIR / asset)

        @app.get("/favicon.ico")
        def favicon() -> JSONResponse:
            return JSONResponse({}, status_code=204)

    else:  # pragma: no cover

        @app.get("/")
        def missing_static() -> JSONResponse:
            return JSONResponse(
                {"error": f"static dir not found at {STATIC_DIR}"},
                status_code=500,
            )

    return app


def _register_static_alias(app: FastAPI, url_name: str, file_path: Path) -> None:
    """Register ``GET /<url_name>`` to serve ``file_path`` (closure-safe)."""

    @app.get(f"/{url_name}", include_in_schema=False)
    def _serve(_path: str = file_path.as_posix()) -> FileResponse:
        return FileResponse(_path, media_type="text/babel")


# Module-level app for ``uvicorn wigamig.dashboard.server:app``.
app = create_app()


def main(host: str = "127.0.0.1", port: int = 8770) -> None:  # pragma: no cover
    """Run the server with uvicorn (used by the CLI launcher)."""
    import uvicorn

    uvicorn.run("wigamig.dashboard.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
