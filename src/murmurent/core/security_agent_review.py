"""
Purpose: LLM-driven per-project security review. Orchestrates the
         ``security_guard`` agent across 3 categories (code, secrets,
         cc) and emits the same :class:`Finding` schema the
         deterministic scanner uses. Phase A.2 of the per-lab security
         dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: Project path + selected categories.
Output: ``AgentReviewResult`` — findings + token/cost meta.

Design notes:

- **LLM client**: thin wrapper around :class:`core.slack_distill.AnthropicLLM`
  (already a project dependency). Tests inject a stub via ``client=``.
- **Cache**: keyed by (project, category, hash-of-inputs). Re-running
  on unchanged inputs returns 0 LLM calls. Cache lives at
  ``~/.wigamig/security/agent_cache/`` and is per-machine — safe to
  delete to force a fresh review.
- **Hard rule (carried from the global murmurent charter)**: every
  category-specific user prompt explicitly forbids the agent from
  proposing or performing writes under ``/data/lab_vm/raw/`` or
  ``/data/lab_vm/refined/``. The agent only ever returns text;
  this module never executes its output as code.
- **Cost transparency**: ``AgentReviewMeta`` carries input/output
  token counts and an estimated USD cost using current Sonnet 4.6
  pricing. Surfaced in the dashboard panel.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_AGENT,
    TIER_1,
)


# Claude Sonnet 4.6 USD/1M-token pricing (as of 2026-05).
# Updated centrally when the model changes; the dashboard surfaces the
# resulting cost-estimate string.
_USD_PER_M_INPUT  = 3.00
_USD_PER_M_OUTPUT = 15.00


# ---------------------------------------------------------------------------
# Category catalogue. Each entry: rule prefixes the agent may use + a
# user-prompt builder. Add a category by appending here + writing the
# builder function below; the orchestrator picks them up automatically.
# ---------------------------------------------------------------------------

CATEGORIES = ("code", "secrets", "cc")


# ---------------------------------------------------------------------------
# LLM protocol — narrow surface so tests can substitute a stub without
# touching the real Anthropic client.
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    """Minimal interface the orchestrator needs from an LLM."""

    def complete(
        self,
        *,
        prompt: str,
        system: str = "",
    ) -> "LLMResponse": ...


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class AnthropicAdapter:
    """Adapt :class:`core.slack_distill.AnthropicLLM` to the LLMClient
    protocol, exposing token counts (which the slack_distill wrapper
    discards).
    """

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    def complete(self, *, prompt: str, system: str = "") -> LLMResponse:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed; `uv sync` to pick up the dep."
            ) from exc
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts: list[str] = []
        for block in msg.content:
            if getattr(block, "type", "") == "text":
                parts.append(block.text)
        usage = getattr(msg, "usage", None)
        return LLMResponse(
            text="\n".join(parts),
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            model=self.model,
        )


# ---------------------------------------------------------------------------
# Shared system prompt + per-category user prompts.
#
# The system prompt always pins the JSON output schema + the immutable
# /data/lab_vm/{raw,refined} guardrail (defence in depth — the murmurent
# CC hooks would also block writes there, but a model that refuses to
# propose such writes in the first place is one fewer surface to worry
# about). All findings carry severity in {info, warn, block} and a
# rule ID from the catalogue documented in docs/security-dashboard.md.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the murmurent `security_guard` agent operating in "agent review" mode for
the per-lab security dashboard. You audit project source code, configurations,
and secrets for security issues.

## Output schema

Reply with a single JSON document of the form:

  {"findings": [{"rule": "...", "severity": "info|warn|block",
                 "path": "...", "current_state": "...", "suggested_fix": "...",
                 "notes": "..."}]}

If you find nothing, reply with `{"findings": []}`. No prose outside the JSON.

## Severity discipline

- `block` — clear security defect that can lead to compromise (hardcoded
  credentials in tracked files, SQL injection in active code paths, unsafe
  deserialization of untrusted input, command injection with user-controlled
  data).
- `warn` — likely defect or weak pattern that deserves review (deprecated
  crypto primitives, suspicious-looking file patterns, possibly-stale config).
- `info` — observation, not a defect (notes for the PI, narrative findings).

Only emit findings you are confident in. False positives waste the PI's time.

## Rule IDs

Use the rule IDs documented in `docs/security-dashboard.md`. Common ones for
agent review:

- CODE-HARDCODED-CRED-01, CODE-SQLI-01, CODE-UNSAFE-DESERIAL-01,
  CODE-CMD-INJECTION-01, CODE-WEAK-CRYPTO-01, CODE-RACE-FILE-01
- SECRETS-GIT-TRACKED-01, SECRETS-GIT-HISTORY-01
- CC-SETTINGS-PERMISSIVE-01, CC-SETTINGS-MCP-EXPOSED-01

If a finding doesn't match an existing ID, invent one in the same style
(CATEGORY-PROBLEM-01) and the dashboard will surface it as a new rule.

## Hard rule — murmurent data immutability

**Never propose any change (chmod, chown, edit, delete) to files under
`/data/lab_vm/raw/` or `/data/lab_vm/refined/`.** Those paths are
hook-protected and write-once by lab convention. If you spot a finding
that would normally suggest a fix in those paths, emit it with
`suggested_fix` explaining the issue but no actionable command — the PI
will handle it manually.
"""


