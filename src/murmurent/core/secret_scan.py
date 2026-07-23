"""
Purpose: Deterministic, regex-based secret-CONTENT scanner. Complements the
         filename-only checks in ``scripts/murmurent_sec_scan.sh`` and the
         LLM path in ``core.security_agent_review`` by catching hardcoded
         credentials inside file *bodies* (``.py``/``.R``/``.yaml``/…) before
         they reach GitHub.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-23
Input: text / file paths / a git repo root (for staged-content scanning).
Output: ``list[SecretHit]`` — each with a REDACTED match, never the raw secret.

Design notes:

- **Read-only, side-effect free.** The scanner only reads; it never writes,
  moves, or pushes. It is safe to run as a mandatory pre-push gate.
- **Never emit a raw secret.** Every :class:`SecretHit` carries only a
  ``redacted`` form (middle masked). The full match is discarded after
  redaction; nothing here ever prints or returns the unmasked value.
- **Two severities.** ``block`` = high-confidence structured tokens (AWS/GitHub/
  Slack/Google keys, PEM private-key blocks). ``warn`` = a heuristic
  "secret-looking assignment" that may be a false positive.
- **Placeholder suppression.** Obvious non-secrets (``your-key-here``,
  ``${VAR}``, ``os.environ[...]``, all-repeated chars, …) are dropped, and an
  inline ``# pragma: allowlist secret`` / ``# noqa: secret`` comment suppresses
  a match on that line.
- **Staged scanning.** :func:`scan_staged` scans the STAGED blob content
  (``git show :<path>``), i.e. exactly what a push would publish — not the
  working tree, which may differ from the index.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"

# Skip files bigger than this (bytes); a real secret is small, big files are
# usually data/binaries and scanning them wastes time.
MAX_FILE_BYTES = 512 * 1024

# Inline suppression comments (case-insensitive).
_ALLOWLIST_RE = re.compile(r"(?i)#\s*(pragma:\s*allowlist\s+secret|noqa:\s*secret)")

# Tokens that mark a value as an obvious placeholder / indirection, not a real
# secret. If a matched value contains any of these (case-insensitive), skip it.
_PLACEHOLDER_TOKENS = (
    "example",
    "placeholder",
    "dummy",
    "changeme",
    "your-",
    "your_",
    "xxxx",
    "<",
    "${",
    "os.environ",
    "getenv",
    "redacted",
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecretHit:
    """One detected (redacted) secret occurrence.

    ``redacted`` is the only representation of the matched text — the raw
    secret is never stored here or emitted anywhere.
    """

    path: str
    line: int  # 1-indexed
    rule: str
    severity: str  # SEVERITY_BLOCK | SEVERITY_WARN
    redacted: str
    hint: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "severity": self.severity,
            "redacted": self.redacted,
            "hint": self.hint,
        }


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def redact(secret: str) -> str:
    """Mask the middle of ``secret`` so provenance is visible but the value
    is not recoverable. Short strings collapse to all-asterisks.

    e.g. ``AKIAIOSFODNN7EXAMPLE`` -> ``AKIA…MPLE``.
    """
    s = secret.strip()
    if len(s) <= 8:
        return "*" * len(s)
    keep = 4
    return f"{s[:keep]}…{s[-keep:]}"


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
# Each high-confidence detector is (rule_id, compiled_regex, hint). The regex
# match's group(0) is the sensitive span.

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
)

_BLOCK_DETECTORS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "PRIVATE-KEY-BLOCK",
        _PRIVATE_KEY_RE,
        "Inline private key block — never commit key material.",
    ),
    (
        "AWS-ACCESS-KEY-ID",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key id — rotate it and use a credentials file / env var.",
    ),
    (
        "GITHUB-PAT-CLASSIC",
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
        "GitHub personal access token (classic) — revoke and use a secret store.",
    ),
    (
        "GITHUB-TOKEN",
        re.compile(r"\b(?:gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"),
        "GitHub OAuth/app/refresh token — revoke and use a secret store.",
    ),
    (
        "GITHUB-PAT-FINEGRAINED",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
        "GitHub fine-grained PAT — revoke and use a secret store.",
    ),
    (
        "SLACK-TOKEN",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        "Slack token — rotate it; load from env / config, never inline.",
    ),
    (
        "GOOGLE-API-KEY",
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        "Google API key — restrict/rotate it; load from a secret store.",
    ),
)

# Heuristic (warn): a secret-looking assignment. The quoted value is captured
# as group "val".
_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|access[_-]?key|password|passwd|client[_-]?secret)"
    r"\s*[:=]\s*['\"](?P<val>[^'\"]{8,})['\"]"
)


def _is_placeholder(value: str) -> bool:
    """True if ``value`` looks like a placeholder / indirection, not a real
    secret."""
    low = value.lower()
    if any(tok in low for tok in _PLACEHOLDER_TOKENS):
        return True
    # All-repeated single character (e.g. "aaaaaaaa", "********").
    stripped = value.strip()
    if stripped and len(set(stripped)) == 1:
        return True
    return False


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------

def scan_text(text: str, path: str) -> list[SecretHit]:
    """Scan ``text`` for secrets, attributing hits to ``path``.

    Never returns raw secret material — only redacted spans.
    """
    hits: list[SecretHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _ALLOWLIST_RE.search(line):
            # Explicit inline suppression on this line.
            continue

        # High-confidence structured detectors -> block.
        for rule, pattern, hint in _BLOCK_DETECTORS:
            m = pattern.search(line)
            if not m:
                continue
            span = m.group(0)
            hits.append(
                SecretHit(
                    path=path,
                    line=lineno,
                    rule=rule,
                    severity=SEVERITY_BLOCK,
                    redacted=redact(span),
                    hint=hint,
                )
            )

        # Heuristic secret-looking assignment -> warn (unless placeholder).
        am = _ASSIGNMENT_RE.search(line)
        if am:
            value = am.group("val")
            if not _is_placeholder(value):
                hits.append(
                    SecretHit(
                        path=path,
                        line=lineno,
                        rule="GENERIC-SECRET-ASSIGNMENT",
                        severity=SEVERITY_WARN,
                        redacted=redact(value),
                        hint="Secret-looking literal — load from env/secret store, "
                        "or add `# pragma: allowlist secret` if a false positive.",
                    )
                )
    return hits


def _looks_binary(data: bytes) -> bool:
    """Heuristic: a NUL byte in the first chunk means binary."""
    return b"\x00" in data[:8192]


def scan_file(path: str | Path) -> list[SecretHit]:
    """Scan a single file. Skips binary files and files > ``MAX_FILE_BYTES``.

    Missing/unreadable files return an empty list (read-only; never raises for
    normal I/O trouble).
    """
    p = Path(path)
    try:
        if not p.is_file():
            return []
        if p.stat().st_size > MAX_FILE_BYTES:
            return []
        data = p.read_bytes()
    except OSError:
        return []
    if _looks_binary(data):
        return []
    text = data.decode("utf-8", errors="replace")
    return scan_text(text, str(path))


def scan_paths(paths) -> list[SecretHit]:
    """Scan a collection of paths. Directories are walked recursively; files
    are scanned directly."""
    hits: list[SecretHit] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file():
                    hits.extend(scan_file(sub))
        else:
            hits.extend(scan_file(p))
    return hits


# ---------------------------------------------------------------------------
# Git-staged scanning
# ---------------------------------------------------------------------------

def _git(repo_root: str | Path, args: list[str], *, binary: bool = False):
    """Run a git command in ``repo_root``. Returns stdout (str or bytes)."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return b"" if binary else ""
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def staged_paths(repo_root: str | Path) -> list[str]:
    """Repo-relative paths staged for commit (added/copied/modified/renamed).

    Deletions are excluded — a deleted file cannot leak a secret upward.
    """
    out = _git(
        repo_root,
        ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
    )
    return [p for p in out.split("\0") if p]


def scan_staged(repo_root: str | Path) -> list[SecretHit]:
    """Scan the STAGED content of a repo — exactly what a push would publish.

    Reads each staged blob via ``git show :<path>`` (the index version), NOT
    the working tree, so a secret only present in the working tree but not
    staged is correctly ignored.
    """
    hits: list[SecretHit] = []
    for rel in staged_paths(repo_root):
        blob = _git(repo_root, ["show", f":{rel}"], binary=True)
        if not blob:
            continue
        if len(blob) > MAX_FILE_BYTES:
            continue
        if _looks_binary(blob):
            continue
        text = blob.decode("utf-8", errors="replace")
        hits.extend(scan_text(text, rel))
    return hits


__all__ = [
    "SecretHit",
    "SEVERITY_BLOCK",
    "SEVERITY_WARN",
    "redact",
    "scan_text",
    "scan_file",
    "scan_paths",
    "scan_staged",
    "staged_paths",
]
