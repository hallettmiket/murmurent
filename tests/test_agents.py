"""
Purpose: Validate the ported agent registry and the loader in ``murmurent.core.agents``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``agents/`` directory at the repo root + synthetic agent files for negative tests.
Output: pytest cases asserting all eight agents load with valid frontmatter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murmurent.core.agents import (
    VALID_CATEGORY_VALUES,
    VALID_FREEZE_VALUES,
    load_agent,
    load_registry,
)
from murmurent.core.frontmatter import FrontmatterError

REPO_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
# receptionist was deprecated in #38 (its only surface, the inbound-SEA
# dashboard panel, was removed; the SEA backend stays but dormant).
EXPECTED_AGENTS = {
    "adversary",
    "artist",
    "blacksmith",
    "bookworm",
    "cable_guy",
    "centre_cable_guy",
    "conscience",
    "judge",
    "lab_oracle",
    "oracle",
    "registrar",
    "lawyer",
    "security_guard",
}

# Commons-agent categories (#38). The rest default to "member".
EXPECTED_CATEGORY = {
    "registrar": "administrative",
    "centre_cable_guy": "administrative",
    "judge": "choreography-support",
}


def test_registry_contains_all_expected_agents() -> None:
    registry = load_registry(REPO_AGENTS_DIR)
    names = {record.name for record in registry}
    assert names == EXPECTED_AGENTS


def test_each_agent_has_required_new_fields() -> None:
    for record in load_registry(REPO_AGENTS_DIR):
        assert record.freeze in VALID_FREEZE_VALUES, record
        assert record.category in VALID_CATEGORY_VALUES, record
        assert isinstance(record.required_tools, tuple)
        assert isinstance(record.denied_tools, tuple)
        assert isinstance(record.defaults, dict)
        assert record.description, f"{record.name} missing description"


def test_agent_categories_match_expected() -> None:
    registry = {r.name: r for r in load_registry(REPO_AGENTS_DIR)}
    for name, record in registry.items():
        assert record.category == EXPECTED_CATEGORY.get(name, "member"), name


def test_descriptions_dropped_the_verdict_boilerplate() -> None:
    """The "MUST: first line…" prefix was removed from every description in #38;
    the rule lives in rules/headline_first.md + each agent body, not the blurb."""
    for record in load_registry(REPO_AGENTS_DIR):
        assert "MUST: first line" not in record.description, record.name


def test_load_agent_rejects_invalid_category(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\nname: bad\nfreeze: personal\ncategory: purple\n---\n\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(FrontmatterError):
        load_agent(bad)


def test_security_guard_is_frozen() -> None:
    registry = {r.name: r for r in load_registry(REPO_AGENTS_DIR)}
    assert registry["security_guard"].freeze == "frozen"
    assert "WebFetch" in registry["security_guard"].denied_tools


def test_load_agent_rejects_invalid_freeze(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\nname: bad\nfreeze: blue\n---\n\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(FrontmatterError):
        load_agent(bad)
