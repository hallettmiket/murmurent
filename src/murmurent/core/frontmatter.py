"""
Purpose: Parse and validate YAML frontmatter on murmurent markdown artefacts.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Markdown text or path to a markdown file with optional ``---`` frontmatter.
Output: ``ParsedDocument(meta: dict, body: str)`` and validation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

FRONTMATTER_DELIM = "---"


class FrontmatterError(ValueError):
    """Raised when a document's frontmatter is malformed or missing required fields."""


@dataclass
class ParsedDocument:
    """A markdown document split into its frontmatter and body."""

    meta: dict[str, Any]
    body: str
    source: Path | None = None


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split ``text`` into a raw frontmatter block and the remaining body.

    Parameters
    ----------
    text:
        Full markdown text. If it starts with ``---``, everything between the
        first two ``---`` delimiters is treated as YAML frontmatter.

    Returns
    -------
    tuple
        ``(frontmatter_text, body)``. ``frontmatter_text`` is ``None`` when the
        document has no frontmatter block.
    """
    stripped = text.lstrip("﻿")
    if not stripped.startswith(FRONTMATTER_DELIM):
        return None, text

    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        return None, text

    closing_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == FRONTMATTER_DELIM:
            closing_idx = idx
            break

    if closing_idx is None:
        raise FrontmatterError("Unterminated frontmatter block (missing closing '---').")

    frontmatter_text = "".join(lines[1:closing_idx])
    body = "".join(lines[closing_idx + 1 :])
    return frontmatter_text, body


def parse_text(text: str, source: Path | None = None) -> ParsedDocument:
    """Parse a markdown string into a :class:`ParsedDocument`."""
    raw_meta, body = split_frontmatter(text)
    meta: dict[str, Any] = {}
    if raw_meta is not None:
        loaded = yaml.safe_load(raw_meta) or {}
        if not isinstance(loaded, dict):
            raise FrontmatterError(
                "Frontmatter must be a YAML mapping; " f"got {type(loaded).__name__} instead."
            )
        meta = loaded
    return ParsedDocument(meta=meta, body=body, source=source)


def parse_file(path: str | Path) -> ParsedDocument:
    """Read and parse a markdown file."""
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), source=p)


def require_fields(meta: dict[str, Any], fields: Iterable[str], *, context: str = "") -> None:
    """Raise :class:`FrontmatterError` if any required ``fields`` are missing.

    Parameters
    ----------
    meta:
        Parsed frontmatter dictionary.
    fields:
        Iterable of required field names.
    context:
        Optional string included in the error message (e.g. file path or document name).
    """
    missing = [f for f in fields if f not in meta]
    if missing:
        suffix = f" in {context}" if context else ""
        raise FrontmatterError(
            f"Missing required frontmatter field(s){suffix}: {', '.join(missing)}"
        )


def dump_document(meta: dict[str, Any], body: str) -> str:
    """Serialize ``meta`` + ``body`` back into a markdown string with frontmatter.

    Uses ``allow_unicode=True`` so characters like ``·`` survive as-is
    rather than being escaped to ``\\xB7`` — important because these
    files are read by humans, not just by code.
    """
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    body_clean = body.lstrip("\n")
    if body_clean and not body_clean.endswith("\n"):
        body_clean += "\n"
    return f"{FRONTMATTER_DELIM}\n{yaml_text}{FRONTMATTER_DELIM}\n\n{body_clean}"
