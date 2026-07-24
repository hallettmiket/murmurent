"""Tests for ``murmurent project push`` (:mod:`murmurent.commands.project_push_cmd`).

Everything runs against real temp git repos + a local bare remote — no network,
no real vault, no real Slack. The cert-project registry is monkeypatched so a
constructed :class:`CertProject` (with ``RepoRef``s pointing at the temp repos)
drives the run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.commands import project_push_cmd as pp
from murmurent.core import cert_projects as _cp

# An AWS access key id shape (AKIA + 16 upper/digits) the scanner blocks on.
PLANTED_SECRET = "AKIAIOSFODNN7EXAMPLE"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _make_repo(root: Path, name: str, *, with_remote: bool = True,
               bad_remote: bool = False):
    """A committed git repo. ``with_remote`` wires a local bare origin (and pushes
    the initial commit). ``bad_remote`` points origin at a nonexistent bare so a
    push is rejected."""
    repo = root / name
    repo.mkdir(parents=True)
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@example.com"], repo)
    _run(["git", "config", "user.name", "Tester"], repo)
    (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "init"], repo)
    bare = None
    if bad_remote:
        _run(["git", "remote", "add", "origin", str(root / "nope" / f"{name}.git")], repo)
    elif with_remote:
        bare = root / f"{name}.git"
        _run(["git", "init", "--bare", str(bare)], root)
        _run(["git", "remote", "add", "origin", str(bare)], repo)
        _run(["git", "push", "-u", "origin", "main"], repo)
    return repo, bare


def _ref(repo: Path, name: str):
    return _cp.RepoRef(name=name, role="code", host="local", path=str(repo))


def _install_project(monkeypatch, name: str, refs, *, channel: str = ""):
    cp = _cp.CertProject(name=name, lab="mh", repos=tuple(refs))
    monkeypatch.setattr(_cp, "get", lambda n, env=None: cp if n == name else None)
    monkeypatch.setattr(_cp, "slack_channel_for", lambda n, env=None: channel)
    return cp


def _local_head(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _remote_head(bare: Path) -> str:
    return _run(["git", "rev-parse", "main"], bare).stdout.strip()


def _change(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_multi_repo_happy_path(monkeypatch, tmp_path):
    """Two repos, each with a change → both committed AND pushed to their bare
    remotes; exit code 0; summary counts 2 of 2."""
    r1, b1 = _make_repo(tmp_path, "code_repo")
    r2, b2 = _make_repo(tmp_path, "docs_repo")
    _change(r1, "src/a.py", "x = 1\n")
    _change(r2, "notes.md", "hello\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "code_repo"), _ref(r2, "docs_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.exit_code == 0
    assert [r.status for r in report.results] == [pp.STATUS_PUSHED, pp.STATUS_PUSHED]
    # Each bare remote actually advanced to the new local HEAD.
    assert _remote_head(b1) == _local_head(r1)
    assert _remote_head(b2) == _local_head(r2)
    assert "2 of 2" in pp.summary_line(report)


def test_planted_secret_blocks_only_that_repo(monkeypatch, tmp_path):
    """A repo with a hardcoded secret is blocked (no commit, nothing staged); the
    clean sibling still pushes; exit code 1."""
    r1, b1 = _make_repo(tmp_path, "clean_repo")
    r2, _b2 = _make_repo(tmp_path, "secret_repo")
    _change(r1, "src/ok.py", "y = 2\n")
    _change(r2, "config.py", f"AWS_KEY = '{PLANTED_SECRET}'\n")
    before = _local_head(r2)
    _install_project(monkeypatch, "proj",
                     [_ref(r1, "clean_repo"), _ref(r2, "secret_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.exit_code == 1
    by = {r.name: r for r in report.results}
    assert by["clean_repo"].status == pp.STATUS_PUSHED
    assert by["secret_repo"].status == pp.STATUS_BLOCKED_SECRET
    # Blocked repo: NOT committed, and nothing left staged.
    assert _local_head(r2) == before
    assert _run(["git", "diff", "--cached", "--name-only"], r2).stdout.strip() == ""
    # The clean repo still reached its remote.
    assert _remote_head(b1) == _local_head(r1)
    # The redacted finding is carried; the raw secret never is.
    assert by["secret_repo"].findings
    blob = repr(by["secret_repo"].findings) + by["secret_repo"].detail + by["secret_repo"].git_detail
    assert PLANTED_SECRET not in blob


def test_uncloned_repo_is_skipped(monkeypatch, tmp_path):
    """A repo the member hasn't cloned (path doesn't exist) is reported as not on
    this computer, not an error."""
    r1, b1 = _make_repo(tmp_path, "here_repo")
    _change(r1, "a.txt", "z\n")
    missing = _cp.RepoRef(name="away_repo", host="local",
                          path=str(tmp_path / "not_cloned_anywhere"))
    _install_project(monkeypatch, "proj", [_ref(r1, "here_repo"), missing])

    report = pp.push_project("proj", post_slack=False)

    by = {r.name: r for r in report.results}
    assert by["away_repo"].status == pp.STATUS_NOT_CLONED
    assert by["here_repo"].status == pp.STATUS_PUSHED
    # One local clone pushed cleanly, the other merely skipped → exit 0.
    assert report.exit_code == 0
    assert "skipped" in pp.summary_line(report)


def test_no_changes_reports_already_backed_up(monkeypatch, tmp_path):
    """A repo with no local changes reports up-to-date, not an empty commit."""
    r1, b1 = _make_repo(tmp_path, "quiet_repo")
    head_before = _local_head(r1)
    _install_project(monkeypatch, "proj", [_ref(r1, "quiet_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_UP_TO_DATE
    assert report.exit_code == 0
    assert _local_head(r1) == head_before   # no empty commit created


def test_push_rejection_is_surfaced(monkeypatch, tmp_path):
    """When the remote refuses the push, the commit stands locally and the repo is
    reported as needing attention (exit 1) — not silently dropped."""
    r1, _ = _make_repo(tmp_path, "norights_repo", with_remote=False, bad_remote=True)
    _change(r1, "src/x.py", "q = 9\n")
    before = _local_head(r1)
    _install_project(monkeypatch, "proj", [_ref(r1, "norights_repo")])

    report = pp.push_project("proj", post_slack=False)

    res = report.results[0]
    assert res.status == pp.STATUS_PUSH_REJECTED
    assert res.short_hash                       # a commit WAS made
    assert _local_head(r1) != before
    assert report.exit_code == 1


def test_governed_path_blocks(monkeypatch, tmp_path):
    """A change under a governed-data path (append_only/) blocks the repo."""
    r1, _ = _make_repo(tmp_path, "gov_repo")
    _change(r1, "append_only/proj/out.csv", "a,b\n1,2\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "gov_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_BLOCKED_GOVERNED
    assert report.exit_code == 1


def test_secret_shaped_filename_blocks(monkeypatch, tmp_path):
    """A newly added ``id_ed25519`` private-key-shaped file blocks the repo even
    with innocuous content (the filename alone is the tell)."""
    r1, _ = _make_repo(tmp_path, "key_repo")
    _change(r1, "id_ed25519", "not actually a key\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "key_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_BLOCKED_SECRET_FILE
    assert report.exit_code == 1


def test_large_file_blocks(monkeypatch, tmp_path):
    """A >1 MB file under a tracked dir blocks the repo."""
    r1, _ = _make_repo(tmp_path, "big_repo")
    _change(r1, "data/huge.bin", "x" * (pp._LARGE_BYTES + 1))
    _install_project(monkeypatch, "proj", [_ref(r1, "big_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_BLOCKED_LARGE
    assert report.exit_code == 1


def test_settings_json_is_skipped_not_staged(monkeypatch, tmp_path):
    """.claude/settings.json is never staged; it's added to .gitignore instead,
    and a real code change still pushes."""
    r1, b1 = _make_repo(tmp_path, "cfg_repo")
    _change(r1, ".claude/settings.json", '{"machine": "/abs/path"}\n')
    _change(r1, "src/real.py", "v = 3\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "cfg_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_PUSHED
    committed = _run(["git", "show", "--name-only", "--format=", "HEAD"], r1).stdout
    assert ".claude/settings.json" not in committed
    assert "src/real.py" in committed
    assert ".claude/settings.json" in (r1 / ".gitignore").read_text()


def test_project_not_found_exit_2(monkeypatch, tmp_path):
    monkeypatch.setattr(_cp, "get", lambda n, env=None: None)
    report = pp.push_project("ghost", post_slack=False)
    assert report.found is False
    assert report.exit_code == 2
    assert "Couldn't find" in pp.summary_line(report)


def test_nothing_pushable_exit_2(monkeypatch, tmp_path):
    """A project whose only repos are un-cloned → nothing to push → exit 2."""
    missing = _cp.RepoRef(name="gone", host="local",
                          path=str(tmp_path / "nowhere"))
    _install_project(monkeypatch, "proj", [missing])
    report = pp.push_project("proj", post_slack=False)
    assert report.exit_code == 2


def test_remote_host_repo_skipped(monkeypatch, tmp_path):
    """A repo whose tree lives on another host is flagged, not pushed from here."""
    r1, b1 = _make_repo(tmp_path, "local_repo")
    _change(r1, "a.txt", "hi\n")
    remote_ref = _cp.RepoRef(name="hpc_repo", host="cluster",
                             remote_path="/scratch/hpc_repo")
    _install_project(monkeypatch, "proj",
                     [_ref(r1, "local_repo"), remote_ref])

    report = pp.push_project("proj", post_slack=False)

    by = {r.name: r for r in report.results}
    assert by["hpc_repo"].status == pp.STATUS_REMOTE_HOST
    assert "cluster" in by["hpc_repo"].detail
    assert report.exit_code == 0


def test_shared_commit_message(monkeypatch, tmp_path):
    """--message applies the same message to every repo's commit."""
    r1, b1 = _make_repo(tmp_path, "m_repo")
    _change(r1, "a.txt", "hi\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "m_repo")])

    pp.push_project("proj", message="sync before the review", post_slack=False)

    subject = _run(["git", "log", "-1", "--format=%s"], r1).stdout.strip()
    assert subject == "sync before the review"


def test_render_report_and_detail(monkeypatch, tmp_path):
    r1, b1 = _make_repo(tmp_path, "rr_repo")
    _change(r1, "a.txt", "hi\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "rr_repo")])

    report = pp.push_project("proj", post_slack=False)
    plain = pp.render_report(report, detail=False)
    detailed = pp.render_report(report, detail=True)

    assert "rr_repo" in plain
    assert "saved to GitHub" in plain
    # --detail surfaces the branch + short hash, absent from the plain view.
    assert report.results[0].short_hash in detailed
    assert report.results[0].short_hash not in plain


def test_renamed_file_pushes_cleanly(monkeypatch, tmp_path):
    """A rename (git mv) is staged at BOTH ends and pushed — the remote reflects
    the move with nothing left behind in the working tree."""
    r1, b1 = _make_repo(tmp_path, "mv_repo")
    _change(r1, "old.txt", "content\n")
    _run(["git", "add", "-A"], r1)
    _run(["git", "commit", "-m", "add old"], r1)
    _run(["git", "push", "-q", "origin", "main"], r1)
    _run(["git", "mv", "old.txt", "new.txt"], r1)
    _install_project(monkeypatch, "proj", [_ref(r1, "mv_repo")])

    report = pp.push_project("proj", post_slack=False)

    assert report.results[0].status == pp.STATUS_PUSHED
    assert _remote_head(b1) == _local_head(r1)
    assert _run(["git", "status", "--porcelain"], r1).stdout.strip() == ""
    committed = _run(["git", "show", "--name-status", "--format=", "HEAD"], r1).stdout
    assert "new.txt" in committed and "old.txt" in committed


def test_slack_note_posts_once_when_channel_present(monkeypatch, tmp_path):
    """With a channel configured + a token available, exactly one Slack note is
    posted after the loop, ending with the required footer."""
    r1, b1 = _make_repo(tmp_path, "s_repo")
    _change(r1, "a.txt", "hi\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "s_repo")], channel="C123")

    posts = []
    monkeypatch.setattr(
        "murmurent.core.cert_provision.resolve_project_slack",
        lambda name, env=None: ("mh", "xoxb-fake"))
    monkeypatch.setattr(
        "murmurent.dashboard.slack_notify._post",
        lambda channel, text, token=None: posts.append((channel, text, token)) or True)

    report = pp.push_project("proj", post_slack=True)

    assert report.slack_posted is True
    assert len(posts) == 1
    channel, text, token = posts[0]
    assert channel == "C123"
    assert token == "xoxb-fake"
    assert text.rstrip().endswith("All worship me and I will let you serve me.")


def test_slack_skipped_silently_without_channel(monkeypatch, tmp_path):
    r1, b1 = _make_repo(tmp_path, "ns_repo")
    _change(r1, "a.txt", "hi\n")
    _install_project(monkeypatch, "proj", [_ref(r1, "ns_repo")], channel="")

    report = pp.push_project("proj", post_slack=True)
    assert report.slack_posted is False
