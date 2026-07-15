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

from murmurent.core import centre_init as CI
from murmurent.core import centre_root as CR
from murmurent.core import idcert as C
from murmurent.core import identity_card as IC
from murmurent.core import idkeys as K
from murmurent.core import issuance as ISS
from murmurent.core import registrar as R


@pytest.fixture
def mayor_world(monkeypatch, tmp_path):
    """Mayor's machine: a centre with a lab + a core, and the centre root key."""
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "mayor_lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "mayor_lab_mgmt"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mayor_home"))
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
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "li"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lm"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "h"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_lab_info"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi2"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi2_li"))
    with pytest.raises(ISS.IssuanceError, match="trust anchor"):
        ISS.verify_and_import_pi_card(card)  # nothing pinned, no --trust-root


def test_import_rejects_anchor_mismatch(mayor_world, monkeypatch, tmp_path):
    _priv, req = _enrollment()
    card = ISS.issue_pi_card("@yxia266", enrollment=req, actor="@tbrowne5")
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi3"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi3_li"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi4"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi4_li"))
    with pytest.raises(ISS.IssuanceError, match="rejected"):
        ISS.verify_and_import_pi_card(forged, trust_root=mayor_world["root_pub"])


# ---- CLI --------------------------------------------------------------------

def test_cli_enroll_produces_valid_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("MURMURENT_USER", "yxia266")
    monkeypatch.delenv("MURMURENT_NO_AUTOKEY", raising=False)  # allow first-run keygen
    from murmurent.cli import cli
    res = CliRunner().invoke(cli, ["enroll", "--nonce", "abc"])
    assert res.exit_code == 0, res.output
    req = json.loads(res.output)
    assert req["payload"]["handle"] == "@yxia266"
    assert C.verify_enrollment(req, expected_nonce="abc")


# ---- standalone PI (no mayor / centre) --------------------------------------

def test_standalone_pi_self_issues_and_runs_a_lab(monkeypatch, tmp_path):
    # PI machine — no centre, no mayor, just their own identity key.
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "allie_li"))
    verdict, _actions = ISS.verify_and_import_member_card(bundle, trust_root=trust)
    assert verdict.ok and verdict.handle == "@allie" and verdict.group == "xia_lab"
    assert R.lab_mgmt_path_for_handle("allie")[0] == "xia_lab"


def test_cli_whoami_shows_trust_root_for_pi(monkeypatch, tmp_path):
    from murmurent.cli import cli
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    K.generate_keypair()
    ISS.self_issue_pi_card("@the_pi", "lab_mh")
    res = CliRunner().invoke(cli, ["whoami"])
    assert res.exit_code == 0, res.output
    assert "trust root" in res.output
    assert K.encode_public(K.load_public()) in res.output   # retrievable any time


def test_cli_issue_member_card_prints_trust_root_when_standalone(monkeypatch, tmp_path):
    from murmurent.cli import cli
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    K.generate_keypair()
    out = ISS.self_issue_pi_card("@the_pi", "lab_mh")
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="lab_mh")
    ef = tmp_path / "e.json"
    ef.write_text(json.dumps(m_req), encoding="utf-8")
    bf = tmp_path / "b.json"
    res = CliRunner().invoke(cli, ["issue-member-card", str(ef), "--group", "lab_mh",
                                   "--out", str(bf), "--no-dm"])
    assert res.exit_code == 0, res.output
    assert out["trust_root"] in res.output          # PI told exactly what to hand over
    assert "import-card" in res.output


def _issue_member_card_setup(monkeypatch, tmp_path, *, email="allie@x.edu"):
    """Standalone PI + one member enrollment request on disk — shared setup
    for the --dm wiring tests below."""
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    K.generate_keypair()
    ISS.self_issue_pi_card("@the_pi", "lab_mh")
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1", group="lab_mh",
                                      email=email)
    ef = tmp_path / "e.json"
    ef.write_text(json.dumps(m_req), encoding="utf-8")
    return ef


