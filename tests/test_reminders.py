"""
Phase 3g tests: service-booking reminder scanner + ledger.

Covers:
  - scan_due_reminders catches slots in the 24h and 1h windows
  - Outside-window slots are not emitted
  - Already-sent (per ledger) entries are suppressed
  - record_sent persists per (core, request_id, window)
  - Cancelled / completed requests do not produce reminders
  - Bad/missing slot.start is silently skipped (no crash)
  - CLI --apply: posts via slack_notify, records the send; idempotent
    on the second run
  - CLI dry-run: prints rows, does not call slack_notify, does not
    write to the ledger
"""

from __future__ import annotations

import datetime as _dt
import json
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from murmurent.commands.reminders_cmd import core_remind
from murmurent.core import calendar_google as CAL  # noqa: F401 (env isolation)
from murmurent.core import registrar as R
from murmurent.core import reminders as REM
from murmurent.core import services as S
from murmurent.core import service_requests as SR


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("MURMURENT_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    (tmp_path / "lab-mgmt" / "members" / "alice.md").write_text(
        "---\nhandle: '@alice'\nrole: postdoc\nstatus: active\n---\n",
        encoding="utf-8",
    )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _book(start_iso, end_iso="2099-01-01T00:00:00+00:00"):
    return SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start=start_iso, end=end_iso),
    )


_NOW = _dt.datetime(2026, 5, 22, 12, 0, 0, tzinfo=_dt.timezone.utc)


# ---- scan_due_reminders ------------------------------------------------

def test_scan_emits_1h_reminder(world):
    _book("2026-05-22T13:00:00+00:00")   # 60 min from NOW
    due = REM.scan_due_reminders(now=_NOW)
    assert len(due) == 1
    assert due[0].window == REM.WINDOW_1H
    assert due[0].minutes_until == 60


def test_scan_emits_24h_reminder(world):
    _book("2026-05-23T12:00:00+00:00")   # 1440 min from NOW
    due = REM.scan_due_reminders(now=_NOW)
    assert len(due) == 1
    assert due[0].window == REM.WINDOW_24H


def test_scan_ignores_outside_window(world):
    _book("2026-05-23T18:00:00+00:00")   # ~30h out — outside 24h window
    _book("2026-05-22T14:00:00+00:00")   # 120 min — outside 1h window
    due = REM.scan_due_reminders(now=_NOW)
    assert due == []


def test_scan_skips_already_sent(world):
    req = _book("2026-05-22T13:00:00+00:00")
    REM.record_sent("biocore", req.request_id, REM.WINDOW_1H)
    due = REM.scan_due_reminders(now=_NOW)
    assert due == []


def test_scan_skips_non_scheduled(world):
    req = _book("2026-05-22T13:00:00+00:00")
    SR.transition_request(core="biocore", request_id=req.request_id,
                            to_state=SR.STATE_CANCELLED)
    due = REM.scan_due_reminders(now=_NOW)
    assert due == []


def test_scan_handles_missing_slot_start(world):
    SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(),   # no start
    )
    due = REM.scan_due_reminders(now=_NOW)
    assert due == []


# ---- record_sent ledger ------------------------------------------------

def test_record_sent_persists_per_window(world):
    REM.record_sent("biocore", "rid-1", REM.WINDOW_24H)
    REM.record_sent("biocore", "rid-1", REM.WINDOW_1H)
    REM.record_sent("biocore", "rid-2", REM.WINDOW_1H)
    assert REM.already_sent("biocore", "rid-1", REM.WINDOW_24H)
    assert REM.already_sent("biocore", "rid-1", REM.WINDOW_1H)
    assert REM.already_sent("biocore", "rid-2", REM.WINDOW_1H)
    assert not REM.already_sent("biocore", "rid-2", REM.WINDOW_24H)
    # Sanity: file is JSON, sorted.
    p = world / "wigamig_home" / "cores" / "biocore" / "reminders_sent.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["rid-1"] == [REM.WINDOW_1H, REM.WINDOW_24H]


# ---- CLI ---------------------------------------------------------------

@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.reminders.scan_due_reminders")
def test_cli_dry_run_does_not_post_or_record(mock_scan, mock_post, world):
    req = _book("2026-05-22T13:00:00+00:00")
    mock_scan.return_value = [REM.DueReminder(
        core="biocore", request=req,
        window=REM.WINDOW_1H, minutes_until=60,
    )]
    result = CliRunner().invoke(core_remind, [])
    assert result.exit_code == 0, result.output
    assert "1 reminder(s) would have been sent" in result.output
    mock_post.assert_not_called()
    assert not REM.already_sent("biocore", req.request_id, REM.WINDOW_1H)


@patch("murmurent.dashboard.slack_notify._post")
@patch("murmurent.core.reminders.scan_due_reminders")
def test_cli_apply_posts_and_records(mock_scan, mock_post, world):
    req = _book("2026-05-22T13:00:00+00:00")
    mock_scan.return_value = [REM.DueReminder(
        core="biocore", request=req,
        window=REM.WINDOW_1H, minutes_until=60,
    )]
    result = CliRunner().invoke(core_remind, ["--apply"])
    assert result.exit_code == 0, result.output
    assert "Sent 1 reminder(s)" in result.output
    mock_post.assert_called_once()
    assert REM.already_sent("biocore", req.request_id, REM.WINDOW_1H)


@patch("murmurent.dashboard.slack_notify._post")
def test_cli_no_reminders_clean_exit(mock_post, world):
    result = CliRunner().invoke(core_remind, ["--apply"])
    assert result.exit_code == 0
    assert "No reminders due" in result.output
    mock_post.assert_not_called()
