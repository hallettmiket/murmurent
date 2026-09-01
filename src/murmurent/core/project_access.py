"""
Purpose: PROJECT-LEVEL access checks — issue #95 Phase 4 (also the deferred
         project-level slice of issue #63 item 2/3). For every project a viewer
         LEADS, verify that each project MEMBER can actually READ (and, for the
         append-only tree, WRITE) the project's governed data directories +
         repos on a shared server — so a human (the PI) can fix a member who was
         locked out. Composes with the existing :class:`Finding` pipeline.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-24
Input: the current lead's handle (env / user-file / gh), the cert-project
       registry (:mod:`core.cert_projects`), the lab roster
       (:mod:`core.membership`), the governed data roots (:mod:`core.lab_vm`),
       and — where present — POSIX mode + NFSv4 ACLs on the target dirs.
Output: a :class:`ProjectAccessReport` of :class:`Finding` objects
        (category :data:`AREA_PROJECT_ACCESS`), persisted as JSONL under
        ``~/.murmurent/security/local/project-access-<date>.jsonl`` (+ latest),
        so it surfaces on the same security dashboard the Tier-1 / personal
        audit findings ride.

Read-only by construction. This module only ``stat``s directories and parses
``nfs4_getfacl`` output (never runs a mutating command, never chmods). Access is
evaluated against POSIX owner/group/other mode bits refined — when an NFSv4 ACL
is available — by :func:`core.security_acl.parse_nfs4_getfacl`.

Member -> OS-user mapping
-------------------------
The roster (:class:`core.membership.MemberRecord`) has no dedicated POSIX-login
field. This module resolves a member to a shared-server OS username in this
order (see :func:`resolve_member_os_user`):

  1. an explicit ``os_user`` (or ``posix_user``) key in the member file's
     frontmatter — the authoritative override a PI can set;
  2. otherwise ``official_handle`` — the institutional netname, which on the
     shared institutional NFS servers murmurent targets IS the login name.

When neither is present the mapping is UNKNOWN and the check emits an
``unverifiable`` finding (never a false "access ok"). The gap + the netname
assumption are flagged in the issue-#95 PR body.
"""

from __future__ import annotations

import datetime as _dt
import os as _os
import stat as _stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import cert_projects as _cp
from . import identity as _identity
from . import lab_vm as _lab_vm
from . import membership as _members
from .frontmatter import parse_file as _parse_file
from .security_acl import FileAcl, parse_nfs4_getfacl
from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SCANNER,
    VERIFY_UNVERIFIABLE,
    VERIFY_VERIFIED,
    write_jsonl,
)

# ---------------------------------------------------------------------------
# Area + persistence
# ---------------------------------------------------------------------------

AREA_PROJECT_ACCESS = "project-access"

LOCAL_HOST = "local"
PERSIST_ROOT = Path.home() / ".murmurent" / "security"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(handle: str) -> str:
    return str(handle or "").strip().lstrip("@").lower()


# ---------------------------------------------------------------------------
# Access description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OsIdentity:
    """A resolved shared-server OS identity for a member: the login name, its
    numeric uid, the set of group gids it belongs to, and the set of group
    NAMES (for NFSv4 named-group ACE matching)."""

    name: str
    uid: int
    gids: frozenset[int] = frozenset()
    group_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Access:
    """Whether an identity can READ (list) and WRITE (create under) a directory,
    plus how the verdict was reached (``posix`` mode class or ``nfs4`` ACL)."""

    can_read: bool
    can_write: bool
    via: str  # "posix" | "nfs4"


# A getfacl provider maps a directory Path -> the raw ``nfs4_getfacl`` text for
# it (or None when no NFSv4 ACL is available / the tool is absent). Injectable so
# tests are deterministic and the default stays read-only.
GetfaclProvider = Callable[[Path], "str | None"]

# A member->OS-user resolver maps a bare handle -> OS login (or None when
# unknown). Injectable for tests; the default is :func:`resolve_member_os_user`.
OsUserResolver = Callable[[str], "str | None"]

