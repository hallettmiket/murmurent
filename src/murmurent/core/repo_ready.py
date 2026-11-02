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
from .commons import commons_root

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
    has_agents_dir: bool = False        # .claude/agents/ exists (informational only)

    @property
    def ready(self) -> bool:
        # Readiness keys on the .murmurent.yaml marker ONLY (issue #28). A
        # legacy CHARTER.md no longer signals readiness — it's a project
        # document (project/lead/members), not a bootstrap marker. Repos that
        # only carry a CHARTER migrate via `murmurent repo upgrade`, which
        # stamps a marker and PRESERVES the CHARTER.
        #
        # .claude/agents/ plays no part (PR #167). It used to be required to
        # EXIST, which said nothing: adopt creates it before linking anything.
        # Counting links instead would be wrong too. Every agent already works
        # in every folder from ~/.claude/agents/; a link here only pins one,
        # and the marker is what turns on what readiness is for: the PHI check,
        # activity attribution, and joining a project.
        return self.marker is not None

    @property
    def needs_upgrade(self) -> bool:
        """True when a marker-ready repo was bootstrapped by an older marker
        shape (schema lags), when this machine last linked it under another
        murmurent release, OR when a repo still carries only a legacy
        CHARTER.md bootstrap and wants a one-time marker stamp.

        The release that linked a repo is a fact about this machine, kept in
        ``~/.murmurent/repo_bootstrap.yaml`` (#257). It used to be written
        into the committed marker as ``bootstrap_version``, so two machines on
        different releases pushed that line back and forth; a marker that
        still carries the line is read as a fallback and never rewritten."""
        if self.marker is None:
            return self.legacy_charter
        if int(self.marker.get("murmurent") or 0) < MARKER_SCHEMA:
            return True
        recorded = bootstrap_version_of(self.path) or \
            str(self.marker.get("bootstrap_version") or "")
        return recorded != _version()


def _bootstrap_record_file() -> Path:
    import os
    return Path(os.environ.get("MURMURENT_HOME") or Path.home() / ".murmurent") / "repo_bootstrap.yaml"


