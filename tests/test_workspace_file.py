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
    # Quick-start cheatsheet is prepended, project comes second.
    assert payload["folders"][0]["name"] == wf.QUICKSTART_FOLDER_NAME
    assert payload["folders"][1]["name"] == "Project: proj_a"
    # startupEditor must be "readme" so the quick-start README auto-opens.
    assert payload["settings"]["workbench.startupEditor"] == "readme"


def test_quickstart_help_folder_and_readme_created(world):
    """The cheatsheet folder exists on disk with a useful README inside."""
    _mkdir(world["repos"] / "proj_a")
    wf.write_workspace_file(project="proj_a", obsidian_vault_path=None)

    help_dir = wf.quickstart_help_dir("proj_a")
    assert help_dir.is_dir()
    readme = help_dir / "README.md"
    assert readme.exists()

    body = readme.read_text()
    # Names the project so users know which workspace they opened.
    assert "proj_a" in body
    # Leads with the one keystroke they really need to learn.
    assert "Cmd+Shift+P" in body
    # Bridges back to the VSCode task we added previously.
    assert "Monitor Claude agents" in body


def test_quickstart_readme_regenerates_on_relaunch(world):
    """Stale or hand-edited content is overwritten on the next launch."""
    _mkdir(world["repos"] / "proj_a")
    wf.write_workspace_file(project="proj_a", obsidian_vault_path=None)
    readme = wf.quickstart_help_dir("proj_a") / "README.md"
    readme.write_text("STALE CONTENT")

    wf.write_workspace_file(project="proj_a", obsidian_vault_path=None)
    assert "Cmd+Shift+P" in readme.read_text()


def test_payload_pins_claude_code_to_editor_and_blocks_copilot(world):
    """Single-chat-window policy: Claude Code in editor, Copilot not recommended."""
    _mkdir(world["repos"] / "proj_a")
    folders = wf.gather_folders(project="proj_a", obsidian_vault_path=None)
    payload = wf.build_payload(folders)

    assert payload["settings"]["claudeCode.preferredLocation"] == "editor"

    unwanted = payload["extensions"]["unwantedRecommendations"]
    assert "GitHub.copilot-chat" in unwanted
    assert "GitHub.copilot" in unwanted


def test_quickstart_readme_mentions_claude_code_shortcut(world):
    """Cheatsheet must explain how to open Claude Code itself."""
    _mkdir(world["repos"] / "proj_a")
    wf.write_workspace_file(project="proj_a", obsidian_vault_path=None)
    body = (wf.quickstart_help_dir("proj_a") / "README.md").read_text()
    assert "Cmd+Shift+Esc" in body
    assert "Claude Code" in body


def test_payload_includes_claude_agents_task(world):
    """The generated workspace exposes a one-click `claude agents` TUI task."""
    _mkdir(world["repos"] / "proj_a")
    folders = wf.gather_folders(project="proj_a", obsidian_vault_path=None)
    payload = wf.build_payload(folders)

    assert payload["tasks"]["version"] == "2.0.0"
    labels = [t["label"] for t in payload["tasks"]["tasks"]]
    assert "Monitor Claude agents" in labels

    task = next(
        t for t in payload["tasks"]["tasks"] if t["label"] == "Monitor Claude agents"
    )
    assert task["type"] == "shell"
    # The version gate must mention claude agents AND the minimum version,
    # so the user gets a useful upgrade hint if their CLI is too old.
    assert "claude agents" in task["command"]
    assert wf.MIN_CLAUDE_VERSION in task["command"]


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
