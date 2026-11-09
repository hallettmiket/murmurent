"""
Purpose: Claude Code ``PostToolUse`` hook that notices when a commons agent's
         file (``agents/<x>.md``) was just edited and reminds the session, once,
         that the agent's training movie was checked against an older version
         of that file (issue #288). It prompts; it never blocks and never
         renders anything itself.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   PostToolUse tool-call JSON on stdin (CC hook contract): the tool name,
         its input (``file_path``) and the session id.
Output:  Empty stdout on the quiet path; ``hookSpecificOutput`` with
         ``additionalContext`` the first time in a session that a given agent's
         file changes and its movie is stamped with another version of it.

What it reads: ``training/index.yaml`` in the commons root, one entry per movie
with the agent, the version and date it was checked against, and the sha256 of
the agent file at that moment. If the file's hash now differs from the stamp,
the movie shows an older agent. A file whose hash still matches (an edit that
was undone, or a whitespace-only save that CC reports anyway) is left alone.

Once per session: a marker under ``~/.murmurent/agent_movie_prompted/<session>/``
(or ``$MURMURENT_HOME``) records which agents have been mentioned, so a session
that edits ``agents/oracle.md`` twenty times hears about the movie once.

Failure policy: never block, never raise. A missing index, an unreadable file
or a strange payload costs the reminder, nothing else.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import IO, Any

INDEX_PARTS = ("training", "index.yaml")
AGENT_FILE = re.compile(r"(?:^|/)agents/([A-Za-z0-9_]+)\.md$")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def commons_root() -> Path:
    try:
        from ..core.commons import commons_root as _root
        return _root()
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return Path(__file__).resolve().parents[3]


def prompted_dir(session: str) -> Path:
    base = os.environ.get("MURMURENT_HOME")
    root = Path(base).expanduser() if base else Path("~/.murmurent").expanduser()
    return root / "agent_movie_prompted" / (session or "no-session")


def parse_index(text: str) -> dict[str, dict[str, str]]:
    """The movie entries of training/index.yaml, by agent. The file is a plain list
    written by training/lib/agent_movie.py, so a small line parser is enough and
    the hook does not need a yaml library at session time."""
    movies: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        m = re.match(r"^- agent:\s*(\S+)\s*$", line)
        if m:
            cur = {"agent": m.group(1)}
            movies[m.group(1)] = cur
            continue
        if line.startswith("- ") or re.match(r"^\w+:\s*$", line):
            cur = None          # a `videos:` or `news:` entry, not a movie
            continue
        m = re.match(r"^  (\w+):\s*(.*?)\s*$", line)
        if m and cur is not None and m.group(2):
            cur[m.group(1)] = m.group(2)
    return movies


def agent_of(call: dict[str, Any]) -> str | None:
    if call.get("tool_name") not in WRITE_TOOLS:
        return None
    tool_input = call.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    m = AGENT_FILE.search(str(path).replace("\\", "/"))
    return m.group(1) if m else None


def evaluate(call: dict[str, Any], root: Path | None = None) -> str | None:
    """The reminder text, or None when there is nothing to say."""
    agent = agent_of(call)
    if not agent:
        return None
    root = root or commons_root()
    index = root.joinpath(*INDEX_PARTS)
    agent_path = root / "agents" / f"{agent}.md"
    if not index.is_file() or not agent_path.is_file():
        return None
    entry = parse_index(index.read_text(encoding="utf-8")).get(agent)
    if not entry:
        return None
    now = hashlib.sha256(agent_path.read_bytes()).hexdigest()
    if entry.get("agent_sha256") == now:
        return None
    marker_dir = prompted_dir(str(call.get("session_id") or ""))
    marker = marker_dir / agent
    if marker.exists():
        return None
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(now, encoding="utf-8")
    except OSError:
        pass
    make = entry.get("make") or f"python3 training/agents/{agent}/make.py"
    return (f"agents/{agent}.md changed; its movie was checked against "
            f"{entry.get('version', '?')} ({entry.get('date', '?')}); re-render it? `{make}` "
            "(training/README.md, \"When a movie goes out of date\").")


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw = src.read()
    if not raw.strip():
        return 0
    try:
        call = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    try:
        note = evaluate(call if isinstance(call, dict) else {})
    except Exception:  # noqa: BLE001
        return 0
    if note:
        dst.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                     "additionalContext": note}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
