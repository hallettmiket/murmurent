"""
Purpose: MCP server exposing this group's offered-SEAs catalog so other
         groups' agents can discover what we do and file inbound
         requests programmatically.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: stdio MCP protocol, plus :func:`tool_*` direct calls used by
       tests.
Output: JSON-serialisable structures.

Tools:
  ``sea_catalog_list``     - all accepting entries (read; group-public)
  ``sea_catalog_get``      - one entry by slug (read)
  ``sea_catalog_request``  - file an inbound request from another group
                             (writes to ``<lab-mgmt>/inbound/``)

Permissions:
  - List + get are open: the catalog is the front door.
  - Request requires a from_group + from_handle in the call (no auth in
    v1; trust the calling MCP client). PI approves before work starts.

Run as a server (registered in ``~/.claude/settings.json`` by
``wigamig install --hooks`` in a future phase)::

    python -m wigamig.mcp.sea_catalog_server
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any

from ..core import cross_group as xg
from ..core import sea_catalog as catalog


# ---------------------------------------------------------------------------
# Tool implementations (callable directly for the test harness)
# ---------------------------------------------------------------------------


def tool_list(*, accepting_only: bool = True) -> list[dict[str, Any]]:
    """List offered SEAs.

    By default only entries with ``accepting: true`` are returned —
    other groups don't need to see paused offerings.
    """
    out: list[dict[str, Any]] = []
    for entry in catalog.iter_catalog(accepting_only=accepting_only):
        out.append({
            "slug": entry.slug,
            "title": entry.title,
            "kind": entry.kind,
            "contact": entry.contact,
            "description": entry.description,
            "turnaround_days": entry.turnaround_days,
            "prerequisites": list(entry.prerequisites),
            "accepting": entry.accepting,
            "updated": entry.updated,
        })
    return out


def tool_get(slug: str) -> dict[str, Any]:
    """Return one catalog entry's full payload (frontmatter + body)."""
    try:
        entry = catalog.get(slug)
    except catalog.CatalogNotFound as exc:
        raise KeyError(str(exc)) from exc
    return {
        "slug": entry.slug,
        "title": entry.title,
        "kind": entry.kind,
        "contact": entry.contact,
        "description": entry.description,
        "turnaround_days": entry.turnaround_days,
        "prerequisites": list(entry.prerequisites),
        "accepting": entry.accepting,
        "created": entry.created,
        "updated": entry.updated,
        "body": entry.body,
    }


def tool_request(
    *,
    catalog_slug: str,
    from_group: str,
    from_handle: str,
    from_pi: str = "",
    description: str = "",
) -> dict[str, Any]:
    """File an inbound cross-group SEA request.

    Refuses if the slug is unknown or the entry is not accepting.
    On success, writes the request to ``<lab-mgmt>/inbound/<id>.md``
    and returns the freshly-assigned id.
    """
    try:
        entry = catalog.get(catalog_slug)
    except catalog.CatalogNotFound as exc:
        raise KeyError(str(exc)) from exc
    if not entry.accepting:
        raise ValueError(
            f"catalog entry {catalog_slug!r} is paused; not accepting requests."
        )
    if not from_group or not from_handle:
        raise ValueError("from_group and from_handle are required")

    req = xg.file_inbound(
        catalog_slug=catalog_slug,
        from_group=from_group,
        from_handle=from_handle,
        from_pi=from_pi,
        description=description,
    )
    return {
        "id": req.id,
        "state": req.state,
        "catalog_slug": req.catalog_slug,
        "from_group": req.from_group,
        "from_handle": req.from_handle,
        "created_at": req.created_at,
    }


# ---------------------------------------------------------------------------
# stdio MCP shim — wire-up lands when wigamig install --hooks supports it
# ---------------------------------------------------------------------------


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name") or payload.get("tool_name")
    args = payload.get("arguments") or payload.get("args") or {}
    if name == "sea_catalog_list":
        return {"result": tool_list(**args)}
    if name == "sea_catalog_get":
        return {"result": tool_get(**args)}
    if name == "sea_catalog_request":
        return {"result": tool_request(**args)}
    return {"error": f"unknown tool: {name!r}"}


def main() -> int:  # pragma: no cover
    raw = sys.stdin.read()
    if not raw.strip():
        sys.stdout.write(json.dumps({"error": "empty payload"}))
        return 1
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stdout.write(json.dumps({"error": f"bad json: {exc}"}))
        return 1
    sys.stdout.write(json.dumps(_dispatch(payload), default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
