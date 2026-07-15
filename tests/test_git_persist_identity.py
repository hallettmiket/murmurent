"""Regression tests for git identity fallback in ``core.git_persist``.

murmurent#21 (reporter tt8804): a member saved their profile in the
dashboard on a fresh machine with no ``git config --global user.email/
user.name``. The auto-commit into their read-only lab_mgmt clone failed
with *"Author identity unknown … unable to auto-detect email address
(got 'tt@tt-ThinkPad-T15-Gen-2i.(none)')"* and the profile edit never
landed in a commit. ``commit_and_push`` must set a best-effort repo-local
identity so the save succeeds even without any user git config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.core import git_persist as _gp


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Plain git — no forced identity, so it reflects real config state."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True)


def _seed_commit(root: Path, message: str) -> None:
    """Commit with an explicit ad-hoc identity, for fixture setup only."""
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=seed@seed",
         "-c", "user.name=seed", "commit", "-m", message],
        check=True, capture_output=True, text=True)


@pytest.fixture
def repo_no_identity(tmp_path, monkeypatch):
    """A git repo with a tracked file and NO resolvable git identity.

    We isolate git from any global/system config by pointing HOME + the
    git config env vars at empty locations, reproducing a fresh member
    machine. ``MURMURENT_USER`` is cleared so identity.resolve can't
    smuggle in a handle from the ambient env either.
    """
    root = tmp_path / "lab-mgmt"
    (root / "members").mkdir(parents=True)

    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    empty_cfg = tmp_path / "empty.gitconfig"
    empty_cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_cfg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.delenv("MURMURENT_USER", raising=False)
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(var, raising=False)

    _git(root, "init", "-b", "main")
    # Force git to REFUSE auto-detecting an identity from username@hostname.
    # tt8804's ThinkPad had an unresolvable hostname domain ('...(none)') so
    # git hard-failed; on hosts where auto-detection *would* succeed this
    # setting reproduces the same failure deterministically.
    _git(root, "config", "user.useConfigOnly", "true")
    member = root / "members" / "tt8804.md"
    member.write_text("---\nhandle: '@tt8804'\n---\n", encoding="utf-8")
    _git(root, "add", "-A")
    _seed_commit(root, "seed")
    return root, member


def _last_msg(root: Path) -> str:
    return _git(root, "log", "-1", "--format=%s").stdout.strip()


def test_commit_succeeds_without_user_git_identity(repo_no_identity):
    """The exact murmurent#21 scenario: no identity → commit must still land."""
    root, member = repo_no_identity
    member.write_text(
        "---\nhandle: '@tt8804'\ngithub: tt8804\n---\n", encoding="utf-8")

    # Sanity: a bare commit here fails exactly the way tt8804 saw.
    _git(root, "add", "-A")
    bare = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "bare"],
        capture_output=True, text=True)
    assert bare.returncode != 0
    assert "identity" in (bare.stderr + bare.stdout).lower()

    # The file is staged and differs from HEAD (nothing was committed).
    probes = _gp.commit_and_push(member, message="profile: @tt8804", push=False)

    commit_probe = next(p for p in probes if p.name == "git commit")
    assert commit_probe.status == "ok", commit_probe.detail
    assert _last_msg(root) == "profile: @tt8804"
    # Tree is clean → the edit is now durable in a commit, not just on disk.
    assert _git(root, "status", "--porcelain").stdout.strip() == ""


def test_repo_local_identity_uses_murmurent_domain(repo_no_identity):
    """Fallback identity is written repo-locally with the murmurent domain."""
    root, member = repo_no_identity
    member.write_text(
        "---\nhandle: '@tt8804'\ngithub: tt8804\n---\n", encoding="utf-8")
    _gp.commit_and_push(member, message="profile: @tt8804", push=False)
    email = _git(root, "config", "--get", "user.email").stdout.strip()
    assert email.endswith("@murmurent.local")


def test_existing_identity_is_not_overwritten(tmp_path):
    """If the machine already has a git identity, we leave it untouched."""
    root = tmp_path / "lab-mgmt"
    (root / "members").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Real Person")
    _git(root, "config", "user.email", "real@person.example")
    member = root / "members" / "tt8804.md"
    member.write_text("---\nhandle: '@tt8804'\n---\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "seed")

    member.write_text(
        "---\nhandle: '@tt8804'\ngithub: tt8804\n---\n", encoding="utf-8")
    _gp.commit_and_push(member, message="profile: @tt8804", push=False)

    assert _git(root, "config", "--get", "user.email").stdout.strip() \
        == "real@person.example"
    # The commit is authored by the real identity, not the fallback.
    assert _git(root, "log", "-1", "--format=%ae").stdout.strip() \
        == "real@person.example"


def test_push_403_explains_read_only_clone(tmp_path, monkeypatch):
    """#21 follow-up: a member's push to lab_mgmt fails 403 BY DESIGN
    (read-only clones). The probe must say so — not 'run git push
    manually when ready', which a member can never do."""
    import subprocess
    from types import SimpleNamespace
    from murmurent.core import git_persist as GP

    repo = tmp_path / "lm"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://github.com/corewestern/lab_mgmt.git"],
                   check=True, capture_output=True)
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        if cmd[:2] == ["git", "-C"] and "push" in cmd:
            return SimpleNamespace(returncode=128, stdout="",
                                   stderr="fatal: unable to access "
                                          "'https://github.com/corewestern/lab_mgmt.git/': "
                                          "The requested URL returned error: 403")
        return real_run(cmd, **kw)

    monkeypatch.setattr(GP.subprocess, "run", fake_run)
    probe = GP._push(repo)
    assert probe.status == "warn"
    assert "READ-ONLY" in probe.detail
    assert "run `git push` manually" not in probe.detail
    assert "git reset --hard" in probe.detail