def test_cli_issue_member_card_dms_by_default(monkeypatch, tmp_path):
    """Without --no-dm, issue-member-card attempts Slack delivery via the
    group's own token, resolving the member's Slack account from the email
    they carried in their enrollment request."""
    from murmurent.cli import cli
    from murmurent.core import group_reconcile as GR
    ef = _issue_member_card_setup(monkeypatch, tmp_path)
    seen = {}
    def fake_send_group_dm(group, *, text, slack_user_id="", email="", slack="", token=None,
                           file_content=None, file_name="bundle.json"):
        seen.update(group=group, slack_user_id=slack_user_id, email=email)
        return True, "sent"
    monkeypatch.setattr(GR, "send_group_dm", fake_send_group_dm)
    res = CliRunner().invoke(cli, ["issue-member-card", str(ef), "--group", "lab_mh"])
    assert res.exit_code == 0, res.output
    assert "DM'd @allie their card on Slack" in res.output
    assert seen == {"group": "lab_mh", "slack_user_id": "", "email": "allie@x.edu"}


def test_cli_issue_member_card_dm_failure_falls_back_to_manual(monkeypatch, tmp_path):
    from murmurent.cli import cli
    from murmurent.core import group_reconcile as GR
    ef = _issue_member_card_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(GR, "send_group_dm",
                        lambda *a, **kw: (False, "no Slack token for 'lab_mh' — run "
                                                   "`murmurent group-slack-setup lab_mh` first"))
    res = CliRunner().invoke(cli, ["issue-member-card", str(ef), "--group", "lab_mh"])
    assert res.exit_code == 0, res.output
    assert "could not DM on Slack" in res.output
    assert "send them this bundle yourself" in res.output
    assert "import-card" in res.output


def test_cli_issue_member_card_explicit_dm_target_overrides_email(monkeypatch, tmp_path):
    from murmurent.cli import cli
    from murmurent.core import group_reconcile as GR
    ef = _issue_member_card_setup(monkeypatch, tmp_path)
    seen = {}
    def fake_send_group_dm(group, *, text, slack_user_id="", email="", slack="", token=None,
                           file_content=None, file_name="bundle.json"):
        seen.update(slack_user_id=slack_user_id)
        return True, "sent"
    monkeypatch.setattr(GR, "send_group_dm", fake_send_group_dm)
    res = CliRunner().invoke(cli, ["issue-member-card", str(ef), "--group", "lab_mh",
                                   "--dm", "U999"])
    assert res.exit_code == 0, res.output
    assert seen["slack_user_id"] == "U999"


def test_issuance_writes_the_roster(monkeypatch, tmp_path):
    """pi-init + issue-member-card make the roster (members/*.md) the single source
    of truth: PI + member land there with email, github, and card fingerprint/id;
    revoke_member reads the fingerprint back from the roster."""
    import yaml as _yaml
    from murmurent.core import centre_root as CR
    from murmurent.core import membership as M
    from murmurent.core import repo as R
    from murmurent.core import revocation as REV

    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.delenv("MURMURENT_LAB_MGMT_REPO", raising=False)   # use the pinned pointer
    K.generate_keypair()
    (tmp_path / "pi").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pi" / "profile.yaml").write_text(
        _yaml.safe_dump({"email": "pi@x.edu", "github": "pigh"}), encoding="utf-8")

    out = ISS.self_issue_pi_card("@yxia266", "lab_mh")
    lab_repo = R.lab_repo_path("lab_mh")
    assert (lab_repo / "members").is_dir()
    assert (lab_repo / ".git").exists()                         # version-controlled
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


