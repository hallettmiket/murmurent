"""
Purpose: ``murmurent prompt``: write prompts in Obsidian, send them to Claude
         Code with one keystroke, keep a record (docs/lab_notebook.md).
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   ``--text``, ``--file`` (default today's prompts file), stdin.
Output:  The clipboard, a paste, and ``sessions/<date>/sent.md`` in the vault.
"""

from __future__ import annotations

import subprocess
import sys

import click

from ..core import lab_notebook as _nb
from ..core import prompt_send as _ps


@click.group("prompt", help="Prompts written in Obsidian, sent to Claude Code, and kept.")
def prompt_group() -> None:
    pass


@prompt_group.command("new", help="Open today's prompts file in the vault (created with a heading when missing).")
@click.option("--no-open", is_flag=True, help="Print the path; do not open it.")
def prompt_new(no_open: bool) -> None:
    paths = _nb.require_paths()
    path = _ps.ensure_prompts_file(paths)
    click.echo(str(path))
    if not no_open and sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


@prompt_group.command("send", help="Send a prompt to Claude Code: the text given, the latest block of a prompts file, or --stdin. Copies, pastes, records.")
@click.option("--text", default=None, help="The prompt itself (an Obsidian hotkey passes the selection here).")
@click.option("--file", "file_", default=None, help="A prompts file; its latest block is sent (default: today's).")
@click.option("--to", default=_ps.DEFAULT_APP, show_default=True, help="The app to paste into (macOS): Claude, Terminal, iTerm, Code.")
@click.option("--tmux", "tmux_pane", default="", help="Paste into this tmux pane instead of an app.")
@click.option("--no-paste", is_flag=True, help="Copy to the clipboard and record only.")
@click.option("--project", default="", help="Project to record it under (default: general).")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the prompt from standard input.")
def prompt_send(text: str | None, file_: str | None, to: str, tmux_pane: str, no_paste: bool, project: str,
                from_stdin: bool) -> None:
    paths = _nb.require_paths()
    try:
        if from_stdin:
            text = sys.stdin.read()
        if text is None:
            from pathlib import Path
            path = Path(file_).expanduser() if file_ else _ps.ensure_prompts_file(paths)
            if not path.exists():
                click.echo(f"no prompts file at {path}", err=True)
                sys.exit(1)
            text = _ps.latest_block(path)
        sent = _ps.send(text, paths=paths, to=to, tmux_pane=tmux_pane, paste=not no_paste, project=project)
    except _ps.SendError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    where = f"pasted into {sent.pasted_to}" if sent.pasted_to else "on the clipboard"
    click.echo(f"sent ({len(sent.text)} characters, {where}); recorded in {paths.rel(sent.record)}")
