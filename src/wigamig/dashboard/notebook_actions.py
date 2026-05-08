"""
Purpose: Open a daily-notes entry in the user's preferred editor (Phase 6).
         The dashboard panel itself stays read-only; clicking ``Edit`` POSTs
         here, the server creates the file if missing, and launches the
         editor on the same machine.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ISO date string (defaults to today).
Output: ``OpenResult`` dict with the resolved path + the launched command.

Editor resolution (first match wins):

  1. ``$WIGAMIG_NOTEBOOK_EDITOR``  — explicit override. Use ``{path}`` as a
     placeholder for the file path. Examples::

          export WIGAMIG_NOTEBOOK_EDITOR="obsidian"
          export WIGAMIG_NOTEBOOK_EDITOR="code -g {path}"
          export WIGAMIG_NOTEBOOK_EDITOR="vim {path}"

  2. ``$EDITOR`` / ``$VISUAL``  — the user's general editor preference.
     We trust this above the design's Obsidian default; users who set
     ``$EDITOR=vim`` almost always want that.
  3. ``obsidian://`` URL  — the design doc's preferred path; works when the
     user has registered ``~/lab-notebook`` as an Obsidian vault.
  4. ``code`` (VS Code) if on PATH.
  5. Platform default — ``open`` (macOS) / ``xdg-open`` (Linux).

Single-user, localhost-only; subprocess.Popen is fine here. The path is
constructed server-side, never from user input.
"""

from __future__ import annotations

import datetime as _dt
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NOTEBOOK_DIR_NAME = "lab-notebook"


@dataclass(frozen=True)
class OpenResult:
    """Returned to the caller on success."""

    path: Path
    cmd: list[str]
    created: bool


class NotebookActionError(Exception):
    """Base for all notebook-action failures."""


class NotebookEditorNotAvailable(NotebookActionError):
    """No editor could be resolved for this platform."""


# ---------------------------------------------------------------------------
# Path / template
# ---------------------------------------------------------------------------


def notebook_folder() -> Path:
    """Resolve the daily-notes folder.

    Honours ``$WIGAMIG_NOTEBOOK_DIR`` for tests / non-default vaults;
    otherwise ``~/lab-notebook/``.
    """
    override = os.environ.get("WIGAMIG_NOTEBOOK_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / NOTEBOOK_DIR_NAME


def entry_path(date_iso: str) -> Path:
    """Resolve the file path for ``date_iso`` (e.g. ``2026-05-08``)."""
    return notebook_folder() / f"{date_iso}.md"


def default_entry_text(date_iso: str) -> str:
    """Template for a fresh daily note.

    Front-matter matches the dashboard's parser (snapshot._parse_markdown_blocks)
    so the new entry round-trips cleanly into the panel.
    """
    return (
        "---\n"
        f"date: {date_iso}\n"
        "tags: []\n"
        "links_seas: []\n"
        "links_exp: []\n"
        "---\n"
        "\n"
        "#### Plan for today\n"
        "\n"
        "- [ ] \n"
        "\n"
        "#### Notes\n"
        "\n"
    )


# ---------------------------------------------------------------------------
# Editor resolution
# ---------------------------------------------------------------------------


def resolve_editor_cmd(path: Path) -> list[str]:
    """Pick a launch command for ``path``. See module docstring for rules."""
    override = os.environ.get("WIGAMIG_NOTEBOOK_EDITOR", "").strip()
    if override:
        if override.lower() == "obsidian":
            # Explicit override - trust the user even if the vault isn't
            # auto-detected in Obsidian's registry.
            forced = _obsidian_cmd(path, force=True)
            if forced:
                return forced
        if "{path}" in override:
            return shlex.split(override.replace("{path}", str(path)))
        # Plain command name -> append the path.
        return shlex.split(override) + [str(path)]

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        return shlex.split(editor) + [str(path)]

    # Implicit Obsidian fallback only when the vault is genuinely
    # registered. Otherwise the URL fails silently and the user sees
    # nothing happen.
    obsidian = _obsidian_cmd(path)
    if obsidian:
        return obsidian

    if shutil.which("code"):
        return ["code", str(path)]

    if sys.platform == "darwin" and shutil.which("open"):
        return ["open", str(path)]
    if shutil.which("xdg-open"):
        return ["xdg-open", str(path)]

    raise NotebookEditorNotAvailable(
        "No editor available. Set $WIGAMIG_NOTEBOOK_EDITOR or $EDITOR."
    )


def _obsidian_cmd(path: Path, *, force: bool = False) -> list[str] | None:
    """Build an ``obsidian://`` open command if possible.

    Refuses to return a URL command unless we can confirm Obsidian has
    the target folder registered as a vault — otherwise the URL fails
    silently (``Unable to find a vault for the URL …``) and the file
    never opens.

    ``force=True`` skips the registration check (the user explicitly
    asked for Obsidian via ``WIGAMIG_NOTEBOOK_EDITOR=obsidian``; trust
    them even if we can't auto-detect the registry).

    Returns ``None`` if (a) the platform can't dispatch URLs, (b) the
    vault isn't registered (and not forced).
    """
    folder = path.parent
    if not force and not _obsidian_vault_registered(folder):
        return None
    vault = folder.name
    file_stem = path.stem
    url = f"obsidian://open?vault={vault}&file={file_stem}"
    if sys.platform == "darwin" and shutil.which("open"):
        return ["open", url]
    if shutil.which("xdg-open"):
        return ["xdg-open", url]
    return None


def _obsidian_vault_registered(folder: Path) -> bool:
    """Return True if ``folder`` is in Obsidian's vault registry.

    Obsidian stores its registry as JSON. Path varies by platform:

      macOS:   ~/Library/Application Support/obsidian/obsidian.json
      Linux:   ~/.config/obsidian/obsidian.json
      Windows: %APPDATA%/obsidian/obsidian.json (not supported here)
    """
    import json

    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(
            Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
        )
    candidates.append(Path.home() / ".config" / "obsidian" / "obsidian.json")

    target = str(folder.resolve())
    for cfg in candidates:
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        vaults = data.get("vaults") or {}
        for entry in vaults.values():
            vp = entry.get("path")
            if vp and Path(vp).resolve() == Path(target):
                return True
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def open_entry(
    date_iso: str | None = None,
    *,
    today: _dt.date | None = None,
    spawn: bool = True,
) -> OpenResult:
    """Open the entry for ``date_iso`` in the user's editor.

    Creates the file with :func:`default_entry_text` if it doesn't exist
    yet. Returns the launched command + resolved path. ``spawn=False`` is
    a hook for tests so we don't actually fork an editor process.
    """
    if date_iso is None:
        date_iso = (today or _dt.date.today()).isoformat()

    folder = notebook_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date_iso}.md"
    created = False
    if not path.is_file():
        path.write_text(default_entry_text(date_iso), encoding="utf-8")
        created = True

    cmd = resolve_editor_cmd(path)
    if spawn:
        try:
            subprocess.Popen(  # noqa: S603 — args are list; never shelled
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            raise NotebookEditorNotAvailable(str(exc)) from exc

    return OpenResult(path=path, cmd=cmd, created=created)
