"""Tests for Phase 2 of ``murmurent project push`` — managed GitHub mirrors
(:mod:`murmurent.commands.project_push_cmd` + the ``mirrors`` field / helpers in
:mod:`murmurent.core.cert_projects`).

Everything runs against real temp git repos + local bare remotes used as BOTH the
primary origin AND the mirror destinations — no network, no real Slack. The
mirror round-trip tests drive a real (temp) lab-mgmt registry via
``MURMURENT_LAB_MGMT_REPO``; the push tests monkeypatch ``cert_projects.get`` with
a constructed :class:`CertProject` whose ``RepoRef``s carry ``mirrors``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.commands import project_push_cmd as pp
from murmurent.core import cert_projects as _cp


# ---------------------------------------------------------------------------
# helpers (mirror the style of test_project_push.py)
# ---------------------------------------------------------------------------

def _run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _make_repo(root: Path, name: str):
    """A committed git repo wired to a local bare ``origin`` (initial commit
    pushed). Returns ``(repo, origin_bare)``."""
    repo = root / name
    repo.mkdir(parents=True)
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@example.com"], repo)
    _run(["git", "config", "user.name", "Tester"], repo)
    (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "init"], repo)
    bare = root / f"{name}.git"
    _run(["git", "init", "--bare", str(bare)], root)
    _run(["git", "remote", "add", "origin", str(bare)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)
    return repo, bare


def _bare(root: Path, name: str) -> Path:
    """A standalone bare repo to serve as a mirror destination."""
    bare = root / f"{name}.git"
    _run(["git", "init", "--bare", str(bare)], root)
    return bare


def _ref(repo: Path, name: str, *, mirrors=()):
    return _cp.RepoRef(name=name, role="code", host="local", path=str(repo),
                       mirrors=tuple(mirrors))


def _install_project(monkeypatch, name: str, refs, *, channel: str = ""):
    cp = _cp.CertProject(name=name, lab="mh", repos=tuple(refs))
    monkeypatch.setattr(_cp, "get", lambda n, env=None: cp if n == name else None)
    monkeypatch.setattr(_cp, "slack_channel_for", lambda n, env=None: channel)
    return cp


def _local_head(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _remote_head(bare: Path, ref: str = "main") -> str:
    return _run(["git", "rev-parse", ref], bare).stdout.strip()


def _change(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _count_remotes(repo: Path, prefix: str = "mm-mirror-") -> int:
    out = _run(["git", "remote"], repo).stdout.split()
    return sum(1 for r in out if r.startswith(prefix))


# ---------------------------------------------------------------------------
# 1. mirror add / remove / list round-trip in the project MD
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry_env(tmp_path, monkeypatch):
    """Point cert_projects at a throwaway lab-mgmt repo dir. ``_persist``'s
    commit/push no-ops harmlessly outside a git checkout."""
    root = tmp_path / "lab_mgmt"
    root.mkdir()
    env = {"MURMURENT_LAB_MGMT_REPO": str(root)}
    # cert_projects resolves the registry via lab_mgmt_repo_root(env); the helpers
    # accept env=, so we thread this env through each call.
    return env


def test_mirror_add_remove_list_roundtrip(registry_env):
    env = registry_env
    _cp.upsert("proj", lab="mh",
               repos=[_cp.RepoRef(name="code_repo", role="code", path="/x")],
               env=env)

    assert _cp.list_mirrors("proj", "code_repo", env=env) == ()

    _cp.add_mirror("proj", "code_repo", "labB/brca", env=env)
    _cp.add_mirror("proj", "code_repo", "git@github.com:labC/brca.git", env=env)
    # Re-read from disk: the mirrors persisted into the frontmatter.
    got = _cp.list_mirrors("proj", "code_repo", env=env)
    assert got == ("labB/brca", "git@github.com:labC/brca.git")

    # Idempotent add — duplicate is a no-op.
    _cp.add_mirror("proj", "code_repo", "labB/brca", env=env)
    assert _cp.list_mirrors("proj", "code_repo", env=env) == got

    # The on-disk YAML actually carries the mirrors under the repo entry.
    raw = _cp.project_path("proj", env).read_text(encoding="utf-8")
    assert "mirrors" in raw and "labB/brca" in raw

    _cp.remove_mirror("proj", "code_repo", "labB/brca", env=env)
    assert _cp.list_mirrors("proj", "code_repo", env=env) == \
        ("git@github.com:labC/brca.git",)


def test_mirror_helpers_reject_unknown_repo(registry_env):
    env = registry_env
    _cp.upsert("proj", lab="mh",
               repos=[_cp.RepoRef(name="code_repo", role="code", path="/x")],
               env=env)
    with pytest.raises(_cp.CertProjectError):
        _cp.add_mirror("proj", "ghost_repo", "labB/brca", env=env)
    with pytest.raises(_cp.CertProjectError):
        _cp.list_mirrors("nope_project", "code_repo", env=env)
    with pytest.raises(_cp.CertProjectError):
        _cp.remove_mirror("proj", "code_repo", "never/added", env=env)


def test_mirror_add_by_project_name_targets_primary(registry_env):
    """Passing the project name (not the repo name) targets the primary repo —
    the common single-repo convenience."""
    env = registry_env
    _cp.upsert("proj", lab="mh",
               repos=[_cp.RepoRef(name="the_code", role="code", path="/x")],
               env=env)
    _cp.add_mirror("proj", "proj", "labB/brca", env=env)
    assert _cp.list_mirrors("proj", "the_code", env=env) == ("labB/brca",)


# ---------------------------------------------------------------------------
# 2. push updates primary + 2 mirrors
# ---------------------------------------------------------------------------

def test_push_updates_primary_and_two_mirrors(monkeypatch, tmp_path):
    repo, origin = _make_repo(tmp_path, "code_repo")
    m1 = _bare(tmp_path, "labB_mirror")
    m2 = _bare(tmp_path, "labC_mirror")
    _change(repo, "src/a.py", "x = 1\n")
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(m1), str(m2)))])

    report = pp.push_project("proj", post_slack=False)

    res = report.results[0]
    assert res.status == pp.STATUS_PUSHED
    assert report.exit_code == 0
    # Primary AND both mirrors advanced to the new local HEAD.
    head = _local_head(repo)
    assert _remote_head(origin) == head
    assert _remote_head(m1) == head
    assert _remote_head(m2) == head
    # Two per-remote mirror results, both successful.
    assert len(res.mirrors) == 2
    assert all(m.status == pp.MIRROR_PUSHED for m in res.mirrors)
    assert not report.mirror_failures


# ---------------------------------------------------------------------------
# 3. one unreachable mirror → primary still pushed, per-remote failure, exit 1
# ---------------------------------------------------------------------------

def test_unreachable_mirror_surfaces_but_primary_pushes(monkeypatch, tmp_path):
    repo, origin = _make_repo(tmp_path, "code_repo")
    good = _bare(tmp_path, "good_mirror")
    bad = tmp_path / "nope" / "missing_mirror.git"   # never created → unreachable
    _change(repo, "src/a.py", "x = 1\n")
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(good), str(bad)))])

    report = pp.push_project("proj", post_slack=False)

    res = report.results[0]
    # Primary reached origin regardless of the mirror failure.
    assert res.status == pp.STATUS_PUSHED
    assert _remote_head(origin) == _local_head(repo)
    assert _remote_head(good) == _local_head(repo)
    # Per-remote outcomes: one ok, one failed.
    by = {m.remote_name: m for m in res.mirrors}
    statuses = sorted(m.status for m in res.mirrors)
    assert statuses == [pp.MIRROR_FAILED, pp.MIRROR_PUSHED]
    # A mirror failure downgrades the exit code to 1 (partial) but is NOT a
    # blocked/attention primary.
    assert report.exit_code == 1
    assert report.attention == []
    assert len(report.mirror_failures) == 1
    # The failure reads novice-friendly + mentions the PI in the summary.
    assert "tell your PI" in pp.summary_line(report)
    line = pp.render_report(report)
    assert "also backed up to" in line


# ---------------------------------------------------------------------------
# 4. no mirrors → behaviour identical to Phase 1 (regression)
# ---------------------------------------------------------------------------

def test_no_mirrors_is_phase1_identical(monkeypatch, tmp_path):
    repo, origin = _make_repo(tmp_path, "code_repo")
    _change(repo, "src/a.py", "x = 1\n")
    _install_project(monkeypatch, "proj", [_ref(repo, "code_repo")])  # no mirrors

    report = pp.push_project("proj", post_slack=False)

    res = report.results[0]
    assert res.status == pp.STATUS_PUSHED
    assert res.mirrors == []
    assert report.exit_code == 0
    assert report.mirror_failures == []
    assert _remote_head(origin) == _local_head(repo)
    # No mm-mirror-* remote was ever created on the clone.
    assert _count_remotes(repo) == 0
    # The summary line is exactly the Phase-1 shape (no mirror clause).
    assert "extra backup" not in pp.summary_line(report)


# ---------------------------------------------------------------------------
# 5. idempotent remote management — re-run doesn't duplicate remotes
# ---------------------------------------------------------------------------

def test_mirror_remote_management_is_idempotent(monkeypatch, tmp_path):
    repo, origin = _make_repo(tmp_path, "code_repo")
    m1 = _bare(tmp_path, "labB_mirror")
    _change(repo, "src/a.py", "x = 1\n")
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(m1),))])

    pp.push_project("proj", post_slack=False)
    assert _count_remotes(repo) == 1
    remotes_after_first = sorted(_run(["git", "remote"], repo).stdout.split())

    # A second change + push must NOT add a duplicate remote.
    _change(repo, "src/b.py", "y = 2\n")
    report2 = pp.push_project("proj", post_slack=False)
    assert _count_remotes(repo) == 1
    assert sorted(_run(["git", "remote"], repo).stdout.split()) == remotes_after_first
    # And the mirror still advanced to the newest HEAD.
    assert _remote_head(m1) == _local_head(repo)
    assert report2.results[0].mirrors[0].status == pp.MIRROR_PUSHED
    # origin was never mangled into a mirror.
    assert _run(["git", "remote", "get-url", "origin"], repo).stdout.strip() \
        == str(origin)


def test_mirror_url_drift_is_corrected(monkeypatch, tmp_path):
    """If a mm-mirror-* remote already exists pointing at the wrong URL, the sync
    corrects it in place (set-url) rather than adding a second remote."""
    repo, _origin = _make_repo(tmp_path, "code_repo")
    m1 = _bare(tmp_path, "right_mirror")
    remote = pp._mirror_remote_name(str(m1))
    # Pre-seed the remote at a bogus URL.
    _run(["git", "remote", "add", remote, str(tmp_path / "wrong.git")], repo)
    _change(repo, "src/a.py", "x = 1\n")
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(m1),))])

    pp.push_project("proj", post_slack=False)

    assert _count_remotes(repo) == 1
    assert _run(["git", "remote", "get-url", remote], repo).stdout.strip() == str(m1)
    assert _remote_head(m1) == _local_head(repo)


# ---------------------------------------------------------------------------
# 6. up-to-date primary still syncs a lagging mirror
# ---------------------------------------------------------------------------

def test_up_to_date_primary_still_updates_lagging_mirror(monkeypatch, tmp_path):
    """No local changes (primary already on origin), but a freshly added mirror is
    behind → the mirror is brought up to the branch HEAD anyway."""
    repo, _origin = _make_repo(tmp_path, "code_repo")
    m1 = _bare(tmp_path, "late_mirror")   # empty; never received the branch
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(m1),))])

    report = pp.push_project("proj", post_slack=False)

    res = report.results[0]
    assert res.status == pp.STATUS_UP_TO_DATE
    assert res.mirrors and res.mirrors[0].status == pp.MIRROR_PUSHED
    assert _remote_head(m1) == _local_head(repo)
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# 7. Slack note carries the per-mirror lines
# ---------------------------------------------------------------------------

def test_slack_body_includes_mirror_lines(monkeypatch, tmp_path):
    repo, _origin = _make_repo(tmp_path, "code_repo")
    m1 = _bare(tmp_path, "labB_mirror")
    _change(repo, "a.txt", "hi\n")
    _install_project(monkeypatch, "proj",
                     [_ref(repo, "code_repo", mirrors=(str(m1),))], channel="C1")

    posts = []
    monkeypatch.setattr(
        "murmurent.core.cert_provision.resolve_project_slack",
        lambda name, env=None: ("mh", "xoxb-fake"))
    monkeypatch.setattr(
        "murmurent.dashboard.slack_notify._post",
        lambda channel, text, token=None: posts.append((channel, text)) or True)

    report = pp.push_project("proj", post_slack=True)

    assert report.slack_posted is True
    _channel, text = posts[0]
    assert "also backed up to" in text
    assert text.rstrip().endswith("All worship me and I will let you serve me.")
