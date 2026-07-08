"""
Tests for core/issuance.py — PI-card issuance (mayor side) + verify-and-import
(PI side), the end-to-end Phase 3 flow, with the attack cases:
proof-of-possession failure, issuing to a non-PI, a card from the wrong root, and
a trust-anchor mismatch.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wigamig.core import centre_init as CI
from wigamig.core import centre_root as CR
from wigamig.core import idcert as C
from wigamig.core import identity_card as IC
from wigamig.core import idkeys as K
from wigamig.core import issuance as ISS
from wigamig.core import registrar as R


@pytest.fixture
def mayor_world(monkeypatch, tmp_path):
    """Mayor's machine: a centre with a lab + a core, and the centre root key."""
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
    CR.generate_root_key()
    return {"tmp": tmp_path, "root_pub": CR.root_public()}


def _enrollment(handle="@yxia266", nonce="n1", centre="western-qa"):
    """A PI-side proof-of-possession request built from a fresh keypair."""
    priv = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request(handle, priv=priv, nonce=nonce, centre=centre)
    return priv, req


# ---- issue (mayor side) -----------------------------------------------------

def test_issue_pi_card_happy(mayor_world):
    priv, req = _enrollment()
    card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    p = card["payload"]
    assert p["kind"] == "pi" and p["subject"]["handle"] == "@yxia266"
    # the card binds the exact key the PI proved possession of
    assert p["subject"]["pubkey"] == K.encode_public(priv.public_key())
    assert any(r["kind"] == "lab_pi" for r in p["roles"])
    v = C.verify_pi_card(card, root_pub=mayor_world["root_pub"], require_crl=False,
                         centre="western-qa")
    assert v.ok


def test_issue_pi_card_for_core_leader(mayor_world):
    _priv, req = _enrollment(handle="@emucaki")
    card = ISS.issue_pi_card("@emucaki", enrollment=req, actor="@tbrowne5")
    assert any(r["kind"] == "core_leader" for r in card["payload"]["roles"])


def test_issue_rejects_bad_proof_of_possession(mayor_world):
    _priv, req = _enrollment()
    req["payload"]["handle"] = "@someone_else"  # tamper → self-signature invalid
    with pytest.raises(ISS.IssuanceError, match="possession"):
        ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")


def test_issue_rejects_non_pi(mayor_world):
    _priv, req = _enrollment(handle="@allie")
    with pytest.raises(ISS.IssuanceError):
        ISS.issue_pi_card("@allie", enrollment=req, actor="@tbrowne5")


def test_issue_requires_root_key(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "li"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lm"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "h"))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", tmp_path / "sentinel")
    CI.init_centre(name="QA", institution="U", founding_mayor="@tbrowne5",
                   unique_name="qa", write_sentinel=False)
    R.create_lab(name="l", display_name="L", pi_handle="@yxia266", pi_email="y@x.edu")
    _priv, req = _enrollment(centre="qa")
    with pytest.raises(ISS.IssuanceError, match="root key"):
        ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")


# ---- verify + import (PI side) ---------------------------------------------

def test_verify_and_import_materializes_role(mayor_world, monkeypatch, tmp_path):
    _priv, req = _enrollment()
    card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    root_pub = mayor_world["root_pub"]
    # move to a FRESH PI machine
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_lab_info"))
    verdict, actions = ISS.verify_and_import_pi_card(card, trust_root=root_pub)
    assert verdict.ok and verdict.handle == "@yxia266"
    # the PI's own machine now resolves them as the lab PI
    match = R.lab_mgmt_path_for_handle("yxia266")
    assert match is not None and match[0] == "yxia_lab"
    # anchor pinned, netname stamped, signed card stored
    assert C.load_pinned_root("western-qa") == root_pub
    assert IC.machine_netname() == "yxia266"
    assert (ISS.cards_dir() / "western-qa_pi.json").is_file()


def test_import_needs_trust_anchor(mayor_world, monkeypatch, tmp_path):
    _priv, req = _enrollment()
    card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi2"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi2_li"))
    with pytest.raises(ISS.IssuanceError, match="trust anchor"):
        ISS.verify_and_import_pi_card(card)  # nothing pinned, no --trust-root


def test_import_rejects_anchor_mismatch(mayor_world, monkeypatch, tmp_path):
    _priv, req = _enrollment()
    card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi3"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi3_li"))
    # a DIFFERENT root is already pinned → offering the real one fails closed
    other = K.encode_public(Ed25519PrivateKey.generate().public_key())
    C.pin_root("western-qa", other)
    with pytest.raises(ISS.IssuanceError, match="mismatch|anchor"):
        ISS.verify_and_import_pi_card(card, trust_root=mayor_world["root_pub"])


def test_import_rejects_card_from_wrong_root(mayor_world, monkeypatch, tmp_path):
    _priv, req = _enrollment()
    evil_root = Ed25519PrivateKey.generate()
    forged = C.issue_pi_card(handle="@yxia266", pi_pubkey=req["payload"]["pubkey"],
                             centre="western-qa", root_priv=evil_root)
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi4"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi4_li"))
    with pytest.raises(ISS.IssuanceError, match="rejected"):
        ISS.verify_and_import_pi_card(forged, trust_root=mayor_world["root_pub"])


# ---- CLI --------------------------------------------------------------------

def test_cli_enroll_produces_valid_request(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("WIGAMIG_USER", "yxia266")
    monkeypatch.delenv("WIGAMIG_NO_AUTOKEY", raising=False)  # allow first-run keygen
    from wigamig.cli import cli
    res = CliRunner().invoke(cli, ["enroll", "--nonce", "abc"])
    assert res.exit_code == 0, res.output
    req = json.loads(res.output)
    assert req["payload"]["handle"] == "@yxia266"
    assert C.verify_enrollment(req, expected_nonce="abc")


def test_cli_issue_and_import_round_trip(mayor_world, monkeypatch, tmp_path):
    from wigamig.cli import cli
    runner = CliRunner()
    # PI builds an enrollment (fresh key), writes it to a file
    priv, req = _enrollment()
    enroll_f = tmp_path / "enroll.json"
    enroll_f.write_text(json.dumps(req), encoding="utf-8")
    card_f = tmp_path / "card.json"
    res = runner.invoke(cli, ["issue-pi-card", str(enroll_f), "--actor", "@tbrowne5",
                              "--out", str(card_f)])
    assert res.exit_code == 0, res.output
    assert card_f.is_file()
    # PI machine imports it
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    res2 = runner.invoke(cli, ["import-card", str(card_f), "--trust-root",
                               mayor_world["root_pub"]])
    assert res2.exit_code == 0, res2.output
    assert "verified" in res2.output
    assert R.lab_mgmt_path_for_handle("yxia266")[0] == "yxia_lab"
