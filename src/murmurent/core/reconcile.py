"""
Purpose: Detect + (optionally) repair drift between murmurent's recorded
         state and on-disk reality across every registered host.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-17
Input: ``~/.murmurent/installations/*.yaml`` (this-machine install
       records), the cert-project registry (``<lab-mgmt>/cert_projects/*.md`` —
       the authoritative project store that replaced the CHARTER-mirror
       registry), registered hosts (``~/.murmurent/hosts.yaml``), and the live
       state of working trees on those hosts (filesystem locally,
       SSH probe remotely).
Output: ``ReconcileReport`` — list of :class:`DriftFinding` rows.
        Dry-run by default; ``apply()`` does the actual deactivation
        (archive manifest, flip registry ``status: archived``).

What we detect (all enabled by default):

  1. **orphan_installation** — manifest at
     ``~/.murmurent/installations/<name>.yaml`` whose target working
     tree no longer exists on the host it points to. Common cause:
     user ``rm -rf``'d the clone locally, or lab-server wiped a repo.
  2. **orphan_registry** — a cert-project at
     ``<lab-mgmt>/cert_projects/<name>.md`` whose code_repo (host +
     remote_path) resolves to a tree that no longer exists. Repair flips
     ``status: archived`` in the cert-project frontmatter so the lab
     history is preserved (we don't hard-delete shared records).
  3. **missing_charter** — working tree is present on a host
     murmurent knows about, but ``CHARTER.md`` was deleted. Surfaces
     as a warning; user decides whether to re-adopt (write a fresh
     CHARTER) or remove from murmurent.
  4. **unadopted_clone** — git clone present in a scan dir but not
     yet a murmurent project. Already surfaced by the Repo Inventory
     panel; here we just include the count so the daily summary
     gives a full picture of "what's on disk vs what murmurent sees".
  5. **lab_mgmt_uncommitted / lab_mgmt_unpushed** — lab_mgmt edits
     that haven't reached the lab (members receive the roster via
     git pull, so local-only edits are invisible to everyone else).

Why dry-run by default: a transient SSH failure (lab-server down for
a reboot during the daily check) would otherwise auto-deactivate
every installation on that host. ``apply=True`` is opt-in and the
audit log records what changed.
"""

from __future__ import annotations

import datetime as _dt
import shlex
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

from . import hosts as _hosts
from . import remote as _remote
from . import repo_inventory as _inv
from .frontmatter import parse_file, dump_document


# Where install manifests live. snapshot.INSTALLATIONS_DIR is the
# runtime path; we re-import inside functions so monkeypatched tests
# pick up the override.
DEFAULT_INSTALLATIONS_DIR = Path.home() / ".murmurent" / "installations"
ARCHIVE_SUBDIR = ".archive"


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


