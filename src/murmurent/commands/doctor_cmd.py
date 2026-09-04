"""
Purpose: ``murmurent doctor``: check the local install and say, for each thing
         that is wrong, the one command that puts it right.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-04
Input: the running interpreter, the commons (core.commons), ``~/.claude/``
Output: one line per check; exit 0 when nothing failed, 1 otherwise

Why this exists. Every one of these checks corresponds to a way an install has
actually gone wrong for a real person, and every one of them was silent at the
time:

* ``pip install -e .`` run from a shell whose ``pip`` belonged to an OLDER Python
  than the one murmurent runs under. pip refused with "requires a different
  Python", which reads as a murmurent defect and is really a PATH one.
* a development clone whose ``origin`` was still the release repository after
  the two were split. ``git pull`` then fails with unrelated histories.
* symlinks in ``~/.claude/agents/`` pointing at an agent that has since left
  the commons, so Claude Code loads a broken link every session.
* hooks in ``settings.json`` still pinned to an interpreter that was removed or
  replaced, so no hook fires and nothing says so.

Each check is a small function returning a :class:`Check`; the command prints
them and never raises, because a doctor that crashes on the second check tells
you nothing about the third.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from .. import __version__
from ..core.commons import commons_root, commons_source, packaged_commons_root

OK = "ok"
WARN = "warn"
FAIL = "fail"

_ICON = {OK: "✓", WARN: "!", FAIL: "✗"}

#: The release repository carries one commit per release. A clone with far more
#: history than that is a development clone, whatever its remote says.
RELEASE_HISTORY_MAX = 50

#: The remote a clone with full history should be pulling from.
DEV_REMOTE = "git@github.com:hallettmiket/murmurent_dev.git"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _cc_dir() -> Path:
    override = os.environ.get("MURMURENT_CC_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def _clone_hint(root: Path) -> str:
    """The reinstall command for THIS install, with the right interpreter."""
    return f"uv tool install --python 3.12 --reinstall -e {root}"


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def check_python() -> Check:
    v = sys.version_info
    detail = f"Python {v.major}.{v.minor}.{v.micro} at {sys.executable}"
    if (v.major, v.minor) >= (3, 12):
        return Check("python", OK, detail)
    return Check(
        "python", FAIL, detail,
        "murmurent needs Python 3.12 or newer; reinstall with "
        f"{_clone_hint(commons_root())}",
    )


def _same_install(a: str | None, b: str) -> bool:
    if not a:
        return True
    try:
        return Path(a).resolve().parent == Path(b).resolve().parent
    except OSError:
        return True


def check_path_tools() -> Check:
    """``pip`` and ``python`` on PATH belong to the interpreter running murmurent.

    When they belong to another interpreter, ``pip install -e .`` installs into
    the wrong Python, or refuses because that Python is too old, and the person
    reads either as murmurent being broken.
    """
    if "uv/tools" in sys.executable.replace("\\", "/") or "uv/tools" in sys.prefix.replace("\\", "/"):
        return Check("path", OK, "installed by uv, which manages its own interpreter; "
                                 "upgrade with `uv tool upgrade murmurent`")
    strangers: list[str] = []
    for tool in ("pip", "python", "python3"):
        found = shutil.which(tool)
        if found and not _same_install(found, sys.executable):
            strangers.append(f"{tool} -> {found}")
    if not strangers:
        return Check("path", OK, "pip and python on PATH match the murmurent interpreter")
    return Check(
        "path", WARN,
        "PATH has another Python first: " + "; ".join(strangers),
        "reinstall or upgrade with uv, which picks its own interpreter: "
        f"{_clone_hint(commons_root())}. A bare `pip install` would go to the "
        "wrong Python.",
    )


def check_version() -> Check:
    root = commons_root()
    return Check("version", OK, f"murmurent {__version__}, commons from the {commons_source()} at {root}")


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_clone_remote() -> Check:
    """A clone with development history should pull from the development remote.

    The release repository is rewritten at every release, so a development clone
    that still points at it can never ``git pull`` again. The two are told apart
    by history depth, since a release history is a handful of commits.
    """
    root = commons_root()
    if not (root / ".git").exists():
        return Check("clone", OK, "installed from the package; no clone to check")
    origin = _git(root, "remote", "get-url", "origin") or ""
    count_s = _git(root, "rev-list", "--count", "HEAD")
    head = _git(root, "rev-parse", "--short", "HEAD") or "?"
    try:
        count = int(count_s or 0)
    except ValueError:
        count = 0
    detail = f"{root} at {head}, {count} commits, origin {origin or '(none)'}"
    is_release_remote = origin.rstrip("/").removesuffix(".git").endswith("hallettmiket/murmurent")
    if is_release_remote and count > RELEASE_HISTORY_MAX:
        return Check(
            "clone", WARN, detail,
            "this is a development clone pointed at the release repository, so "
            "`git pull` will fail. Run: git -C "
            f"{root} remote set-url origin {DEV_REMOTE}",
        )
    return Check("clone", OK, detail)


def _links(dest_dir: Path, root: Path) -> tuple[int, list[str], int]:
    """(links into the commons, dangling names, other entries)."""
    into = 0
    dangling: list[str] = []
    other = 0
    if not dest_dir.is_dir():
        return (0, [], 0)
    root_s = str(root.resolve())
    for p in sorted(dest_dir.iterdir()):
        if not p.is_symlink():
            other += 1
            continue
        target = os.readlink(p)
        try:
            in_commons = str(Path(target).resolve()).startswith(root_s) or target.startswith(str(root))
        except OSError:
            in_commons = target.startswith(str(root))
        if not p.exists():
            if in_commons:
                dangling.append(p.name)
            else:
                other += 1
        elif in_commons:
            into += 1
        else:
            other += 1
    return (into, dangling, other)


def check_links() -> list[Check]:
    root = commons_root()
    cc = _cc_dir()
    out: list[Check] = []
    for sub, pattern in (("agents", "*.md"), ("rules", "*.md"), ("skills", "*")):
        src = root / sub
        wanted = {p.name for p in src.glob(pattern) if (p.is_file() if sub != "skills" else p.is_dir())}
        if sub == "rules" and (src / "local").is_dir():
            wanted |= {p.name for p in (src / "local").glob("*.md")}
        into, dangling, other = _links(cc / sub, root)
        linked = {p.name for p in (cc / sub).iterdir()} if (cc / sub).is_dir() else set()
        missing = sorted(wanted - linked)
        detail = f"{into} linked into the commons, {len(wanted)} available, {other} of your own"
        if into == 0 and wanted:
            out.append(Check(sub, FAIL, detail, "run: murmurent install"))
            continue
        if dangling:
            out.append(Check(
                sub, WARN, detail + f"; dangling: {', '.join(dangling)}",
                "these point at files that left the commons. Run: murmurent setup",
            ))
        elif missing:
            out.append(Check(
                sub, WARN, detail + f"; unlinked: {', '.join(missing)}",
                "run: murmurent setup",
            ))
        else:
            out.append(Check(sub, OK, detail))
    return out


def _hook_interpreters(settings: dict) -> set[str]:
    found: set[str] = set()
    for groups in (settings.get("hooks") or {}).values():
        for grp in groups or []:
            for h in grp.get("hooks") or []:
                cmd = str(h.get("command") or "")
                if "murmurent.hooks" not in cmd:
                    continue
                first = cmd.split()[0] if cmd.split() else ""
                if first and "=" not in first:
                    found.add(first)
    return found


def check_hooks() -> Check:
    settings_path = _cc_dir() / "settings.json"
    if not settings_path.is_file():
        return Check("hooks", FAIL, f"{settings_path} is missing", "run: murmurent install --hooks")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        return Check("hooks", FAIL, f"{settings_path} could not be parsed: {exc}",
                     "fix the JSON, then run: murmurent install --hooks")
    interpreters = _hook_interpreters(settings)
    if not interpreters:
        return Check("hooks", FAIL, "no murmurent hooks registered in settings.json",
                     "run: murmurent install --hooks")
    gone = sorted(i for i in interpreters if not Path(i).exists())
    if gone:
        return Check(
            "hooks", FAIL,
            f"hooks call an interpreter that no longer exists: {', '.join(gone)}",
            "run: murmurent install --hooks",
        )
    stale = sorted(i for i in interpreters if not _same_install(i, sys.executable))
    if stale:
        return Check(
            "hooks", WARN,
            f"hooks run under {', '.join(stale)}, murmurent runs under {sys.executable}",
            "run: murmurent install --hooks   (re-pins the hooks to this interpreter)",
        )
    n_mcp = sum(1 for k in (settings.get("mcpServers") or {}) if str(k).startswith("murmurent"))
    return Check("hooks", OK, f"{len(interpreters)} interpreter, {n_mcp} murmurent MCP servers registered")


def check_packaged_commons() -> Check:
    """Only meaningful for a package install; a clone always wins."""
    if commons_source() != "package":
        return Check("package", OK, "reading the commons from a clone; the packaged copy is unused")
    pk = packaged_commons_root()
    n = len(list((pk / "agents").glob("*.md"))) if (pk / "agents").is_dir() else 0
    if n:
        return Check("package", OK, f"packaged commons has {n} agents")
    return Check("package", FAIL, f"packaged commons at {pk} has no agents",
                 "reinstall: uv tool install --reinstall murmurent")


def run_checks() -> list[Check]:
    checks: list[Check] = [check_python(), check_path_tools(), check_version(), check_clone_remote()]
    checks.extend(check_links())
    checks.append(check_hooks())
    checks.append(check_packaged_commons())
    return checks


def cmd_doctor() -> int:
    checks = run_checks()
    for c in checks:
        click.echo(f"  {_ICON[c.status]} {c.name}: {c.detail}")
        if c.fix and c.status != OK:
            click.echo(f"      fix: {c.fix}")
    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    click.echo()
    if fails == 0 and warns == 0:
        click.echo("All checks passed.")
        return 0
    if fails == 0:
        click.echo(f"{warns} warning(s); nothing is broken, the fixes above keep it that way.")
        return 0
    click.echo(f"{fails} problem(s), {warns} warning(s). Run the fixes above, then `murmurent doctor` again.")
    return 1
