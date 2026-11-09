"""
Purpose: The language agents speak their verdicts in, per machine (#279).
         Reads the language table out of the agent-event hook, and reads and
         writes the ``language`` line of ``~/.murmurent/speak``.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-05
Input:  ``~/.murmurent/speak`` (``$MURMURENT_SPEAK_FILE``) and
        ``scripts/murmurent_log_agent_event.sh`` in the commons.
Output: the ``language`` (and optional ``voice``) line of the speak file.

The hook is the one place the table lives: it needs it at speaking time, and
it is bash, so this module parses the table from the script rather than
keeping a second copy that could drift. ``tests/test_spoken_language.py``
checks that this parse and the installer's agree.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .commons import commons_root

_ROW = re.compile(r'^\s+([a-z]{2}_[A-Z]{2})\)\s+echo "([^"|]+)\|([^"|]+)\|([^"|]+)"')
_ENGLISH = {"", "en", "english"}


@dataclass(frozen=True)
class Language:
    code: str          # Piper language code, e.g. fr_FR
    name: str          # English name, what the agent is told to write in
    piper_voice: str   # the Piper voice every agent shares in this language
    say_voice: str     # the Mac `say` voice shipped for it


def speak_file() -> Path:
    return Path(os.environ.get("MURMURENT_SPEAK_FILE") or Path.home() / ".murmurent" / "speak")


def hook_script() -> Path:
    return commons_root() / "scripts" / "murmurent_log_agent_event.sh"


def languages(script: Path | None = None) -> list[Language]:
    """The languages the hook knows a voice for, in the hook's own order."""
    text = (script or hook_script()).read_text(encoding="utf-8")
    body = text.split("language_voice()", 1)[1].split("\n}", 1)[0]
    out = []
    for line in body.splitlines():
        m = _ROW.match(line)
        if m:
            out.append(Language(*m.groups()))
    return out


def is_english(code: str) -> bool:
    c = code.strip()
    return c.lower() in _ENGLISH or c.startswith("en_")


def _setting(lines: list[str], key: str) -> str:
    val = ""
    for line in lines:
        m = re.match(rf"^\s*{key}\s+(.*?)\s*$", line)
        if m:
            val = m.group(1)
    return val


def current(path: Path | None = None) -> tuple[str, str]:
    """``(language code, voice)`` from the speak file; ``("", "")`` means English."""
    p = path or speak_file()
    if not p.is_file():
        return "", ""
    lines = p.read_text(encoding="utf-8").splitlines()
    lang = _setting(lines, "language")
    if is_english(lang):
        return "", ""
    return lang, _setting(lines, "voice")


def set_language(code: str, voice: str = "", path: Path | None = None) -> Path:
    """Write the ``language`` line (and ``voice``, when given), replacing any
    earlier ones. English removes both, so the per-agent English voices are
    back. The rest of the file (engine, speed, per-agent lines) is kept."""
    p = path or speak_file()
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    keep = [l for l in lines if not re.match(r"^\s*(language|voice)\s+", l)]
    if not is_english(code):
        keep.append(f"language {code.strip()}")
        if voice.strip():
            keep.append(f"voice {voice.strip()}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return p
