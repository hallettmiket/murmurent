"""
Purpose: Single chokepoint for "make this clone murmurent-READY" +
        "is this repo ready yet?" — shared by the dashboard endpoint
        (``POST /api/inventory/adopt``) and the CLI
        (``murmurent repo adopt`` / ``status`` / ``upgrade``).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-14 (readiness split 2026-07-15)
Input: Path to a git clone (local or on a registered SSH host).
Output: :class:`AdoptOutcome` wrapping the readiness probes, or
        :class:`AdoptionStatus` for the read-only check.

Terminology (2026-07-15 split): adopting a repo makes it
**murmurent-ready** — the ``.murmurent.yaml`` marker + the CC bootstrap
(:mod:`core.repo_ready`). It does NOT create a project. A *project* is
a named set of repos + members recorded in the lab_mgmt registry
(``cert_projects/``), created via the New Project flow which attaches
already-ready repos. Before the split, adopt minted a one-repo project
(CHARTER.md + registry record + manifest) — repos bootstrapped that way
still count as ready ("legacy") and ``murmurent repo upgrade`` converts
them to the marker.

Remote (SSH) adopts still write the legacy CHARTER-style bootstrap on
the host (the batched script predates the marker); that is recognized
as ready and upgraded in place later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import hosts as _hosts
from . import remote as _remote
from . import repo as _repo
from . import repo_ready as _rr

# code → the HTTP status the dashboard endpoint responds with. Kept here
# so the mapping can't drift from the codes adopt_clone() raises.
ERROR_HTTP_STATUS = {
    "host_not_found": 404,
    "bad_request": 400,
    "conflict": 409,
    "bootstrap_failed": 422,
    "ssh_failed": 502,
    "internal": 500,
}


class AdoptError(Exception):
    """Adoption refused or failed. ``code`` is one of ERROR_HTTP_STATUS."""

    def __init__(self, message: str, *, code: str = "internal") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class AdoptOutcome:
    """What :func:`adopt_clone` produced, host-agnostic."""

    repo: str
    host: str
    clone_path: str
    probes: list

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "repo": self.repo,
            "host": self.host,
            "clone_path": self.clone_path,
            "probes": [p.to_dict() for p in self.probes],
        }


def adopt_clone(
    *,
    clone_path: str,
    lab: str = "",
    agents: list[str] | None = None,
    host: str = "local",
) -> AdoptOutcome:
    """Make an existing git clone murmurent-ready.

    ``host == "local"`` validates the path against ``~/repos/`` and
    bootstraps on this filesystem. Any other value must name a
    registered SSH host; the bootstrap runs on the remote over one
    batched SSH session. No project is created — attach the ready repo
    to a project separately.

    Raises :class:`AdoptError`; never touches HTTP.
    """
    if host and host != "local":
        return _adopt_remote(clone_path=clone_path, lab=lab,
                             agents=agents, host=host)

    clone = Path(clone_path).expanduser().resolve()
    # repo.repos_root() — NOT a local Path.home() / "repos": the latter reads the
    # real home even when $MURMURENT_REPOS_ROOT redirects it, so the guard could
    # only ever be exercised against the operator's live ~/repos.
    repos_root = _repo.repos_root().resolve()
    try:
        clone.relative_to(repos_root)
    except ValueError:
        raise AdoptError(
            f"clone_path must live under {repos_root} (got {clone})",
            code="bad_request",
        )
    if not (clone / ".git").exists():
        raise AdoptError(f"not a git working tree: {clone}", code="bad_request")
    if (clone / _rr.LEGACY_MARKER).is_file():
        raise AdoptError(
            f"{clone} carries a legacy CHARTER.md bootstrap — run "
            "`murmurent repo upgrade` to convert it instead of re-adopting",
            code="conflict",
        )

    if not lab:
        lab = _default_lab()
    try:
        probes = _rr.make_ready(clone, lab=lab, agents=agents)
    except Exception as exc:  # noqa: BLE001
        raise AdoptError(f"bootstrap failed: {exc}", code="internal") from exc
    _raise_if_required_failed(probes)
    return AdoptOutcome(repo=clone.name, host="local",
                        clone_path=str(clone), probes=probes)


def _default_lab() -> str:
    """This machine's lab slug, best-effort (blank on a bare install)."""
    try:
        from .lab import load_lab_config
        return str(load_lab_config().lab or "")
    except Exception:  # noqa: BLE001
        return ""


