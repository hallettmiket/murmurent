"""
Purpose: Choose which definition of each agent Claude Code uses, across five
         levels, and install the winners (issue #186, steps 2 to 4).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: agent definitions at each level (below); the repo being worked in.
Output: links in ``~/.claude/agents/`` and in each repo's ``.claude/agents/``
        pointing at the winning file; ``Agent(<name>)`` deny rules in a repo's
        ``.claude/settings.local.json`` for agents switched off there.

The levels, most specific first (Mike's decisions on #186: a person's own
version beats the lab's; lab agents live in the lab management repo):

1. person, one project: ``<vault>/projects/<project>/agents/<name>.md``
2. project:             ``<repo>/.murmurent/agents/<name>.md``, committed
3. person, everywhere:  ``<vault>/agent_forks/`` or ``<vault>/agents/``
4. lab:                 ``<lab management repo>/agents/<name>.md``
5. centre:              the commons ``agents/<name>.md``

How it reaches Claude Code. Claude Code reads a repo's ``.claude/agents/``
before ``~/.claude/agents/``. So ``~/.claude/agents/`` holds the winner among
levels 3 to 5 (``sync_user_level``), and each repo's ``.claude/agents/`` holds
links to the winner among all five for the agents it needs
(``sync_repo``). Those repo links are listed in the repo's managed
``.gitignore`` block, so they never reach anyone else (#150). A real file a
person or project put in ``.claude/agents/`` is never replaced.

Switching off. "Use our own blacksmith" is a version at a more specific level.
"No blacksmith in this project" is a switch-off: a person's list in
``<vault>/projects/<project>/agents_off.yaml``, or the project's
``agents_off:`` list in ``.murmurent.yaml``. It becomes Claude Code's
documented deny rule, ``Agent(<name>)``, in the repo's
``.claude/settings.local.json``, which applies to that repo on that machine.

What cannot be overridden: the guardian agents (security_guard, adversary,
conscience) and any centre agent marked ``freeze: frozen`` always use the
centre definition, and a guardian cannot be switched off.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import agent_forks as _af

PERSON_PROJECT = "person-project"
PROJECT = "project"
PERSON = "person"
LAB = "lab"
CENTRE = "centre"

#: Words for each level, for the dashboard and `murmurent agent which`.
LABELS = {PERSON_PROJECT: "your version for this project", PROJECT: "project version",
          PERSON: "your version", LAB: "lab version", CENTRE: "centre version"}

OFF_FILE = "agents_off.yaml"
SETTINGS_LOCAL = Path(".claude") / "settings.local.json"


# ---------------------------------------------------------------------------
# Where each level lives
# ---------------------------------------------------------------------------

def _vault() -> Path | None:
    try:
        from .vault_sync import personal_vault_root
        return personal_vault_root()
    except Exception:  # noqa: BLE001
        return None


def person_project_dir(project: str) -> Path | None:
    """``<vault>/projects/<project>/agents``; None without a personal vault."""
    v = _vault()
    return (v / "projects" / project / "agents") if (v is not None and project) else None


def project_agents_dir(repo: Path) -> Path:
    return Path(repo) / ".murmurent" / "agents"


def lab_agents_dir() -> Path | None:
    try:
        from .repo import lab_mgmt_repo_root
        d = lab_mgmt_repo_root() / "agents"
    except Exception:  # noqa: BLE001
        return None
    return d if d.is_dir() else None


def _person_file(name: str) -> Path | None:
    """The person's own version for all projects: a fork murmurent made, or an
    agent of their own, both kept in the vault (or the legacy fork home)."""
    fork = _af.forks_dir() / f"{name}.md"
    if fork.is_file() and name in _af.load_manifest().get("forks", {}):
        return fork
    try:
        from . import personal_agents as _pa
        d = _pa.vault_agents_dir()
        if d is not None and (Path(d) / f"{name}.md").is_file():
            return Path(d) / f"{name}.md"
    except Exception:  # noqa: BLE001
        pass
    return None


def is_locked(name: str) -> bool:
    """True for a guardian or a centre agent marked frozen: centre only."""
    try:
        from . import personal_audit as _audit
        from .frontmatter import parse_file
        centre = _af.commons_agent_path(name)
        meta = parse_file(centre).meta or {} if centre.is_file() else {}
        if str(meta.get("freeze") or "").strip().lower() == "frozen":
            return True
        return bool(_audit._is_guardian(name, meta))
    except Exception:  # noqa: BLE001
        return name in ("security_guard", "adversary", "conscience")


def is_guardian(name: str) -> bool:
    try:
        from . import personal_audit as _audit
        return name in _audit.GUARDIAN_AGENTS
    except Exception:  # noqa: BLE001
        return name in ("security_guard", "adversary", "conscience")


# ---------------------------------------------------------------------------
# Choosing the winner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Winner:
    level: str
    path: Path

    @property
    def label(self) -> str:
        return LABELS[self.level]


def resolve(name: str, *, project: str | None = None, repo: Path | None = None,
            user_level_only: bool = False) -> Winner | None:
    """The winning definition of ``name``, or None if no level has one.

    ``user_level_only`` considers levels 3 to 5 only (what ``~/.claude/agents``
    holds). A locked agent always resolves to the centre.
    """
    centre = _af.commons_agent_path(name)
    if is_locked(name):
        return Winner(CENTRE, centre) if centre.is_file() else None
    if not user_level_only:
        if project:
            d = person_project_dir(project)
            if d is not None and (d / f"{name}.md").is_file():
                return Winner(PERSON_PROJECT, d / f"{name}.md")
        if repo is not None:
            f = project_agents_dir(repo) / f"{name}.md"
            if f.is_file():
                return Winner(PROJECT, f)
    own = _person_file(name)
    if own is not None:
        return Winner(PERSON, own)
    lab = lab_agents_dir()
    if lab is not None and (lab / f"{name}.md").is_file():
        return Winner(LAB, lab / f"{name}.md")
    return Winner(CENTRE, centre) if centre.is_file() else None


def switched_off(project: str | None, repo: Path | None) -> set[str]:
    """Agents switched off for this repo: the person's list for the project
    plus the project's own ``agents_off`` in ``.murmurent.yaml``. Guardians
    are never switched off."""
    names: set[str] = set()
    if project:
        d = person_project_dir(project)
        if d is not None:
            names |= set(_read_list(d.parent / OFF_FILE))
    if repo is not None:
        marker = Path(repo) / ".murmurent.yaml"
        try:
            meta = yaml.safe_load(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
        except (OSError, yaml.YAMLError):
            meta = {}
        names |= {str(n) for n in (meta or {}).get("agents_off") or []}
    return {n for n in names if not is_guardian(n)}


def _read_list(path: Path) -> list[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, yaml.YAMLError):
        return []
    return [str(n) for n in (data or [])] if isinstance(data, list) else []


def set_switched_off(project: str, name: str, off: bool) -> Path:
    """Add or remove ``name`` from the person's switch-off list for ``project``."""
    d = person_project_dir(project)
    if d is None:
        raise RuntimeError("switching an agent off for one project needs a personal "
                           "vault (murmurent vault init)")
    if off and is_guardian(name):
        raise RuntimeError(f"{name} is a guardian agent and cannot be switched off")
    path = d.parent / OFF_FILE
    names = set(_read_list(path))
    names = (names | {name}) if off else (names - {name})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(sorted(names)), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Installing the winners
