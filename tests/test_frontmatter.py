"""
Purpose: Unit tests for ``murmurent.core.frontmatter``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Synthetic markdown strings.
Output: pytest cases asserting correct parsing and validation behaviour.
"""

from __future__ import annotations

import pytest

from murmurent.core.frontmatter import (
    FrontmatterError,
    dump_document,
    parse_text,
    require_fields,
    split_frontmatter,
)


def test_parse_text_with_frontmatter() -> None:
    text = "---\nname: oracle\nfreeze: frozen\n---\n\nbody line 1\nbody line 2\n"
    doc = parse_text(text)
    assert doc.meta == {"name": "oracle", "freeze": "frozen"}
    assert doc.body.startswith("\nbody line 1")


def test_parse_text_without_frontmatter() -> None:
    text = "no frontmatter here\nstill no frontmatter"
    doc = parse_text(text)
    assert doc.meta == {}
    assert doc.body == text


def test_split_frontmatter_unterminated_raises() -> None:
    text = "---\nname: oracle\nno closing"
    with pytest.raises(FrontmatterError):
        split_frontmatter(text)


def test_parse_text_non_mapping_raises() -> None:
    text = "---\n- 1\n- 2\n---\nbody\n"
    with pytest.raises(FrontmatterError):
        parse_text(text)


def test_require_fields_passes_when_all_present() -> None:
    require_fields({"a": 1, "b": 2}, ["a", "b"])


def test_require_fields_raises_with_context() -> None:
    with pytest.raises(FrontmatterError) as excinfo:
        require_fields({"a": 1}, ["a", "b"], context="charter.md")
    assert "charter.md" in str(excinfo.value)
    assert "b" in str(excinfo.value)


def test_dump_document_roundtrip() -> None:
    meta = {"name": "x", "freeze": "personal"}
    body = "hello\n"
    rendered = dump_document(meta, body)
    parsed = parse_text(rendered)
    assert parsed.meta == meta
    assert parsed.body.strip() == body.strip()