# An OS-identity resolver maps an OS login -> :class:`OsIdentity` (or None when
# the login does not exist on this host). Injectable; default uses ``pwd``+``grp``.
OsIdentityResolver = Callable[[str], "OsIdentity | None"]


# ---------------------------------------------------------------------------
# Member -> OS-user mapping (see module docstring)
# ---------------------------------------------------------------------------


def _member_frontmatter_os_user(rec: "_members.MemberRecord | None") -> str | None:
    """Return an explicit ``os_user``/``posix_user`` frontmatter override, read
    straight from the member file (``MemberRecord`` drops unknown keys). None
    when the file is absent/unreadable or carries no such key."""
    if rec is None or not getattr(rec, "path", None):
        return None
    try:
        meta = _parse_file(rec.path).meta or {}
    except Exception:  # noqa: BLE001 — a malformed member file is not fatal here
        return None
    for key in ("os_user", "posix_user", "unix_user"):
        val = str(meta.get(key) or "").strip().lstrip("@")
        if val:
            return val
    return None


def resolve_member_os_user(handle: str) -> str | None:
    """Map a murmurent handle to a shared-server OS login. Order:
    explicit ``os_user`` frontmatter override, then the ``official_handle``
    (institutional netname == the shared-server login). None when neither is
    known — the caller then emits an ``unverifiable`` finding rather than a
    false clean."""
    try:
        rec = _members.get(handle)
    except Exception:  # noqa: BLE001 — MemberNotFound / bad roster
        rec = None
    override = _member_frontmatter_os_user(rec)
    if override:
        return override
    if rec is not None and getattr(rec, "official_handle", ""):
        return rec.official_handle.strip().lstrip("@")
    return None


def resolve_os_identity(os_user: str) -> OsIdentity | None:
    """Resolve an OS login to its uid + group gids/names via ``pwd``/``grp``.
    Returns None when the login does not exist on this host (so the caller emits
    an ``unverifiable`` finding). Never raises."""
    try:
        import grp
        import pwd
    except ImportError:  # non-POSIX host — cannot resolve
        return None
    try:
        pw = pwd.getpwnam(os_user)
    except (KeyError, TypeError):
        return None
    gids: set[int] = {pw.pw_gid}
    names: set[str] = set()
    try:
        primary = grp.getgrgid(pw.pw_gid)
        names.add(primary.gr_name)
    except (KeyError, OverflowError):
        pass
    try:
        for g in grp.getgrall():
            if os_user in g.gr_mem:
                gids.add(g.gr_gid)
                names.add(g.gr_name)
    except Exception:  # noqa: BLE001
        pass
    return OsIdentity(name=os_user, uid=pw.pw_uid, gids=frozenset(gids),
                      group_names=frozenset(names))


# ---------------------------------------------------------------------------
# POSIX-mode access evaluation
# ---------------------------------------------------------------------------


def posix_access(st: _os.stat_result, ident: OsIdentity) -> Access:
    """Evaluate READ (list) + WRITE (create) for ``ident`` on a directory whose
    ``stat`` is ``st``, using the standard owner/group/other class rules. A
    directory needs R+X to be listed and W+X to be written into. ``stat`` only;
    never mutates."""
    mode = st.st_mode
    if ident.uid == st.st_uid:
        r, w, x = _stat.S_IRUSR, _stat.S_IWUSR, _stat.S_IXUSR
    elif st.st_gid in ident.gids:
        r, w, x = _stat.S_IRGRP, _stat.S_IWGRP, _stat.S_IXGRP
    else:
        r, w, x = _stat.S_IROTH, _stat.S_IWOTH, _stat.S_IXOTH
    can_exec = bool(mode & x)
    can_read = bool(mode & r) and can_exec
    can_write = bool(mode & w) and can_exec
    return Access(can_read=can_read, can_write=can_write, via="posix")


