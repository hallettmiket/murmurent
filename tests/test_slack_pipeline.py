"""Tests for the Phase-11 Slack mirror + distillation pipeline.

Slack and Anthropic clients are mocked — no network required. Covers:
  - core.slack_mirror: token resolution, opt-in marker, fetch, render
  - core.slack_distill: prompt building, draft writing, status: draft
  - drafts gate in snapshot._oracle_recent + _oracle_drafts
  - HTTP endpoint POST /api/oracle/{slug}/{action}
"""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.commands import project_cmd
from wigamig.core import slack_distill as distill
from wigamig.core import slack_mirror as mirror
from wigamig.dashboard import snapshot


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # force StubLLM
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    project_cmd.cmd_new(
        "p_slk", charter_path=None, members_csv="@the_pi,@allie",
        description="x", sensitivity="standard", lead="@the_pi",
        skip_github=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_token_from_env_wins(monkeypatch):
    monkeypatch.setenv("WIGAMIG_SLACK_TOKEN", "xoxb-abc")
    assert mirror.resolve_token() == "xoxb-abc"


def test_token_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("WIGAMIG_SLACK_TOKEN", raising=False)
    monkeypatch.setattr(mirror, "TOKEN_FILE", tmp_path / "absent")
    with pytest.raises(mirror.SlackMirrorError):
        mirror.resolve_token()


# ---------------------------------------------------------------------------
# Opt-in marker
# ---------------------------------------------------------------------------


class _MockClient:
    """In-memory mock implementing the SlackClientLike protocol."""

    def __init__(self, *, channels=None, history=None, users=None, replies=None):
        self._channels = channels or []
        self._history = history or {}  # channel_id -> list[message dict]
        self._users = users or {}      # user_id -> handle
        self._replies = replies or {}  # (channel_id, ts) -> list[message dict]

    def conversations_list(self, *, types: str = "") -> dict:
        return {"channels": self._channels}

    def conversations_info(self, *, channel: str) -> dict:
        for c in self._channels:
            if c["id"] == channel:
                return {"channel": c}
        return {"channel": {"topic": {"value": ""}}}

    def conversations_history(self, *, channel: str, oldest, latest, limit=1000):
        return {"messages": list(self._history.get(channel, []))}

    def conversations_replies(self, *, channel: str, ts: str, oldest="", latest=""):
        return {"messages": list(self._replies.get((channel, ts), []))}

    def users_info(self, *, user: str) -> dict:
        return {"user": {"profile": {"display_name": self._users.get(user, user)}}}


def test_list_monitored_channels_filters_by_marker(world):
    client = _MockClient(channels=[
        {"id": "C1", "name": "proj_dcis", "topic": {"value": "DCIS team [oracle:on]"}},
        {"id": "C2", "name": "general",   "topic": {"value": "everyone hangs out"}},
    ])
    out = mirror.list_monitored_channels(client)
    assert [c["name"] for c in out] == ["proj_dcis"]


def test_is_oracle_on(world):
    client = _MockClient(channels=[
        {"id": "C1", "name": "proj_dcis", "topic": {"value": "[oracle:on]"}},
        {"id": "C2", "name": "noop",      "topic": {"value": "x"}},
    ])
    assert mirror.is_oracle_on(client, "C1") is True
    assert mirror.is_oracle_on(client, "C2") is False


# ---------------------------------------------------------------------------
# Fetch + render
# ---------------------------------------------------------------------------


def test_fetch_day_normalises_users_and_threads(world):
    ts1 = "1714128842.001234"  # ~2024-04-26 some time
    ts2 = "1714128942.005678"
    client = _MockClient(
        history={"C1": [
            {"ts": ts1, "user": "U1", "text": "hello", "thread_ts": ts1},  # thread parent
            {"ts": ts2, "user": "U2", "text": "follow-up"},
        ]},
        users={"U1": "allie", "U2": "bob"},
        replies={("C1", ts1): [
            {"ts": ts1, "user": "U1", "text": "hello"},  # parent itself, skipped
            {"ts": "1714128890.000000", "user": "U2", "text": "reply", "thread_ts": ts1},
        ]},
    )
    msgs = mirror.fetch_day(client, channel_id="C1", date=_dt.date(2024, 4, 26))
    handles = [m.user_handle for m in msgs]
    assert "@allie" in handles
    assert "@bob" in handles
    # thread parent flagged
    parent = next(m for m in msgs if m.user_handle == "@allie" and m.text == "hello")
    assert parent.is_thread_parent is True


def test_render_mirror_has_frontmatter_and_body(world):
    msgs = [
        mirror.Message(ts="1.0", iso_local="2024-04-26T09:14:00",
                       user_handle="@allie", text="run 17 fastqs look fine."),
        mirror.Message(ts="2.0", iso_local="2024-04-26T09:18:00",
                       user_handle="@bob",   text="confirmed — same chrM artefact."),
    ]
    text = mirror.render_mirror(channel_name="proj_dcis", date=_dt.date(2024, 4, 26),
                                messages=msgs, workspace="hallett-lab.slack.com")
    assert "channel: proj_dcis" in text
    assert "message_count: 2" in text
    assert "## 09:14 · @allie" in text
    assert "run 17 fastqs look fine." in text


def test_mirror_channel_day_writes_file(world, tmp_path):
    client = _MockClient(
        channels=[{"id": "C1", "name": "proj_dcis", "topic": {"value": "[oracle:on]"}}],
        history={"C1": [{"ts": "1714128842.001234", "user": "U1", "text": "hi"}]},
        users={"U1": "allie"},
    )
    path = mirror.mirror_channel_day(
        channel_name="proj_dcis", channel_id="C1",
        date=_dt.date(2024, 4, 26), client=client,
    )
    assert path.is_file()
    assert "proj_dcis" in path.read_text()


def test_mirror_channel_day_refuses_non_optin(world):
    client = _MockClient(
        channels=[{"id": "C1", "name": "proj_dcis", "topic": {"value": "no marker"}}],
    )
    with pytest.raises(mirror.SlackMirrorError):
        mirror.mirror_channel_day(
            channel_name="proj_dcis", channel_id="C1",
            date=_dt.date(2024, 4, 26), client=client,
        )


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


class _MockLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, prompt: str, system: str = "") -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self.response


