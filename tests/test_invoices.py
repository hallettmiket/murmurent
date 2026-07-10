"""
Phase 4b tests: monthly invoice generator.

Covers:
  - _parse_month rejects bad strings
  - gather_invoices: groups by requester_lab, only includes requests
    whose slot.start falls in the target month
  - include_unconfirmed=False excludes rows without actual_charge
  - actual_charge.total wins over fee_at_booking.total when present
  - cancelled requests always excluded
  - subtotal = sum of charges; unconfirmed_count reports flagged rows
  - render_lab_csv produces a SUBTOTAL row + correct columns
  - render_lab_md flags unconfirmed lines
  - render_summary_md totals across labs
  - write_invoices: writes one CSV + one MD per lab + summary.md;
    commits via git ledger
  - CLI dry-run prints summary; CLI --apply writes files
  - CLI --finalised hides unconfirmed rows
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from murmurent.commands.invoice_cmd import core_invoice
from murmurent.core import invoices as INV
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _make_req(
    *, requester="@alice", lab="hallett", slot_start="2026-05-23T10:00-04:00",
    booked_total=80.0, actual_total=None, state=SR.STATE_COMPLETED,
):
    req = SR.create_request(
        core="biocore", service="itc",
        requester=requester, requester_lab=lab,
        booked_slot=SR.BookingSlot(
            start=slot_start, end=slot_start.replace("10:00", "11:00"),
        ),
        fee_at_booking=SR.FeeSnapshot(
            tier="academic_internal", unit="per_run",
            base=booked_total, total=booked_total,
        ),
    )
    if state == SR.STATE_CANCELLED:
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_CANCELLED)
    elif state == SR.STATE_COMPLETED:
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_IN_PROGRESS)
        SR.transition_request(core="biocore", request_id=req.request_id,
                                to_state=SR.STATE_COMPLETED)
    if actual_total is not None:
        SR.set_actual_charge(
            core="biocore", request_id=req.request_id,
            charge=SR.FeeSnapshot(
                tier="academic_internal", unit="per_run",
                base=booked_total, total=actual_total,
            ),
            confirmed_by="@gary",
        )
    return req


# ---- _parse_month ------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "2026", "2026/05", "26-05", "2026-13-01"])
def test_parse_month_rejects_bad(world, bad):
    with pytest.raises(INV.InvoiceError):
        INV.gather_invoices(core="biocore", month=bad)


# ---- gather_invoices ---------------------------------------------------

def test_gather_groups_by_lab(world):
    _make_req(requester="@alice", lab="hallett", actual_total=80)
    _make_req(requester="@bob",   lab="castellani", actual_total=80)
    _make_req(requester="@carol", lab="hallett", actual_total=80)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    assert [i.lab for i in invs] == ["castellani", "hallett"]
    assert len(invs[0].lines) == 1
    assert len(invs[1].lines) == 2
    assert invs[1].subtotal == 160.0


def test_gather_filters_by_month(world):
    _make_req(slot_start="2026-04-30T10:00-04:00", actual_total=80)
    _make_req(slot_start="2026-05-23T10:00-04:00", actual_total=80)
    _make_req(slot_start="2026-06-01T10:00-04:00", actual_total=80)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    assert len(invs) == 1
    assert len(invs[0].lines) == 1


def test_gather_excludes_cancelled(world):
    _make_req(actual_total=80, state=SR.STATE_COMPLETED)
    _make_req(state=SR.STATE_CANCELLED)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    assert sum(len(i.lines) for i in invs) == 1


def test_gather_uses_actual_when_confirmed(world):
    _make_req(booked_total=80, actual_total=120)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    line = invs[0].lines[0]
    assert line.is_confirmed is True
    assert line.charge == 120.0


def test_gather_falls_back_to_booked_when_unconfirmed(world):
    _make_req(booked_total=80, actual_total=None)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    line = invs[0].lines[0]
    assert line.is_confirmed is False
    assert line.charge == 80.0
    assert invs[0].unconfirmed_count == 1


def test_gather_finalised_excludes_unconfirmed(world):
    _make_req(actual_total=80)
    _make_req(actual_total=None)
    invs = INV.gather_invoices(
        core="biocore", month="2026-05", include_unconfirmed=False,
    )
    assert sum(len(i.lines) for i in invs) == 1
    assert invs[0].unconfirmed_count == 0


# ---- renderers ---------------------------------------------------------

def test_render_lab_csv_has_subtotal(world):
    _make_req(actual_total=100, lab="hallett")
    _make_req(actual_total=50, lab="hallett",
              slot_start="2026-05-24T10:00-04:00")
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    csv_text = INV.render_lab_csv(invs[0])
    assert "request_id,service" in csv_text
    assert "SUBTOTAL" in csv_text
    assert "150.00" in csv_text


def test_render_lab_md_flags_unconfirmed(world):
    _make_req(actual_total=None)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    md = INV.render_lab_md(invs[0])
    assert "actual_charge has not been confirmed yet" in md
    assert "booked fee" in md


def test_render_summary_md_totals(world):
    _make_req(lab="hallett", actual_total=100)
    _make_req(lab="castellani", actual_total=50)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    summary = INV.render_summary_md(invs, core="biocore", month="2026-05")
    assert "Total: **$150.00**" in summary
    assert "hallett" in summary and "castellani" in summary


# ---- write_invoices ----------------------------------------------------

def test_write_invoices_creates_expected_files(world):
    _make_req(lab="hallett", actual_total=100)
    _make_req(lab="castellani", actual_total=50)
    invs = INV.gather_invoices(core="biocore", month="2026-05")
    paths = INV.write_invoices(core="biocore", month="2026-05", invoices=invs)
    names = sorted(p.name for p in paths)
    assert names == ["castellani.csv", "castellani.md",
                     "hallett.csv", "hallett.md", "summary.md"]
    base = INV.invoices_dir("biocore") / "2026-05"
    assert (base / "summary.md").is_file()


# ---- CLI ---------------------------------------------------------------

def test_cli_dry_run_no_write(world):
    _make_req(lab="hallett", actual_total=100)
    runner = CliRunner()
    res = runner.invoke(core_invoice, ["--core", "biocore", "--month", "2026-05"])
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output
    assert "100.00" in res.output
    assert not (INV.invoices_dir("biocore") / "2026-05").exists()


def test_cli_apply_writes_files(world):
    _make_req(lab="hallett", actual_total=100)
    res = CliRunner().invoke(
        core_invoice,
        ["--core", "biocore", "--month", "2026-05", "--apply"],
    )
    assert res.exit_code == 0, res.output
    assert "Wrote" in res.output
    base = INV.invoices_dir("biocore") / "2026-05"
    assert (base / "hallett.csv").is_file()
    assert (base / "summary.md").is_file()


def test_cli_unknown_core(world):
    res = CliRunner().invoke(
        core_invoice, ["--core", "ghost", "--month", "2026-05"],
    )
    assert res.exit_code != 0
    assert "core not found" in res.output


def test_cli_no_billable_clean_exit(world):
    res = CliRunner().invoke(
        core_invoice, ["--core", "biocore", "--month", "2026-05"],
    )
    assert res.exit_code == 0
    assert "No billable" in res.output


def test_cli_finalised_excludes_unconfirmed(world):
    _make_req(actual_total=None)
    res = CliRunner().invoke(core_invoice,
        ["--core", "biocore", "--month", "2026-05", "--finalised"])
    assert res.exit_code == 0
    # Unconfirmed only -> nothing finalised -> "No billable".
    assert "No billable" in res.output
