"""
Purpose: Claude Code ``PreToolUse`` hook that refuses any tool call that would
         delete or overwrite an existing file under murmurent's append-only
         roots — ``<data-root>/append_only/`` and the legacy
         ``<data-root>/refined/`` (dual-name transition) — plus every
         registered Obsidian notebook. Creating NEW files and mkdir of missing
         folders is allowed — the lab's versioning convention says "make a new
         file_2.csv, never overwrite file.csv."
Author:  Mike Hallett (with Claude Code)
Date:    2026-05-13
Input:   Tool-call JSON on stdin in the CC hook contract.
Output:  Decision JSON on stdout (``{"decision": "allow"|"deny", ...}``).

The data root is resolved from ``$MURMURENT_DATA_ROOT`` (new canonical name),
falling back to the legacy ``$MURMURENT_LAB_VM_ROOT``. Both the new
``append_only/`` and the legacy ``refined/`` sub-dirs are protected so
un-migrated deployments stay covered.

Sister hook to :mod:`raw_guard` — that one blocks **all** writes under the
immutable tree (``immutable/`` / legacy ``raw/``; strictly read-only). This
hook is more nuanced: under ``append_only/`` and the notebook vault, NEW files
are allowed but overwrites and deletions are not.

What gets blocked:
  - ``Write`` whose ``file_path`` already exists under a protected root
  - ``Edit`` / ``NotebookEdit`` on any path under a protected root
    (both tools modify existing files by definition)
  - ``Bash`` commands that delete, move-out, truncate, chmod/chown,
    or shell-redirect into an existing protected file
  - Append-redirect (``>>``) into a protected path (still modifies)
  - ``mv`` / ``cp`` / ``rsync`` / ``install`` whose destination is an
    existing protected file

What stays allowed:
  - ``Write`` of a new path under a protected root
  - ``mkdir`` / ``mkdir -p`` under a protected root (lab convention is
    folder structure mirrors experiment numbering)
  - Pure reads (``Read``, ``Glob``, ``Grep``) — never touched here
  - Any operation outside the protected roots

Caveats: this is a guardrail, not a security perimeter. A python script
that shells out to ``os.unlink`` will bypass the hook (because the hook
sees only the ``Bash`` invocation, not its child processes). Combine
with filesystem-level read-only mounts in production.
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
APPEND_ONLY_SUBDIR = "append_only"
LEGACY_APPEND_ONLY_SUBDIR = "refined"
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "NotebookEdit"})
DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {"rm", "rmdir", "truncate", "shred", "dd", "chmod", "chown"}
)
COPY_LIKE_COMMANDS: frozenset[str] = frozenset({"cp", "rsync", "install"})


# ---------------------------------------------------------------------------
# Protected-root discovery
# ---------------------------------------------------------------------------


def _refined_prefixes() -> list[str]:
    """Return append-only prefixes covered by this hook.

    Covers both the new ``append_only/`` sub-dir and the legacy ``refined/``
    sub-dir of the configured data root, so a dual-name (partly-migrated)
    deployment stays protected either way. The data root is resolved from
    ``$MURMURENT_DATA_ROOT`` (new), falling back to the legacy
    ``$MURMURENT_LAB_VM_ROOT`` (or the dev default ``~/lab_vm/data``).
    """
    env = os.environ.get("MURMURENT_DATA_ROOT") or os.environ.get("MURMURENT_LAB_VM_ROOT")
    base = Path(env).expanduser() if env else DEFAULT_DATA_ROOT
    prefixes: list[str] = [
        str(base / APPEND_ONLY_SUBDIR),
        str(base / LEGACY_APPEND_ONLY_SUBDIR),
    ]
    return _dedup_prefixes(prefixes)


def _notebook_prefixes() -> list[str]:
    """Return notebook prefixes covered by this hook.

    The write-once scope is the **daily lab-notebook subfolder**
    (``<vault>/<notebook_subfolder>``), NOT the whole Obsidian vault.
    The rest of the vault (recipes, to-dos, project notes, …) is
    freely editable — only the lab-notebook entries are append-only,
    matching the oracle MCP server's notebook tier
    (``oracle_server._safe_notebook_dir``).

    Resolution order:
      1. ``$MURMURENT_NOTEBOOK_ROOT`` — explicit override (one path)
      2. ``<vault>/<notebook_subfolder>`` from per-machine settings
    Both, if both are set. Returns an empty list when neither resolves
    — the hook silently skips notebook protection in that case rather
    than guessing (and never falls back to protecting the vault root).
    """
    out: list[str] = []
    explicit = os.environ.get("MURMURENT_NOTEBOOK_ROOT")
    if explicit:
        out.append(str(Path(explicit).expanduser()))
    try:
        # Lazy import — keeps the hook startup cheap when the murmurent
        # source tree isn't on the importer's path (it always is when
        # invoked via ``python -m murmurent.hooks.protected_paths``, but
        # the test harness may import this module standalone).
        from ..dashboard import machine_settings as _ms
        s = _ms.load()
        vault = (s.obsidian_vault_path or "").strip()
        sub = (s.notebook_subfolder or "").strip()
        # Only protect the notebook *subfolder*. If the subfolder is
        # unset we deliberately protect nothing rather than freezing
        # the entire vault.
        if vault and sub:
            out.append(str(Path(vault).expanduser() / sub))
    except Exception:
        pass  # settings discovery is best-effort — never block on it
    return _dedup_prefixes(out)


def _protected_prefixes() -> list[str]:
    """Union of refined + notebook prefixes."""
    return _dedup_prefixes(_refined_prefixes() + _notebook_prefixes())


def _dedup_prefixes(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        norm = p.rstrip("/")
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _is_protected_path(candidate: str) -> bool:
    """Lexical 'under any protected prefix' check (no symlink chasing)."""
    if not candidate:
        return False
    expanded = str(Path(candidate).expanduser())
    for prefix in _protected_prefixes():
        if expanded == prefix or expanded.startswith(prefix + "/"):
            return True
    return False


def _exists(candidate: str) -> bool:
    """Does this path currently exist as a file or symlink? (Not a dir.)

    Folders are exempt from the "no overwrite" rule by design: the lab
    convention is to mkdir freely (experiments live in `exp/1_name/`,
    `exp/2_name/` etc.) so directories must be re-creatable idempotently.
    """
    try:
        p = Path(candidate).expanduser()
        return p.is_file() or p.is_symlink()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Bash command analysis
# ---------------------------------------------------------------------------


def _bash_violation(command: str) -> str:
    """Return the rejection reason for ``command``, or ``""`` if allowed.

    Conservative: when the parser can't make sense of the command (bad
    quoting, very long pipelines), the hook errs on the side of
    allowing — we'd rather miss a violation than block legitimate work.
    """
    if not command or not command.strip():
        return ""

    redirect_re = re.compile(
        r"(?P<op>>>?|\|\s*tee\b)\s+['\"]?(?P<path>\S+)",
        re.IGNORECASE,
    )
    for match in redirect_re.finditer(command):
        path = match.group("path").strip("'\"")
        op = match.group("op")
        if not _is_protected_path(path):
            continue
        # `>` to existing file = overwrite; `>` to new file = create (ok)
        # `>>` to existing file = append/modify; `>>` to new file = create (ok)
        if _exists(path):
            return f"shell redirect ({op}) would overwrite protected file: {path}"

    try:
        tokens = shlex.split(command, comments=True, posix=True)
    except ValueError:
        # Bad quoting — coarse substring check.
        for prefix in _protected_prefixes():
            if prefix in command and _exists(prefix):
                return f"command references protected prefix: {prefix}"
        return ""

    for i, tok in enumerate(tokens):
        cmd_name = Path(tok).name
        args = tokens[i + 1 :]
        positionals = [a for a in args if not a.startswith("-")]
        if cmd_name in DESTRUCTIVE_COMMANDS:
            # rm/rmdir/truncate/shred/dd/chmod/chown of a protected path
            # is a violation regardless of existence — these always
            # delete or in-place modify.
            for arg in positionals:
                if _is_protected_path(arg):
                    return f"{cmd_name} on protected path: {arg}"
        elif cmd_name == "mv":
            # mv SRC... DEST. Two violations: deleting from protected
            # (any positional except the last under protected) OR
            # overwriting at protected destination (last positional
            # under protected AND that path exists).
            if len(positionals) >= 2:
                *sources, dest = positionals
                for src in sources:
                    if _is_protected_path(src):
                        return f"mv would remove protected file: {src}"
                if _is_protected_path(dest) and _exists(dest):
                    return f"mv would overwrite protected file: {dest}"
        elif cmd_name in COPY_LIKE_COMMANDS:
            # cp/rsync/install write to their last positional. Allow if
            # the destination is new; deny if it would overwrite.
            if positionals:
                dest = positionals[-1]
                if _is_protected_path(dest) and _exists(dest):
                    return f"{cmd_name} would overwrite protected file: {dest}"
    return ""


# ---------------------------------------------------------------------------
# Tool-call evaluation
# ---------------------------------------------------------------------------


def evaluate(call: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a tool-call payload and return the CC hook decision dict."""
    tool = call.get("tool_name") or call.get("tool") or ""
    args = call.get("tool_input") or call.get("args") or {}

    if tool == "Write":
        target = args.get("file_path") or ""
        if _is_protected_path(target) and _exists(target):
            return {
                "decision": "deny",
                "reason": (
                    f"protected path is write-once by lab policy; refusing Write "
                    f"that would overwrite {target}. Use an integer-versioned name "
                    f"(e.g. file_2.csv) instead."
                ),
            }
    elif tool == "Edit":
        target = args.get("file_path") or ""
        if _is_protected_path(target):
            return {
                "decision": "deny",
                "reason": (
                    f"protected path is write-once by lab policy; refusing Edit on "
                    f"{target}. Write a new version-suffixed file instead."
                ),
            }
    elif tool == "NotebookEdit":
        target = args.get("notebook_path") or args.get("file_path") or ""
        if _is_protected_path(target):
            return {
                "decision": "deny",
                "reason": (
                    f"notebook is write-once by lab policy; refusing NotebookEdit on "
                    f"{target}. Append a new dated entry instead of editing existing ones."
                ),
            }
    elif tool == "Bash":
        reason = _bash_violation(args.get("command", ""))
        if reason:
            return {
                "decision": "deny",
                "reason": f"protected path is write-once by lab policy; {reason}",
            }
    return {"decision": "allow"}


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    """Read tool-call JSON from stdin, write decision JSON to stdout.

    CC modern protocol: empty stdout = allow; deny uses
    hookSpecificOutput. See raw_guard.main for the rationale.
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
