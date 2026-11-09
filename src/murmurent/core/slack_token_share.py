"""
Purpose: let a certified lab member post project notes from their own machine
without the PI hand-copying the lab's Slack bot token to them.

The PI's machine holds the lab bot token
(``~/.config/murmurent/groups/<lab>/slack-token``). Every certified member's
roster entry (``members/<handle>.md`` in the lab records repository) already
carries the ed25519 public key their machine attested when their card was
issued, and the member's machine holds the private half
(``~/.murmurent/keys/id_ed25519``). So the token can be **sealed** to those
keys and committed to the records repository, which members already clone and
pull. A member's machine opens the box with its own key; nobody else can, and
nothing new has to be installed, generated or sent.

    PI:      murmurent group-slack-share <lab>    seal + commit + push
    member:  murmurent group-slack-unlock <lab>   open + store the token locally
             (``murmurent project note`` also tries this on its own when the
             machine has no token yet)

How the box is built ("envelope" encryption, the same shape ``age`` uses):

  1. a random 32-byte **file key** encrypts the token once
     (ChaCha20-Poly1305, so a tampered box is refused, never misread);
  2. for each recipient, the ed25519 key is turned into its X25519 twin
     (the standard birational map that ``age`` applies to ssh-ed25519 keys),
     an ephemeral X25519 key does a Diffie-Hellman exchange with it, and the
     result is stretched with HKDF-SHA256 into a key that wraps the file key.

A box therefore lists one slot per member. A machine opens the slot whose
fingerprint matches its key, and fails closed when none does.

Revocation means rotation. A box committed today stays openable forever, in
git history, by every key it was sealed to. When a member leaves the lab, the
PI rotates the token in Slack, runs ``group-slack-setup`` with the new one,
and shares again; the old box in history then opens to a dead token.

Author: Mike Hallett (with Claude Code)
Date: 2026-11-05
Input: the lab's token on the PI's machine; the roster's attested public keys.
Output: ``<records repo>/security/slack_bot_token.sealed.json``; on a member
        machine, the token file at the path every Slack seam already reads.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import idkeys as _k

BOX_VERSION = 1
BOX_KIND = "slack_bot_token"
#: Where the box lives inside the lab records repository.
BOX_RELPATH = Path("security") / "slack_bot_token.sealed.json"

_AAD_BODY = b"murmurent sealed slack bot token v1: body"
_AAD_SLOT = b"murmurent sealed slack bot token v1: slot"
_HKDF_INFO = b"murmurent sealed slack bot token v1"
_P = 2**255 - 19


class SealError(RuntimeError):
    """Sealing or opening a box failed; the message says why in plain words."""


# --------------------------------------------------------------------------- #
# ed25519 -> X25519
# --------------------------------------------------------------------------- #
def _x25519_private_from_ed25519(priv: Ed25519PrivateKey) -> X25519PrivateKey:
    """The X25519 private key that corresponds to an ed25519 signing key:
    the first half of SHA-512 of the seed, as RFC 8032 derives the scalar.
    The X25519 code clamps it the same way, so the public keys match."""
    seed = priv.private_bytes_raw()
    scalar = hashlib.sha512(seed).digest()[:32]
    return X25519PrivateKey.from_private_bytes(scalar)


def _x25519_public_from_ed25519(pub: Ed25519PublicKey) -> X25519PublicKey:
    """The X25519 public key of an ed25519 public key: the Montgomery
    u-coordinate ``u = (1 + y) / (1 - y) mod p`` of the Edwards point."""
    raw = pub.public_bytes_raw()
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)   # drop the sign bit of x
    denominator = (1 - y) % _P
    if denominator == 0:
        raise SealError("this ed25519 key has no X25519 twin (degenerate point)")
    u = ((1 + y) * pow(denominator, -1, _P)) % _P
    return X25519PublicKey.from_public_bytes(u.to_bytes(32, "little"))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.b64decode(str(text or ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise SealError("the box is not well formed (bad base64)") from exc


def _wrap_key(shared: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_HKDF_INFO).derive(shared)


# --------------------------------------------------------------------------- #
# Seal / open
# --------------------------------------------------------------------------- #
def seal(plaintext: str, recipients: dict[str, str], *, group: str = "",
         sealed_by: str = "", sealed_at: str | None = None) -> dict:
    """Seal ``plaintext`` so that any one of ``recipients`` (``{handle:
    "ed25519:<base64>"}``) can open it. Returns the box as a plain dict,
    ready to be written as JSON. Raises :class:`SealError` when a key is
    unreadable or there is nobody to seal to."""
    text = (plaintext or "").strip()
    if not text:
        raise SealError("nothing to seal (the token is empty)")
    if not recipients:
        raise SealError("no recipients: no active member has an attested public key")

    file_key = secrets.token_bytes(32)
    body_nonce = secrets.token_bytes(12)
    body = ChaCha20Poly1305(file_key).encrypt(body_nonce, text.encode("utf-8"), _AAD_BODY)

    slots: list[dict] = []
    for handle, pubtext in sorted(recipients.items()):
        try:
            ed_pub = _k.decode_public(pubtext)
        except Exception as exc:  # noqa: BLE001
            raise SealError(f"@{handle}: unreadable public key ({exc})") from exc
        x_pub = _x25519_public_from_ed25519(ed_pub)
        eph = X25519PrivateKey.generate()
        eph_pub = eph.public_key().public_bytes_raw()
        shared = eph.exchange(x_pub)
        wrap = _wrap_key(shared, eph_pub + x_pub.public_bytes_raw())
        slot_nonce = secrets.token_bytes(12)
        wrapped = ChaCha20Poly1305(wrap).encrypt(slot_nonce, file_key, _AAD_SLOT)
        slots.append({
            "handle": handle.lstrip("@"),
            "fingerprint": _k.fingerprint(ed_pub),
            "ephemeral": _b64(eph_pub),
            "nonce": _b64(slot_nonce),
            "wrapped": _b64(wrapped),
        })

    return {
        "version": BOX_VERSION,
        "kind": BOX_KIND,
        "group": group,
        "sealed_by": sealed_by.lstrip("@"),
        "sealed_at": sealed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nonce": _b64(body_nonce),
        "ciphertext": _b64(body),
        "recipients": slots,
    }


def open_box(box: dict, priv: Ed25519PrivateKey) -> str:
    """Open ``box`` with ``priv``. Tries the slot whose fingerprint matches
    first, then every other slot, so a box sealed before a key's fingerprint
    was recorded still opens. Raises :class:`SealError` when no slot opens:
    the key is not among the recipients, or the box was altered."""
    if not isinstance(box, dict) or box.get("kind") != BOX_KIND:
        raise SealError("not a sealed Slack bot token")
    if int(box.get("version") or 0) != BOX_VERSION:
        raise SealError(f"unknown box version {box.get('version')!r}; "
                        "update murmurent on this machine")
    slots = list(box.get("recipients") or [])
    if not slots:
        raise SealError("the box has no recipients")
    mine = _k.fingerprint(priv.public_key())
    ordered = sorted(slots, key=lambda s: 0 if s.get("fingerprint") == mine else 1)

    x_priv = _x25519_private_from_ed25519(priv)
    x_pub_raw = x_priv.public_key().public_bytes_raw()
    body_nonce = _unb64(box.get("nonce"))
    body = _unb64(box.get("ciphertext"))
    for slot in ordered:
        try:
            eph_pub_raw = _unb64(slot.get("ephemeral"))
            shared = x_priv.exchange(X25519PublicKey.from_public_bytes(eph_pub_raw))
            wrap = _wrap_key(shared, eph_pub_raw + x_pub_raw)
            file_key = ChaCha20Poly1305(wrap).decrypt(
                _unb64(slot.get("nonce")), _unb64(slot.get("wrapped")), _AAD_SLOT)
            text = ChaCha20Poly1305(file_key).decrypt(body_nonce, body, _AAD_BODY)
            return text.decode("utf-8").strip()
        except (InvalidTag, ValueError, SealError):
            continue
    raise SealError("this machine's key is not among the recipients of the box, "
                    "or the box was altered")


# --------------------------------------------------------------------------- #
# Where things are
# --------------------------------------------------------------------------- #
def records_repo(group: str, *, env: dict[str, str] | None = None) -> Path:
    """The lab records repository for ``group`` on this machine: the registry's
    ``lab_mgmt_path`` (a member's scoped registry points at their clone), else
    the conventional ``<repos>/murmurent_lab_mgmt_<group>``."""
    try:
        from . import registrar as _R
        reg = _R.read_registry(env)
        entry = next((g for g in [*reg.labs, *reg.cores] if g.name == group), None)
        if entry is not None and entry.lab_mgmt_path:
            return Path(entry.lab_mgmt_path).expanduser()
    except Exception:  # noqa: BLE001
        pass
    from . import repo as _repo
    return _repo.lab_repo_path(group)


def box_path(group: str, *, env: dict[str, str] | None = None) -> Path:
    return records_repo(group, env=env) / BOX_RELPATH


def roster_keys(group: str, *, env: dict[str, str] | None = None
                ) -> tuple[dict[str, str], list[str]]:
    """``({handle: pubkey}, [handles without a key])`` for the group's active
    members, read from ``members/*.md`` in its records repository."""
    from .frontmatter import parse_file as _pf
    from . import registrar as _R
    members_dir = records_repo(group, env=env) / "members"
    keys: dict[str, str] = {}
    missing: list[str] = []
    if not members_dir.is_dir():
        return keys, missing
    for mf in sorted(members_dir.glob("*.md")):
        try:
            meta = _pf(mf).meta or {}
        except Exception:  # noqa: BLE001
            continue
        if str(meta.get("status") or "active") != "active":
            continue
        handle = _R._normalize(str(meta.get("handle") or mf.stem))
        pub = str(meta.get("pubkey") or "").strip()
        if pub:
            keys[handle] = pub
        else:
            missing.append(handle)
    return keys, missing


def this_machine_leads(group: str, *, env: dict[str, str] | None = None) -> bool:
    """True when this machine's identity card says its owner leads ``group``."""
    try:
        from .identity_card import local_card
        card = local_card(env) or {}
    except Exception:  # noqa: BLE001
        return False
    return any(r.get("kind") in ("lab_pi", "core_leader") and r.get("group") == group
               for r in card.get("roles") or [])


# --------------------------------------------------------------------------- #
# PI side: share
# --------------------------------------------------------------------------- #
@dataclass
class ShareReport:
    group: str
    path: Path | None = None
    sealed_for: list[str] = field(default_factory=list)
    without_key: list[str] = field(default_factory=list)
    git: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def share_group_token(group: str, *, env: dict[str, str] | None = None,
                      push: bool = True, token: str | None = None,
                      sealed_by: str = "") -> ShareReport:
    """Seal the lab's bot token to every active member's attested key and
    commit the box to the records repository. Never raises."""
    rep = ShareReport(group=group)
    if token is None:
        from .group_reconcile import resolve_group_slack_token
        token = resolve_group_slack_token(group)
    if not token:
        rep.error = (f"no Slack bot token on this machine for '{group}'; run "
                     f"`murmurent group-slack-setup {group}` first")
        return rep
    keys, missing = roster_keys(group, env=env)
    rep.without_key = missing
    if not keys:
        rep.error = (f"no active member of '{group}' has an attested public key on the "
                     "roster, so there is nobody to seal the token to (a key is recorded "
                     "when a member's card is issued)")
        return rep
    if not sealed_by:
        try:
            from .project_unit import local_handle
            sealed_by = local_handle()
        except Exception:  # noqa: BLE001
            sealed_by = ""
    try:
        box = seal(token, keys, group=group, sealed_by=sealed_by)
    except SealError as exc:
        rep.error = str(exc)
        return rep
    rep.sealed_for = sorted(keys)
    target = box_path(group, env=env)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(box, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        rep.error = f"could not write {target}: {exc}"
        return rep
    rep.path = target
    try:
        from .git_persist import commit_and_push
        probes = commit_and_push(target, f"Share the Slack bot token with {len(keys)} "
                                         f"member(s) of {group} (sealed to their keys)",
                                 push=push)
        rep.git = [f"{p.name}: {p.status}: {p.detail}" for p in probes]
    except Exception as exc:  # noqa: BLE001
        rep.git = [f"git: failed: {exc}"]
    return rep


# --------------------------------------------------------------------------- #
# Member side: unlock
# --------------------------------------------------------------------------- #
@dataclass
class UnlockReport:
    group: str
    path: Path | None = None       # the token file written
    sealed_at: str = ""
    sealed_by: str = ""
    token: str = ""
    error: str = ""
    fix: str = ""                  # the exact next command, when there is one

    @property
    def ok(self) -> bool:
        return not self.error


def unlock_group_token(group: str, *, env: dict[str, str] | None = None,
                       write: bool = True) -> UnlockReport:
    """Open the box the PI shared and, by default, store the token at the path
    every Slack seam reads (``~/.config/murmurent/groups/<group>/slack-token``).
    Never raises; ``error`` and ``fix`` say what stands in the way."""
    rep = UnlockReport(group=group)
    repo = records_repo(group, env=env)
    if not repo.is_dir():
        try:
            from .repo import records_clone_hint
            hint = records_clone_hint(group)
        except Exception:  # noqa: BLE001
            hint = f"clone the lab records of '{group}' to {repo}"
        rep.error = f"the lab records of '{group}' are not on this machine ({repo})"
        rep.fix = hint
        return rep
    path = repo / BOX_RELPATH
    if not path.is_file():
        rep.error = (f"the PI has not shared the Slack bot token of '{group}' yet "
                     f"(no {BOX_RELPATH} in {repo})")
        rep.fix = (f"ask the PI to run `murmurent group-slack-share {group}`, then "
                   f"`git -C {repo} pull` and try again")
        return rep
    try:
        box = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        rep.error = f"could not read {path}: {exc}"
        return rep
    if not _k.have_keys():
        rep.error = "this machine has no identity key (~/.murmurent/keys/id_ed25519)"
        rep.fix = "run `murmurent whoami`, which mints one, then ask the PI to re-issue your card"
        return rep
    try:
        priv = _k.load_private()
        tok = open_box(box, priv)
    except (SealError, ValueError, OSError) as exc:
        rep.error = f"could not open the shared token: {exc}"
        rep.fix = (f"`git -C {repo} pull` in case the box is stale; if that does not help, "
                   f"the PI runs `murmurent group-slack-share {group}` again once your "
                   "key is on the roster (it is recorded when your card is issued)")
        return rep
    rep.token = tok
    rep.sealed_at = str(box.get("sealed_at") or "")
    rep.sealed_by = str(box.get("sealed_by") or "")
    if write:
        from .group_reconcile import write_group_slack_token
        try:
            rep.path = write_group_slack_token(group, tok)
        except (OSError, ValueError) as exc:
            rep.error = f"could not store the token: {exc}"
    return rep


def missing_token_hint(group: str, *, env: dict[str, str] | None = None) -> str:
    """The one command to run on this machine when it has no bot token for
    ``group``: the PI sets the token up; a member unlocks the shared copy."""
    g = group or "<lab>"
    if this_machine_leads(group, env=env):
        return f"run `murmurent group-slack-setup {g}` here once (the token is per machine)"
    return (f"run `murmurent group-slack-unlock {g}` here once; it opens the copy the PI "
            f"shared through the lab records, or says what is missing")


__all__ = ["SealError", "ShareReport", "UnlockReport", "BOX_RELPATH",
           "seal", "open_box", "records_repo", "box_path", "roster_keys",
           "this_machine_leads", "share_group_token", "unlock_group_token",
           "missing_token_hint"]
