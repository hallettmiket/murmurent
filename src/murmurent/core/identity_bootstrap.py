"""
Purpose: clone-first local identity. The bottom-up onboarding flow starts when a
member clones the murmurent repo — the first real ``murmurent`` command they run
mints THIS machine's ed25519 signing keypair, whose fingerprint is their unique
murmurent ID (the thing a PI later binds an identity card to).

Two entry points:
  - :func:`ensure_local_keypair` — the AUTO path, called from the CLI group
    callback. Idempotent, best-effort, and gated by ``WIGAMIG_NO_AUTOKEY`` so the
    test suite (and anyone who wants to opt out) never mints a key as a side
    effect of an unrelated command. Keys always land under ``~/.wigamig/keys``
    (never the CWD / a repo working tree) — see ``core/idkeys.py``.
  - :func:`local_identity` — read-only: who this machine is (resolved handle +
    key fingerprint + whether a card has been imported).

The explicit ``murmurent identity-init`` command calls ``idkeys.generate_keypair``
directly (not this AUTO path), so it works regardless of the opt-out flag.
"""

from __future__ import annotations

import os

from . import idkeys as K

AUTOKEY_OFF = "WIGAMIG_NO_AUTOKEY"


def ensure_local_keypair() -> str | None:
    """Mint this machine's keypair if absent (idempotent). AUTO path.

    Returns the fingerprint, or ``None`` when opted out (``WIGAMIG_NO_AUTOKEY``)
    or if generation fails — this must NEVER raise into a CLI command, so a
    transient filesystem/permission hiccup can't block unrelated work.
    """
    if os.environ.get(AUTOKEY_OFF):
        return None
    try:
        return K.generate_keypair()  # idempotent: no-op when a key exists
    except Exception:  # noqa: BLE001 — best-effort; never break the command
        return None


def local_identity(*, allow_unknown: bool = True) -> dict:
    """This machine's identity: resolved handle + key fingerprint (unique ID).

    Read-only — does not mint a key. ``fingerprint`` is ``None`` until a keypair
    exists (``murmurent identity-init`` or the first auto-run)."""
    from . import identity as _id

    ident = _id.resolve(allow_unknown=allow_unknown)
    return {
        "handle": ident.at_handle,
        "source": ident.source,
        "fingerprint": K.local_fingerprint(),
    }


__all__ = ["ensure_local_keypair", "local_identity", "AUTOKEY_OFF"]