# ---------------------------------------------------------------------------
# NFSv4-ACL access evaluation (refines POSIX when an ACL is present)
# ---------------------------------------------------------------------------

_READ_BITS = "r"       # read-data / list-directory
_WRITE_BITS = "wa"     # write-data / append-data (create under a dir)


def _principal_matches(ace, ident: OsIdentity, *, is_owner: bool,
                       in_owning_group: bool) -> bool:
    """Whether an NFSv4 ACE's principal applies to ``ident``. Matches the
    special principals (OWNER@/GROUP@/EVERYONE@) by role, and named user/group
    ACEs by local-part (before ``@``) against the login / group names."""
    p = ace.principal.strip()
    if p == "EVERYONE@":
        return True
    if p == "OWNER@":
        return is_owner
    if p == "GROUP@":
        return in_owning_group
    local = p.split("@", 1)[0].strip().lower()
    if ace.is_group_principal:
        return local in {g.lower() for g in ident.group_names}
    return local == ident.name.strip().lower()


def nfs4_access(file_acl: FileAcl, ident: OsIdentity, *, is_owner: bool,
                in_owning_group: bool) -> Access:
    """Evaluate READ + WRITE for ``ident`` against a single path's NFSv4 ACL.

    NFSv4 semantics: ACEs are examined in order; the first ACE that mentions a
    requested permission bit for a matching principal decides that bit
    (allow -> granted, deny -> denied). A bit never mentioned defaults to
    denied. Inherit-only ACEs (``i`` flag) do not apply to the object itself and
    are skipped."""
    def _grant(want: str) -> bool:
        for ace in file_acl.aces:
            if "i" in ace.flags:
                continue  # inherit-only — applies to children, not this object
            if not _principal_matches(ace, ident, is_owner=is_owner,
                                      in_owning_group=in_owning_group):
                continue
            if ace.has_any_perm(want):
                return ace.is_allow
        return False
    return Access(can_read=_grant(_READ_BITS), can_write=_grant(_WRITE_BITS),
                  via="nfs4")


def _acl_for_dir(text: str, path: Path) -> FileAcl | None:
    """Pick the :class:`FileAcl` for ``path`` from parsed ``nfs4_getfacl`` text.
    Matches by basename/suffix so a per-dir dump (``# file: <path>``) or a
    recursive dump both resolve. Returns None when no block matches."""
    acls = parse_nfs4_getfacl(text)
    if not acls:
        return None
    want = str(path)
    want_name = path.name
    for fa in acls:
        fp = fa.path.rstrip("/")
        if fp == want or fp.endswith("/" + want_name) or fp == want_name:
            return fa
    # Single-block dump for exactly this dir — accept it.
    return acls[0] if len(acls) == 1 else None


def evaluate_access(path: Path, ident: OsIdentity,
                    getfacl_provider: GetfaclProvider | None) -> Access:
    """Evaluate ``ident``'s access to directory ``path``. Uses the NFSv4 ACL
    (authoritative) when the provider yields one for the path, otherwise falls
    back to POSIX mode. ``stat`` only; never mutates."""
    st = path.stat()
    is_owner = ident.uid == st.st_uid
    in_owning_group = st.st_gid in ident.gids
    if getfacl_provider is not None:
        try:
            text = getfacl_provider(path)
        except Exception:  # noqa: BLE001 — a flaky getfacl must not break the scan
            text = None
        if text:
            fa = _acl_for_dir(text, path)
            if fa is not None:
                return nfs4_access(fa, ident, is_owner=is_owner,
                                   in_owning_group=in_owning_group)
    return posix_access(st, ident)


# ---------------------------------------------------------------------------
# Finding factory
# ---------------------------------------------------------------------------


