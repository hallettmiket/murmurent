"""Tests for core/vault_sync.py — best-effort commit+push + ff-only pull of the
personal vault (murmurent_vault). Uses real *local* git repos + a bare remote so
nothing touches the network or the developer's real vault.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.core import vault_sync as VS
from murmurent.dashboard import machine_settings as MS


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=False)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "T")


def _init_repo_with_remote(root: Path, remote: Path) -> None:
    """A working clone at ``root`` wired to a bare remote at ``remote``."""
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _init_repo(root)
    (root / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    _git(root, "branch", "-M", "main")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "-u", "origin", "main")


@pytest.fixture
def pin_vault(monkeypatch, tmp_path):
    """Redirect machine.yaml so personal_vault_root() resolves to our tmp dir."""
    machine_yaml = tmp_path / "murmurent" / "machine.yaml"
    monkeypatch.setattr(MS, "MACHINE_FILE", machine_yaml)

    def _pin(path: Path) -> None:
        from murmurent.dashboard.contract import MachineSettings
        MS.write(MachineSettings(obsidian_vault_path=str(path)))

    return _pin


# ---- personal_vault_root -----------------------------------------------------

def test_personal_vault_root_unregistered(pin_vault):
    assert VS.personal_vault_root() is None


def test_personal_vault_root_from_machine_yaml(pin_vault, tmp_path):
    pin_vault(tmp_path / "myvault")
    assert VS.personal_vault_root() == tmp_path / "myvault"


# ---- commit_and_push ---------------------------------------------------------

def test_commit_and_push_commits_and_pushes(tmp_path):
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    _init_repo_with_remote(clone, remote)
    (clone / "oracle").mkdir()
    (clone / "oracle" / "note.md").write_text("hi\n", encoding="utf-8")

    res = VS.commit_and_push(clone, message="add note")
    assert res.ok and res.committed and res.pushed
    # the remote actually advanced
    log = subprocess.run(["git", "-C", str(remote), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "add note" in log


def test_commit_and_push_accepts_file_path_inside_vault(tmp_path):
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    _init_repo_with_remote(clone, remote)
    f = clone / "lab-notebook" / "2026-07-16.md"
    f.parent.mkdir()
    f.write_text("entry\n", encoding="utf-8")

    res = VS.commit_and_push(f, message="notebook entry")
    assert res.ok and res.committed and res.pushed


def test_commit_and_push_nothing_to_commit_is_ok(tmp_path):
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    _init_repo_with_remote(clone, remote)
    res = VS.commit_and_push(clone, message="noop")
    assert res.ok and res.committed is False


def test_commit_and_push_push_failure_never_crashes_write(tmp_path):
    """The core contract (memo §6.2): a broken remote must NOT lose the commit."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    (clone / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-q", "-m", "seed")
    # A remote that points nowhere → push fails, but the commit must land.
    _git(clone, "remote", "add", "origin", str(tmp_path / "does_not_exist.git"))
    (clone / "new.md").write_text("new\n", encoding="utf-8")

    res = VS.commit_and_push(clone, message="local commit")
    assert res.ok is True and res.committed is True and res.pushed is False
    assert VS._last_commit_iso(clone)  # commit is really there


def test_commit_and_push_no_remote_is_soft(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    (clone / "a.md").write_text("a\n", encoding="utf-8")
    res = VS.commit_and_push(clone, message="first")
    assert res.ok and res.committed and res.pushed is False
    assert "no remote" in res.detail


def test_commit_and_push_not_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    res = VS.commit_and_push(plain, message="x")
    assert res.ok is False and "not a git" in res.detail


def test_commit_and_push_missing_path(tmp_path):
    # Neither the path nor its parent exists → the "does not exist" branch.
    res = VS.commit_and_push(tmp_path / "missing" / "deeper", message="x")
    assert res.ok is False and "does not exist" in res.detail


# ---- vault_info --------------------------------------------------------------

def test_vault_info_unregistered(pin_vault):
    info = VS.vault_info()
    assert info.is_git is False and info.ok is False
    assert "no personal vault registered" in info.detail


def test_vault_info_not_cloned(pin_vault, tmp_path):
    pin_vault(tmp_path / "ghost")
    info = VS.vault_info()
    assert info.is_git is False and info.ok is False and "no personal vault clone" in info.detail


def test_vault_info_plain_dir(pin_vault, tmp_path):
    d = tmp_path / "plainvault"; d.mkdir()
    pin_vault(d)
    info = VS.vault_info()
    assert info.is_git is False and info.ok is True and "not a git clone" in info.detail


def test_vault_info_git_reports_freshness(pin_vault, tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    (clone / "a.md").write_text("a\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-q", "-m", "seed")
    pin_vault(clone)
    info = VS.vault_info()
    assert info.is_git and info.ok and info.as_of  # ISO timestamp present


# ---- pull_personal_vault -----------------------------------------------------

def test_pull_personal_vault_fast_forwards(pin_vault, tmp_path):
    remote = tmp_path / "remote.git"
    clone_a = tmp_path / "a"
    _init_repo_with_remote(clone_a, remote)
    # A second clone that pushes a new commit upstream.
    clone_b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone_b)], check=True)
    _git(clone_b, "config", "user.email", "b@b"); _git(clone_b, "config", "user.name", "B")
    (clone_b / "fromb.md").write_text("b\n", encoding="utf-8")
    _git(clone_b, "add", "-A"); _git(clone_b, "commit", "-q", "-m", "from b")
    _git(clone_b, "push", "-q")

    pin_vault(clone_a)
    res = VS.pull_personal_vault()
    assert res.ok and res.is_git
    assert (clone_a / "fromb.md").exists()  # ff pull landed the new file


def test_pull_personal_vault_no_remote_is_soft(pin_vault, tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    (clone / "a.md").write_text("a\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-q", "-m", "seed")
    pin_vault(clone)
    res = VS.pull_personal_vault()
    assert res.ok and "no remote" in res.detail


def test_pull_personal_vault_unregistered(pin_vault):
    res = VS.pull_personal_vault()
    assert res.is_git is False and res.ok is False
