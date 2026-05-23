"""
Purpose: Monthly invoice generation for a core's billable requests.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Walks every completed request on a core whose slot.start falls in a
given calendar month, groups by requesting lab, and writes:

  <lab_info>/cores/<core>/lab-mgmt/invoices/<YYYY-MM>/
    <lab>.csv                 # machine-readable; one row per request
    <lab>.md                  # human-readable per-lab invoice
    summary.md                # totals + flags across all labs

Per the plan (docs/cores_plan.md §7): wigamig is a billing-data
*producer*, not a billing system. A human routes the artifacts to
Western's actual finance system (Path 1 today; CSV shape designed
for Path 2 upload-to-expense-tool migration).

Charge precedence: ``actual_charge.total`` when confirmed, otherwise
``fee_at_booking.total`` (with the row flagged as ``unconfirmed`` so
the leader can see what still needs sign-off before the month closes).

PDF rendering deferred — Markdown invoices are diff-able + easier to
edit by hand; PDF conversion can be a pandoc post-step.
"""

from __future__ import annotations

import csv
import datetime as _dt
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import service_requests as _sr
from .registrar import (
    _git_commit_all, _git_init_if_needed, lab_info_root,
)


_MONTH_RE = _re.compile(r"^(\d{4})-(\d{2})$")


class InvoiceError(RuntimeError):
    """Invoice generation failed (bad month string, unknown core, ...)."""


@dataclass
class InvoiceLine:
    """One billable request as it appears on an invoice."""

    request_id: str
    service: str
    requester: str
    slot_start: str
    slot_end: str
    state: str                       # at time of invoicing
    tier: str
    unit: str
    base: float
    modifiers: list[str] = field(default_factory=list)
    charge: float = 0.0              # the effective total (actual or booked)
    is_confirmed: bool = False       # True iff actual_charge present
    note: str = ""                   # actual_charge_note when present


@dataclass
class LabInvoice:
    """All InvoiceLines for one requesting lab in one month."""

    core: str
    lab: str
    month: str                       # 'YYYY-MM'
    lines: list[InvoiceLine] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(l.charge for l in self.lines), 2)

    @property
    def unconfirmed_count(self) -> int:
        return sum(1 for l in self.lines if not l.is_confirmed)


def invoices_dir(core: str, env: dict[str, str] | None = None) -> Path:
    """``<lab_info>/cores/<core>/lab-mgmt/invoices/``."""
    return lab_info_root(env) / "cores" / core / "lab-mgmt" / "invoices"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _parse_month(month: str) -> tuple[int, int]:
    m = _MONTH_RE.match(month or "")
    if not m:
        raise InvoiceError(
            f"month must be 'YYYY-MM' (got {month!r})"
        )
    yr, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        raise InvoiceError(
            f"month component must be 01..12 (got {month!r})"
        )
    return yr, mo


def _slot_month_matches(slot_start: str, year: int, month: int) -> bool:
    if not slot_start:
        return False
    try:
        dt = _dt.datetime.fromisoformat(slot_start)
    except ValueError:
        return False
    return dt.year == year and dt.month == month


def _line_from_request(req) -> InvoiceLine:
    confirmed = req.actual_charge is not None
    fee = req.actual_charge if confirmed else req.fee_at_booking
    return InvoiceLine(
        request_id=req.request_id,
        service=req.service,
        requester=req.requester,
        slot_start=req.booked_slot.start,
        slot_end=req.booked_slot.end,
        state=req.state,
        tier=fee.tier,
        unit=fee.unit,
        base=float(fee.base),
        modifiers=[m.get("name") for m in (fee.modifiers_applied or []) if m.get("name")],
        charge=float(fee.total),
        is_confirmed=confirmed,
        note=req.actual_charge_note if confirmed else "",
    )