def _code_user_prompt(project_name: str, files: list[tuple[str, str]]) -> str:
    """Build the user prompt for the ``code`` category."""
    bundle = "\n\n".join(
        f"--- file: {path} ---\n{content}" for path, content in files
    )
    return f"""\
Project: {project_name}
Category: code

Review the following source files for security defects: hardcoded credentials,
SQL injection (especially Shiny/Flask/raw R DBI string-concat queries), unsafe
deserialization (`pickle.load`, `yaml.load`, `readRDS()` from untrusted
sources), command injection (`system()`/`system2()`/`subprocess(shell=True)`
with un-sanitised input), weak crypto (MD5/SHA1 for security, AES-ECB,
hardcoded IVs, weak RNG), TOCTOU and predictable temp-path patterns.

Bundle ({len(files)} file(s)):

{bundle}
"""


def _secrets_user_prompt(project_name: str,
                          tracked_files: list[str],
                          suspicious_matches: list[dict]) -> str:
    """Build the user prompt for the ``secrets`` category.

    Receives a list of tracked filenames + grep matches the bash scanner
    already flagged. The LLM's job: confirm true positives, reject false
    ones (e.g. a placeholder in a .env.example, a docstring example).
    """
    matches_str = "\n".join(
        f"  {m.get('path')}: {m.get('line', '')!r}" for m in suspicious_matches
    )
    return f"""\
Project: {project_name}
Category: secrets

The deterministic pattern-scanner flagged the following files / lines as
secret-shaped. Review each and confirm whether it is a real secret leak
(`block`/`warn`) or a benign false positive (do not include in findings).

A real leak: an API key, password, token, or other credential committed to git
in a tracked file.
A false positive: placeholder text in `.env.example`, a docstring example, a
test fixture using obvious dummy values like "your-key-here".

Tracked files in the repo ({len(tracked_files)}): {", ".join(tracked_files[:20])}{"…" if len(tracked_files) > 20 else ""}

Flagged matches:
{matches_str if matches_str else "(none — the bash scanner found no suspicious filenames; do a sanity pass on the tracked file list above)"}
"""


def _cc_user_prompt(project_name: str,
                     settings_global: dict | None,
                     settings_project: dict | None) -> str:
    """Build the user prompt for the ``cc`` category."""
    blob: list[str] = []
    if settings_global is not None:
        blob.append("--- ~/.claude/settings.json (global) ---\n"
                    + json.dumps(settings_global, indent=2))
    if settings_project is not None:
        blob.append(f"--- {project_name}/.claude/settings.json (per-project) ---\n"
                    + json.dumps(settings_project, indent=2))
    if not blob:
        blob.append("(no .claude/settings.json files present)")
    return f"""\
Project: {project_name}
Category: cc (Claude Code settings)

Audit the following Claude Code settings file(s) for over-permissive
allowlists or leaked secrets. Specifically look for:

- `permissions.allow` entries that grant broad shell access
  (e.g. `Bash`, `Bash(*)`, `Bash(sudo *)`, `Bash(rm *)`, `Write` without
   path restriction). These let CC run arbitrary commands with no audit.
- `permissions.allow` entries that match destructive patterns under
  `/data/lab_vm/raw/` or `/data/lab_vm/refined/` — those should be blocked
  by the murmurent hooks but should also not appear in allow lists.
- `mcpServers` entries whose `env` contains auth tokens or API keys in
  plain text (these files are committed to nothing per .gitignore but are
  still visible to anyone with read access to the user's home).

{chr(10).join(blob)}
"""


# ---------------------------------------------------------------------------
# Input gathering (project filesystem walk)
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS = {".py", ".r", ".R", ".sh", ".js", ".ts", ".jsx", ".tsx"}
_CODE_FILE_MAX_BYTES = 60_000          # ~15k tokens; cap a single file
_CODE_BUNDLE_MAX_BYTES = 250_000       # total input cap; bigger projects truncate
_SECRET_FILENAME_PATTERN = ("*.env", "*.pem", "*_rsa", "*_ed25519",
                             "*.p12", "*.pfx", "*.key", "id_*")


