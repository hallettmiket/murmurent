"""Tests for read-only lab_mgmt access grants (core.group_reconcile).

The GH roster flow needs every member to be a read-only collaborator on
the lab_mgmt repo. Pinned here:

  * _gh_add_collaborator passes permission=pull when asked (and omits
    the field otherwise — project repos keep GitHub's push default)
  * lab_mgmt_repo_slug() parses the clone's origin URL (SSH + HTTPS)
  * grant_lab_mgmt_read refuses cleanly when there is no GitHub remote
  * group_reconcile reports/applies the per-member lab_mgmt grants
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from murmurent.core import group_reconcile as _gr


def _fake_runner(calls, returncode=0):
    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")
    return run


def test_add_collaborator_pull_permission():
    calls = []
    ok, detail = _gr._gh_add_collaborator(
        "org/lab_mgmt", "vaibhavg037", permission="pull",
        runner=_fake_runner(calls))
    assert ok
    assert calls[0][-2:] == ["-f", "permission=pull"]


def test_add_collaborator_default_keeps_push_default():
    calls = []
    ok, _ = _gr._gh_add_collaborator("org/proj", "someone", runner=_fake_runner(calls))
    assert ok
    assert "-f" not in calls[0]  # no permission field → GitHub default (push)


@pytest.fixture
def lab_mgmt_clone(monkeypatch, tmp_path):
    root = tmp_path / "lab-mgmt"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True,
                   capture_output=True)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))
    return root


@pytest.mark.parametrize("url", [
    "git@github.com:hallettmiket/murmurent_lab_mgmt_mh.git",
    "https://github.com/hallettmiket/murmurent_lab_mgmt_mh.git",
    "https://github.com/hallettmiket/murmurent_lab_mgmt_mh",
])
def test_lab_mgmt_repo_slug_parses_origin(lab_mgmt_clone, url):
    subprocess.run(["git", "-C", str(lab_mgmt_clone), "remote", "add", "origin", url],
                   check=True, capture_output=True)
    assert _gr.lab_mgmt_repo_slug() == "hallettmiket/murmurent_lab_mgmt_mh"


def test_lab_mgmt_repo_slug_no_remote(lab_mgmt_clone):
    assert _gr.lab_mgmt_repo_slug() == ""


def test_grant_refuses_without_remote(lab_mgmt_clone):
    ok, detail = _gr.grant_lab_mgmt_read("someone")
    assert not ok
    assert "no GitHub remote" in detail


def test_grant_uses_pull_permission(lab_mgmt_clone):
    subprocess.run(["git", "-C", str(lab_mgmt_clone), "remote", "add", "origin",
                    "git@github.com:org/lab_mgmt.git"], check=True, capture_output=True)
    calls = []
    ok, _ = _gr.grant_lab_mgmt_read("someone", runner=_fake_runner(calls))
    assert ok
    assert "repos/org/lab_mgmt/collaborators/someone" in calls[0]
    assert ["-f", "permission=pull"] == calls[0][-2:]


def test_group_reconcile_reports_and_applies_lab_mgmt_grants(monkeypatch):
    """Reconcile lists a would-grant line per member (dry-run) and calls
    the granter with the lab_mgmt slug on --apply."""
    roster = {
        "didi": {"email": "d@uwo.ca", "github": "didi-gh"},
        "nokey": {"email": "n@uwo.ca", "github": ""},
    }
    monkeypatch.setattr(_gr, "group_roster", lambda g, env=None: roster)
    monkeypatch.setattr(_gr, "lab_mgmt_repo_slug", lambda: "org/lab_mgmt")
    monkeypatch.setattr(_gr, "resolve_group_slack_token", lambda g: "")
    from murmurent.core import registrar as _R
    monkeypatch.setattr(_R, "read_group_profile", lambda g, env=None: {})

    res = _gr.group_reconcile("mh", workspace_checker=lambda e: None)
    assert any("would grant read-only" in line for line in res.lab_mgmt)
    assert any("no GitHub login" in line for line in res.lab_mgmt)

    granted = []
    res = _gr.group_reconcile(
        "mh", apply=True, workspace_checker=lambda e: None,
        lab_mgmt_granter=lambda repo, login: (granted.append((repo, login)) or (True, "ok")),
    )
    assert granted == [("org/lab_mgmt", "didi-gh")]
    assert any("✓" in line for line in res.lab_mgmt)


def test_group_reconcile_notes_missing_remote(monkeypatch):
    monkeypatch.setattr(_gr, "group_roster",
                        lambda g, env=None: {"didi": {"email": "", "github": "x"}})
    monkeypatch.setattr(_gr, "lab_mgmt_repo_slug", lambda: "")
    monkeypatch.setattr(_gr, "resolve_group_slack_token", lambda g: "")
    from murmurent.core import registrar as _R
    monkeypatch.setattr(_R, "read_group_profile", lambda g, env=None: {})
    res = _gr.group_reconcile("mh", workspace_checker=lambda e: None)
    assert any("no GitHub remote" in line for line in res.lab_mgmt)


def test_parse_logins_backfills_from_top_level_github():
    """membership.add() writes a top-level ``github:`` field; parse_logins
    must see it (vgupta88 regression — reconcile said 'no GitHub login on
    file' for a member whose profile had one)."""
    from murmurent.core.git_providers import parse_logins
    assert parse_logins({"github": "@vaibhavg037"}) == {"github": "vaibhavg037"}
    # git_logins wins when both are present.
    assert parse_logins({"github": "old", "git_logins": {"github": "new"}}) == {"github": "new"}
