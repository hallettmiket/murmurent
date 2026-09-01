"""
Purpose: THIS-machine + cross-GitHub git-repo inventory for the dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15 (this-machine-only since 2026-07, issue #94)
Input: Lab's GitHub org (``lab.md:github_org``), this machine's scan dirs
       (the ``local`` host's ``scan_dirs``, defaulting to ``~/repo`` +
       ``~/repos``; both ``$HOME``-relative and absolute paths are accepted),
       and this machine's private-repo exclusions (``exclude.yaml``).
Output: ``InventoryReport`` — list of rows keyed by canonical origin URL,
        each row carrying this-machine presence + murmurent-ready signals.

Why this module exists: the dashboard's "Repos" panel surfaces THIS
machine's repos cross-referenced against the lab's GitHub org, so the
user can see at a glance which repos are murmurent-ready here, which are
GitHub-only (could be cloned to this machine), and which are local-only
(at risk of loss because they have no GitHub remote).

Scope (issue #94): the inventory is **this-machine-only**. The retired
"SSH into every registered host and scan it" sweep is gone — under the
per-machine model each machine runs its own dashboard, and you view
another machine's repos by tunnelling to ITS dashboard
(``docs/remote_dashboard.md``), not by driving it from here.

The inventory is **cheap to re-run** (one local ``find`` pass, one
``gh repo list`` per org) so the dashboard's Refresh button can fire it
on demand without paying for an agent loop.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import Any

import yaml

from . import hosts as _hosts
from . import remote as _remote

INVENTORY_DIR = Path.home() / ".murmurent" / "inventory"
SCAN_INTERVAL_DAYS = 7  # weekly refresh
DEFAULT_SCAN_DIRS = ("repo", "repos")  # under each host's $HOME


# ---------------------------------------------------------------------------
# Private repos — where the local/lab line gets drawn
# ---------------------------------------------------------------------------

EXCLUDE_FILE = INVENTORY_DIR / "exclude.yaml"


def _ensure_inventory_dir_private() -> None:
    """Create ``INVENTORY_DIR`` owner-only, tightening what is already there.

    Also chmods pre-existing reports, so a data root created before this
    hardening stops being world-readable on the next write rather than
    staying at the umask default forever.
    """
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        INVENTORY_DIR.chmod(0o700)
        for f in list(INVENTORY_DIR.glob("inventory_*.yaml")) + [EXCLUDE_FILE]:
            if f.exists():
                f.chmod(0o600)
    except OSError:  # a path we cannot chmod is not worth failing a scan over
        pass


def _write_owner_only(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` readable by its owner alone (0600).

    An inventory report lists every repo path on the machine, and the
    exclude file names the repos deliberately kept private — neither
    belongs at the 0644 a default umask hands out, which on a shared lab
    server is readable by every account on the box. The descriptor is
    opened 0600 up front rather than chmod'd afterwards so the content is
    never even briefly world-readable; the trailing chmod covers a file
    that already existed at looser permissions.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass



def load_exclusions() -> tuple[str, ...]:
    """Glob patterns naming repos this machine must NOT inventory.

    Read from ``~/.murmurent/inventory/exclude.yaml``. The file is
    machine-local and never published — it is the user's own answer to
    "this clone is mine, not the lab's".

    Why this exists: ``~/repos`` is where *everything* goes, personal
    work included, and the scan takes every git repo it finds there. A
    private repo therefore lands in the dashboard's Repos panel rendered
    as lab work pending adoption ("not ready · Make ready"), which is
    exactly backwards — lab membership should be opt-in. Excluded repos
    are dropped at scan time, so they never reach the report on disk;
    this is a privacy boundary, not a display filter.

    Accepts either a bare list or a ``patterns:`` mapping. A malformed or
    unreadable file yields no patterns rather than raising — a bad
    exclude file must never take the whole inventory down.
    """
    try:
        raw = yaml.safe_load(EXCLUDE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except Exception:  # noqa: BLE001 — malformed file, not a scan failure
        return ()
    if isinstance(raw, dict):
        raw = raw.get("patterns")
    if not isinstance(raw, list):
        return ()
    return tuple(str(x).strip() for x in raw if str(x).strip())


def exclusions_error() -> str | None:
    """Why the exclude file could not be read, or ``None`` when it is fine.

    :func:`load_exclusions` deliberately fails **open** — a typo in the
    exclude file must not take the whole Repos panel down. But failing
    open means private repos quietly become visible again, which is the
    one outcome the user must never discover by seeing it on screen. So
    the parse failure is surfaced in the report's ``errors`` banner.
    """
    if not EXCLUDE_FILE.exists():
        return None
    try:
        raw = yaml.safe_load(EXCLUDE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — any parse/IO failure reads the same
        return (f"{EXCLUDE_FILE.name} unreadable ({exc.__class__.__name__}) — "
                "private repos are NOT being hidden")
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("patterns")
        if raw is None:
            return None
    if not isinstance(raw, list):
        return (f"{EXCLUDE_FILE.name}: expected a list of patterns — "
                "private repos are NOT being hidden")
    return None


def is_excluded(path: str, patterns: tuple[str, ...] = ()) -> bool:
    """True when ``path`` matches any exclusion pattern.

    A pattern matches either the repo's **basename** (``cmwim_website``)
    or its **full path** (``~/personal/*``), so the common case is just
    the repo name while a whole tree can still be excluded in one line.
    ``~`` in a pattern expands to the user's home.
    """
    if not patterns:
        return False
    target = str(path).rstrip("/")
    name = PurePath(target).name
    for pat in patterns:
        pat = pat.rstrip("/")
        if not pat:
            continue
        full = str(Path(pat).expanduser()) if pat.startswith("~") else pat
        if fnmatch(name, pat) or fnmatch(target, full):
            return True
    return False


def _write_exclusions(patterns: list[str]) -> None:
    """Persist the exclude file (sorted + deduped), creating the dir."""
    _ensure_inventory_dir_private()
    _write_owner_only(
        EXCLUDE_FILE,
        "# Repos on this machine that murmurent must not inventory.\n"
        "# Machine-local; never published to the lab. A pattern matches a\n"
        "# repo's basename (cmwim_website) or its full path (~/personal/*).\n"
        "# Manage with: murmurent repo private add|remove|list\n"
        + yaml.safe_dump({"patterns": sorted(set(patterns))}, sort_keys=False),
    )


def add_exclusion(pattern: str) -> tuple[str, ...]:
    """Mark ``pattern`` private; return the full pattern set afterwards."""
    pattern = (pattern or "").strip()
    if not pattern:
        raise ValueError("empty exclusion pattern")
    current = list(load_exclusions())
    if pattern not in current:
        current.append(pattern)
    _write_exclusions(current)
    return tuple(sorted(set(current)))


def remove_exclusion(pattern: str) -> tuple[str, ...]:
    """Un-mark ``pattern``; return the full pattern set afterwards."""
    pattern = (pattern or "").strip()
    current = [x for x in load_exclusions() if x != pattern]
    _write_exclusions(current)
    return tuple(sorted(set(current)))


def is_murmurent_infra_repo(name: str) -> bool:
    """True for murmurent's OWN repos — the commons clone (``murmurent``) and the
    ``murmurent_*`` family (``murmurent_lab_mgmt_<lab>``, ``murmurent_vault``,
    ``murmurent_public``, ``murmurent_dev``, …). These are murmurent
    infrastructure, not project working repos: they must never be "made ready"
    (a repo can't adopt itself; a lab-mgmt clone is governance, not a project).
    The dashboard flags them and disables their make-ready button (#41 pt 5)."""
    n = (name or "").strip().rsplit("/", 1)[-1]
    return n == "murmurent" or n.startswith("murmurent_")


@dataclass
class RepoOnHost:
    """One clone of a project, on one machine."""

    host: str                       # "local" / "lab-server"
    path: str                       # ``$HOME/repos/<name>`` absolute on the host
    origin_url: str                 # "" when the repo has no ``origin`` remote
    has_marker: bool                # readiness marker (.murmurent.yaml)
    has_claude_dir: bool            # ``.claude/agents/`` exists
    is_murmurent_ready: bool        # marker + .claude/agents — the repo is murmurent-ready
    is_murmurent_infra: bool = False  # murmurent's own repo — never "made ready" (#41 pt 5)
    is_git: bool = True             # a git repo (False = a plain project folder, #49)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GitHubRepo:
    """One repo on the GitHub side. Sparse — we only carry fields the
    dashboard actually displays."""

    name: str                       # bare repo name (no org prefix)
    full_name: str                  # ``<org>/<name>``
    ssh_url: str                    # ``git@github.com:<org>/<name>.git``
    visibility: str                 # ``public`` / ``private`` / ``internal``
    updated_at: str                 # ISO timestamp
    archived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InventoryRow:
    """A single project row in the cross-referenced report.

    Keyed by canonical origin URL. A row may have GitHub-side metadata,
    per-machine clones, both, or neither (the last would be filtered
    out — a row with no presence has nothing to display).
    """

    key: str                                # origin URL or local-only synthetic id
    name: str                               # display name (basename of repo)
    github: GitHubRepo | None = None        # None when no matching GitHub repo
    clones: list[RepoOnHost] = field(default_factory=list)
    local_only: bool = False                # True when no GitHub origin found

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "github": self.github.to_dict() if self.github else None,
            "clones": [c.to_dict() for c in self.clones],
            "local_only": self.local_only,
        }


@dataclass
class InventoryReport:
    """The full cross-referenced report."""

    generated_at: str
    github_org: str
    hosts_scanned: list[str]
    rows: list[InventoryRow]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "github_org": self.github_org,
            "hosts_scanned": self.hosts_scanned,
            "rows": [r.to_dict() for r in self.rows],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# GitHub side — uses ``gh repo list`` so we inherit the user's existing auth
# ---------------------------------------------------------------------------


def list_github_repos(org: str, *, limit: int = 500) -> tuple[list[GitHubRepo], str | None]:
    """List every repo under ``org`` the authenticated user can see.

    Returns ``(repos, error)``. ``error`` is non-None when the call
    can't be made at all (gh CLI missing, not authenticated). An empty
    repo list with no error means the user genuinely has no repos in
    that org.
    """
    if not org:
        return [], "no GitHub org configured (set lab_settings.github_org)"
    if not shutil.which("gh"):
        return [], "gh CLI not installed on this machine"
    try:
        res = subprocess.run(  # noqa: S603
            [
                "gh", "repo", "list", org,
                "--limit", str(limit),
                "--json", "name,nameWithOwner,sshUrl,visibility,updatedAt,isArchived",
            ],
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"gh repo list failed: {exc}"
    if res.returncode != 0:
        return [], (res.stderr or res.stdout or "gh repo list non-zero exit").strip()
    try:
        data = json.loads(res.stdout or "[]")
    except json.JSONDecodeError as exc:
        return [], f"gh repo list returned malformed JSON: {exc}"
    out: list[GitHubRepo] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(GitHubRepo(
            name=str(entry.get("name") or ""),
            full_name=str(entry.get("nameWithOwner") or ""),
            ssh_url=str(entry.get("sshUrl") or ""),
            visibility=str(entry.get("visibility") or "").lower(),
            updated_at=str(entry.get("updatedAt") or ""),
            archived=bool(entry.get("isArchived")),
        ))
    return out, None


# ---------------------------------------------------------------------------
# Local scan — one local ``find`` pass produces all rows for THIS machine
# ---------------------------------------------------------------------------


def _scan_script(scan_dirs: tuple[str, ...]) -> str:
    """Bash snippet that lists every git repo under each scan dir +
    prints one record per line.

    Each entry in ``scan_dirs`` may be absolute (starts with ``/``) or
    ``$HOME``-relative. Absolute entries are used verbatim on the
    remote; relative ones are resolved against the host's ``$HOME``.
    This lets a host scan both ``~/repos`` and a shared mount like
    ``/srv/projects`` in the same pass.

    Output format: ``<path>|<origin>|<has_marker>|<has_claude_agents>|<is_git>``
    where ``has_marker`` (readiness marker: .murmurent.yaml — a legacy
    CHARTER.md no longer counts, issue #28), ``has_claude_agents``, and
    ``is_git`` are 1/0. Uses ``|`` because git remote URLs can contain ``:``
    (ssh form).

    Two passes so nothing under a scan dir silently disappears from the
    repo manager (#49):
      1. **Git repos** at depth 2--3 --- ``.git`` matched as a directory OR a
         FILE, so linked worktrees and submodule clones are found, not just
         plain clones (the previous ``-type d`` missed worktrees).
      2. **Non-git project folders** --- every immediate child directory of a
         scan dir that is neither a git repo itself nor a container of git
         repos (a plain ``~/repos/<project>`` the user has not ``git init``'d,
         or has not cloned as git). These are emitted with ``is_git=0`` so the
         dashboard can show them (marked "not a git repo") instead of dropping
         them.
    """
    quoted = " ".join(shlex.quote(d) for d in scan_dirs)
    return (
        f'for base in {quoted}; do '
        '  case "$base" in '
        '    /*) full="$base" ;; '
        '    "~/"*) full="$HOME/${base#"~/"}" ;; '   # ~/repos -> $HOME/repos
        '    "~") full="$HOME" ;; '
        '    *)  full="$HOME/$base" ;; '
        '  esac; '
        '  [ -d "$full" ] || continue; '
        # (1) Git repos (depth 2-3). ``-name .git`` (no -type) matches a .git
        # directory AND a .git file (worktrees/submodules).
        '  find "$full" -mindepth 2 -maxdepth 3 -name .git 2>/dev/null | '
        '  while IFS= read -r gitdir; do '
        '    repo=$(dirname "$gitdir"); '
        '    url=$(git -C "$repo" remote get-url origin 2>/dev/null); '
        '    marked=0; [ -f "$repo/.murmurent.yaml" ] && marked=1; '
        '    claude=0; [ -d "$repo/.claude/agents" ] && claude=1; '
        '    echo "$repo|$url|$marked|$claude|1"; '
        '  done; '
        # (2) Non-git immediate child folders (plain project dirs).
        '  for child in "$full"/*/; do '
        '    [ -d "$child" ] || continue; child="${child%/}"; '
        '    [ -e "$child/.git" ] && continue; '   # it IS a git repo -> pass (1)
        # skip a container folder that holds git repos one level down; its
        # repos are already emitted by pass (1).
        '    if find "$child" -mindepth 1 -maxdepth 2 -name .git 2>/dev/null | grep -q .; then continue; fi; '
        '    marked=0; [ -f "$child/.murmurent.yaml" ] && marked=1; '
        '    claude=0; [ -d "$child/.claude/agents" ] && claude=1; '
        '    echo "$child||$marked|$claude|0"; '
        '  done; '
        'done'
    )


