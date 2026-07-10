"""Tests for hub_publish: clone-if-needed + idempotent upsert of the centre's
row in join/directory.tsv and the README table. No network — the clone path
uses an injected runner."""

from __future__ import annotations

import pytest

from murmurent.core import hub_publish as H


DIRECTORY = (
    "# murmurent institution directory — machine-readable, read by wigamig-join.sh.\n"
    "# institution\temail\tage_recipient\n"
    "Western University (Bioconvergence Centre)\n"
)

README = (
    "# Join a murmurent institution\n\n"
    "## Institutions using murmurent\n\n"
    "| Institution | Installation | Email to join | age key (encrypt to this) |\n"
    "|---|---|---|---|\n"
    "| Western University | Bioconvergence Centre | _(added when live)_ | _(added when live)_ |\n\n"
    "**Don't see your institution?** ask your PI.\n\n"
    "## Where's the software?\n"
)


@pytest.fixture()
def hub(tmp_path):
    (tmp_path / "join").mkdir()
    (tmp_path / "join" / "directory.tsv").write_text(DIRECTORY, encoding="utf-8")
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    return tmp_path


# ---- directory.tsv --------------------------------------------------------

def test_directory_replaces_placeholder_for_same_institution(hub):
    action = H.upsert_directory(hub, "Western University", "Nirvana",
                                "the_pi@example.edu", "age1abc")
    assert action == "updated"                       # replaced the not-live placeholder
    body = (hub / "join" / "directory.tsv").read_text()
    assert "Western University (Nirvana)\tthe_pi@example.edu\tage1abc" in body
    assert "Bioconvergence Centre" not in body       # placeholder gone
    # comments preserved
    assert body.startswith("# murmurent institution directory")


def test_directory_idempotent(hub):
    H.upsert_directory(hub, "Western University", "Nirvana", "m@example.edu", "age1abc")
    assert H.upsert_directory(hub, "Western University", "Nirvana", "m@example.edu", "age1abc") == "unchanged"


def test_directory_update_on_key_change_matches_by_label(hub):
    H.upsert_directory(hub, "Western University", "Nirvana", "m@example.edu", "age1old")
    action = H.upsert_directory(hub, "Western University", "Nirvana", "m@example.edu", "age1new")
    assert action == "updated"
    body = (hub / "join" / "directory.tsv").read_text()
    assert "age1new" in body and "age1old" not in body
    assert body.count("Western University (Nirvana)") == 1   # no duplicate


def test_directory_append_for_new_institution(hub):
    action = H.upsert_directory(hub, "McMaster University", "MacLab", "x@mcmaster.ca", "age1z")
    assert action == "added"
    body = (hub / "join" / "directory.tsv").read_text()
    assert "McMaster University (MacLab)\tx@mcmaster.ca\tage1z" in body
    assert "Western University (Bioconvergence Centre)" in body   # untouched


# ---- README table ---------------------------------------------------------

def test_readme_replaces_placeholder(hub):
    action = H.upsert_readme(hub, "Western University", "Nirvana", "m@example.edu", "age1abc")
    assert action == "updated"
    body = (hub / "README.md").read_text()
    assert "| Western University | Nirvana | m@example.edu | age1abc |" in body
    assert "_(added when live)_" not in body


def test_readme_idempotent_then_append(hub):
    H.upsert_readme(hub, "Western University", "Nirvana", "m@example.edu", "age1abc")
    assert H.upsert_readme(hub, "Western University", "Nirvana", "m@example.edu", "age1abc") == "unchanged"
    action = H.upsert_readme(hub, "McMaster University", "MacLab", "x@mcmaster.ca", "age1z")
    assert action == "added"
    body = (hub / "README.md").read_text()
    assert "| McMaster University | MacLab | x@mcmaster.ca | age1z |" in body
    # inserted inside the table, before the "Don't see" line
    assert body.index("MacLab") < body.index("Don't see your institution")


# ---- clone + orchestrator -------------------------------------------------

def test_ensure_clone_reuses_existing(hub):
    (hub / ".git").mkdir()
    calls = []
    cloned = H.ensure_hub_clone(hub, runner=lambda *a, **k: calls.append(a))
    assert cloned is False and calls == []


def test_ensure_clone_errors_on_nonempty_nongit(tmp_path):
    (tmp_path / "stuff.txt").write_text("x")
    with pytest.raises(H.HubPublishError):
        H.ensure_hub_clone(tmp_path, runner=lambda *a, **k: None)


def test_prepare_listing_requires_age_recipient(hub):
    (hub / ".git").mkdir()
    with pytest.raises(H.HubPublishError):
        H.prepare_listing(institution="Western", name="Nirvana",
                          email="m@example.edu", recipient="",
                          hub_dir=hub, runner=lambda *a, **k: None)


def test_prepare_listing_full_flow(hub):
    (hub / ".git").mkdir()                       # existing clone → runner unused
    res = H.prepare_listing(institution="Western University", name="Nirvana",
                            email="the_pi@example.edu", recipient="age1abc",
                            hub_dir=hub, runner=lambda *a, **k: None)
    assert res.cloned is False
    assert res.directory_action == "updated" and res.readme_action == "updated"
    assert res.row == "Western University (Nirvana)\tthe_pi@example.edu\tage1abc"


# ---- submit: direct push vs fork + PR -------------------------------------

class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _runner(responses=None, record=None):
    responses = responses or {}
    def run(cmd, capture_output=False, text=False):
        if record is not None:
            record.append(cmd)
        key = " ".join(cmd)
        for pat, proc in responses.items():
            if pat in key:
                return proc
        return _Proc(0, "", "")
    return run