def test_project_scoped_card_issue_and_revoke(monkeypatch, tmp_path):
    """A standalone PI issues a PROJECT-scoped card (group == '<lab>/<project>')
    that chains member → PI → the PI's own root, and can revoke the whole project
    with their own key (no centre root needed)."""
    import yaml as _yaml
    from murmurent.core import cert_projects as CP
    from murmurent.core import revocation as REV

    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    monkeypatch.delenv("MURMURENT_LAB_MGMT_REPO", raising=False)
    K.generate_keypair()
    (tmp_path / "pi").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pi" / "profile.yaml").write_text(
        _yaml.safe_dump({"email": "pi@x.edu", "github": "pigh"}), encoding="utf-8")
    out = ISS.self_issue_pi_card("@yxia266", "lab_mh")
    realm, root = out["realm"], out["trust_root"]

    # member enrolls into the project; PI issues a project-scoped card
    allie = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request("@allie", priv=allie, nonce="p1",
                                    group="rna_atlas")
    bundle = ISS.issue_project_card("@allie", enrollment=req, project="rna_atlas")
    assert bundle["group"] == "lab_mh/rna_atlas"
    card, pi_card = bundle["member_card"], bundle["pi_card"]
    assert card["payload"]["group"] == "lab_mh/rna_atlas"
    assert card["payload"]["roles"][0]["kind"] == "project_member"

    # chains member -> PI -> the PI's own root, and reports the composite group
    v = C.verify_member_card(card, pi_card, root_pub=root, centre=realm,
                             require_crl=False)
    assert v.ok and v.group == "lab_mh/rna_atlas"

    # the per-project ledger indexes the member; project_context agrees on the key
    assert "allie" in REV.project_ledger(realm, "lab_mh/rna_atlas")
    assert ISS.project_context("rna_atlas") == (realm, "lab_mh/rna_atlas")

    # the cert-project registry mirrors the issued card
    reg = CP.get("rna_atlas")
    assert reg is not None and reg.lab == "lab_mh" and reg.status == "active"
    assert "@allie" in reg.members
    assert reg.certs[0]["fingerprint"] == card["payload"]["subject"]["fingerprint"]
    assert CP.projects_for_member("allie") and not CP.projects_for_member("ghost")

    # PI deletes the project with their OWN key (no centre root key present):
    # revokes every card AND archives the registry entry
    assert not REV._cr.have_root_key()
    res = ISS.delete_project("rna_atlas")
    assert res["revoked"] == 1
    assert card["payload"]["card_id"] in res["crl"]["payload"]["revoked"]
    assert CP.get("rna_atlas").status == "archived"
    assert not CP.projects_for_member("allie")     # archived → not in the member lens
    # the CRL verifies against the PI's pinned root, and the card now reads revoked
    v2 = C.verify_member_card(card, pi_card, root_pub=root, centre=realm,
                              crl=REV.current_crl(realm), require_crl=True)
    assert not v2.ok and v2.reason == "revoked"


def test_standalone_pi_requires_a_group_name(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "li"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / home))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / (home + "_li")))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "allie_li"))
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie2"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "allie2_li"))
    with pytest.raises(ISS.IssuanceError, match="rejected"):
        ISS.verify_and_import_member_card(bad_bundle, trust_root=ctx["root_pub"])


def test_cli_member_card_round_trip(mayor_world, monkeypatch, tmp_path):
    from murmurent.cli import cli
    ctx = _carded_pi(mayor_world, monkeypatch, tmp_path)  # env at the PI machine
    runner = CliRunner()
    _priv, m_req = _member_enrollment()
    enroll_f = tmp_path / "m_enroll.json"
    enroll_f.write_text(json.dumps(m_req), encoding="utf-8")
    bundle_f = tmp_path / "bundle.json"
    r = runner.invoke(cli, ["issue-member-card", str(enroll_f), "--group", "yxia_lab",
                            "--out", str(bundle_f), "--no-dm"])
    assert r.exit_code == 0, r.output
    # member machine imports it
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_cli"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "allie_cli_li"))
    r2 = runner.invoke(cli, ["import-card", str(bundle_f), "--trust-root", ctx["root_pub"]])
    assert r2.exit_code == 0, r2.output
    assert "verified" in r2.output and "member" in r2.output
    assert R.lab_mgmt_path_for_handle("allie")[0] == "yxia_lab"


def test_cli_issue_and_import_round_trip(mayor_world, monkeypatch, tmp_path):
    from murmurent.cli import cli
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
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    res2 = runner.invoke(cli, ["import-card", str(card_f), "--trust-root",
                               mayor_world["root_pub"]])
    assert res2.exit_code == 0, res2.output
    assert "verified" in res2.output
    assert R.lab_mgmt_path_for_handle("yxia266")[0] == "yxia_lab"


# ---- lead-delegated project cards (root → PI → lead → member) ----------------