def _seed_mirror(world, channel="proj-x", date=_dt.date(2026, 5, 8)) -> "Path":
    msgs = [
        mirror.Message(ts="1.0", iso_local=f"{date.isoformat()}T09:14:00",
                       user_handle="@allie", text="GRCh38.p14 fixes the chrM bug."),
        mirror.Message(ts="2.0", iso_local=f"{date.isoformat()}T09:18:00",
                       user_handle="@bob",   text="Confirmed; switching reference."),
    ]
    return mirror.write_mirror(channel_name=channel, date=date, messages=msgs)


def test_distill_writes_drafts_with_status_draft(world):
    path = _seed_mirror(world)
    response = (
        "---\n"
        "title: 'GRCh38.p14 fixes chrM'\n"
        "author: '@wigamig-oracle'\n"
        "date: 2026-05-08\n"
        "tags: [reference-genome]\n"
        "status: draft\n"
        "---\n\n"
        "# GRCh38.p14 fixes chrM\n\n"
        "Patch fixes the issue from earlier in the year.\n"
    )
    result = distill.distill_mirror(
        mirror_path=path, channel_name="proj-x",
        date=_dt.date(2026, 5, 8), llm=_MockLLM(response),
    )
    assert len(result.drafts_written) == 1
    text = result.drafts_written[0].read_text()
    assert "status: draft" in text


def test_distill_returns_zero_drafts_when_no_oracle_entries(world):
    path = _seed_mirror(world)
    result = distill.distill_mirror(
        mirror_path=path, channel_name="proj-x",
        date=_dt.date(2026, 5, 8),
        llm=_MockLLM("NO_ORACLE_ENTRIES_TODAY"),
    )
    assert result.drafts_written == []