@dataclass
class DriftFinding:
    """One row of drift, suitable for Rich-rendering and Slack posting.

    ``kind`` is one of the four detector names above. ``severity``
    is informational (``warn`` for things that probably want
    attention but don't have a clean auto-fix; ``info`` for
    unadopted clones; ``actionable`` for things ``apply()`` will fix
    when invoked).
    """

    kind: str
    severity: str            # "info" | "warn" | "actionable"
    target: str              # project name, path, etc. — the subject of the row
    host: str                # "local" / "lab-server" / etc.
    detail: str              # one-line human explanation
    suggested_action: str    # what apply() would do (or what the user should)
    artefact_path: str = ""  # absolute path to the artefact involved, when applicable

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconcileReport:
    """Result of one reconciliation pass. ``apply()`` may mutate this
    in place by appending ``applied`` entries as it goes."""

    generated_at: str
    findings: list[DriftFinding] = field(default_factory=list)
    applied: list[DriftFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def by_kind(self) -> dict[str, list[DriftFinding]]:
        out: dict[str, list[DriftFinding]] = {}
        for f in self.findings:
            out.setdefault(f.kind, []).append(f)
        return out

    def summary_line(self) -> str:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        if not counts:
            return "Clean — no drift detected."
        parts = [f"{n} {k.replace('_', ' ')}" for k, n in sorted(counts.items())]
        return "Drift: " + ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "summary": self.summary_line(),
            "findings": [f.to_dict() for f in self.findings],
            "applied": [f.to_dict() for f in self.applied],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _installations_dir() -> Path:
    """Re-import on every call so test monkeypatches of
    ``snapshot.INSTALLATIONS_DIR`` are honoured."""
    try:
        from ..dashboard.snapshot import INSTALLATIONS_DIR
        return INSTALLATIONS_DIR
    except Exception:
        return DEFAULT_INSTALLATIONS_DIR


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None


def _is_local_path_alive(path_str: str) -> bool:
    """A local working tree is 'alive' if the directory exists and
    contains a ``.git`` dir. We don't follow symlinks deeply — a
    broken symlink to a clone counts as dead."""
    if not path_str:
        return False
    p = Path(path_str).expanduser()
    return p.is_dir() and (p / ".git").exists()


def _ssh_probe_paths(host: _hosts.Host, paths: list[str]) -> dict[str, bool]:
    """Batch one SSH call per host that checks every supplied path
    in a single round-trip. Result maps path → True (clone present)
    or False (gone). Paths the SSH call couldn't decide about
    (probe error) are reported as True (don't auto-deactivate on
    ambiguous result — dry-run vs apply matters).
    """
    if not paths:
        return {}
    # Quote each path; the for-loop interpolates them safely.
    quoted = " ".join(shlex.quote(p) for p in paths)
    script = (
        f'for p in {quoted}; do '
        '  if [ -d "$p/.git" ]; then '
        '    printf "%s\\n" "ALIVE:$p"; '
        '  else '
        '    printf "%s\\n" "GONE:$p"; '
        '  fi; '
        'done'
    )
    rem = _remote.Remote(host)
    try:
        res = rem.run(script, check=False, timeout=30)
    except _remote.RemoteError:
        # Probe failed (host unreachable, auth, etc.). Be conservative:
        # report every path as alive so we don't auto-deactivate on
        # a transient outage.
        return {p: True for p in paths}
    out: dict[str, bool] = {p: True for p in paths}  # default to conservative
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("ALIVE:"):
            out[line[len("ALIVE:"):]] = True
        elif line.startswith("GONE:"):
            out[line[len("GONE:"):]] = False
    return out


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_orphan_installations() -> list[DriftFinding]:
    """For each installation manifest, verify the working tree is
    still on the host it points to. Local installs check the
    filesystem directly; SSH installs go via :func:`_ssh_probe_paths`
    (batched, one call per host). Manifests already inside
    ``.archive/`` are skipped."""
    findings: list[DriftFinding] = []
    inst_dir = _installations_dir()
    if not inst_dir.is_dir():
        return findings

    # Group by host so we make at most one SSH call per host.
    remote_targets: dict[str, list[tuple[str, str]]] = {}
    for manifest_path in sorted(inst_dir.glob("*.yaml")):
        if manifest_path.parent.name == ARCHIVE_SUBDIR:
            continue
        data = _load_manifest(manifest_path)
        if data is None:
            continue
        project = data.get("project") or manifest_path.stem
        ssh_remote = (data.get("ssh_remote") or "").strip()
        if ssh_remote:
            # Resolve the host's project_root; the clone lives at
            # ``<project_root>/<project>`` by convention. We don't
            # store the absolute remote path in the manifest today
            # so we re-synthesize it.
            try:
                host_obj = _hosts.resolve(ssh_remote)
                proot = (host_obj.project_root or "~/repos").rstrip("/")
            except Exception:
                proot = "~/repos"
            remote_targets.setdefault(ssh_remote, []).append(
                (project, f"{proot}/{project}")
            )
        else:
            # Local install — check EACH of the project's repos the manifest
            # records on this machine (a project may have code + manuscript + …).
            # Legacy manifests have no ``repos`` block → fall back to the derived
            # ~/repos/<project>. A single missing repo is a warn (install still
            # lives); ALL gone archives the manifest.
            repos = [r for r in (data.get("repos") or [])
                     if isinstance(r, dict) and r.get("path")]
            checks = [(str(r.get("name") or project), str(r.get("path"))) for r in repos] \
                or [(project, f"~/repos/{project}")]
            missing = [(nm, pth) for nm, pth in checks
                       if not _is_local_path_alive(str(Path(pth).expanduser()))]
            if missing and len(missing) == len(checks):
                locs = ", ".join(p for _n, p in checks)
                findings.append(DriftFinding(
                    kind="orphan_installation",
                    severity="actionable",
                    target=project,
                    host="local",
                    detail=f"manifest points at {locs} but the clone(s) are gone",
                    suggested_action="archive the installation manifest",
                    artefact_path=str(manifest_path),
                ))
            else:
                for nm, pth in missing:
                    findings.append(DriftFinding(
                        kind="orphan_installation",
                        severity="warn",
                        target=f"{project}/{nm}",
                        host="local",
                        detail=f"repo {nm!r} at {pth} is gone; {project} still has "
                               "other clones here",
                        suggested_action="re-clone it, or drop it from the project",
                        artefact_path=str(manifest_path),
                    ))

    # Now resolve each remote group via one SSH call.
    for ssh_remote, items in remote_targets.items():
        try:
            host_obj = _hosts.resolve(ssh_remote)
        except _hosts.HostNotFound:
            # Host disappeared from the registry; treat all its
            # installations as orphaned by definition.
            for project, remote_path in items:
                findings.append(DriftFinding(
                    kind="orphan_installation",
                    severity="actionable",
                    target=project,
                    host=ssh_remote,
                    detail=f"ssh host {ssh_remote!r} is not registered any more",
                    suggested_action="archive the installation manifest",
                    artefact_path=str(_installations_dir() / f"{project}.yaml"),
                ))
            continue
        results = _ssh_probe_paths(host_obj, [p for _, p in items])
        for project, remote_path in items:
            if not results.get(remote_path, True):
                findings.append(DriftFinding(
                    kind="orphan_installation",
                    severity="actionable",
                    target=project,
                    host=ssh_remote,
                    detail=f"manifest points at {ssh_remote}:{remote_path} but the clone is gone",
                    suggested_action="archive the installation manifest",
                    artefact_path=str(_installations_dir() / f"{project}.yaml"),
                ))
    return findings


def detect_orphan_registries() -> list[DriftFinding]:
    """For each active cert-project, verify EACH of its repos (a project may
    have several — code + manuscript + …) is still on its recorded host.
    Cert-only projects (no repos) and archived ones are skipped.

    A single missing repo is a ``warn`` (the project still lives via its other
    clones — e.g. the code repo is present but a manuscript repo was removed);
    only when EVERY repo is gone is the project an ``actionable`` orphan whose
    repair (in ``apply``) flips ``status: archived`` in the cert-project
    frontmatter (lab history is preserved, not deleted).

    The cert-project registry (``<lab-mgmt>/cert_projects/<name>.md``) is the
    authoritative project store, carrying each repo's clone location.
    """
    findings: list[DriftFinding] = []
    from . import cert_projects as _cp
    try:
        projects = _cp.iter_projects()
    except Exception as exc:
        return [DriftFinding(
            kind="orphan_registry",
            severity="warn",
            target="(none)",
            host="local",
            detail=f"can't reach the cert-project registry: {exc}",
            suggested_action="check the lab-mgmt repo is present (murmurent pi-init)",
        )]

    def _loc(r) -> str:
        return r.path if r.host == "local" else \
            f"{r.host}:{r.remote_path or '~/repos/' + r.name}"

    # 1. Local repos: aliveness now. Remote repos: queue for a batched SSH probe.
    remote_targets: dict[str, list[tuple[str, str, str]]] = {}  # host → (proj, repo, path)
    per_project: dict[str, dict] = {}    # name → {cp, entries: [[repo, alive|None]]}
    for cp in projects:
        if cp.status == "archived" or not cp.repos:   # cert-only: nothing to reconcile
            continue
        entries: list[list] = []
        for r in cp.repos:
            if r.host == "local":
                alive = _is_local_path_alive(r.path) if r.path else True
                entries.append([r, alive])
            else:
                remote_targets.setdefault(r.host, []).append(
                    (cp.name, r.name, r.remote_path or f"~/repos/{r.name}"))
                entries.append([r, None])             # pending remote probe
        per_project[cp.name] = {"cp": cp, "entries": entries}

    # 2. Probe remotes, fill in aliveness (unreachable host → treat its repos gone).
    remote_alive: dict[tuple[str, str], bool] = {}
    for host_name, items in remote_targets.items():
        try:
            host_obj = _hosts.resolve(host_name)
        except _hosts.HostNotFound:
            for project, repo_name, _rp in items:
                remote_alive[(project, repo_name)] = False
            continue
        results = _ssh_probe_paths(host_obj, [rp for _, _, rp in items])
        for project, repo_name, rp in items:
            remote_alive[(project, repo_name)] = results.get(rp, True)
    for pname, info in per_project.items():
        for e in info["entries"]:
            if e[1] is None:
                e[1] = remote_alive.get((pname, e[0].name), True)

    # 3. Per project: a single missing repo is a WARN (the project still lives via
    #    its other clones); ALL repos gone is ACTIONABLE (archive the project).
    for pname, info in per_project.items():
        cp = info["cp"]
        artefact = str(_cp.project_path(pname))
        entries = info["entries"]
        missing = [r for (r, alive) in entries if not alive]
        if not missing:
            continue
        if any(alive for (_r, alive) in entries):     # some clones still present
            for r in missing:
                findings.append(DriftFinding(
                    kind="orphan_registry",
                    severity="warn",
                    target=f"{pname}/{r.name}",
                    host=r.host,
                    detail=f"repo {r.name!r} ({r.role}) at {_loc(r)} is gone; "
                           f"{pname} still has other clones",
                    suggested_action=f"re-clone {r.name}, or drop it from the project",
                    artefact_path=artefact,
                ))
        else:                                         # every clone gone → orphan
            locs = ", ".join(_loc(r) for (r, _a) in entries)
            findings.append(DriftFinding(
                kind="orphan_registry",
                severity="actionable",
                target=pname,
                host=entries[0][0].host if entries else "local",
                detail=f"all clones gone ({locs})",
                suggested_action="flip cert-project status: archived",
                artefact_path=artefact,
            ))
    return findings


def detect_missing_charters() -> list[DriftFinding]:
    """For each install manifest with a still-alive working tree,
    verify CHARTER.md is still present. Surfaces as ``warn`` (no
    auto-fix; the user should either re-adopt or remove)."""
    findings: list[DriftFinding] = []
    inst_dir = _installations_dir()
    if not inst_dir.is_dir():
        return findings

    # Local installs first.
    for manifest_path in sorted(inst_dir.glob("*.yaml")):
        if manifest_path.parent.name == ARCHIVE_SUBDIR:
            continue
        data = _load_manifest(manifest_path)
        if not data:
            continue
        project = data.get("project") or manifest_path.stem
        if (data.get("ssh_remote") or "").strip():
            continue  # handled below
        local_path = Path(f"~/repos/{project}").expanduser()
        if local_path.is_dir() and not (local_path / "CHARTER.md").exists():
            findings.append(DriftFinding(
                kind="missing_charter",
                severity="warn",
                target=project,
                host="local",
                detail=f"clone exists at {local_path} but CHARTER.md is missing",
                suggested_action="re-adopt or remove from murmurent",
                artefact_path=str(manifest_path),
            ))

    # Remote: batch CHARTER existence checks per host (same shape as
    # the path-alive probe but checking for CHARTER.md too).
    remote_groups: dict[str, list[tuple[str, str]]] = {}
    for manifest_path in sorted(inst_dir.glob("*.yaml")):
        if manifest_path.parent.name == ARCHIVE_SUBDIR:
            continue
        data = _load_manifest(manifest_path)
        if not data:
            continue
        ssh_remote = (data.get("ssh_remote") or "").strip()
        if not ssh_remote:
            continue
        project = data.get("project") or manifest_path.stem
        try:
            host_obj = _hosts.resolve(ssh_remote)
            proot = (host_obj.project_root or "~/repos").rstrip("/")
        except Exception:
            proot = "~/repos"
        remote_groups.setdefault(ssh_remote, []).append(
            (project, f"{proot}/{project}")
        )
    for ssh_remote, items in remote_groups.items():
        try:
            host_obj = _hosts.resolve(ssh_remote)
        except _hosts.HostNotFound:
            continue
        # One script: each path → "STATE:<path>:<alive>:<charter>"
        quoted = " ".join(shlex.quote(p) for p, _ in [(p, p) for _, p in items])
        script = (
            f'for p in {quoted}; do '
            '  if [ -d "$p/.git" ]; then '
            '    if [ -f "$p/CHARTER.md" ]; then printf "%s\\n" "OK:$p"; '
            '    else printf "%s\\n" "NOCHARTER:$p"; fi; '
            '  fi; '
            'done'
        )
        try:
            res = _remote.Remote(host_obj).run(script, check=False, timeout=30)
        except _remote.RemoteError:
            continue
        no_charter: set[str] = set()
        for line in (res.stdout or "").splitlines():
            if line.startswith("NOCHARTER:"):
                no_charter.add(line[len("NOCHARTER:"):].strip())
        for project, remote_path in items:
            if remote_path in no_charter:
                findings.append(DriftFinding(
                    kind="missing_charter",
                    severity="warn",
                    target=project,
                    host=ssh_remote,
                    detail=f"clone exists at {ssh_remote}:{remote_path} but CHARTER.md is missing",
                    suggested_action="re-adopt or remove from murmurent",
                    artefact_path=str(_installations_dir() / f"{project}.yaml"),
                ))
    return findings


def detect_unadopted_clones() -> list[DriftFinding]:
    """Count clones that aren't yet murmurent projects, grouped by host.
    Uses the most recent cached inventory report rather than running
    a fresh scan — reconciliation should be cheap. One finding per
    host with a rolled-up count, not per-clone, so the daily summary
    stays scannable."""
    try:
        from . import repo_inventory as _ri
        latest = _ri.latest_report_path()
        if latest is None:
            return []
        data = _ri.load_report(latest)
    except Exception:
        return []
    if not data:
        return []
    counts: dict[str, int] = {}
    for row in data.get("rows", []):
        for c in row.get("clones", []) or []:
            if not c.get("is_murmurent_ready"):
                host = c.get("host") or "unknown"
                counts[host] = counts.get(host, 0) + 1
    findings: list[DriftFinding] = []
    for host, n in sorted(counts.items()):
        findings.append(DriftFinding(
            kind="unadopted_clone",
            severity="info",
            target=f"{n} clones",
            host=host,
            detail=f"{n} git clones on {host} are not yet murmurent projects",
            suggested_action="click ↑ adopt in the Repos panel",
        ))
    return findings


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def detect_lab_mgmt_unsynced() -> list[DriftFinding]:
    """lab_mgmt edits that haven't reached the lab.

    Members receive the roster (and every other lab_mgmt artefact) via
    ``git pull`` of the lab_mgmt repo, so two states mean the lab can't
    see what this machine has:

      - **uncommitted changes** in the working tree (a writer bypassed
        the auto-commit, or a hand-edit wasn't committed);
      - **unpushed commits** (committed locally, never pushed — offline
        save, or a push that failed silently).

    Both are ``warn``: no auto-repair, because sweeping up arbitrary
    working-tree changes could commit the PI's work-in-progress.
    """
    import subprocess as _sp

    from .repo import lab_mgmt_repo_root

    root = lab_mgmt_repo_root()
    if not (root / ".git").exists():
        return []
    findings: list[DriftFinding] = []

    def _git(*args: str):
        return _sp.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True, timeout=20)

    try:
        status = _git("status", "--porcelain")
        dirty = [ln for ln in (status.stdout or "").splitlines() if ln.strip()]
        if status.returncode == 0 and dirty:
            findings.append(DriftFinding(
                kind="lab_mgmt_uncommitted",
                severity="warn",
                target=str(root),
                host="local",
                detail=(f"{len(dirty)} uncommitted change(s) in lab_mgmt — "
                        "invisible to the lab until committed and pushed"),
                suggested_action=f"review + commit + push in {root}",
                artefact_path=str(root),
            ))
        # Unpushed commits: needs an upstream to compare against. No
        # upstream/remote is roster_sync's department — skip quietly.
        ahead = _git("rev-list", "--count", "@{u}..HEAD")
        if ahead.returncode == 0:
            n = int((ahead.stdout or "0").strip() or 0)
            if n:
                findings.append(DriftFinding(
                    kind="lab_mgmt_unpushed",
                    severity="warn",
                    target=str(root),
                    host="local",
                    detail=(f"{n} unpushed lab_mgmt commit(s) — members' "
                            "dashboards won't see them until pushed"),
                    suggested_action=f"git -C {root} push",
                    artefact_path=str(root),
                ))
    except (OSError, _sp.SubprocessError, ValueError):
        return findings
    return findings


