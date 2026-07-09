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


# ---- standalone PI (no mayor / centre) --------------------------------------

def test_standalone_pi_self_issues_and_runs_a_lab(monkeypatch, tmp_path):
    # PI machine — no centre, no mayor, just their own identity key.
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    K.generate_keypair()
    out = ISS.self_issue_pi_card("@yxia266", "xia_lab")
    trust = out["trust_root"]
    assert trust.startswith("ed25519:")
    # the PI now resolves locally as their lab's PI
    assert R.lab_mgmt_path_for_handle("yxia266")[0] == "xia_lab"

    # a member enrolls; the PI issues them a card with NO centre in sight
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="xia_lab")
    bundle = ISS.issue_member_card("@allie", enrollment=m_req, group="xia_lab")
    assert bundle["member_card"]["payload"]["kind"] == "member"

    # the member imports it, pinning the PI's key (the trust root) — chains
    # member -> PI(self-root), no centre.
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "allie_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "allie_li"))
    verdict, _actions = ISS.verify_and_import_member_card(bundle, trust_root=trust)
    assert verdict.ok and verdict.handle == "@allie" and verdict.group == "xia_lab"
    assert R.lab_mgmt_path_for_handle("allie")[0] == "xia_lab"


def test_cli_whoami_shows_trust_root_for_pi(monkeypatch, tmp_path):
    from wigamig.cli import cli
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    K.generate_keypair()
    ISS.self_issue_pi_card("@mhallet", "lab_mh")
    res = CliRunner().invoke(cli, ["whoami"])
    assert res.exit_code == 0, res.output
    assert "trust root" in res.output
    assert K.encode_public(K.load_public()) in res.output   # retrievable any time


def test_cli_issue_member_card_prints_trust_root_when_standalone(monkeypatch, tmp_path):
    from wigamig.cli import cli
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    K.generate_keypair()
    out = ISS.self_issue_pi_card("@mhallet", "lab_mh")
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="lab_mh")
    ef = tmp_path / "e.json"
    ef.write_text(json.dumps(m_req), encoding="utf-8")
    bf = tmp_path / "b.json"
    res = CliRunner().invoke(cli, ["issue-member-card", str(ef), "--group", "lab_mh",
                                   "--out", str(bf)])
    assert res.exit_code == 0, res.output
    assert out["trust_root"] in res.output          # PI told exactly what to hand over
    assert "import-card" in res.output


def test_issuance_writes_the_roster(monkeypatch, tmp_path):
    """pi-init + issue-member-card make the roster (members/*.md) the single source
    of truth: PI + member land there with email, github, and card fingerprint/id;
    revoke_member reads the fingerprint back from the roster."""
    import yaml as _yaml
    from wigamig.core import centre_root as CR
    from wigamig.core import membership as M
    from wigamig.core import repo as R
    from wigamig.core import revocation as REV

    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.delenv("WIGAMIG_LAB_MGMT_REPO", raising=False)   # use the pinned pointer
    K.generate_keypair()
    (tmp_path / "pi").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pi" / "profile.yaml").write_text(
        _yaml.safe_dump({"email": "pi@x.edu", "github": "pigh"}), encoding="utf-8")

    out = ISS.self_issue_pi_card("@yxia266", "lab_mh")
    lab_repo = R.lab_repo_path("lab_mh")
    assert (lab_repo / "members").is_dir()
    assert R.lab_mgmt_repo_root() == lab_repo                    # pointer resolves here
    pi_rec = M.parse_member(M.member_path("yxia266"))
    assert pi_rec.role == "pi" and pi_rec.email == "pi@x.edu" and pi_rec.github == "pigh"
    assert pi_rec.card_fingerprint == out["pi_card"]["payload"]["subject"]["fingerprint"]

    # a member enrolls (email/github travel in the enrollment) -> on the roster
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="lab_mh",
                                      email="allie@x.edu", github="@alliegh")
    bundle = ISS.issue_member_card("@allie", enrollment=m_req, group="lab_mh")
    allie_rec = M.parse_member(M.member_path("allie"))
    assert allie_rec.email == "allie@x.edu" and allie_rec.github == "alliegh"
    assert allie_rec.status == "active"
    assert allie_rec.card_fingerprint == bundle["member_card"]["payload"]["subject"]["fingerprint"]

    # revoke_member reads the fingerprint from the roster
    CR.generate_root_key()
    crl = REV.revoke_member("lab_mh", "allie")
    assert allie_rec.card_fingerprint in crl["payload"]["revoked"]


def test_standalone_pi_requires_a_group_name(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "li"))
    K.generate_keypair()
    with pytest.raises(ISS.IssuanceError, match="name is required"):
        ISS.self_issue_pi_card("@yxia266", "")


# ---- member cards (group registrar = the PI) --------------------------------