def _standalone_pi(monkeypatch, tmp_path, *, home="pi_home"):
    """Standalone PI machine with a lab + one carded member (@allie).

    Returns (trust_root, allie_priv). @allie's pubkey lands on the roster at
    member-card issuance, which is what one-click project issuance reads."""
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / home))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / f"{home}_li"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "shared_lab_mgmt"))
    K.generate_keypair()
    out = ISS.self_issue_pi_card("@yxia266", "xia_lab")
    allie = Ed25519PrivateKey.generate()
    m_req = C.make_enrollment_request("@allie", priv=allie, nonce="a1",
                                      group="xia_lab", email="allie@x.edu")
    ISS.issue_member_card("@allie", enrollment=m_req, group="xia_lab")
    return out["trust_root"], allie


def test_member_card_issuance_records_pubkey_on_roster(monkeypatch, tmp_path):
    from murmurent.core import membership as MEM
    _trust, allie = _standalone_pi(monkeypatch, tmp_path)
    rec = MEM.get("allie")
    assert rec.pubkey == K.encode_public(allie.public_key())


def test_pi_self_delegates_and_issues_one_click(monkeypatch, tmp_path):
    """PI == lead: self-delegation stores the lead bundle locally; a project
    card for a roster-keyed member is one click, no fresh PoP."""
    trust, allie = _standalone_pi(monkeypatch, tmp_path)
    lead = ISS.issue_project_lead_card("@yxia266", project="dcis_17")
    assert lead["lead_card"]["payload"]["kind"] == "project_lead"
    assert lead["group"] == "xia_lab/dcis_17"

    bundle = ISS.issue_project_card_from_roster("@allie", project="dcis_17")
    assert bundle["project_card"]["payload"]["group"] == "xia_lab/dcis_17"
    # registry mirrors both: allie certified, yxia266 is lead + certified
    from murmurent.core import cert_projects as CP
    cp = CP.get("dcis_17")
    assert cp is not None and cp.lead == "@yxia266"
    assert {m.lstrip("@") for m in cp.members} == {"yxia266", "allie"}

    # member side: import + prove membership; lab member bundle untouched
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    v, _actions = ISS.verify_and_import_project_card(bundle, trust_root=trust)
    assert v.ok and v.handle == "@allie" and v.group == "xia_lab/dcis_17"
    pv = ISS.verify_project_membership("dcis_17")
    assert pv.ok and pv.handle == "@allie"
    member_bundles = list(ISS.cards_dir().glob("*_member.json"))
    assert member_bundles == []          # project import never clobbers the lab card


def test_from_roster_raises_no_recorded_key(monkeypatch, tmp_path):
    _trust, _allie = _standalone_pi(monkeypatch, tmp_path)
    ISS.issue_project_lead_card("@yxia266", project="dcis_17")
    with pytest.raises(ISS.NoRecordedKey):
        ISS.issue_project_card_from_roster("@bob", project="dcis_17")


def test_pop_fallback_records_pubkey_for_next_time(monkeypatch, tmp_path):
    _trust, _allie = _standalone_pi(monkeypatch, tmp_path)
    ISS.issue_project_lead_card("@yxia266", project="dcis_17")
    bob = Ed25519PrivateKey.generate()
    req = C.make_enrollment_request("@bob", priv=bob, nonce="b1",
                                    email="bob@x.edu", slack="bobslack")
    out = ISS.issue_project_card_pop("@bob", enrollment=req, project="dcis_17")
    assert out["project_card"]["payload"]["subject"]["handle"] == "@bob"
    # roster now has bob's key → the NEXT project add is one-click
    from murmurent.core import membership as MEM
    assert MEM.get("bob").pubkey == K.encode_public(bob.public_key())
    ISS.issue_project_lead_card("@yxia266", project="proj_two")
    assert ISS.issue_project_card_from_roster("@bob", project="proj_two")["project_card"]


# ---- legacy PI==lead self-heal (issue #19) ----------------------------------

def _legacy_pi_lead_project(monkeypatch, tmp_path, project="dcis_17"):
    """A project as a PRE-lead-card-machinery project would look on the PI's
    machine: a registry record with the PI as lead + members, but NO lead
    bundle on disk (creation never wrote one)."""
    trust, allie = _standalone_pi(monkeypatch, tmp_path)
    from murmurent.core import cert_projects as CP
    CP.upsert(project, lab="xia_lab", lead="@yxia266", member="@yxia266")
    CP.upsert(project, lab="xia_lab", member="@allie")
    assert not list(ISS.cards_dir().glob("*_lead_*.json"))   # the legacy gap
    return trust, allie


