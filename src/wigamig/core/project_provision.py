"""
Purpose: Provision a project's git origin + collaborators with traffic-light progress.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Project name, lab GitHub org, request metadata (repo kind, members).
Output: ``[Probe]`` list the dashboard renders as green/yellow/red rows.

The PI-approve path used to do this work silently in a try/except — the
user got "request approved" but had no idea whether gh repo create
actually fired, whether the push went through, or whether members were
added as collaborators. This module wraps each step so the same
information is visible from the dashboard.

What each probe means:
  - ``slack channel``  : Slack project channel created (or already there)
  - ``github repo``    : Repo exists on github (created if missing)
  - ``origin + push``  : ``origin`` set on the local clone and main pushed
  - ``collaborator: X``: Member X granted push access via the GitHub API

For ``kind="local"`` repos the GitHub-specific steps are skipped — the
bare repo on a shared filesystem doesn't have a collaborator concept.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import git_providers as _GP
from .frontmatter import parse_file
from .preflight import Probe

_log = logging.getLogger(__name__)


@dataclass
class ProvisionContext:
    """Inputs to :func:`provision_project_remote`. Kept as a dataclass
    so the server endpoint and the request-approve path can build it
    without juggling keyword arguments.

    Phase 4 (2026-05-15): ``provider`` is the canonical input — a
    fully-resolved :class:`GitProvider`. Callers that still hand-build
    ``kind`` / ``org`` / ``bare_repo_path`` get translated into a
    synthesized provider for back-compat.
    """

    project: str
    local_repo: Path
    kind: str = "github"
    org: str = ""  # empty = unconfigured; provisioning fails safe (see line ~441)
    bare_repo_path: Path | None = None
    members: list[str] | None = None
    lab_mgmt_root: Path | None = None  # for resolving member git logins
    # Phase 4 inputs (preferred). When ``provider`` is set, ``kind`` /
    # ``org`` / ``bare_repo_path`` above are ignored — the provider's
    # kind + target are the source of truth. ``provider_id`` is the
    # provider's id, also used as the key into each member's
    # ``git_logins`` dict for collaborator-sync lookups.
    provider: "_GP.GitProvider | None" = None
    provider_id: str | None = None


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run ``gh`` and return the completed process. Never raises on
    non-zero exit — callers inspect ``returncode`` to build the probe."""
    return subprocess.run(  # noqa: S603 — args are a list
        ["gh", *args], check=False, capture_output=True, text=True, timeout=timeout,
    )


def _provider_login(
    handle: str, provider_id: str, lab_mgmt_root: Path | None,
) -> str | None:
    """Look up the user's login on ``provider_id`` from their profile.

    Returns ``git_logins[provider_id]`` from the member's frontmatter,
    or ``None`` when missing. For the ``github`` provider id, falls
    back to the legacy ``contact.github`` field so members who haven't
    re-saved their profile since the Phase 3 refactor still resolve
    correctly. See [[project-git-providers-model]].
    """
    if lab_mgmt_root is None:
        return None
    norm = handle.lstrip("@").strip()
    if not norm:
        return None
    path = lab_mgmt_root / "members" / f"{norm}.md"
    if not path.is_file():
        return None
    try:
        meta = parse_file(path).meta or {}
    except Exception:
        return None
    logins = _GP.parse_logins(meta)
    val = logins.get(provider_id)
    if val:
        return val
    return None


def _github_login(handle: str, lab_mgmt_root: Path | None) -> str | None:
    """Legacy alias for :func:`_provider_login` (provider id ``github``)."""
    return _provider_login(handle, "github", lab_mgmt_root)


def _probe_repo_exists(org: str, project: str) -> Probe:
    """Check if the GitHub repo already exists. Doesn't create it.

    ``gh repo view`` exits 0 when the repo exists, non-zero when not.
    Network failures look the same as "doesn't exist" from the CLI's
    side; we don't distinguish — the next probe will create-or-noop.
    """
    if not _gh_available():
        return Probe(
            name="github repo",
            status="fail",
            detail="gh CLI not installed — install with `brew install gh && gh auth login`.",
            required=True,
        )
    res = _gh(["repo", "view", f"{org}/{project}", "--json", "name"])
    if res.returncode == 0:
        return Probe(
            name="github repo",
            status="ok",
            detail=f"{org}/{project} (already exists on github)",
            required=True,
        )
    return Probe(
        name="github repo",
        status="warn",
        detail=f"{org}/{project} not found on github — will create",
        required=True,
    )


def _probe_repo_create(org: str, project: str) -> Probe:
    """Create the GitHub repo (idempotent — no-ops when it exists)."""
    res = _gh([
        "repo", "create", f"{org}/{project}", "--private",
        "--description", f"Wigamig project {project}.",
    ])
    if res.returncode == 0:
        return Probe(
            name="github repo create",
            status="ok",
            detail=f"created {org}/{project}",
            required=True,
        )
    # Re-running on an existing repo prints "name already exists" — that
    # is success, not a failure. Detect that case so the panel doesn't
    # glare red on the second approval.
    err = (res.stderr or "").lower()
    if "already exists" in err or "name already exists" in err:
        return Probe(
            name="github repo create",
            status="ok",
            detail=f"{org}/{project} already exists",
            required=True,
        )
    return Probe(
        name="github repo create",
        status="fail",
        detail=(res.stderr or res.stdout).strip() or f"gh repo create exited {res.returncode}",
        required=True,
    )


