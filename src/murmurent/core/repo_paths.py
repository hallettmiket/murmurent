"""
Purpose: find a repository on THIS machine by name (issue #166).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-14
Input: this machine's repositories folder (core.repo.repos_root) and its
       record of where repositories are, ~/.murmurent/repo_paths.yaml
Output: a Path, or None when the repository is not on this machine

Two things made "where is repository X?" hard to answer, and both are why this
module exists:

1. **The folder was assumed.** Code wrote ``~/repos/X``. People also use
   ``~/repo`` and ``~/repositories``, and since #166 a project's repositories
   may sit together in a project folder, ``<repos>/<project>/X``.
2. **Shared records held one person's paths.** A project's list of repositories
   lives in the lab records repository, which everyone pulls. A ``path`` stored
   there is one member's folder (``/home/<them>/repos/X``), so every other
   member's lookup went into a folder they cannot read.

So the answer is found on each machine, never taken from a shared record:
first this machine's own record (written whenever murmurent adopts, clones or
moves a repository), then the repositories folder flat, then inside project
folders one level down, then any repository whose ``origin`` matches. A path
from a shared record is used only as a hint, and only when it lies under this
account's home folder.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .repo import repos_root

def _record_file() -> Path:
    """This machine's record of where repositories are: {name: path}.

    Under MURMURENT_HOME when set (the test suite isolates it), else ~/.murmurent.
    """
    return Path(os.environ.get("MURMURENT_HOME") or Path.home() / ".murmurent") / "repo_paths.yaml"


#: The placeholder a remote project leaves on this machine (core.projects).
REMOTE_POINTER = ".murmurent-remote-pointer"


def _is_git_repo(path: Path) -> bool:
    """A local copy: a git repository, or a remote project's placeholder."""
    return path.is_dir() and ((path / ".git").exists() or (path / REMOTE_POINTER).exists())


def _read_record() -> dict[str, str]:
    try:
        import yaml
        data = yaml.safe_load(_record_file().read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - no record means "nothing recorded"
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def record(name: str, path: str | Path) -> None:
    """Note that repository ``name`` is at ``path`` on this machine.

    Called by adopt, clone and ``murmurent project gather``. Best-effort: a
    failure to write leaves the search below to find the repository.
    """
    import yaml
    data = _read_record()
    data[str(name)] = str(Path(str(path)).expanduser())
    try:
        _record_file().parent.mkdir(parents=True, exist_ok=True)
        _record_file().write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def forget(name: str) -> None:
    """Drop ``name`` from this machine's record."""
    import yaml
    data = _read_record()
    if data.pop(str(name), None) is not None:
        try:
            _record_file().write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
        except OSError:
            pass


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def is_mine(path: str | Path) -> bool:
    """False when ``path`` lies in ANOTHER account's home folder.

    A path in a shared record that names someone else's home folder is never
    used: it is the problem this module exists to fix. Paths elsewhere (this
    account's home, a shared data drive) are fine.
    """
    p = Path(os.path.normpath(Path(str(path)).expanduser()))
    home = Path.home()
    if _under(p, home):
        return True
    return not _under(p, home.parent)   # a sibling of my home = someone else's home


def _origin(path: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _same_remote(a: str, b: str) -> bool:
    """Compare two git addresses, ignoring ssh/https form and a trailing .git."""
    def norm(url: str) -> str:
        u = url.strip().lower().removesuffix(".git").rstrip("/")
        u = u.replace("git@github.com:", "github.com/").replace("https://", "").replace("http://", "")
        return u.replace("ssh://git@", "")
    return bool(a and b) and norm(a) == norm(b)


def candidates(name: str) -> list[Path]:
    """Where ``name`` could sit in this machine's repositories folder."""
    root = repos_root()
    found = [root / name]
    try:
        found += [child / name for child in sorted(root.iterdir())
                  if child.is_dir() and not _is_git_repo(child)]
    except OSError:
        pass
    return found


def find(name: str, *, hint: str = "", remote_url: str = "") -> Path | None:
    """Repository ``name`` on this machine, or None.

    ``hint`` is a path from a shared record: used only if it is under this
    account's home and holds a repository. ``remote_url`` lets a repository
    cloned under another folder name still be found.
    """
    recorded = _read_record().get(str(name))
    if recorded and Path(recorded).is_dir():     # this machine's own record: trust it while the folder exists
        return Path(recorded)
    if hint and is_mine(hint) and _is_git_repo(Path(hint).expanduser()):
        return Path(hint).expanduser()
    for cand in candidates(name):
        if _is_git_repo(cand):
            return cand
    if remote_url:
        root = repos_root()
        try:
            pool = [c for c in root.iterdir() if c.is_dir()]
        except OSError:
            pool = []
        for top in pool:
            for cand in ([top] if _is_git_repo(top) else
                         [c for c in sorted(top.iterdir()) if _is_git_repo(c)] if top.is_dir() else []):
                if _same_remote(_origin(cand), remote_url):
                    return cand
    return None


def find_or_default(name: str, *, hint: str = "", remote_url: str = "") -> Path:
    """Like :func:`find`, but when the repository is not here, the place a new
    copy would go: ``<repositories folder>/<name>``. For code that needs a path
    to report or to check, not a guarantee that it exists."""
    return find(name, hint=hint, remote_url=remote_url) or repos_root() / name


# ---------------------------------------------------------------------------
# Where a NEW project's repositories go (issue #166, part 2)
# ---------------------------------------------------------------------------

#: The two layouts. Both are fully supported; nobody has to move.
FLAT, NESTED = "flat", "nested"


def project_layout() -> str:
    """``nested`` (new projects get a project folder) or ``flat``.

    Read from ``project_layout`` in this machine's machine.yaml; default
    nested. It decides only where murmurent puts a NEW project. Existing
    repositories stay where they are unless moved with `murmurent project
    gather`, and are found in either layout.
    """
    from .repo import MACHINE_SETTINGS_FILE
    try:
        import yaml
        data = yaml.safe_load(MACHINE_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - unset means the default
        return NESTED
    value = str((data or {}).get("project_layout") or "").strip().lower() if isinstance(data, dict) else ""
    return FLAT if value == FLAT else NESTED


def new_project_repo(project: str, repo_name: str | None = None) -> Path:
    """Where a new repository of ``project`` goes on this machine.

    Nested layout: ``<repositories>/<project>/<repo_name>``, so a project's
    code, manuscript and seminar repositories sit together, each keeping its
    full name (``x_y``, ``x_y_manuscript``, ``x_y_seminar``). Flat layout:
    ``<repositories>/<repo_name>``. ``repo_name`` defaults to the project name
    (the code repository).
    """
    name = repo_name or project
    if project_layout() == FLAT:
        return repos_root() / name
    return repos_root() / project / name
