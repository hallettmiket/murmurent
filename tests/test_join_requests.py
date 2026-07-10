"""
Tests for core.join_requests (2d) + the provision_lab_onboarding hook
on approval (2g).
"""

from __future__ import annotations

import pytest
import yaml

from murmurent.core import centre_init as CI
from murmurent.core import centre_provision as CP
from murmurent.core import join_requests as JR
from murmurent.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "tbrowne")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                         fake_home / ".murmurent" / "registrar")
    # Centre is initialised; provisioning hooks need it.
    CI.init_centre(
        name="C", institution="U", founding_mayor="@tbrowne",
        slack_workspace="T0X", github_org="centre-x",
        data_server="biodatsci",
        write_sentinel=False,
    )
    return tmp_path


# ---- file_request ------------------------------------------------------

def test_file_request_persists(world):
    req = JR.file_request(
        kind="lab", requester_email="pi@uwo.ca",
        proposed_name="dcis_imaging", proposed_pi="@allie",
        institution_affiliation="Western University",
        justification="image-genomics joint with neuro",
    )
    assert req.id == 1
    assert req.state == "pending"
    assert req.path.is_file()
    rt = JR.get_request(1)
    assert rt.proposed_name == "dcis_imaging"
    assert rt.kind == "lab"


def test_file_request_assigns_sequential_ids(world):
    a = JR.file_request(kind="lab", requester_email="a@x.uwo.ca",
                         proposed_name="alpha", proposed_pi="@a")
    b = JR.file_request(kind="lab", requester_email="b@x.uwo.ca",
                         proposed_name="beta", proposed_pi="@b")
    assert a.id == 1 and b.id == 2


@pytest.mark.parametrize("bad", ["", "weird_kind"])
def test_file_request_rejects_bad_kind(world, bad):
    with pytest.raises(JR.JoinRequestError, match="kind"):
        JR.file_request(kind=bad, requester_email="x@y", proposed_name="z",
                         proposed_pi="@p")


def test_file_request_rejects_missing_email(world):
    with pytest.raises(JR.JoinRequestError, match="email"):
        JR.file_request(kind="lab", requester_email="",
                         proposed_name="x", proposed_pi="@p")


def test_file_request_rejects_missing_name(world):
    with pytest.raises(JR.JoinRequestError, match="name"):
        JR.file_request(kind="lab", requester_email="x@y",
                         proposed_name="", proposed_pi="@p")


def test_file_request_lab_requires_pi(world):
    with pytest.raises(JR.JoinRequestError, match="proposed_pi"):
        JR.file_request(kind="lab", requester_email="x@y",
                         proposed_name="z", proposed_pi="")


def test_file_request_admin_does_not_require_pi(world):
    req = JR.file_request(kind="admin", requester_email="a@x",
                           proposed_name="admin-role", proposed_pi="")
    assert req.kind == "admin"


# ---- iter / get --------------------------------------------------------

def test_iter_state_filter(world):
    a = JR.file_request(kind="lab", requester_email="a@x",
                         proposed_name="alpha", proposed_pi="@a")
    b = JR.file_request(kind="lab", requester_email="b@x",
                         proposed_name="beta", proposed_pi="@b")
    JR.decline(req_id=a.id, actor="@tbrowne", reason="duplicate")
    pending = JR.iter_requests(state="pending")
    declined = JR.iter_requests(state="declined")
    assert [r.id for r in pending] == [b.id]
    assert [r.id for r in declined] == [a.id]


def test_get_unknown_raises(world):
    with pytest.raises(JR.JoinRequestNotFound):
        JR.get_request(99)


# ---- approve (lab) — end-to-end with injected fakes --------------------

def _fake_slack(_name, _ws):
    return "C0FAKE"


def _fake_acl_runner(_argv):
    import subprocess
    return subprocess.CompletedProcess(_argv, 0, "ok\n", "")


