"""
Purpose: Wigamig inventory MCP server. Exposes the markdown-backed
         ``<lab-mgmt-repo>/inventory/`` as a set of MCP tools (list, show,
         provision, set, add, order). v1 derives the lab manager from
         ``<lab-mgmt>/lab.md`` (the lab's PI), so changes happen via PR.
         ``lab_manager``; real token-based auth lands in v2.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: stdio MCP protocol (the canonical CC integration), or direct calls via
       :mod:`wigamig.mcp.inventory_server.tools` for the test harness.
Output: JSON-serialisable structures the MCP client renders for the model.

Run as a server::

    python -m wigamig.mcp.inventory_server

The CLI never calls this server directly; ``wigamig install --hooks``
registers it under ``mcpServers`` in ``~/.claude/settings.json``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..core import inventory
from ..core.frontmatter import parse_file
from ..core.identity import resolve as resolve_identity
from ..core.repo import lab_mgmt_repo_root

def _lab_manager_handle() -> str:
    """The lab manager handle today is the PI from <lab-mgmt>/lab.md."""
    from ..core.lab import pi_handle

    return pi_handle()
ORDER_DIR = "onboarding"  # placeholder for `inventory_order` issues until
# a real Issues integration lands; "open an order issue file in lab-mgmt".


# ---------------------------------------------------------------------------
# Tool implementations (callable directly for the test harness)
# ---------------------------------------------------------------------------


def _serialise(item: inventory.InventoryItem) -> dict[str, Any]:
    d = asdict(item)
    d.pop("body", None)
    if d.get("path") is not None:
        d["path"] = str(d["path"])
    return d


def _resolve_caller(handle_override: str | None = None) -> str:
    if handle_override:
        return handle_override.lstrip("@").lower()
    identity = resolve_identity(allow_unknown=True)
    return identity.handle.lower()


def _require_lab_manager(handle: str | None) -> None:
    caller = _resolve_caller(handle)
    lm = _lab_manager_handle().lower()
    if caller != lm:
        raise PermissionError(
            f"inventory write tools require lab_manager (@{lm}); caller is @{caller}."
        )


def tool_list(filter_: str | None = None) -> list[dict[str, Any]]:
    """List items, optionally filtered.

    ``filter_`` accepts: ``None`` (all), ``"low"`` (status low / out),
    ``"out"`` (status out only), ``"expired"`` (expired or past expiry),
    ``"expiring"`` or ``"expiring:<days>"`` (within ``<days>`` days; default 30).
    """
    items = inventory.iter_items()
    if filter_ in (None, "", "all"):
        result = items
    elif filter_ == "low":
        result = inventory.filter_low(items)
    elif filter_ == "out":
        result = inventory.filter_out(items)
    elif filter_ == "expired":
        result = inventory.filter_expired(items)
    elif filter_ == "expiring":
        result = inventory.filter_expiring(items, within_days=30)
    elif filter_.startswith("expiring:"):
        try:
            days = int(filter_.split(":", 1)[1])
        except ValueError as exc:
            raise ValueError(f"bad expiring filter: {filter_!r}") from exc
        result = inventory.filter_expiring(items, within_days=days)
    else:
        raise ValueError(f"unknown filter: {filter_!r}")
    return [_serialise(i) for i in result]


def tool_show(name: str) -> dict[str, Any]:
    """Return frontmatter + body of one reagent."""
    path = inventory.item_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"no inventory item named {name!r}")
    item = inventory.parse_item(path)
    payload = _serialise(item)
    payload["body"] = item.body
    return payload


def tool_provision(plan_path: str) -> dict[str, list[str]]:
    """Read frontmatter ``reagents`` from ``plan_path``; intersect with inventory."""
    parsed = parse_file(plan_path)
    plan_reagents = parsed.meta.get("reagents") or []
    if not isinstance(plan_reagents, list):
        raise ValueError(
            f"plan {plan_path}: 'reagents' must be a list, got {type(plan_reagents)!r}"
        )
    return inventory.provision([str(r) for r in plan_reagents], inventory.iter_items())


def tool_set(
    name: str,
    fields: dict[str, Any],
    *,
    handle: str | None = None,
) -> dict[str, Any]:
    """Update fields on an item; auto-bumps ``last_updated``. Lab-manager only."""
    _require_lab_manager(handle)
    path = inventory.item_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"no inventory item named {name!r}")
    item = inventory.parse_item(path)
    for key, value in fields.items():
        if not hasattr(item, key):
            raise ValueError(f"unknown field for inventory item: {key!r}")
        setattr(item, key, value)
    inventory.write_item(item)
    return _serialise(item)


def tool_add(
    name: str,
    *,
    vendor: str | None = None,
    catalog_no: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
    expiry: str | None = None,
    location: str | None = None,
    status: str = "in_stock",
    protocols: list[str] | None = None,
    handle: str | None = None,
) -> dict[str, Any]:
    """Create a new inventory item. Lab-manager only."""
    _require_lab_manager(handle)
    path = inventory.item_path(name)
    if path.is_file():
        raise FileExistsError(f"inventory item {name!r} already exists at {path}")
    item = inventory.InventoryItem(
        name=name,
        vendor=vendor,
        catalog_no=catalog_no,
        qty=qty,
        unit=unit,
        expiry=expiry,
        location=location,
        status=status,
        protocols=protocols or [],
    )
    inventory.write_item(item)
    return _serialise(item)


def tool_order(name: str, *, handle: str | None = None) -> dict[str, str]:
    """Open a fake order-issue file in lab-mgmt. Lab-manager only.

    Real issue creation lives in v2; here we just write
    ``<lab-mgmt>/orders/<date>_<name>.md`` so the action is auditable.
    """
    _require_lab_manager(handle)
    if not inventory.item_path(name).is_file():
        raise FileNotFoundError(f"no inventory item named {name!r} to order")
    orders_dir = lab_mgmt_repo_root() / "orders"
    orders_dir.mkdir(parents=True, exist_ok=True)
    import datetime as _dt

    today = _dt.date.today().isoformat()
    order_path = orders_dir / f"{today}_{name}.md"
    if not order_path.exists():
        order_path.write_text(
            f"---\nitem: {name}\nopened: {today}\nopened_by: '@{_lab_manager_handle()}'\n---\n\n"
            f"# Order: {name}\n\nPlaced by lab_manager via the inventory MCP.\n",
            encoding="utf-8",
        )
    return {"order_file": str(order_path)}


# ---------------------------------------------------------------------------
# MCP server wiring (lazy import; only required to actually run as a server)
# ---------------------------------------------------------------------------


def _build_server():  # pragma: no cover - exercised only when mcp is installed
    """Construct the MCP server. Imports the SDK lazily."""
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

    server = FastMCP(
        name="wigamig-inventory",
        instructions=(
            "Wigamig group inventory. Use `inventory_list` for browsing "
            "(filters: low, expired, expiring, expiring:<days>); "
            "`inventory_show` for details on one reagent; "
            "`inventory_provision` for plan ∩ inventory gap analysis. "
            "Write tools (set/add/order) require lab_manager."
        ),
    )

    @server.tool(name="inventory_list", description="List inventory items, optionally filtered.")
    def _list(filter: str | None = None) -> str:  # noqa: A002
        return json.dumps(tool_list(filter))

    @server.tool(name="inventory_show", description="Show frontmatter + body for one item.")
    def _show(name: str) -> str:
        return json.dumps(tool_show(name))

    @server.tool(
        name="inventory_provision",
        description="Compare a plan's reagents to inventory. Returns ok/gaps/expiring.",
    )
    def _provision(plan_path: str) -> str:
        return json.dumps(tool_provision(plan_path))

    @server.tool(
        name="inventory_set",
        description="Update fields on an inventory item (lab_manager only).",
    )
    def _set(name: str, fields: dict[str, Any]) -> str:
        return json.dumps(tool_set(name, fields))

    @server.tool(
        name="inventory_add",
        description="Create a new inventory item (lab_manager only).",
    )
    def _add(
        name: str,
        vendor: str | None = None,
        catalog_no: str | None = None,
        qty: float | None = None,
        unit: str | None = None,
        expiry: str | None = None,
        location: str | None = None,
        status: str = "in_stock",
        protocols: list[str] | None = None,
    ) -> str:
        return json.dumps(
            tool_add(
                name,
                vendor=vendor,
                catalog_no=catalog_no,
                qty=qty,
                unit=unit,
                expiry=expiry,
                location=location,
                status=status,
                protocols=protocols,
            )
        )

    @server.tool(
        name="inventory_order",
        description="Open an order issue file in lab-mgmt (lab_manager only).",
    )
    def _order(name: str) -> str:
        return json.dumps(tool_order(name))

    return server


def main() -> int:  # pragma: no cover - run only as MCP server
    server = _build_server()
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
