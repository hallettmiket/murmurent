"""Tests for automatic git persistence of roster changes + the
lab_mgmt-unsynced reconcile detectors.

Every mutation of ``members/<handle>.md`` must land as a git commit
(members receive the roster via git pull), and reconcile must flag
anything that slipped through (uncommitted edits, unpushed commits).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.core import membership as _m
from murmurent.core import reconcile as _rc


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True)


@pytest.fixture
def lab_mgmt(monkeypatch, tmp_path):
    """Git-initialized lab_mgmt with a lab.md naming the PI."""
    root = tmp_path / "lab-mgmt"
    (root / "members").mkdir(parents=True)
    (root / "lab.md").write_text(
        "---\nlab: testlab\nname: Test Lab\npi: '@boss'\n---\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "seed")
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))
    return root


def _last_msg(root: Path) -> str:
    return _git(root, "log", "-1", "--format=%s").stdout.strip()


def _is_clean(root: Path) -> bool:
    return _git(root, "status", "--porcelain").stdout.strip() == ""


def test_add_commits_roster_change(lab_mgmt):
    _m.add(handle="didi", full_name="Didi", role="postdoc")
    assert _last_msg(lab_mgmt) == "roster: add @didi (postdoc)"
    assert _is_clean(lab_mgmt)
    # No remote here → push probe reports the skip; the add itself succeeded
    # and the probes are exposed for endpoints to surface.
    assert any(p.name == "git push" and "no origin" in p.detail
               for p in _m.last_persist_probes)


def test_set_status_commits(lab_mgmt):
    _m.add(handle="didi", full_name="Didi")
    _m.set_status("didi", _m.INACTIVE, by_handle="@boss")
    assert _last_msg(lab_mgmt) == "roster: deactivate @didi"
    _m.set_status("didi", _m.ACTIVE)
    assert _last_msg(lab_mgmt) == "roster: reactivate @didi"
    assert _is_clean(lab_mgmt)


def test_upsert_and_lab_sudo_commit(lab_mgmt):
    _m.add(handle="didi", full_name="Didi")
    _m.upsert_member("didi", github="didi-gh")
    assert _last_msg(lab_mgmt) == "roster: update @didi"
    _m.set_lab_sudo("didi", True)
    assert _last_msg(lab_mgmt) == "roster: lab_sudo grant @didi"
    assert _is_clean(lab_mgmt)


def test_add_outside_git_still_works(monkeypatch, tmp_path):
    """No git checkout → the write succeeds and nothing raises."""
    root = tmp_path / "plain"
    (root / "members").mkdir(parents=True)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))
    rec = _m.add(handle="didi", full_name="Didi")
    assert (root / "members" / "didi.md").is_file()
    assert rec.handle == "didi"


# ---------------------------------------------------------------------------
# Reconcile detectors
# ---------------------------------------------------------------------------


def test_detector_flags_uncommitted(lab_mgmt):
    (lab_mgmt / "members" / "hand_edit.md").write_text("---\nhandle: '@x'\n---\n")
    kinds = {f.kind for f in _rc.detect_lab_mgmt_unsynced()}
    assert "lab_mgmt_uncommitted" in kinds


def test_detector_flags_unpushed(lab_mgmt, tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    _git(lab_mgmt, "remote", "add", "origin", str(remote))
    _git(lab_mgmt, "push", "-u", "origin", "HEAD")
    assert _rc.detect_lab_mgmt_unsynced() == []          # clean + pushed
    _m.add(handle="didi", full_name="Didi")              # commits, push fails? no —
    # push succeeds here (file remote), so still clean:
    assert all(f.kind != "lab_mgmt_unpushed" for f in _rc.detect_lab_mgmt_unsynced())
    # Now a local commit the push can't reach: break the remote URL first.
    _git(lab_mgmt, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    _m.add(handle="zed", full_name="Zed")                # commit ok, push fails
    kinds = {f.kind for f in _rc.detect_lab_mgmt_unsynced()}
    assert "lab_mgmt_unpushed" in kinds
    assert "lab_mgmt_uncommitted" not in kinds           # tree itself is clean


def test_detector_silent_without_git(monkeypatch, tmp_path):
    root = tmp_path / "plain"
    (root / "members").mkdir(parents=True)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))
    assert _rc.detect_lab_mgmt_unsynced() == []