def test_approve_lab_dispatches_create_and_provision(world,
                                                       monkeypatch):
    monkeypatch.setattr(CP, "_live_slack_create_channel", _fake_slack)
    # No GitHub creator to patch — the mayor onboarding path never creates the
    # group's repo (that's the PI's job); it only emits an informational probe.
    # Patch the apply_fs_acl runner via env.
    real_apply = CP.apply_fs_acl
    def patched_apply(**kw):
        kw["runner"] = _fake_acl_runner
        return real_apply(**kw)
    monkeypatch.setattr(CP, "apply_fs_acl", patched_apply)

    req = JR.file_request(kind="lab", requester_email="pi@uwo.ca",
                           proposed_name="dcis", proposed_pi="@allie",
                           institution_affiliation="Western")
    approved = JR.approve(req_id=req.id, actor="@tbrowne")
    assert approved.state == "provisioned"
    # Slack + github + fs ACL = 3 probes.
    kinds = [p["kind"] for p in approved.probes]
    assert "slack-channel" in kinds
    assert "github-repo" in kinds
    assert any(k.startswith("fs-acl") for k in kinds)
    # Lab record exists.
    reg = R.read_registry()
    assert any(l.name == "dcis" for l in reg.labs)
    # PI email from the request propagated onto the PI's member record, so the
    # lab's email map is non-empty and the PI can be invited to the channel.
    assert R.group_email_map("dcis") == {"allie": "pi@uwo.ca"}


def test_approve_failed_create_lab_marks_failed(world, monkeypatch):
    """Force create_lab to raise; approve() should mark the request
    failed, not bail out."""
    def boom(**kw):
        raise RuntimeError("simulated create_lab failure")
    monkeypatch.setattr(R, "create_lab", boom)
    req = JR.file_request(kind="lab", requester_email="x@y",
                           proposed_name="z", proposed_pi="@p")
    out = JR.approve(req_id=req.id, actor="@tbrowne")
    assert out.state == "failed"
    assert any("create_lab failed" in p["summary"] for p in out.probes)


def test_approve_admin_adds_registrar(world, monkeypatch):
    """kind=admin promotes the requester to the registrar list."""
    req = JR.file_request(kind="admin",
                           requester_email="newadmin@x",
                           proposed_name="newadmin-role",
                           proposed_pi="@newadmin")
    out = JR.approve(req_id=req.id, actor="@tbrowne", provision=False)
    assert out.state == "approved"
    assert R.is_registrar("newadmin") is True


def test_pi_kind_no_longer_fileable(world):
    # A lab/core request creates the PI + group in one step, so `pi` was retired.
    with pytest.raises(JR.JoinRequestError, match="kind must be one of"):
        JR.file_request(kind="pi", requester_email="newpi@x",
                        proposed_name="newpi-role", proposed_pi="@newpi")
    assert "pi" not in JR.VALID_KINDS


def test_member_join_nonexistent_group_rejected(world):
    # "Join a group that doesn't exist" → refused at filing time.
    with pytest.raises(JR.JoinRequestError, match="no lab or core named"):
        JR.file_request(kind="member", requester_email="s@x.edu",
                        proposed_name="ghost_lab", proposed_pi="@student")


def test_member_join_existing_group_adds_member(world):
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie",
                 pi_email="allie@x.edu")
    req = JR.file_request(kind="member", requester_email="student@x.edu",
                          proposed_name="dcis", proposed_pi="@student")
    assert req.kind == "member" and req.state == "pending"
    out = JR.approve(req_id=req.id, actor="@allie", provision=False)
    assert out.state == "approved"
    # the member is now on the group's roster, with their email (for the invite)
    assert R.group_email_map("dcis").get("student") == "student@x.edu"
    assert any(p["kind"] == "add-member" and p["severity"] == "ok" for p in out.probes)


def test_add_group_member_and_group_lookups(world):
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    assert R.group_exists("dcis") is True
    assert R.group_exists("nope") is False
    assert R.group_pi("dcis") == "@allie"
    assert R.add_group_member("dcis", handle="@bob", email="bob@x.edu") is True
    assert R.add_group_member("nope", handle="@bob") is False    # no such group
    assert R.group_email_map("dcis").get("bob") == "bob@x.edu"