def _mk(rule: str, *, severity: str, path: str, current: str, expected: str = "",
        fix: str = "", handle: str | None = None, project: str | None = None,
        notes: str = "", verify_state: str = VERIFY_VERIFIED,
        when: str = "") -> Finding:
    """Build a project-access :class:`Finding` (source=scanner, host=local)."""
    return Finding(
        severity=severity, category=AREA_PROJECT_ACCESS, rule=rule,
        host=LOCAL_HOST, path=path, current_state=current,
        expected_state=expected, suggested_fix=fix,
        detected_at=when or _iso(_now()), source=SOURCE_SCANNER,
        verify_state=verify_state,
        owner_handle=(f"@{_norm(handle)}" if handle else None),
        project=project, notes=notes,
        rule_doc_anchor="docs/security-dashboard.md#project-access",
    )


# ---------------------------------------------------------------------------
# Project data-directory enumeration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataDir:
    """One governed directory of a project + whether members need WRITE to it.
    ``immutable`` (source data) is read-only for everyone; ``append_only`` (and
    code repos) require write for members to do their work."""

    path: Path
    label: str
    needs_write: bool


def project_data_dirs(cp: _cp.CertProject, env: dict | None) -> list[DataDir]:
    """The governed directories to check for a project: its ``immutable/`` tree
    (read), its ``append_only/`` tree (read + write), and each LOCAL repo clone
    (read + write). Remote-host repos are skipped — their ACLs live on that host
    and are audited there."""
    dirs: list[DataDir] = [
        DataDir(_lab_vm.project_immutable_dir(cp.name, env),
                "immutable data", needs_write=False),
        DataDir(_lab_vm.project_append_only_dir(cp.name, env),
                "append_only data", needs_write=True),
    ]
    for r in cp.repos:
        if (r.host or "local") != "local" or not r.path:
            continue
        dirs.append(DataDir(Path(r.path).expanduser(),
                            f"repo {r.name or Path(r.path).name}",
                            needs_write=True))
    return dirs


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _projects_i_lead(handle: str, env: dict | None) -> list[_cp.CertProject]:
    """Active cert-projects where ``handle`` is the LEAD — the PI who can fix a
    member's access. This is the natural scope for a standing access check."""
    h = _norm(handle)
    return [p for p in _cp.iter_projects(env)
            if p.status == "active" and _norm(p.lead) == h]


