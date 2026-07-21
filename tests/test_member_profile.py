"""Unit tests for the member-owned profile staging store (#34 Option C).

``member_profile`` stages a member's dashboard profile edits into their OWN
``~/.murmurent/profile.yaml`` (under ``roster_profile``) instead of committing
to the read-only roster clone. These pin: the round-trip, the per-field merge
semantics (set / clear), the handle guard, and that init's flat keys survive.
"""

from __future__ import annotations

import pytest
import yaml

from murmurent.core import member_profile as mp


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_stage_and_read_back_round_trip(home):
    mp.stage_roster_profile("@bob", {
        "contact": {"email": "bob@x.edu", "orcid": "0000-0001"},
        "location": {"office": "MSB-1"},
        "official_handle": "@bobby",
        "slack": "bob.slack",
        "git_logins": {"github": "@bobgh"},
    })
    staged = mp.staged_roster_profile("bob")
    assert staged["contact"] == {"email": "bob@x.edu", "orcid": "0000-0001"}
    assert staged["location"] == {"office": "MSB-1"}
    assert staged["official_handle"] == "bobby"     # top-level handles @-stripped
    assert staged["slack"] == "bob.slack"
    # Block values are staged VERBATIM — normalization (e.g. @-stripping git
    # logins) happens at roster-write/ingest time, not in the staging store.
    assert staged["git_logins"] == {"github": "@bobgh"}
    assert "handle" not in staged                    # internal marker hidden


def test_partial_merge_and_clear_semantics(home):
    mp.stage_roster_profile("bob", {"contact": {"email": "a@b.c", "orcid": "x"}})
    # A later partial edit updates email, clears orcid, leaves nothing else.
    mp.stage_roster_profile("bob", {"contact": {"email": "new@b.c", "orcid": ""}})
    staged = mp.staged_roster_profile("bob")
    assert staged["contact"] == {"email": "new@b.c"}


def test_handle_guard_refuses_other_peoples_staged_block(home):
    mp.stage_roster_profile("bob", {"contact": {"email": "bob@x.edu"}})
    # A different handle must never read back bob's staged edits.
    assert mp.staged_roster_profile("alice") == {}
    assert mp.staged_roster_profile("bob")["contact"]["email"] == "bob@x.edu"


def test_staging_preserves_init_flat_keys(home):
    # profile.yaml as `murmurent init` writes it (flat contact keys).
    mp.profile_path().parent.mkdir(parents=True, exist_ok=True)
    mp.profile_path().write_text(
        yaml.safe_dump({"handle": "@bob", "role": "member", "email": "init@x.edu",
                        "github": "initgh"}), encoding="utf-8")
    mp.stage_roster_profile("bob", {"location": {"office": "MSB-9"}})
    prof = mp.read_profile()
    # Init's flat keys are untouched; staged edits live under roster_profile.
    assert prof["email"] == "init@x.edu" and prof["github"] == "initgh"
    assert prof["roster_profile"]["location"] == {"office": "MSB-9"}