def _collect_code_files(project_root: Path) -> list[tuple[str, str]]:
    """Walk the project tree for source files. Skip common heavy dirs.

    Returns ``[(relpath, content), ...]`` capped at
    :data:`_CODE_BUNDLE_MAX_BYTES`. Each file individually capped at
    :data:`_CODE_FILE_MAX_BYTES` (with a truncation marker). Order is
    deterministic so the cache key is stable.
    """
    skip = {".git", "node_modules", "__pycache__", ".venv", "target",
            ".tox", ".next", ".cache", "obsolete"}
    out: list[tuple[str, str]] = []
    running = 0
    for root, dirs, files in os.walk(project_root):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for fname in sorted(files):
            ext = "".join(Path(fname).suffixes)[-len(Path(fname).suffix):] or ""
            if Path(fname).suffix not in _CODE_EXTENSIONS:
                continue
            path = Path(root) / fname
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) > _CODE_FILE_MAX_BYTES:
                data = data[:_CODE_FILE_MAX_BYTES] + b"\n# ... [truncated by murmurent]\n"
            running += len(data)
            if running > _CODE_BUNDLE_MAX_BYTES:
                break
            try:
                content = data.decode("utf-8", errors="replace")
            except Exception:
                continue
            rel = str(path.relative_to(project_root))
            out.append((rel, content))
        if running > _CODE_BUNDLE_MAX_BYTES:
            break
    return out


