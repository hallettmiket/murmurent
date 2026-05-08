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

  2. ``obsidian://`` URL  — when the file is *inside a registered
     Obsidian vault*. We win over ``$EDITOR`` here because the file
     literally lives in the user's Obsidian world; opening it elsewhere
     surprises them and breaks the ``[[wikilink]]`` graph.
  3. ``$EDITOR`` / ``$VISUAL``  — for files that aren't in a vault
     (e.g. when ``$WIGAMIG_NOTEBOOK_DIR`` points outside Obsidian).
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
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ..core import obsidian as _obs

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

    Priority:
      1. ``$WIGAMIG_NOTEBOOK_DIR`` — explicit override (used by tests
         + power users with non-Obsidian setups).
      2. ``<obsidian-vault>/lab-notebook/`` — the user's registered
         Obsidian vault, so the ``obsidian://`` URL works and notes
         live alongside the rest of their thinking.
      3. ``~/lab-notebook/`` — fallback when no vault is registered.

    On the first call after switching to the vault path, any pre-existing
    files under ``~/lab-notebook/`` are migrated in (one-time, logged).
    """
    override = os.environ.get("WIGAMIG_NOTEBOOK_DIR")
    if override:
        return Path(override).expanduser()

    vault = _obs.preferred_vault()
    if vault is not None:
        target = vault.path / NOTEBOOK_DIR_NAME
        _migrate_legacy_into_vault(Path.home() / NOTEBOOK_DIR_NAME, target)
        return target

    return Path.home() / NOTEBOOK_DIR_NAME


def _migrate_legacy_into_vault(legacy: Path, target: Path) -> None:
    """Move any ``.md`` files from ``legacy`` to ``target`` once.

    Skipped silently when ``legacy`` is empty or non-existent. Existing
    files in ``target`` are not overwritten.
    """
    if not legacy.is_dir() or legacy.resolve() == target.resolve():
        return
    md_files = [p for p in legacy.glob("*.md") if p.is_file()]
    if not md_files:
        return
    target.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for src in md_files:
        dst = target / src.name
        if dst.exists():
            continue  # respect existing vault content
        try:
            src.replace(dst)
            moved.append(src.name)
        except OSError:
            continue
    if moved:
        # Single-line stderr note; harmless in tests.
        print(
            f"[wigamig] migrated {len(moved)} note(s) from {legacy} -> {target}: "
            f"{', '.join(moved[:3])}{'…' if len(moved) > 3 else ''}",
            file=sys.stderr,
        )


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

    # Files inside a registered Obsidian vault always open in Obsidian
    # — the URL form actually works because the vault is registered, and
    # the user's [[wikilink]] graph + plugin set is in Obsidian, not
    # whatever $EDITOR they happen to have set.
    obsidian = _obsidian_cmd(path)
    if obsidian:
        return obsidian

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        return shlex.split(editor) + [str(path)]

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
    """Build an ``obsidian://`` open command, or ``None`` if not applicable.

    The URL only works when the *containing vault* is registered in
    Obsidian. We:

      - Look up which vault contains ``path`` via :mod:`core.obsidian`.
      - Build the URL with ``vault=<vault name>&file=<relative path
        without .md>``, both URL-encoded.
      - Return ``["open", url]`` (macOS) / ``["xdg-open", url]`` (Linux).

    ``force=True`` (e.g. user set ``WIGAMIG_NOTEBOOK_EDITOR=obsidian``
    explicitly) builds a best-effort URL using the parent folder name
    even when no vault match is found. The URL may still fail in
    Obsidian, but at least we try.
    """
    vault = _obs.vault_for_path(path)
    rel: str | None = None
    vault_name: str | None = None
    if vault is not None:
        vault_name = vault.name
        rel = _obs.relative_inside_vault(path, vault)
    elif force:
        vault_name = path.parent.name
        rel = path.stem

    if vault_name is None:
        return None
    file_param = rel if rel is not None else path.stem
    url = (
        "obsidian://open"
        f"?vault={urllib.parse.quote(vault_name, safe='')}"
        f"&file={urllib.parse.quote(file_param, safe='/')}"
    )
    if sys.platform == "darwin" and shutil.which("open"):
        return ["open", url]
    if shutil.which("xdg-open"):
        return ["xdg-open", url]
    return None


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
