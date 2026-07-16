"""
Purpose: Unit tests for ``murmurent.core.repo``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``tmp_path`` fixtures simulating project repos.
Output: pytest cases asserting charter discovery and members parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murmurent.core.repo import (
    PERSONAL_VAULT_REPO_NAME,
    RepoDiscoveryError,
    find_project_repo,
    lab_repo_path,
    lab_vault_path,
    lab_vault_repo_name,
    personal_vault_path,
    personal_vault_repo_name,
    read_members,
    require_project_repo,
)


def _make_project(root: Path) -> Path:
    project = root / "project_a"
    project.mkdir()
    (project / "CHARTER.md").write_text("---\nname: project_a\n---\n", encoding="utf-8")
    (project / "MEMBERS").write_text("# header\n@the_pi\n@allie\n", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Vault naming helpers (issue #25)
# ---------------------------------------------------------------------------


def test_personal_vault_repo_name_is_canonical() -> None:
    """The personal vault repo is ``murmurent_vault`` on the person's GitHub."""
    assert personal_vault_repo_name() == "murmurent_vault"
    assert PERSONAL_VAULT_REPO_NAME == "murmurent_vault"


def test_personal_vault_path_honours_repos_root(tmp_path: Path, monkeypatch) -> None:
    """The default clone path sits under the (overridable) repos root."""
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path))
    assert personal_vault_path() == tmp_path / "murmurent_vault"


def test_lab_vault_repo_name_is_the_lab_mgmt_repo() -> None:
    """Per issue #25 the lab vault IS the lab-mgmt repo — its name is
    ``murmurent_lab_mgmt_<lab>``, NOT the superseded ``murmurent_vault_lab``."""
    assert lab_vault_repo_name("hallett") == "murmurent_lab_mgmt_hallett"
    assert lab_vault_repo_name("hallett") != "murmurent_vault_lab"


def test_lab_vault_path_matches_lab_repo_path(tmp_path: Path, monkeypatch) -> None:
    """The lab vault clone path is identical to the lab-mgmt clone path."""
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path))
    assert lab_vault_path("hallett") == lab_repo_path("hallett")
    assert lab_vault_path("hallett") == tmp_path / "murmurent_lab_mgmt_hallett"


def test_require_project_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(RepoDiscoveryError):
        require_project_repo(tmp_path)


def test_read_members_skips_blank_and_comments(tmp_path: Path) -> None:
    members = tmp_path / "MEMBERS"
    members.write_text("# comment\n\n@the_pi\n@allie\n", encoding="utf-8")
    assert read_members(members) == ["@the_pi", "@allie"]