def _effective_scan_dirs(host: _hosts.Host) -> tuple[str, ...]:
    """Return the scan dirs to use for ``host``.

    Falls back to :data:`DEFAULT_SCAN_DIRS` when the host has none
    configured, so existing registries keep their current behaviour
    without an explicit ``scan_dirs:`` field.
    """
    return host.scan_dirs or DEFAULT_SCAN_DIRS


def list_machine_repos(host_name: str = _hosts.LOCAL_NAME) -> tuple[list[RepoOnHost], str | None]:
    """List every git repo on THIS machine under the conventional scan dirs.

    Issue #94: this is a **local-only** scan. The retired cross-machine
    sweep used to SSH into foreign hosts; it no longer does. A caller that
    passes a remote (``ssh``-kind) host name gets an explanatory error
    rather than an SSH round-trip — view that machine's repos on its own
    dashboard instead (``docs/remote_dashboard.md``). The scan itself runs
    the ``find`` script in a local shell (no network).

    Returns ``(repos, error)``. ``error`` is non-None for a bad/remote host
    or a scan failure; an empty list with no error means this machine
    genuinely has no repos in the scan dirs.
    """
    try:
        host = _hosts.resolve(host_name)
    except _hosts.HostNotFound as exc:
        return [], str(exc)
    except _hosts.HostError as exc:
        return [], str(exc)
    if host.is_remote():
        return [], (
            f"cross-machine repo scan retired (issue #94): {host_name!r} is a "
            "remote host — open its own dashboard (see docs/remote_dashboard.md)"
        )
    remote = _remote.Remote(host)
    try:
        res = remote.run(_scan_script(_effective_scan_dirs(host)), check=False, timeout=60)
    except _remote.RemoteError as exc:
        return [], (exc.stderr or str(exc)).strip() or "ssh failed"
    if not res.ok:
        return [], (res.stderr or "").strip() or f"scan exited rc={res.returncode}"
    out: list[RepoOnHost] = []
    excluded = load_exclusions()
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 4:
            continue
        path, origin, marked, claude = parts[:4]
        # Private repos are dropped HERE, before the row is built, so an
        # excluded clone's path + origin URL never reach the report file.
        if is_excluded(path, excluded):
            continue
        is_git = parts[4] if len(parts) >= 5 else "1"  # tolerate 4-field output
        out.append(RepoOnHost(
            host=host_name,
            path=path,
            origin_url=origin,
            has_marker=marked == "1",
            has_claude_dir=claude == "1",
            # "murmurent-ready" = readiness marker + .claude/agents —
            # the repo-side state, independent of any project.
            is_murmurent_ready=(marked == "1" and claude == "1"),
            is_murmurent_infra=is_murmurent_infra_repo(path),
            is_git=is_git == "1",
        ))
    return out, None


