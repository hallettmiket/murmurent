"""
Purpose: Centre-wide registry of "common SEAs" — services / experiments /
         assays / skills / routines / MCPs / datasets that one lab built
         and is offering to every other lab in the centre to clone or use.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

A "Common SEA" is the centre-wide-scope counterpart to a per-lab SEA
(``D.sea_catalog`` — the existing lab-local SEA catalog). Per-lab SEAs
are offered to specific labs; common SEAs are advertised to everyone.

The registrar advertises these on a public list; the member dashboard
shows them inside the "SEAs we offer" panel alongside the lab's own
SEA catalog. Submission is explicit (each lab declares what it's
sharing — no auto-discovery), so the catalog stays curated.

Storage:

  <lab_info>/common_seas/<slug>.md
    ---
    slug: qc_drift_routine
    name: 'QC drift watcher'
    kind: routine               # service | skill | routine | mcp | dataset
    owner_lab: hallett
    description: 'Posts Slack on MoM QC drift > 2σ.'
    install: 'murmurent routine install qc_drift_routine'
    url: 'https://github.com/hallettmiket/qc_drift_routine'
    tags: [qc, monitoring]
    status: active              # active | deprecated
    created: '2026-05-26'
    ---

    # QC drift watcher
    Optional long-form body.

Authority:
  - Any lab's PI or registrar may submit (create).
  - Only the owner_lab's PI or a registrar may edit / archive.
  - Anyone may read (public catalog).
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .frontmatter import parse_file
from .registrar import (
    _git_commit_all, _git_init_if_needed, lab_info_root,
)


COMMON_SEAS_SUBDIR = "common_seas"
VALID_KINDS = ("service", "skill", "routine", "mcp", "dataset")
_SLUG_RE = _re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


class CommonSeaError(ValueError):
    """Common-SEA mutation failed (bad slug, missing fields, …)."""


@dataclass
class CommonSea:
    """One advertised common SEA."""

    slug: str                              # filename stem
    name: str                              # display
    kind: str                              # service | skill | routine | mcp | dataset
    owner_lab: str                         # short id of the lab that submitted it
    description: str = ""
    install: str = ""                      # copy-paste install command
    url: str = ""                          # canonical source (git URL / docs)
    tags: list[str] = field(default_factory=list)
    status: str = "active"                 # active | deprecated
    notes: str = ""                        # md body
    created: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def common_seas_dir(env: dict[str, str] | None = None) -> Path:
    """``<lab_info>/common_seas/``."""
    return lab_info_root(env) / COMMON_SEAS_SUBDIR


def sea_path(slug: str, env: dict[str, str] | None = None) -> Path:
    return common_seas_dir(env) / f"{slug}.md"


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _parse_sea(path: Path) -> CommonSea | None:
    try:
        parsed = parse_file(path)
    except Exception:
        return None
    meta = parsed.meta or {}
    slug = str(meta.get("slug") or path.stem)
    name = str(meta.get("name") or slug)
    return CommonSea(
        slug=slug, name=name,
        kind=str(meta.get("kind") or "skill").lower(),
        owner_lab=str(meta.get("owner_lab") or "").lower(),
        description=str(meta.get("description") or "").strip(),
        install=str(meta.get("install") or "").strip(),
        url=str(meta.get("url") or "").strip(),
        tags=[str(t) for t in (meta.get("tags") or [])],
        status=str(meta.get("status") or "active").lower(),
        notes=(parsed.body or "").strip(),
        created=str(meta.get("created") or ""),
        path=path,
    )


def iter_seas(
    *,
    include_deprecated: bool = False,
    kind: str | None = None,
    owner_lab: str | None = None,
    tag: str | None = None,
    env: dict[str, str] | None = None,
) -> list[CommonSea]:
    """Browse the catalog with optional filters. Filters compose."""
    cdir = common_seas_dir(env)
    if not cdir.is_dir():
        return []
    out: list[CommonSea] = []
    for entry in sorted(cdir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        s = _parse_sea(entry)
        if s is None:
            continue
        if s.status == "deprecated" and not include_deprecated:
            continue
        if kind and s.kind != kind.lower():
            continue
        if owner_lab and s.owner_lab != owner_lab.lower():
            continue
        if tag and tag.lower() not in [x.lower() for x in s.tags]:
            continue
        out.append(s)
    return out


def get_sea(
    slug: str, env: dict[str, str] | None = None,
) -> CommonSea | None:
    p = sea_path(slug, env)
    if not p.is_file():
        return None
    return _parse_sea(p)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise CommonSeaError(
            f"slug must match {_SLUG_RE.pattern} (got {slug!r}); "
            "use lowercase letters / digits / underscore; 2-64 chars."
        )
    return s


def _render(s: CommonSea) -> str:
    meta = {
        "slug": s.slug,
        "name": s.name,
        "kind": s.kind,
        "owner_lab": s.owner_lab,
        "description": s.description,
        "install": s.install,
        "url": s.url,
        "tags": list(s.tags),
        "status": s.status,
        "created": s.created,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False).rstrip()
    body = (s.notes or "").strip() or f"# {s.name}"
    return f"---\n{yaml_text}\n---\n\n{body}\n"


def create_sea(
    *,
    slug: str,
    name: str,
    kind: str,
    owner_lab: str,
    description: str = "",
    install: str = "",
    url: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    s = _validate_slug(slug)
    if not name.strip():
        raise CommonSeaError("name is required")
    k = (kind or "").strip().lower()
    if k not in VALID_KINDS:
        raise CommonSeaError(
            f"kind must be one of {VALID_KINDS} (got {kind!r})"
        )
    if not owner_lab.strip():
        raise CommonSeaError("owner_lab is required")
    p = sea_path(s, env)
    if p.is_file():
        raise CommonSeaError(f"common SEA already exists: {s}")
    now = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    sea = CommonSea(
        slug=s, name=name.strip(), kind=k,
        owner_lab=owner_lab.strip().lower(),
        description=description.strip(),
        install=install.strip(),
        url=url.strip(),
        tags=list(tags or []),
        notes=notes,
        created=now,
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render(sea), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"common_seas: +{s} ({k}, by lab {owner_lab.lower()})")
    return p


def update_sea(
    *,
    slug: str,
    patch: dict[str, Any],
    env: dict[str, str] | None = None,
) -> Path:
    s = get_sea(slug, env)
    if s is None:
        raise CommonSeaError(f"common SEA not found: {slug}")
    allowed = {"name", "kind", "description", "install", "url",
               "tags", "status", "notes"}
    for k, v in (patch or {}).items():
        if k not in allowed:
            continue
        if k == "tags":
            setattr(s, k, list(v or []))
        elif k == "kind":
            kv = str(v or "").strip().lower()
            if kv not in VALID_KINDS:
                raise CommonSeaError(
                    f"kind must be one of {VALID_KINDS} (got {v!r})"
                )
            s.kind = kv
        else:
            setattr(s, k, v if isinstance(v, str) else str(v or ""))
    p = sea_path(slug, env)
    p.write_text(_render(s), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root, f"common_seas: {slug} updated")
    return p


def archive_sea(
    *, slug: str, env: dict[str, str] | None = None,
) -> Path:
    return update_sea(slug=slug, patch={"status": "deprecated"}, env=env)


__all__ = [
    "COMMON_SEAS_SUBDIR", "VALID_KINDS",
    "CommonSeaError", "CommonSea",
    "common_seas_dir", "sea_path",
    "iter_seas", "get_sea",
    "create_sea", "update_sea", "archive_sea",
]
