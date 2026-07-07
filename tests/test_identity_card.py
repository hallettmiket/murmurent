"""
Tests for decentralized identity cards — putting a member's role onto THEIR
machine so their dashboard login resolves correctly and an arbitrary netname is
refused.
"""

from __future__ import annotations

import pytest

from wigamig.core import centre_init as CI
from wigamig.core import identity_card as IC
from wigamig.core import registrar as R


@pytest.fixture
def mayor_world(monkeypatch, tmp_path):
    """The MAYOR's machine: a full centre registry with a lab + a core."""
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "mayor_lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "mayor_lab_mgmt"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "mayor_home"))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", tmp_path / "sentinel")
    CI.init_centre(name="Western QA", institution="U", founding_mayor="@tbrowne5",
                   unique_name="western-qa", write_sentinel=False)
    R.create_lab(name="yxia_lab", display_name="Xia Lab",
                 pi_handle="@yxia266", pi_email="y@x.edu")
    R.create_core(name="western_core", display_name="Western Core",
                  leader_handle="@emucaki", leader_email="e@x.edu")
    return tmp_path


# ---- build_card (mayor side) -------------------------------------------

def test_build_card_core_leader(mayor_world):
    card = IC.build_card("emucaki", issued_by="@tbrowne5")
    assert card["netname"] == "emucaki"
    assert card["centre"] == "western-qa"
    kinds = {(r["kind"], r.get("group")) for r in card["roles"]}
    assert ("core_leader", "western_core") in kinds
    assert not any(r["kind"] == "lab_pi" for r in card["roles"])  # NOT a lab PI


def test_build_card_lab_pi(mayor_world):
    card = IC.build_card("yxia266")
    assert any(r["kind"] == "lab_pi" and r["group"] == "yxia_lab" for r in card["roles"])


def test_build_card_unknown_raises(mayor_world):
    with pytest.raises(ValueError, match="no role"):
        IC.build_card("nobody_here")


# ---- import_card (member side) → scoped registry resolves --------------

def test_import_card_materializes_role_on_member_machine(mayor_world, monkeypatch, tmp_path):
    # Mayor builds emucaki's card...
    card = IC.build_card("emucaki", issued_by="@tbrowne5")
    # ...then we move to a FRESH member machine (separate home + registry root).
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "member_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "member_lab_info"))
    IC.import_card(card)

    # The member's machine now independently resolves emucaki as the core leader.
    match = R.lab_mgmt_path_for_handle("emucaki")
    assert match is not None and match[0] == "western_core"
    reg = R.read_registry()
    assert "western_core" in {c.name for c in reg.cores}
    assert R._normalize(reg.cores[0].pi) == "emucaki"
    # An arbitrary netname resolves to nothing (the scoping gate would refuse).
    assert R.lab_mgmt_path_for_handle("totally_made_up") is None
    # The machine's netname is stamped + the card is retrievable.
    assert (tmp_path / "member_home" / "user").read_text().strip() == "emucaki"
    assert IC.machine_netname() == "emucaki"


def test_card_yaml_round_trips(mayor_world):
    card = IC.build_card("emucaki")
    reparsed = IC.parse_card(IC.card_yaml(card))
    assert reparsed["netname"] == "emucaki"
    assert reparsed["roles"] == card["roles"]


# ---- netname enforcement on the dashboard ------------------------------

def test_dashboard_refuses_wrong_netname_on_carded_machine(mayor_world, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from wigamig.dashboard.server import create_app
    # Build the card while the MAYOR registry is active, THEN move to the
    # member machine (separate home + registry root) and import it.
    card = IC.build_card("emucaki")
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "member_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "member_lab_info"))
    IC.import_card(card)
    client = TestClient(create_app())
    # Signing in as anyone but the machine owner → refused.
    res = client.get("/api/dashboard?user=someone_else")
    assert res.status_code == 403
    assert "registered to @emucaki" in res.json()["detail"]