# ---------------------------------------------------------------------------
# Cross-reference
# ---------------------------------------------------------------------------


def _canonical_url(url: str) -> str:
    """Normalize a git remote URL so HTTPS + SSH forms collide on the
    same key. ``git@github.com:<org>/<name>.git`` ←→
    ``https://github.com/<org>/<name>.git`` ←→ ``…/<org>/<name>``
    (any trailing ``.git`` dropped).
    """
    s = url.strip()
    if not s:
        return ""
    s = s.lower()
    if s.startswith("git@github.com:"):
        s = "github.com/" + s[len("git@github.com:"):]
    elif s.startswith("https://github.com/"):
        s = "github.com/" + s[len("https://github.com/"):]
    elif s.startswith("http://github.com/"):
        s = "github.com/" + s[len("http://github.com/"):]
    elif s.startswith("ssh://git@github.com/"):
        s = "github.com/" + s[len("ssh://git@github.com/"):]
    if s.endswith(".git"):
        s = s[:-4]
    return s.rstrip("/")


def build_inventory(
    *,
    github_org: str,
) -> InventoryReport:
    """Build the cross-referenced report for THIS machine.

    Issue #94: this-machine-only. GitHub repos seed the rows; the local
    scan then attaches this machine's clones to matching keys (or creates
    a new local-only row when no GitHub match exists).

    Best-effort: when ``gh`` is offline the GitHub side is simply missing.
    Errors accumulate in :attr:`InventoryReport.errors` so the UI can
    surface them as a banner.
    """
    errors: list[str] = []

    gh_repos, gh_err = list_github_repos(github_org)
    if gh_err:
        errors.append(f"github: {gh_err}")

    # Build a key→row map keyed on canonical URLs. GitHub repos seed
    # the map; the local scan then attaches this machine's clones to
    # matching keys (or creates a new local-only row when no GitHub
    # match exists).
    excluded = load_exclusions()
    exc_err = exclusions_error()
    if exc_err:
        errors.append(f"private-repos: {exc_err}")
    rows: dict[str, InventoryRow] = {}
    for gh in gh_repos:
        if gh.archived:
            continue
        # A private repo stays private even when it lives in the lab's org.
        if is_excluded(gh.name, excluded):
            continue
        key = _canonical_url(gh.ssh_url)
        if not key:
            continue
        rows[key] = InventoryRow(key=key, name=gh.name, github=gh)

    hosts_scanned: list[str] = []
    clones, host_err = list_machine_repos(_hosts.LOCAL_NAME)
    if host_err:
        errors.append(f"{_hosts.LOCAL_NAME}: {host_err}")
    else:
        hosts_scanned.append(_hosts.LOCAL_NAME)
        for c in clones:
            key = _canonical_url(c.origin_url)
            if not key:
                # Local-only repo (no origin). Synthesize a key from
                # the path so the row stays distinct from other repos.
                key = f"local-only:{_hosts.LOCAL_NAME}:{c.path}"
                rows.setdefault(key, InventoryRow(
                    key=key, name=Path(c.path).name, local_only=True,
                ))
            elif key not in rows:
                # Has an origin we didn't see on the GitHub side
                # (e.g. Bitbucket, a different org, or a repo not
                # accessible to gh). Treat as a row with no github
                # metadata but a canonical origin key.
                rows[key] = InventoryRow(
                    key=key, name=Path(c.path).name,
                )
            rows[key].clones.append(c)

    # Sort rows for deterministic display: github-bearing first
    # (alphabetical by name), then non-github / local-only.
    sorted_rows = sorted(
        rows.values(),
        key=lambda r: (r.github is None, r.name.lower()),
    )

    return InventoryReport(
        generated_at=_dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        github_org=github_org,
        hosts_scanned=hosts_scanned,
        rows=sorted_rows,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Cache layer — write the latest report; the dashboard reads it back
# ---------------------------------------------------------------------------


def latest_report_path() -> Path | None:
    """Return the most recent report on disk, or ``None`` when none
    have been generated yet."""
    if not INVENTORY_DIR.is_dir():
        return None
    candidates = sorted(INVENTORY_DIR.glob("inventory_*.yaml"))
    return candidates[-1] if candidates else None


def write_report(report: InventoryReport) -> Path:
    """Persist a report under a date-stamped filename. Returns the path."""
    _ensure_inventory_dir_private()
    stamp = report.generated_at[:19].replace(":", "")  # filesystem-safe
    path = INVENTORY_DIR / f"inventory_{stamp}.yaml"
    _write_owner_only(
        path,
        yaml.safe_dump(report.to_dict(), sort_keys=False, allow_unicode=True),
    )
    return path


def load_report(path: Path) -> dict | None:
    """Load a previously-written report. Returns ``None`` on missing /
    malformed. Returns the raw dict (not the dataclass) because the
    dashboard's response body just round-trips it."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or None
    except (OSError, yaml.YAMLError):
        return None


def purge_excluded_from_cache() -> int:
    """Strip currently-excluded repos from EVERY cached report on disk.

    Returns the number of rows dropped. A row whose clones are all
    excluded goes entirely; a row with a mix keeps the clones that
    remain. Every report is rewritten, not just the newest, because the
    point of marking a repo private is that its path and origin URL stop
    being recorded — a stale report on disk is still a record.

    Called when a pattern is added, so the repo disappears immediately
    rather than at the next weekly scan. A privacy setting that takes a
    week to take effect is not one.
    """
    patterns = load_exclusions()
    if not patterns or not INVENTORY_DIR.is_dir():
        return 0
    dropped = 0
    for path in sorted(INVENTORY_DIR.glob("inventory_*.yaml")):
        data = load_report(path)
        if not data:
            continue
        kept: list[dict] = []
        changed = False
        for row in data.get("rows") or []:
            if is_excluded(str(row.get("name") or ""), patterns):
                dropped += 1
                changed = True
                continue
            clones = row.get("clones") or []
            live = [c for c in clones
                    if not is_excluded(str(c.get("path") or ""), patterns)]
            if len(live) == len(clones):
                kept.append(row)
                continue
            changed = True
            if clones and not live:
                dropped += 1          # every clone was private -> drop the row
                continue
            kept.append({**row, "clones": live})
        if not changed:
            continue
        data["rows"] = kept
        try:
            _write_owner_only(
                path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        except OSError:  # a report we cannot rewrite is left alone
            continue
    return dropped


def report_is_stale(path: Path | None, *, max_age_days: int = SCAN_INTERVAL_DAYS) -> bool:
    """Return True when ``path`` is missing or older than ``max_age_days``."""
    if path is None or not path.is_file():
        return True
    age = _dt.datetime.now() - _dt.datetime.fromtimestamp(path.stat().st_mtime)
    return age.days >= max_age_days


# ---------------------------------------------------------------------------
# Convenience: scan + cache in one call (used by both endpoint + cron)
# ---------------------------------------------------------------------------


def scan_and_cache(*, github_org: str) -> InventoryReport:
    """Full pipeline: build inventory (this machine) → write to cache → return.

    Don't pre-emptively wrap exceptions here — the discovery functions
    are best-effort and already accumulate their failures into
    ``report.errors``. Callers see a complete report even when the local
    scan or GitHub side errored.
    """
    report = build_inventory(github_org=github_org)
    try:
        write_report(report)
    except OSError as exc:
        report.errors.append(f"cache write failed: {exc}")
    return report
