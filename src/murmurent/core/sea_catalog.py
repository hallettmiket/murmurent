"""
Purpose: Read + write the lab's catalog of offered SEAs at
         ``<lab-mgmt>/sea_catalog/<slug>.md``. Each entry is one
         markdown file; other groups discover them via the
         ``sea_catalog`` MCP (see :mod:`murmurent.mcp.sea_catalog_server`).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Markdown files with frontmatter, one per offered SEA.
Output: ``CatalogEntry`` dataclass; CRUD helpers.

Schema::

    ---
    slug: bulk_rnaseq_alignment           # filename stem
    title: 'DCIS bulk RNA-seq alignment'
    kind: experiment                       # skill | experiment | analysis
    turnaround_days: 7
    prerequisites: [GRCh38 reference, fastq files]
    contact: '@allie'                      # owner / receptionist match key
    accepting: true                        # if false, hidden from MCP listing
    created: 2026-05-08
    updated: 2026-05-08
    ---

    # DCIS bulk RNA-seq alignment

    Align bulk RNA-seq fastqs to GRCh38.p14, deliver count matrix
    + QC report.

The body is the rich human description (rendered in the catalog panel
as the entry's expanded content). The frontmatter is what other
groups' agents see via the MCP.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import dump_document, parse_file
from .repo import lab_mgmt_repo_root

CATALOG_SUBDIR = "sea_catalog"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
VALID_KINDS: tuple[str, ...] = ("skill", "experiment", "analysis")


class CatalogError(ValueError):
    """Schema or state error."""


class CatalogNotFound(CatalogError):
    """No matching slug on disk."""


@dataclass
class CatalogEntry:
    slug: str
    title: str
    kind: str
    contact: str  # ``@handle``
    description: str = ""
    turnaround_days: int | None = None
    prerequisites: list[str] = field(default_factory=list)
    accepting: bool = True
    created: str | None = None
    updated: str | None = None
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "slug": self.slug,
            "title": self.title,
            "kind": self.kind,
            "contact": self.contact,
            "accepting": self.accepting,
        }
        if self.turnaround_days is not None:
            meta["turnaround_days"] = self.turnaround_days
        if self.prerequisites:
            meta["prerequisites"] = list(self.prerequisites)
        if self.description:
            meta["description"] = self.description
        if self.created:
            meta["created"] = self.created
        if self.updated:
            meta["updated"] = self.updated
        return meta


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def catalog_dir() -> Path:
    return lab_mgmt_repo_root() / CATALOG_SUBDIR


def entry_path(slug: str) -> Path:
    return catalog_dir() / f"{slug}.md"


def parse_entry(path: Path) -> CatalogEntry:
    parsed = parse_file(path)
    meta = parsed.meta
    prereq = meta.get("prerequisites") or []
    if isinstance(prereq, str):
        prereq = [s.strip() for s in prereq.split(",") if s.strip()]
    return CatalogEntry(
        slug=str(meta.get("slug") or path.stem),
        title=str(meta.get("title") or path.stem),
        kind=str(meta.get("kind") or "skill"),
        contact=str(meta.get("contact") or ""),
        description=str(meta.get("description") or ""),
        turnaround_days=int(meta["turnaround_days"]) if meta.get("turnaround_days") else None,
        prerequisites=[str(p) for p in prereq],
        accepting=bool(meta.get("accepting", True)),
        created=str(meta.get("created")) if meta.get("created") else None,
        updated=str(meta.get("updated")) if meta.get("updated") else None,
        body=parsed.body,
        path=path,
    )


def iter_catalog(*, accepting_only: bool = False) -> list[CatalogEntry]:
    """List every offered SEA, alphabetised by slug."""
    cdir = catalog_dir()
    if not cdir.is_dir():
        return []
    out: list[CatalogEntry] = []
    for child in sorted(cdir.glob("*.md")):
        try:
            entry = parse_entry(child)
        except Exception:
            continue
        if accepting_only and not entry.accepting:
            continue
        out.append(entry)
    return out


def render_entry(entry: CatalogEntry) -> str:
    body = entry.body or _default_body(entry)
    return dump_document(entry.to_meta(), body)


def write_entry(entry: CatalogEntry) -> Path:
    cdir = catalog_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    path = entry_path(entry.slug)
    path.write_text(render_entry(entry), encoding="utf-8")
    entry.path = path
    return path


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def upsert(
    *,
    slug: str,
    title: str,
    kind: str,
    contact: str,
    description: str = "",
    turnaround_days: int | None = None,
    prerequisites: list[str] | None = None,
    accepting: bool = True,
    today: _dt.date | None = None,
) -> CatalogEntry:
    """Create or update an entry. Caller is responsible for authz."""
    if not SLUG_RE.match(slug):
        raise CatalogError(
            f"slug must be lowercase letters, digits, underscores; got {slug!r}"
        )
    if kind not in VALID_KINDS:
        raise CatalogError(f"kind must be one of {VALID_KINDS!r}; got {kind!r}")
    if not contact.strip():
        raise CatalogError("contact handle is required (e.g. '@allie')")

    today = today or _dt.date.today()
    path = entry_path(slug)
    existing: CatalogEntry | None = None
    if path.is_file():
        try:
            existing = parse_entry(path)
        except Exception:
            existing = None

    entry = CatalogEntry(
        slug=slug,
        title=title.strip() or slug,
        kind=kind,
        contact=contact if contact.startswith("@") else f"@{contact}",
        description=description.strip(),
        turnaround_days=turnaround_days,
        prerequisites=list(prerequisites or []),
        accepting=accepting,
        created=existing.created if existing else today.isoformat(),
        updated=today.isoformat(),
        body=existing.body if existing else "",
    )
    write_entry(entry)
    return entry


def set_accepting(slug: str, *, accepting: bool, today: _dt.date | None = None) -> CatalogEntry:
    """Toggle the ``accepting`` flag on an entry without rewriting other fields."""
    path = entry_path(slug)
    if not path.is_file():
        raise CatalogNotFound(f"no catalog entry: {slug}")
    entry = parse_entry(path)
    entry.accepting = accepting
    entry.updated = (today or _dt.date.today()).isoformat()
    write_entry(entry)
    return entry


def delete(slug: str) -> None:
    """Remove an entry from disk."""
    path = entry_path(slug)
    if not path.is_file():
        raise CatalogNotFound(f"no catalog entry: {slug}")
    path.unlink()


def get(slug: str) -> CatalogEntry:
    path = entry_path(slug)
    if not path.is_file():
        raise CatalogNotFound(f"no catalog entry: {slug}")
    return parse_entry(path)


def _default_body(entry: CatalogEntry) -> str:
    return (
        f"# {entry.title}\n\n"
        f"{entry.description or '_(brief description here)_'}\n\n"
        "## What we need from you\n\n"
        "_(list inputs / data / context here)_\n\n"
        "## What we deliver\n\n"
        "_(list outputs / format / timeline here)_\n"
    )
