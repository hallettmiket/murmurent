"""
Tests for the join-flow Slack routing (Phase 2 communication backbone).

Covers:
  - notify_new_request posts a summary to the *admin* channel
  - notify_decision DMs the requester (approve / decline / failed wording)
  - every path no-ops (returns False, no poster call) when no Slack token
    is configured — a join must never depend on Slack
  - the wiring in file_request / approve / decline is best-effort: it never
    raises even if the notifier blows up
"""

from __future__ import annotations

import pytest

from wigamig.core import join_notify as JN
from wigamig.core import join_requests as JR
from wigamig.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                        fake_home / ".wigamig" / "registrar")
    return tmp_path


def _req(**kw):
    base = dict(
        id=1, kind="lab", requester_email="pi@demo.edu",
        proposed_name="newlab", proposed_pi="@newpi",
        institution_affiliation="Demo U", justification="a new lab",
        state="pending",
    )
    base.update(kw)
    return JR.JoinRequest(**base)


# ---- token gating ------------------------------------------------------

def test_new_request_noop_without_token(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: False)
    calls = []
    ok = JN.notify_new_request(_req(), poster=lambda c, t: calls.append((c, t)) or True)
    assert ok is False
    assert calls == []


def test_decision_noop_without_token(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: False)
    calls = []
    ok = JN.notify_decision(_req(state="approved"),
                            poster=lambda c, t: calls.append((c, t)) or True)
    assert ok is False
    assert calls == []


# ---- new request → admin channel --------------------------------------

