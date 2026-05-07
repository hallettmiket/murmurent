"""
Purpose: ``PostToolUse`` hook that appends one jsonl row per tool call to
         ``~/.claude/wigamig-audit/YYYY-MM-DD.log``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: PostToolUse payload JSON on stdin.
Output: ``{"decision": "allow"}`` (the hook is observation-only).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import IO, Any

from ..core.identity import resolve as resolve_identity
from ..core.repo import find_project_repo

DEFAULT_LOG_DIR = Path("~/.claude/wigamig-audit").expanduser()
ENV_LOG_DIR = "WIGAMIG_AUDIT_LOG_DIR"
MAX_ARGS_SUMMARY = 200


def _log_dir() -> Path:
    return Path(os.environ.get(ENV_LOG_DIR, DEFAULT_LOG_DIR)).expanduser()


def _summarise_args(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, str):
        s = args
    else:
        try:
            s = json.dumps(args, default=str)
        except (TypeError, ValueError):
            s = str(args)
    if len(s) > MAX_ARGS_SUMMARY:
        s = s[: MAX_ARGS_SUMMARY - 1] + "…"
    return s


def _project_name(start: str | None = None) -> str | None:
    repo = find_project_repo(start or os.getcwd())
    return repo.path.name if repo is not None else None


def write_entry(payload: dict[str, Any], *, log_dir: Path | None = None) -> Path:
    """Write the audit row for ``payload``. Returns the log path."""
    log_dir = log_dir or _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    log_path = log_dir / f"{today}.log"

    identity = resolve_identity(allow_unknown=True)
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "member": identity.at_handle,
        "project": _project_name(),
        "tool": payload.get("tool_name") or payload.get("tool"),
        "args_summary": _summarise_args(payload.get("tool_input") or payload.get("args")),
        "outcome": str(payload.get("outcome") or payload.get("status") or "ok"),
        "duration_ms": payload.get("duration_ms"),
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return log_path


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw = src.read()
    if not raw.strip():
        dst.write(json.dumps({"decision": "allow"}))
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        dst.write(json.dumps({"decision": "allow"}))
        return 0
    if isinstance(payload, dict):
        try:
            write_entry(payload)
        except Exception:
            # Audit must never block the call; log silently and continue.
            pass
    dst.write(json.dumps({"decision": "allow"}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