def _adopt_remote(*, clone_path: str, lab: str,
                  agents: list[str] | None, host: str) -> AdoptOutcome:
    """SSH-host branch: bootstrap on the remote (legacy CHARTER shape —
    the batched script predates the marker; recognized as ready)."""
    try:
        host_obj = _hosts.resolve(host)
    except _hosts.HostNotFound as exc:
        raise AdoptError(str(exc), code="host_not_found") from exc
    if host_obj.kind != "ssh":
        raise AdoptError(f"host {host!r} is not an SSH host", code="bad_request")

    rem = _remote.Remote(host_obj)
    qpath = clone_path.replace("'", "'\\''")
    try:
        res = rem.run(
            f"if [ -d '{qpath}/.git' ]; then echo OK; "
            f"elif [ -d '{qpath}' ]; then echo NOGIT; "
            f"else echo NOPATH; fi",
            check=False, timeout=20,
        )
    except _remote.RemoteError as exc:
        raise AdoptError(
            f"ssh probe to {host} failed: {(exc.stderr or str(exc)).strip()}",
            code="ssh_failed",
        ) from exc
    verdict = (res.stdout or "").strip().splitlines()[-1] if res.stdout else ""
    if verdict == "NOPATH":
        raise AdoptError(
            f"path does not exist on {host}: {clone_path}", code="bad_request")
    if verdict == "NOGIT":
        raise AdoptError(
            f"not a git working tree on {host}: {clone_path}", code="bad_request")
    if verdict != "OK":
        raise AdoptError(
            f"unexpected probe verdict {verdict!r}: {res.stderr or ''}",
            code="ssh_failed",
        )

    from . import remote_adopt as _radopt
    name = Path(clone_path).name
    charter_text = (
        "---\n"
        f"lab: {lab or _default_lab() or ''}\n"
        "---\n\n"
        f"# {name}\n\n"
        "murmurent-ready marker (legacy shape written over SSH; run "
        "`murmurent repo upgrade` on the host to convert).\n"
    )
    try:
        probes = _radopt.adopt_remote_clone(
            host=host_obj, clone_path=clone_path, project=name,
            charter_text=charter_text, agents=list(agents or []))
    except Exception as exc:  # noqa: BLE001
        raise AdoptError(f"remote bootstrap failed: {exc}", code="internal") from exc
    _raise_if_required_failed(probes)
    return AdoptOutcome(repo=name, host=host, clone_path=clone_path,
                        probes=probes)


def _raise_if_required_failed(probes) -> None:
    for p in probes:
        if getattr(p, "status", "") == "fail" and getattr(p, "required", False):
            raise AdoptError(p.detail, code="bootstrap_failed")


# ---------------------------------------------------------------------------
# Read-only: is this repo murmurent-ready yet?
# ---------------------------------------------------------------------------


@dataclass
class AdoptionStatus:
    """Readiness state of one clone on one host.

    ``ready`` matches the Repos panel's ✓ signal: a readiness marker
    (``.murmurent.yaml``, or a legacy ``CHARTER.md`` bootstrap) plus
    ``.claude/agents/``.
    """

    host: str
    path: str
    exists: bool
    is_git: bool
    has_marker: bool
    legacy_charter: bool
    has_claude_agents: bool
    bootstrap_version: str = ""

    @property
    def ready(self) -> bool:
        return (self.exists and self.is_git
                and (self.has_marker or self.legacy_charter)
                and self.has_claude_agents)

    @property
    def verdict(self) -> str:
        """One-word-ish summary for tables + headlines."""
        if not self.exists:
            return "missing"
        if not self.is_git:
            return "not a git repo"
        if self.ready:
            return "ready (legacy)" if (self.legacy_charter
                                        and not self.has_marker) else "ready"
        if self.has_marker or self.legacy_charter or self.has_claude_agents:
            return "partial"
        return "plain clone"

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "path": self.path,
            "exists": self.exists,
            "is_git": self.is_git,
            "has_marker": self.has_marker,
            "legacy_charter": self.legacy_charter,
            "has_claude_agents": self.has_claude_agents,
            "bootstrap_version": self.bootstrap_version,
            "ready": self.ready,
            "verdict": self.verdict,
        }


