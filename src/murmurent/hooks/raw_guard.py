"""
Purpose: Claude Code ``PreToolUse`` hook that refuses any tool call that would
         mutate files under the immutable data tree — ``<data-root>/immutable/``
         and the legacy ``<data-root>/raw/`` (dual-name transition). Read / Glob
         / Grep are explicitly allowed; the lab's data-storage rule is
         "immutable data is read-only, ever."
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Tool-call JSON on stdin in the CC hook contract.
Output: Decision JSON on stdout (``{"decision": "allow"|"deny", ...}``).

Standalone script: invoked as ``python -m murmurent.hooks.raw_guard`` from
``~/.claude/settings.json``.

The data root is resolved from ``$MURMURENT_DATA_ROOT`` (new canonical name),
falling back to the legacy ``$MURMURENT_LAB_VM_ROOT``. Both the new
``immutable/`` and the legacy ``raw/`` sub-dirs are blocked so un-migrated
deployments stay protected.

The hook is permissive by design: it only refuses obvious mutations (Write /
Edit / NotebookEdit targeting immutable data, plus Bash commands containing
redirects or destructive operations on those paths). Subtle attacks (a Python
script that shells out to ``os.unlink``) are out of scope; this is a guardrail,
not a security perimeter.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import IO, Any

DEFAULT_DATA_ROOT = Path("~/lab_vm/data").expanduser()
IMMUTABLE_SUBDIR = "immutable"
LEGACY_IMMUTABLE_SUBDIR = "raw"
DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {"rm", "mv", "tee", "dd", "chmod", "chown", "truncate", "shred"}
)
COPY_COMMANDS: frozenset[str] = frozenset({"cp", "rsync", "install"})
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "NotebookEdit"})


def _data_root() -> Path:
    """Resolve the data root from the env, honouring both spellings.

    Prefers ``$MURMURENT_DATA_ROOT``; falls back to the legacy
    ``$MURMURENT_LAB_VM_ROOT``; then the dev default ``~/lab_vm/data``.
    """
    env = os.environ.get("MURMURENT_DATA_ROOT") or os.environ.get("MURMURENT_LAB_VM_ROOT")
    return Path(env).expanduser() if env else DEFAULT_DATA_ROOT


def _raw_prefixes() -> tuple[str, ...]:
    """Return the set of path prefixes that count as 'immutable'.

    Covers both the new ``immutable/`` sub-dir and the legacy ``raw/`` sub-dir
    of the configured data root, so a dual-name (partly-migrated) deployment
    stays protected either way.
    """
    base = _data_root()
    prefixes: list[str] = [
        str(base / IMMUTABLE_SUBDIR),
        str(base / LEGACY_IMMUTABLE_SUBDIR),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in prefixes:
        norm = p.rstrip("/")
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return tuple(out)


def _is_raw_path(candidate: str) -> bool:
    """Return True if ``candidate`` (lexically) lives under any raw prefix."""
    if not candidate:
        return False
    expanded = str(Path(candidate).expanduser())
    for prefix in _raw_prefixes():
        if expanded == prefix or expanded.startswith(prefix + "/"):
            return True
    return False


def _bash_targets_raw(command: str) -> tuple[bool, str]:
    """Inspect a bash command line for raw-mutating operations.

    Returns ``(is_violation, reason)``.
    """
    if not command:
        return False, ""

    raw_prefixes = _raw_prefixes()
    redirect_re = re.compile(
        r"(?:>>?|\|\s*tee\b)\s+['\"]?(\S+)",
        re.IGNORECASE,
    )
    for match in redirect_re.finditer(command):
        target = match.group(1).strip("'\"")
        if _is_raw_path(target):
            return True, f"shell redirect into raw path: {target}"

    try:
        tokens = shlex.split(command, comments=True, posix=True)
    except ValueError:
        # Unbalanced quotes etc. - fall back to a coarse substring check.
        for prefix in raw_prefixes:
            if prefix in command:
                return True, f"command references raw prefix: {prefix}"
        return False, ""

    for i, tok in enumerate(tokens):
        cmd_name = Path(tok).name
        if cmd_name in DESTRUCTIVE_COMMANDS:
            for arg in tokens[i + 1 :]:
                if _is_raw_path(arg):
                    return True, f"{cmd_name} on raw path: {arg}"
        elif cmd_name in COPY_COMMANDS:
            # cp / rsync write to their last positional argument; skip flags.
            args_only = [a for a in tokens[i + 1 :] if not a.startswith("-")]
            if args_only and _is_raw_path(args_only[-1]):
                return True, f"{cmd_name} writes into raw path: {args_only[-1]}"

    return False, ""


def evaluate(call: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a tool-call payload and return the decision dict.

    Decision shape mirrors the CC hook contract:
        {"decision": "deny", "reason": "..."}
        {"decision": "allow"}
    """
    tool = call.get("tool_name") or call.get("tool") or ""
    args = call.get("tool_input") or call.get("args") or {}

    if tool in WRITE_TOOLS:
        target = args.get("file_path") or args.get("notebook_path") or ""
        if _is_raw_path(target):
            return {
                "decision": "deny",
                "reason": (
                    f"immutable data is read-only by lab policy; refusing {tool} on {target}"
                ),
            }
    elif tool == "Bash":
        violated, reason = _bash_targets_raw(args.get("command", ""))
        if violated:
            return {
                "decision": "deny",
                "reason": f"immutable data is read-only by lab policy; {reason}",
            }
    return {"decision": "allow"}


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    """Read tool-call JSON from stdin, write the decision to stdout.

    CC's modern hook protocol: empty stdout = "no opinion, proceed".
    Block decisions use the hookSpecificOutput shape. (The legacy
    ``{"decision": "allow"}`` form is no longer accepted and trips
    CC's schema validator; that was the source of every "Hook JSON
    output validation failed" line in fresh CC sessions.)
    """
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw_text = src.read()
    if not raw_text.strip():
        return 0
    try:
        call = json.loads(raw_text)
    except json.JSONDecodeError:
        return 0
    decision = evaluate(call if isinstance(call, dict) else {})
    if decision.get("decision") == "deny":
        dst.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.get("reason", ""),
            },
        }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
