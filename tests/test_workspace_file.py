"""Tests for :mod:`wigamig.dashboard.workspace_file`.

The workspace generator deliberately drops folders that don't exist on
disk — a non-IT-savvy user opening VSCode and seeing a red "missing
folder" tile is exactly the friction this feature is meant to remove.
These tests pin that contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wigamig.dashboard import workspace_file as wf


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A self-contained tmp filesystem with project + lab_vm + vault dirs."""
    repos = tmp_path / "repos"
    lab_vm_root = tmp_path / "lab_vm" / "data"
    vault = tmp_path / "obsidian" / "vault"

    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(lab_vm_root))
    monkeypatch.setattr(wf, "WORKSPACE_DIR", tmp_path / "workspaces")
    # Force the personal-oracle fallback path so it does not leak from
    # the developer's real home dir into the test.
    monkeypatch.setattr(
        wf, "PERSONAL_ORACLE_FALLBACK", tmp_path / "claude_agent_memory" / "oracle"
    )

    return {
        "tmp": tmp_path,
        "repos": repos,
        "lab_vm": lab_vm_root,
        "vault": vault,
    }


def _mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_only_repo_when_nothing_else_exists(world):
    _mkdir(world["repos"] / "proj_a")
    folders = wf.gather_folders(project="proj_a", obsidian_vault_path=None)
    names = [f.name for f in folders]
    assert names == ["Project: proj_a"]


def test_repo_missing_is_dropped(world):
    # No proj_a dir at all.
    folders = wf.gather_folders(project="proj_a", obsidian_vault_path=None)
    assert folders == []


def test_refined_added_when_present(world):
    _mkdir(world["repos"] / "proj_a")
    _mkdir(world["lab_vm"] / "refined" / "proj_a")
    folders = wf.gather_folders(project="proj_a", obsidian_vault_path=None)
    names = [f.name for f in folders]
    assert names == ["Project: proj_a", "Refined outputs"]


def test_full_layout(world):
    _mkdir(world["repos"] / "proj_a")
    _mkdir(world["lab_vm"] / "refined" / "proj_a")
    _mkdir(world["vault"] / "lab-notebook")
    _mkdir(world["vault"] / "oracle")
    lab_oracle = _mkdir(world["tmp"] / "lab_oracle_vault")

    folders = wf.gather_folders(
        project="proj_a",
        obsidian_vault_path=str(world["vault"]),
        lab_oracle_vault=str(lab_oracle),
    )
    names = [f.name for f in folders]
    assert names == [
        "Project: proj_a",
        "Refined outputs",
        "Lab notebook",
        "My Oracle",
        "Group Oracle",
    ]


def test_project_scoped_notebook_subfolder_wins(world):
    _mkdir(world["repos"] / "proj_a")
    notebook = _mkdir(world["vault"] / "lab-notebook")
    scoped = _mkdir(notebook / "proj_a")
    folders = wf.gather_folders(
        project="proj_a", obsidian_vault_path=str(world["vault"])
    )
    notebook_folder = next(f for f in folders if f.name == "Lab notebook")
    assert notebook_folder.path == scoped


def test_personal_oracle_fallback_used_when_vault_has_no_oracle(world):
    _mkdir(world["repos"] / "proj_a")
    _mkdir(world["vault"] / "lab-notebook")
    fallback = _mkdir(wf.PERSONAL_ORACLE_FALLBACK)
    folders = wf.gather_folders(
        project="proj_a", obsidian_vault_path=str(world["vault"])
    )
    my_oracle = next(f for f in folders if f.name == "My Oracle")
    assert my_oracle.path == fallback


def test_vault_resident_oracle_preferred_over_fallback(world):
    _mkdir(world["repos"] / "proj_a")
    _mkdir(world["vault"] / "lab-notebook")
    vault_oracle = _mkdir(world["vault"] / "oracle")
    _mkdir(wf.PERSONAL_ORACLE_FALLBACK)
    folders = wf.gather_folders(
        project="proj_a", obsidian_vault_path=str(world["vault"])
    )
    my_oracle = next(f for f in folders if f.name == "My Oracle")
    assert my_oracle.path == vault_oracle


def test_group_oracle_missing_dir_dropped(world):
    _mkdir(world["repos"] / "proj_a")
    folders = wf.gather_folders(
        project="proj_a",
        obsidian_vault_path=None,
        lab_oracle_vault="wigamig-vault-hallett/",  # display string, no real dir
    )
    assert all(f.name != "Group Oracle" for f in folders)


def test_write_workspace_file_round_trip(world):
    _mkdir(world["repos"] / "proj_a")
    _mkdir(world["lab_vm"] / "refined" / "proj_a")
    written = wf.write_workspace_file(
        project="proj_a", obsidian_vault_path=None
    )
    assert written.exists()
    payload = json.loads(written.read_text())
    assert "folders" in payload and "settings" in payload
    assert payload["folders"][0]["name"] == "Project: proj_a"
    assert payload["settings"]["workbench.startupEditor"] == "none"


def test_custom_subfolder_names(world):
    _mkdir(world["repos"] / "proj_a")
    custom_nb = _mkdir(world["vault"] / "notes")
    custom_or = _mkdir(world["vault"] / "memory")
    folders = wf.gather_folders(
        project="proj_a",
        obsidian_vault_path=str(world["vault"]),
        notebook_subfolder="notes",
        oracle_subfolder="memory",
    )
    paths = {f.name: f.path for f in folders}
    assert paths["Lab notebook"] == custom_nb
    assert paths["My Oracle"] == custom_or
