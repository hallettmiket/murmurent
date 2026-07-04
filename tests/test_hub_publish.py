"""Tests for hub_publish: clone-if-needed + idempotent upsert of the centre's
row in join/directory.tsv and the README table. No network — the clone path
uses an injected runner."""

from __future__ import annotations

import pytest

from wigamig.core import hub_publish as H


DIRECTORY = (
    "# wigamig institution directory — machine-readable, read by wigamig-join.sh.\n"
    "# institution\temail\tage_recipient\n"
    "Western University (Bioconvergence Centre)\n"
)

README = (
    "# Join a wigamig institution\n\n"
    "## Institutions using wigamig\n\n"
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
    assert body.startswith("# wigamig institution directory")


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