def _install_machine_key(priv):
    """Make ``priv`` this machine's idkeys key (so the PI machine signs member
    cards with the same key bound in its PI card)."""
    from cryptography.hazmat.primitives import serialization
    p = K.private_key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    K._pub_for(p).write_text(K.encode_public(priv.public_key()) + "\n", encoding="utf-8")


def _carded_pi(mayor_world, monkeypatch, tmp_path, home="pi_home"):
    """Issue a PI card for @yxia266 and import it onto a fresh PI machine whose
    machine key IS the PI's key. Leaves env pointed at the PI machine."""
    pi_priv = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request("@yxia266", priv=pi_priv, nonce="p1",
                                    centre="western-qa")
    pi_card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    root_pub = mayor_world["root_pub"]
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / home))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / (home + "_li")))
    _install_machine_key(pi_priv)
    ISS.verify_and_import_pi_card(pi_card, trust_root=root_pub)
    return {"pi_priv": pi_priv, "root_pub": root_pub}


def _member_enrollment(handle="@allie", nonce="a1", group="yxia_lab"):
    priv = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request(handle, priv=priv, nonce=nonce,
                                    centre="western-qa", group=group)
    return priv, req


def test_member_card_full_chain(mayor_world, monkeypatch, tmp_path):
    ctx = _carded_pi(mayor_world, monkeypatch, tmp_path)
    _priv, m_req = _member_enrollment()
    bundle = ISS.issue_member_card("@allie", enrollment=m_req, group="yxia_lab")
    assert bundle["member_card"]["payload"]["kind"] == "member"
    assert bundle["pi_card"]["payload"]["subject"]["handle"] == "@yxia266"
    # member machine imports the bundle and now resolves as a member of the lab
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "allie_home"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "allie_li"))
    verdict, actions = ISS.verify_and_import_member_card(bundle, trust_root=ctx["root_pub"])
    assert verdict.ok and verdict.handle == "@allie" and verdict.group == "yxia_lab"
    match = R.lab_mgmt_path_for_handle("allie")
    assert match is not None and match[0] == "yxia_lab"
    assert IC.machine_netname() == "allie"


def test_member_card_requires_leading_the_group(mayor_world, monkeypatch, tmp_path):
    _carded_pi(mayor_world, monkeypatch, tmp_path)
    _priv, m_req = _member_enrollment(group="")
    with pytest.raises(ISS.IssuanceError, match="do not lead"):
        ISS.issue_member_card("@allie", enrollment=m_req, group="some_other_lab")


def test_member_card_rejects_bad_proof_of_possession(mayor_world, monkeypatch, tmp_path):
    _carded_pi(mayor_world, monkeypatch, tmp_path)
    _priv, m_req = _member_enrollment()
    m_req["payload"]["handle"] = "@evil"  # tamper → self-signature invalid
    with pytest.raises(ISS.IssuanceError, match="possession"):
        ISS.issue_member_card("@allie", enrollment=m_req, group="yxia_lab")


def test_member_card_from_forged_pi_rejected(mayor_world, monkeypatch, tmp_path):
    ctx = _carded_pi(mayor_world, monkeypatch, tmp_path)
    _priv, m_req = _member_enrollment()
    good = ISS.issue_member_card("@allie", enrollment=m_req, group="yxia_lab")
    # attacker re-signs the member card with their own key, keeps the real PI card
    attacker = Ed25519PrivateKey.generate()
    forged = C.issue_member_card(handle="@allie", member_pubkey=m_req["payload"]["pubkey"],
                                 group="yxia_lab", centre="western-qa",
                                 pi_priv=attacker, pi_handle="@yxia266")
    bad_bundle = {"member_card": forged, "pi_card": good["pi_card"]}
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "allie2"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "allie2_li"))
    with pytest.raises(ISS.IssuanceError, match="rejected"):
        ISS.verify_and_import_member_card(bad_bundle, trust_root=ctx["root_pub"])


def test_cli_member_card_round_trip(mayor_world, monkeypatch, tmp_path):
    from wigamig.cli import cli
    ctx = _carded_pi(mayor_world, monkeypatch, tmp_path)  # env at the PI machine
    runner = CliRunner()
    _priv, m_req = _member_enrollment()
    enroll_f = tmp_path / "m_enroll.json"
    enroll_f.write_text(json.dumps(m_req), encoding="utf-8")
    bundle_f = tmp_path / "bundle.json"
    r = runner.invoke(cli, ["issue-member-card", str(enroll_f), "--group", "yxia_lab",
                            "--out", str(bundle_f)])
    assert r.exit_code == 0, r.output
    # member machine imports it
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "allie_cli"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "allie_cli_li"))
    r2 = runner.invoke(cli, ["import-card", str(bundle_f), "--trust-root", ctx["root_pub"]])
    assert r2.exit_code == 0, r2.output
    assert "verified" in r2.output and "member" in r2.output
    assert R.lab_mgmt_path_for_handle("allie")[0] == "yxia_lab"


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