def test_distill_handles_multiple_blocks(world):
    path = _seed_mirror(world)
    response = (
        "---\n"
        "title: 'A'\n"
        "status: draft\n"
        "---\n# A\n\nfirst.\n"
        "---ORACLE-ENTRY-SEPARATOR---\n"
        "---\n"
        "title: 'B'\n"
        "status: draft\n"
        "---\n# B\n\nsecond.\n"
    )
    result = distill.distill_mirror(
        mirror_path=path, channel_name="proj-x",
        date=_dt.date(2026, 5, 8), llm=_MockLLM(response),
    )
    assert len(result.drafts_written) == 2


def test_force_status_draft_inserts_when_missing(world):
    text = "---\ntitle: x\n---\n\n# Body"
    out = distill._force_status_draft(text)
    assert "status: draft" in out


def test_stub_llm_used_without_anthropic_key(world, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = distill.make_llm()
    assert isinstance(llm, distill.StubLLM)


# ---------------------------------------------------------------------------
# Drafts gate in snapshot
# ---------------------------------------------------------------------------


def _seed_oracle_file(world, *, slug: str, status: str, **extras):
    odir = world / "lab-mgmt" / "oracle"
    odir.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"title: '{slug}'", f"status: {status}", "author: '@wigamig-oracle'",
          "date: 2026-05-08"]
    for k, v in extras.items():
        fm.append(f"{k}: {v}")
    fm += ["---", "", "Body of " + slug]
    (odir / f"{slug}.md").write_text("\n".join(fm), encoding="utf-8")


def test_oracle_recent_excludes_drafts_for_members(world):
    _seed_oracle_file(world, slug="published_one", status="published")
    _seed_oracle_file(world, slug="draft_one", status="draft")
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    titles = {e.title for e in resp.oracle_recent}
    assert "published_one" in titles
    assert "draft_one" not in titles


def test_oracle_drafts_visible_to_pi_only(world):
    _seed_oracle_file(world, slug="d1", status="draft")
    pi_resp = snapshot.build_response("the_pi", today=_dt.date(2026, 5, 8))
    member_resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert len(pi_resp.oracle_drafts) == 1
    assert member_resp.oracle_drafts == []


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


def test_approve_draft_flips_status(world):
    _seed_oracle_file(world, slug="d1", status="draft")
    path = world / "lab-mgmt" / "oracle" / "d1.md"
    distill.approve_draft(path, approver="the_pi")
    text = path.read_text()
    assert "status: published" in text
    assert "approved_by: '@the_pi'" in text or "approved_by: \"@the_pi\"" in text or "approved_by: '@the_pi'" in text


def test_decline_draft_requires_reason(world):
    _seed_oracle_file(world, slug="d1", status="draft")
    path = world / "lab-mgmt" / "oracle" / "d1.md"
    with pytest.raises(distill.DistillError):
        distill.decline_draft(path, reason="")


def test_iter_drafts_returns_only_drafts(world):
    _seed_oracle_file(world, slug="p1", status="published")
    _seed_oracle_file(world, slug="d1", status="draft")
    _seed_oracle_file(world, slug="d2", status="draft")
    drafts = distill.iter_drafts()
    names = {p.name for p in drafts}
    assert names == {"d1.md", "d2.md"}


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from wigamig.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_approve_pi_only(world):
    _seed_oracle_file(world, slug="d1", status="draft")
    client = _client()
    res_member = client.post("/api/oracle/d1/approve?user=allie", json={})
    assert res_member.status_code == 403
    res_pi = client.post("/api/oracle/d1/approve?user=the_pi", json={})
    assert res_pi.status_code == 200


def test_endpoint_approve_404_for_unknown(world):
    client = _client()
    res = client.post("/api/oracle/nope/approve?user=the_pi", json={})
    assert res.status_code == 404


def test_endpoint_approve_409_when_not_draft(world):
    _seed_oracle_file(world, slug="published_thing", status="published")
    client = _client()
    res = client.post("/api/oracle/published_thing/approve?user=the_pi", json={})
    assert res.status_code == 409


def test_endpoint_decline_requires_reason(world):
    _seed_oracle_file(world, slug="d1", status="draft")
    client = _client()
    res = client.post("/api/oracle/d1/decline?user=the_pi", json={})
    assert res.status_code == 422