def test_group_profile_roundtrip(world):
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    assert R.read_group_profile("dcis") == {}
    assert R.update_group_profile("dcis", {
        "github": "hallettmiket/dcis", "notebook_host": "biodatsci",
        "data_raw": "/data/lab_vm/raw/dcis", "bogus": "ignored"}) is True
    prof = R.read_group_profile("dcis")
    assert prof["github"] == "hallettmiket/dcis"
    assert prof["notebook_host"] == "biodatsci"
    assert prof["data_raw"] == "/data/lab_vm/raw/dcis"
    assert "bogus" not in prof                       # only known fields written
    # empty value clears a field
    R.update_group_profile("dcis", {"github": ""})
    assert "github" not in R.read_group_profile("dcis")


def test_update_group_profile_no_such_group(world):
    assert R.update_group_profile("ghost", {"github": "x/y"}) is False


def test_group_setup_cli(world):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_setup
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    res = CliRunner().invoke(group_setup, [
        "dcis", "--non-interactive",
        "--set", "github=hallettmiket/dcis", "--set", "slack_workspace=T0DCIS"])
    assert res.exit_code == 0, res.output
    prof = R.read_group_profile("dcis")
    assert prof["github"] == "hallettmiket/dcis" and prof["slack_workspace"] == "T0DCIS"


def test_group_slack_setup_cli_happy_path(world, monkeypatch):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_slack_setup
    from murmurent.core import centre_provision as CP, group_reconcile as GR
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")

    fake_home = world / "home2"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    monkeypatch.setattr(CP, "slack_auth_test", lambda token: CP.SlackAuthResult(
        ok=True, team_id="T0DCIS", team_name="dcis-lab", bot_user="dcis"))

    res = CliRunner().invoke(group_slack_setup, [
        "dcis", "--non-interactive",
        "--token", "xoxb-dcis",
        "--invite-url", "https://join.slack.com/dcis",
    ])
    assert res.exit_code == 0, res.output

    prof = R.read_group_profile("dcis")
    assert prof["slack_workspace"] == "T0DCIS"
    assert prof["slack_invite_url"] == "https://join.slack.com/dcis"
    assert GR.resolve_group_slack_token("dcis") == "xoxb-dcis"
    token_path = fake_home / ".config" / "murmurent" / "groups" / "dcis" / "slack-token"
    assert (token_path.stat().st_mode & 0o777) == 0o600


def test_group_slack_setup_cli_recovers_duplicated_prefix_paste(world, monkeypatch):
    """Regression for the exact failure a PI hit: typing 'xoxb-' before
    pasting a token that already includes it. The command must normalize
    it rather than send the garbled string to Slack."""
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_slack_setup
    from murmurent.core import centre_provision as CP, group_reconcile as GR
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")

    fake_home = world / "home4"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    seen = {}
    def fake_auth_test(token):
        seen["token"] = token
        return CP.SlackAuthResult(ok=True, team_id="T0DCIS", team_name="dcis-lab", bot_user="dcis")
    monkeypatch.setattr(CP, "slack_auth_test", fake_auth_test)

    res = CliRunner().invoke(group_slack_setup, [
        "dcis", "--non-interactive", "--token", "xoxb-xoxb-realtoken123"])
    assert res.exit_code == 0, res.output
    assert seen["token"] == "xoxb-realtoken123"          # duplicated prefix collapsed
    assert GR.resolve_group_slack_token("dcis") == "xoxb-realtoken123"


def test_group_slack_setup_cli_bad_token_writes_nothing(world, monkeypatch):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_slack_setup
    from murmurent.core import centre_provision as CP, group_reconcile as GR
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")

    fake_home = world / "home3"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    monkeypatch.setattr(CP, "slack_auth_test", lambda token: CP.SlackAuthResult(
        ok=False, error="invalid_auth", detail="the token is wrong or has been revoked."))

    res = CliRunner().invoke(group_slack_setup, [
        "dcis", "--non-interactive", "--token", "xoxb-bad"])
    assert res.exit_code == 1
    assert "invalid_auth" in res.output
    assert GR.resolve_group_slack_token("dcis") == ""
    assert not (fake_home / ".config" / "murmurent" / "groups" / "dcis").exists()
    assert R.read_group_profile("dcis").get("slack_workspace", "") == ""


