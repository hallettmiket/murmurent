"""Tests for the Phase-5 lab-mgmt audit chain.

Covers ``audit_log`` module (write + read + humanize), the SEA-action
integration (each successful transition writes a row), and the
``_notifs`` source-switching (audit chain wins when populated).
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from wigamig.commands import project_cmd, sea_cmd
from wigamig.dashboard import audit_log, sea_actions, snapshot


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "audit").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def project(world):
    project_cmd.cmd_new(
        "p_audit",
        charter_path=None,
        members_csv="@allie,@bob",
        description="x",
        sensitivity="standard",
        lead="@allie",
        skip_github=True,
    )
    sea_cmd.cmd_request(
        project_name="p_audit", to_target="@bob", kind="analysis",
        description="y", from_handle="@allie",
    )


# ---------------------------------------------------------------------------
# audit_log.write_event + read_recent
# ---------------------------------------------------------------------------


def test_write_event_creates_dated_jsonl(world):
    when = _dt.datetime(2026, 5, 8, 14, 23, 0, tzinfo=_dt.timezone.utc)
    path = audit_log.write_event(
        actor="allie", kind="sea.claim", project="p_audit",
        target="sea/1", summary="@allie claimed SEA #1", when=when,
    )
    assert path.name == "2026-05-08.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert rows[0]["actor"] == "@allie"
    assert rows[0]["kind"] == "sea.claim"


def test_write_event_appends_multiple_lines(world):
    audit_log.write_event(actor="a", kind="sea.claim", project="p", target="sea/1", summary="x")
    audit_log.write_event(actor="a", kind="sea.complete", project="p", target="sea/1", summary="y")
    files = list((world / "lab-mgmt" / "audit").glob("*.jsonl"))
    assert len(files) == 1
    assert len(files[0].read_text().strip().splitlines()) == 2


def test_read_recent_returns_newest_first(world):
    yest = _dt.datetime(2026, 5, 7, 10, 0, tzinfo=_dt.timezone.utc)
    today = _dt.datetime(2026, 5, 8, 10, 0, tzinfo=_dt.timezone.utc)
    audit_log.write_event(actor="a", kind="x", project="p", target="t", summary="yesterday", when=yest)
    audit_log.write_event(actor="a", kind="x", project="p", target="t", summary="today", when=today)
    events = audit_log.read_recent(today=_dt.date(2026, 5, 8))
    assert events[0].summary == "today"
    assert events[1].summary == "yesterday"


def test_read_recent_respects_limit(world):
    for i in range(20):
        audit_log.write_event(
            actor="a", kind="sea.claim", project="p", target=f"sea/{i}",
            summary=f"event {i}",
            when=_dt.datetime(2026, 5, 8, 10, i, tzinfo=_dt.timezone.utc),
        )
    events = audit_log.read_recent(limit=5, today=_dt.date(2026, 5, 8))
    assert len(events) == 5


def test_has_any_events_false_when_empty(world):
    assert not audit_log.has_any_events(today=_dt.date(2026, 5, 8))


def test_has_any_events_true_after_write(world):
    audit_log.write_event(actor="a", kind="x", project="p", target="t", summary="s")
    assert audit_log.has_any_events()


def test_read_recent_skips_unparseable_lines(world):
    path = world / "lab-mgmt" / "audit" / "2026-05-08.jsonl"
    path.write_text(
        "{not json\n"
        '{"ts":"2026-05-08T10:00:00+00:00","actor":"@a","kind":"x","project":"p","target":"t","summary":"ok"}\n'
        "garbage line\n",
        encoding="utf-8",
    )
    events = audit_log.read_recent(today=_dt.date(2026, 5, 8))
    assert len(events) == 1
    assert events[0].summary == "ok"


# ---------------------------------------------------------------------------
# humanize()
# ---------------------------------------------------------------------------


def test_humanize_just_now(world):
    now = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)
    assert audit_log.humanize(now, now=now) == "just now"


def test_humanize_minutes_ago(world):
    now = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)
    when = now - _dt.timedelta(minutes=15)
    assert audit_log.humanize(when, now=now) == "15m ago"


def test_humanize_hours_today_returns_hhmm(world):
    now = _dt.datetime(2026, 5, 8, 14, 0, 0, tzinfo=_dt.timezone.utc)
    when = _dt.datetime(2026, 5, 8, 8, 14, 0, tzinfo=_dt.timezone.utc)
    out = audit_log.humanize(when, now=now)
    assert ":" in out  # local-time formatting


def test_humanize_yesterday(world):
    now = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)
    when = _dt.datetime(2026, 5, 7, 10, 0, 0, tzinfo=_dt.timezone.utc)
    assert audit_log.humanize(when, now=now) == "yesterday"


def test_humanize_days_ago(world):
    now = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)
    when = _dt.datetime(2026, 5, 5, 12, 0, 0, tzinfo=_dt.timezone.utc)
    assert audit_log.humanize(when, now=now) == "3d ago"


# ---------------------------------------------------------------------------
# sea_actions integration
# ---------------------------------------------------------------------------


def test_sea_action_writes_audit_row(world, project):
    sea_actions.apply_action(
        project="p_audit", sea_id=1, action="claim", actor="bob"
    )
    events = audit_log.read_recent()
    assert any(e.kind == "sea.claim" and e.target == "sea/1" for e in events)
    summary = next(e for e in events if e.kind == "sea.claim").summary
    assert "@bob" in summary
    assert "SEA #1" in summary


def test_sea_action_writes_delivery_in_summary(world, project):
    sea_actions.apply_action(project="p_audit", sea_id=1, action="claim", actor="bob")
    sea_actions.apply_action(
        project="p_audit", sea_id=1, action="complete", actor="bob",
        delivery="findings/x.md",
    )
    events = audit_log.read_recent()
    complete = next(e for e in events if e.kind == "sea.complete")
    assert "findings/x.md" in complete.summary


def test_failed_actions_do_not_log(world, project):
    """Forbidden / conflict transitions should NOT create audit rows."""
    with pytest.raises(sea_actions.SeaForbidden):
        sea_actions.apply_action(
            project="p_audit", sea_id=1, action="claim", actor="cassie"
        )
    assert not audit_log.has_any_events()


# ---------------------------------------------------------------------------
# _notifs source-switching
# ---------------------------------------------------------------------------


def test_notifs_falls_back_when_no_audit_rows(world, project):
    """No audit rows -> derived from SEA timestamps (or empty)."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    # No transitions yet, no claimed_at etc, so empty list.
    assert resp.notifs == []


def test_notifs_uses_audit_chain_when_populated(world, project):
    sea_actions.apply_action(project="p_audit", sea_id=1, action="claim", actor="bob")
    resp = snapshot.build_response("allie", today=_dt.date.today())
    assert resp.notifs, "expected at least one notif"
    assert any("SEA #1" in n.text for n in resp.notifs)


def test_notifs_humanizes_audit_times(world, project):
    sea_actions.apply_action(project="p_audit", sea_id=1, action="claim", actor="bob")
    resp = snapshot.build_response("allie", today=_dt.date.today())
    # Today's event: time should be "just now" or "Nm ago" or HH:MM, never an ISO date.
    assert all(":" in n.time or "just now" in n.time or "ago" in n.time for n in resp.notifs)
