"""
Purpose: ``murmurent core-invoice`` — month-end per-lab invoice generator.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Examples:

    # Dry-run: print summary to stdout, do not write files.
    murmurent core-invoice --core biocore --month 2026-05

    # Write per-lab CSV + MD + summary.md under lab_info, commit audit.
    murmurent core-invoice --core biocore --month 2026-05 --apply

    # Finalised invoices only (exclude unconfirmed actual_charge rows).
    murmurent core-invoice --core biocore --month 2026-05 --apply --finalised
"""

from __future__ import annotations

import click

from ..core import invoices as _inv
from ..core import registrar as _reg


@click.command(
    "core-invoice",
    help="Generate per-lab invoices for a core for a given month.",
)
@click.option("--core", required=True, help="Core name (e.g. biocore).")
@click.option("--month", required=True, help="YYYY-MM (e.g. 2026-05).")
@click.option("--apply", is_flag=True, default=False,
              help="Write CSV + MD + summary; otherwise dry-run summary.")
@click.option("--finalised", is_flag=True, default=False,
              help="Exclude rows whose actual_charge is unconfirmed.")
def core_invoice(core: str, month: str, apply: bool, finalised: bool) -> None:
    try:
        reg = _reg.read_registry()
    except Exception as exc:
        raise click.ClickException(f"could not read registry: {exc}") from exc
    entry = next((c for c in reg.cores if c.name == core), None)
    if entry is None:
        raise click.ClickException(f"core not found: {core}")
    try:
        invoices = _inv.gather_invoices(
            core=core, month=month,
            include_unconfirmed=not finalised,
        )
    except _inv.InvoiceError as exc:
        raise click.ClickException(str(exc)) from exc
    if not invoices:
        click.echo(f"No billable requests for {core} in {month}.")
        return
    total = sum(i.subtotal for i in invoices)
    unconfirmed = sum(i.unconfirmed_count for i in invoices)
    for i in invoices:
        click.echo(
            f"  {i.lab:20s} "
            f"{len(i.lines):4d} line(s)  "
            f"unconfirmed: {i.unconfirmed_count:3d}  "
            f"subtotal: ${i.subtotal:>10,.2f}"
        )
    click.echo(
        f"\n{len(invoices)} labs · {sum(len(i.lines) for i in invoices)} lines · "
        f"unconfirmed: {unconfirmed} · "
        f"total: ${total:,.2f}"
    )
    if not apply:
        click.echo("\n(dry-run) Pass --apply to write CSV + MD + summary.md.")
        return
    # Pull display name from the core's lab-mgmt/lab.md when present.
    core_display = core
    try:
        from pathlib import Path
        from ..core.frontmatter import parse_file as _pf
        lab_md = Path(entry.lab_mgmt_path) / "lab.md"
        if lab_md.is_file():
            core_display = str((_pf(lab_md).meta or {}).get("name") or core)
    except Exception:
        pass
    paths = _inv.write_invoices(
        core=core, month=month, invoices=invoices,
        core_display=core_display,
    )
    click.echo(f"\nWrote {len(paths)} file(s) under {paths[0].parent}/")
