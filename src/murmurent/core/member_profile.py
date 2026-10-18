"""
Purpose: the member-owned profile staging store (``~/.murmurent/profile.yaml``).

A member's roster record (``<lab-mgmt>/members/<handle>.md``) is READ-ONLY to
them by design: the PI/leader is the only writer, so a member's
``git pull --ff-only`` on the roster clone can never conflict
(``group_reconcile.grant_lab_mgmt_read``). That invariant is what makes a
member commit to the roster clone harmful — the push always 403s and the local
commit diverges the clone, which then breaks the next pull (#34).

So a non-PI profile edit made in the dashboard is STAGED here, in the member's
OWN ``profile.yaml``, under a ``roster_profile:`` block whose shape mirrors the
roster frontmatter (``contact``/``location`` blocks, top-level
``official_handle``/``slack``, and ``git_logins``). The same block is also
written to the member's personal vault (``<vault>/profile/roster_profile.yaml``),
which travels to their other machines (#187). Consumers:

  * the member's own dashboard overlays it so their edit is visible immediately,
    on every machine that has their vault (``dashboard.snapshot``), and
  * the PI's ``murmurent reconcile`` applies it to ``members/<handle>.md``,
    carried there as an issue on the lab management repo
    (``core.profile_relay``; #34 Option A, built in #187).

A cleared field is kept as an empty string, not dropped, so the overlay can
show it cleared instead of falling back to the roster's old value.

``profile.yaml``'s original flat keys (``handle``/``role``/``name``/``email``/
``github``/``slack``, written by ``murmurent init``) are left untouched; the
staged edits live entirely under the ``roster_profile`` key.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

STAGE_KEY = "roster_profile"

# Fields the dashboard profile form owns, in the roster's own frontmatter shape.
CONTACT_KEYS = ("email", "orcid", "bluesky", "github", "osf", "website")
LOCATION_KEYS = ("office", "dry_lab", "wet_labs", "address", "city", "department")


def _home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME", str(Path.home() / ".murmurent")))


def profile_path() -> Path:
    """This machine owner's ``~/.murmurent/profile.yaml`` (from ``murmurent init``)."""
    return _home() / "profile.yaml"


