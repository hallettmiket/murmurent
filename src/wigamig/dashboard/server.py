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
from . import contract as C
from . import notebook_actions
from . import request_actions
from . import sea_actions
from . import snapshot as snap_mod


class NotebookEditBody(BaseModel):
    """Optional JSON body for ``POST /api/notebook/edit``."""

    date: str | None = None  # ISO date; defaults to today


class JoinRequestBody(BaseModel):
    """JSON body for ``POST /api/request/join``."""

    project: str
    justification: str = ""


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
        actor = (user or "").strip().lstrip("@")
        if not actor:
            identity = resolve_identity(allow_unknown=True)
            actor = identity.handle if identity.source != "unknown" else ""
        if not actor:
            raise HTTPException(
                status_code=400,
                detail="No actor resolved. Set $WIGAMIG_USER or pass ?user=<handle>.",
            )

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
        actor = (user or "").strip().lstrip("@")
        if not actor:
            identity = resolve_identity(allow_unknown=True)
            actor = identity.handle if identity.source != "unknown" else ""
        if not actor:
            raise HTTPException(
                status_code=400,
                detail="No actor resolved. Set $WIGAMIG_USER or pass ?user=<handle>.",
            )
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

    @app.post("/api/request/{request_id}/{action}")
    def request_action(
        request_id: int,
        action: str,
        body: RequestActionBody = Body(default_factory=RequestActionBody),
        user: str = Query("", description="Actor handle; falls back to $WIGAMIG_USER."),
    ) -> dict:
        """Approve or decline a project-join request. PI only."""
        actor = (user or "").strip().lstrip("@")
        if not actor:
            identity = resolve_identity(allow_unknown=True)
            actor = identity.handle if identity.source != "unknown" else ""
        if not actor:
            raise HTTPException(
                status_code=400,
                detail="No actor resolved. Set $WIGAMIG_USER or pass ?user=<handle>.",
            )
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