def check_project_access(handle: str, env: dict | None = None, *,
                         projects: list[_cp.CertProject] | None = None,
                         getfacl_provider: GetfaclProvider | None = None,
                         os_user_resolver: OsUserResolver | None = None,
                         os_identity_resolver: OsIdentityResolver | None = None,
                         when: str = "") -> list[Finding]:
    """For every project ``handle`` LEADS, check each member's read (and, for
    the append-only tree + repos, write) access to the project's governed data
    directories. Emits one :class:`Finding` per (member, directory):

    - ``PROJECT-ACCESS-NO-READ-01`` / ``-NO-WRITE-01`` (warn; **block** on a
      clinical project) when a member is locked out;
    - ``PROJECT-ACCESS-OK-01`` (info) when access is correct;
    - ``PROJECT-ACCESS-UNVERIFIABLE-01`` (info, unverifiable) when the member's
      OS-user mapping or its OS identity cannot be resolved;
    - ``PROJECT-ACCESS-DIR-MISSING-01`` (info, unverifiable) when a governed
      directory does not exist on this host.

    Read-only: only ``stat`` + ``nfs4_getfacl`` parsing. Never chmods."""
    when = when or _iso(_now())
    resolve_user = os_user_resolver or resolve_member_os_user
    resolve_ident = os_identity_resolver or resolve_os_identity
    projects = projects if projects is not None else _projects_i_lead(handle, env)

    out: list[Finding] = []
    for cp in projects:
        clinical = cp.sensitivity == "clinical"
        block_sev = SEVERITY_BLOCK if clinical else SEVERITY_WARN
        dirs = project_data_dirs(cp, env)

        # Resolve each member's OS identity ONCE (an unresolved mapping is one
        # finding per member, not one per directory — keeps the report legible).
        resolved: dict[str, OsIdentity] = {}
        for m in cp.members:
            mh = _norm(m)
            if mh in resolved:
                continue
            os_user = resolve_user(mh)
            if not os_user:
                out.append(_mk("PROJECT-ACCESS-UNVERIFIABLE-01",
                               severity=SEVERITY_INFO, path=cp.name,
                               current=f"@{mh}: no OS-user mapping on the roster "
                                       "(no os_user / official_handle)",
                               expected="an os_user or official_handle so access "
                                        "can be verified",
                               fix=f"record @{mh}'s server login in their member "
                                   "file (os_user: <login>)",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE,
                               notes="Cannot confirm access without the member's "
                                     "server login — not a clean result.", when=when))
                continue
            ident = resolve_ident(os_user)
            if ident is None:
                out.append(_mk("PROJECT-ACCESS-UNVERIFIABLE-01",
                               severity=SEVERITY_INFO, path=cp.name,
                               current=f"@{mh}: OS login {os_user!r} does not exist "
                                       "on this host",
                               expected="a resolvable server account",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE,
                               notes="Run the check on the shared server where the "
                                     "member's account lives.", when=when))
                continue
            resolved[mh] = ident

        for d in dirs:
            try:
                exists = d.path.is_dir()
            except OSError:
                exists = False
            if not exists:
                out.append(_mk("PROJECT-ACCESS-DIR-MISSING-01",
                               severity=SEVERITY_INFO, path=str(d.path),
                               current=f"{d.label} directory does not exist",
                               expected="the project's governed directory is present "
                                        "on the shared server",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE,
                               notes="Run on the data host, or provision the dir.",
                               when=when))
                continue
            for mh, ident in resolved.items():
                try:
                    acc = evaluate_access(d.path, ident, getfacl_provider)
                except OSError as exc:
                    out.append(_mk("PROJECT-ACCESS-STAT-FAILED-01",
                                   severity=SEVERITY_INFO, path=str(d.path),
                                   current=f"@{mh}: could not stat {d.label}: {exc}",
                                   handle=handle, project=cp.name,
                                   verify_state=VERIFY_UNVERIFIABLE, when=when))
                    continue
                kind = "clinical " if clinical else ""
                if not acc.can_read:
                    out.append(_mk("PROJECT-ACCESS-NO-READ-01",
                                   severity=block_sev, path=str(d.path),
                                   current=f"@{mh} ({ident.name}) cannot READ the "
                                           f"project's {d.label}",
                                   expected="every project member can read the "
                                            "project's data",
                                   fix=f"PI: grant @{mh} read on {d.path} "
                                       "(fix group/ACL membership)",
                                   handle=handle, project=cp.name,
                                   notes=(f"{kind}project — a locked-out member "
                                          "blocks their work; PI must fix." if clinical
                                          else "PI must fix the member's access."),
                                   when=when))
                    continue
                if d.needs_write and not acc.can_write:
                    out.append(_mk("PROJECT-ACCESS-NO-WRITE-01",
                                   severity=block_sev, path=str(d.path),
                                   current=f"@{mh} ({ident.name}) can read but cannot "
                                           f"WRITE the project's {d.label}",
                                   expected="members can write the append-only tree "
                                            "and their repos",
                                   fix=f"PI: grant @{mh} write on {d.path}",
                                   handle=handle, project=cp.name,
                                   notes=(f"{kind}project." if clinical else
                                          "PI must fix the member's access."),
                                   when=when))
                    continue
                out.append(_mk("PROJECT-ACCESS-OK-01",
                               severity=SEVERITY_INFO, path=str(d.path),
                               current=f"@{mh} ({ident.name}) has correct access to "
                                       f"the project's {d.label} (via {acc.via})",
                               expected="ok", handle=handle, project=cp.name,
                               when=when))
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class ProjectAccessReport:
    """The result of one project-access check: a flat list of :class:`Finding`
    (all category :data:`AREA_PROJECT_ACCESS`) + the metadata to render/persist."""

    handle: str
    generated_at: str
    findings: list[Finding] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = {"ok": 0, "concern": 0, "block": 0, "unverifiable": 0}
        for f in self.findings:
            if f.verify_state == VERIFY_UNVERIFIABLE:
                c["unverifiable"] += 1
            elif f.severity == SEVERITY_BLOCK:
                c["block"] += 1
            elif f.severity == SEVERITY_WARN:
                c["concern"] += 1
            else:
                c["ok"] += 1
        return c

    def headline(self) -> str:
        c = self.counts()
        if c["block"]:
            verb = f"BLOCKED — {c['block']} member(s) locked out of project data"
        elif c["concern"]:
            verb = f"Concerns — {c['concern']} member/dir access issue(s)"
        else:
            verb = "Clear — all project members can reach their data"
        tail = f"; {c['unverifiable']} could-not-verify" if c["unverifiable"] else ""
        return f"{verb} for projects @{self.handle} leads{tail}."[:200]

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "generated_at": self.generated_at,
            "counts": self.counts(),
            "headline": self.headline(),
            "findings": [f.to_dict() for f in self.findings],
        }


