"""
Purpose: give a repository a GitHub remote and grant the project's members
         access, in one step, when it is added to a project (#269). Creating
         a GitHub repository is a project decision, so it belongs here with
         ``murmurent project add-repo --create-remote``, never in make ready.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-02
Input:   the project record, the local clone, the lab's ``github_org``, the
         ``gh`` command.
Output:  a private ``<org>/<repo>`` on GitHub with the clone pushed to it,
         ``remote_url`` on the project's repository entry, and collaborator
         access for every certified member.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import cert_projects as _cp


def origin_of(repo_dir: Path) -> str:
    """The clone's ``origin`` URL, or ''."""
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def current_branch(repo_dir: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    name = out.stdout.strip() if out.returncode == 0 else ""
    return "" if name == "HEAD" else name


def _default_creator(org: str, name: str) -> tuple[bool, str]:
    """``gh repo create <org>/<name> --private``; an existing repository is fine."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return False, "gh CLI not installed (brew install gh && gh auth login)"
    if _pp._gh(["repo", "view", f"{org}/{name}", "--json", "name"]).returncode == 0:
        return True, "already on GitHub"
    res = _pp._gh(["repo", "create", f"{org}/{name}", "--private",
                   "--description", f"murmurent project repository {name}."])
    if res.returncode == 0:
        return True, "created"
    err = (res.stderr or res.stdout or "").strip()
    if "already exists" in err.lower():
        return True, "already on GitHub"
    return False, err or f"gh repo create exited {res.returncode}"


def _default_pusher(repo_dir: Path, url: str) -> tuple[bool, str]:
    """Set ``origin`` to ``url`` and push the current branch."""
    existing = origin_of(repo_dir)
    verb = ["add"] if not existing else (["set-url"] if existing != url else [])
    if verb:
        op = subprocess.run(["git", "-C", str(repo_dir), "remote", *verb, "origin", url],
                            capture_output=True, text=True, check=False)
        if op.returncode != 0:
            return False, (op.stderr or op.stdout).strip() or "git remote failed"
    branch = current_branch(repo_dir) or "main"
    push = subprocess.run(["git", "-C", str(repo_dir), "push", "-u", "origin", branch],
                          capture_output=True, text=True, check=False)
    if push.returncode != 0:
        return False, (push.stderr or push.stdout).strip() or "git push failed"
    return True, f"pushed {branch}"


def github_org_for(cp, *, env: dict | None = None) -> str:
    """The organisation a project's repositories are created under: the lab's
    ``github_org`` (``lab.md``), read from the records that hold the project."""
    try:
        from .lab import load_lab_config
        return str(load_lab_config().github_org or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def create_remote_and_grant(project: str, repo_name: str, *, env: dict | None = None,
                            org: str = "", creator=None, pusher=None,
                            github_reconciler=None) -> dict:
    """Create ``<org>/<repo_name>`` on GitHub for the project's repository
    ``repo_name`` (a clone on this machine), set its ``origin``, push, record
    the remote on the project's entry, and grant every certified member
    access on it (#269). A clone that already has a GitHub origin skips the
    creation and keeps its remote. Returns ``{ok, repo, remote_url, created,
    pushed, github, problems}``; never raises for a GitHub refusal."""
    from .repo import github_slug as _slug
    creator = creator or _default_creator
    pusher = pusher or _default_pusher
    out: dict = {"ok": False, "repo": repo_name, "remote_url": "", "created": "",
                 "pushed": "", "github": None, "problems": []}
    cp = _cp.get(project, env)
    if cp is None:
        out["problems"].append(f"no project named {project!r}")
        return out
    entry = next((r for r in cp.repos if r.name.casefold() == repo_name.casefold()), None)
    if entry is None:
        out["problems"].append(f"{project} does not list a repository named {repo_name}")
        return out
    if (entry.host or "local") != "local" or not entry.path:
        out["problems"].append(f"{repo_name} is not a clone on this machine; create its "
                               "remote where the clone is")
        return out
    repo_dir = Path(entry.path).expanduser()
    if not (repo_dir / ".git").exists():
        out["problems"].append(f"{repo_dir} is not a git repository")
        return out

    existing = origin_of(repo_dir)
    if existing and _slug(existing):
        url, created = existing, "kept the existing GitHub remote"
    else:
        org = (org or github_org_for(cp, env=env)).strip()
        if not org:
            out["problems"].append("no GitHub organisation to create it under: set "
                                   "github_org in the lab's lab.md")
            return out
        ok, detail = creator(org, repo_name)
        if not ok:
            out["problems"].append(f"could not create {org}/{repo_name}: {detail}")
            return out
        created = detail
        url = f"git@github.com:{org}/{repo_name}.git"
        ok, detail = pusher(repo_dir, url)
        out["pushed"] = detail
        if not ok:
            out["problems"].append(f"could not push {repo_name} to {url}: {detail}")
    out["created"], out["remote_url"] = created, url
    # Record the remote on the entry, keeping everything else about it.
    try:
        _cp.add_repo(project, role=entry.role, repo_name=entry.name, host=entry.host,
                     path=entry.path, remote_path=entry.remote_path, remote_url=url,
                     overleaf=entry.overleaf, env=env)
    except _cp.CertProjectError as exc:
        out["problems"].append(f"could not record the remote: {exc}")
    # Access follows membership (#255): every certified member, now.
    try:
        from . import cert_provision as _cprov
        reconcile = github_reconciler or _cprov.reconcile_github
        out["github"] = reconcile(project, env=env, remove_extras=False)
        out["problems"] += list(out["github"].get("problems") or [])
    except Exception as exc:  # noqa: BLE001
        out["problems"].append(f"could not grant access: {exc}")
    out["ok"] = not any(p.startswith(("could not create", "could not push")) for p in out["problems"])
    return out


__all__ = ["origin_of", "current_branch", "github_org_for", "create_remote_and_grant"]
