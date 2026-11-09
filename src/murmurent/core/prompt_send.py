"""
Purpose: Send a prompt written in Obsidian to Claude Code in one keystroke,
         and keep a record of it. Members write prompts in the vault
         (``prompts/<date>.md``, one block per prompt, blocks separated by a
         line ``---``) because a long prompt is easier to write there than in
         a terminal; this module takes the selected text or the latest block,
         copies it to the clipboard, pastes it into the Claude Code window
         (macOS, through osascript) or a tmux pane, and appends it to
         ``sessions/<date>/sent.md`` with the time, so what was sent is never
         lost when the session closes.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   Text, or a prompts file (default today's), the vault from
         :mod:`murmurent.core.lab_notebook`.
Output:  The clipboard, a paste into the chosen app or pane, the record file.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import lab_notebook as _nb

PROMPTS_SUBFOLDER = "prompts"
SEPARATOR = re.compile(r"^\s*---\s*(send)?\s*$", re.M)
DEFAULT_APP = "Claude"


class SendError(Exception):
    pass


@dataclass
class Sent:
    text: str
    record: Path
    pasted_to: str      # "Claude", "Terminal", "tmux:<pane>", or "" when only copied


def prompts_dir(paths: _nb.NotebookPaths) -> Path:
    return paths.vault / PROMPTS_SUBFOLDER


def prompts_file(paths: _nb.NotebookPaths, day: _dt.date | None = None) -> Path:
    day = day or _dt.date.today()
    return prompts_dir(paths) / f"{day.isoformat()}.md"


def ensure_prompts_file(paths: _nb.NotebookPaths, day: _dt.date | None = None) -> Path:
    """Today's prompts file, created with a heading when missing. Never rewritten."""
    path = prompts_file(paths, day)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        d = (day or _dt.date.today()).isoformat()
        path.write_text(f"# Prompts, {d}\n\nOne prompt per block; a line `---` ends a block. "
                        f"Send the latest with `murmurent prompt send`, or a selection with a hotkey.\n\n---\n\n",
                        encoding="utf-8")
    return path


def blocks(text: str) -> list[str]:
    """The prompt blocks of a prompts file: the text between `---` lines, the heading
    and the help line left out, empty blocks dropped."""
    body = text
    if body.startswith("# "):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    body = re.sub(r"^One prompt per block;.*$", "", body, count=1, flags=re.M)
    out = [b.strip() for b in SEPARATOR.split(body) if b and b.strip() and b.strip() != "send"]
    return out


def latest_block(path: Path) -> str:
    bs = blocks(path.read_text(encoding="utf-8"))
    if not bs:
        raise SendError(f"{path} has no prompt block yet (write one, then a line `---`)")
    return bs[-1]


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def paste_into_app(app: str) -> None:
    """Bring ``app`` to the front and paste the clipboard, then press return.
    macOS only; the first use asks for the automation permission."""
    script = (f'tell application "{app}" to activate\n'
              'delay 0.4\n'
              'tell application "System Events" to keystroke "v" using command down\n'
              'delay 0.2\n'
              'tell application "System Events" to key code 36\n')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise SendError(f"could not paste into {app}: {r.stderr.strip() or 'osascript failed'}; "
                        "the prompt is on the clipboard, paste it by hand")


def send_to_tmux(pane: str, text: str) -> None:
    r = subprocess.run(["tmux", "send-keys", "-t", pane, "-l", text], capture_output=True, text=True)
    if r.returncode == 0:
        r = subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SendError(f"could not send to tmux pane {pane}: {r.stderr.strip()}; the prompt is on the clipboard")


def record_sent(paths: _nb.NotebookPaths, text: str, when: _dt.datetime, project: str = "") -> Path:
    """Append the prompt to sessions/<date>/sent.md, the member's own record of what
    they sent, beside the hook's record of what reached Claude Code."""
    return _nb.record_prompt(paths, session_id="sent", prompt=text, when=when, project=project)


def send(text: str, *, paths: _nb.NotebookPaths, to: str = DEFAULT_APP, tmux_pane: str = "",
         paste: bool = True, project: str = "", now: _dt.datetime | None = None,
         clipboard: Callable[[str], None] | None = None,
         paster: Callable[[str], None] | None = None,
         tmux: Callable[[str, str], None] | None = None) -> Sent:
    """The three side effects are looked up at call time (so a test can replace the
    module's functions and never reach the clipboard, an app or tmux)."""
    clipboard = clipboard or copy_to_clipboard
    paster = paster or paste_into_app
    tmux = tmux or send_to_tmux
    text = text.strip()
    if not text:
        raise SendError("nothing to send")
    now = now or _dt.datetime.now()
    clipboard(text)
    pasted = ""
    if paste:
        if tmux_pane:
            tmux(tmux_pane, text)
            pasted = f"tmux:{tmux_pane}"
        else:
            paster(to)
            pasted = to
    record = record_sent(paths, text, now, project)
    return Sent(text, record, pasted)
