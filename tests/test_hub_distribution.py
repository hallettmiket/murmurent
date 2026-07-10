"""
Tests for phase 6 — publishing trust material to the hub (hub_publish) and the
member-side fetch/verify/pin (hub_fetch), including the end-to-end path where CRL
distribution makes a member's local verification enforce revocation.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from murmurent.core import centre_root as CR
from murmurent.core import hub_fetch as HF
from murmurent.core import hub_publish as HP
from murmurent.core import idcert as C
from murmurent.core import identity_card as IC
from murmurent.core import issuance as ISS
from murmurent.core import revocation as REV


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wig"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "li"))


def _publish(hub, unique="qa"):
    """Generate a root key, build the self-signed entry + CRL, write to the hub."""
    CR.generate_root_key()
    entry = CR.build_installation_entry(unique_name=unique, institution="U",
                                        name="QA", join_email="j@x.edu",
                                        age_recipient="age1abc")
    HP.write_centre_artifacts(hub, unique_name=unique, entry=entry,
                              crl=REV.current_crl(unique))
    return CR.root_public(), CR.root_fingerprint()


# ---- write + read + verify --------------------------------------------------

def test_write_and_read_entry(tmp_path):
    hub = tmp_path / "hub"
    root_pub, _ = _publish(hub)
    assert (hub / "centres" / "qa.json").is_file()
    assert (hub / "crl" / "qa.json").is_file()
    entry = HF.read_centre_entry(hub, "qa")
    assert entry["payload"]["signing_pubkey"] == root_pub
    assert entry["payload"]["age_pubkey"] == "age1abc"


def test_read_entry_tamper_rejected(tmp_path):
    hub = tmp_path / "hub"
    _publish(hub)
    p = hub / "centres" / "qa.json"
    d = json.loads(p.read_text())
    d["payload"]["unique_name"] = "evil"          # tamper breaks the self-signature
    p.write_text(json.dumps(d))
    with pytest.raises(HF.HubFetchError, match="self-signature"):
        HF.read_centre_entry(hub, "qa")


def test_read_entry_missing(tmp_path):
    with pytest.raises(HF.HubFetchError, match="no published entry"):
        HF.read_centre_entry(tmp_path / "hub", "nope")


# ---- pin --------------------------------------------------------------------

def test_pin_from_hub_pins_and_imports_crl(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    root_pub, fpr = _publish(hub)
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "member"))  # fresh member machine
    out = HF.pin_from_hub("qa", hub_dir=hub, expect_fingerprint=fpr)
    assert out["fingerprint"] == fpr and out["crl_imported"] is True
    assert C.load_pinned_root("qa") == root_pub


def test_pin_fingerprint_mismatch_fails_closed(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    _publish(hub)
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "member"))
    with pytest.raises(HF.HubFetchError, match="mismatch"):
        HF.pin_from_hub("qa", hub_dir=hub, expect_fingerprint="SHA256:wrong")
    assert C.load_pinned_root("qa") is None  # nothing pinned on refusal


# ---- end-to-end: distribution makes revocation bite on the member -----------

def test_distribution_enforces_revocation_end_to_end(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    # --- mayor: root key, a PI card, publish entry + (empty) CRL ---
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mayor"))
    CR.generate_root_key()
    root = CR.load_root_private()
    fpr = CR.root_fingerprint()
    pi = Ed25519PrivateKey.generate()
    card = C.issue_pi_card(handle="@yxia266", pi_pubkey=pi.public_key(),
                           centre="qa", root_priv=root)
    entry = CR.build_installation_entry(unique_name="qa", institution="U", name="QA")
    HP.write_centre_artifacts(hub, unique_name="qa", entry=entry,
                              crl=REV.current_crl("qa"))

    # --- member: pin from hub + hold the card → verifies OK ---
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "member"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "member_li"))
    HF.pin_from_hub("qa", hub_dir=hub, expect_fingerprint=fpr)
    IC.import_card({"version": IC.CARD_VERSION, "netname": "yxia266", "centre": "qa",
                    "roles": [{"kind": "lab_pi", "group": "xia_lab", "pi": "@yxia266"}],
                    "issued_by": "@m", "issued_at": card["payload"]["issued_at"]})
    ISS.cards_dir().mkdir(parents=True, exist_ok=True)
    (ISS.cards_dir() / "qa_pi.json").write_text(C.dumps(card))
    assert ISS.verify_local_identity()[0] == "ok"

    # --- mayor: revoke + republish the CRL ---
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mayor"))
    REV.revoke("qa", card_id=card["payload"]["card_id"])
    HP.write_centre_artifacts(hub, unique_name="qa", entry=entry,
                              crl=REV.current_crl("qa"))

    # --- member: re-pin (re-imports the updated CRL) → now REJECTED ---
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "member"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "member_li"))
    HF.pin_from_hub("qa", hub_dir=hub, expect_fingerprint=fpr)
    assert ISS.verify_local_identity() == ("reject", "revoked")


# ---- CLI --------------------------------------------------------------------

def test_cli_centre_pin(tmp_path, monkeypatch):
    from murmurent.cli import cli
    hub = tmp_path / "hub"
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mayor"))
    root_pub, fpr = _publish(hub)
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "member"))
    res = CliRunner().invoke(cli, ["centre-pin", "qa", "--hub-dir", str(hub),
                                   "--fingerprint", fpr])
    assert res.exit_code == 0, res.output
    assert "pinned centre 'qa'" in res.output
    assert C.load_pinned_root("qa") == root_pub
