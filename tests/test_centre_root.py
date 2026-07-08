"""
Tests for core/centre_root.py (the centre CA root key) + the
`centre-root-keygen` command.

Covers: root key generation/idempotency/rotation, self-signed installation entry
(tamper + pubkey-swap rejected), anchor pinning, that a root-signed PI card
verifies through the Phase-0 chain, and the CLI wiring (stamps signing_recipient,
warns to back up).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from wigamig.core import centre_init as CI
from wigamig.core import centre_root as CR
from wigamig.core import idcert as C
from wigamig.core import idkeys as K


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wig"))
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))


# ---- key lifecycle ----------------------------------------------------------

def test_generate_root_key_idempotent_and_distinct_from_machine_key():
    assert CR.have_root_key() is False
    fp = CR.generate_root_key()
    assert fp.startswith("SHA256:") and CR.have_root_key()
    assert CR.generate_root_key() == fp                       # idempotent
    # the root key is a SEPARATE file from the machine key
    assert CR.root_key_path() != K.private_key_path()
    assert not K.have_keys()  # minting a root key did not mint the machine key


def test_rotate_changes_root_fingerprint():
    fp1 = CR.generate_root_key()
    fp2 = CR.generate_root_key(overwrite=True)
    assert fp1 != fp2 and CR.root_fingerprint() == fp2


def test_root_public_and_fingerprint_none_before_keygen():
    assert CR.root_public() is None and CR.root_fingerprint() is None


# ---- bootstrap pins the anchor ---------------------------------------------

def test_bootstrap_root_pins_anchor():
    out = CR.bootstrap_root("western-qa")
    assert out["fingerprint"] == CR.root_fingerprint()
    assert C.load_pinned_root("western-qa") == CR.root_public()


# ---- self-signed installation entry ----------------------------------------

def test_installation_entry_self_signs_and_verifies():
    CR.generate_root_key()
    entry = CR.build_installation_entry(unique_name="western-qa",
                                        institution="Western", name="Western QA",
                                        join_email="join@x.edu",
                                        age_recipient="age1abc")
    assert CR.verify_installation_entry(entry)
    assert entry["payload"]["signing_pubkey"] == CR.root_public()


def test_installation_entry_tamper_rejected():
    CR.generate_root_key()
    entry = CR.build_installation_entry(unique_name="western-qa",
                                        institution="Western", name="Western QA")
    entry["payload"]["unique_name"] = "evil-centre"
    assert not CR.verify_installation_entry(entry)


def test_installation_entry_pubkey_swap_rejected():
    CR.generate_root_key()
    entry = CR.build_installation_entry(unique_name="western-qa",
                                        institution="Western", name="Western QA")
    # attacker swaps in their own pubkey but can't produce a matching signature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    entry["payload"]["signing_pubkey"] = K.encode_public(
        Ed25519PrivateKey.generate().public_key())
    assert not CR.verify_installation_entry(entry)


# ---- integration: root signs a PI card that verifies through the chain ------

def test_root_signed_pi_card_verifies():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from datetime import datetime, timezone
    CR.generate_root_key()
    root = CR.load_root_private()
    root_pub = CR.root_public()
    t0 = datetime(2026, 7, 8, tzinfo=timezone.utc)
    pi = Ed25519PrivateKey.generate()
    pi_card = C.issue_pi_card(handle="@yxia266", pi_pubkey=pi.public_key(),
                              centre="western-qa", root_priv=root, issued_at=t0)
    crl = C.build_crl(centre="western-qa", revoked=[], root_priv=root, serial=1,
                      issued_at=t0)
    v = C.verify_pi_card(pi_card, root_pub=root_pub, now=t0, crl=crl,
                         centre="western-qa")
    assert v.ok and v.handle == "@yxia266"


# ---- CLI --------------------------------------------------------------------

def _init_centre():
    CI.init_centre(name="Western QA", institution="Western",
                   founding_mayor="@tbrowne5", unique_name="western-qa",
                   write_sentinel=False)


def test_cli_centre_root_keygen_stamps_signing_recipient():
    from wigamig.cli import cli
    _init_centre()
    res = CliRunner().invoke(cli, ["centre-root-keygen"])
    assert res.exit_code == 0, res.output
    assert "root key generated" in res.output
    assert "BACK IT UP" in res.output
    prof = CI.read_centre()
    assert prof.signing_recipient == CR.root_public()
    assert prof.signing_recipient.startswith("ed25519:")


def test_cli_centre_root_keygen_idempotent():
    from wigamig.cli import cli
    _init_centre()
    runner = CliRunner()
    runner.invoke(cli, ["centre-root-keygen"])
    fp1 = CR.root_fingerprint()
    res = runner.invoke(cli, ["centre-root-keygen"])
    assert "already present" in res.output
    assert CR.root_fingerprint() == fp1


def test_cli_centre_root_keygen_requires_centre():
    from wigamig.cli import cli
    res = CliRunner().invoke(cli, ["centre-root-keygen"])
    assert res.exit_code != 0
    assert "no centre initialised" in res.output