def gather_invoices(
    *,
    core: str,
    month: str,
    include_unconfirmed: bool = True,
    env: dict[str, str] | None = None,
) -> list[LabInvoice]:
    """Build one LabInvoice per requesting lab for ``core`` in
    ``month`` (YYYY-MM).

    By default includes requests whose actual_charge is *not* yet
    confirmed (using fee_at_booking + flagged) so leaders can see the
    pending pipeline during the month. Set ``include_unconfirmed=False``
    to restrict to fully-confirmed lines (typical for month-end finalise).
    """
    year, mo = _parse_month(month)
    by_lab: dict[str, LabInvoice] = {}
    # We pull every state EXCEPT cancelled; an in-progress slot in the
    # billing month is still billable if the leader confirms a charge.
    # The default flow ships completed-only via include_unconfirmed=False.
    for req in _sr.iter_requests(core, env=env, include_terminal=True):
        if req.state == _sr.STATE_CANCELLED:
            continue
        if not _slot_month_matches(req.booked_slot.start, year, mo):
            continue
        confirmed = req.actual_charge is not None
        if not confirmed and not include_unconfirmed:
            continue
        line = _line_from_request(req)
        lab = (req.requester_lab or "unknown").lower()
        inv = by_lab.setdefault(lab, LabInvoice(core=core, lab=lab, month=month))
        inv.lines.append(line)
    # Stable ordering: sort lines by slot.start asc within each lab.
    for inv in by_lab.values():
        inv.lines.sort(key=lambda l: l.slot_start or "")
    return [by_lab[k] for k in sorted(by_lab)]


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_lab_csv(inv: LabInvoice) -> str:
    """One row per InvoiceLine; columns shaped for Western expense-tool
    upload (Path 2 in the plan)."""
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "request_id", "service", "requester", "slot_start", "slot_end",
        "tier", "unit", "base", "modifiers", "charge",
        "confirmed", "note",
    ])
    for l in inv.lines:
        w.writerow([
            l.request_id, l.service, l.requester,
            l.slot_start, l.slot_end,
            l.tier, l.unit, f"{l.base:.2f}",
            ";".join(l.modifiers), f"{l.charge:.2f}",
            "yes" if l.is_confirmed else "no",
            l.note,
        ])
    w.writerow([])
    w.writerow(["", "", "", "", "", "", "", "", "SUBTOTAL",
                f"{inv.subtotal:.2f}", "", ""])
    return buf.getvalue()


def render_lab_md(inv: LabInvoice, core_display: str = "") -> str:
    """Human-readable per-lab invoice."""
    lines = [
        f"# Invoice — {core_display or inv.core} — {inv.lab} lab — {inv.month}",
        "",
        f"Lines: {len(inv.lines)} · "
        f"Confirmed: {len(inv.lines) - inv.unconfirmed_count} / {len(inv.lines)} · "
        f"Subtotal: **${inv.subtotal:.2f}**",
        "",
        "| request | service | requester | start | charge | confirmed | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for l in inv.lines:
        lines.append(
            f"| `{l.request_id}` | {l.service} | {l.requester} | "
            f"{l.slot_start} | ${l.charge:.2f} | "
            f"{'✓' if l.is_confirmed else '✗ (booked fee)'} | "
            f"{l.note} |"
        )
    if inv.unconfirmed_count:
        lines += [
            "",
            f"> ⚠ {inv.unconfirmed_count} line(s) use the booking-time fee "
            "because actual_charge has not been confirmed yet. Confirm "
            "via the core dashboard or `PATCH "
            "/api/core/<core>/requests/<id>/actual_charge` before finalising.",
        ]
    return "\n".join(lines) + "\n"


def render_summary_md(
    invoices: list[LabInvoice], *,
    core: str, month: str, core_display: str = "",
) -> str:
    total = round(sum(i.subtotal for i in invoices), 2)
    unconfirmed = sum(i.unconfirmed_count for i in invoices)
    lines = [
        f"# Invoice summary — {core_display or core} — {month}",
        "",
        f"Labs billed: {len(invoices)} · "
        f"Lines: {sum(len(i.lines) for i in invoices)} · "
        f"Unconfirmed: {unconfirmed} · "
        f"Total: **${total:.2f}**",
        "",
        "| lab | lines | unconfirmed | subtotal |",
        "|---|---:|---:|---:|",
    ]
    for i in invoices:
        lines.append(
            f"| {i.lab} | {len(i.lines)} | {i.unconfirmed_count} | "
            f"${i.subtotal:.2f} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_invoices(
    *,
    core: str,
    month: str,
    invoices: list[LabInvoice],
    core_display: str = "",
    env: dict[str, str] | None = None,
) -> list[Path]:
    """Persist invoices to ``<lab_info>/cores/<core>/lab-mgmt/invoices/<month>/``.

    Files written: ``<lab>.csv`` + ``<lab>.md`` per lab + ``summary.md``.
    Returns the list of written paths in sorted order. Commits via the
    lab_info git ledger for audit-trail.
    """
    base = invoices_dir(core, env) / month
    base.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for inv in invoices:
        csv_path = base / f"{inv.lab}.csv"
        md_path  = base / f"{inv.lab}.md"
        csv_path.write_text(render_lab_csv(inv), encoding="utf-8")
        md_path.write_text(render_lab_md(inv, core_display=core_display),
                            encoding="utf-8")
        written += [csv_path, md_path]
    summary = base / "summary.md"
    summary.write_text(
        render_summary_md(invoices, core=core, month=month,
                           core_display=core_display),
        encoding="utf-8",
    )
    written.append(summary)
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"core {core}: invoices for {month} "
        f"({len(invoices)} labs, ${sum(i.subtotal for i in invoices):.2f})")
    return sorted(written)


__all__ = [
    "InvoiceError",
    "InvoiceLine", "LabInvoice",
    "invoices_dir",
    "gather_invoices",
    "render_lab_csv", "render_lab_md", "render_summary_md",
    "write_invoices",
]