def _collect_tracked_files(project_root: Path) -> list[str]:
    """Return git-tracked filenames; empty list if not a git tree."""
    import subprocess
    try:
        res = subprocess.run(
            ["git", "-C", str(project_root), "ls-files"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    return [line.strip() for line in (res.stdout or "").splitlines() if line.strip()]


def _collect_suspicious_matches(project_root: Path,
                                  tracked: list[str]) -> list[dict]:
    """Filename-based hits the deterministic scanner would flag."""
    import fnmatch
    out: list[dict] = []
    for tf in tracked:
        for pat in _SECRET_FILENAME_PATTERN:
            if fnmatch.fnmatch(tf.lower(), pat) or fnmatch.fnmatch(
                Path(tf).name.lower(), pat
            ):
                out.append({"path": tf, "line": ""})
                break
    return out


def _collect_cc_settings(project_root: Path) -> tuple[dict | None, dict | None]:
    """Read global + per-project Claude Code settings; return parsed JSON."""
    global_path = Path.home() / ".claude" / "settings.json"
    project_path = project_root / ".claude" / "settings.json"

    def _load(p: Path) -> dict | None:
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            return None
    return _load(global_path), _load(project_path)


# ---------------------------------------------------------------------------
# Cache — keyed by (category, sha256(inputs)). Stored as JSON.
# ---------------------------------------------------------------------------

CACHE_DIR_DEFAULT = Path.home() / ".wigamig" / "security" / "agent_cache"


def _input_hash(category: str, payload: Any) -> str:
    """SHA256 of the canonical JSON payload. Stable across runs."""
    blob = json.dumps({"category": category, "payload": payload},
                       sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_read(cache_dir: Path, key: str) -> dict | None:
    path = cache_dir / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(cache_dir: Path, key: str, payload: dict) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{key}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Parse the LLM's JSON response into Finding rows.
# ---------------------------------------------------------------------------

def _parse_response(text: str, *, host: str, project: str,
                     category: str, model: str) -> list[Finding]:
    """Tolerant JSON extraction. The model is asked for pure JSON but
    occasionally wraps in ```json fences or adds a leading sentence —
    strip those before parsing.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json ... ``` or ``` ... ``` — drop first + last fence.
        cleaned = "\n".join(cleaned.splitlines()[1:-1] or [""])
    # Find the first '{' and the matching trailing '}'.
    if "{" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    try:
        doc = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    items = doc.get("findings", []) if isinstance(doc, dict) else []
    now = _dt.datetime.utcnow().isoformat() + "Z"
    out: list[Finding] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rule = str(it.get("rule") or "AGENT-UNCATEGORIZED")
        severity = str(it.get("severity") or SEVERITY_INFO).lower()
        if severity not in (SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO):
            severity = SEVERITY_INFO
        path = str(it.get("path") or project)
        try:
            out.append(Finding(
                severity=severity,
                category=category,
                rule=rule,
                host=host,
                path=path,
                current_state=str(it.get("current_state") or ""),
                expected_state="",
                suggested_fix=str(it.get("suggested_fix") or ""),
                detected_at=now,
                source=SOURCE_AGENT,
                tier=TIER_1,
                owner_handle=None,
                project=project,
                rule_doc_anchor=f"docs/security-dashboard.md#{rule}",
                notes=f"[model={model}] " + str(it.get("notes") or ""),
            ))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class AgentReviewMeta:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def cost_estimate_usd(self) -> float:
        return (self.input_tokens * _USD_PER_M_INPUT / 1_000_000
                + self.output_tokens * _USD_PER_M_OUTPUT / 1_000_000)


@dataclass
class AgentReviewResult:
    findings: list[Finding] = field(default_factory=list)
    meta: AgentReviewMeta = field(default_factory=AgentReviewMeta)
    errors: list[str] = field(default_factory=list)


def review_project(
    project_root: Path,
    *,
    host: str,
    categories: Iterable[str] = CATEGORIES,
    client: LLMClient | None = None,
    cache_dir: Path | None = None,
) -> AgentReviewResult:
    """Run the selected categories against ``project_root``.

    Set ``client=None`` (the default) to use :class:`AnthropicAdapter`
    backed by the real Anthropic SDK. Tests inject a stub.
    """
    project_root = Path(project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"project root does not exist: {project_root}")
    project_name = project_root.name
    cache_dir = cache_dir or CACHE_DIR_DEFAULT
    client = client or AnthropicAdapter()
    result = AgentReviewResult()
    cats = [c for c in categories if c in CATEGORIES]
    for cat in cats:
        try:
            findings, used_cache, tokens_in, tokens_out, model = _run_category(
                cat, project_root, project_name, host, client, cache_dir,
            )
            result.findings.extend(findings)
            if used_cache:
                result.meta.cache_hits += 1
            else:
                result.meta.cache_misses += 1
                result.meta.input_tokens  += tokens_in
                result.meta.output_tokens += tokens_out
            if model and not result.meta.model:
                result.meta.model = model
        except Exception as exc:                                  # noqa: BLE001
            result.errors.append(f"{cat}: {exc}")
    return result


def _run_category(category: str, project_root: Path, project_name: str,
                   host: str, client: LLMClient,
                   cache_dir: Path) -> tuple[list[Finding], bool, int, int, str]:
    """Resolve the per-category input, hit cache or LLM, parse response."""
    if category == "code":
        files = _collect_code_files(project_root)
        if not files:
            return [], False, 0, 0, ""
        payload = {"files": [(p, hashlib.sha256(c.encode("utf-8")).hexdigest()[:12])
                              for p, c in files]}
        key = _input_hash(category, payload)
        cached = _cache_read(cache_dir, key)
        if cached:
            return [Finding.from_dict(d) for d in cached.get("findings", [])], True, 0, 0, cached.get("model", "")
        user = _code_user_prompt(project_name, files)
    elif category == "secrets":
        tracked = _collect_tracked_files(project_root)
        matches = _collect_suspicious_matches(project_root, tracked)
        payload = {"tracked": tracked, "matches": matches}
        key = _input_hash(category, payload)
        cached = _cache_read(cache_dir, key)
        if cached:
            return [Finding.from_dict(d) for d in cached.get("findings", [])], True, 0, 0, cached.get("model", "")
        user = _secrets_user_prompt(project_name, tracked, matches)
    elif category == "cc":
        glob_s, proj_s = _collect_cc_settings(project_root)
        payload = {"global": glob_s, "project": proj_s}
        key = _input_hash(category, payload)
        cached = _cache_read(cache_dir, key)
        if cached:
            return [Finding.from_dict(d) for d in cached.get("findings", [])], True, 0, 0, cached.get("model", "")
        user = _cc_user_prompt(project_name, glob_s, proj_s)
    else:
        raise ValueError(f"unknown category: {category}")

    resp = client.complete(prompt=user, system=_SYSTEM_PROMPT)
    findings = _parse_response(resp.text, host=host, project=project_name,
                                category=category, model=resp.model or "")
    # Persist to cache so a re-run on unchanged inputs is free.
    _cache_write(cache_dir, key, {
        "model": resp.model,
        "findings": [f.to_dict() for f in findings],
    })
    return findings, False, resp.input_tokens, resp.output_tokens, resp.model


__all__ = [
    "CATEGORIES",
    "LLMClient",
    "LLMResponse",
    "AnthropicAdapter",
    "AgentReviewMeta",
    "AgentReviewResult",
    "review_project",
]
