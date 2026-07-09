"""
Roster-as-source-of-truth model: member records carry the card fingerprint/id,
`upsert_member` add-or-updates (what card issuance will call), and a persistent
pointer resolves a standalone lab's roster location.
"""

from __future__ import annotations

import pytest

from wigamig.core import membership as M
from wigamig.core import repo as R


@pytest.fixture
def lab(monkeypatch, tmp_path):
    root = tmp_path / "lab-mgmt"
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(root))
    (root / "members").mkdir(parents=True)
    return root


def test_add_persists_github_and_card_fields(lab):
    M.add(handle="allie", full_name="Allie", role="postdoc", email="a@x.edu",
          github="@alliegh", card_fingerprint="SHA256:fp", card_id="cid1")
    rec = M.parse_member(M.member_path("allie"))
    assert rec.github == "alliegh"           # @ stripped
    assert rec.card_fingerprint == "SHA256:fp" and rec.card_id == "cid1"
    assert "card_fingerprint: SHA256:fp" in M.member_path("allie").read_text()


def test_upsert_creates_then_updates_subset(lab):
    r1 = M.upsert_member("allie", email="a@x.edu", github="gh1",
                         card_fingerprint="fp1", card_id="c1")
    assert r1.status == "active" and r1.email == "a@x.edu" and r1.role == "staff"
    r2 = M.upsert_member("allie", github="gh2")          # update only github
    assert r2.github == "gh2" and r2.email == "a@x.edu"  # email preserved
    assert r2.card_fingerprint == "fp1"                  # preserved


def test_upsert_reactivates(lab):
    M.add(handle="allie", full_name="Allie")
    M.set_status("allie", "inactive")
    r = M.upsert_member("allie", card_fingerprint="fp")
    assert r.status == "active" and r.deactivated_at is None


def test_upsert_rejects_bad_role(lab):
    with pytest.raises(M.MembershipError):
        M.upsert_member("allie", role="member")          # not a VALID_ROLE


def test_lab_mgmt_pointer_resolves_and_env_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("WIGAMIG_LAB_MGMT_REPO", raising=False)
    # WIGAMIG_HOME is isolated by the conftest autouse; the pointer lives under it
    target = tmp_path / "repos" / "wigamig_lab_mh"
    R.set_lab_mgmt_path(target)
    assert R.lab_mgmt_repo_root() == target
    # an explicit env var still overrides the pointer
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "other"))
    assert R.lab_mgmt_repo_root() == tmp_path / "other"
