"""
Purpose: Centre-wide registry of "common tools" — SEAs, skills, routines,
         MCP servers, datasets that one lab built and is offering for any
         other lab to clone / use.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-23

The registrar advertises these on a public list; the member dashboard
renders them with a copy-paste install command per row. Submission is
explicit (each lab declares what it's sharing — no auto-discovery), so
the catalog stays curated.

Storage:

  <lab_info>/common_tools/<slug>.md
    ---
    slug: qc_drift_routine
    name: 'QC drift watcher'
    kind: routine                     # sea | skill | routine | mcp | dataset
    owner_lab: hallett
    description: 'Posts to slack when MoM QC metric drifts > 2σ.'
    install: 'wigamig routine install qc_drift_routine'
    url: 'https://github.com/hallettmiket/qc_drift_routine'
    tags: [qc, monitoring]
    status: active                    # active | deprecated
    created: '2026-05-23'
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


COMMON_TOOLS_SUBDIR = "common_tools"
VALID_KINDS = ("sea", "skill", "routine", "mcp", "dataset")
_SLUG_RE = _re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


class CommonToolError(ValueError):
    """Common-tool mutation failed (bad slug, missing fields, …)."""


@dataclass
class CommonTool:
    """One advertised common tool."""

    slug: str                              # filename stem
    name: str                              # display
    kind: str                              # sea | skill | routine | mcp | dataset
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

def common_tools_dir(env: dict[str, str] | None = None) -> Path:
    """``<lab_info>/common_tools/``."""
    return lab_info_root(env) / COMMON_TOOLS_SUBDIR


def tool_path(slug: str, env: dict[str, str] | None = None) -> Path:
    return common_tools_dir(env) / f"{slug}.md"


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _parse_tool(path: Path) -> CommonTool | None:
    try:
        parsed = parse_file(path)
    except Exception:
        return None
    meta = parsed.meta or {}
    slug = str(meta.get("slug") or path.stem)
    name = str(meta.get("name") or slug)
    return CommonTool(
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


def iter_tools(
    *,
    include_deprecated: bool = False,
    kind: str | None = None,
    owner_lab: str | None = None,
    tag: str | None = None,
    env: dict[str, str] | None = None,
) -> list[CommonTool]:
    """Browse the catalog with optional filters. Filters compose."""
    cdir = common_tools_dir(env)
    if not cdir.is_dir():
        return []
    out: list[CommonTool] = []
    for entry in sorted(cdir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        t = _parse_tool(entry)
        if t is None:
            continue
        if t.status == "deprecated" and not include_deprecated:
            continue
        if kind and t.kind != kind.lower():
            continue
        if owner_lab and t.owner_lab != owner_lab.lower():
            continue
        if tag and tag.lower() not in [x.lower() for x in t.tags]:
            continue
        out.append(t)
    return out


def get_tool(
    slug: str, env: dict[str, str] | None = None,
) -> CommonTool | None:
    p = tool_path(slug, env)
    if not p.is_file():
        return None
    return _parse_tool(p)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise CommonToolError(
            f"slug must match {_SLUG_RE.pattern} (got {slug!r}); "
            "use lowercase letters / digits / underscore; 2-64 chars."
        )
    return s


def _render(t: CommonTool) -> str:
    meta = {
        "slug": t.slug,
        "name": t.name,
        "kind": t.kind,
        "owner_lab": t.owner_lab,
        "description": t.description,
        "install": t.install,
        "url": t.url,
        "tags": list(t.tags),
        "status": t.status,
        "created": t.created,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False).rstrip()
    body = (t.notes or "").strip() or f"# {t.name}"
    return f"---\n{yaml_text}\n---\n\n{body}\n"


def create_tool(
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
        raise CommonToolError("name is required")
    k = (kind or "").strip().lower()
    if k not in VALID_KINDS:
        raise CommonToolError(
            f"kind must be one of {VALID_KINDS} (got {kind!r})"
        )
    if not owner_lab.strip():
        raise CommonToolError("owner_lab is required")
    p = tool_path(s, env)
    if p.is_file():
        raise CommonToolError(f"common tool already exists: {s}")
    now = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    t = CommonTool(
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
    p.write_text(_render(t), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"common_tools: +{s} ({k}, by lab {owner_lab.lower()})")
    return p


def update_tool(
    *,
    slug: str,
    patch: dict[str, Any],
    env: dict[str, str] | None = None,
) -> Path:
    t = get_tool(slug, env)
    if t is None:
        raise CommonToolError(f"common tool not found: {slug}")
    allowed = {"name", "kind", "description", "install", "url",
               "tags", "status", "notes"}
    for k, v in (patch or {}).items():
        if k not in allowed:
            continue
        if k == "tags":
            setattr(t, k, list(v or []))
        elif k == "kind":
            kv = str(v or "").strip().lower()
            if kv not in VALID_KINDS:
                raise CommonToolError(
                    f"kind must be one of {VALID_KINDS} (got {v!r})"
                )
            t.kind = kv
        else:
            setattr(t, k, v if isinstance(v, str) else str(v or ""))
    p = tool_path(slug, env)
    p.write_text(_render(t), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root, f"common_tools: {slug} updated")
    return p


def archive_tool(
    *, slug: str, env: dict[str, str] | None = None,
) -> Path:
    return update_tool(slug=slug, patch={"status": "deprecated"}, env=env)


__all__ = [
    "COMMON_TOOLS_SUBDIR", "VALID_KINDS",
    "CommonToolError", "CommonTool",
    "common_tools_dir", "tool_path",
    "iter_tools", "get_tool",
    "create_tool", "update_tool", "archive_tool",
]
