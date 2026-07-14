"""Tests for :mod:`core.roster_sync` + the Lab Members refresh endpoints.

The GH-based roster flow: every member has a read-only lab_mgmt clone;
the PI pushes roster changes; the member side stays fresh via
``pull_lab_mgmt()`` (dashboard update button, reconcile). These tests pin:

  * roster_info() verdicts for missing / plain-dir / git-clone lab_mgmt
  * pull_lab_mgmt() failure shapes (no remote, not a git repo) — never raises
  * GET /api/members/roster-info and POST /api/members/refresh
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.core import roster_sync as _rs


@pytest.fixture
def lab_mgmt(monkeypatch, tmp_path):
    root = tmp_path / "lab-mgmt"
    (root / "members").mkdir(parents=True)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _make_git(root: Path) -> None:
    _git(root, "init")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-m", "seed")


def test_roster_info_missing_clone(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "nope"))
    info = _rs.roster_info()
    assert not info.ok and not info.is_git
    assert "clone" in info.detail


def test_roster_info_plain_dir(lab_mgmt):
    info = _rs.roster_info()
    assert info.ok and not info.is_git
    assert info.as_of == ""


def test_roster_info_git_clone_has_as_of(lab_mgmt):
    _make_git(lab_mgmt)
    info = _rs.roster_info()
    assert info.ok and info.is_git
    assert info.as_of  # ISO date of the seed commit


def test_pull_plain_dir_is_noop(lab_mgmt):
    res = _rs.pull_lab_mgmt()
    assert res.ok and not res.is_git


def test_pull_without_remote_is_tolerated_noop(lab_mgmt):
    """A git repo with NO remote (local-only lab_mgmt — e.g. the PI's
    machine before pushing to GitHub) is a legitimate state: ok=True,
    nothing pulled, freshness stamp intact, no scary git error."""
    _make_git(lab_mgmt)
    res = _rs.pull_lab_mgmt()
    assert res.is_git and res.ok
    assert "no remote" in res.detail
    assert res.as_of


def test_pull_without_upstream_falls_back_to_explicit_remote(lab_mgmt, tmp_path):
    """Remote exists but the branch has no upstream (cloned by hand,
    or `git push` without -u): pull_lab_mgmt retries `git pull
    <remote> <branch>` instead of surfacing git's set-upstream hint."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    _make_git(lab_mgmt)
    _git(lab_mgmt, "remote", "add", "origin", str(remote))
    branch = subprocess.run(
        ["git", "-C", str(lab_mgmt), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    _git(lab_mgmt, "push", "origin", branch)  # deliberately no -u
    res = _rs.pull_lab_mgmt()
    assert res.ok, res.detail
    assert "tracking information" not in res.detail


def test_pull_fast_forwards_from_remote(lab_mgmt, tmp_path):
    """End to end: PI pushes to the 'remote'; member's pull picks it up."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    _make_git(lab_mgmt)
    _git(lab_mgmt, "remote", "add", "origin", str(remote))
    _git(lab_mgmt, "push", "-u", "origin", "HEAD")
    # "PI side": clone elsewhere, add a member, push.
    pi = tmp_path / "pi-clone"
    subprocess.run(["git", "clone", str(remote), str(pi)], check=True,
                   capture_output=True, text=True)
    (pi / "members").mkdir(exist_ok=True)
    (pi / "members" / "newbie.md").write_text("---\nhandle: '@newbie'\n---\n")
    _git(pi, "add", "-A")
    _git(pi, "-c", "user.email=pi@t", "-c", "user.name=pi", "commit", "-m", "add newbie")
    _git(pi, "push")
    # Member side pulls.
    res = _rs.pull_lab_mgmt()
    assert res.ok, res.detail
    assert (lab_mgmt / "members" / "newbie.md").is_file()


def test_roster_endpoints(lab_mgmt):
    from murmurent.dashboard.server import create_app

    client = TestClient(create_app())
    info = client.get("/api/members/roster-info")
    assert info.status_code == 200
    assert info.json()["path"] == str(lab_mgmt)
    # Refresh on a plain dir: ok, nothing to pull, never a 5xx.
    res = client.post("/api/members/refresh")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["is_git"] is False
