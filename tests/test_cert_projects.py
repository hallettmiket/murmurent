"""
Tests for core/cert_projects.py — the lab-scoped cert-project registry
(idempotent upsert, member de-dup, status flips, member lens).
"""

from __future__ import annotations

import pytest

from wigamig.core import cert_projects as CP


@pytest.fixture(autouse=True)
def _lab_mgmt(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab_mgmt"))


def test_upsert_creates_then_adds_members():
    CP.upsert("rna_atlas", lab="lab_mh", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"}, today="2026-07-09")
    CP.upsert("rna_atlas", lab="lab_mh", member="bob",
              cert={"fingerprint": "fb", "card_id": "cB"}, today="2026-07-10")
    p = CP.get("rna_atlas")
    assert p.lab == "lab_mh" and p.status == "active" and p.created == "2026-07-09"
    assert p.members == ("@allie", "@bob")           # bob normalized to @bob
    assert {c["handle"] for c in p.certs} == {"@allie", "@bob"}


def test_upsert_is_idempotent_and_replaces_cert():
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "old", "card_id": "c1"})
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "new", "card_id": "c2"})   # re-issue
    p = CP.get("p")
    assert p.members == ("@allie",)                  # not duplicated
    assert len(p.certs) == 1 and p.certs[0]["fingerprint"] == "new"


def test_set_status_and_member_lens():
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "f", "card_id": "c"})
    assert [x.name for x in CP.projects_for_member("allie")] == ["p"]
    CP.set_status("p", "archived")
    assert CP.get("p").status == "archived"
    assert CP.projects_for_member("allie") == []     # archived drops out of the lens


def test_set_status_missing_is_noop():
    assert CP.set_status("ghost", "archived") is None


def test_iter_projects_skips_and_sorts():
    CP.upsert("beta", lab="lab_mh")
    CP.upsert("alpha", lab="lab_mh")
    assert [p.name for p in CP.iter_projects()] == ["alpha", "beta"]


def test_enrichment_fields_round_trip():
    CP.upsert("p", lab="lab_mh", lead="@the_pi", sensitivity="Clinical",
              choreography="hub", code_repo="~/repos/p", github_repo="org/p")
    p = CP.get("p")
    assert p.lead == "@the_pi" and p.sensitivity == "clinical"   # normalized
    assert p.choreography == "hub" and p.code_repo == "~/repos/p"
    assert p.github_repo == "org/p"


def test_membership_upsert_preserves_metadata():
    CP.upsert("p", lab="lab_mh", lead="@the_pi", sensitivity="restricted",
              code_repo="~/repos/p")
    # a later membership-only upsert (as issue_project_card does) must NOT wipe
    # the previously-set project metadata
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "f", "card_id": "c"})
    p = CP.get("p")
    assert p.sensitivity == "restricted" and p.lead == "@the_pi"
    assert p.code_repo == "~/repos/p" and "@allie" in p.members


def test_set_status_preserves_metadata():
    CP.upsert("p", lab="lab_mh", sensitivity="clinical", code_repo="~/repos/p")
    CP.set_status("p", "archived")
    p = CP.get("p")
    assert p.status == "archived" and p.sensitivity == "clinical"
    assert p.code_repo == "~/repos/p"


def test_backfill_from_charter(monkeypatch, tmp_path):
    """Existing CHARTER code-projects are mirrored into the cert-project registry
    with their name/lab/sensitivity/lead/members and a code_repo link."""
    from wigamig.core import charter as _charter
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    repo = tmp_path / "repos" / "dcis_sc"
    repo.mkdir(parents=True)
    (repo / "CHARTER.md").write_text(
        "---\nproject: dcis_sc\nlab: hallett\nsensitivity: clinical\n"
        "lead: '@allie'\nchoreography: clinical_cohort\n"
        "reb_number: WREM-1\nreb_expires: '2027-01-01'\ndata_residency: ca\n"
        "members: ['@allie', '@bob']\n---\n\n# dcis_sc\n", encoding="utf-8")

    touched = CP.backfill_from_charter()
    assert "dcis_sc" in touched
    p = CP.get("dcis_sc")
    assert p.lab == "hallett" and p.sensitivity == "clinical" and p.lead == "@allie"
    assert p.choreography == "clinical_cohort"
    assert str(repo) in p.code_repo
    assert set(p.members) == {"@allie", "@bob"}
    # idempotent: a second run doesn't duplicate members
    CP.backfill_from_charter()
    assert list(CP.get("dcis_sc").members).count("@allie") == 1
