"""
Purpose: implementation of ``murmurent project push`` — a project-WIDE commit +
         push. Enumerates a cert-project's repos, runs the per-repo pre-flight
         (the same safety gates as ``/murmurent-push``: governed-data paths,
         secret-shaped filenames, staged-content secret scan, large files,
         ``.claude/settings.json`` skip), then commits + pushes each clean repo
         to its tracking remote. One repo failing pre-flight is BLOCKED (no
         commit, no push) and reported; the other repos proceed independently.
         A single plain-language summary + one Slack note to the project's
         channel close the run.
Author: Mike Hallett (with Claude Code)
Input: a cert-project name (or the repo you're standing in) + its repo list.
Output: per-repo commit/push side effects; a novice-friendly report; one Slack
        note; an exit code (0 all clean, 1 partial, 2 nothing pushable).

This is Phase 1 of issue #95 (intra-group project push). No mirrors (Phase 2),
no inter-group Slack guests (Phase 3), no Security-Guard access checks (Phase 4).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..core import cert_projects as _cp
from ..core import secret_scan as _ss

# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------
# Each per-repo result carries one of these statuses. The three buckets below
# drive the summary counts + exit code.

STATUS_PUSHED = "pushed"              # committed + pushed to the remote
STATUS_UP_TO_DATE = "up_to_date"      # nothing to commit — already backed up
STATUS_NOT_CLONED = "not_cloned"      # no local clone on this machine
STATUS_REMOTE_HOST = "remote_host"    # tree lives on another host
STATUS_BLOCKED_SECRET = "blocked_secret"            # secret in file CONTENT
STATUS_BLOCKED_SECRET_FILE = "blocked_secret_file"  # secret-shaped filename
STATUS_BLOCKED_GOVERNED = "blocked_governed"        # governed-data path in diff
STATUS_BLOCKED_LARGE = "blocked_large"              # oversize in-repo file
STATUS_PUSH_REJECTED = "push_rejected"              # commit ok, push refused
STATUS_COMMITTED_LOCAL = "committed_local"          # commit ok, no remote to push to

# Buckets.
_SUCCESS = {STATUS_PUSHED, STATUS_UP_TO_DATE}
_SKIPPED = {STATUS_NOT_CLONED, STATUS_REMOTE_HOST}
# everything else needs attention.


# ---------------------------------------------------------------------------
# Pre-flight helpers
# ---------------------------------------------------------------------------

# Governed-data path segments (rules/data-storage.md). Matched as a path
# segment so a top-level ``immutable/`` or a ``data/lab_vm/append_only/`` both
# trip. ``raw``/``refined`` are the legacy names, still recognized.
_GOVERNED_RE = re.compile(r"(?:^|/)(?:immutable|append_only|raw|refined)/")

# 1 MB — the large-file threshold, matching /murmurent-push.
_LARGE_BYTES = 1024 * 1024
_LARGE_DIRS = ("data/", "src/", "exp/", "obsolete/")

# Never stage this — it holds machine-absolute paths + per-machine allowlists.
_SKIP_ALWAYS = (".claude/settings.json",)


def _secret_shaped(path: str) -> bool:
    """True if the basename looks like a credential file (private key, ``.env``,
    ``.pem``, ``credentials``, …). Mirrors the /murmurent-push filename table."""
    name = Path(path).name.lower()
    full = path.lower()
    # ``.env.example`` with placeholder values is fine; a bare/other .env is not.
    if name.endswith(".env"):
        return True
    if name == ".env.example":
        return False
    if name.endswith((".pem", ".p12", ".pfx", ".key")):
        return True
    if name in ("id_rsa", "id_ed25519", "id_dsa", "id_ecdsa", ".netrc", ".pgpass"):
        return True
    if name.startswith("id_") and "." not in name:
        return True
    if name.endswith(("_rsa", "_ed25519")):
        return True
    if "passphrase" in name or "credentials" in name:
        return True
    if full.endswith(".aws/credentials"):
        return True
    return False


def _is_governed(path: str) -> bool:
    return bool(_GOVERNED_RE.search(path))


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RepoPushResult:
    """Outcome of the push attempt for ONE repo in a project."""

    name: str
    status: str
    path: str = ""
    detail: str = ""           # the human next step / short explanation
    git_detail: str = ""       # git-level detail (shown under --detail)
    short_hash: str = ""       # commit hash when a commit was made
    branch: str = ""
    files: int = 0             # number of files staged/committed
    findings: tuple = ()       # redacted SecretHit dicts for blocked_secret

    @property
    def ok(self) -> bool:
        return self.status in _SUCCESS

    @property
    def needs_attention(self) -> bool:
        return self.status not in _SUCCESS and self.status not in _SKIPPED

    @property
    def skipped(self) -> bool:
        return self.status in _SKIPPED


@dataclass
class ProjectPushReport:
    """The whole run: per-repo results + a resolved exit code."""

    project: str
    results: list = field(default_factory=list)
    found: bool = True                 # False when the project doesn't exist
    slack_posted: bool = False

    @property
    def backed_up(self) -> list:
        return [r for r in self.results if r.ok]

    @property
    def attention(self) -> list:
        return [r for r in self.results if r.needs_attention]

    @property
    def skipped(self) -> list:
        return [r for r in self.results if r.skipped]

    @property
    def pushable(self) -> list:
        """Repos we actually attempted (had a local clone) — not the skipped ones."""
        return [r for r in self.results if not r.skipped]

    @property
    def exit_code(self) -> int:
        if not self.found:
            return 2
        if not self.pushable:
            return 2            # nothing on this machine to push
        if self.attention:
            return 1            # partial — some blocked/failed
        return 0


# ---------------------------------------------------------------------------
# Git plumbing (kept tiny + side-effect-explicit)
# ---------------------------------------------------------------------------

def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=False, capture_output=True, text=True)


def _porcelain_paths(repo: Path) -> list[str]:
    """Repo-relative paths with any change (modified/added/deleted/untracked/
    renamed). Rename lines contribute the NEW path."""
    out = _git(repo, ["status", "--porcelain=v1", "-uall", "-z"]).stdout
    paths: list[str] = []
    tokens = out.split("\0")
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        if not entry:
            i += 1
            continue
        # "XY <path>"; rename/copy (R/C in either column) consumes the next token
        # as the ORIGINAL path — we keep the destination (this entry's path).
        xy = entry[:2]
        path = entry[3:] if len(entry) > 3 else ""
        if ("R" in xy or "C" in xy):
            i += 2  # skip the paired origin token
        else:
            i += 1
        if path:
            paths.append(path)
    return paths


def _current_branch(repo: Path) -> str:
    return _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "HEAD"


def _has_origin(repo: Path) -> bool:
    return _git(repo, ["remote", "get-url", "origin"]).returncode == 0


# ---------------------------------------------------------------------------
# Repo resolution
# ---------------------------------------------------------------------------

def _resolve_clone(ref) -> Path | None:
    """Local clone path for ``ref`` (a RepoRef), or None if not on this machine.
    Prefers the record's explicit ``path``; falls back to ``<repos_root>/<name>``."""
    from ..core.repo import repos_root
    cand = None
    if ref.path:
        cand = Path(ref.path).expanduser()
    elif ref.name:
        cand = repos_root() / ref.name
    if cand is None:
        return None
    if cand.is_dir() and (cand / ".git").exists():
        return cand
    return None