def reconcile(*, apply: bool = False) -> ReconcileReport:
    """Run all four detectors and return a report.

    With ``apply=False`` (default) the report describes the drift
    but nothing is mutated. With ``apply=True``, actionable findings
    are repaired and recorded in ``report.applied``.
    """
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    report = ReconcileReport(generated_at=now)
    # Freshen the lab_mgmt clone first (roster + cert-project registry both
    # live there), so the detectors below — and the Lab Members panel —
    # read what the PI last pushed, not a stale local copy. Best-effort:
    # offline / diverged / not-a-git-clone is a note, never a failure.
    try:
        from . import roster_sync as _rs
        sync = _rs.pull_lab_mgmt()
        if sync.is_git and not sync.ok:
            report.errors.append(f"lab_mgmt pull: {sync.detail}")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"lab_mgmt pull: {exc}")
    for detector in (
        detect_orphan_installations,
        detect_orphan_registries,
        detect_missing_charters,
        detect_unadopted_clones,
        detect_lab_mgmt_unsynced,
    ):
        try:
            report.findings.extend(detector())
        except Exception as exc:
            report.errors.append(f"{detector.__name__}: {exc}")
    if apply:
        for finding in list(report.findings):
            if finding.severity != "actionable":
                continue
            try:
                if _apply_finding(finding):
                    report.applied.append(finding)
            except Exception as exc:
                report.errors.append(f"apply {finding.kind}/{finding.target}: {exc}")
    return report


