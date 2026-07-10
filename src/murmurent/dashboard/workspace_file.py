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
        a helper that writes it to ``~/.murmurent/workspaces/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..core import lab_vm
from ..core.projects import project_path

WORKSPACE_DIR = Path.home() / ".murmurent" / "workspaces"
DEFAULT_NOTEBOOK_SUBFOLDER = "lab-notebook"
DEFAULT_ORACLE_SUBFOLDER = "oracle"
PERSONAL_ORACLE_FALLBACK = Path.home() / ".claude" / "agent-memory" / "oracle"

# `claude agents` (the background-session TUI) shipped here. Older CLIs
# would error out, so the workspace task gates on this version.
MIN_CLAUDE_VERSION = "2.1.139"

# Quick-start cheatsheet (Option 1): a tiny per-project help folder added
# as the FIRST workspace root so VSCode's startupEditor="readme" pops the
# cheatsheet as a tab on first launch. Non-IT users see "Cmd+Shift+P …"
# without having to know they need Cmd+Shift+P to find it.
QUICKSTART_FOLDER_NAME = "Quick start"


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


def _claude_agents_task() -> dict:
    """VSCode task that opens the ``claude agents`` monitor TUI.

    Wrapped in an inline version gate because the feature is a research
    preview; an older ``claude`` CLI would error out in a way that
    confuses non-IT users. The gate uses ``sort -V`` so semver ordering
    is handled correctly without needing a helper script.
    """
    min_v = MIN_CLAUDE_VERSION
    gate = (
        "v=$(claude --version 2>/dev/null | awk '{print $1}'); "
        f'if printf "%s\\n%s\\n" "{min_v}" "$v" | sort -V -C; '
        "then claude agents; "
        f'else echo "claude agents needs Claude Code >= {min_v} '
        '(you have ${v:-none}). Run: npm i -g @anthropic-ai/claude-code"; fi'
    )
    return {
        "label": "Monitor Claude agents",
        "type": "shell",
        "command": gate,
        "problemMatcher": [],
        "presentation": {
            "panel": "dedicated",
            "reveal": "always",
            "focus": False,
            "clear": True,
        },
    }


def build_payload(folders: Iterable[WorkspaceFolder]) -> dict:
    """Render the workspace JSON payload from a folder list.

    ``startupEditor`` is ``"readme"`` so the first folder's ``README.md``
    auto-opens on a fresh launch — the quickstart cheatsheet is meant to
    sit at position 0 to leverage this. ``claudeCode.preferredLocation``
    pins Claude Code to an editor tab (more screen real estate than the
    panel). ``extensions.unwantedRecommendations`` stops VSCode from
    nagging the user to install Copilot Chat, which would otherwise add
    a second chat surface and confuse non-IT users.
    """
    return {
        "folders": [{"name": f.name, "path": str(f.path)} for f in folders],
        "settings": {
            "workbench.startupEditor": "readme",
            "explorer.compactFolders": False,
            "claudeCode.preferredLocation": "editor",
        },
        "extensions": {
            "unwantedRecommendations": [
                "GitHub.copilot-chat",
                "GitHub.copilot",
            ],
        },
        "tasks": {
            "version": "2.0.0",
            "tasks": [_claude_agents_task()],
        },
    }


def quickstart_help_dir(project: str) -> Path:
    """Return ``~/.murmurent/workspaces/<project>_help/``."""
    return WORKSPACE_DIR / f"{project}_help"


def _quickstart_readme_content(project: str) -> str:
    """Render the per-project cheatsheet markdown.

    Regenerated on every workspace-launch so it never drifts from the
    current murmurent install. The opening section deliberately leads with
    the *one* keystroke a user needs (`Cmd+Shift+P`); everything else is
    discoverable from the command palette.
    """
    return f"""# Quick start — {project}

Welcome! This workspace puts everything you need for **{project}** in one window.

## Open Claude Code

Press **`Cmd+Shift+Esc`** — Claude Code opens as an editor tab.
(`Cmd+Esc` toggles focus in/out of the Claude Code input.)

## Open the agent monitor

1. Press **`Cmd+Shift+P`** to open the command palette.
2. Type **Run Task** and press Enter.
3. Pick **Monitor Claude agents**.

You'll get a live TUI of your background Claude sessions.

## What's in the Explorer (left sidebar)

- **Quick start** — this folder.
- **Project: {project}** — your code.
- **Refined outputs** — analysis outputs from the lab VM.
- **Lab notebook** — your Obsidian notebook for this project.
- **My Oracle** — your personal AI memory.
- **Group Oracle** — your lab's shared AI memory.

Folders that don't exist yet are hidden — they'll appear automatically once they're created.

## Common VSCode shortcuts

| Shortcut | What it does |
| --- | --- |
| `Cmd+Shift+Esc` | Open Claude Code as an editor tab |
| `Cmd+Esc` | Toggle focus in/out of Claude Code |
| `Cmd+Shift+P` | Command palette — run any VSCode action by name |
| `` Cmd+` `` | Toggle the integrated terminal |
| `Cmd+B` | Toggle the left sidebar (Explorer) |
| `Cmd+P` | Quick-open any file in the workspace |
| `Cmd+Shift+E` | Focus the Explorer |
| `Cmd+W` | Close the current tab |

## Need help?

- Lab Slack: `#claude-test`
- Murmurent training: see the dashboard's "Training" row.

---

*Generated by murmurent. Regenerates each time you launch this project — your edits here will be overwritten.*
"""


def _write_quickstart_help(project: str) -> WorkspaceFolder:
    """Create (or refresh) the per-project quick-start help folder.

    Idempotent — the README is overwritten on every call so users always
    see the cheatsheet that matches the murmurent version that just opened
    their workspace. Returns the :class:`WorkspaceFolder` for prepending.
    """
    help_dir = quickstart_help_dir(project)
    help_dir.mkdir(parents=True, exist_ok=True)
    readme = help_dir / "README.md"
    readme.write_text(_quickstart_readme_content(project), encoding="utf-8")
    return WorkspaceFolder(name=QUICKSTART_FOLDER_NAME, path=help_dir)


def workspace_file_path(project: str) -> Path:
    """Return ``~/.murmurent/workspaces/<project>.code-workspace``."""
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
    help_folder = _write_quickstart_help(project)
    discovered = gather_folders(
        project=project,
        obsidian_vault_path=obsidian_vault_path,
        notebook_subfolder=notebook_subfolder,
        oracle_subfolder=oracle_subfolder,
        lab_oracle_vault=lab_oracle_vault,
        env=env,
    )
    # Quick-start root must be position 0: VSCode's startupEditor="readme"
    # only looks at the first folder's README.
    folders = [help_folder, *discovered]
    payload = build_payload(folders)
    out = workspace_file_path(project)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