def _normalize(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


def read_profile() -> dict:
    """The whole ``profile.yaml`` as a dict, or ``{}`` when absent/unreadable."""
    p = profile_path()
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


VAULT_PROFILE = Path("profile") / "roster_profile.yaml"


def vault_profile_path() -> Path | None:
    """``<vault>/profile/roster_profile.yaml``, or None without a personal vault."""
    try:
        from .vault_sync import personal_vault_root
        root = personal_vault_root()
    except Exception:  # noqa: BLE001
        return None
    return (root / VAULT_PROFILE) if root is not None else None


def _read_vault_block() -> dict:
    path = vault_profile_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def staged_roster_profile(handle: str) -> dict:
    """The staged ``roster_profile`` block IF it belongs to ``handle``, else ``{}``.

    The vault copy wins, since it is the one that travels between the member's
    machines; ``profile.yaml`` is the fallback on a machine without a vault.
    Guarded by handle so a machine that changed hands (or a ``?user=`` query for
    someone who is not the machine owner) never reads back the wrong person's
    staged edits. Returns a copy without the internal ``handle`` marker.
    """
    block = _read_vault_block()
    if _normalize(str(block.get("handle") or "")) != _normalize(handle):
        block = read_profile().get(STAGE_KEY)
    if not isinstance(block, dict):
        return {}
    if _normalize(str(block.get("handle") or "")) != _normalize(handle):
        return {}
    out = {k: v for k, v in block.items() if k != "handle"}
    return out


def stage_roster_profile(handle: str, edits: dict) -> Path:
    """Merge ``edits`` into ``profile.yaml``'s ``roster_profile`` block.

    ``edits`` carries only the fields the member actually changed, in roster
    shape: ``{"contact": {...}, "location": {...}, "official_handle": str,
    "slack": str, "git_logins": {...}}``. Any key may be absent (untouched).
    Per-field semantics mirror the roster writer: a value of ``None`` or an
    empty/whitespace string CLEARS that field (kept as ``""`` so the clear is
    seen); a real value sets it.

    The block is tagged with ``handle`` so :func:`staged_roster_profile` can
    refuse to serve it to anyone else. Written to ``profile.yaml`` and, when
    there is one, to the personal vault. Returns the vault path when written
    there, else the ``profile.yaml`` path.
    """
    prof = read_profile()
    existing = staged_roster_profile(handle) or prof.get(STAGE_KEY)
    block: dict = dict(existing) if isinstance(existing, dict) else {}
    block["handle"] = "@" + _normalize(handle)

    def _empty(v) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    def _merge_map(name: str, incoming: dict) -> None:
        cur = block.get(name)
        merged = dict(cur) if isinstance(cur, dict) else {}
        for k, v in incoming.items():
            merged[k] = "" if _empty(v) else (v.strip() if isinstance(v, str) else v)
        if merged:
            block[name] = merged
        else:
            block.pop(name, None)

    if isinstance(edits.get("contact"), dict):
        _merge_map("contact", edits["contact"])
    if isinstance(edits.get("location"), dict):
        _merge_map("location", edits["location"])
    if isinstance(edits.get("git_logins"), dict):
        _merge_map("git_logins", edits["git_logins"])
    for top in ("official_handle", "slack"):
        if top in edits:
            v = edits[top]
            block[top] = "" if _empty(v) else (v.strip().lstrip("@") if isinstance(v, str) else v)

    prof[STAGE_KEY] = block
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")
    vault = vault_profile_path()
    if vault is not None:
        try:
            vault.parent.mkdir(parents=True, exist_ok=True)
            vault.write_text(yaml.safe_dump(block, sort_keys=False), encoding="utf-8")
            return vault
        except OSError:
            pass
    return path


def apply_edits_to_meta(meta: dict, edits: dict) -> dict:
    """Apply profile ``edits`` (roster shape, see :func:`stage_roster_profile`)
    to a roster member file's frontmatter ``meta`` and return the new dict.

    The one place roster entries are edited from a profile: the PI's own save
    and the PI applying a member's update (``core.profile_relay``) both use it.
    ``None`` or an empty string removes a field. ``git_logins.github`` is
    mirrored into ``contact.github`` for older readers.
    """
    meta = dict(meta or {})

    def _empty(v) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    def _merge(block_name: str, fields: dict) -> None:
        existing = meta.get(block_name)
        block = dict(existing) if isinstance(existing, dict) else {}
        for k, v in fields.items():
            if _empty(v):
                block.pop(k, None)
            else:
                block[k] = v.strip() if isinstance(v, str) else v
        if block:
            meta[block_name] = block
        else:
            meta.pop(block_name, None)

    if isinstance(edits.get("contact"), dict):
        _merge("contact", {k: v for k, v in edits["contact"].items() if k in CONTACT_KEYS})
    if isinstance(edits.get("location"), dict):
        _merge("location", {k: v for k, v in edits["location"].items() if k in LOCATION_KEYS})
    for top in ("official_handle", "slack"):
        if top in edits:
            v = edits[top]
            if _empty(v):
                meta.pop(top, None)
            else:
                meta[top] = v.strip().lstrip("@") if isinstance(v, str) else v
    if isinstance(edits.get("git_logins"), dict):
        from . import git_providers as _gpr
        existing = meta.get("git_logins") if isinstance(meta.get("git_logins"), dict) else {}
        merged = dict(existing or {})
        for k, v in edits["git_logins"].items():
            if _empty(v):
                merged.pop(k, None)
            else:
                merged[str(k)] = str(v).strip().lstrip("@")
        cleaned = _gpr.dump_logins(merged)
        if cleaned:
            meta["git_logins"] = cleaned
        else:
            meta.pop("git_logins", None)
        gh = cleaned.get("github") if cleaned else None
        contact = dict(meta.get("contact") or {}) if isinstance(meta.get("contact"), dict) else {}
        if gh:
            contact["github"] = gh
        elif "github" in (existing or {}):
            contact.pop("github", None)
        if contact:
            meta["contact"] = contact
        else:
            meta.pop("contact", None)
    return meta
