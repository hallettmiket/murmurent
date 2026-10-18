"""
Purpose: Report which version of each agent Claude Code will actually use on
         this machine, and where that version came from (issue #186, step 1).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: an agent name, and optionally a repository folder; the files under
       ``<repo>/.claude/agents/`` and ``~/.claude/agents/``.
Output: :class:`AgentInUse` — the level the definition comes from, a short
        label for a badge, one plain sentence, and the file Claude Code reads.

Read-only. Claude Code picks a definition by location: a repository's
``.claude/agents/<name>.md`` beats the user's ``~/.claude/agents/<name>.md``.
murmurent fills those folders with links into the commons, links into the
member's vault, and copies (forks), so the file name alone does not say whose
definition is running. This module follows each file to say so.

The levels reported today:

- ``centre``: a link into the commons, the definition every member shares;
- ``yours``: the member's own agent or own copy, kept in their vault;
- ``project``: a real file committed in the repository, shared with the team;
- ``local-file``: a real file on this machine only (hand-written, or an
  uncommitted file in a repository);
- ``broken-link``: a link Claude Code cannot follow, for example one that
  points into another member's home folder (the #150 problem);
- ``missing``: no definition installed, so Claude Code cannot use the agent.

Lab and per-project personal versions (#186 steps 2 to 4) will add levels.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import agent_forks as _af

CENTRE = "centre"
YOURS = "yours"
PROJECT = "project"
LOCAL_FILE = "local-file"
BROKEN_LINK = "broken-link"
MISSING = "missing"


@dataclass(frozen=True)
class AgentInUse:
    """Which definition of one agent Claude Code will load, and from where."""

    name: str
    level: str            # one of the module-level constants
    label: str            # a few words for a badge
    detail: str           # one plain sentence for a tooltip or a table
    path: str = ""        # the file Claude Code reads ("" when missing)
    upstream_changed: bool = False  # a copy whose centre original has changed since

    def to_dict(self) -> dict:
        return asdict(self)


def _is_under(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_file(path: Path) -> bool:
    """``Path.is_file`` that answers False instead of raising when the file,
    or a folder a link points through, cannot be read (another member's home
    folder, for example)."""
    try:
        return path.is_file()
    except OSError:
        return False


def _readable(path: Path) -> bool:
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def _vault_agents_dir() -> Path | None:
    try:
        from . import personal_agents as _pa
        d = _pa.vault_agents_dir()
        return _safe_resolve(Path(d)) if d else None
    except Exception:  # noqa: BLE001
        return None


def _is_tracked(repo: Path, rel: str) -> bool:
    """True when ``rel`` is committed in ``repo`` (shared with the team)."""
    try:
        res = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", rel],
                             capture_output=True, text=True, timeout=10)
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _classify_link(name: str, path: Path, *, where: str) -> AgentInUse:
    """A symlink: follow it and say whose definition it is."""
    target = _safe_resolve(path)
    shown = str(target or path)
    if target is None or not _is_file(target) or not _readable(target):
        return AgentInUse(
            name, BROKEN_LINK, "broken link",
            f"{where} links to {shown}, which is missing or cannot be read on "
            "this machine, so Claude Code cannot use this agent.",
            path=str(path))
    commons = _safe_resolve(_af.commons_agents_dir())
    if _is_under(target, commons):
        return AgentInUse(name, CENTRE, "centre version",
            f"{where} links to the shared centre definition.", path=str(target))
    if _is_under(target, _vault_agents_dir()):
        return AgentInUse(name, YOURS, "your agent",
            f"{where} links to your own agent in your vault.", path=str(target))
    return AgentInUse(name, LOCAL_FILE, "linked file",
        f"{where} links to {shown}, which is not a murmurent location.",
        path=str(target))


def _classify_user_file(name: str, path: Path) -> AgentInUse:
    """A real file in ~/.claude/agents: a fork murmurent made, or hand-written."""
    st = _af.status_for(name)
    if st is not None and st.kind == "forked":
        note = (" The centre version has changed since you copied it; "
                "`murmurent agent drift` shows how." if st.upstream_changed else "")
        return AgentInUse(name, YOURS, "your version",
            "You use your own copy of the centre agent, kept in your vault." + note,
            path=str(path), upstream_changed=bool(st.upstream_changed))
    return AgentInUse(name, LOCAL_FILE, "hand-written copy",
        "You use a file written by hand on this machine. It is not in your "
        "vault, so your other machines do not have it.", path=str(path))


def which(name: str, *, repo: Path | None = None) -> AgentInUse:
    """The definition of ``name`` Claude Code will load.

    With ``repo``, a session started in that repository is described: its own
    ``.claude/agents/<name>.md`` wins when present. Without it, a session
    outside any repository with agents of its own. Never raises.
    """
    if repo is not None:
        repo = Path(repo).expanduser()
        here = repo / ".claude" / "agents" / f"{name}.md"
        if here.is_symlink():
            return _classify_link(name, here, where="This repo")
        if _is_file(here):
            rel = f".claude/agents/{name}.md"
            if _is_tracked(repo, rel):
                return AgentInUse(name, PROJECT, "project version",
                    "This repo has its own definition, committed and shared "
                    "with everyone who works in it.", path=str(here))
            return AgentInUse(name, LOCAL_FILE, "local file in this repo",
                "This repo has a definition that is not committed, so only "
                "this machine has it.", path=str(here))

    user = _af.installed_agents_dir() / f"{name}.md"
    if user.is_symlink():
        return _classify_link(name, user, where="Your agents folder")
    if _is_file(user):
        return _classify_user_file(name, user)
    return AgentInUse(name, MISSING, "not installed",
        "No definition is installed on this machine, so Claude Code cannot "
        "use this agent here. `bash scripts/setup.sh` installs the centre agents.")


def known_names(repo: Path | None = None) -> list[str]:
    """Every agent name in the commons, the user's agents folder and the repo."""
    names: set[str] = set()
    try:
        names |= _af.commons_agent_names()
    except Exception:  # noqa: BLE001
        pass
    dirs = [_af.installed_agents_dir()]
    if repo is not None:
        dirs.insert(0, Path(repo).expanduser() / ".claude" / "agents")
    for d in dirs:
        if d.is_dir():
            names |= {p.stem for p in d.glob("*.md")}
    return sorted(names)


def which_all(repo: Path | None = None) -> list[AgentInUse]:
    """:func:`which` for every known agent, sorted by name."""
    return [which(n, repo=repo) for n in known_names(repo)]