def _probe_set_origin_and_push(repo_dir: Path, url: str) -> Probe:
    """Set ``origin`` to ``url`` (idempotent) and push main."""
    existing = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_dir), check=False, capture_output=True, text=True,
    )
    if existing.returncode != 0:
        op = subprocess.run(
            ["git", "remote", "add", "origin", url],
            cwd=str(repo_dir), check=False, capture_output=True, text=True,
        )
        if op.returncode != 0:
            return Probe(
                name="origin + push",
                status="fail",
                detail=(op.stderr or op.stdout).strip() or "git remote add failed",
                required=True,
            )
    elif existing.stdout.strip() != url:
        op = subprocess.run(
            ["git", "remote", "set-url", "origin", url],
            cwd=str(repo_dir), check=False, capture_output=True, text=True,
        )
        if op.returncode != 0:
            return Probe(
                name="origin + push",
                status="fail",
                detail=(op.stderr or op.stdout).strip() or "git remote set-url failed",
                required=True,
            )
    push = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(repo_dir), check=False, capture_output=True, text=True,
    )
    if push.returncode != 0:
        return Probe(
            name="origin + push",
            status="warn",
            detail=(
                (push.stderr or push.stdout).strip()
                or "push failed (no upstream yet?) — run `git push -u origin main` manually"
            ),
            required=False,
        )
    return Probe(
        name="origin + push",
        status="ok",
        detail=f"origin = {url}; pushed main",
        required=True,
    )


def _probe_collaborator(
    org: str, project: str, handle: str, login: str | None
) -> Probe:
    """Grant ``login`` push access on ``org/project`` (idempotent)."""
    label = f"collab: @{handle.lstrip('@')}"
    if not login:
        return Probe(
            name=label,
            status="warn",
            detail=(
                "no github login on member profile — set contact.github "
                f"on members/{handle.lstrip('@')}.md and re-sync"
            ),
            required=False,
        )
    if not _gh_available():
        return Probe(
            name=label,
            status="fail",
            detail="gh CLI not installed",
            required=False,
        )
    res = _gh([
        "api", "-X", "PUT",
        f"repos/{org}/{project}/collaborators/{login}",
        "-f", "permission=push",
    ])
    if res.returncode == 0:
        body = (res.stdout or "").strip()
        # PUT returns 201 (Created) for new invites and 204 (No Content)
        # for users already in the org. gh prints the JSON body for 201
        # and nothing for 204. Either way it's success.
        return Probe(
            name=label,
            status="ok",
            detail=f"github={login} ({'invited' if body else 'already had access'})",
            required=False,
        )
    err = (res.stderr or res.stdout or "").strip()
    # 422 is what gh returns when ``login`` is the repo owner / an org
    # owner — they already have admin and you can't add them as a
    # collaborator (the API rejects the invite). Treat as a non-issue
    # rather than scary red, because there is literally nothing to fix.
    err_lower = err.lower()
    is_owner_skip = (
        "422" in err
        or "validation failed" in err_lower
        or "cannot add the repo owner" in err_lower
        or "is already a collaborator" in err_lower
    )
    if is_owner_skip:
        return Probe(
            name=label,
            status="ok",
            detail=f"github={login} (owner / already has admin — skip)",
            required=False,
        )
    return Probe(
        name=label,
        status="fail",
        detail=err or f"gh api exited {res.returncode}",
        required=False,
    )


def _resolve_provider(ctx: ProvisionContext) -> tuple[_GP.GitProvider, str]:
    """Return the provider to dispatch on, plus its id for login lookups.

    Three input shapes accepted (in priority order):
      1. ``ctx.provider`` set explicitly → use it as-is.
      2. ``ctx.kind == "local"`` → synthesize a ``local-bare`` provider
         with target = ``ctx.bare_repo_path`` (legacy callers).
      3. Default (``ctx.kind == "github"``) → synthesize a ``github``
         provider with target = ``ctx.org``.
    """
    if ctx.provider is not None:
        return ctx.provider, ctx.provider_id or ctx.provider.id
    if ctx.kind == "local":
        return _GP.GitProvider(
            id=ctx.provider_id or "local",
            kind="local-bare",
            target=str(ctx.bare_repo_path or ""),
        ), ctx.provider_id or "local"
    return _GP.GitProvider(
        id=ctx.provider_id or "github",
        kind="github",
        target=ctx.org,
    ), ctx.provider_id or "github"