def test_new_request_posts_to_admin_channel(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    seen = {}
    def poster(channel, text):
        seen["channel"] = channel
        seen["text"] = text
        return True
    ok = JN.notify_new_request(
        _req(), poster=poster,
        channel_resolver=lambda aud, env=None: (seen.setdefault("aud", aud), "C0ADMIN")[1],
    )
    assert ok is True
    assert seen["aud"] == "admin"          # routed to the admin audience
    assert seen["channel"] == "C0ADMIN"
    assert "New join request" in seen["text"]
    assert "newlab" in seen["text"] and "@newpi" in seen["text"]


def test_new_request_noop_when_admin_channel_unconfigured(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    def resolver(aud, env=None):
        raise RuntimeError("broadcast_channels not configured")
    posted = []
    ok = JN.notify_new_request(_req(), poster=lambda c, t: posted.append(1) or True,
                               channel_resolver=resolver)
    assert ok is False
    assert posted == []


# ---- decision → DM the requester --------------------------------------

@pytest.mark.parametrize("state,marker", [
    ("approved", "approved"),
    ("provisioned", "approved"),
    ("declined", "declined"),
    ("failed", "snag"),
])
def test_decision_dms_requester(world, monkeypatch, state, marker):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    seen = {}
    def poster(channel, text):
        seen["channel"] = channel
        seen["text"] = text
        return True
    req = _req(state=state, decline_reason="not this cycle" if state == "declined" else "")
    ok = JN.notify_decision(req, poster=poster,
                            user_resolver=lambda email: "U0JOINER")
    assert ok is True
    assert seen["channel"] == "U0JOINER"   # DM opened against the user id
    assert marker in seen["text"].lower()
    if state == "declined":
        assert "not this cycle" in seen["text"]


def test_decision_noop_when_requester_not_in_workspace(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    posted = []
    ok = JN.notify_decision(_req(state="approved"),
                            poster=lambda c, t: posted.append(1) or True,
                            user_resolver=lambda email: None)
    assert ok is False
    assert posted == []


def test_decision_noop_without_email(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    posted = []
    ok = JN.notify_decision(_req(state="approved", requester_email=""),
                            poster=lambda c, t: posted.append(1) or True,
                            user_resolver=lambda email: "U0X")
    assert ok is False
    assert posted == []


# ---- provisioned → remind the mayor/registrar --------------------------

def test_provisioned_noop_without_token(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: False)
    posted = []
    ok = JN.notify_group_provisioned(
        _req(state="provisioned"),
        poster=lambda c, t: posted.append(1) or True,
        channel_resolver=lambda aud, env=None: "C0ADMIN")
    assert ok is False
    assert posted == []


def test_provisioned_noop_for_non_group(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    posted = []
    ok = JN.notify_group_provisioned(
        _req(kind="member", state="provisioned"),
        poster=lambda c, t: posted.append(1) or True,
        channel_resolver=lambda aud, env=None: "C0ADMIN")
    assert ok is False
    assert posted == []


def test_provisioned_posts_to_admin_with_action_reminder(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    seen = {}
    def poster(channel, text):
        seen["channel"] = channel
        seen["text"] = text
        return True
    ok = JN.notify_group_provisioned(
        _req(state="provisioned"), poster=poster,
        channel_resolver=lambda aud, env=None: (seen.setdefault("aud", aud), "C0ADMIN")[1])
    assert ok is True
    assert seen["aud"] == "admin"          # the mayor/registrar channel
    assert seen["channel"] == "C0ADMIN"
    # It reminds the registrar to act, names the PI's email, and gives setup cmds.
    assert "Action for the registrar" in seen["text"]
    assert "pi@demo.edu" in seen["text"]
    assert "group-init-toolkit newlab" in seen["text"]


def test_provisioned_includes_invite_link_when_set(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    from wigamig.core import centre_init as CI
    monkeypatch.setattr(
        CI, "read_centre",
        lambda env=None: type("P", (), {"slack_invite_url": "https://join.example/xyz"})())
    seen = {}
    JN.notify_group_provisioned(
        _req(state="provisioned"),
        poster=lambda c, t: seen.setdefault("text", t) or True,
        channel_resolver=lambda aud, env=None: "C0ADMIN")
    assert "https://join.example/xyz" in seen["text"]


def test_group_onboarding_steps_shape():
    steps = JN.group_onboarding_steps("newlab", invite_url="https://join.example/xyz")
    assert len(steps) == 4
    assert "https://join.example/xyz" in steps[0]
    assert "group-init-toolkit newlab --create-repo" in steps[1]
    assert "group-setup newlab" in steps[2]
    assert "group-reconcile newlab --apply" in steps[3]
    # Without a link, step 1 tells the PI the registrar will email it.
    nolink = JN.group_onboarding_steps("newlab")
    assert "registrar will email" in nolink[0]


# ---- PI onboarding DMs -------------------------------------------------

def test_pi_onboarded_noop_without_token(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: False)
    posts = []
    ok = JN.notify_pi_onboarded("mh", email="pi@x.edu",
                                poster=lambda c, t: posts.append(1) or True,
                                user_resolver=lambda e: "U0PI")
    assert ok is False
    assert posts == []


def test_pi_onboarded_noop_when_not_in_workspace(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    posts = []
    ok = JN.notify_pi_onboarded("mh", email="pi@x.edu",
                                poster=lambda c, t: posts.append(1) or True,
                                user_resolver=lambda e: None)
    assert ok is False
    assert posts == []


def test_pi_onboarded_dms_each_step(world, monkeypatch):
    monkeypatch.setattr(JN, "_has_token", lambda: True)
    seen = []
    ok = JN.notify_pi_onboarded("mh", email="pi@x.edu", centre_name="Serenity",
                                channel_name="mh",
                                poster=lambda c, t: seen.append((c, t)) or True,
                                user_resolver=lambda e: "U0PI")
    assert ok is True
    assert all(c == "U0PI" for c, _ in seen)          # all DMs to the PI
    joined = " ".join(t for _, t in seen)
    assert "registrar" in joined and "cable_guy" in joined
    assert "security_guard" in joined and "dashboard" in joined
    assert "#mh" in joined


def test_pi_onboarding_messages_shape():
    msgs = JN.pi_onboarding_messages("mh", centre_name="Serenity", channel_name="mh")
    assert len(msgs) == 5
    assert "Serenity" in msgs[0]
    assert any("#mh" in m for m in msgs)


# ---- lifecycle wiring is best-effort ----------------------------------

def test_file_request_survives_notifier_explosion(world, monkeypatch):
    """A broken notifier must not stop a join request from being filed."""
    def boom(*a, **k):
        raise RuntimeError("slack exploded")
    monkeypatch.setattr(JN, "notify_new_request", boom)
    req = JR.file_request(kind="lab", requester_email="x@y.edu",
                          proposed_name="visitor_lab", proposed_pi="@visitor")
    assert req.state == "pending"          # filed despite the notifier blowing up
    assert JR.get_request(req.id) is not None
