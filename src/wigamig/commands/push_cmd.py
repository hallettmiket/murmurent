"""
Purpose: Implementations of ``wigamig push`` and ``wigamig pull``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI arguments forwarded from :mod:`wigamig.cli`.
Output: Side effects on the project repo's git state, GitHub remote, and the
        notebook's ``refined_data`` / ``checksums`` frontmatter.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click

from ..core import lab_vm
from ..core.frontmatter import dump_document, parse_file
from ..core.identity import resolve as resolve_identity
from ..core.notebook import ChecksumEntry, sha256_file
from ..core.projects import find_project
from ..core.repo import ProjectRepo

GITHUB_ORG = "hallettmiket"


def _resolve_repo(project_name: str) -> ProjectRepo:
    repo = find_project(project_name)
    if repo is None:
        raise click.ClickException(f"Project not found locally: {project_name}")
    return repo


def _run(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), check=check, text=True, capture_output=True)


def _git(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", *cmd], cwd=cwd, check=check)


def _current_branch(repo: ProjectRepo) -> str:
    out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo.path)
    return out.stdout.strip()


def _has_uncommitted(repo: ProjectRepo) -> bool:
    out = _git(["status", "--porcelain"], cwd=repo.path)
    return bool(out.stdout.strip())


def _personal_branch(handle: str, topic: str) -> str:
    safe_topic = topic.strip().replace(" ", "-")
    return f"member/{handle}/{safe_topic}"


def _ensure_personal_branch(repo: ProjectRepo, branch: str) -> None:
    """Switch to ``branch``, creating it if necessary."""
    current = _current_branch(repo)
    if current == branch:
        return
    existing = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=str(repo.path),
        check=False,
        capture_output=True,
        text=True,
    )
    if existing.returncode == 0:
        _git(["checkout", branch], cwd=repo.path)
    else:
        _git(["checkout", "-b", branch], cwd=repo.path)


def cmd_push(
    project_name: str,
    *,
    message: str | None,
    finalize: bool,
    refined: str | None,
    topic: str | None = None,
) -> int:
    """``wigamig push`` — personal branch push, finalize PR, or refined refresh."""
    repo = _resolve_repo(project_name)
    identity = resolve_identity(allow_unknown=True)
    handle = identity.handle

    if refined is not None:
        return _push_refined(repo, exp_slug=refined, handle=handle, message=message)

    if finalize:
        return _push_finalize(repo, handle=handle, message=message)

    return _push_personal(repo, handle=handle, message=message, topic=topic)


def cmd_pull(project_name: str) -> int:
    """``wigamig pull`` — fetch + fast-forward main."""
    repo = _resolve_repo(project_name)
    _git(["fetch", "--all", "--prune"], cwd=repo.path, check=False)
    current = _current_branch(repo)
    res = _git(["pull", "--ff-only"], cwd=repo.path, check=False)
    click.echo(res.stdout.strip() or f"pulled {current}")
    return 0


# ---------------------------------------------------------------------------
# Push variants
# ---------------------------------------------------------------------------


def _push_personal(
    repo: ProjectRepo,
    *,
    handle: str,
    message: str | None,
    topic: str | None,
) -> int:
    if topic is None:
        topic = "wip"
    branch = _personal_branch(handle, topic)
    _ensure_personal_branch(repo, branch)
    if _has_uncommitted(repo):
        _git(["add", "-A"], cwd=repo.path)
        commit_msg = message or f"wip on {topic}"
        _git(["commit", "-m", commit_msg], cwd=repo.path)
    if shutil.which("gh") is None or _no_remote(repo):
        click.echo(f"Local branch {branch} created/updated. No 'gh' or no remote — skipping push.")
        return 0
    res = _git(["push", "-u", "origin", branch], cwd=repo.path, check=False)
    click.echo(res.stdout.strip() or f"pushed {branch}")
    return 0


def _push_finalize(repo: ProjectRepo, *, handle: str, message: str | None) -> int:
    branch = _current_branch(repo)
    if branch == "main":
        raise click.ClickException(
            "Refusing to finalize from main. Switch to your personal branch and try again."
        )
    if _has_uncommitted(repo):
        _git(["add", "-A"], cwd=repo.path)
        _git(["commit", "-m", message or f"finalize {branch}"], cwd=repo.path)
    if shutil.which("gh") is None or _no_remote(repo):
        click.echo(f"gh not available or no origin; would open PR from {branch} -> main.")
        return 0
    _git(["push", "-u", "origin", branch], cwd=repo.path, check=False)
    title = message or f"Finalize {branch}"
    body = (
        f"Opened by `wigamig push --finalize` for @{handle}.\n\n"
        f"Source branch: `{branch}`.\n\n"
        "Squad: please review and approve."
    )
    res = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", "main"],
        cwd=str(repo.path),
        check=False,
        capture_output=True,
        text=True,
    )
    click.echo(res.stdout.strip() or res.stderr.strip())
    return 0


def _push_refined(
    repo: ProjectRepo,
    *,
    exp_slug: str,
    handle: str,
    message: str | None,
) -> int:
    project_name = repo.path.name
    refined_dir = lab_vm.experiment_refined_dir(project_name, exp_slug)
    if not refined_dir.is_dir():
        raise click.ClickException(f"refined dir not found: {refined_dir}")
    files: list[Path] = []
    for root, _dirs, names in os.walk(refined_dir):
        for n in names:
            p = Path(root) / n
            if p.is_file() and not p.is_symlink():
                files.append(p)
    files.sort()
    entries = [ChecksumEntry(path=f, sha256=sha256_file(f)) for f in files]

    notebook_path = repo.path / "exp" / exp_slug / "notebook.md"
    if not notebook_path.is_file():
        raise click.ClickException(f"notebook not found: {notebook_path}")
    parsed = parse_file(notebook_path)
    refined_paths = [str(e.path) for e in entries]
    checksums = dict(parsed.meta.get("checksums") or {})
    for e in entries:
        checksums[str(e.path)] = e.sha256
    parsed.meta["refined_data"] = refined_paths
    parsed.meta["checksums"] = checksums
    notebook_path.write_text(dump_document(parsed.meta, parsed.body), encoding="utf-8")
    click.echo(
        f"Recomputed SHA-256 for {len(entries)} files in {refined_dir}; "
        f"updated {notebook_path}."
    )

    return _push_personal(
        repo,
        handle=handle,
        message=message or f"refresh refined checksums for {exp_slug}",
        topic=f"{exp_slug}-refined",
    )


def _no_remote(repo: ProjectRepo) -> bool:
    res = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo.path),
        check=False,
        capture_output=True,
        text=True,
    )
    return res.returncode != 0
