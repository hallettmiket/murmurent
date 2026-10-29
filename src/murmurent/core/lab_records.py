"""
Purpose: Say whether this machine holds its group's lab records repo, and
        how to get it if not.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-27
Input: The identity card (which group), the canonical clone path
       (``repo.lab_repo_path``), and the stored member-card bundle (which
       carries the GitHub address of the records repo).
Output: :class:`RecordsStatus`, shown on the dashboard and printed by the
        terminal commands that read the records.

A group's records repo (``murmurent_lab_mgmt_<group>``) lives at exactly one
place per machine. When it is not there, nothing is invented: the person is
told the one command that puts it there.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import repo as _repo


@dataclass(frozen=True)
class RecordsStatus:
    """Where the group's records repo should be on this machine, and whether it is."""

    group: str
    path: str
    present: bool
    is_git: bool
    remote: str = ""   # git URL of the records repo on GitHub, when known
    hint: str = ""     # the command to run when ``present`` is False

    def to_dict(self) -> dict:
        return asdict(self)


def records_remote(group: str) -> str:
    """The git URL of ``group``'s records repo, or ''.

    Known from the member-card bundle this machine imported (the PI's machine
    stamps ``records_repo`` into it at issue time), else from the clone's own
    ``origin`` when the clone exists.
    """
    slug = _bundle_records_slug(group)
    if slug:
        return f"git@github.com:{slug}.git"
    try:
        from . import group_reconcile as _gr

        with _repo.use_lab_mgmt_root(_repo.lab_repo_path(group)):
            slug = _gr.lab_mgmt_repo_slug()
    except Exception:  # noqa: BLE001 - best-effort
        slug = ""
    return f"git@github.com:{slug}.git" if slug else ""


def _bundle_records_slug(group: str) -> str:
    try:
        from .issuance import cards_dir

        for p in cards_dir().glob("*_member.json"):
            bundle = json.loads(p.read_text(encoding="utf-8"))
            payload = (bundle.get("member_card") or {}).get("payload") or {}
            if str(payload.get("group") or "") == str(group):
                return str(bundle.get("records_repo") or "")
    except (OSError, ValueError):
        pass
    return ""


def records_status(group: str = "") -> RecordsStatus | None:
    """Status of ``group``'s records repo on this machine. With no ``group``,
    the owner's primary group from their card; ``None`` when there is none."""
    if not group:
        groups = _repo.owner_groups()
        if not groups:
            return None
        group = groups[0].group
    path = _repo.lab_repo_path(group)
    present = path.is_dir()
    remote = records_remote(group)
    return RecordsStatus(
        group=group, path=str(path), present=present,
        is_git=(path / ".git").exists(), remote=remote,
        hint="" if present else _repo.records_clone_hint(group, remote=remote),
    )


# ---------------------------------------------------------------------------
# The member's own view of their access. A failed clone looks the same whether
# the member was never invited, never accepted the invitation, was invited
# under another GitHub account, or is not signed in to gh. This asks GitHub,
# as the member, which one it is.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordsAccess:
    """Can this machine's GitHub account read the group's records repo?"""

    kind: str              # access | no_access | wrong_account | not_signed_in | no_gh | unknown
    slug: str              # owner/name of the records repo on GitHub ('' when unknown)
    login: str = ""        # the GitHub account gh is signed in as
    expected: str = ""     # the GitHub login this member gave at `murmurent init`
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], *, runner=None, timeout: int = 20):
    import subprocess
    runner = runner or subprocess.run
    try:
        return runner(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def records_access_probe(group: str = "", *, runner=None, which=None) -> RecordsAccess:
    """Ask GitHub, as this machine's ``gh`` login, whether it can read the
    group's records repo, and say what to do if not.

    ``runner`` and ``which`` are seams for tests (``subprocess.run`` and
    ``shutil.which`` by default). Never raises.
    """
    import shutil

    which = which or shutil.which
    if not group:
        groups = _repo.owner_groups()
        group = groups[0].group if groups else ""
    slug = _repo.github_slug(records_remote(group)) if group else ""
    try:
        from .member_profile import read_profile

        expected = str(read_profile().get("github") or "").strip().lstrip("@")
    except Exception:  # noqa: BLE001 - the profile is a convenience, not a requirement
        expected = ""
    ask = f"ask your PI to run:  murmurent group-reconcile {group} --apply"

    if which("gh") is None:
        return RecordsAccess("no_gh", slug, expected=expected,
                             detail="the GitHub command-line tool `gh` is not installed",
                             fix="brew install gh && gh auth login")
    auth = _run(["gh", "auth", "status"], runner=runner)
    if auth is None or auth.returncode != 0:
        return RecordsAccess("not_signed_in", slug, expected=expected,
                             detail="`gh` is not signed in to GitHub, so GitHub cannot "
                                    "tell who you are", fix="gh auth login")
    me = _run(["gh", "api", "user", "--jq", ".login"], runner=runner)
    login = (me.stdout or "").strip() if me is not None and me.returncode == 0 else ""
    if not slug:
        return RecordsAccess("unknown", "", login=login, expected=expected,
                             detail="the GitHub address of the lab records is not known "
                                    "on this machine (no member card carries it)",
                             fix="ask your PI for the repository name, then "
                                 "gh repo clone <owner>/murmurent_lab_mgmt_<lab>")
    look = _run(["gh", "api", f"repos/{slug}", "--jq", ".full_name"], runner=runner)
    if look is not None and look.returncode == 0:
        return RecordsAccess("access", slug, login=login, expected=expected,
                             detail=f"{login or 'your GitHub account'} can read {slug}")
    err = ((look.stderr or look.stdout) if look is not None else "").strip().splitlines()
    first = err[0][:120] if err else "GitHub refused"
    if login and expected and login.lower() != expected.lower():
        return RecordsAccess(
            "wrong_account", slug, login=login, expected=expected,
            detail=f"gh is signed in as {login}, but your murmurent profile says your "
                   f"GitHub login is {expected}; your PI invites the login on the roster",
            fix=f"either `gh auth login` as {expected}, or tell your PI your GitHub "
                f"login is {login} so the roster can be corrected, then {ask}")
    return RecordsAccess(
        "no_access", slug, login=login, expected=expected,
        detail=f"{login or 'your GitHub account'} cannot read {slug} ({first}). Either "
               f"the invitation is waiting for you, it expired unaccepted after "
               f"7 days, or you were never invited",
        fix=f"check https://github.com/{slug}/invitations and your GitHub email; "
            f"if nothing is waiting, {ask}")


__all__ = ["RecordsStatus", "RecordsAccess", "records_status", "records_remote",
           "records_access_probe"]
