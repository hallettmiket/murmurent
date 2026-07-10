"""
Tests for item 3 of the post-smoke design conversation: tier-tailored
broadcast messaging.

Covers:
  - channel_id_for(audience): valid lookup; unknown audience; channel
    not configured
  - send_broadcast: posts via injected fake; appends to month ledger
  - iter_recent: round-trips a write/read; sorts newest first; reads
    across two months
  - HTTP: POST /api/broadcast gates to PI/registrar; member 403;
    422 on missing message; 422 on bad audience
  - HTTP: GET /api/broadcast/recent (public read)
  - CLI: dry-run vs --apply; recent listing
"""

from __future__ import annotations

import datetime as _dt
import json
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner
from fastapi.testclient import TestClient

from murmurent.commands.broadcast_cmd import broadcast as cli_broadcast
from murmurent.core import broadcasts as BC
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n",
                                                       encoding="utf-8")
    for h in ("alice", "the_pi"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    # Seed registrar profile with broadcast channel mapping.
    (tmp_path / "lab_info" / "registrar.md").write_text(
        "---\n"
        "handle: '@the_pi'\n"
        "broadcast_channels:\n"
        "  everyone: C0EVERYONE\n"
        "  pis: C0PIS\n"
        "  leaders: C0LEADERS\n"
        "  admin: C0ADMIN\n"
        "---\n\n# Registrar profile\n",
        encoding="utf-8",
    )
    return tmp_path


# ---- channel_id_for -----------------------------------------------------

def test_channel_id_for_known_audience(world):
    assert BC.channel_id_for("everyone") == "C0EVERYONE"
    assert BC.channel_id_for("pis") == "C0PIS"
    assert BC.channel_id_for("LEADERS") == "C0LEADERS"  # case-insensitive


def test_channel_id_for_unknown_audience(world):
    with pytest.raises(BC.BroadcastError, match="audience must be"):
        BC.channel_id_for("students")


def test_channel_id_for_missing_channel(world, tmp_path):
    """Removed channel → clear error rather than silent drop."""
    (tmp_path / "lab_info" / "registrar.md").write_text(
        "---\nhandle: '@the_pi'\nbroadcast_channels:\n  pis: C0PIS\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(BC.BroadcastError, match="no channel configured"):
        BC.channel_id_for("everyone")


def test_channel_id_for_malformed_mapping(world, tmp_path):
    (tmp_path / "lab_info" / "registrar.md").write_text(
        "---\nhandle: '@the_pi'\nbroadcast_channels: oops\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(BC.BroadcastError, match="not a mapping"):
        BC.channel_id_for("everyone")


# ---- send_broadcast -----------------------------------------------------

def test_send_broadcast_posts_and_logs(world):
    calls = []
    def fake_poster(cid, text):
        calls.append((cid, text))
        return "https://slack.example/x/1"
    b = BC.send_broadcast(
        audience="leaders", message="Friday 2pm cores review",
        sender="@the_pi", poster=fake_poster,
    )
    assert b.audience == "leaders"
    assert b.channel_id == "C0LEADERS"
    assert b.message_link == "https://slack.example/x/1"
    assert calls == [("C0LEADERS",
                       "📣 *leaders* broadcast from @the_pi\n"
                       "Friday 2pm cores review")]
    # Ledger appended.
    rows = BC.iter_recent()
    assert len(rows) == 1
    assert rows[0].message == "Friday 2pm cores review"


def test_send_broadcast_surfaces_failed_post_and_skips_ledger(world, monkeypatch):
    # Live path (no injected poster): a rejected Slack post must raise with the
    # real error AND must not be recorded in the audit ledger.
    from murmurent.dashboard import slack_notify as SN
    monkeypatch.setattr(SN, "post_message_result",
        lambda cid, text: SN.SlackPostResult(ok=False, error="not_in_channel",
                                             detail="invite the bot into the channel"))
    with pytest.raises(BC.BroadcastError, match="not_in_channel"):
        BC.send_broadcast(audience="leaders", message="hi", sender="@the_pi")
    assert BC.iter_recent() == []          # nothing logged for a failed send


def test_send_broadcast_empty_message(world):
    with pytest.raises(BC.BroadcastError, match="message is required"):
        BC.send_broadcast(audience="pis", message="   ",
                            sender="@the_pi",
                            poster=lambda c, t: "")


def test_send_broadcast_missing_sender(world):
    with pytest.raises(BC.BroadcastError, match="sender is required"):
        BC.send_broadcast(audience="pis", message="x",
                            sender="", poster=lambda c, t: "")


def test_send_broadcast_unknown_audience(world):
    with pytest.raises(BC.BroadcastError, match="audience must be"):
        BC.send_broadcast(audience="students", message="x",
                            sender="@the_pi", poster=lambda c, t: "")


# ---- iter_recent --------------------------------------------------------

def test_iter_recent_sorts_newest_first(world):
    for i, msg in enumerate(["first", "second", "third"]):
        BC.send_broadcast(audience="everyone", message=msg,
                            sender="@the_pi", poster=lambda c, t: "")
    rows = BC.iter_recent(limit=10)
    assert [r.message for r in rows] == ["third", "second", "first"]


def test_iter_recent_respects_limit(world):
    for i in range(5):
        BC.send_broadcast(audience="pis", message=f"m{i}",
                            sender="@the_pi", poster=lambda c, t: "")
    rows = BC.iter_recent(limit=2)
    assert len(rows) == 2


def test_iter_recent_reads_prior_month(world, tmp_path, monkeypatch):
    """Hand-write a prior-month ledger; iter_recent should pick it up."""
    BC.broadcasts_dir().mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc)
    prior_yr, prior_mo = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    prior_path = BC.broadcasts_dir() / f"{prior_yr:04d}-{prior_mo:02d}.md"
    prior_path.write_text(
        "# Broadcasts\n\n"
        "## 2026-04-15T10:00:00Z · pis · @the_pi\n\n"
        "- channel: `C0PIS`\n\n"
        "> from a prior month\n",
        encoding="utf-8",
    )
    BC.send_broadcast(audience="pis", message="now-month",
                        sender="@the_pi", poster=lambda c, t: "")
    rows = BC.iter_recent(limit=10)
    msgs = [r.message for r in rows]
    assert "now-month" in msgs
    assert "from a prior month" in msgs


# ---- HTTP ---------------------------------------------------------------

def _post_json(client, url, body, **kw):
    return client.post(url, json=body, **kw)


def test_http_post_pi_passes(world):
    with patch("murmurent.core.broadcasts.send_broadcast") as m:
        m.return_value = BC.Broadcast(
            iso_ts="2026-05-26T12:00:00Z", audience="leaders",
            channel_id="C0LEADERS", sender="the_pi",
            message="x", message_link="https://slack.example/y",
        )
        client = TestClient(create_app())
        res = client.post("/api/broadcast?user=the_pi", json={
            "audience": "leaders", "message": "Friday 2pm",
        })
        assert res.status_code == 200, res.text
        assert res.json()["message_link"] == "https://slack.example/y"


def test_http_post_member_forbidden(world):
    client = TestClient(create_app())
    res = client.post("/api/broadcast?user=alice", json={
        "audience": "leaders", "message": "x",
    })
    assert res.status_code == 403


def test_http_post_empty_message_422(world):
    client = TestClient(create_app())
    res = client.post("/api/broadcast?user=the_pi", json={
        "audience": "pis", "message": "   ",
    })
    assert res.status_code == 422


def test_http_post_bad_audience_422(world):
    client = TestClient(create_app())
    res = client.post("/api/broadcast?user=the_pi", json={
        "audience": "students", "message": "x",
    })
    assert res.status_code == 422


def test_http_get_recent_public(world):
    BC.send_broadcast(audience="everyone", message="for everyone",
                        sender="@the_pi", poster=lambda c, t: "")
    client = TestClient(create_app())
    # No ?user= — public read.
    res = client.get("/api/broadcast/recent")
    assert res.status_code == 200
    assert any(b["message"] == "for everyone" for b in res.json()["broadcasts"])


# ---- CLI ---------------------------------------------------------------

def test_cli_send_dry_run_no_post(world):
    """No --apply → prints the routing, doesn't call Slack, doesn't write ledger."""
    res = CliRunner().invoke(cli_broadcast, [
        "send", "--to", "leaders", "--message", "test msg",
        "--sender", "@the_pi",
    ])
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output.lower()
    assert "C0LEADERS" in res.output
    # No ledger written.
    assert BC.iter_recent() == []


def test_cli_send_apply_writes_ledger(world):
    with patch("murmurent.core.broadcasts.send_broadcast") as m:
        m.return_value = BC.Broadcast(
            iso_ts="2026-05-26T12:00:00Z", audience="leaders",
            channel_id="C0LEADERS", sender="the_pi",
            message="hi", message_link="https://slack.example/z",
        )
        res = CliRunner().invoke(cli_broadcast, [
            "send", "--to", "leaders", "--message", "hi",
            "--sender", "@the_pi", "--apply",
        ])
        assert res.exit_code == 0, res.output
        assert "Sent" in res.output
        assert "https://slack.example/z" in res.output


def test_cli_recent_lists_writes(world):
    BC.send_broadcast(audience="everyone", message="hello world",
                        sender="@the_pi", poster=lambda c, t: "")
    res = CliRunner().invoke(cli_broadcast, ["recent", "--limit", "5"])
    assert res.exit_code == 0
    assert "hello world" in res.output
    assert "@the_pi" in res.output