def test_group_slack_setup_cli_unknown_group(world):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_slack_setup
    res = CliRunner().invoke(group_slack_setup, [
        "no-such-group", "--non-interactive", "--token", "xoxb-x"])
    assert res.exit_code != 0
    assert "no lab or core named" in res.output


def test_group_slack_setup_cli_non_interactive_requires_token(world):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_slack_setup
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    res = CliRunner().invoke(group_slack_setup, ["dcis", "--non-interactive"])
    assert res.exit_code != 0
    assert "--token is required" in res.output


def test_send_group_dm_no_token_is_actionable(monkeypatch, tmp_path):
    from murmurent.core import group_reconcile as GR
    monkeypatch.delenv("MURMURENT_GROUP_SLACK_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    ok, detail = GR.send_group_dm("dcis", text="hi", email="a@x")
    assert ok is False
    assert "group-slack-setup dcis" in detail


def test_send_group_dm_no_email_or_uid_is_actionable():
    from murmurent.core import group_reconcile as GR
    ok, detail = GR.send_group_dm("dcis", text="hi", token="xoxb-x")
    assert ok is False
    assert "no email on file" in detail


def test_send_group_dm_email_not_found_in_workspace(monkeypatch):
    from murmurent.core import group_reconcile as GR
    monkeypatch.setattr(GR, "resolve_group_slack_user_id", lambda email, token: None)
    ok, detail = GR.send_group_dm("dcis", text="hi", email="a@x", token="xoxb-x")
    assert ok is False
    assert "couldn't find a@x" in detail


def test_send_group_dm_dm_open_failure(monkeypatch):
    from murmurent.core import group_reconcile as GR
    from murmurent.dashboard import slack_notify as SN
    monkeypatch.setattr(GR, "resolve_group_slack_user_id", lambda email, token: "U123")
    monkeypatch.setattr(SN, "_open_dm", lambda uid, tok: None)
    ok, detail = GR.send_group_dm("dcis", text="hi", email="a@x", token="xoxb-x")
    assert ok is False
    assert "couldn't open a DM" in detail


def test_send_group_dm_happy_path_via_explicit_uid(monkeypatch):
    """An explicit --dm slack_user_id skips email resolution entirely."""
    from murmurent.core import group_reconcile as GR
    from murmurent.dashboard import slack_notify as SN
    calls = {}
    def fake_open_dm(uid, tok):
        calls["uid"] = uid
        return "D999"
    monkeypatch.setattr(SN, "_open_dm", fake_open_dm)
    def fake_post(channel, text, *, token=None):
        calls["channel"] = channel
        calls["token"] = token
        calls["text"] = text
        return True
    monkeypatch.setattr(SN, "_post", fake_post)
    ok, detail = GR.send_group_dm("dcis", text="your card", slack_user_id="U777",
                                   token="xoxb-x")
    assert ok is True and detail == "sent"
    assert calls == {"uid": "U777", "channel": "D999", "token": "xoxb-x", "text": "your card"}


def test_send_group_dm_post_failure(monkeypatch):
    from murmurent.core import group_reconcile as GR
    from murmurent.dashboard import slack_notify as SN
    monkeypatch.setattr(SN, "_open_dm", lambda uid, tok: "D999")
    monkeypatch.setattr(SN, "_post", lambda channel, text, **kw: False)
    ok, detail = GR.send_group_dm("dcis", text="hi", slack_user_id="U777", token="xoxb-x")
    assert ok is False
    assert detail == "Slack post failed"


def test_resolve_group_slack_user_id_happy_path(monkeypatch):
    from murmurent.core import group_reconcile as GR
    from unittest.mock import patch, MagicMock
    mock = MagicMock()
    mock.json.return_value = {"ok": True, "user": {"id": "U555"}}
    with patch("httpx.get", return_value=mock):
        assert GR.resolve_group_slack_user_id("a@x", "xoxb-x") == "U555"


def test_group_reconcile_reports_and_applies(world):
    from murmurent.core import group_reconcile as GR
    from murmurent.core.frontmatter import parse_file, dump_document
    import pathlib
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    R.update_group_profile("dcis", {"slack_workspace": "T0DCIS",
                                    "slack_invite_url": "https://join/x", "github": "org/dcis"})
    R.add_group_member("dcis", handle="@bob", email="bob@x.edu")
    # give bob a GitHub login
    lab = next(l for l in R.read_registry().labs if l.name == "dcis")
    mf = pathlib.Path(lab.lab_mgmt_path) / "members" / "bob.md"
    doc = parse_file(mf); meta = dict(doc.meta); meta["git_logins"] = {"github": "bob-gh"}
    mf.write_text(dump_document(meta, doc.body))

    calls = []
    res = GR.group_reconcile("dcis", token="xoxb-x",
        workspace_checker=lambda email: False,               # not in the workspace
        collaborator_adder=lambda repo, login: (calls.append((repo, login)), (True, "ok"))[1])
    assert any("NOT in the group workspace" in s for s in res.slack)
    assert any("would add" in s for s in res.github)
    assert calls == []                                       # report-only: no writes

    res2 = GR.group_reconcile("dcis", token="xoxb-x", apply=True,
        workspace_checker=lambda email: True,
        collaborator_adder=lambda repo, login: (calls.append((repo, login)), (True, "ok"))[1])
    assert ("org/dcis", "bob-gh") in calls                   # applied → collaborator added
    assert any("added to org/dcis" in s for s in res2.github)
    assert any("in the group workspace" in s for s in res2.slack)


def test_resolve_group_slack_token_env_then_file(monkeypatch, tmp_path):
    from murmurent.core import group_reconcile as GR
    monkeypatch.delenv("MURMURENT_GROUP_SLACK_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    d = tmp_path / ".config" / "murmurent" / "groups" / "dcis"; d.mkdir(parents=True)
    (d / "slack-token").write_text("xoxb-group\n")
    assert GR.resolve_group_slack_token("dcis") == "xoxb-group"
    monkeypatch.setenv("MURMURENT_GROUP_SLACK_TOKEN", "xoxb-env")
    assert GR.resolve_group_slack_token("dcis") == "xoxb-env"   # env wins


def test_write_group_slack_token_round_trips(monkeypatch, tmp_path):
    """write_group_slack_token is the only writer for the path
    resolve_group_slack_token reads — round-trip them against each other."""
    from murmurent.core import group_reconcile as GR
    monkeypatch.delenv("MURMURENT_GROUP_SLACK_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    path = GR.write_group_slack_token("dcis", "  xoxb-fresh  ")
    assert path == tmp_path / ".config" / "murmurent" / "groups" / "dcis" / "slack-token"
    assert path.read_text(encoding="utf-8") == "xoxb-fresh\n"
    assert (path.stat().st_mode & 0o777) == 0o600

    assert GR.resolve_group_slack_token("dcis") == "xoxb-fresh"


def test_write_group_slack_token_overwrites_and_fixes_perms(monkeypatch, tmp_path):
    """Re-running group-slack-setup should replace the old token and
    reassert 0600 even if the file previously had looser permissions."""
    from murmurent.core import group_reconcile as GR
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    first = GR.write_group_slack_token("dcis", "xoxb-old")
    first.chmod(0o644)   # simulate a loosely-permissioned pre-existing file
    second = GR.write_group_slack_token("dcis", "xoxb-new")

    assert first == second
    assert second.read_text(encoding="utf-8") == "xoxb-new\n"
    assert (second.stat().st_mode & 0o777) == 0o600


def test_write_group_slack_token_refuses_empty(monkeypatch, tmp_path):
    from murmurent.core import group_reconcile as GR
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    with pytest.raises(ValueError):
        GR.write_group_slack_token("dcis", "   ")


def test_group_init_toolkit_scaffolds(world, tmp_path):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_init_toolkit
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    target = tmp_path / "dcis_toolkit"
    res = CliRunner().invoke(group_init_toolkit, ["dcis", "--dir", str(target)])
    assert res.exit_code == 0, res.output
    assert (target / ".claude" / "agents" / "_TEMPLATE.md").is_file()
    assert (target / ".claude" / "agents" / "README.md").is_file()
    assert "override" in (target / "README.md").read_text().lower()


def test_group_init_toolkit_refuses_nonempty(world, tmp_path):
    from click.testing import CliRunner
    from murmurent.commands.centre_cmd import group_init_toolkit
    R.create_lab(name="dcis", display_name="dcis", pi_handle="@allie", pi_email="a@x")
    target = tmp_path / "dcis_toolkit"; target.mkdir()
    (target / "x").write_text("y")
    res = CliRunner().invoke(group_init_toolkit, ["dcis", "--dir", str(target)])
    assert res.exit_code != 0 and "already exists" in res.output


def test_legacy_pi_request_still_approves(world):
    # A `pi` request already on disk (pre-retirement) must still read + approve
    # (no infra) — approve() reads without re-validating the kind.
    req = JR.file_request(kind="lab", requester_email="p@x",
                          proposed_name="l1", proposed_pi="@p")
    # hand-mutate the on-disk kind to the legacy value
    import pathlib, re
    f = next(pathlib.Path(JR.requests_dir()).glob("*.md"))
    f.write_text(re.sub(r"^kind:.*$", "kind: pi", f.read_text(), count=1, flags=re.M))
    out = JR.approve(req_id=req.id, actor="@tbrowne", provision=False)
    assert out.state == "approved"


def test_approve_refuses_terminal_state(world):
    req = JR.file_request(kind="admin", requester_email="x@y",
                           proposed_name="role", proposed_pi="@p")
    JR.approve(req_id=req.id, actor="@tbrowne", provision=False)
    with pytest.raises(JR.JoinRequestStateError):
        JR.approve(req_id=req.id, actor="@tbrowne", provision=False)


# ---- decline -----------------------------------------------------------

def test_decline_records_reason(world):
    req = JR.file_request(kind="lab", requester_email="x@y",
                           proposed_name="z", proposed_pi="@p")
    out = JR.decline(req_id=req.id, actor="@tbrowne",
                       reason="duplicate of #2")
    assert out.state == "declined"
    assert out.decline_reason == "duplicate of #2"


def test_decline_refuses_empty_reason(world):
    req = JR.file_request(kind="lab", requester_email="x@y",
                           proposed_name="z", proposed_pi="@p")
    with pytest.raises(JR.JoinRequestError, match="reason"):
        JR.decline(req_id=req.id, actor="@tbrowne", reason="   ")


# ---- provision_lab_onboarding (direct unit test) -----------------------

def test_provision_lab_onboarding_no_centre(monkeypatch, tmp_path):
    """If centre.md is missing → returns a single block probe."""
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT",
                         str(tmp_path / "fresh_lab_info"))
    probes = CP.provision_lab_onboarding("any_lab")
    assert len(probes) == 1
    assert probes[0].status == "block"
    assert "centre" in probes[0].detail.lower()


def test_provision_lab_onboarding_warns_on_missing_config(world,
                                                            monkeypatch):
    """If centre is initialised but optional fields are blank → warn
    probes, not block. The github-repo step is exempt: it is deliberately
    deferred to the PI (group-side), so it is always ``ok``, never a
    config-driven warning — the mayor doesn't create the group's repo."""
    CI.update_centre({"slack_workspace": "", "github_org": "",
                        "data_server": ""})
    probes = CP.provision_lab_onboarding("any_lab")
    by = {p.name: p.status for p in probes}
    assert by.get("github-repo") == "ok"        # deferred to the PI, not a warn
    assert all(p.status == "warn" for p in probes if p.name != "github-repo")
    assert not any(p.status == "fail" for p in probes)