def _read_bootstrap_record() -> dict[str, str]:
    try:
        data = yaml.safe_load(_bootstrap_record_file().read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - no record means "never linked here"
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _repo_key(repo: Path) -> str:
    from .repo import repo_name as _repo_name
    return _repo_name(Path(repo).expanduser())


def record_bootstrap(repo: Path, version: str | None = None) -> None:
    """Note, for this machine only, which murmurent release last linked
    ``repo`` (#257). Best-effort."""
    data = _read_bootstrap_record()
    data[_repo_key(repo)] = str(version or _version())
    try:
        _bootstrap_record_file().parent.mkdir(parents=True, exist_ok=True)
        _bootstrap_record_file().write_text(yaml.safe_dump(data, sort_keys=True),
                                            encoding="utf-8")
    except OSError:
        pass


def bootstrap_version_of(repo: Path) -> str:
    """The release that last linked ``repo`` on this machine, or ''."""
    return _read_bootstrap_record().get(_repo_key(repo), "")


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


#: The marker fields readiness owns. Every other field belongs to someone else
#: (a choreography's ``kind: choreography`` declaration, for one) and is kept.
READINESS_FIELDS: tuple[str, ...] = (
    "murmurent", "lab", "ready_since", "bootstrap_version", "agents",
)


def _write_marker(repo: Path, *, lab: str, agents: list[str],
                  ready_since: str | None = None) -> Path:
    """Write the readiness fields, keeping every other field already there.

    This used to write the five readiness fields and nothing else, so
    ``repo upgrade`` (and ``adopt --all-agents`` on a ready repo) silently
    erased a choreography's declaration, after which ``choreography install``
    refused the repo as not being one.
    """
    existing = read_marker(repo) or {}
    marker = {
        "murmurent": MARKER_SCHEMA,
        "lab": lab or "",
        "ready_since": ready_since or _dt.date.today().isoformat(),
        "agents": sorted(set(agents or [])),
    }
    # ``bootstrap_version`` is no longer written (#257): the release that
    # linked a repo is per machine. A marker that already carries the line
    # keeps it as it is, so an upgrade never dirties a committed file for it.
    if existing.get("bootstrap_version"):
        marker["bootstrap_version"] = existing["bootstrap_version"]
    for key, value in existing.items():
        if key not in READINESS_FIELDS:
            marker[key] = value
    f = Path(repo) / MARKER_FILENAME
    text = yaml.safe_dump(marker, sort_keys=False)
    if existing and existing == marker:
        return f                      # nothing changed: leave the file alone
    f.write_text(text, encoding="utf-8")
    return f


def update_marker(repo: Path, fields: dict) -> Path:
    """Merge ``fields`` into an existing marker, leaving readiness fields alone.

    For a caller that owns fields other than readiness, such as the choreography
    declaration. Refuses to create a marker: a repo is made ready by
    :func:`make_ready`, not by acquiring unrelated fields.
    """
    repo = Path(repo).expanduser()
    marker = read_marker(repo)
    if marker is None:
        raise FileNotFoundError(
            f"{repo / MARKER_FILENAME} does not exist; make the repo ready first")
    clash = sorted(set(fields) & set(READINESS_FIELDS))
    if clash:
        raise ValueError(f"readiness owns these marker fields: {', '.join(clash)}")
    marker.update(fields)
    f = repo / MARKER_FILENAME
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


#: Files make ready writes that belong in the repository: the marker, the
#: CLAUDE.md stub, and the .gitignore lines that keep agent links out.
READINESS_FILES: tuple[str, ...] = (MARKER_FILENAME, "CLAUDE.md", ".gitignore")
READINESS_COMMIT_MESSAGE = "Make this repository murmurent-ready"


def commit_readiness(repo: Path, *, message: str = READINESS_COMMIT_MESSAGE) -> Probe:
    """Commit the readiness files, and only them, so readiness travels with
    every clone (#257). Never touches anything else staged. A repository that
    is not git, or where git cannot commit, gets a probe saying what to run."""
    import subprocess
    repo = Path(repo).expanduser()
    if not (repo / ".git").exists():
        return Probe(name="commit", status="ok", required=False,
                     detail="not a git repository; nothing to commit")
    files = [f for f in READINESS_FILES if (repo / f).is_file()]
    hint = (f"commit them yourself: git add {' '.join(files)} && "
            f"git commit -m \"{message}\" -- {' '.join(files)}")
    try:
        subprocess.run(["git", "-C", str(repo), "add", "--", *files],
                       check=True, capture_output=True, text=True, timeout=30)
        staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet",
                                 "--", *files], capture_output=True, text=True, timeout=30)
        if staged.returncode == 0:
            return Probe(name="commit", status="ok", required=False,
                         detail="readiness files already committed")
        done = subprocess.run(["git", "-C", str(repo), "commit", "-q", "--only",
                               "-m", message, "--", *files],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return Probe(name="commit", status="warn", required=False,
                     detail=f"could not commit ({exc}); {hint}")
    if done.returncode != 0:
        why = (done.stderr or done.stdout or "git commit failed").strip().splitlines()
        return Probe(name="commit", status="warn", required=False,
                     detail=f"could not commit ({why[0] if why else '?'}); {hint}")
    return Probe(name="commit", status="ok", required=False,
                 detail=f"committed {', '.join(files)}: push, and every clone is ready")


def register_ready_clones(repos_root: Path | None = None) -> list[Path]:
    """Note every murmurent-ready repository under the repositories folder on
    this machine (#257): a clone made by hand on a second machine, carrying
    the committed marker, is then found by name like one adopted here.
    Returns the repositories seen. Writes only this machine's path record."""
    from . import repo_paths as _rp
    from .repo import repos_root as _repos_root
    root = Path(repos_root) if repos_root else _repos_root()
    if not root.is_dir():
        return []
    tops = sorted(c for c in root.iterdir() if c.is_dir())
    nested = [g for t in tops if not (t / ".git").exists()
              for g in sorted(t.iterdir()) if g.is_dir() and (g / ".git").exists()]
    seen: list[Path] = []
    for child in tops + nested:
        if (child / MARKER_FILENAME).is_file() and (child / ".git").exists():
            _rp.record(_repo_key(child), child)
            seen.append(child)
    return seen


def make_ready(clone_path: Path, *, lab: str = "",
               agents: list[str] | None = None,
               murmurent_root: Path | None = None,
               commit: bool = True) -> list[Probe]:
    """Make ``clone_path`` murmurent-ready: marker + CC bootstrap.

    The agent symlinks point into :func:`commons.commons_root` — the same
    commons ``murmurent setup``, ``install`` and ``doctor`` read, which is the
    clone you installed rather than whatever sits at ``~/repos/murmurent``.
    This used to call ``repo.murmurent_repo_root()`` instead, and the two
    disagree on a machine holding both a release clone and a development one:
    ``doctor`` would report the commons coming from ``~/repos/murmurent_dev``
    while the repo adopted a moment earlier was linked into
    ``~/repos/murmurent``. An agent edited in the clone you are working on was
    then live in ``~/.claude/agents/`` and silently absent from the repo, which
    is the worst shape a failure like this can take: no error, and the thing
    you just changed appears not to work.

    Deliberately does NOT create a project, write a charter, or touch
    the lab registry — attach the repo to a project separately. ``lab``
    is recorded so multi-lab machines know whose commons this repo
    follows. Idempotent: an existing marker is preserved (its agent
    picks win when ``agents`` is None); re-running refreshes symlinks.

    The marker, the CLAUDE.md stub and the .gitignore lines are committed
    (``commit=True``) so readiness travels with every clone (#257); nothing
    else staged is touched. The release that did the linking is recorded for
    this machine only.
    """
    from . import project_cc_init as _cci

    repo = Path(clone_path).expanduser()
    name = _repo_key(repo)
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

    root = murmurent_root or commons_root()
    probes.extend(_cci.bootstrap_local(repo, root, agents=picked,
                                       project_name=name))
    # Note where this repository is on this machine (#166), so it is found
    # wherever it sits, including inside a project folder, and which release
    # linked it (#257). The name is the main copy's, not a worktree folder's.
    from . import repo_paths as _rp
    _rp.record(name, repo)
    record_bootstrap(repo)
    if commit:
        probes.append(commit_readiness(repo))
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

    root = murmurent_root or commons_root()
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
                        detail=f"schema {MARKER_SCHEMA}; linked here by murmurent "
                               f"{_version()}", required=False))
    from . import project_cc_init as _cci
    name = _repo_key(repo)
    probes.extend(_cci.bootstrap_local(repo, root, agents=agents, project_name=name))
    # A clone that arrived with the marker (a second machine) is registered
    # the first time install or upgrade sees it (#257).
    from . import repo_paths as _rp
    _rp.record(name, repo)
    record_bootstrap(repo)
    return probes
