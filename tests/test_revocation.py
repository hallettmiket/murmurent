"""
Tests for core/revocation.py (the centre CRL + issuance ledger), issuance's
verify_local_identity, and the dashboard gate refusing a revoked/expired card.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from murmurent.core import centre_root as CR
from murmurent.core import idcert as C
from murmurent.core import idkeys as K
from murmurent.core import identity_card as IC
from murmurent.core import issuance as ISS
from murmurent.core import revocation as REV


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wig"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "li"))


# ---- ledger + revoke core ---------------------------------------------------

def test_record_and_lookup_issued():
    REV.record_issued("qa", handle="@allie", card_id="c1",
                      fingerprint="SHA256:x", kind="member")
    rec = REV.lookup_issued("qa", "allie")
    assert rec["card_id"] == "c1" and rec["fingerprint"] == "SHA256:x"


def test_revoke_requires_root_key():
    with pytest.raises(REV.RevocationError, match="root key"):
        REV.revoke("qa", card_id="c1")


def test_revoke_bumps_serial_and_is_root_signed():
    CR.generate_root_key()
    crl1 = REV.revoke("qa", card_id="c1")
    assert crl1["payload"]["serial"] == 1 and "c1" in crl1["payload"]["revoked"]
    assert K.verify(crl1["payload"], crl1["signature"], CR.root_public())
    crl2 = REV.revoke("qa", fingerprint="SHA256:z")
    assert crl2["payload"]["serial"] == 2
    assert {"c1", "SHA256:z"} <= set(crl2["payload"]["revoked"])


def test_revoke_member_via_ledger():
    CR.generate_root_key()
    REV.record_issued("qa", handle="@allie", card_id="cA",
                      fingerprint="SHA256:fa", kind="member")
    crl = REV.revoke_member("qa", "allie")
    assert {"cA", "SHA256:fa"} <= set(crl["payload"]["revoked"])


def test_revoke_member_unknown_handle():
    CR.generate_root_key()
    with pytest.raises(REV.RevocationError, match="no issued card"):
        REV.revoke_member("qa", "ghost")


def test_current_crl_fresh_on_root_machine_none_without():
    assert REV.current_crl("qa") is None       # no root, nothing stored
    CR.generate_root_key()
    crl = REV.current_crl("qa")
    assert crl is not None
    assert K.verify(crl["payload"], crl["signature"], CR.root_public())


def test_revoked_card_fails_verification():
    CR.generate_root_key()
    root = CR.load_root_private()
    pi = Ed25519PrivateKey.generate()
    card = C.issue_pi_card(handle="@yxia266", pi_pubkey=pi.public_key(),
                           centre="qa", root_priv=root)
    REV.revoke("qa", card_id=card["payload"]["card_id"])
    v = C.verify_pi_card(card, root_pub=CR.root_public(), crl=REV.current_crl("qa"),
                         centre="qa")
    assert not v.ok and v.reason == "revoked"


# ---- verify_local_identity + dashboard --------------------------------------

def _card_machine(monkeypatch, tmp_path, *, issued_at=None, ttl_days=90, home="m"):
    """A machine holding the root key, a pinned anchor, and a stored PI card."""
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / home))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / (home + "_li")))
    CR.generate_root_key()
    root = CR.load_root_private()
    C.pin_root("qa", CR.root_public())
    pi = Ed25519PrivateKey.generate()
    card = C.issue_pi_card(handle="@yxia266", pi_pubkey=pi.public_key(),
                           centre="qa", root_priv=root, issued_at=issued_at,
                           ttl_days=ttl_days)
    IC.import_card({"version": IC.CARD_VERSION, "netname": "yxia266", "centre": "qa",
                    "roles": [{"kind": "lab_pi", "group": "yxia_lab", "pi": "@yxia266"}],
                    "issued_by": "@tbrowne5", "issued_at": card["payload"]["issued_at"]})
    ISS.cards_dir().mkdir(parents=True, exist_ok=True)
    (ISS.cards_dir() / "qa_pi.json").write_text(C.dumps(card), encoding="utf-8")
    return card


def test_verify_local_identity_ok_then_revoked(monkeypatch, tmp_path):
    card = _card_machine(monkeypatch, tmp_path)
    assert ISS.verify_local_identity()[0] == "ok"
    REV.revoke("qa", card_id=card["payload"]["card_id"])
    status, reason = ISS.verify_local_identity()
    assert status == "reject" and reason == "revoked"


def test_verify_local_identity_no_card(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "empty"))
    assert ISS.verify_local_identity()[0] == "no_card"


def test_verify_local_identity_expired(monkeypatch, tmp_path):
    _card_machine(monkeypatch, tmp_path,
                  issued_at=datetime(2020, 1, 1, tzinfo=timezone.utc), ttl_days=1)
    status, reason = ISS.verify_local_identity()
    assert status == "reject" and reason == "expired"


def test_dashboard_refuses_revoked_card(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    card = _card_machine(monkeypatch, tmp_path)
    REV.revoke("qa", card_id=card["payload"]["card_id"])
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=yxia266")
    assert res.status_code == 403
    assert "failed verification" in res.json()["detail"]
