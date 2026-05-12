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

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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


class LabSettingsBody(BaseModel):
    """JSON body for ``POST /api/lab/settings`` (PI-only)."""

    name: str | None = None                          # short id, e.g. "hallett"
    display_name: str | None = None                  # e.g. "Hallett Lab"
    pi_handle: str | None = None                     # ``@handle``
    website: str | None = None
    notebook_large_files_path: str | None = None
    lab_oracle_vault: str | None = None
    admins: list[str] | None = None
    github_org: str | None = None                    # e.g. "hallettmiket"
    git_repos_subpath: str | None = None             # default "git_repos"


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


class RegistrarCollabCreateBody(BaseModel):
    """JSON body for ``POST /api/registrar/collaboration`` (Phase D)."""

    name: str                                  # short ID, lowercase + _
    pis: list[str]                             # >=2 @handles
    groups: list[str]                          # >=2 lab/core short IDs
    member_subset: dict[str, list[str]] = {}   # group -> [@handles]
    oracle_vault: str | None = None            # defaults to "wigamig-collab-<name>"


class RegistrarCollabEditBody(BaseModel):
    """JSON body for ``POST /api/registrar/collaboration/{name}/edit``."""

    pis: list[str] | None = None
    groups: list[str] | None = None
    member_subset: dict[str, list[str]] | None = None
    oracle_vault: str | None = None


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
        if action == "approve" and req.kind == "project-create":
            import logging as _logging
            from . import slack_notify as _notify
            from ..commands import project_cmd as _project_cmd
            _log = _logging.getLogger(__name__)
            # Create Slack channel
            ch = _notify.create_project_channel(req.project)
            if ch:
                _notify._write_charter_channel_id(req.project, ch)
                _notify._post(ch, f":rocket: Project `{req.project}` approved! Welcome to the channel.")
            else:
                _log.warning("Slack channel creation failed for project %s", req.project)
            # Provision the git origin per the request's repo_kind.
            local_repo = Path(f"~/repos/{req.project}").expanduser()
            if (local_repo / ".git").is_dir():
                kind = req.repo_kind or "github"
                try:
                    if kind == "local":
                        if not req.local_repo_root:
                            _log.warning(
                                "local repo provisioning skipped for %s: no local_repo_root",
                                req.project,
                            )
                        else:
                            bare = Path(req.local_repo_root).expanduser() / f"{req.project}.git"
                            _project_cmd.ensure_remote(
                                local_repo, req.project, kind="local", bare_repo_path=bare,
                            )
                    else:
                        # kind="github" — read org from lab.md, fall back to historic literal.
                        lab_name = "hallett"
                        org = snap_mod._lab_settings(lab_name).github_org or "hallettmiket"
                        _project_cmd.ensure_remote(
                            local_repo, req.project, kind="github", org=org,
                        )
                except Exception as _exc:
                    _log.warning(
                        "remote provisioning (kind=%s) failed for %s: %s",
                        kind, req.project, _exc,
                    )
        return _request_response(result.request)

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

        Pass ``project`` (the basename of a local project repo under
        ``~/repos``) and ``agents`` (a list of agent names). Optionally
        ``sea_id`` to focus on a specific SEA. The server spawns
        ``scripts/start_workspace.sh`` in the background; the actual
        windows pop up locally.
        """
        import os
        import subprocess
        from ..core.repo import wigamig_repo_root
        from ..core.projects import find_project as _find_project
        from . import workspace_file as _workspace_file

        actor = _resolve_actor(user)
        _require_active(actor)

        if not body.agents:
            raise HTTPException(status_code=422, detail="at least one agent required")
        if _find_project(body.project) is None:
            raise HTTPException(status_code=404, detail=f"project not found: {body.project}")

        script = wigamig_repo_root() / "scripts" / "start_workspace.sh"
        if not script.is_file():
            raise HTTPException(status_code=500, detail=f"launcher missing: {script}")

        from ..core.projects import project_path
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

        Minimal scope by design. Does not clone the repo, install agents,
        or run any shell beyond ``mkdir -p`` — those steps stay as a user
        checklist. The manifest at ``~/.wigamig/installations/<project>.yaml``
        is what makes the installation appear in the dashboard's
        Installations panel on the next refresh.
        """
        import datetime as _dt
        import yaml as _yaml
        from .snapshot import INSTALLATIONS_DIR

        actor = _resolve_actor(user)
        _require_active(actor)

        # Validate project exists locally before scribbling any state.
        from ..core.projects import project_path as _pp
        if not _pp(body.project).is_dir():
            raise HTTPException(status_code=404, detail=f"project not found: {body.project}")

        # Create raw + refined dirs for this project. ``mkdir -p`` is idempotent.
        try:
            raw_proj = Path(body.raw_path).expanduser() / body.project
            refined_proj = Path(body.refined_path).expanduser() / body.project
            raw_proj.mkdir(parents=True, exist_ok=True)
            refined_proj.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"mkdir failed: {exc}")

        member_at = body.member if body.member.startswith("@") else f"@{body.member}"
        today_iso = _dt.date.today().isoformat()
        manifest = {
            "member": member_at,
            "project": body.project,
            "machine_type": body.machine_type,
            "hostname": body.hostname,
            "username": body.username,
            "access": "direct" if body.has_direct_access else "ssh",
            "has_direct_access": body.has_direct_access,
            "lab_base": body.lab_base,
            "raw_path": body.raw_path,
            "refined_path": body.refined_path,
            "notebook_path": body.notebook_path,
            "ssh_remote": body.ssh_remote,
            "mount_point": body.mount_point,
            "components": body.infra_components,
            "agents": body.agents,
            "status": "active",
            "created": today_iso,
            "last_checked": today_iso,
            "issues": [],
        }

        INSTALLATIONS_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = INSTALLATIONS_DIR / f"{body.project}.yaml"
        try:
            manifest_path.write_text(
                _yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"manifest write failed: {exc}")

        return {
            "ok": True,
            "project": body.project,
            "manifest": str(manifest_path),
            "raw_dir": str(raw_proj),
            "refined_dir": str(refined_proj),
        }

    # -----------------------------------------------------------------
    # Settings: machine (per-machine), member (per-person), lab (PI-only)
    # -----------------------------------------------------------------

    @app.post("/api/machine/settings")
    def save_machine_settings(body: MachineSettingsBody) -> dict:
        """Persist per-machine settings to ``~/.wigamig/machine.yaml``.

        Not gated on identity: the file is in the user's home dir, so
        the OS already enforces who can write it. Returns the path so
        the UI can display where the value landed.
        """
        from . import machine_settings as _ms
        path = _ms.write(C.MachineSettings(**body.model_dump()))
        return {"ok": True, "path": str(path)}

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

        try:
            member_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}")

        return {"ok": True, "path": str(member_path)}

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

        for k, v in updates.items():
            if v in (None, ""):
                meta.pop(k, None)
            else:
                meta[k] = v

        try:
            lab_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}")

        return {"ok": True, "path": str(lab_path)}

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
            rec = _m.set_status(handle, new_status)
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
        return {"ok": True, "handle": rec.handle, "status": rec.status}

    # -----------------------------------------------------------------
    # Project provisioning (GitHub / Slack / installation dirs)
    # -----------------------------------------------------------------

    @app.post("/api/project/{project}/provision/slack")
    def provision_slack(
        project: str,
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Create the Slack channel for a project. PI only. Idempotent."""
        actor = _require_pi(user)
        from . import slack_notify as _notify
        channel_id = _notify.create_project_channel(project)
        if not channel_id:
            raise HTTPException(status_code=500, detail="Slack channel creation failed — check server logs")
        _notify._write_charter_channel_id(project, channel_id)
        _notify._post(channel_id, f":rocket: Project `{project}` channel ready.")
        return {"ok": True, "channel_id": channel_id}

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
                        detail="CHARTER.md says repo_kind=local but local_repo_root is missing",
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

        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            return HTMLResponse(
                (STATIC_DIR / "Wigamig Dashboard Hi-Fi.html").read_text(encoding="utf-8")
            )

        @app.get("/registrar", response_class=HTMLResponse)
        def registrar_index() -> HTMLResponse:
            """Phase A registrar dashboard — separate route from the lab UI."""
            return HTMLResponse(
                (STATIC_DIR / "registrar.html").read_text(encoding="utf-8")
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
