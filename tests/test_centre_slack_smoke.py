"""
Tests for the Slack channel-create surface (backlog #2):

  - core.centre_provision.slack_create_channel: structured result
    for every Slack response code we know about.
  - the _live_slack_create_channel compat shim still returns the
    raw channel_id (or None) so provision_lab_onboarding's hook
    signature stays unchanged.
  - the wigamig centre-slack-smoke CLI prints actionable hints +
    exit code 0/1 correctly.

All tests mock httpx — none hit a real Slack workspace. The live
smoke is the CLI itself, which the registrar runs once against a
real token before approving the first lab join.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from wigamig.commands.centre_cmd import (
    centre_slack_smoke as cli_smoke,
)
from wigamig.core import centre_provision as CP


def _httpx_response(ok: bool, *, channel_id: str = "C0FAKE",
                     error: str = "", status_code: int = 200,
                     raw_body: str | None = None) -> MagicMock:
    """Mock for an httpx.post return value."""
    mock = MagicMock()
    mock.status_code = status_code
    if raw_body is not None:
        # Simulate a non-JSON response.
        mock.json.side_effect = ValueError("not json")
    else:
        body = {"ok": ok}
        if ok:
            body["channel"] = {"id": channel_id}
        else:
            body["error"] = error
        mock.json.return_value = body
    return mock


# ---- slack_create_channel ---------------------------------------------

def test_missing_token_is_actionable(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    res = CP.slack_create_channel("smoke-test")
    assert res.ok is False
    assert res.error == "missing_token"
    assert "SLACK_BOT_TOKEN" in res.detail


def test_explicit_token_overrides_env(monkeypatch):
    """An explicit token= wins over the env, so the smoke CLI can be
    run with a temporary token without exporting it globally."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with patch("httpx.post", return_value=_httpx_response(True)):
        res = CP.slack_create_channel("smoke-test", token="xoxb-real")
    assert res.ok is True


def test_happy_path_returns_channel_id(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            True, channel_id="C0WGM01")):
        res = CP.slack_create_channel("lab-demo")
    assert res.ok is True
    assert res.channel_id == "C0WGM01"
    assert res.channel_name == "lab-demo"
    assert "created" in res.detail


def test_private_default_sets_is_private(monkeypatch):
    """The join-approve flow always wants private channels — verify
    we send is_private=True by default."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    captured = {}
    def fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _httpx_response(True)
    with patch("httpx.post", side_effect=fake_post):
        CP.slack_create_channel("lab-demo")
    assert captured["json"]["is_private"] is True


def test_public_flag_flips_is_private(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    captured = {}
    def fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _httpx_response(True)
    with patch("httpx.post", side_effect=fake_post):
        CP.slack_create_channel("lab-demo", private=False)
    assert captured["json"]["is_private"] is False


@pytest.mark.parametrize("err,hint_substr", [
    ("missing_scope",          "OAuth scope"),
    ("not_authed",             "no token"),
    ("invalid_auth",           "wrong or has been revoked"),
    ("name_taken",             "already exists"),
    ("invalid_name_specials",  "special chars"),
    ("invalid_name_maxlength", "80 chars"),
    ("ratelimited",            "rate-limited"),
    ("restricted_action",      "admin policy"),
])
def test_known_error_codes_get_actionable_hints(monkeypatch, err, hint_substr):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(False, error=err)):
        res = CP.slack_create_channel("lab-demo")
    assert res.ok is False
    assert res.error == err
    assert hint_substr.lower() in res.detail.lower()


def test_unknown_error_surfaces_raw_body(monkeypatch):
    """If Slack invents a new error code, we still show what they
    sent us so the registrar can paste it into a bug report."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            False, error="some_new_error")):
        res = CP.slack_create_channel("lab-demo")
    assert res.ok is False
    assert "some_new_error" in res.detail


def test_network_error_classified_as_transport(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    import httpx as _httpx
    with patch("httpx.post", side_effect=_httpx.ConnectError("dns fail")):
        res = CP.slack_create_channel("lab-demo")
    assert res.ok is False
    assert res.error == "transport"
    assert "dns fail" in res.detail


def test_non_json_response_classified_as_bad_response(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            False, raw_body="<html>500</html>", status_code=502)):
        res = CP.slack_create_channel("lab-demo")
    assert res.ok is False
    assert res.error == "bad_response"
    assert "502" in res.detail


# ---- _live_slack_create_channel compat shim ----------------------------

def test_compat_shim_returns_channel_id_on_success(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            True, channel_id="C0LIVE")):
        out = CP._live_slack_create_channel("lab-demo", "T0X")
    assert out == "C0LIVE"


def test_compat_shim_returns_none_on_failure(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            False, error="missing_scope")):
        out = CP._live_slack_create_channel("lab-demo", "T0X")
    assert out is None


# ---- centre-slack-smoke CLI -------------------------------------------

def test_cli_missing_token_clean_error(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    res = CliRunner().invoke(cli_smoke)
    assert res.exit_code != 0
    assert "SLACK_BOT_TOKEN" in res.output


def test_cli_happy_path_exits_0(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", side_effect=[
        # First call: conversations.create
        _httpx_response(True, channel_id="C0FAKE"),
        # Second call: conversations.archive (cleanup)
        _httpx_response(True),
    ]):
        res = CliRunner().invoke(cli_smoke, ["--channel", "smoke-1"])
    assert res.exit_code == 0, res.output
    assert "✓ created channel" in res.output
    assert "C0FAKE" in res.output
    assert "Bot token is healthy" in res.output


def test_cli_keep_skips_archive(monkeypatch):
    """--keep should not call conversations.archive."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    posts = []
    def fake_post(url, **kw):
        posts.append(url)
        return _httpx_response(True, channel_id="C0FAKE")
    with patch("httpx.post", side_effect=fake_post):
        res = CliRunner().invoke(cli_smoke,
                                   ["--channel", "smoke-2", "--keep"])
    assert res.exit_code == 0
    # Only conversations.create was called.
    assert posts == ["https://slack.com/api/conversations.create"]


def test_cli_archive_failure_warns_but_exits_0(monkeypatch):
    """If conversations.archive fails, the create still succeeded —
    surface the warning but don't fail the smoke."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", side_effect=[
        _httpx_response(True, channel_id="C0FAKE"),
        _httpx_response(False, error="cant_archive"),
    ]):
        res = CliRunner().invoke(cli_smoke, ["--channel", "smoke-3"])
    assert res.exit_code == 0
    assert "could not archive" in res.output


def test_cli_failure_prints_hint_and_exits_1(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("httpx.post", return_value=_httpx_response(
            False, error="missing_scope")):
        res = CliRunner().invoke(cli_smoke, ["--channel", "smoke-4"])
    assert res.exit_code == 1
    assert "failed" in res.output
    assert "OAuth scope" in res.output


def test_cli_default_channel_is_timestamped(monkeypatch):
    """No --channel → generated probe name so re-runs don't collide
    with each other."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    captured = {}
    def fake_post(url, **kw):
        if "conversations.create" in url and "json" in kw:
            captured["name"] = kw["json"].get("name")
        return _httpx_response(True, channel_id="C0FAKE")
    with patch("httpx.post", side_effect=fake_post):
        CliRunner().invoke(cli_smoke)
    assert captured["name"].startswith("wigamig-smoke-")