# ---------------------------------------------------------------------------
# Per-repo push
# ---------------------------------------------------------------------------

def push_one_repo(ref, *, message: str | None) -> RepoPushResult:
    """Run the full pre-flight + commit + push for a single repo. Never raises;
    every failure mode is a status on the returned result. A repo that fails
    ANY pre-flight gate is left un-staged, un-committed, and un-pushed."""
    name = ref.name or (Path(ref.path).name if ref.path else "repo")

    # 1. Remote-host repos can't be pushed from this laptop.
    if ref.host and ref.host != "local":
        return RepoPushResult(name=name, status=STATUS_REMOTE_HOST,
                              detail=f"lives on {ref.host}; save it from there",
                              path=ref.remote_path or ref.path)

    # 2. Must have a local clone on this machine.
    repo = _resolve_clone(ref)
    if repo is None:
        return RepoPushResult(name=name, status=STATUS_NOT_CLONED,
                              detail="isn't on this computer, so it was skipped",
                              path=ref.path)

    changed = _porcelain_paths(repo)
    if not changed:
        return RepoPushResult(name=name, status=STATUS_UP_TO_DATE, path=str(repo),
                              detail="nothing new to save")

    # 3. Governed-data paths must never reach GitHub.
    governed = [p for p in changed if _is_governed(p)]
    if governed:
        return RepoPushResult(
            name=name, status=STATUS_BLOCKED_GOVERNED, path=str(repo),
            detail=f"it contains protected data files ({governed[0]}) that "
                   "must not be saved to GitHub",
            git_detail=", ".join(governed))

    # 4. Secret-shaped filenames.
    secret_files = [p for p in changed if _secret_shaped(p)]
    if secret_files:
        return RepoPushResult(
            name=name, status=STATUS_BLOCKED_SECRET_FILE, path=str(repo),
            detail=f"the file {secret_files[0]} looks like it holds a password "
                   "or key — remove it (or keep it outside the repo), then run "
                   "this again",
            git_detail=", ".join(secret_files))

    # 5. Large in-repo files.
    for p in changed:
        fp = repo / p
        if not fp.is_file():
            continue
        if not p.startswith(_LARGE_DIRS):
            continue
        try:
            size = fp.stat().st_size
        except OSError:
            continue
        if size > _LARGE_BYTES:
            mb = size / (1024 * 1024)
            return RepoPushResult(
                name=name, status=STATUS_BLOCKED_LARGE, path=str(repo),
                detail=f"the file {p} is too big ({mb:.1f} MB) to save here — "
                       "move it to the project's data area, then run this again",
                git_detail=f"{p} = {size} bytes")

    # 6. Select files to stage (drop the always-skip list).
    to_stage = [p for p in changed if p not in _SKIP_ALWAYS]
    settings_changed = any(p in _SKIP_ALWAYS for p in changed)
    if settings_changed:
        _ensure_gitignored(repo, ".claude/settings.json")
        gi = ".gitignore"
        if (repo / gi).is_file() and gi not in to_stage:
            to_stage.append(gi)
    if not to_stage:
        # Only the skipped file changed — nothing to back up.
        return RepoPushResult(name=name, status=STATUS_UP_TO_DATE, path=str(repo),
                              detail="nothing new to save")

    # Selective stage.
    _git(repo, ["add", "-A", "--", *to_stage])

    # 7. Staged-content secret scan — the load-bearing gate. Block on any
    #    block-severity hit; UNSTAGE so we never leave a secret staged.
    hits = _ss.scan_staged(repo)
    blocks = [h for h in hits if h.severity == _ss.SEVERITY_BLOCK]
    if blocks:
        _git(repo, ["reset", "-q"])   # unstage everything we just staged
        first = blocks[0]
        return RepoPushResult(
            name=name, status=STATUS_BLOCKED_SECRET, path=str(repo),
            detail=f"a secret was found in {first.path} (line {first.line}) — "
                   "remove it and load it from an environment variable instead, "
                   "then run this again",
            git_detail="; ".join(f"{h.path}:{h.line} {h.rule} [{h.redacted}]"
                                  for h in blocks),
            findings=tuple(h.to_dict() for h in blocks))

    # 8. Commit.
    staged_now = _git(repo, ["diff", "--cached", "--name-only"]).stdout.split()
    n = len(staged_now)
    commit_msg = message or f"project push: {n} file{'s' if n != 1 else ''} updated"
    commit = _git(repo, ["commit", "-m", commit_msg])
    if commit.returncode != 0:
        # Nothing actually committed (e.g. only ignored changes) — treat as clean.
        _git(repo, ["reset", "-q"])
        return RepoPushResult(name=name, status=STATUS_UP_TO_DATE, path=str(repo),
                              detail="nothing new to save")
    branch = _current_branch(repo)
    short = _git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()

    # 9. Push to the tracking remote. Commit stands regardless; a rejected push
    #    is surfaced (never force / amend / no-verify).
    if not _has_origin(repo):
        return RepoPushResult(
            name=name, status=STATUS_COMMITTED_LOCAL, path=str(repo),
            detail="saved on this computer, but no GitHub backup is set up — "
                   "ask your project lead to connect it",
            short_hash=short, branch=branch, files=n)

    push = _git(repo, ["push", "origin", branch])
    if push.returncode != 0:
        # Try to establish upstream on a first push, then report if still failing.
        push2 = _git(repo, ["push", "-u", "origin", branch])
        if push2.returncode != 0:
            reason = (push2.stderr or push.stderr or "push rejected").strip().splitlines()
            reason = reason[-1] if reason else "push rejected"
            return RepoPushResult(
                name=name, status=STATUS_PUSH_REJECTED, path=str(repo),
                detail="saved on this computer, but GitHub refused it — you may "
                       "not have permission; ask your project lead",
                git_detail=reason, short_hash=short, branch=branch, files=n)

    return RepoPushResult(name=name, status=STATUS_PUSHED, path=str(repo),
                          detail="saved to GitHub", short_hash=short,
                          branch=branch, files=n)