# ---------------------------------------------------------------------------

@dataclass
class SyncReport:
    linked: list[str] = field(default_factory=list)     # "name -> level"
    left: list[str] = field(default_factory=list)       # real files kept
    off: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _point(link: Path, target: Path) -> bool:
    """Make ``link`` a symlink to ``target``; True if it changed."""
    try:
        if link.is_symlink() and os.readlink(link) == str(target):
            return False
        if link.is_symlink():
            link.unlink()
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        return True
    except OSError:
        return False


def _is_ours(link: Path) -> bool:
    """A link murmurent may repoint: into the commons, the lab agents, or a vault."""
    if not link.is_symlink():
        return False
    target = Path(os.readlink(link))
    roots = [p for p in (_af.commons_agents_dir(), lab_agents_dir(), _vault(),
                         _af.forks_dir()) if p is not None]
    try:
        roots += [Path(str(r)).resolve() for r in roots]
    except OSError:
        pass
    return any(str(target).startswith(str(r)) for r in roots) or not target.exists()


def sync_user_level() -> SyncReport:
    """Put the lab's versions into ``~/.claude/agents`` where the person has no
    version of their own, and back to the centre's where the lab removed one.
    A person's own version (fork, own agent, hand-written file) is never
    touched: their version beats the lab's."""
    rep = SyncReport()
    cc = _af.installed_agents_dir()
    lab = lab_agents_dir()
    names = set(p.stem for p in lab.glob("*.md")) if lab else set()
    names |= {p.stem for p in cc.glob("*.md") if p.is_symlink()} if cc.is_dir() else set()
    for name in sorted(names):
        link = cc / f"{name}.md"
        if link.exists() and not link.is_symlink():
            continue                         # a fork or a hand-written file
        if link.is_symlink() and not _is_ours(link):
            continue
        win = resolve(name, user_level_only=True)
        if win is None or win.level == PERSON:
            continue                         # personal agents are relinked elsewhere
        if _point(link, win.path):
            rep.linked.append(f"{name} -> {win.level}")
    return rep


