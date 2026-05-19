"""
Purpose: NFSv4 ACL parser + template diff for the wigamig Tier-2 audit.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: Output of ``nfs4_getfacl -R <path>`` (a stream of per-file ACL
       blocks).
Output: ``[Ace]`` per path + ``[Finding]`` from diffing against the
        expected templates documented in ``docs/security-dashboard.md``
        (compiled from Dr. Core Lead's NFSv4 reference).

ACE format (one line of ``nfs4_getfacl`` output)::

    A:fdg:Users@example.edu:rxtncy
    D:fdi:OWNER@:Dd
    A::OWNER@:rwaDdxtTnNcCoy

Field layout: ``<type>:<flags>:<principal>:<perms>``. Flags may be
empty (``A::OWNER@:...``). ``type`` is ``A`` (allow) or ``D`` (deny).
``perms`` is a string from the alphabet ``rwaDdxtTnNcCoy``.

This module is pure-parsing: it never executes a command or writes
under ``/data/lab_vm/raw|refined``. It only emits :class:`Finding`
rows the dashboard surfaces.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SNAPSHOT,
    TIER_2,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ace:
    """One Access Control Entry on a file or directory.

    Order in the on-disk ACL matters (first ACE that mentions a bit
    wins). The parser preserves order; downstream consumers iterate.
    """

    type: str            # "A" or "D"
    flags: str           # "" / "f" / "fd" / "fdi" / "fdg" / "dg" / ...
    principal: str       # "OWNER@" | "GROUP@" | "EVERYONE@" | "<user>@<domain>" | "<group>@<domain>"
    perms: str           # alphabet rwaDdxtTnNcCoy

    @property
    def is_allow(self) -> bool:
        return self.type == "A"

    @property
    def is_deny(self) -> bool:
        return self.type == "D"

    @property
    def has_file_inherit(self) -> bool:
        return "f" in self.flags

    @property
    def has_dir_inherit(self) -> bool:
        return "d" in self.flags

    @property
    def has_inherit_only(self) -> bool:
        return "i" in self.flags

    @property
    def is_group_principal(self) -> bool:
        # nfs4_getfacl marks group principals with the ``g`` flag.
        return "g" in self.flags

    def has_any_perm(self, perms: str) -> bool:
        """True iff this ACE grants/denies ANY of the chars in ``perms``."""
        return any(p in self.perms for p in perms)

    def to_text(self) -> str:
        return f"{self.type}:{self.flags}:{self.principal}:{self.perms}"


@dataclass
class FileAcl:
    """All ACEs that apply to a single path, in declared order."""

    path: str
    aces: list[Ace] = field(default_factory=list)

    def find(self, *, type_: str | None = None,
             principal: str | None = None,
             flags_contain: str | None = None) -> list[Ace]:
        out = []
        for a in self.aces:
            if type_ is not None and a.type != type_:
                continue
            if principal is not None and a.principal != principal:
                continue
            if flags_contain is not None and any(
                f not in a.flags for f in flags_contain
            ):
                continue
            out.append(a)
        return out


# Regex for one ACE line. Tolerates spaces around the colons (which
# ``nfs4_getfacl`` sometimes inserts when aligning columns).
_ACE_LINE = re.compile(
    r"^\s*([AD])\s*:\s*([fdingS]*)\s*:\s*([^:]+?)\s*:\s*([rwaDdxtTnNcCoy]*)\s*$"
)
_FILE_HEADER = re.compile(r"^\s*#\s*file:\s*(.+?)\s*$")


def parse_nfs4_getfacl(text: str) -> list[FileAcl]:
    """Parse the output of ``nfs4_getfacl -R <root>`` into FileAcl rows.

    Tolerant of:
      - Blank lines between blocks.
      - Comment lines other than ``# file:`` (silently skipped).
      - Trailing whitespace inside fields.

    Skips malformed ACE lines without aborting — a corrupt single line
    shouldn't lose the whole dump.
    """
    out: list[FileAcl] = []
    current: FileAcl | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m_file = _FILE_HEADER.match(line)
        if m_file:
            if current is not None:
                out.append(current)
            current = FileAcl(path=m_file.group(1))
            continue
        if line.lstrip().startswith("#"):
            # Other metadata comments (e.g. ``# owner: ...``) — skip.
            continue
        m_ace = _ACE_LINE.match(line)
        if not m_ace:
            continue
        if current is None:
            # ACE before any ``# file:`` header — defensive: synthesise
            # an unknown-path block so we don't drop the entry silently.
            current = FileAcl(path="<unknown>")
        current.aces.append(Ace(
            type=m_ace.group(1),
            flags=m_ace.group(2),
            principal=m_ace.group(3).strip(),
            perms=m_ace.group(4),
        ))
    if current is not None:
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# Template diff — emits Finding rows from observed FileAcl
# ---------------------------------------------------------------------------

# Permission alphabet that an OWNER@/GROUP@ allow ACE may carry on a
# **file under raw/**. The Core Lead reference shows files are born with
# ``A:fi:OWNER@:rxtTcy`` and ``A:fi:GROUP@:rxtTcy`` — read-only-ish.
# Anything more than this set is drift.
_RAW_FILE_ALLOWED_PERMS = set("rxtTcy")

# Permission characters that, if present in an allow ACE on a raw file,
# constitute a writability defect (block).
_RAW_FILE_FORBIDDEN_WRITE = set("waDC")  # write, append, delete-self,
                                          # delete-child, write-ACL

# Expected inherited-Deny on raw/ root: ``D:fdi:OWNER@:Dd`` AND
# ``D:fdi:GROUP@:Dd``. Both must be present.
_RAW_DENY_EXPECTED = {
    ("OWNER@", "fdi", "Dd"),
    ("GROUP@", "fdi", "Dd"),
}

# Expected refined/ root allow ACEs (presence required; perm-set checked
# by membership rather than equality so the dashboard tolerates minor
# vendor-side reordering of letters in ``perms``).
_REFINED_REQUIRED_ALLOW = (
    # (principal-suffix-or-name, flags-must-contain, perms-must-contain)
    ("OWNER@", "", "rwaD"),
    ("GROUP@", "", "rwaD"),
    ("Administrators@example.edu", "fdg", "rwaDd"),
    ("Users@example.edu", "fdg", "r"),     # UWO read access (inherited)
)

# Refined-exception template (the bc_dcis pattern): GROUP@ stripped to
# metadata-only. Detected, not flagged as drift — emitted info-finding
# for the PI to vet.
_EXCEPTION_GROUP_PERMS_MAX = set("tcy")  # GROUP@ ≤ metadata-only


def diff_raw(acls: list[FileAcl], *, host: str,
             lab_vm_root: str = "/data/lab_vm",
             now_iso: str | None = None) -> list[Finding]:
    """Diff the observed ``raw/`` ACLs against the immutability template.

    Emits:

    - ``RAW-DENY-DELETE-MISSING-01`` (block) when a directory under raw/
      lacks the inherited Deny-delete ACEs.
    - ``RAW-FILE-WRITABLE-01`` (block) when a file under raw/ has an
      OWNER@/GROUP@ allow ACE granting any forbidden write/delete bit.
    - ``RAW-UNEXPECTED-PRINCIPAL-01`` (info) when an ACE names a
      principal that isn't on the standard allowlist.

    ``acls`` is the parsed output of ``nfs4_getfacl -R <v4>/lab_vm/raw``.
    """
    now_iso = now_iso or _dt.datetime.utcnow().isoformat() + "Z"
    findings: list[Finding] = []
    raw_root_prefix = "lab_vm/raw"  # match suffix; the snapshot rewrites
                                     # /srv/acl-view/lab_vm/raw -> .../lab_vm/raw
    for fa in acls:
        # Determine if this is a directory or a file. ``nfs4_getfacl``
        # doesn't tag the kind; we use the rule "dir = has ``d`` or
        # ``fdi`` inheritance flags on any ACE" as a proxy. Imperfect
        # but matches Core Lead's templates which only put inheritance
        # flags on dir ACEs.
        is_dir = any(("d" in a.flags or "fd" in a.flags or "fdi" in a.flags)
                     for a in fa.aces)
        project = _extract_project(fa.path, "raw")
        if is_dir:
            # RAW-DENY-DELETE-MISSING-01 — both OWNER@ and GROUP@ inherited
            # Deny-delete required.
            present = {
                (a.principal, "fdi" if "fdi" in a.flags else a.flags, a.perms)
                for a in fa.aces if a.is_deny
            }
            for principal in ("OWNER@", "GROUP@"):
                ok = any(
                    a.is_deny and a.principal == principal
                    and "fdi" in a.flags
                    and "D" in a.perms and "d" in a.perms
                    for a in fa.aces
                )
                if not ok:
                    findings.append(_finding(
                        rule="RAW-DENY-DELETE-MISSING-01",
                        severity=SEVERITY_BLOCK,
                        path=_map_to_v3(fa.path, lab_vm_root),
                        host=host,
                        current=f"no D:fdi:{principal}:Dd on {fa.path}",
                        expected="Deny inherited (Dd) for OWNER@ and GROUP@",
                        fix=(f"sudo nfs4_setfacl -a 'D:fdi:{principal}:Dd' "
                             f"/srv/acl-view/lab_vm/raw/...    "
                             "# review template in docs/security-dashboard.md first"),
                        project=project,
                        now_iso=now_iso,
                        category="raw",
                    ))
        else:
            # File. Any OWNER@/GROUP@ allow ACE granting w/a/D/C is a defect.
            for a in fa.aces:
                if not a.is_allow:
                    continue
                if a.principal not in ("OWNER@", "GROUP@"):
                    continue
                offending = set(a.perms) & _RAW_FILE_FORBIDDEN_WRITE
                if offending:
                    findings.append(_finding(
                        rule="RAW-FILE-WRITABLE-01",
                        severity=SEVERITY_BLOCK,
                        path=_map_to_v3(fa.path, lab_vm_root),
                        host=host,
                        current=f"{a.to_text()} (forbidden bits: {''.join(sorted(offending))})",
                        expected=f"{a.principal} ACE perms subset of '{''.join(sorted(_RAW_FILE_ALLOWED_PERMS))}'",
                        fix=("review file; raw/ files should have only "
                             "OWNER@/GROUP@ rxtTcy via inherited fi ACEs"),
                        project=project,
                        now_iso=now_iso,
                        category="raw",
                    ))
        # Unexpected principal (any ACE that names a user/group other
        # than OWNER@/GROUP@/EVERYONE@/Administrators@/helpdesk).
        for a in fa.aces:
            if a.principal in ("OWNER@", "GROUP@", "EVERYONE@"):
                continue
            if a.principal.startswith("Administrators@") \
               or a.principal.startswith("labgroup@") \
               or a.principal.startswith("Users@"):
                continue
            findings.append(_finding(
                rule="RAW-UNEXPECTED-PRINCIPAL-01",
                severity=SEVERITY_INFO,
                path=_map_to_v3(fa.path, lab_vm_root),
                host=host,
                current=f"named ACE: {a.to_text()}",
                expected="standard principal allowlist (OWNER@, GROUP@, helpdesk, Admins, Users@example.edu)",
                fix="vet whether the named principal is intentional",
                project=project,
                now_iso=now_iso,
                category="raw",
            ))
    return findings


def diff_refined(acls: list[FileAcl], *, host: str,
                  lab_vm_root: str = "/data/lab_vm",
                  now_iso: str | None = None) -> list[Finding]:
    """Diff the observed ``refined/`` ACLs.

    Emits:

    - ``REFINED-PATTERN-DRIFT-01`` (warn) on the refined/ root if any
      of the required-allow ACEs (OWNER+GROUP full, Admins inherited,
      UWO Users inherited read) is absent.
    - ``REFINED-EXCEPTION-DETECTED-01`` (info) on any directory whose
      GROUP@ allow ACE is metadata-only (``tcy`` or subset). Surfaced
      for the PI to vet — like the bc_dcis pattern, this MAY be
      intentional. Per the user's preference, we do not auto-classify;
      we just flag and let the PI sort it.
    - ``ACL-UNEXPECTED-PRINCIPAL-01`` (info) as for raw/.
    """
    now_iso = now_iso or _dt.datetime.utcnow().isoformat() + "Z"
    findings: list[Finding] = []
    refined_root_suffix = "lab_vm/refined"
    for fa in acls:
        is_root = fa.path.rstrip("/").endswith(refined_root_suffix)
        project = _extract_project(fa.path, "refined")
        if is_root:
            missing = []
            for principal_match, flag_req, perm_req in _REFINED_REQUIRED_ALLOW:
                ok = any(
                    a.is_allow
                    and (a.principal == principal_match
                         or a.principal.endswith(principal_match))
                    and all(f in a.flags for f in flag_req)
                    and all(p in a.perms for p in perm_req)
                    for a in fa.aces
                )
                if not ok:
                    missing.append(f"{principal_match}/{flag_req}/{perm_req}")
            if missing:
                findings.append(_finding(
                    rule="REFINED-PATTERN-DRIFT-01",
                    severity=SEVERITY_WARN,
                    path=_map_to_v3(fa.path, lab_vm_root),
                    host=host,
                    current=f"missing required ACEs: {', '.join(missing)}",
                    expected="OWNER+GROUP+Admins full; Users@example.edu rxtncy + way",
                    fix="see expected templates in docs/security-dashboard.md",
                    project=project,
                    now_iso=now_iso,
                    category="refined",
                ))
        # Exception pattern: GROUP@ ACE on a subdir is metadata-only.
        # We only check non-root paths so the root's collaborative
        # GROUP@:rwaDxtTnNcy doesn't get flagged.
        if not is_root:
            for a in fa.aces:
                if a.principal != "GROUP@" or not a.is_allow:
                    continue
                if set(a.perms).issubset(_EXCEPTION_GROUP_PERMS_MAX):
                    findings.append(_finding(
                        rule="REFINED-EXCEPTION-DETECTED-01",
                        severity=SEVERITY_INFO,
                        path=_map_to_v3(fa.path, lab_vm_root),
                        host=host,
                        current=f"GROUP@ ACE is metadata-only ({a.perms}); subdir locked down",
                        expected="(none — exception patterns are intentional)",
                        fix="confirm this restriction is intentional (PI vet)",
                        project=project,
                        now_iso=now_iso,
                        category="refined",
                    ))
                    break
        for a in fa.aces:
            if a.principal in ("OWNER@", "GROUP@", "EVERYONE@"):
                continue
            if (a.principal.startswith("Administrators@")
                or a.principal.startswith("labgroup@")
                or a.principal.startswith("Users@")):
                continue
            findings.append(_finding(
                rule="ACL-UNEXPECTED-PRINCIPAL-01",
                severity=SEVERITY_INFO,
                path=_map_to_v3(fa.path, lab_vm_root),
                host=host,
                current=f"named ACE: {a.to_text()}",
                expected="standard principal allowlist",
                fix="vet whether the named principal is intentional",
                project=project,
                now_iso=now_iso,
                category="refined",
            ))
    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(*, rule: str, severity: str, path: str, host: str,
              current: str, expected: str, fix: str, project: str | None,
              now_iso: str, category: str) -> Finding:
    return Finding(
        severity=severity,
        category=category,
        rule=rule,
        host=host,
        path=path,
        current_state=current,
        expected_state=expected,
        suggested_fix=fix,
        detected_at=now_iso,
        source=SOURCE_SNAPSHOT,
        tier=TIER_2,
        owner_handle=None,
        project=project,
        rule_doc_anchor=f"docs/security-dashboard.md#{rule}",
        notes="",
    )


def _extract_project(path: str, kind: str) -> str | None:
    """Extract the project name from ``.../lab_vm/<kind>/<project>/...``.

    Returns None for the kind-root itself (``.../lab_vm/raw``).
    """
    marker = f"/lab_vm/{kind}/"
    if marker not in path:
        return None
    tail = path.split(marker, 1)[1].strip("/")
    if not tail:
        return None
    return tail.split("/", 1)[0]


def _map_to_v3(path: str, lab_vm_root: str) -> str:
    """Rewrite ``/srv/acl-view/lab_vm/...`` -> ``<lab_vm_root>/...`` so
    the dashboard's suggested-fix text references paths the PI sees
    on the v3 mount."""
    v4 = "/srv/acl-view/lab_vm/"
    if path.startswith(v4):
        rel = path[len(v4):]
        return f"{lab_vm_root.rstrip('/')}/{rel}"
    return path


__all__ = [
    "Ace", "FileAcl",
    "parse_nfs4_getfacl",
    "diff_raw", "diff_refined",
]
