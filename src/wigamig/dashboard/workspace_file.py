"""
Purpose: Build a VSCode multi-root ``.code-workspace`` file for a project so
         a non-IT-savvy user sees their repo, refined outputs, lab notebook,
         personal Oracle, and group Oracle in a single Explorer pane —
         without having to navigate the filesystem themselves.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-11
Input: Project name; member's Obsidian config (vault + subfolders); lab
       oracle vault path. All optional folders that do not resolve to a
       real directory are silently skipped — VSCode renders broken
       workspace roots as red error tiles, which scares users.
Output: A JSON dict ready to serialise as ``<project>.code-workspace`` and
        a helper that writes it to ``~/.wigamig/workspaces/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..core import lab_vm
from ..core.projects import project_path

WORKSPACE_DIR = Path.home() / ".wigamig" / "workspaces"
DEFAULT_NOTEBOOK_SUBFOLDER = "lab-notebook"
DEFAULT_ORACLE_SUBFOLDER = "oracle"
PERSONAL_ORACLE_FALLBACK = Path.home() / ".claude" / "agent-memory" / "oracle"


@dataclass(frozen=True)
class WorkspaceFolder:
    """One root in the VSCode workspace."""

    name: str
    path: Path


def gather_folders(
    *,
    project: str,
    obsidian_vault_path: str | None,
    notebook_subfolder: str = DEFAULT_NOTEBOOK_SUBFOLDER,
    oracle_subfolder: str = DEFAULT_ORACLE_SUBFOLDER,
    lab_oracle_vault: str | None = None,
    env: dict[str, str] | None = None,
) -> list[WorkspaceFolder]:
    """Resolve every folder that should appear in the workspace.

    Order matters — VSCode shows roots in declared order in the Explorer.
    We lead with the project repo (the user's main edit surface), then
    refined outputs (the data they care about), then the narrative /
    memory layers in increasing scope (personal → group).
    """
    folders: list[WorkspaceFolder] = []

    repo_dir = project_path(project, env=env)
    if repo_dir.is_dir():
        folders.append(WorkspaceFolder(name=f"Project: {project}", path=repo_dir))

    refined = lab_vm.project_refined_dir(project, env=env)
    if refined.is_dir():
        folders.append(WorkspaceFolder(name="Refined outputs", path=refined))

    vault: Path | None = None
    if obsidian_vault_path:
        candidate = Path(obsidian_vault_path).expanduser()
        if candidate.is_dir():
            vault = candidate

    if vault is not None:
        notebook = vault / notebook_subfolder
        scoped = notebook / project
        if scoped.is_dir():
            folders.append(WorkspaceFolder(name="Lab notebook", path=scoped))
        elif notebook.is_dir():
            folders.append(WorkspaceFolder(name="Lab notebook", path=notebook))

        personal_oracle = vault / oracle_subfolder
        if personal_oracle.is_dir():
            folders.append(WorkspaceFolder(name="My Oracle", path=personal_oracle))

    if not any(f.name == "My Oracle" for f in folders) and PERSONAL_ORACLE_FALLBACK.is_dir():
        folders.append(WorkspaceFolder(name="My Oracle", path=PERSONAL_ORACLE_FALLBACK))

    if lab_oracle_vault:
        lab_path = Path(lab_oracle_vault).expanduser()
        if lab_path.is_dir():
            folders.append(WorkspaceFolder(name="Group Oracle", path=lab_path))

    return folders


def build_payload(folders: Iterable[WorkspaceFolder]) -> dict:
    """Render the workspace JSON payload from a folder list."""
    return {
        "folders": [{"name": f.name, "path": str(f.path)} for f in folders],
        "settings": {
            "workbench.startupEditor": "none",
            "explorer.compactFolders": False,
        },
    }


def workspace_file_path(project: str) -> Path:
    """Return ``~/.wigamig/workspaces/<project>.code-workspace``."""
    return WORKSPACE_DIR / f"{project}.code-workspace"


def write_workspace_file(
    *,
    project: str,
    obsidian_vault_path: str | None,
    notebook_subfolder: str = DEFAULT_NOTEBOOK_SUBFOLDER,
    oracle_subfolder: str = DEFAULT_ORACLE_SUBFOLDER,
    lab_oracle_vault: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Build the workspace payload and write it to disk.

    Returns the path of the file written. The file is regenerated on
    every call so it tracks moves to the vault, new refined dirs, etc.
    """
    folders = gather_folders(
        project=project,
        obsidian_vault_path=obsidian_vault_path,
        notebook_subfolder=notebook_subfolder,
        oracle_subfolder=oracle_subfolder,
        lab_oracle_vault=lab_oracle_vault,
        env=env,
    )
    payload = build_payload(folders)
    out = workspace_file_path(project)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