@pytest.mark.parametrize("url,slug", [
    ("https://github.com/hallettmiket/wigamig_public.git", "hallettmiket/wigamig_public"),
    ("git@github.com:hallettmiket/wigamig_public.git", "hallettmiket/wigamig_public"),
    ("https://github.com/foo/bar", "foo/bar"),
])
def test_parse_upstream_slug(url, slug):
    assert H.parse_upstream_slug(url) == slug


def test_gh_available():
    assert H.gh_available(runner=_runner({"auth status": _Proc(0)})) is True
    assert H.gh_available(runner=_runner({"auth status": _Proc(1)})) is False
    def boom(*a, **k):
        raise FileNotFoundError
    assert H.gh_available(runner=boom) is False


def test_can_push_parses_gh():
    assert H.can_push("o/r", runner=_runner({"api repos/o/r": _Proc(0, "true\n")})) is True
    assert H.can_push("o/r", runner=_runner({"api repos/o/r": _Proc(0, "false\n")})) is False
    assert H.can_push("o/r", runner=_runner({"api repos/o/r": _Proc(1)})) is None


def test_submit_direct_sequence(tmp_path):
    rec = []
    res = H.submit_direct(tmp_path, "directory: list Nirvana", runner=_runner(record=rec))
    assert res.mode == "pushed"
    joined = [" ".join(c) for c in rec]
    assert any("add join/directory.tsv README.md" in j for j in joined)
    assert any('commit -m directory: list Nirvana' in j for j in joined)
    assert joined[-1].endswith("push")


def test_submit_pr_sequence(tmp_path):
    rec = []
    resp = {"api user": _Proc(0, "the_pi\n"),
            "pr create": _Proc(0, "https://github.com/hallettmiket/wigamig_public/pull/7\n")}
    res = H.submit_pr(tmp_path, "hallettmiket/wigamig_public", branch="list-nirvana",
                      message="m", title="t", body="b", runner=_runner(resp, rec))
    assert res.mode == "pr" and res.detail.endswith("/pull/7")
    joined = [" ".join(c) for c in rec]
    assert any("repo fork hallettmiket/wigamig_public --remote --remote-name fork" in j for j in joined)
    assert any("checkout -B list-nirvana" in j for j in joined)
    assert any("push -u fork list-nirvana --force" in j for j in joined)
    assert any("pr create --repo hallettmiket/wigamig_public --head the_pi:list-nirvana" in j for j in joined)


def test_submit_pr_reuses_existing_pr(tmp_path):
    resp = {"api user": _Proc(0, "the_pi\n"),
            "pr create": _Proc(1, "", "a pull request already exists for the_pi:list-x"),
            "pr view": _Proc(0, "https://github.com/o/r/pull/3\n")}
    res = H.submit_pr(tmp_path, "o/r", branch="list-x", message="m", title="t",
                      body="b", runner=_runner(resp))
    assert res.mode == "pr" and res.detail.endswith("/pull/3")


def test_submit_pr_needs_gh_login(tmp_path):
    with pytest.raises(H.HubPublishError):
        H.submit_pr(tmp_path, "o/r", branch="b", message="m", title="t", body="b",
                    runner=_runner({"api user": _Proc(1)}))


def test_command_submit_publishes_even_when_files_unchanged(monkeypatch, tmp_path):
    """--submit must still publish when the row is already written locally
    ("unchanged") — a prior run writes the files without pushing, and the old
    code wrongly bailed with "nothing to publish"."""
    from click.testing import CliRunner
    from murmurent.commands import centre_cmd as CC

    class _Prof:
        institution = "Western University"; name = "Western Samadhi"
        join_email = "m@example.edu"; unique_name = "samadhi"; age_recipient = "age1abc"

    monkeypatch.setattr(CC._ci, "read_centre", lambda *a, **k: _Prof())
    monkeypatch.setattr(H, "prepare_listing", lambda **k: H.HubPublishResult(
        hub_dir=tmp_path, cloned=False, directory_action="unchanged",
        readme_action="unchanged", row="Western University (Western Samadhi)\tm@example.edu\tage1abc"))
    monkeypatch.setattr(H, "gh_available", lambda *a, **k: True)
    monkeypatch.setattr(H, "upstream_slug", lambda *a, **k: "hallettmiket/wigamig_public")
    monkeypatch.setattr(H, "can_push", lambda *a, **k: True)
    called = {}
    def fake_direct(hub_dir, msg, **k):
        called["direct"] = (hub_dir, msg)
        return H.SubmitResult("pushed", "pushed to origin")
    monkeypatch.setattr(H, "submit_direct", fake_direct)

    res = CliRunner().invoke(CC.centre_hub_publish, ["--submit"])
    assert res.exit_code == 0, res.output
    assert "direct" in called                       # pushed despite "unchanged"
    assert "listed on the public hub" in res.output


def test_command_no_submit_when_unchanged_tells_you_to_submit(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from murmurent.commands import centre_cmd as CC

    class _Prof:
        institution = "U"; name = "C"; join_email = "m@u"; unique_name = "c"
        age_recipient = "age1abc"
    monkeypatch.setattr(CC._ci, "read_centre", lambda *a, **k: _Prof())
    monkeypatch.setattr(H, "prepare_listing", lambda **k: H.HubPublishResult(
        hub_dir=tmp_path, cloned=False, directory_action="unchanged",
        readme_action="unchanged", row="row"))
    res = CliRunner().invoke(CC.centre_hub_publish, [])   # no --submit
    assert res.exit_code == 0
    assert "--submit" in res.output and "on the public hub" in res.output
