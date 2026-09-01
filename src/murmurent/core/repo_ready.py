"""
Purpose: Repo-level murmurent READINESS — distinct from projects.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-15
Input: A git working tree (``~/repos/<name>``) + the murmurent commons clone.
Output: A ``.murmurent.yaml`` marker at the repo root + the layer-2 CC
        bootstrap (commons agent symlinks, CLAUDE.md stub, chrome).

Terminology (the point of this module): a repo with the murmurent
bootstrap is **murmurent-ready** — nothing more. A *project* is a
different, bigger thing: a named set of repos + a set of members (+
Slack channel, certificates), recorded in the lab_mgmt registry
(``cert_projects/``). Adopting a repo makes it ready; creating a
project attaches ready repos to a project record. Historically the two
were fused — adopting wrote a project-ish ``CHARTER.md`` into the repo
AND minted a one-repo project — which is how five trial adoptions
polluted a Projects panel (issue context: 2026-07-15).

The marker also solves the upgrade problem: agent CONTENT updates flow
automatically (agents are symlinks into the commons clone), but
structural changes — new commons agents, marker schema, refreshed
stubs — are frozen at bootstrap time. ``upgrade()`` re-runs the
bootstrap idempotently against the current commons and re-stamps
``bootstrap_version``; for a legacy CHARTER.md bootstrap it stamps the
marker while PRESERVING the CHARTER.md (which may be a project document —
readiness just stops keying on it; issue #28).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .preflight import Probe
from .repo import murmurent_repo_root

MARKER_FILENAME = ".murmurent.yaml"
# Versions the SHAPE of the .murmurent.yaml marker — independent of the
# murmurent release version (murmurent.__version__). Bump only when the marker
# format changes; do NOT bump it to match a release. (issue #24)
MARKER_SCHEMA = 1
LEGACY_MARKER = "CHARTER.md"   # pre-split repos carried a project charter


def _version() -> str:
    try:
        from .. import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


@dataclass
class Readiness:
    """Repo-level readiness verdict for one working tree."""

    path: Path
    marker: dict | None = None          # parsed .murmurent.yaml, if present
    legacy_charter: bool = False        # CHARTER.md present (pre-split bootstrap)
    has_agents_dir: bool = False        # .claude/agents/ exists

    @property
    def ready(self) -> bool:
        # Readiness keys on the .murmurent.yaml marker ONLY (issue #28). A
        # legacy CHARTER.md no longer signals readiness — it's a project
        # document (project/lead/members), not a bootstrap marker. Repos that
        # only carry a CHARTER migrate via `murmurent repo upgrade`, which
        # stamps a marker and PRESERVES the CHARTER.
        return self.marker is not None and self.has_agents_dir

    @property
    def needs_upgrade(self) -> bool:
        """True when a marker-ready repo was bootstrapped by an older marker
        shape (schema/version lags), OR when a repo still carries only a legacy
        CHARTER.md bootstrap and wants a one-time marker stamp."""
        if self.marker is None:
            return self.legacy_charter
        if int(self.marker.get("murmurent") or 0) < MARKER_SCHEMA:
            return True
        return str(self.marker.get("bootstrap_version") or "") != _version()


def read_marker(repo: Path) -> dict | None:
    f = Path(repo) / MARKER_FILENAME
    if not f.is_file():
        return None
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def readiness(repo: Path) -> Readiness:
    repo = Path(repo).expanduser()
    return Readiness(
        path=repo,
        marker=read_marker(repo),
        legacy_charter=(repo / LEGACY_MARKER).is_file(),
        has_agents_dir=(repo / ".claude" / "agents").is_dir(),
    )


def _write_marker(repo: Path, *, lab: str, agents: list[str],
                  ready_since: str | None = None) -> Path:
    marker = {
        "murmurent": MARKER_SCHEMA,
        "lab": lab or "",
        "ready_since": ready_since or _dt.date.today().isoformat(),
        "bootstrap_version": _version(),
        "agents": sorted(set(agents or [])),
    }
    f = Path(repo) / MARKER_FILENAME
    f.write_text(yaml.safe_dump(marker, sort_keys=False), encoding="utf-8")
    return f


def ensure_marker(repo: Path, *, lab: str = "",
                  agents: list[str] | None = None) -> Path:
    """Idempotently write the ``.murmurent.yaml`` readiness marker.

    Preserves an existing marker (keeps its recorded agent picks when
    ``agents`` is None). Used by paths that make a repo ready but do their
    own CC bootstrap — e.g. :mod:`core.projectize`, which writes a project's
    CHARTER + registry + manifest and now also stamps the readiness marker so
    a project repo is marker-ready (not CHARTER-ready). Returns the marker path.
    """
    repo = Path(repo).expanduser()
    existing = read_marker(repo)
    if existing is not None and agents is None:
        return repo / MARKER_FILENAME
    picked = list(agents) if agents is not None else list(
        (existing or {}).get("agents") or [])
    return _write_marker(
        repo, lab=lab or str((existing or {}).get("lab") or ""),
        agents=picked,
        ready_since=str((existing or {}).get("ready_since") or "") or None)


def make_ready(clone_path: Path, *, lab: str = "",
               agents: list[str] | None = None,
               murmurent_root: Path | None = None) -> list[Probe]:
    """Make ``clone_path`` murmurent-ready: marker + CC bootstrap.

    Deliberately does NOT create a project, write a charter, or touch
    the lab registry — attach the repo to a project separately. ``lab``
    is recorded so multi-lab machines know whose commons this repo
    follows. Idempotent: an existing marker is preserved (its agent
    picks win when ``agents`` is None); re-running refreshes symlinks.
    """
    from . import project_cc_init as _cci

    repo = Path(clone_path).expanduser()
    probes: list[Probe] = []
    existing = read_marker(repo)
    picked = list(agents) if agents is not None else list(
        (existing or {}).get("agents") or [])

    if existing is not None and agents is None:
        probes.append(Probe(name="marker", status="ok",
                            detail=f"{MARKER_FILENAME} already present — kept",
                            required=False))
    else:
        f = _write_marker(repo, lab=lab or str((existing or {}).get("lab") or ""),
                          agents=picked,
                          ready_since=str((existing or {}).get("ready_since") or "") or None)
        probes.append(Probe(name="marker", status="ok",
                            detail=f"wrote {f}", required=False))

    root = murmurent_root or murmurent_repo_root()
    probes.extend(_cci.bootstrap_local(repo, root, agents=picked,
                                       project_name=repo.name))
    return probes


def upgrade(clone_path: Path, *, add_agents: list[str] | None = None,
            all_agents: bool = False,
            murmurent_root: Path | None = None) -> list[Probe]:
    """Bring a ready repo up to the current murmurent release.

    - Legacy CHARTER.md bootstrap → a ``.murmurent.yaml`` marker is stamped
      (lab lifted from the charter). The CHARTER.md is **preserved** — it may
      be a project document (project/lead/members) still read by
      :mod:`core.projects`; readiness simply stops keying on it (issue #28,
      never drop project metadata during migration).
    - Marker schema migrated; ``bootstrap_version`` re-stamped.
    - Agent symlinks re-created against the current commons; new agents
      join via ``add_agents`` or ``all_agents=True`` (every commons
      agent). Content updates never need this — symlinks track the
      commons clone automatically.
    """
    repo = Path(clone_path).expanduser()
    r = readiness(repo)
    if not (r.marker or r.legacy_charter):
        return [Probe(name="upgrade", status="fail",
                      detail=f"{repo} is not murmurent-ready — adopt it first",
                      required=True)]
    probes: list[Probe] = []
    lab = str((r.marker or {}).get("lab") or "")
    agents = list((r.marker or {}).get("agents") or [])

    if r.legacy_charter and r.marker is None:
        # Stamp the marker from the legacy CHARTER bootstrap: lift the lab and
        # any existing agent links out of it. The CHARTER.md is PRESERVED — it
        # may be a project document still read by core.projects; readiness no
        # longer keys on it, so it just stops being a bootstrap marker (issue
        # #28). If it holds project metadata not yet in cert_projects, run
        # `cert_projects.backfill_from_charter()` to register it.
        try:
            from .frontmatter import parse_file
            meta = parse_file(repo / LEGACY_MARKER).meta or {}
            lab = str(meta.get("lab") or "")
        except Exception:  # noqa: BLE001
            pass
        agents_dir = repo / ".claude" / "agents"
        if agents_dir.is_dir():
            agents = sorted(p.stem for p in agents_dir.iterdir()
                            if p.suffix == ".md")
        probes.append(Probe(name="upgrade", status="ok",
                            detail=f"stamped {MARKER_FILENAME} from legacy "
                                   "CHARTER.md bootstrap (CHARTER.md preserved)",
                            required=False))

    root = murmurent_root or murmurent_repo_root()
    if all_agents:
        commons = root / "agents"
        if commons.is_dir():
            agents = sorted(p.stem for p in commons.glob("*.md"))
    for a in (add_agents or []):
        if a not in agents:
            agents.append(a)

    _write_marker(repo, lab=lab, agents=agents,
                  ready_since=str((r.marker or {}).get("ready_since") or "") or None)
    probes.append(Probe(name="marker", status="ok",
                        detail=f"schema {MARKER_SCHEMA}, bootstrap_version "
                               f"{_version()}", required=False))
    from . import project_cc_init as _cci
    probes.extend(_cci.bootstrap_local(repo, root, agents=agents,
                                       project_name=repo.name))
    return probes
