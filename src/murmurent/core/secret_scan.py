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
import time
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"
# ``info`` is used only for non-secret bookkeeping rows (e.g. a history-scan
# truncation notice). It is never counted as a block/warn hit by the CLI, so it
# does not affect the exit-code contract.
SEVERITY_INFO = "info"

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
    severity: str  # SEVERITY_BLOCK | SEVERITY_WARN | SEVERITY_INFO
    redacted: str
    hint: str
    commit: str = ""  # commit-ish when the hit came from a history walk; else ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "severity": self.severity,
            "redacted": self.redacted,
            "hint": self.hint,
            "commit": self.commit,
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

def scan_line(line: str, path: str, lineno: int, *,
              commit: str = "") -> list[SecretHit]:
    """Scan a SINGLE line for secrets. Shared by :func:`scan_text` (whole-file)
    and :func:`scan_history` (per added diff line), so both paths use exactly
    the same detectors, placeholder/pragma suppression, and redaction.

    ``commit`` is stamped onto each hit when the line came from history.
    Never returns raw secret material — only redacted spans.
    """
    if _ALLOWLIST_RE.search(line):
        # Explicit inline suppression on this line.
        return []
    hits: list[SecretHit] = []

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
                commit=commit,
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
                    commit=commit,
                )
            )
    return hits


def scan_text(text: str, path: str) -> list[SecretHit]:
    """Scan ``text`` for secrets, attributing hits to ``path``.

    Never returns raw secret material — only redacted spans.
    """
    hits: list[SecretHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        hits.extend(scan_line(line, path, lineno))
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


# ---------------------------------------------------------------------------
# Git-history scanning (bounded)
# ---------------------------------------------------------------------------
#
# Walks reachable commit history (HEAD-first) and scans the ADDED lines of each
# commit's diff, so a secret that was committed and later deleted is still
# found (scanning only the current tree would miss it). Reuses the same
# per-line detectors + redaction as the working-tree/staged scanners.
#
# BOUNDED by construction: it stops after ``max_commits`` commits OR
# ``max_seconds`` of wall time, whichever comes first, and appends a single
# ``HISTORY-SCAN-TRUNCATED`` info row (never a secret) when it did so, so the
# caller can tell the difference between "clean" and "ran out of budget".

# The rule id for the (non-secret) truncation notice.
HISTORY_TRUNCATED_RULE = "HISTORY-SCAN-TRUNCATED"

# Defaults keep a standalone ``secrets-scan --history`` responsive; the personal
# audit passes tighter bounds so ``audit-me`` stays a few seconds.
DEFAULT_HISTORY_MAX_COMMITS = 500
DEFAULT_HISTORY_MAX_SECONDS = 8.0

# Commit-boundary sentinel: git prints ``\x01<full-sha>`` (SOH byte) at the
# start of the line for each commit. A real diff line never starts with \x01.
_COMMIT_SENTINEL = "\x01"
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def scan_history(
    repo_root: str | Path,
    *,
    max_commits: int = DEFAULT_HISTORY_MAX_COMMITS,
    max_seconds: float = DEFAULT_HISTORY_MAX_SECONDS,
) -> list[SecretHit]:
    """Scan the ADDED lines across reachable commit history for secrets.

    Deterministic within its budget: walks ``git log`` newest-first, parsing a
    ``-U0`` patch and scanning every added (``+``) line. Each hit records the
    file, the 1-indexed line in that commit's version, and the commit-ish — all
    redacted. Stops at ``max_commits`` / ``max_seconds`` and, if it stopped
    early, appends one ``HISTORY-SCAN-TRUNCATED`` info row.

    Read-only: only ``git log`` (no checkout, no write). Never raises for a
    repo with no commits / not a git repo — returns ``[]``.
    """
    root = str(repo_root)
    # newest-first patch, no context (-U0), no rename/textconv noise. The
    # ``--format`` sentinel lets us attribute each hunk to its commit.
    proc = subprocess.Popen(  # noqa: S603 — args are a fixed list
        [
            "git", "-C", root, "log", "--no-color", "--no-textconv",
            "-p", "-U0", f"--format={_COMMIT_SENTINEL}%H",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:  # pragma: no cover - defensive
        return []

    hits: list[SecretHit] = []
    start = time.monotonic()
    commit = ""
    path = ""
    new_lineno = 0
    commits_seen = 0
    truncated = False
    try:
        for raw in proc.stdout:
            if time.monotonic() - start > max_seconds:
                truncated = True
                break
            line = raw.rstrip("\n")

            if line.startswith(_COMMIT_SENTINEL):
                commits_seen += 1
                if commits_seen > max_commits:
                    truncated = True
                    break
                commit = line[len(_COMMIT_SENTINEL):].strip()
                path = ""
                continue
            if line.startswith("+++ "):
                target = line[4:].strip()
                if target == "/dev/null":
                    path = ""
                else:
                    path = target[2:] if target.startswith(("a/", "b/")) else target
                continue
            if line.startswith("---") or line.startswith("diff ") or \
                    line.startswith("index "):
                continue
            hm = _HUNK_RE.match(line)
            if hm:
                new_lineno = int(hm.group(1))
                continue
            if line.startswith("+"):
                content = line[1:]
                if path:
                    hits.extend(scan_line(content, path, new_lineno, commit=commit))
                new_lineno += 1
                continue
            if line.startswith(" "):  # context (rare with -U0)
                new_lineno += 1
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait()

    if truncated:
        hits.append(
            SecretHit(
                path=root,
                line=0,
                rule=HISTORY_TRUNCATED_RULE,
                severity=SEVERITY_INFO,
                redacted="",
                hint=(
                    f"history scan stopped after {commits_seen - 1 if commits_seen > max_commits else commits_seen} "
                    f"commit(s) / {max_seconds:g}s budget; older commits were not "
                    "scanned. Raise max_commits/max_seconds for full coverage."
                ),
                commit=commit,
            )
        )
    return hits


__all__ = [
    "SecretHit",
    "SEVERITY_BLOCK",
    "SEVERITY_WARN",
    "SEVERITY_INFO",
    "HISTORY_TRUNCATED_RULE",
    "DEFAULT_HISTORY_MAX_COMMITS",
    "DEFAULT_HISTORY_MAX_SECONDS",
    "redact",
    "scan_line",
    "scan_text",
    "scan_file",
    "scan_paths",
    "scan_staged",
    "scan_history",
    "staged_paths",
]
