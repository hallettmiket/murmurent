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


class AddMemberBody(BaseModel):
    """JSON body for ``POST /api/members``."""

    handle: str
    full_name: str
    role: str = "staff"


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

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