def adoption_status(clone_path: str, *, host: str = "local") -> AdoptionStatus:
    """Report whether the clone at ``clone_path`` on ``host`` is
    murmurent-ready. Read-only; safe on any directory.

    Local hosts are checked on the filesystem; SSH hosts with a single
    batched probe. Raises :class:`AdoptError` (``host_not_found`` /
    ``ssh_failed``) only for host-resolution or connection problems —
    a missing path is a normal ``exists=False`` answer, not an error.
    """
    if host == "local":
        p = Path(clone_path).expanduser().resolve()
        r = _rr.readiness(p)
        return AdoptionStatus(
            host="local",
            path=str(p),
            exists=p.is_dir(),
            is_git=p.is_dir() and (p / ".git").is_dir(),
            has_marker=r.marker is not None,
            legacy_charter=r.legacy_charter,
            has_claude_agents=r.has_agents_dir,
            bootstrap_version=str((r.marker or {}).get("bootstrap_version") or ""),
        )

    try:
        host_obj = _hosts.resolve(host)
    except _hosts.HostNotFound as exc:
        raise AdoptError(str(exc), code="host_not_found") from exc
    rem = _remote.Remote(host_obj)
    qpath = clone_path.replace("'", "'\\''")
    script = (
        f"p='{qpath}'; "
        'e=0; [ -d "$p" ] && e=1; '
        'g=0; [ -d "$p/.git" ] && g=1; '
        f'm=0; [ -f "$p/{_rr.MARKER_FILENAME}" ] && m=1; '
        f'c=0; [ -f "$p/{_rr.LEGACY_MARKER}" ] && c=1; '
        'a=0; [ -d "$p/.claude/agents" ] && a=1; '
        'echo "$e|$g|$m|$c|$a"'
    )
    try:
        res = rem.run(script, check=False, timeout=20)
    except _remote.RemoteError as exc:
        raise AdoptError(
            f"ssh probe to {host} failed: {(exc.stderr or str(exc)).strip()}",
            code="ssh_failed",
        ) from exc
    line = (res.stdout or "").strip().splitlines()[-1] if res.stdout else ""
    parts = line.split("|")
    if len(parts) != 5:
        raise AdoptError(
            f"unexpected probe output from {host}: {line!r}", code="ssh_failed")
    e, g, m, c, a = (x == "1" for x in parts)
    return AdoptionStatus(host=host, path=clone_path, exists=e, is_git=g,
                          has_marker=m, legacy_charter=c, has_claude_agents=a)


# ---------------------------------------------------------------------------
# Legacy installation manifests (kept for the Installations panel)
# ---------------------------------------------------------------------------


def find_manifest_for(clone_path: str, *, host: str = "local",
                      installations_dir: Path | None = None) -> Path | None:
    """Return the installation manifest that references ``clone_path``
    on ``host``, if any. Manifests always live on THIS machine (remote
    installs carry ``ssh_remote``), so this is a local scan either way.
    Manifests are a project×machine record — written at project
    install time, no longer by adopt.
    """
    if installations_dir is None:
        from . import projectize as _proj
        installations_dir = _proj.INSTALLATIONS_DIR_DEFAULT
    if not installations_dir.is_dir():
        return None
    if host == "local":
        want = str(Path(clone_path).expanduser().resolve())
    else:
        want = clone_path.rstrip("/")
    name_match: Path | None = None
    want_name = Path(clone_path).name
    for mf in sorted(installations_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        remote = data.get("ssh_remote") or "local"
        if remote != host:
            continue
        if name_match is None and str(data.get("project") or "") == want_name:
            name_match = mf
        for repo in data.get("repos") or []:
            if not isinstance(repo, dict):
                continue
            raw = str(repo.get("path") or "").rstrip("/")
            if not raw:
                continue
            if host == "local":
                try:
                    got = str(Path(raw).expanduser().resolve())
                except OSError:
                    got = raw
            else:
                got = raw
            if got == want:
                return mf
    return name_match
