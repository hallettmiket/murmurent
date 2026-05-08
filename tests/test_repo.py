"""
Purpose: Unit tests for ``wigamig.core.repo``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``tmp_path`` fixtures simulating project repos.
Output: pytest cases asserting charter discovery and members parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wigamig.core.repo import (
    RepoDiscoveryError,
    find_project_repo,
    read_members,
    require_project_repo,
)


def _make_project(root: Path) -> Path:
    project = root / "project_a"
    project.mkdir()
    (project / "CHARTER.md").write_text("---\nname: project_a\n---\n", encoding="utf-8")
    (project / "MEMBERS").write_text("# header\n@mhallet\n@allie\n", encoding="utf-8")
    nested = project / "exp" / "1_qc"
    nested.mkdir(parents=True)
    return project


def test_find_project_repo_walks_up(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    nested = project / "exp" / "1_qc"
    found = find_project_repo(nested)
    assert found is not None
    assert found.path == project
    assert found.charter_path == project / "CHARTER.md"
    assert found.members_path == project / "MEMBERS"


def test_find_project_repo_returns_none_when_no_charter(tmp_path: Path) -> None:
    assert find_project_repo(tmp_path) is None


def test_require_project_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(RepoDiscoveryError):
        require_project_repo(tmp_path)


def test_read_members_skips_blank_and_comments(tmp_path: Path) -> None:
    members = tmp_path / "MEMBERS"
    members.write_text("# comment\n\n@mhallet\n@allie\n", encoding="utf-8")
    assert read_members(members) == ["@mhallet", "@allie"]