def provision_project_remote(ctx: ProvisionContext) -> list[Probe]:
    """Provision the git origin for ``ctx.project`` with structured
    progress.

    The local working tree at ``ctx.local_repo`` must already exist with
    a ``.git/`` dir (the request-approve path creates it before calling
    this). Returns one ``Probe`` per discrete step; the caller is
    responsible for displaying them and (optionally) deciding whether to
    short-circuit the rest of the approve flow on a required failure.

    Phase 4: dispatches on the provider's ``kind``:
      - ``github``     → existing gh CLI flow (org from provider.target)
      - ``local-bare`` → ``git init --bare`` at provider.target
      - ``gitea``      → stub probe; real implementation pending
    """
    probes: list[Probe] = []

    if not (ctx.local_repo / ".git").is_dir():
        probes.append(Probe(
            name="local clone",
            status="fail",
            detail=(
                f"{ctx.local_repo} has no .git/ — run `wigamig project new {ctx.project}` "
                "first to scaffold the working tree."
            ),
            required=True,
        ))
        return probes
    probes.append(Probe(
        name="local clone",
        status="ok",
        detail=str(ctx.local_repo),
        required=True,
    ))

    provider, provider_id = _resolve_provider(ctx)

    if provider.kind == "local-bare":
        target = provider.target
        if not target:
            probes.append(Probe(
                name="local bare repo",
                status="fail",
                detail=f"provider {provider.id!r} (local-bare) has no target path",
                required=True,
            ))
            return probes
        bare = Path(target).expanduser()
        # Existing per-project bare repos live at ``<target>/<project>.git``
        # (matches the legacy ``lab_base/repos/<project>.git`` convention).
        # If the caller already passed a full path ending in ``.git`` we
        # honour it verbatim — otherwise we tack on the project suffix.
        if not str(bare).endswith(".git"):
            bare = bare / f"{ctx.project}.git"
        try:
            bare.parent.mkdir(parents=True, exist_ok=True)
            if not (bare / "HEAD").exists():
                init = subprocess.run(
                    ["git", "init", "--bare", str(bare)],
                    check=False, capture_output=True, text=True,
                )
                if init.returncode != 0:
                    probes.append(Probe(
                        name="local bare repo",
                        status="fail",
                        detail=(init.stderr or init.stdout).strip(),
                        required=True,
                    ))
                    return probes
                probes.append(Probe(
                    name="local bare repo",
                    status="ok",
                    detail=f"created {bare}",
                    required=True,
                ))
            else:
                probes.append(Probe(
                    name="local bare repo",
                    status="ok",
                    detail=f"{bare} (already exists)",
                    required=True,
                ))
        except OSError as exc:
            probes.append(Probe(
                name="local bare repo",
                status="fail",
                detail=f"could not initialize: {exc}",
                required=True,
            ))
            return probes
        probes.append(_probe_set_origin_and_push(ctx.local_repo, str(bare)))
        # Local-bare repos have no per-user collaborator concept — the
        # filesystem ACL on the lab server is the access control.
        return probes

    if provider.kind == "gitea":
        # Phase 4 stub. A real implementation needs to (a) hit the
        # gitea API to create repos under provider.target's instance,
        # (b) push, (c) add each member as a collaborator using
        # git_logins[provider_id]. Surface a clear yellow probe so the
        # UI doesn't pretend the install succeeded silently.
        probes.append(Probe(
            name="gitea provider",
            status="warn",
            detail=(
                f"provider {provider.id!r} (kind=gitea, target={provider.target!r}) "
                "is not yet implemented. Track in project-git-providers-model memory; "
                "manual `git remote add origin …` works as a workaround."
            ),
            required=True,
        ))
        return probes

    if provider.kind != "github":
        probes.append(Probe(
            name="provider",
            status="fail",
            detail=f"unknown provider kind: {provider.kind!r}",
            required=True,
        ))
        return probes

    # provider.kind == "github"
    org = provider.target or ""
    if not org:
        # Fail safe: never substitute another lab's org. Without a
        # configured org we cannot create the repo or add collaborators
        # — refuse with a clear, actionable probe instead of querying or
        # writing to a stranger's org.
        probes.append(Probe(
            name="github org",
            status="fail",
            detail="no GitHub org configured — set github_org in lab.md",
            required=True,
        ))
        return probes
    exists = _probe_repo_exists(org, ctx.project)
    probes.append(exists)
    if exists.status == "fail":
        return probes
    if exists.status == "warn":
        probes.append(_probe_repo_create(org, ctx.project))
        if probes[-1].status == "fail":
            return probes

    url = f"git@github.com:{org}/{ctx.project}.git"
    probes.append(_probe_set_origin_and_push(ctx.local_repo, url))

    # Collaborator sync uses the project's provider id as the key into
    # each member's ``git_logins`` map. Falls back to the legacy
    # ``contact.github`` field when the provider is ``github``.
    for handle in (ctx.members or []):
        login = _provider_login(handle, provider_id, ctx.lab_mgmt_root)
        probes.append(_probe_collaborator(org, ctx.project, handle, login))

    return probes
