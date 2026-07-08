"""
Purpose: MEMBER-side trust bootstrap from the public ``wigamig_public`` hub
(phase 6). Reads a centre's machine-readable, self-signed entry (age + signing
pubkeys) and its signed CRL from a local hub checkout, verifies the
self-signature, and pins the signing key locally so this machine can verify
identity cards and enforce revocation.

Trust note: the self-signature only proves the entry is internally consistent —
an attacker who controls the hub could publish a *different* key and re-sign it.
The real anchor is the **fingerprint confirmed out-of-band** (``expect_fingerprint``);
without it this is trust-on-first-use. Once pinned, a later mismatch fails closed
(``idcert.verify_or_pin_root``).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import centre_root as _cr
from . import hub_publish as _hp
from . import idcert as _cert
from . import idkeys as _k
from . import revocation as _rev


class HubFetchError(RuntimeError):
    """A centre entry / CRL could not be read or verified from the hub."""


def read_centre_entry(hub_dir, unique_name: str) -> dict:
    """Read + self-verify the published centre entry (age + signing pubkeys)."""
    p = _hp.centre_entry_path(Path(hub_dir), unique_name)
    if not p.is_file():
        raise HubFetchError(f"no published entry for '{unique_name}' at {p}")
    try:
        entry = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HubFetchError(f"malformed centre entry: {exc}") from exc
    if not _cr.verify_installation_entry(entry):
        raise HubFetchError(
            "published centre entry failed self-signature verification "
            "(tampered, or not signed by the key it advertises)")
    return entry


def read_centre_crl(hub_dir, unique_name: str) -> dict | None:
    p = _hp.crl_path(Path(hub_dir), unique_name)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HubFetchError(f"malformed CRL: {exc}") from exc


def pin_from_hub(unique_name: str, *, hub_dir=None,
                 expect_fingerprint: str | None = None) -> dict:
    """Fetch a centre's trust material from the hub, pin its signing key (TOFU,
    fail-closed on mismatch), and import its CRL. Returns a summary dict.

    Pass ``expect_fingerprint`` (confirmed out-of-band) to reject a substituted
    key on first pin — without it, the first key seen is trusted."""
    hub_dir = Path(hub_dir) if hub_dir else _hp.default_hub_dir()
    entry = read_centre_entry(hub_dir, unique_name)
    signing = entry["payload"].get("signing_pubkey")
    if not signing:
        raise HubFetchError("centre entry has no signing key")
    fpr = _k.fingerprint(signing)
    if expect_fingerprint and fpr != expect_fingerprint.strip():
        raise HubFetchError(
            f"fingerprint mismatch — the hub advertises {fpr} but you expected "
            f"{expect_fingerprint.strip()}. Refusing to pin (possible tampering).")
    ok, reason = _cert.verify_or_pin_root(unique_name, signing)
    if not ok:
        raise HubFetchError(f"trust anchor: {reason}")
    crl = read_centre_crl(hub_dir, unique_name)
    if crl is not None:
        _rev.import_distributed_crl(unique_name, crl)
    return {
        "fingerprint": fpr,
        "pinned": reason,
        "age_pubkey": entry["payload"].get("age_pubkey", ""),
        "crl_imported": crl is not None,
        "crl_serial": (crl or {}).get("payload", {}).get("serial"),
    }


__all__ = ["HubFetchError", "read_centre_entry", "read_centre_crl", "pin_from_hub"]
