"""
Purpose: ``Finding`` dataclass + JSONL (de)serializer for the security
         agent / per-lab security dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: Constructor args from scanners (Python or bash-emitted JSONL);
       read paths from ``~/.murmurent/security/<host>/<date>.jsonl``.
Output: Dashboard rows, slack summaries, CLI tables.

Single source of truth for the row schema rendered in
``docs/designer_dashboard/security-app.jsx`` and serialised both by the
remote bash scanner (``scripts/murmurent_sec_scan.sh``) and the Python
laptop-side scanners. Keeping it in one place means a rule_id added on
either side automatically flows through the JSONL persistence layer
without code changes.

Each Finding is one row in the dashboard table — exactly one violation
(or one rolled-up parent directory when many siblings share a category).
The ``rule`` field is the stable rule id (e.g. ``RAW-IMMUTABLE-01``)
documented in ``docs/security-dashboard.md`` so suggested fixes deep-link.

The dashboard NEVER auto-applies fixes under ``/data/lab_vm/raw`` or
``/data/lab_vm/refined`` (CC rule 9). The ``suggested_fix`` string is
display-only; if you find yourself wiring it into an exec path, stop.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


# Severity vocabulary mirrors `core.preflight.Probe` for visual
# consistency in the dashboard (green / yellow / red ladder).
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_BLOCK = "block"
ALL_SEVERITIES = (SEVERITY_INFO, SEVERITY_WARN, SEVERITY_BLOCK)

# Where a Finding originated. ``scanner`` = deterministic Python/bash;
# ``agent`` = LLM-driven review (Phase A.2). ``snapshot`` = parsed out of
# the Tier-2 root-owned ACL/sshd dump.
SOURCE_SCANNER = "scanner"
SOURCE_AGENT = "agent"
SOURCE_SNAPSHOT = "snapshot"
ALL_SOURCES = (SOURCE_SCANNER, SOURCE_AGENT, SOURCE_SNAPSHOT)

# Tier 1 = unprivileged (works today on any host with SSH).
# Tier 2 = requires the root-owned sudo snapshot on the remote.
TIER_1 = "tier1"
TIER_2 = "tier2"


@dataclass
class Finding:
    """One actionable row in the security dashboard.

    ``id`` is a stable hash of (host, path, rule) so reruns on the same
    drift produce the same id — lets the UI track "is this finding new
    since yesterday?" without a separate state field.
    """

    severity: str                        # info | warn | block
    category: str                        # raw | refined | ssh | dotfiles | github | …
    rule: str                            # RAW-IMMUTABLE-01, SSH-WEAK-KEY-01, …
    host: str                            # "lab-server" | "local"
    path: str                            # absolute on the target host
    current_state: str                   # human summary, e.g. "0664 the_pi:labgroup"
    expected_state: str                  # "0444 the_pi:labgroup"
    suggested_fix: str                   # "chmod 0444 <path>" — DISPLAY ONLY
    detected_at: str                     # ISO8601 UTC, e.g. "2026-05-19T14:00:00Z"
    source: str = SOURCE_SCANNER         # scanner | agent | snapshot
    tier: str = TIER_1                   # tier1 | tier2
    is_directory: bool = False
    aggregate_count: int = 1             # >1 when a parent dir rolled up siblings
    owner_handle: str | None = None      # "@the_pi" when attributable to a member
    project: str | None = None           # murmurent project name when attributable
    rule_doc_anchor: str = ""            # "docs/security-dashboard.md#RAW-IMMUTABLE-01"
    notes: str = ""                      # free-form; LLM agent narrative lives here
    id: str = ""                         # set in __post_init__ if blank

    def __post_init__(self) -> None:
        if not self.id:
            self.id = stable_finding_id(self.host, self.path, self.rule)
        if self.severity not in ALL_SEVERITIES:
            raise ValueError(
                f"Finding.severity must be one of {ALL_SEVERITIES}; got {self.severity!r}"
            )
        if self.source not in ALL_SOURCES:
            raise ValueError(
                f"Finding.source must be one of {ALL_SOURCES}; got {self.source!r}"
            )
        if self.tier not in (TIER_1, TIER_2):
            raise ValueError(
                f"Finding.tier must be {TIER_1!r} or {TIER_2!r}; got {self.tier!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json_line(self) -> str:
        # ``ensure_ascii=False`` keeps non-ASCII filenames legible in the
        # JSONL file when viewed with ``less``; the file is utf-8 anyway.
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        # Drop unknown keys silently so newer rule schemas can be read by
        # older code (forward-compat for the on-disk JSONL files).
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def stable_finding_id(host: str, path: str, rule: str) -> str:
    """Short, deterministic id. 12 hex chars = collision-safe at our scale."""
    h = hashlib.sha256(f"{host}\x00{path}\x00{rule}".encode("utf-8")).hexdigest()
    return h[:12]


# ---------------------------------------------------------------------------
# JSONL persistence
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, findings: Iterable[Finding], *, append: bool = False) -> int:
    """Write findings as JSONL. Returns the number of lines written.

    Default is overwrite — the daily scan replaces yesterday's file in
    its own dated path. ``append`` exists for the SSE / streaming case
    where the server writes rows as they arrive from the bash scanner.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    n = 0
    with path.open(mode, encoding="utf-8") as fh:
        for f in findings:
            fh.write(f.to_json_line())
            fh.write("\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[Finding]:
    """Read a JSONL findings file. Returns [] if missing.

    Malformed lines are skipped (with a stderr warning would be nice but
    we keep the loader pure so it's safe to call from any context).
    """
    path = Path(path)
    if not path.is_file():
        return []
    out: list[Finding] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            out.append(Finding.from_dict(d))
        except (TypeError, ValueError):
            continue
    return out


def iter_jsonl(path: Path) -> Iterator[Finding]:
    """Generator variant of :func:`read_jsonl` for big files."""
    path = Path(path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                yield Finding.from_dict(d)
            except (TypeError, ValueError):
                continue


# ---------------------------------------------------------------------------
# Roll-up helper (used by both bash scanner output processing and
# Python scanners): if N siblings in the same directory hit the same
# rule, replace them with one parent-directory Finding.
# ---------------------------------------------------------------------------

ROLLUP_THRESHOLD = 5


def _rollup_key(f: Finding) -> str:
    """Return the directory to group ``f`` under for rollup.

    Default = ``Path(f.path).parent``. Categories that benefit from
    coarser rollup override:

    - ``repos`` — roll up to the **project root** (``~/repos/<project>/``)
      so a clone with 100 group-readable files becomes one row with a
      single ``chmod -R`` fix. Without this, findings spread across
      dozens of subdirs never cluster enough to trigger threshold.
    - ``refined`` / ``raw`` — roll up to the **project root** under
      ``<lab_vm>/{raw,refined}/<project>/`` for the same reason.
    """
    p = Path(f.path)
    if f.category in ("repos", "raw", "refined") and f.project:
        # Find the **highest** ancestor whose basename matches the
        # project name. Walk top-down so that a path like
        # ``/home/u/repos/wigamig/src/murmurent/foo.py`` rolls up at
        # ``/home/u/repos/wigamig``, not the nested ``src/murmurent``.
        # Falls back to immediate parent if no match (defensive).
        parts = p.parts
        for i in range(len(parts)):
            if parts[i] == f.project:
                return str(Path(*parts[: i + 1]))
    return str(p.parent)


def rollup_by_directory(findings: list[Finding], *, threshold: int = ROLLUP_THRESHOLD) -> list[Finding]:
    """Collapse same-(rule, group-dir) finding clusters into one parent row.

    Preserves order: the parent row replaces the first occurrence and the
    siblings are dropped. Non-clustered findings pass through unchanged.

    Per the dashboard spec: "if a folder contains many files, then only
    list the parent folder. Suggest what changes should be made."

    Grouping key comes from :func:`_rollup_key` — defaults to immediate
    parent dir, but ``repos``/``raw``/``refined`` categories roll up to
    the project root so the suggested fix is one ``chmod -R`` per repo.
    """
    if threshold < 2:
        return list(findings)
    # Group by (rule, group-dir) preserving first-seen index.
    groups: dict[tuple[str, str], list[int]] = {}
    for i, f in enumerate(findings):
        if f.is_directory:
            continue
        key = _rollup_key(f)
        groups.setdefault((f.rule, key), []).append(i)
    drop: set[int] = set()
    replace: dict[int, Finding] = {}
    for (rule, group_dir), idxs in groups.items():
        if len(idxs) < threshold:
            continue
        first = findings[idxs[0]]
        parent = group_dir
        # Build a parent-directory roll-up Finding. Severity stays at the
        # max of the cluster (a single block keeps the row red).
        sev_order = {SEVERITY_INFO: 0, SEVERITY_WARN: 1, SEVERITY_BLOCK: 2}
        max_sev = max((findings[i].severity for i in idxs), key=lambda s: sev_order[s])
        # Suggested fix uses chmod -R style for the parent. We do NOT
        # synthesize a destructive command — the parent fix mirrors the
        # original suggested fix but applied to the directory.
        rolled = Finding(
            severity=max_sev,
            category=first.category,
            rule=rule,
            host=first.host,
            path=parent,
            current_state=f"{len(idxs)} files under this directory match",
            expected_state=first.expected_state,
            suggested_fix=_dirify_fix(first.suggested_fix, parent),
            detected_at=first.detected_at,
            source=first.source,
            tier=first.tier,
            is_directory=True,
            aggregate_count=len(idxs),
            owner_handle=first.owner_handle,
            project=first.project,
            rule_doc_anchor=first.rule_doc_anchor,
            notes=f"Rolled up from {len(idxs)} sibling files.",
        )
        replace[idxs[0]] = rolled
        for j in idxs[1:]:
            drop.add(j)
    out: list[Finding] = []
    for i, f in enumerate(findings):
        if i in drop:
            continue
        out.append(replace.get(i, f))
    return out


def _dirify_fix(file_fix: str, parent: str) -> str:
    """Best-effort rewrite of a per-file suggested_fix to per-directory.

    Heuristic: if the fix starts with ``chmod`` or ``chown`` and contains
    a path, replace the path with the parent and add ``-R``. Otherwise
    just prefix with a note so the user has the parent to operate on.
    """
    tokens = file_fix.split()
    if tokens and tokens[0] in ("chmod", "chown") and "-R" not in tokens:
        # chmod 0444 /foo/bar.bam  ->  chmod -R 0444 /foo/
        return f"{tokens[0]} -R {' '.join(tokens[1:-1])} {parent}/"
    return f"# applies to {parent}/ recursively\n{file_fix}"


__all__ = [
    "Finding",
    "SEVERITY_INFO",
    "SEVERITY_WARN",
    "SEVERITY_BLOCK",
    "ALL_SEVERITIES",
    "SOURCE_SCANNER",
    "SOURCE_AGENT",
    "SOURCE_SNAPSHOT",
    "ALL_SOURCES",
    "TIER_1",
    "TIER_2",
    "ROLLUP_THRESHOLD",
    "stable_finding_id",
    "write_jsonl",
    "read_jsonl",
    "iter_jsonl",
    "rollup_by_directory",
]