def run_project_access_check(handle: str | None = None,
                             env: dict | None = None, *,
                             getfacl_provider: GetfaclProvider | None = None,
                             ) -> ProjectAccessReport:
    """Run the project-level access check for the projects ``handle`` LEADS and
    return a :class:`ProjectAccessReport`. ``handle`` defaults to the resolved
    current member. Read-only; missing prerequisites become ``unverifiable``
    findings so the report never silently lies."""
    when = _iso(_now())
    if handle:
        resolved = _norm(handle)
    else:
        ident = _identity.resolve(allow_unknown=True)
        resolved = "" if ident.source == "unknown" else _norm(ident.handle)

    if not resolved:
        f = _mk("PROJECT-ACCESS-NO-HANDLE-01", severity=SEVERITY_INFO,
                path="(identity)",
                current="could not resolve your murmurent handle",
                expected="set $MURMURENT_USER or run `gh auth login`",
                verify_state=VERIFY_UNVERIFIABLE, when=when,
                notes="Skipped the project-access check (need a lead handle).")
        return ProjectAccessReport(handle="unknown", generated_at=when,
                                   findings=[f])

    findings = check_project_access(resolved, env,
                                    getfacl_provider=getfacl_provider, when=when)
    return ProjectAccessReport(handle=resolved, generated_at=when,
                               findings=findings)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def persist(report: ProjectAccessReport) -> Path:
    """Write the report as JSONL under
    ``~/.murmurent/security/local/project-access-<date>.jsonl`` and refresh the
    ``project-access-latest.jsonl`` symlink so the security dashboard surfaces
    it alongside the personal audit + Tier-1 findings. Returns the dated path."""
    out_dir = PERSIST_ROOT / LOCAL_HOST
    out_dir.mkdir(parents=True, exist_ok=True)
    date = report.generated_at[:10]
    target = out_dir / f"project-access-{date}.jsonl"
    write_jsonl(target, report.findings)
    latest = out_dir / "project-access-latest.jsonl"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(target.name)
    except OSError:
        pass
    return target


def run_and_persist(handle: str | None = None, env: dict | None = None, *,
                    getfacl_provider: GetfaclProvider | None = None,
                    ) -> tuple[ProjectAccessReport, Path]:
    """Convenience: run the project-access check + persist it. Returns
    ``(report, path)``."""
    report = run_project_access_check(handle=handle, env=env,
                                      getfacl_provider=getfacl_provider)
    path = persist(report)
    return report, path


__all__ = [
    "AREA_PROJECT_ACCESS", "LOCAL_HOST",
    "OsIdentity", "Access", "DataDir",
    "GetfaclProvider", "OsUserResolver", "OsIdentityResolver",
    "resolve_member_os_user", "resolve_os_identity",
    "posix_access", "nfs4_access", "evaluate_access",
    "project_data_dirs", "check_project_access",
    "ProjectAccessReport", "run_project_access_check",
    "persist", "run_and_persist",
]
