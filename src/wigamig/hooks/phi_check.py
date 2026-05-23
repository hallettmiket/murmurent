"""
Purpose: PHI pattern detection hook for Claude Code. Active *only* when the
         current project's CHARTER is ``sensitivity: clinical``. Pre-call: refuses
         outbound prompts containing PHI-shaped patterns. Post-call: redacts
         matches in the returned content.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Tool-call (PreToolUse) or tool-result (PostToolUse) JSON on stdin.
Output: Decision JSON ({"decision": "allow"|"deny", ...}) or modified result
        JSON ({"decision": "modify", "tool_response": {...}}) on stdout.

Run as ``python -m wigamig.hooks.phi_check``. The phase-4 ``wigamig install --hooks``
registers it under ``PreToolUse`` and ``PostToolUse`` matchers in
``~/.claude/settings.json``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import IO, Any

from ..core.charter import validate_charter
from ..core.frontmatter import parse_file
from ..core.repo import find_project_repo

REDACTION = "[REDACTED-PHI]"

# Patterns kept conservative — favour false-positives over silent leakage.
PHI_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OHIP", re.compile(r"\b\d{4}[ -]\d{3}[ -]\d{3}(?:[ -]?[A-Z]{1,2})?\b")),
    ("MRN", re.compile(r"\bMRN[-_ ]\w{4,}\b", re.IGNORECASE)),
    ("SIN", re.compile(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b")),
]
NAME_LIKE = re.compile(r"\b[A-Z][a-z]{2,}\b")
DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DOB_NEAR_NAME_WINDOW = 50

OUTBOUND_TOOLS: frozenset[str] = frozenset({"WebFetch", "WebSearch", "Bash"})
OUTBOUND_BASH_HEADS: frozenset[str] = frozenset(
    {"curl", "wget", "ssh", "scp", "rsync", "http", "httpie"}
)


def _is_clinical_project(start: str | None = None) -> bool:
    repo = find_project_repo(start or os.getcwd())
    if repo is None:
        return False
    try:
        parsed = parse_file(repo.charter_path)
        validate_charter(parsed.meta, context=str(repo.charter_path))
    except Exception:
        return False
    return parsed.meta.get("sensitivity") == "clinical"


def _bash_is_outbound(command: str) -> bool:
    if not command:
        return False
    head = command.strip().split()[0] if command.strip() else ""
    if "/" in head:
        head = head.rsplit("/", 1)[-1]
    return head in OUTBOUND_BASH_HEADS


def _pattern_hits(text: str) -> list[tuple[str, str]]:
    """Return (label, match_text) for every PHI hit in ``text``."""
    hits: list[tuple[str, str]] = []
    if not text:
        return hits
    for label, pattern in PHI_PATTERNS:
        for m in pattern.finditer(text):
            hits.append((label, m.group(0)))
    # DOB-near-name: a date and a name-shape within 50 chars.
    for date_match in DATE_LIKE.finditer(text):
        start, end = date_match.span()
        window_start = max(0, start - DOB_NEAR_NAME_WINDOW)
        window_end = min(len(text), end + DOB_NEAR_NAME_WINDOW)
        window = text[window_start:window_end]
        if NAME_LIKE.search(window):
            hits.append(("DOB-near-name", date_match.group(0)))
    return hits


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_flatten(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    return str(value)


def _redact(text: str) -> str:
    out = text
    for _label, pattern in PHI_PATTERNS:
        out = pattern.sub(REDACTION, out)
    return out


# ---------------------------------------------------------------------------
# Pre / Post evaluators
# ---------------------------------------------------------------------------


def evaluate_pre(call: dict[str, Any]) -> dict[str, Any]:
    """Decide on a PreToolUse call: deny if outbound + PHI-shaped + clinical."""
    if not _is_clinical_project():
        return {"decision": "allow"}
    tool = call.get("tool_name") or call.get("tool") or ""
    args = call.get("tool_input") or call.get("args") or {}

    # MCP outbound channels (slack post, etc.) by name pattern.
    is_outbound = (
        tool in OUTBOUND_TOOLS
        or tool.startswith("mcp__slack__")
        or tool.startswith("mcp__claude_ai_Slack__")
    )
    if tool == "Bash":
        is_outbound = _bash_is_outbound(args.get("command", ""))
    if not is_outbound:
        return {"decision": "allow"}

    text = _flatten(args)
    hits = _pattern_hits(text)
    if not hits:
        return {"decision": "allow"}
    labels = sorted({h[0] for h in hits})
    return {
        "decision": "deny",
        "reason": (
            f"PHI hook: refusing outbound {tool} with {', '.join(labels)} pattern(s). "
            f"Active project is clinical-tier; de-identify before retrying."
        ),
    }


def evaluate_post(payload: dict[str, Any]) -> dict[str, Any]:
    """Decide on a PostToolUse result: redact PHI in the response."""
    if not _is_clinical_project():
        return {"decision": "allow"}
    response = payload.get("tool_response") or payload.get("response") or payload.get("result")
    text = _flatten(response)
    hits = _pattern_hits(text)
    if not hits:
        return {"decision": "allow"}
    redacted = _redact(text)
    return {
        "decision": "modify",
        "tool_response": redacted,
        "reason": f"PHI hook: redacted {len(hits)} match(es) of {sorted({h[0] for h in hits})!r}.",
    }


def main(
    stdin: IO[str] | None = None, stdout: IO[str] | None = None, mode: str | None = None
) -> int:
    """Read stdin, write the decision JSON to stdout.

    ``mode`` is ``"pre"`` (default) or ``"post"``. Inferred from
    ``$WIGAMIG_PHI_HOOK_MODE`` when not passed. The shipped install registers
    two hook entries — one per mode — pointing at this same module.
    """
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    if mode is None:
        mode = os.environ.get("WIGAMIG_PHI_HOOK_MODE", "pre").lower()

    raw = src.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate_post(payload) if mode == "post" else evaluate_pre(payload)
    dec = decision.get("decision")
    if dec == "deny":
        event = "PostToolUse" if mode == "post" else "PreToolUse"
        dst.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.get("reason", ""),
            },
        }))
    elif dec == "modify" and mode == "post" and "tool_response" in decision:
        # PHI redaction on the response — emit modern PostToolUse
        # additionalContext (the tool already ran; this is feedback to
        # the model that the response was redacted).
        dst.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": decision.get("reason", "PHI redacted"),
            },
        }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
