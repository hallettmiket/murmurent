"""
Purpose: Keep the personal vault in step with GitHub from inside Claude Code,
         without anyone pressing a button: bring in the other machines' notes
         when a session starts, and send this machine's as soon as a session
         changes one.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-19
Input: Claude Code hook events on stdin (SessionStart, PostToolUse, Stop).
Output: A background ``core.vault_sync.sync``; one line per sync in
        ``~/.murmurent/vault_sync.log``. Prints nothing (a SessionStart hook's
        output would be added to the session), and always exits 0.

When each event syncs:

- **SessionStart**: syncs and waits up to :data:`START_WAIT_SECONDS`, so the
  session normally starts with the latest notes. A slow network does not hold
  the session up; the sync finishes in the background.
- **PostToolUse** (Write, Edit, NotebookEdit, the Oracle's tools): syncs in the
  background when the file written is inside the vault.
- **Stop** (the end of each reply): syncs in the background when the vault has
  changes not yet sent, which catches notes written any other way.

Notes marked protected or restricted are never sent (``core.vault_sync``).
Edits typed in Obsidian are not seen by Claude Code; the dashboard sends those
when it starts and every 15 minutes, and its Sync vault button sends them at
once.

``MURMURENT_NO_VAULT_SYNC=1`` turns all of this off.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: How long a session start waits for the vault to come in.
START_WAIT_SECONDS = 10
#: Tools whose writes may land in the vault.
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
ORACLE_TOOL_PREFIX = "mcp__murmurent-oracle__"


def _state_dir() -> Path:
    home = Path(os.environ.get("MURMURENT_HOME", "~/.murmurent")).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home


def _vault_root() -> Path | None:
    from ..core import vault_sync as _vs
    root = _vs.personal_vault_root()
    return root if root is not None and (root / ".git").exists() else None


def _inside(path: str, root: Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _has_changes(root: Path) -> bool:
    try:
        res = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(res.stdout.strip())


def _spawn_worker() -> subprocess.Popen | None:
    """Start the sync in its own process, so it outlives this hook."""
    try:
        return subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "murmurent.hooks.vault_sync", "--worker"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None


def run_worker() -> None:
    """Sync once, then again while more changes arrived during the sync.

    One worker at a time: a second worker started meanwhile leaves a
    ``pending`` mark and exits, and the running one picks it up.
    """
    from ..core import vault_sync as _vs
    state = _state_dir()
    pending = state / "vault_sync.pending"
    pending.touch()
    with open(state / "vault_sync.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for _ in range(5):
            if not pending.exists():
                break
            pending.unlink(missing_ok=True)
            result = _vs.sync("vault sync (Claude Code)")
            with open(state / "vault_sync.log", "a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {result.message}\n")


def handle(event: dict) -> None:
    """Decide whether this hook event should sync, and start it."""
    if os.environ.get("MURMURENT_NO_VAULT_SYNC"):
        return
    root = _vault_root()
    if root is None:
        return
    name = event.get("hook_event_name", "")
    if name == "SessionStart":
        proc = _spawn_worker()
        if proc is not None:
            try:
                proc.wait(timeout=START_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass  # finishes in the background
        return
    if name == "PostToolUse":
        tool = event.get("tool_name", "")
        target = (event.get("tool_input") or {}).get("file_path") or \
                 (event.get("tool_input") or {}).get("notebook_path") or ""
        if (tool in WRITE_TOOLS and target and _inside(target, root)) or \
                tool.startswith(ORACLE_TOOL_PREFIX):
            _spawn_worker()
        return
    if name == "Stop" and _has_changes(root):
        _spawn_worker()


def main() -> int:
    if "--worker" in sys.argv:
        try:
            run_worker()
        except Exception:  # noqa: BLE001 - a background sync must never surface
            pass
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    try:
        handle(event)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
