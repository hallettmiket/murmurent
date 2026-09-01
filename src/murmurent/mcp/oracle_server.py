"""
Purpose: Murmurent oracle MCP server. Exposes the personal Obsidian-vault
         oracle and the lab-mgmt Lab Oracle as a unified set of search
         tools so any CC agent (including the user's main session) can
         recall structured knowledge without grepping by hand.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-16
Input: stdio MCP protocol (the canonical CC integration), or direct
       calls into ``tool_search`` / ``tool_get`` / ``tool_list`` /
       ``tool_publish_draft`` for the test harness.
Output: JSON-serialisable dicts the MCP client renders for the model.

Run as a server::

    python -m murmurent.mcp.oracle_server

The CLI never calls this server directly; ``murmurent install --hooks``
registers it under ``mcpServers`` in ``~/.claude/settings.json``
alongside the inventory server.

Design notes:
  - All tools are READ-first. Writes (``oracle_publish_draft``) wrap
    the same ``core.oracle_publish.publish_draft`` the CLI uses, so
    there's exactly one path for promotion semantics.
  - Search is keyword + frontmatter filter, not embeddings. That's
    deliberate for v1 — the schema is the index. A future
    ``oracle_search_semantic`` tool can plug in alongside.
  - ``kind`` parameter values: ``personal``, ``lab``, ``both``.
    ``both`` is the default for queries (members care about whatever
    answers their question); ``oracle_publish_draft`` is personal-only
    by design.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..core import obsidian as _obsidian
from ..core import oracle_publish as _op

# Env override so the notebook tier is resolvable without machine.yaml
# (symmetric with MURMURENT_PERSONAL_ORACLE_DIR for the personal tier).
ENV_NOTEBOOK = "MURMURENT_NOTEBOOK_DIR"
DEFAULT_NOTEBOOK_SUBFOLDER = "lab-notebook"

VALID_KINDS: tuple[str, ...] = ("personal", "lab", "notebook", "both", "all")
# Backwards-compat: ``both`` originally meant {personal, lab}. ``all``
# is the post-2026-05-17 superset that also includes ``notebook`` (the
# user's daily lab-notebook entries in <vault>/<notebook_subfolder>/).
# We keep ``both`` so existing callers (and the murmurent dashboard) work
# unchanged. ``notebook`` queries the notebook tier in isolation.


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleEntry:
    """One entry's metadata + body, normalised across personal/lab tiers."""

    kind: str                  # "personal" | "lab"
    path: str                  # absolute path on this machine
    title: str
    date: str
    project: str
    sensitivity: str
    tags: list[str]
    sources: list[str]
    related: list[str]
    body: str                  # markdown body (no frontmatter)

    def to_dict(self, *, include_body: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if not include_body:
            d.pop("body", None)
        return d


# ---------------------------------------------------------------------------
# Discovery + parsing
# ---------------------------------------------------------------------------


def _safe_personal_dir() -> Path | None:
    """personal_oracle_dir() can raise if no vault is registered; tools
    must degrade gracefully (return [] for that tier) instead."""
    try:
        return _op.personal_oracle_dir()
    except _op.OracleError:
        return None


def _safe_lab_dir() -> Path | None:
    try:
        return _op.lab_oracle_dir()
    except Exception:
        return None


def _safe_notebook_dir() -> Path | None:
    """Resolve ``<vault>/<notebook_subfolder>`` on this machine.

    Uses the **same fallback chain** as
    :func:`murmurent.core.oracle_publish.personal_oracle_dir` so the
    notebook tier survives a missing ``~/.murmurent/machine.yaml`` (the
    old implementation read only ``machine.yaml.obsidian_vault_path`` and
    returned ``None`` whenever that file was absent, silently killing the
    notebook tier):

      1. ``$MURMURENT_NOTEBOOK_DIR`` — an explicit override (tests + power
         users), pointing straight at the notebook dir.
      2. ``machine.yaml`` ``obsidian_vault_path`` + ``notebook_subfolder``.
      3. The most-recently-opened Obsidian vault (from ``obsidian.json``)
         + the machine's notebook subfolder (default ``lab-notebook``).

    Returns ``None`` when no vault resolves at all, or when the resolved
    path doesn't exist. The path may exist but be unreadable (macOS Full
    Disk Access on iCloud-backed vaults) — :func:`_iter_paths` handles
    the EPERM gracefully so a sandbox restriction never crashes the MCP
    server (see also ``murmurent oracle doctor``)."""
    # 1. Explicit override wins — trust it verbatim (existence is checked
    #    below like every other branch).
    pin = os.environ.get(ENV_NOTEBOOK, "").strip()
    if pin:
        return _dir_if_exists(Path(pin).expanduser())

    # 2 + 3. Resolve the vault root, then append the notebook subfolder.
    sub = DEFAULT_NOTEBOOK_SUBFOLDER
    vault_root: Path | None = None
    try:
        from ..dashboard import machine_settings as _ms
        s = _ms.load()
        if s.notebook_subfolder:
            sub = s.notebook_subfolder
        if s.obsidian_vault_path:
            vault_root = Path(s.obsidian_vault_path).expanduser()
    except Exception:
        # machine_settings is best-effort (optional dashboard deps); fall
        # through to obsidian.json discovery.
        pass

    if vault_root is None:
        try:
            v = _obsidian.preferred_vault()
        except Exception:
            v = None
        if v is None:
            return None
        vault_root = v.path

    return _dir_if_exists(vault_root / sub)


def _dir_if_exists(p: Path) -> Path | None:
    """Return ``p`` if it exists, else ``None``.

    ``exists()`` swallows OSError and returns False, so an EPERM on the
    parent reads as "absent" here — that's fine: the notebook tier just
    stays empty, and ``murmurent oracle doctor`` is the tool that names the
    Full-Disk-Access cause explicitly."""
    try:
        return p if p.exists() else None
    except OSError:
        return None


# One best-effort ff-only pull of the personal vault per process, so MCP
# search reflects the latest push from another machine (issue #25 §4). Guarded
# by a once-flag + ``MURMURENT_NO_VAULT_PULL`` opt-out (tests set it); every
# failure is swallowed so a sandbox/network denial keeps the silent
# degrade-to-empty behaviour rather than crashing search.
_pulled_personal = False


def _maybe_pull_personal() -> None:
    global _pulled_personal
    if _pulled_personal or os.environ.get("MURMURENT_NO_VAULT_PULL"):
        return
    _pulled_personal = True  # attempt at most once, even on failure
    try:
        from ..core import vault_sync as _vs
        _vs.pull_personal_vault()
    except Exception:  # noqa: BLE001 — read must degrade, never crash
        pass


def _iter_paths(kind: str) -> list[tuple[str, Path]]:
    """Yield (kind, path) for every .md entry in the requested tier(s).

    Excludes the personal vault's ``drafts/`` subdir (those are
    not-yet-published and should not appear in lab-wide search).
    Skips ``MEMORY.md`` and README-style index files.
    """
    out: list[tuple[str, Path]] = []
    if kind in ("personal", "both", "all"):
        _maybe_pull_personal()
        p = _safe_personal_dir()
        if p and p.is_dir():
            for f in p.rglob("*.md"):
                if "drafts" in f.parts:
                    continue
                if f.name in {"MEMORY.md", "README.md"}:
                    continue
                out.append(("personal", f))
    if kind in ("lab", "both", "all"):
        p = _safe_lab_dir()
        if p and p.is_dir():
            for f in p.glob("*.md"):
                if f.name in {"MEMORY.md", "README.md"}:
                    continue
                out.append(("lab", f))
    if kind in ("notebook", "all"):
        p = _safe_notebook_dir()
        if p is not None:
            # Walk recursively — notebooks may be flat (lab-notebook/
            # YYYY-MM-DD.md) or nested per-project (lab-notebook/<project>/
            # YYYY-MM-DD.md). Catch OSError so macOS Full Disk Access
            # denials don't crash the whole search.
            try:
                for f in p.rglob("*.md"):
                    if f.name in {"MEMORY.md", "README.md", "index.md"}:
                        continue
                    out.append(("notebook", f))
            except (OSError, PermissionError):
                pass
    return out


def _parse_entry(kind: str, path: Path) -> OracleEntry | None:
    """Parse one file into an :class:`OracleEntry`.

    For ``personal`` and ``lab`` tiers, requires the file to start
    with YAML frontmatter conforming to rules/oracle_schema.md;
    returns ``None`` for files that don't (those are surfaced via
    ``oracle_lint`` if the user wants to fix them).

    For ``notebook`` tier, frontmatter is *optional* — daily lab
    notebooks are often free-form. Missing fields are synthesised
    from filename + path conventions; missing frontmatter entirely
    falls back to deriving everything from the path. This keeps
    notebooks searchable without requiring the user to retrofit
    every old daily entry with a schema block.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        # macOS sandbox / iCloud paths sometimes deny reads even
        # after the dir lists — skip silently.
        return None
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = None
        body = m.group(2).strip()
    else:
        meta = None
        body = text
    if meta is None or not isinstance(meta, dict):
        if kind == "notebook":
            meta = {}  # accept frontmatter-less notebooks
        else:
            return None  # personal + lab tiers require schema

    if kind == "notebook":
        return _parse_notebook_entry(path, meta, body)

    tags = meta.get("tags") or []
    sources = meta.get("sources") or []
    related = meta.get("related") or []
    return OracleEntry(
        kind=kind,
        path=str(path),
        title=str(meta.get("title") or path.stem),
        date=str(meta.get("date") or ""),
        project=str(meta.get("project") or ""),
        sensitivity=str(meta.get("sensitivity") or "standard"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        sources=[str(s) for s in sources] if isinstance(sources, list) else [],
        related=[str(r) for r in related] if isinstance(related, list) else [],
        body=body,
    )


# Filename pattern for date-stamped daily notebooks: YYYY-MM-DD.md or
# YYYY-MM-DD_<slug>.md. Used to extract ``date`` when notebook
# frontmatter doesn't carry it.
_NOTEBOOK_DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<slug>.+))?$")


def _parse_notebook_entry(path: Path, meta: dict[str, Any], body: str) -> OracleEntry:
    """Build an OracleEntry from a notebook file.

    Notebook conventions assumed (in order of preference):
      - ``<vault>/lab-notebook/<project>/<YYYY-MM-DD>.md`` (nested)
      - ``<vault>/lab-notebook/<YYYY-MM-DD>.md`` (flat)
      - Any other ``.md`` under ``lab-notebook/`` — uses the filename
        stem as a fallback title; project + date stay empty.

    Frontmatter, when present, takes precedence over path-derived
    values. The notebook frontmatter may carry ``tags`` (per the
    designer_dashboard HANDOFF doc), but doesn't need to.
    """
    # Date from filename, unless frontmatter overrides.
    fname_match = _NOTEBOOK_DATE_RE.match(path.stem)
    date_from_name = fname_match.group("date") if fname_match else ""
    # Project from parent dir, unless flat-layout (parent is lab-notebook itself).
    notebook_root = _safe_notebook_dir()
    project_from_path = ""
    if notebook_root is not None:
        try:
            rel = path.parent.resolve().relative_to(notebook_root.resolve())
            parts = rel.parts
            if parts and parts[0] not in ("", "."):
                project_from_path = parts[0]
        except (ValueError, OSError):
            pass
    # Title: frontmatter `title:` wins, then first H1 in body, then filename.
    title = str(meta.get("title") or _first_h1(body) or path.stem)
    tags = meta.get("tags") or []
    return OracleEntry(
        kind="notebook",
        path=str(path),
        title=title,
        date=str(meta.get("date") or date_from_name),
        project=str(meta.get("project") or project_from_path),
        # Notebooks default to ``standard``; if a daily entry needs to be
        # restricted/clinical the author should add the frontmatter
        # explicitly. Conservative default avoids accidentally treating
        # sensitive notes as broadly shareable.
        sensitivity=str(meta.get("sensitivity") or "standard"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        sources=[str(s) for s in (meta.get("sources") or [])] if isinstance(meta.get("sources"), list) else [],
        related=[str(r) for r in (meta.get("related") or [])] if isinstance(meta.get("related"), list) else [],
        body=body,
    )


def _first_h1(body: str) -> str:
    """Return the first ``# heading`` line in ``body`` (without the
    leading ``# ``), or empty string when none exists. Used for
    notebook titles when frontmatter doesn't carry one."""
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _load_entries(kind: str) -> list[OracleEntry]:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")
    entries = []
    for k, p in _iter_paths(kind):
        e = _parse_entry(k, p)
        if e is not None:
            entries.append(e)
    return entries


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _matches_filters(
    entry: OracleEntry,
    *,
    project: str | None,
    tags: list[str] | None,
    sensitivity: str | None,
    source: str | None,
) -> bool:
    """All filters AND together. Tag filter uses set-overlap (any tag
    in ``tags`` matches the entry's tag list)."""
    if project and not _glob_match(entry.project, project):
        return False
    if sensitivity and entry.sensitivity != sensitivity:
        return False
    if source:
        wanted = source.lower().lstrip("@")
        if not any(wanted == s.lower().lstrip("@") for s in entry.sources):
            return False
    if tags:
        wanted = {t.lower() for t in tags}
        have = {t.lower() for t in entry.tags}
        if not (wanted & have):
            return False
    return True


def _glob_match(value: str, pattern: str) -> bool:
    """Tiny glob: ``*`` matches any run of chars. Anchored. Used for
    project filters like ``dcis_*``."""
    rx = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.match(rx, value or "") is not None


def _score(entry: OracleEntry, query: str) -> int:
    """Naive ranking: title hits > tag hits > body hits.

    Good enough for v1 keyword search. Replace with embeddings when
    we add ``oracle_search_semantic``.
    """
    q = query.lower()
    score = 0
    if q in entry.title.lower():
        score += 10
    if any(q in t.lower() for t in entry.tags):
        score += 5
    if q in entry.body.lower():
        score += 1
    return score


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def tool_search(
    query: str = "",
    *,
    kind: str = "both",
    project: str | None = None,
    tags: list[str] | None = None,
    sensitivity: str | None = None,
    source: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search across the requested tier(s).

    Empty ``query`` is allowed — returns everything matching the
    filters (useful for "show me all dcis entries" without keyword).
    Results are sorted by score then by date (newest first), capped
    at ``limit``.
    """
    entries = _load_entries(kind)
    filtered = [
        e for e in entries
        if _matches_filters(
            e, project=project, tags=tags, sensitivity=sensitivity, source=source,
        )
    ]
    if query:
        scored = [(_score(e, query), e) for e in filtered]
        scored = [(s, e) for s, e in scored if s > 0]
        scored.sort(key=lambda pair: (-pair[0], pair[1].date), reverse=False)
        # Python's sort by negative score sorts descending; date sorts
        # ascending. Reverse the whole list to get newest-first for ties.
        result = [e for _, e in scored]
    else:
        result = sorted(filtered, key=lambda e: e.date, reverse=True)
    return [e.to_dict(include_body=False) for e in result[:limit]]


def tool_get(path: str) -> dict[str, Any]:
    """Read one entry by absolute path. Includes body.

    Tier inferred from where the file lives: personal vault →
    ``personal``, notebook subdir → ``notebook``, anything else
    (including the lab-mgmt oracle dir) → ``lab``. Notebooks are
    permissive about missing frontmatter; personal + lab tiers
    require it.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"no oracle entry at {path}")
    # Determine kind by which dir contains the file. Notebook check
    # must come first because it's the most specific (some notebooks
    # could be inside the vault under the notebook subdir, which the
    # personal check would otherwise claim).
    kind = "lab"
    notebook = _safe_notebook_dir()
    personal = _safe_personal_dir()
    if notebook and _is_under(p, notebook):
        kind = "notebook"
    elif personal and _is_under(p, personal):
        kind = "personal"
    entry = _parse_entry(kind, p)
    if entry is None:
        raise ValueError(
            f"{path}: no parseable YAML frontmatter — does the file conform "
            f"to rules/oracle_schema.md?"
        )
    return entry.to_dict(include_body=True)


def tool_list(kind: str = "both") -> list[dict[str, Any]]:
    """One-line summary of every entry in the tier(s). Cheap to call —
    no body parsing beyond what frontmatter needs."""
    entries = _load_entries(kind)
    entries.sort(key=lambda e: e.date, reverse=True)
    return [e.to_dict(include_body=False) for e in entries]


def tool_publish_draft(slug: str, *, push: bool = False) -> dict[str, Any]:
    """Promote a personal-vault draft to the Lab Oracle.

    Equivalent to ``murmurent oracle publish <slug>``. The committer
    handle comes from :func:`murmurent.core.identity.resolve` — agents
    cannot impersonate another user.
    """
    from ..core.identity import resolve as resolve_identity
    committer = resolve_identity(allow_unknown=False).handle
    result = _op.publish_draft(slug, committer=committer, commit=True, push=push)
    return {
        "source": str(result.source),
        "target": str(result.target),
        "commit_sha": result.commit_sha,
        "pushed": result.pushed,
    }


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# MCP server wiring (lazy import; only required to actually run as server)
# ---------------------------------------------------------------------------


def _build_server():  # pragma: no cover - exercised only when mcp is installed
    """Construct the MCP server. Imports the SDK lazily."""
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

    server = FastMCP(
        name="murmurent-oracle",
        instructions=(
            "Murmurent oracle. Three tiers, queryable separately or "
            "together: `personal` (your Obsidian vault `oracle/`), "
            "`lab` (lab-mgmt repo `oracle/`), `notebook` (your daily "
            "lab-notebook entries in <vault>/<notebook_subfolder>/). "
            "Use `kind=both` for {personal, lab} (default), `kind=all` "
            "for {personal, lab, notebook}, or any single tier name. "
            "`oracle_search` filters by query + project/tags/sensitivity/"
            "source. `oracle_get(path)` fetches one entry (notebooks "
            "tolerate missing frontmatter; personal + lab require it). "
            "`oracle_list` browses everything. `oracle_publish_draft("
            "slug)` promotes a vault draft to lab. Schema for the "
            "structured tiers: rules/oracle_schema.md."
        ),
    )

    @server.tool(name="oracle_search", description="Search oracle entries by query + filters.")
    def _search(
        query: str = "",
        kind: str = "both",
        project: str | None = None,
        tags: list[str] | None = None,
        sensitivity: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> str:
        return json.dumps(tool_search(
            query, kind=kind, project=project, tags=tags,
            sensitivity=sensitivity, source=source, limit=limit,
        ))

    @server.tool(name="oracle_get", description="Read one oracle entry (full body) by absolute path.")
    def _get(path: str) -> str:
        return json.dumps(tool_get(path))

    @server.tool(name="oracle_list", description="List every entry in the requested tier(s).")
    def _list(kind: str = "both") -> str:
        return json.dumps(tool_list(kind))

    @server.tool(
        name="oracle_publish_draft",
        description="Promote a personal-vault draft to the Lab Oracle (commits to lab-mgmt).",
    )
    def _publish(slug: str, push: bool = False) -> str:
        return json.dumps(tool_publish_draft(slug, push=push))

    return server


def main() -> int:  # pragma: no cover - run only as MCP server
    server = _build_server()
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