def test_add_member_self_heals_missing_lead_bundle(monkeypatch, tmp_path):
    """Issue #19: adding a member to a legacy PI==lead project no longer fails
    with 'no lead card' — the PI's self-delegation is reconstructed on the fly
    and the one-click issue then succeeds."""
    _legacy_pi_lead_project(monkeypatch, tmp_path)
    bundle = ISS.issue_project_card_from_roster("@allie", project="dcis_17")
    assert bundle["project_card"]["payload"]["group"] == "xia_lab/dcis_17"
    # the reconstructed self-delegation is now on disk (future adds skip the heal)
    assert list(ISS.cards_dir().glob("*_lead_*.json"))


def test_repair_project_lead_is_idempotent(monkeypatch, tmp_path):
    """The explicit repair reconstructs once, then reports already-present."""
    _legacy_pi_lead_project(monkeypatch, tmp_path)
    first = ISS.repair_project_lead("dcis_17")
    assert first["repaired"] is True and first["group"] == "xia_lab/dcis_17"
    second = ISS.repair_project_lead("dcis_17")
    assert second["repaired"] is False and second["already_present"] is True


def test_self_heal_refuses_when_lead_is_someone_else(monkeypatch, tmp_path):
    """A project delegated to a DIFFERENT lead is NOT silently re-delegated to
    the PI — the original 'import your lead bundle' error stands."""
    _standalone_pi(monkeypatch, tmp_path)
    from murmurent.core import cert_projects as CP
    CP.upsert("dcis_17", lab="xia_lab", lead="@allie", member="@allie")
    with pytest.raises(ISS.IssuanceError, match="no lead card|import your lead bundle"):
        ISS.issue_project_card_from_roster("@allie", project="dcis_17")
    with pytest.raises(ISS.IssuanceError, match="cannot repair"):
        ISS.repair_project_lead("dcis_17")


def test_repair_project_lead_refuses_on_non_pi_machine(monkeypatch, tmp_path):
    """A machine that leads no lab cannot self-heal — it must import the bundle."""
    _standalone_pi(monkeypatch, tmp_path)
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "stranger_home"))
    K.generate_keypair()
    with pytest.raises(ISS.IssuanceError, match="cannot repair"):
        ISS.repair_project_lead("dcis_17")


def test_member_delegated_lead_issues_from_their_machine(monkeypatch, tmp_path):
    """creator == member: the PI delegates to @allie; on HER machine (her key,
    the shared roster) she signs @bob's project card herself."""
    trust, _ = _standalone_pi(monkeypatch, tmp_path)
    # allie's real key lives on HER machine — pin her machine key as the lead key
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    K.generate_keypair()
    allie_pub = K.encode_public(K.load_public())
    # back on the PI machine: delegate the project to allie's machine key
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    lead_bundle = ISS.issue_project_lead_card("@allie", project="dcis_17",
                                              pubkey=allie_pub)
    assert lead_bundle["lead_card"]["payload"]["subject"]["pubkey"] == allie_pub
    # no lead bundle materializes on the PI machine (allie ≠ PI)
    assert not list(ISS.cards_dir().glob("*_lead_*.json"))

    # bob gets carded on the PI machine so his pubkey is on the shared roster
    bob = Ed25519PrivateKey.generate()
    ISS.issue_member_card("@bob", enrollment=C.make_enrollment_request(
        "@bob", priv=bob, nonce="b1", group="xia_lab"), group="xia_lab")

    # allie's machine: import the DM'd lead bundle, then one-click bob
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    v, _actions = ISS.verify_and_import_project_card(
        {"lead_card": lead_bundle["lead_card"], "pi_card": lead_bundle["pi_card"]},
        trust_root=trust)
    assert v.ok and v.kind == "project_lead"
    out = ISS.issue_project_card_from_roster("@bob", project="dcis_17")
    assert out["project_card"]["payload"]["issuer"]["handle"] == "@allie"
    # a valid lead card also proves allie's own membership
    assert ISS.verify_project_membership("dcis_17").ok


