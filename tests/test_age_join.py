"""
Tests for the encrypted-email join flow: the join-form parser (no crypto) and,
when `age` is installed, a live keygen→encrypt→decrypt→file round-trip.
"""

from __future__ import annotations

import pytest

from wigamig.core import age_crypto as A
from wigamig.core import join_requests as JR
from wigamig.core import centre_init as CI
from wigamig.core import registrar as R


# ---- form parsing (no age needed) -------------------------------------

def test_parse_join_form_basic():
    form = (
        "# a comment\n"
        "kind: lab\n"
        "institution: western\n"
        "name: harrys_lab\n"
        "pi: @harry   # inline comment stripped\n"
        "email: harry@uwo.ca\n"
        "justification: new wet lab\n"
        "unknown_key: ignored\n"
    )
    f = JR.parse_join_form(form)
    assert f == {"kind": "lab", "institution": "western", "name": "harrys_lab",
                 "pi": "@harry", "email": "harry@uwo.ca",
                 "justification": "new wet lab"}
    assert "unknown_key" not in f


def test_parse_join_form_skips_blank_and_unfilled():
    f = JR.parse_join_form("kind:\ninstitution: western\n\nname: x\n")
    assert f == {"institution": "western", "name": "x"}  # empty `kind:` dropped


# ---- age_recipient on the centre profile ------------------------------

def test_age_recipient_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                        tmp_path / "home" / ".wigamig" / "registrar")
    CI.init_centre(name="C", institution="U", founding_mayor="@tbrowne",
                   age_recipient="age1demo...", write_sentinel=False)
    assert CI.read_centre().age_recipient == "age1demo..."


# ---- live crypto round-trip (skips if age isn't installed) -------------

@pytest.mark.skipif(not A.age_available(), reason="age not installed")
def test_live_encrypt_decrypt_and_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                        tmp_path / "home" / ".wigamig" / "registrar")
    CI.init_centre(name="C", institution="U", founding_mayor="@tbrowne",
                   write_sentinel=False)

    key = tmp_path / "mayor.key"
    recipient = A.keygen(key)
    assert recipient.startswith("age1")

    form = ("kind: lab\ninstitution: western\nname: harrys_lab\n"
            "pi: @harry\nemail: harry@uwo.ca\njustification: new lab\n")
    ciphertext = A.encrypt(recipient, form)
    assert "BEGIN AGE ENCRYPTED FILE" in ciphertext
    assert "harry" not in ciphertext          # nothing readable in the ciphertext

    plaintext = A.decrypt(ciphertext, key)
    req = JR.file_request_from_form(plaintext, source="test@x.edu")
    assert req.kind == "lab" and req.proposed_name == "harrys_lab"
    assert req.proposed_pi == "@harry" and req.requester_email == "harry@uwo.ca"
    assert req.state == "pending"
    assert JR.get_request(req.id).institution_affiliation == "western"


@pytest.mark.skipif(not A.age_available(), reason="age not installed")
def test_keygen_refuses_overwrite(tmp_path):
    key = tmp_path / "k.key"
    A.keygen(key)
    with pytest.raises(A.AgeError):
        A.keygen(key)


def test_decrypt_missing_key_is_actionable(tmp_path):
    with pytest.raises(A.AgeError):
        A.decrypt("whatever", key_path=tmp_path / "nope.key")