def sync_repo(repo: Path, project: str | None = None) -> SyncReport:
    """Install the winners into ``repo/.claude/agents`` and apply switch-offs.

    Manages the agents the repo already links, plus every agent with a
    project or person-in-project version. Real files are left alone.
    """
    from . import agent_links as _links
    repo = Path(repo).expanduser()
    rep = SyncReport()
    if project is None:
        try:
            from . import cert_projects as _cp
            owner = _cp.owning_project(repo.name)
            project = owner.name if owner else None
        except Exception:  # noqa: BLE001
            project = None
    agents = repo / ".claude" / "agents"
    names = {p.stem for p in agents.glob("*.md")} if agents.is_dir() else set()
    names |= {p.stem for p in project_agents_dir(repo).glob("*.md")} \
        if project_agents_dir(repo).is_dir() else set()
    pp = person_project_dir(project) if project else None
    if pp is not None and pp.is_dir():
        names |= {p.stem for p in pp.glob("*.md")}

    tracked = _tracked(repo)
    for name in sorted(names):
        here = agents / f"{name}.md"
        if f".claude/agents/{name}.md" in tracked:
            # Committed: changing it would leave a change in a shared repo.
            rep.left.append(name)
            if here.is_symlink():
                rep.notes.append(f"{name}: a committed link; {_links.repair_hint(repo)}")
            continue
        if here.exists() and not here.is_symlink():
            rep.left.append(name)
            continue
        if here.is_symlink() and not _is_ours(here):
            rep.left.append(name)
            continue
        win = resolve(name, project=project, repo=repo)
        if win is None:
            if here.is_symlink():
                here.unlink()
            continue
        _point(here, win.path)
        rep.linked.append(f"{name} -> {win.level}")

    rep.notes = list(dict.fromkeys(rep.notes))
    linked_now = sorted(p.stem for p in agents.glob("*.md") if p.is_symlink()) \
        if agents.is_dir() else []
    _links.update_gitignore(repo, linked_now)
    rep.off = sorted(_apply_off(repo, switched_off(project, repo)))
    return rep


