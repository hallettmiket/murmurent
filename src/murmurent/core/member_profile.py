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
``official_handle``/``slack``, and ``git_logins``). Two consumers read it:

  * the member's own dashboard overlays it so their edit is visible immediately
    (``dashboard.snapshot``), and
  * a future PI-run ``murmurent reconcile`` step ingests it into
    ``members/<handle>.md`` and pushes (#34 Option A — not yet built).

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


def staged_roster_profile(handle: str) -> dict:
    """The staged ``roster_profile`` block IF it belongs to ``handle``, else ``{}``.

    Guarded by handle so a machine that changed hands (or a ``?user=`` query for
    someone who is not the machine owner) never reads back the wrong person's
    staged edits. Returns a copy without the internal ``handle`` marker.
    """
    prof = read_profile()
    block = prof.get(STAGE_KEY)
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
    empty/whitespace string CLEARS that field; a real value sets it.

    The block is tagged with ``handle`` so :func:`staged_roster_profile` can
    refuse to serve it to anyone else. Returns the written path.
    """
    prof = read_profile()
    existing = prof.get(STAGE_KEY)
    block: dict = dict(existing) if isinstance(existing, dict) else {}
    block["handle"] = "@" + _normalize(handle)

    def _empty(v) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    def _merge_map(name: str, incoming: dict) -> None:
        cur = block.get(name)
        merged = dict(cur) if isinstance(cur, dict) else {}
        for k, v in incoming.items():
            if _empty(v):
                merged.pop(k, None)
            else:
                merged[k] = v.strip() if isinstance(v, str) else v
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
            if _empty(v):
                block.pop(top, None)
            else:
                block[top] = v.strip().lstrip("@") if isinstance(v, str) else v

    prof[STAGE_KEY] = block
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")
    return path