def _ensure_gitignored(repo: Path, entry: str) -> None:
    gi = repo / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    if entry not in [ln.strip() for ln in lines]:
        with gi.open("a", encoding="utf-8") as fh:
            if lines and lines[-1].strip():
                fh.write("\n")
            fh.write(f"{entry}\n")


# ---------------------------------------------------------------------------
# Whole-project push
# ---------------------------------------------------------------------------

def push_project(name: str, *, message: str | None = None,
                 env: dict | None = None, post_slack: bool = True) -> ProjectPushReport:
    """Push every repo of cert-project ``name``. Returns a structured report; the
    caller renders it + reads ``.exit_code``. Emits ONE Slack note to the
    project channel afterwards (skipped silently if there's no channel)."""
    cp = _cp.get(name, env)
    if cp is None:
        return ProjectPushReport(project=name, results=[], found=False)

    results = [push_one_repo(ref, message=message) for ref in cp.repos]
    report = ProjectPushReport(project=name, results=results)

    if post_slack:
        report.slack_posted = _maybe_post_slack(name, report, env=env)
    return report


def _maybe_post_slack(name: str, report: ProjectPushReport,
                      *, env: dict | None = None) -> bool:
    """Post ONE plain-language note to the project's Slack channel. No channel →
    skip silently (a supported state per the plan). Best-effort: never raises."""
    try:
        channel = _cp.slack_channel_for(name, env)
        if not channel:
            return False
        from ..core.cert_provision import resolve_project_slack
        _workspace, token = resolve_project_slack(name, env=env)
        if not token:
            return False
        from ..dashboard import slack_notify as _sn
        return _sn._post(channel, _slack_body(name, report), token=token)
    except Exception:  # noqa: BLE001 — a Slack hiccup never fails a push
        return False