def _tracked(repo: Path) -> set[str]:
    """Paths under ``.claude/agents`` that are committed in ``repo``."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files", ".claude/agents"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _state_path() -> Path:
    from .project_unit import murmurent_home
    return murmurent_home() / "agent_off_state.json"


def _apply_off(repo: Path, off: set[str]) -> set[str]:
    """Make the repo's ``settings.local.json`` deny exactly the agents in
    ``off`` that murmurent manages, keeping every rule a person added. The
    names murmurent added are remembered per repo in ~/.murmurent so they can
    be taken out again."""
    state_file = _state_path()
    try:
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
    except (OSError, ValueError):
        state = {}
    key = str(repo.resolve())
    before = set(state.get(key, []))
    path = repo / SETTINGS_LOCAL
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return before          # leave a settings file we cannot read alone
    perms = data.setdefault("permissions", {})
    deny = [r for r in perms.get("deny", []) if r not in {f"Agent({n})" for n in before}]
    deny += [f"Agent({n})" for n in sorted(off) if f"Agent({n})" not in deny]
    if deny:
        perms["deny"] = deny
    else:
        perms.pop("deny", None)
        if not perms:
            data.pop("permissions", None)
    if data or path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    state[key] = sorted(off)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return off


# ---------------------------------------------------------------------------
# Actions shared by the commands and the dashboard
# ---------------------------------------------------------------------------

class LevelError(RuntimeError):
    """An action on an agent's version that cannot be done; the message is
    meant for a person."""


def project_repos(project: str) -> list[Path]:
    return [p for name, p in local_project_repos() if name == project]


def fork_for_project(name: str, project: str) -> tuple[Path, bool]:
    """Copy the version in use into the vault as your version for one project.
    Returns ``(path, created)``; then syncs that project's repos here."""
    import shutil
    if is_locked(name):
        raise LevelError(f"{name} is centre-controlled and cannot have its own version.")
    dest_dir = person_project_dir(project)
    if dest_dir is None:
        raise LevelError("a version for one project is kept in your personal vault; "
                         "set one up first with `murmurent vault init`.")
    dest = dest_dir / f"{name}.md"
    created = False
    if not dest.exists():
        win = resolve(name, user_level_only=True)
        if win is None:
            raise LevelError(f"no agent named {name!r}.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(win.path, dest)
        created = True
    for repo in project_repos(project):
        sync_repo(repo, project)
    return dest, created


def switch(name: str, project: str, off: bool) -> None:
    """Switch an agent off (or on) for you in one project, and sync its repos."""
    try:
        set_switched_off(project, name, off)
    except RuntimeError as exc:
        raise LevelError(str(exc)) from exc
    for repo in project_repos(project):
        sync_repo(repo, project)


def share_with_lab(name: str) -> tuple[Path, list]:
    """PI only: make the version in use the lab's, committed and pushed."""
    import shutil
    from . import git_persist
    from .identity import resolve as _who
    from .lab import pi_handle
    from .repo import lab_mgmt_repo_root
    if is_locked(name):
        raise LevelError(f"{name} is centre-controlled and cannot be replaced.")
    me = (_who(allow_unknown=True).handle or "").lstrip("@").lower()
    if me != pi_handle().lstrip("@").lower():
        raise LevelError("only the PI can set the lab's version of an agent.")
    win = resolve(name, user_level_only=True)
    if win is None:
        raise LevelError(f"no agent named {name!r}.")
    dest = lab_mgmt_repo_root() / "agents" / f"{name}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if win.path.resolve() != dest.resolve():
        shutil.copyfile(win.path, dest)
    probes = git_persist.commit_and_push(dest, message=f"lab version of agent {name} (#186)")
    sync_user_level()
    return dest, probes


def switched_off_for(project: str) -> list[str]:
    """Agents you switched off in ``project``."""
    d = person_project_dir(project)
    return sorted(_read_list(d.parent / OFF_FILE)) if d is not None else []


def local_project_repos() -> list[tuple[str, Path]]:
    """``(project, repo path)`` for every project repo cloned on this machine."""
    out: list[tuple[str, Path]] = []
    try:
        from . import cert_projects as _cp
        for p in _cp.iter_projects():
            for r in p.repos:
                if (r.host or "local") == "local" and r.path:
                    path = Path(r.path).expanduser()
                    if (path / ".git").exists():
                        out.append((p.name, path))
    except Exception:  # noqa: BLE001
        pass
    return out