def _apply_finding(finding: DriftFinding) -> bool:
    """Repair one actionable finding. Returns True when something
    changed; False if the artefact was already in the desired state.
    """
    if finding.kind == "orphan_installation":
        return _archive_manifest(Path(finding.artefact_path))
    if finding.kind == "orphan_registry":
        return _archive_registry(Path(finding.artefact_path))
    # missing_charter + unadopted_clone aren't auto-repaired.
    return False


def _archive_manifest(manifest_path: Path) -> bool:
    """Move an orphan installation manifest into ``.archive/`` with
    a date suffix so multiple deactivations of the same project
    don't collide.
    """
    if not manifest_path.is_file():
        return False
    archive_dir = manifest_path.parent / ARCHIVE_SUBDIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.date.today().isoformat()
    dest = archive_dir / f"{manifest_path.stem}_{stamp}.yaml"
    # If the dated dest already exists (re-run on the same day),
    # add a counter suffix.
    i = 1
    while dest.exists():
        dest = archive_dir / f"{manifest_path.stem}_{stamp}_{i}.yaml"
        i += 1
    manifest_path.rename(dest)
    return True


def _archive_registry(registry_path: Path) -> bool:
    """Flip ``status: archived`` in the registry frontmatter. Don't
    delete the file — the lab history is worth preserving.
    """
    if not registry_path.is_file():
        return False
    try:
        parsed = parse_file(registry_path)
    except Exception:
        return False
    meta = dict(parsed.meta or {})
    if meta.get("status") == "archived":
        return False  # already archived
    meta["status"] = "archived"
    meta["archived_at"] = _dt.date.today().isoformat()
    registry_path.write_text(
        dump_document(meta, parsed.body),
        encoding="utf-8",
    )
    return True


__all__ = [
    "DriftFinding",
    "ReconcileReport",
    "detect_orphan_installations",
    "detect_orphan_registries",
    "detect_missing_charters",
    "detect_unadopted_clones",
    "reconcile",
]