def _slack_body(name: str, report: ProjectPushReport) -> str:
    lines = [f"*Project backup — {name}*", "", summary_line(report)]
    for r in report.results:
        lines.append(f"• {_repo_line(r, detail=False)}")
    lines.append("")
    lines.append("All worship me and I will let you serve me.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering (novice-friendly)
# ---------------------------------------------------------------------------

def summary_line(report: ProjectPushReport) -> str:
    """The one-line, jargon-free headline printed first."""
    if not report.found:
        return f"Couldn't find a project called '{report.project}'."
    total = len(report.results)
    n_ok = len(report.backed_up)
    n_att = len(report.attention)
    n_skip = len(report.skipped)
    mark = "✔" if not n_att else "⚠"
    parts = [f"{mark} {n_ok} of {total} repo{'s' if total != 1 else ''} "
             "safely backed up to GitHub."]
    if n_att:
        parts.append(f"{n_att} need{'s' if n_att == 1 else ''} attention.")
    if n_skip:
        parts.append(f"{n_skip} skipped.")
    return " ".join(parts)


def _mark(status: str) -> str:
    if status in _SUCCESS:
        return "✔"
    if status in _SKIPPED:
        return "·"
    return "✗"


def _repo_line(r: RepoPushResult, *, detail: bool) -> str:
    base = f"{_mark(r.status)} {r.name} — {r.detail}."
    if detail and (r.git_detail or r.short_hash):
        extra = r.git_detail
        if r.short_hash:
            extra = f"{r.branch} {r.short_hash}" + (f"; {extra}" if extra else "")
        base += f"\n      ({extra})"
    return base


def render_report(report: ProjectPushReport, *, detail: bool = False) -> str:
    """The full report: summary line, then one plain line per repo."""
    lines = [summary_line(report)]
    if report.found and report.results:
        lines.append("")
        for r in report.results:
            lines.append(_repo_line(r, detail=detail))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_project_push(project: str | None, *, message: str | None,
                     detail: bool) -> int:
    """``murmurent project push`` — resolve the project (``--project`` or CWD),
    push all its repos, print the report, return the exit code."""
    import click

    name = project or _cp.project_name_for_cwd()
    if not name:
        raise click.ClickException(
            "not inside a project repo (no readiness marker / CHARTER found); "
            "pass --project <name>.")

    report = push_project(name, message=message)
    click.echo(render_report(report, detail=detail))
    if report.found and report.slack_posted:
        click.echo("\n(posted a note to the project's Slack channel)")
    return report.exit_code
