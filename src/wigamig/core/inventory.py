"""
Purpose: Read / write / filter the markdown-backed inventory in the lab-mgmt repo.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``<lab-mgmt-repo>/inventory/<name>.md`` files.
Output: ``InventoryItem`` dataclasses + helpers for the inventory MCP and CLI.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .frontmatter import dump_document, parse_file
from .repo import lab_mgmt_repo_root

INVENTORY_SUBDIR = "inventory"
VALID_STATUSES: tuple[str, ...] = ("in_stock", "low", "out", "expired", "on_order")


@dataclass
class InventoryItem:
    """One inventory item parsed from `inventory/<name>.md`."""

    name: str
    lot: str | None = None
    qty: float | None = None
    unit: str | None = None
    expiry: str | None = None
    location: str | None = None
    vendor: str | None = None
    catalog_no: str | None = None
    last_updated: str | None = None
    status: str = "in_stock"
    protocols: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"name": self.name}
        for key, value in (
            ("lot", self.lot),
            ("qty", self.qty),
            ("unit", self.unit),
            ("expiry", self.expiry),
            ("location", self.location),
            ("vendor", self.vendor),
            ("catalog_no", self.catalog_no),
            ("last_updated", self.last_updated),
        ):
            if value is not None:
                meta[key] = value
        meta["status"] = self.status
        if self.protocols:
            meta["protocols"] = list(self.protocols)
        return meta


def inventory_dir(env: dict[str, str] | None = None) -> Path:
    return lab_mgmt_repo_root(env) / INVENTORY_SUBDIR


def item_path(name: str, env: dict[str, str] | None = None) -> Path:
    return inventory_dir(env) / f"{name}.md"


def parse_item(path: Path) -> InventoryItem:
    parsed = parse_file(path)
    meta = parsed.meta
    return InventoryItem(
        name=str(meta.get("name", path.stem)),
        lot=_opt_str(meta.get("lot")),
        qty=_opt_float(meta.get("qty")),
        unit=_opt_str(meta.get("unit")),
        expiry=_opt_str(meta.get("expiry")),
        location=_opt_str(meta.get("location")),
        vendor=_opt_str(meta.get("vendor")),
        catalog_no=_opt_str(meta.get("catalog_no")),
        last_updated=_opt_str(meta.get("last_updated")),
        status=str(meta.get("status", "in_stock")),
        protocols=list(meta.get("protocols") or []),
        body=parsed.body,
        path=path,
    )


def iter_items(env: dict[str, str] | None = None) -> list[InventoryItem]:
    root = inventory_dir(env)
    if not root.is_dir():
        return []
    out: list[InventoryItem] = []
    for child in sorted(root.iterdir()):
        if child.suffix != ".md" or child.name == "README.md":
            continue
        try:
            out.append(parse_item(child))
        except Exception:
            continue
    return out


def render_item(item: InventoryItem) -> str:
    body = item.body or _default_body(item)
    return dump_document(item.to_meta(), body)


def write_item(item: InventoryItem, env: dict[str, str] | None = None) -> Path:
    if item.status not in VALID_STATUSES:
        raise ValueError(f"unknown status {item.status!r}; must be one of {VALID_STATUSES}")
    item.last_updated = _today()
    path = item_path(item.name, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_item(item), encoding="utf-8")
    item.path = path
    return path


# ---------------------------------------------------------------------------
# Filters used by the MCP
# ---------------------------------------------------------------------------


def filter_low(items: Iterable[InventoryItem]) -> list[InventoryItem]:
    return [i for i in items if i.status in {"low", "out"}]


def filter_expiring(
    items: Iterable[InventoryItem], *, within_days: int, today: _dt.date | None = None
) -> list[InventoryItem]:
    today_d = today or _dt.date.today()
    out: list[InventoryItem] = []
    for item in items:
        if not item.expiry:
            continue
        try:
            exp = _dt.date.fromisoformat(item.expiry)
        except ValueError:
            continue
        if exp <= today_d + _dt.timedelta(days=within_days):
            out.append(item)
    return out


def filter_expired(
    items: Iterable[InventoryItem], *, today: _dt.date | None = None
) -> list[InventoryItem]:
    today_d = today or _dt.date.today()
    out: list[InventoryItem] = []
    for item in items:
        if item.status == "expired":
            out.append(item)
            continue
        if not item.expiry:
            continue
        try:
            exp = _dt.date.fromisoformat(item.expiry)
        except ValueError:
            continue
        if exp < today_d:
            out.append(item)
    return out


def filter_out(items: Iterable[InventoryItem]) -> list[InventoryItem]:
    return [i for i in items if i.status == "out"]


def provision(
    plan_reagents: Iterable[str],
    items: Iterable[InventoryItem],
    *,
    expiring_window_days: int = 30,
    today: _dt.date | None = None,
) -> dict[str, list[str]]:
    """Compute plan ∩ inventory, returning gaps and expiring lots.

    Returns a dict with three keys:
    - ``ok``: reagents in stock and within expiry.
    - ``gaps``: reagents in the plan that are missing or out of stock.
    - ``expiring``: reagents in stock but expiring within ``expiring_window_days``.
    """
    today_d = today or _dt.date.today()
    by_name: dict[str, InventoryItem] = {i.name: i for i in items}
    ok: list[str] = []
    gaps: list[str] = []
    expiring: list[str] = []
    for reagent in plan_reagents:
        item = by_name.get(reagent)
        if item is None or item.status in {"out", "on_order"}:
            gaps.append(reagent)
            continue
        if item.status == "expired":
            gaps.append(reagent)
            continue
        if item.expiry:
            try:
                exp = _dt.date.fromisoformat(item.expiry)
            except ValueError:
                ok.append(reagent)
                continue
            if exp < today_d:
                gaps.append(reagent)
                continue
            if exp <= today_d + _dt.timedelta(days=expiring_window_days):
                expiring.append(reagent)
                continue
        ok.append(reagent)
    return {"ok": ok, "gaps": gaps, "expiring": expiring}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return _dt.date.today().isoformat()


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_body(item: InventoryItem) -> str:
    return (
        f"# {item.name}\n\n"
        f"Vendor: {item.vendor or 'TBD'}  |  Catalog: {item.catalog_no or 'TBD'}\n\n"
        "## Notes\n\n_(MSDS, prep procedure, photos of label / catalog page)_\n"
    )