def test_non_lead_machine_cannot_sign_project_cards(monkeypatch, tmp_path):
    """The crypto gate: a machine whose key ≠ the delegated lead key refuses."""
    trust, _ = _standalone_pi(monkeypatch, tmp_path)
    stranger = Ed25519PrivateKey.generate()
    lead_bundle = ISS.issue_project_lead_card(
        "@allie", project="dcis_17",
        pubkey=K.encode_public(stranger.public_key()))
    # mallory's machine imports the (public) lead bundle but holds her own key
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mallory_home"))
    K.generate_keypair()
    ISS.verify_and_import_project_card(
        {"lead_card": lead_bundle["lead_card"], "pi_card": lead_bundle["pi_card"]},
        trust_root=trust)
    with pytest.raises(ISS.IssuanceError, match="does not match"):
        ISS.issue_project_card_from_roster("@allie", project="dcis_17")


def test_delete_project_with_zero_certs(monkeypatch, tmp_path):
    """A project registered but never certified is still deletable; the report
    is written and the registry archives."""
    _standalone_pi(monkeypatch, tmp_path)
    from murmurent.core import cert_projects as CP
    CP.upsert("empty_proj", lab="xia_lab")
    out = ISS.delete_project("empty_proj", by_handle="@yxia266")
    assert out["revoked"] == 0 and out["crl"] is None
    assert out["report"] and "empty_proj" in out["report"]
    assert CP.get("empty_proj").status == "archived"


def test_delete_project_revokes_lead_and_members(monkeypatch, tmp_path):
    """Full delete: lead + member cards all land on the CRL in one bump, and
    the member's stored proof then FAILS verification."""
    trust, _allie = _standalone_pi(monkeypatch, tmp_path)
    ISS.issue_project_lead_card("@yxia266", project="dcis_17")
    bundle = ISS.issue_project_card_from_roster("@allie", project="dcis_17")

    # allie imports her proof (verifies now)…
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    ISS.verify_and_import_project_card(bundle, trust_root=trust)
    assert ISS.verify_project_membership("dcis_17").ok

    # …PI deletes the project…
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    out = ISS.delete_project("dcis_17", by_handle="@yxia266")
    assert out["revoked"] == 2            # lead card + allie's project card

    # …and allie's proof dies once she holds the distributed CRL.
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "allie_home"))
    from murmurent.core import revocation as REV
    realm = out["crl"]["payload"]["centre"]        # the PI's self-realm
    REV.import_distributed_crl(realm, out["crl"])
    pv = ISS.verify_project_membership("dcis_17")
    assert not pv.ok and "revoked" in pv.reason


# ---- group resolution on member cards (issue #16) ---------------------------

def _solo_core_pi(monkeypatch, tmp_path, handle="@emucaki", group="bioinformatics"):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "pi_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "pi_li"))
    K.generate_keypair()
    ISS.self_issue_pi_card(handle, group)


def _member_req(handle, nonce, group="bioinformatics"):
    priv = Ed25519PrivateKey.generate()
    return C.make_enrollment_request(handle, priv=priv, nonce=nonce, group=group)


def test_issue_member_card_blank_group_uses_the_led_group(monkeypatch, tmp_path):
    """Issue #16: the dashboard sends no group — issuance resolves it from
    the PI's own card (they lead exactly one group), instead of the old
    endpoint fallback that guessed a display name."""
    _solo_core_pi(monkeypatch, tmp_path)
    bundle = ISS.issue_member_card("@hagaremam", enrollment=_member_req("@hagaremam", "n1"),
                                   group=None)
    assert bundle["member_card"]["payload"]["group"] == "bioinformatics"


def test_issue_member_card_group_match_is_case_insensitive(monkeypatch, tmp_path):
    _solo_core_pi(monkeypatch, tmp_path)
    bundle = ISS.issue_member_card("@tim", enrollment=_member_req("@tim", "n2"),
                                   group="Bioinformatics")
    assert bundle["member_card"]["payload"]["group"] == "bioinformatics"


def test_issue_member_card_wrong_group_names_the_led_groups(monkeypatch, tmp_path):
    """The refusal now says what the card DOES authorise, so a PI staring
    at "you do not lead group 'Bioinformatics Lab'" can self-correct."""
    _solo_core_pi(monkeypatch, tmp_path)
    with pytest.raises(ISS.IssuanceError, match="you lead: bioinformatics"):
        ISS.issue_member_card("@zed", enrollment=_member_req("@zed", "n3"),
                              group="Bioinformatics Lab")
