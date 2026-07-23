"""
Purpose: the LOCAL, member-initiated **personal security audit** — issue #63
         Phase 1. Aggregates existing drift-reconcilers + scanners into one
         on-demand report of the calling member's own security posture, with
         NO SSH and NO write actions (every reconciler runs ``apply=False``;
         ACL checks ``stat`` only).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-23
Input: the current member handle (env ``MURMURENT_USER`` / ``~/.murmurent/user``
       / ``gh``), the cert-project registry, the local repo inventory, and the
       personal vault path — all read-only.
Output: a :class:`PersonalAuditReport` of :class:`Finding` objects grouped by
        area, persisted as JSONL under
        ``~/.murmurent/security/local/personal-<date>.jsonl`` (+ ``latest``).

Design (from the maintainer's locked decisions on issue #63):
  1. One ``Finding`` pipeline + the new ``verify_state`` field — so a missing
     prerequisite (no ``gh``, no Slack token, no handle) yields an explicit
     ``verify_state="unverifiable"`` finding rather than a false "in sync" or a
     false "everyone is missing". The report never silently lies.
  3. Phase-1 scope = aggregate EXISTING checks behind one button: item 1
     (GitHub perms), 2i (local repo + vault ACLs), 4 (Slack membership), 6
     (non-MM repos), 7-member (own cert validity), and item V clinical
     containment. New content scanners (2ii-iv), machine posture (5), and
     project-CARD expiry across other members are Phase 2/3 — NOT here.

Clinical-repo rule: a repo is clinical if its linked cert-project has
``sensitivity == "clinical"`` (matched by ``github_repo`` and/or a repo path in
``repos``), OR its ``.murmurent.yaml`` declares ``sensitivity: clinical``. For a
clinical repo and for the personal vault, an over-share ACL finding escalates
from ``warn`` to ``block``.

Read-only by construction. This module never mutates GitHub, Slack, or the
filesystem; it only reports.
"""

from __future__ import annotations

import datetime as _dt
import os
import re as _re
import stat as _stat
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_forks as _af
from . import cert_projects as _cp
from . import cert_provision as _cprov
from . import group_reconcile as _gr
from . import identity as _identity
from . import lab_vm as _lab_vm
from . import project_provision as _pp
from . import repo as _repo
from . import repo_content_scan as _rcs
from . import repo_inventory as _inv
from .frontmatter import parse_text as _parse_fm
from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SCANNER,
    VERIFY_UNVERIFIABLE,
    VERIFY_VERIFIED,
    rollup_by_directory,
    write_jsonl,
)

# ---------------------------------------------------------------------------
# Areas + persistence
# ---------------------------------------------------------------------------

AREA_GITHUB = "github"
AREA_SLACK = "slack"
AREA_CERT = "cert"
AREA_REPOS = "repos"
AREA_VAULT = "vault"
AREA_NON_MM = "non-mm"
AREA_AGENTS = "agents"
# Phase 2 content scanners (issue #63 items 2ii-2iv), defined in
# ``repo_content_scan`` and re-exported here so ``ALL_AREAS`` stays the single
# source of truth the CLI + dashboard iterate.
AREA_OUTPUT = _rcs.AREA_OUTPUT      # 2(ii) output-location
AREA_NETWORK = _rcs.AREA_NETWORK    # 2(iii) network safety
AREA_EGRESS = _rcs.AREA_EGRESS      # 2(iv) data-shipping / external APIs
# Secret detection (issue #63 Phase 2 follow-up): tracked-file CONTENT +
# bounded git-history walk (via ``core.secret_scan``) + GitHub secret-scanning
# alerts per project repo. Redacted by construction — no raw secret ever lands
# in a Finding.
AREA_SECRETS = "secrets"
ALL_AREAS = (AREA_GITHUB, AREA_SLACK, AREA_CERT, AREA_REPOS, AREA_VAULT,
             AREA_NON_MM, AREA_AGENTS, AREA_OUTPUT, AREA_NETWORK, AREA_EGRESS,
             AREA_SECRETS)

# Secret-scan bounds for the audit path — tighter than the standalone
# ``secrets-scan`` CLI so ``audit-me`` stays a few seconds even across several
# repos. History is capped by commits AND wall time; tracked-file content is
# capped by file count. Truncation is surfaced as an ``unverifiable`` info row.
SECRETS_HISTORY_MAX_COMMITS = 200
SECRETS_HISTORY_MAX_SECONDS = 4.0
SECRETS_MAX_TRACKED_FILES = 2000

# The synthetic host for a local, no-SSH audit. Keeps the JSONL layout identical
# to the SSH scanner's ``~/.murmurent/security/<host>/`` tree.
LOCAL_HOST = "local"
PERSIST_ROOT = Path.home() / ".murmurent" / "security"

# Certs / REB expiry thresholds (days). A cert inside its warn window is amber;
# past valid_until is a block.
CERT_WARN_DAYS = 14
REB_WARN_DAYS = 30

MARKER_FILENAME = ".murmurent.yaml"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(handle: str) -> str:
    return str(handle or "").strip().lstrip("@").lower()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class PersonalAuditReport:
    """The result of one personal audit: a flat list of :class:`Finding` plus
    the metadata needed to render + persist it. ``findings`` carry their own
    ``category`` (one of :data:`ALL_AREAS`) so grouping is derived, not stored
    twice."""

    handle: str
    generated_at: str
    findings: list[Finding] = field(default_factory=list)

    # ---- grouping / summary -------------------------------------------------
    def by_area(self) -> dict[str, list[Finding]]:
        """``{area: [Finding, …]}`` for every area, empty lists included so the
        renderer can show a green "nothing to report" per area."""
        out: dict[str, list[Finding]] = {a: [] for a in ALL_AREAS}
        for f in self.findings:
            out.setdefault(f.category, []).append(f)
        return out

    def counts(self) -> dict[str, int]:
        """``{ok, concern, block, unverifiable}`` summary counts.

        ``concern`` = warn-severity, verified. ``block`` = block-severity,
        verified. ``unverifiable`` = any could-not-verify finding (regardless of
        severity). ``ok`` = verified info findings (the green "checked, fine"
        rows)."""
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
        """A ≤200-char, headline-first verdict line (per rules/headline_first)."""
        c = self.counts()
        if c["block"]:
            verb = f"BLOCKED — {c['block']} blocking issue(s)"
        elif c["concern"]:
            verb = f"Concerns — {c['concern']} to review"
        else:
            verb = "Clear — no blocking or concern findings"
        tail = f"; {c['unverifiable']} could-not-verify" if c["unverifiable"] else ""
        return f"{verb} for @{self.handle}{tail}."[:200]

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "generated_at": self.generated_at,
            "counts": self.counts(),
            "headline": self.headline(),
            "areas": {a: [f.to_dict() for f in fs] for a, fs in self.by_area().items()},
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Finding factory
# ---------------------------------------------------------------------------


def _mk(area: str, rule: str, *, severity: str, path: str, current: str,
        expected: str = "", fix: str = "", handle: str | None = None,
        project: str | None = None, notes: str = "",
        verify_state: str = VERIFY_VERIFIED, when: str = "") -> Finding:
    """Build a personal-audit :class:`Finding`. Thin wrapper so every check
    emits a consistent row (source=scanner, host=local)."""
    return Finding(
        severity=severity, category=area, rule=rule, host=LOCAL_HOST, path=path,
        current_state=current, expected_state=expected, suggested_fix=fix,
        detected_at=when or _iso(_now()), source=SOURCE_SCANNER,
        verify_state=verify_state,
        owner_handle=(f"@{_norm(handle)}" if handle else None),
        project=project, notes=notes,
        rule_doc_anchor="docs/security-dashboard.md#personal-audit",
    )


# ---------------------------------------------------------------------------
# Project scoping
# ---------------------------------------------------------------------------


def _my_projects(handle: str, env: dict | None) -> list[_cp.CertProject]:
    """Active cert-projects where ``handle`` is the lead OR a member."""
    h = _norm(handle)
    out: list[_cp.CertProject] = []
    for p in _cp.iter_projects(env):
        if p.status != "active":
            continue
        if _norm(p.lead) == h or any(_norm(m) == h for m in p.members):
            out.append(p)
    return out


def _is_lead(cp: _cp.CertProject, handle: str) -> bool:
    return _norm(cp.lead) == _norm(handle)


# ===========================================================================
# Item 1 — GitHub collaborator perms
# ===========================================================================


def check_github(handle: str, projects: list[_cp.CertProject],
                 env: dict | None) -> list[Finding]:
    """Item 1. As LEAD: every project member should have push; extra
    collaborators are noted (info, not a drift). As MEMBER: the viewer should be
    a collaborator. ``gh`` absent/unauthed ⇒ one ``unverifiable`` finding per
    project (never a false drift)."""
    gh_ok = _pp._gh_available()
    out: list[Finding] = []
    for cp in projects:
        repo = cp.github_repo or "(unprovisioned)"
        if not (cp.github_repo and "/" in cp.github_repo):
            out.append(_mk(AREA_GITHUB, "PERSONAL-GH-UNPROVISIONED-01",
                           severity=SEVERITY_INFO, path=repo,
                           current=f"{cp.name}: no GitHub repo provisioned yet",
                           expected="a private repo per project",
                           handle=handle, project=cp.name))
            continue
        if not gh_ok:
            out.append(_mk(AREA_GITHUB, "PERSONAL-GH-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=repo,
                           current="gh CLI not installed / not authenticated",
                           expected="`gh auth login` so collaborators can be read",
                           fix="gh auth login",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE,
                           notes="Could not read GitHub collaborators; not a drift."))
            continue
        try:
            drift = _cprov.reconcile_github(cp.name, env=env, apply=False)
        except Exception as exc:  # noqa: BLE001
            out.append(_mk(AREA_GITHUB, "PERSONAL-GH-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=repo,
                           current=f"could not reconcile: {exc}",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        if not drift.get("ok"):
            out.append(_mk(AREA_GITHUB, "PERSONAL-GH-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=repo,
                           current=f"reconcile unavailable: {drift.get('error')}",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        to_add = drift.get("to_add") or []      # desired members missing push
        to_remove = drift.get("to_remove") or []  # extra collaborators (owner excluded)
        if _is_lead(cp, handle):
            if to_add:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-MEMBER-MISSING-01",
                               severity=SEVERITY_WARN, path=repo,
                               current=f"{len(to_add)} project member(s) lack push: "
                                       + ", ".join(to_add),
                               expected="every project member has push access",
                               fix=f"murmurent project reconcile {cp.name} --apply",
                               handle=handle, project=cp.name))
            if to_remove:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-EXTRA-COLLAB-01",
                               severity=SEVERITY_INFO, path=repo,
                               current=f"{len(to_remove)} GitHub account(s) with repo "
                                       f"access but not in the project (noted, not an "
                                       f"error): " + ", ".join(to_remove),
                               expected="informational — review if unexpected",
                               handle=handle, project=cp.name,
                               notes="Extra collaborators are allowed; surfaced so "
                                     "you can react if unintended."))
            if not to_add and not to_remove:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-IN-SYNC-01",
                               severity=SEVERITY_INFO, path=repo,
                               current="collaborators match project members",
                               expected="in sync", handle=handle, project=cp.name))
        else:
            # As a member: am I (my github login) a collaborator? The reconcile
            # ``to_add`` lists the desired logins missing from actual; if MY login
            # is in it, I lack access.
            gh_map = _cprov.member_github_map([handle])
            my_login = gh_map.get(_norm(handle))
            if my_login and my_login in to_add:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-NO-ACCESS-01",
                               severity=SEVERITY_WARN, path=repo,
                               current=f"you ({my_login}) are not a collaborator",
                               expected="you should have push access",
                               fix="ask the project lead to add you",
                               handle=handle, project=cp.name))
            elif not my_login:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-NO-LOGIN-01",
                               severity=SEVERITY_INFO, path=repo,
                               current="no GitHub login recorded on your roster entry",
                               expected="a github login so access can be verified",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE))
            else:
                out.append(_mk(AREA_GITHUB, "PERSONAL-GH-ACCESS-OK-01",
                               severity=SEVERITY_INFO, path=repo,
                               current=f"you ({my_login}) have push access",
                               expected="ok", handle=handle, project=cp.name))
    return out


# ===========================================================================
# Item 4 — Slack channel membership
# ===========================================================================


def check_slack(handle: str, projects: list[_cp.CertProject],
                env: dict | None) -> list[Finding]:
    """Item 4. As LEAD: project members should be in the channel; extras noted.
    As MEMBER: the viewer should be in the channel. Missing token ⇒
    ``unverifiable`` (never a false in-sync)."""
    out: list[Finding] = []
    for cp in projects:
        chan = cp.slack_channel_id or "(unprovisioned)"
        if not cp.slack_channel_id:
            out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNPROVISIONED-01",
                           severity=SEVERITY_INFO, path=chan,
                           current=f"{cp.name}: no Slack channel provisioned yet",
                           handle=handle, project=cp.name))
            continue
        workspace = cp.slack_workspace or cp.lab
        token = ""
        try:
            token = _gr.resolve_group_slack_token(workspace) if workspace else ""
        except Exception:  # noqa: BLE001
            token = ""
        if not token:
            out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=chan,
                           current="no Slack bot token for this workspace",
                           expected="a group Slack token so membership can be read",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE,
                           notes="Could not read channel membership; not a drift."))
            continue
        try:
            drift = _cprov.reconcile_slack(cp.name, env=env, apply=False,
                                           remove_extras=True)
        except Exception as exc:  # noqa: BLE001
            out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=chan,
                           current=f"could not reconcile: {exc}",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        if not drift.get("ok"):
            out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=chan,
                           current=f"reconcile unavailable: {drift.get('error')}",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        to_invite = drift.get("to_invite") or []
        to_kick = drift.get("to_kick") or []       # extras, bot already excluded
        unresolved = drift.get("unresolved") or []
        if _is_lead(cp, handle):
            if to_invite:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-MEMBER-MISSING-01",
                               severity=SEVERITY_WARN, path=chan,
                               current=f"{len(to_invite)} project member(s) not in "
                                       f"the channel: " + ", ".join(to_invite),
                               expected="every project member is in the channel",
                               fix=f"murmurent project reconcile {cp.name} --apply",
                               handle=handle, project=cp.name))
            if to_kick:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-EXTRA-MEMBER-01",
                               severity=SEVERITY_INFO, path=chan,
                               current=f"{len(to_kick)} Slack account(s) in the channel "
                                       f"but not in the project (noted, not an error)",
                               handle=handle, project=cp.name,
                               notes="Extra channel members are allowed; surfaced so "
                                     "you can react if unintended."))
            if unresolved:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNRESOLVED-01",
                               severity=SEVERITY_INFO, path=chan,
                               current=f"couldn't find a Slack account for "
                                       f"{len(unresolved)} project member(s) "
                                       f"({', '.join(unresolved)}) — their roster email "
                                       f"may be missing or not in the workspace",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE))
            if not to_invite and not to_kick and not unresolved:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-IN-SYNC-01",
                               severity=SEVERITY_INFO, path=chan,
                               current="channel members match project members",
                               handle=handle, project=cp.name))
        else:
            if _norm(handle) in {_norm(h) for h in to_invite}:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-NOT-IN-CHANNEL-01",
                               severity=SEVERITY_WARN, path=chan,
                               current="you are not in the project's Slack channel",
                               expected="you should be in the channel",
                               fix="ask the project lead to invite you",
                               handle=handle, project=cp.name))
            elif _norm(handle) in {_norm(h) for h in unresolved}:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-UNRESOLVED-01",
                               severity=SEVERITY_INFO, path=chan,
                               current="your Slack id could not be resolved",
                               handle=handle, project=cp.name,
                               verify_state=VERIFY_UNVERIFIABLE))
            else:
                out.append(_mk(AREA_SLACK, "PERSONAL-SLACK-IN-CHANNEL-01",
                               severity=SEVERITY_INFO, path=chan,
                               current="you are in the project's Slack channel",
                               handle=handle, project=cp.name))
    return out


# ===========================================================================
# Item 7 (member) — the viewer's own certificate validity + clinical REB
# ===========================================================================


def _own_card_valid_until(env: dict | None) -> _dt.datetime | None:
    """``valid_until`` of this machine's stored signed member card, or ``None``
    when no dated card is on disk (member cards live in ``~/.murmurent/cards/``)."""
    try:
        from . import identity_card as _ic
        from . import issuance as _iss
        local = _ic.local_card(env=env) or {}
        centre = str(local.get("centre") or "")
        if not centre:
            return None
        import json
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in centre)
        member_p = _iss.cards_dir() / f"{safe}_member.json"
        if not member_p.is_file():
            return None
        bundle = json.loads(member_p.read_text(encoding="utf-8"))
        vu = (((bundle.get("member_card") or {}).get("payload") or {})
              .get("valid_until"))
        if not vu:
            return None
        dt = _dt.datetime.fromisoformat(str(vu).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def check_cert(handle: str, projects: list[_cp.CertProject],
               env: dict | None, now: _dt.datetime | None = None) -> list[Finding]:
    """Item 7 (member scope). Validate the viewer's OWN identity card
    (expired/revoked ⇒ block; expiring within 14 days ⇒ warn) via the crypto
    verifier, plus — for clinical projects the viewer LEADS — the REB expiry."""
    now = now or _now()
    out: list[Finding] = []

    # -- the viewer's own card ------------------------------------------------
    try:
        from . import issuance as _iss
        status, reason = _iss.verify_local_identity(env=env, now=now)
    except Exception as exc:  # noqa: BLE001
        status, reason = "unverifiable", str(exc)

    if status == "no_card":
        out.append(_mk(AREA_CERT, "PERSONAL-CERT-NO-CARD-01",
                       severity=SEVERITY_INFO, path="~/.murmurent/cards",
                       current="no signed identity card on this machine",
                       expected="an imported member/PI card",
                       handle=handle, verify_state=VERIFY_UNVERIFIABLE,
                       notes="Cannot verify certificate standing without a card."))
    elif status == "reject":
        out.append(_mk(AREA_CERT, "PERSONAL-CERT-INVALID-01",
                       severity=SEVERITY_BLOCK, path="~/.murmurent/cards",
                       current=f"your identity card is not valid: {reason}",
                       expected="a valid, unrevoked, unexpired card",
                       fix="ask your PI to re-issue your card",
                       handle=handle))
    elif status == "ok":
        vu = _own_card_valid_until(env)
        if vu is not None and (vu - now).days <= CERT_WARN_DAYS:
            days = (vu - now).days
            out.append(_mk(AREA_CERT, "PERSONAL-CERT-EXPIRING-01",
                           severity=SEVERITY_WARN, path="~/.murmurent/cards",
                           current=f"your identity card expires in {days} day(s) "
                                   f"({vu.date().isoformat()})",
                           expected=f"renew before it lapses (>{CERT_WARN_DAYS}d out)",
                           fix="ask your PI to re-issue your card",
                           handle=handle))
        else:
            out.append(_mk(AREA_CERT, "PERSONAL-CERT-OK-01",
                           severity=SEVERITY_INFO, path="~/.murmurent/cards",
                           current="your identity card is valid",
                           handle=handle))
    else:
        out.append(_mk(AREA_CERT, "PERSONAL-CERT-UNVERIFIABLE-01",
                       severity=SEVERITY_INFO, path="~/.murmurent/cards",
                       current=f"could not verify your card: {reason}",
                       handle=handle, verify_state=VERIFY_UNVERIFIABLE))

    # -- REB expiry on clinical projects the viewer LEADS ---------------------
    for cp in projects:
        if cp.sensitivity != "clinical" or not _is_lead(cp, handle):
            continue
        reb = (cp.reb_expires or "").strip()
        if not reb:
            out.append(_mk(AREA_CERT, "PERSONAL-REB-MISSING-01",
                           severity=SEVERITY_BLOCK, path=cp.name,
                           current="clinical project has no reb_expires recorded",
                           expected="a valid REB approval date",
                           handle=handle, project=cp.name))
            continue
        try:
            exp = _dt.datetime.fromisoformat(reb.replace("Z", "+00:00"))
            exp = exp if exp.tzinfo else exp.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            out.append(_mk(AREA_CERT, "PERSONAL-REB-BAD-DATE-01",
                           severity=SEVERITY_WARN, path=cp.name,
                           current=f"unparseable reb_expires: {reb!r}",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        days = (exp - now).days
        if days < 0:
            out.append(_mk(AREA_CERT, "PERSONAL-REB-EXPIRED-01",
                           severity=SEVERITY_BLOCK, path=cp.name,
                           current=f"REB approval expired {exp.date().isoformat()}",
                           expected="a current REB approval",
                           fix="renew the REB before continuing clinical work",
                           handle=handle, project=cp.name))
        elif days <= REB_WARN_DAYS:
            out.append(_mk(AREA_CERT, "PERSONAL-REB-EXPIRING-01",
                           severity=SEVERITY_WARN, path=cp.name,
                           current=f"REB approval expires in {days} day(s) "
                                   f"({exp.date().isoformat()})",
                           expected=f"renew before it lapses (>{REB_WARN_DAYS}d out)",
                           handle=handle, project=cp.name))
        else:
            out.append(_mk(AREA_CERT, "PERSONAL-REB-OK-01",
                           severity=SEVERITY_INFO, path=cp.name,
                           current=f"REB valid until {exp.date().isoformat()}",
                           handle=handle, project=cp.name))
    return out


# ===========================================================================
# Item 2i + vault — local repo + vault directory ACLs
# ===========================================================================


def _describe_access(path: Path) -> dict:
    """POSIX-mode access probe for ``path`` (follows symlinks — the vault is
    often a symlinked folder). Returns owner/group/world r/w/x bits + whether
    the current user owns it. ``stat`` only; never mutates."""
    st = path.stat()  # follows symlinks by design (item V: follow the vault link)
    mode = st.st_mode
    def bit(m: int) -> bool:
        return bool(mode & m)
    return {
        "mode": _stat.S_IMODE(mode),
        "owner_uid": st.st_uid,
        "is_owner": st.st_uid == os.getuid(),
        "group_read": bit(_stat.S_IRGRP), "group_write": bit(_stat.S_IWGRP),
        "group_exec": bit(_stat.S_IXGRP),
        "world_read": bit(_stat.S_IROTH), "world_write": bit(_stat.S_IWOTH),
        "world_exec": bit(_stat.S_IXOTH),
    }


def _acl_finding(area: str, path: Path, acc: dict, *, clinical: bool,
                 handle: str, project: str | None, label: str) -> Finding:
    """Turn an access description into a Finding. Ideal = owner-only (0700). Any
    group/world read or write escalates: warn on a normal repo, BLOCK on a
    clinical repo or the vault."""
    over_share = (acc["group_read"] or acc["group_write"] or acc["world_read"]
                  or acc["world_write"])
    mode_str = oct(acc["mode"])[-3:]
    if not over_share:
        return _mk(area, "PERSONAL-ACL-OK-01", severity=SEVERITY_INFO,
                   path=str(path),
                   current=f"{label}: owner-only ({mode_str})",
                   expected="owner-only (0700)", handle=handle, project=project,
                   notes="clinical" if clinical else "")
    who = []
    if acc["world_read"] or acc["world_write"]:
        who.append("world")
    if acc["group_read"] or acc["group_write"]:
        who.append("group")
    sev = SEVERITY_BLOCK if clinical else SEVERITY_WARN
    rule = ("PERSONAL-ACL-CLINICAL-01" if clinical
            else "PERSONAL-ACL-OVERSHARE-01")
    kind = "clinical repo/vault" if clinical else "repo"
    return _mk(area, rule, severity=sev, path=str(path),
               current=f"{label}: {'/'.join(who)}-accessible ({mode_str})",
               expected="owner-only (0700)",
               fix=f"chmod 700 {path}",
               handle=handle, project=project,
               notes=(f"{kind}: over-shared directory permissions escalate to "
                      "BLOCK for clinical data." if clinical else ""))


def _clinical_repo_index(env: dict | None) -> tuple[set[str], set[str]]:
    """Return ``(clinical_repo_paths, clinical_github_slugs)`` derived from
    cert-projects with ``sensitivity == "clinical"``. Paths are resolved
    absolute strings; slugs are lower-cased ``org/name``."""
    paths: set[str] = set()
    slugs: set[str] = set()
    for cp in _cp.iter_projects(env):
        if cp.sensitivity != "clinical":
            continue
        if cp.github_repo and "/" in cp.github_repo:
            slugs.add(cp.github_repo.strip().lower())
        for r in cp.repos:
            if r.path:
                try:
                    paths.add(str(Path(r.path).expanduser().resolve()))
                except OSError:
                    paths.add(str(Path(r.path).expanduser()))
        if cp.code_repo:
            try:
                paths.add(str(Path(cp.code_repo).expanduser().resolve()))
            except OSError:
                paths.add(str(Path(cp.code_repo).expanduser()))
    return paths, slugs


def _marker_declares_clinical(repo_dir: Path) -> bool:
    """True when ``repo_dir/.murmurent.yaml`` declares ``sensitivity: clinical``."""
    marker = repo_dir / MARKER_FILENAME
    if not marker.is_file():
        return False
    try:
        import yaml
        data = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return False
    return str((data or {}).get("sensitivity") or "").strip().lower() == "clinical"


def _repo_is_clinical(repo, clinical_paths: set[str], clinical_slugs: set[str]) -> bool:
    """Whether a scanned local repo is clinical: its path or origin matches a
    clinical cert-project, or its own ``.murmurent.yaml`` says so."""
    p = Path(repo.path)
    try:
        rp = str(p.resolve())
    except OSError:
        rp = str(p)
    if rp in clinical_paths or str(p) in clinical_paths:
        return True
    if repo.origin_url:
        canon = _inv._canonical_url(repo.origin_url)  # "github.com/org/name"
        slug = canon[len("github.com/"):] if canon.startswith("github.com/") else canon
        if slug and slug in clinical_slugs:
            return True
    return _marker_declares_clinical(p)


def check_repo_acls(handle: str, repos: list, env: dict | None) -> list[Finding]:
    """Item 2i. For each local MM-ready repo, describe who can read/write/execute
    it; over-share warns (blocks on a clinical repo)."""
    clinical_paths, clinical_slugs = _clinical_repo_index(env)
    out: list[Finding] = []
    for repo in repos:
        if not getattr(repo, "is_murmurent_ready", False):
            continue
        p = Path(repo.path)
        try:
            acc = _describe_access(p)
        except OSError as exc:
            out.append(_mk(AREA_REPOS, "PERSONAL-ACL-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=str(p),
                           current=f"could not stat: {exc}", handle=handle,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        clinical = _repo_is_clinical(repo, clinical_paths, clinical_slugs)
        out.append(_acl_finding(AREA_REPOS, p, acc, clinical=clinical,
                                handle=handle, project=None,
                                label=p.name + (" [clinical]" if clinical else "")))
    return out


def check_vault_acls(handle: str, env: dict | None) -> list[Finding]:
    """Item V (ACLs). The personal vault should be owner-only; ANY group/world
    read or write is a BLOCK (a clinical oracle entry behind a readable vault is
    a serious leak). Follows the vault symlink."""
    from . import vault_sync as _vs
    root = _vs.personal_vault_root()
    if root is None:
        return [_mk(AREA_VAULT, "PERSONAL-VAULT-UNREGISTERED-01",
                    severity=SEVERITY_INFO, path="(none)",
                    current="no personal vault registered on this machine",
                    expected="`murmurent vault init` to create/adopt one",
                    handle=handle, verify_state=VERIFY_UNVERIFIABLE)]
    if not root.exists():
        return [_mk(AREA_VAULT, "PERSONAL-VAULT-MISSING-01",
                    severity=SEVERITY_INFO, path=str(root),
                    current="registered vault path does not exist",
                    handle=handle, verify_state=VERIFY_UNVERIFIABLE)]
    try:
        acc = _describe_access(root)
    except OSError as exc:
        return [_mk(AREA_VAULT, "PERSONAL-VAULT-UNVERIFIABLE-01",
                    severity=SEVERITY_INFO, path=str(root),
                    current=f"could not stat vault: {exc}", handle=handle,
                    verify_state=VERIFY_UNVERIFIABLE)]
    # The vault is always treated as clinical-grade (block on over-share).
    return [_acl_finding(AREA_VAULT, root, acc, clinical=True, handle=handle,
                         project=None, label="personal vault")]


# ===========================================================================
# Item V — clinical-containment sweep (no clinical entry outside the vault)
# ===========================================================================


def check_clinical_containment(handle: str, repos: list,
                               env: dict | None) -> list[Finding]:
    """Item V. Scan lab-shared locations (the group governance repo ``oracle/``
    and every local repo) for oracle markdown carrying frontmatter
    ``sensitivity: clinical``. Any hit OUTSIDE the personal vault is a BLOCK —
    a clinical entry must never leave the personal vault (rules/oracle_schema)."""
    from . import vault_sync as _vs
    from .frontmatter import parse_file as _pf

    vault_root = _vs.personal_vault_root()
    try:
        vault_abs = vault_root.resolve() if vault_root else None
    except OSError:
        vault_abs = vault_root

    scan_roots: list[Path] = []
    try:
        lab_root = _repo.lab_mgmt_repo_root(env)
        if lab_root and lab_root.is_dir():
            scan_roots.append(lab_root)
    except Exception:  # noqa: BLE001
        pass
    for repo in repos:
        try:
            scan_roots.append(Path(repo.path))
        except Exception:  # noqa: BLE001
            continue

    out: list[Finding] = []
    seen: set[str] = set()
    for root in scan_roots:
        if not root.is_dir():
            continue
        try:
            if vault_abs is not None and root.resolve().is_relative_to(vault_abs):
                continue  # inside the vault — clinical is allowed there
        except (OSError, ValueError):
            pass
        for md in root.rglob("*.md"):
            if ".git" in md.parts:
                continue
            key = str(md)
            if key in seen:
                continue
            try:
                meta = _pf(md).meta or {}
            except Exception:  # noqa: BLE001
                continue
            if str(meta.get("sensitivity") or "").strip().lower() != "clinical":
                continue
            seen.add(key)
            out.append(_mk(AREA_VAULT, "PERSONAL-CLINICAL-LEAK-01",
                           severity=SEVERITY_BLOCK, path=str(md),
                           current="clinical-tagged oracle entry outside the "
                                   "personal vault",
                           expected="clinical entries live ONLY in the personal vault",
                           fix="move this entry into your personal vault and remove "
                               "the shared copy",
                           handle=handle,
                           notes="rules/oracle_schema.md: a clinical entry must "
                                 "never leave the personal vault."))
    if not out:
        out.append(_mk(AREA_VAULT, "PERSONAL-CLINICAL-CONTAINED-01",
                       severity=SEVERITY_INFO, path="(lab-shared locations)",
                       current="no clinical entries found outside the personal vault",
                       handle=handle))
    return out


# ===========================================================================
# Item 6 — non-MM repos
# ===========================================================================


def check_non_mm(handle: str, repos: list, github_repos: list,
                 inventory_keys: set[str], env: dict | None) -> list[Finding]:
    """Item 6. Local git repos that are NOT murmurent-ready and NOT murmurent
    infra ⇒ "using CC, not MM; may not follow lab rules". GitHub repos absent
    from the local inventory ⇒ info (could be cloned)."""
    out: list[Finding] = []
    for repo in repos:
        if not getattr(repo, "is_git", True):
            continue
        if getattr(repo, "is_murmurent_ready", False):
            continue
        if getattr(repo, "is_murmurent_infra", False):
            continue
        out.append(_mk(AREA_NON_MM, "PERSONAL-NON-MM-REPO-01",
                       severity=SEVERITY_INFO, path=repo.path,
                       current="git repo is not murmurent-ready",
                       expected="`murmurent adopt` to bring it under lab rules",
                       fix="murmurent adopt  # from inside the repo",
                       handle=handle,
                       notes="Using Claude Code, not murmurent — may not follow "
                             "lab data/naming rules."))
    for gh in github_repos:
        if getattr(gh, "archived", False):
            continue
        canon = _inv._canonical_url(getattr(gh, "ssh_url", ""))
        if canon and canon not in inventory_keys:
            out.append(_mk(AREA_NON_MM, "PERSONAL-GH-NOT-LOCAL-01",
                           severity=SEVERITY_INFO, path=gh.full_name,
                           current="GitHub repo not cloned on this machine",
                           expected="informational — clone if you work on it here",
                           handle=handle))
    return out


# ===========================================================================
# Item 8 — agent integrity (deterministic half; issue #63 item 8)
# ===========================================================================
#
# Classify every installed CC agent (pristine commons symlink / personal fork /
# orphan), then — for forks and untracked overrides — diff the fork against its
# commons origin for GUARDRAIL WEAKENING (a withheld tool re-enabled), freeze /
# category / model tampering, and safety-instruction removal, and run a static
# risk grep over the agent body. Everything lands in the same ``Finding``
# pipeline under ``category="agents"``. Read-only: agent files are only read,
# never forked / unforked / rewritten (all mutation lives in ``agent_forks``).
#
# The reuse substrate is :mod:`murmurent.core.agent_forks`: ``iter_status()``
# gives the install kind ("linked" | "forked" | "user-file") + drift booleans
# derived from each fork's ``source_sha``; ``commons_agents_dir()`` /
# ``commons_agent_path()`` locate the commons origin; ``load_manifest()`` is the
# fork provenance.
#
# TODO(phase-2): the SEMANTIC half of item 8 — an LLM ``agents`` category in
# ``security_agent_review.py`` that reasons about a fork's *intent* (a subtly
# reworded refusal, a persona nudged toward over-compliance) — plugs in here,
# consuming the same ``AREA_AGENTS`` findings as deterministic priors. Not built
# in this phase; do NOT implement it in this module.

# Guardian agents: any modification escalates one severity level (item 8.5).
# The named set are the egress/PHI/methodology gatekeepers; additionally, any
# commons agent whose frontmatter DENIES an egress tool is treated as guardian.
GUARDIAN_AGENTS = frozenset({"security_guard", "adversary", "conscience"})
EGRESS_TOOLS = frozenset({"WebFetch", "WebSearch", "Bash"})

# Static risk grep over the agent BODY. STRONG matches are warn-worthy on their
# own; WEAK matches are ambiguous → info. Guardian escalation still applies.
_RISK_STRONG: tuple[tuple[str, str], ...] = (
    (r"always\s+approve", "always-approve"),
    (r"do\s+not\s+(?:check|report|verify|flag)", "do-not-check/report"),
    (r"\bexfiltrat", "exfiltrate"),
    (r"send\s+.{0,40}?\bto\s+https?://", "send-to-remote-host"),
    (r"\brm\s+-rf\b", "destructive-rm"),
    (r"curl\s+.{0,80}?\|\s*(?:ba)?sh", "pipe-curl-to-shell"),
    (r"sk-[A-Za-z0-9]{16,}", "openai-key-shape"),
    (r"AKIA[0-9A-Z]{12,}", "aws-key-shape"),
    (r"xoxb-[0-9A-Za-z-]{10,}", "slack-token-shape"),
    (r"-----BEGIN\s+[A-Z ]*PRIVATE KEY-----", "private-key-block"),
    (r"(?:cat|read)\s+.{0,40}?(?:id_rsa|\.ssh/|\.env\b)", "read-secret-file"),
)
_RISK_WEAK: tuple[tuple[str, str], ...] = (
    (r"\bignore\b", "ignore"),
    (r"\bbypass\b", "bypass"),
    (r"\bdisable\b", "disable"),
)

# Safety-instruction markers: if a phrase family is present in the COMMONS body
# but absent from the fork body, that guardrail was removed.
_SAFETY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("headline-first verdict", ("mandatory output rule", "verdict")),
    ("PHI guardrail", ("phi",)),
    ("secret guardrail", ("secret",)),
    ("refusal language", ("refuse", "must never", "never let")),
)


def _tool_set(value) -> set[str]:
    """Normalise a frontmatter tool field (list or comma-string) to a set."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {p.strip() for p in value.split(",") if p.strip()}
    if isinstance(value, (list, tuple)):
        return {str(x).strip() for x in value if str(x).strip()}
    return set()


def _agent_tools(meta: dict) -> tuple[set[str], set[str]]:
    """Return ``(allowed, denied)`` tool sets. ``allowed`` merges the murmurent
    ``required_tools`` and the Claude-Code ``tools`` frontmatter fields."""
    allowed = _tool_set(meta.get("required_tools")) | _tool_set(meta.get("tools"))
    denied = _tool_set(meta.get("denied_tools"))
    return allowed, denied


def _is_guardian(name: str, commons_meta: dict | None) -> bool:
    if name in GUARDIAN_AGENTS:
        return True
    if commons_meta is None:
        return False
    _, denied = _agent_tools(commons_meta)
    return bool(denied & EGRESS_TOOLS)


def _esc(severity: str, guardian: bool) -> str:
    """Escalate a concern one severity level for guardian agents (item 8.5)."""
    if not guardian:
        return severity
    return {SEVERITY_INFO: SEVERITY_WARN, SEVERITY_WARN: SEVERITY_BLOCK,
            SEVERITY_BLOCK: SEVERITY_BLOCK}[severity]


def _parse_agent(text: str) -> tuple[dict, str]:
    """Best-effort ``(meta, body_lower)`` from agent markdown text. On a
    frontmatter parse error, meta is ``{}`` and the whole text is the body."""
    try:
        doc = _parse_fm(text)
        return (doc.meta or {}), doc.body.lower()
    except Exception:  # noqa: BLE001
        return {}, text.lower()


def _diff_fork(name: str, fork_meta: dict, fork_body: str,
               commons_meta: dict, commons_body: str, *, guardian: bool,
               handle: str) -> list[Finding]:
    """Diff a fork's frontmatter + body against its commons origin. Emits
    guardrail-weakening, freeze/category/model-tamper and safety-removal
    findings (all in ``AREA_AGENTS``)."""
    out: list[Finding] = []
    f_allowed, f_denied = _agent_tools(fork_meta)
    c_allowed, c_denied = _agent_tools(commons_meta)

    # -- guardrail weakening (highest signal) --------------------------------
    regained = c_denied - f_denied            # a denied tool is no longer denied
    widened = f_allowed - c_allowed           # a new tool granted
    reenabled = sorted((regained | (widened & EGRESS_TOOLS)))
    if regained or (widened & EGRESS_TOOLS):
        # Block if a guardian regains a withheld (denied) tool (item 8.2/8.5).
        base = SEVERITY_WARN
        sev = SEVERITY_BLOCK if (guardian and regained) else _esc(base, guardian)
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-GUARDRAIL-WEAKENED-01",
                       severity=sev, path=name,
                       current=f"fork re-enables withheld capability: "
                               + ", ".join(reenabled),
                       expected="fork keeps the commons tool guardrails",
                       fix=f"murmurent agent unfork {name}  # or restore denied_tools",
                       handle=handle,
                       notes=("guardian agent — tool weakening escalated"
                              if guardian else "")))
    elif widened:
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-TOOLS-WIDENED-01",
                       severity=_esc(SEVERITY_WARN, guardian), path=name,
                       current=f"fork grants extra tool(s): "
                               + ", ".join(sorted(widened)),
                       expected="fork keeps the commons tool set",
                       handle=handle))

    # -- freeze / category / model tampering ---------------------------------
    if str(commons_meta.get("freeze") or "").strip().lower() == "frozen":
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-FROZEN-MODIFIED-01",
                       severity=_esc(SEVERITY_WARN, guardian), path=name,
                       current="a commons-frozen agent has been modified locally",
                       expected="frozen agents are not meant to be forked/edited",
                       fix=f"murmurent agent unfork {name}",
                       handle=handle))
    if commons_meta.get("category") is not None and \
            str(fork_meta.get("category")) != str(commons_meta.get("category")):
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-CATEGORY-CHANGED-01",
                       severity=_esc(SEVERITY_WARN, guardian), path=name,
                       current=f"category changed "
                               f"{commons_meta.get('category')!r} → "
                               f"{fork_meta.get('category')!r}",
                       expected="category matches the commons definition",
                       handle=handle))
    if commons_meta.get("model") is not None and \
            str(fork_meta.get("model")) != str(commons_meta.get("model")):
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-MODEL-CHANGED-01",
                       severity=_esc(SEVERITY_WARN, guardian), path=name,
                       current=f"model changed {commons_meta.get('model')!r} → "
                               f"{fork_meta.get('model')!r}",
                       expected="model matches the commons definition",
                       handle=handle))

    # -- safety-instruction removal ------------------------------------------
    removed = []
    for label, subs in _SAFETY_MARKERS:
        in_commons = any(s in commons_body for s in subs)
        in_fork = any(s in fork_body for s in subs)
        if in_commons and not in_fork:
            removed.append(label)
    if removed:
        out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-SAFETY-REMOVED-01",
                       severity=_esc(SEVERITY_WARN, guardian), path=name,
                       current="fork drops safety language present in commons: "
                               + ", ".join(removed),
                       expected="fork retains the commons safety instructions",
                       handle=handle))
    return out


def _risk_grep(name: str, body: str, *, guardian: bool, handle: str) -> Finding | None:
    """Static risk grep over an agent body. Returns one summarising Finding, or
    ``None`` when nothing matched. STRONG hits ⇒ warn; only-WEAK hits ⇒ info."""
    strong = sorted({tag for pat, tag in _RISK_STRONG if _re.search(pat, body, _re.I)})
    weak = sorted({tag for pat, tag in _RISK_WEAK if _re.search(pat, body, _re.I)})
    if not strong and not weak:
        return None
    base = SEVERITY_WARN if strong else SEVERITY_INFO
    tags = strong + weak
    return _mk(AREA_AGENTS, "PERSONAL-AGENT-RISK-GREP-01",
               severity=_esc(base, guardian), path=name,
               current="risk pattern(s) in agent body: " + ", ".join(tags),
               expected="agent body free of override / exfiltration language",
               handle=handle,
               notes="ambiguous (weak match only)" if not strong else "")


def check_agent_integrity(handle: str, env: dict | None) -> list[Finding]:
    """Item 8 (deterministic half). Classify every installed CC agent and, for
    forks / untracked overrides, diff them against the commons origin. Read-only:
    only reads agent files. Missing prerequisites (commons dir unresolvable,
    unreadable manifest) ⇒ a single ``unverifiable`` finding, never a false
    clean."""
    h = handle or None

    commons_dir = _af.commons_agents_dir()
    if not commons_dir.is_dir():
        return [_mk(AREA_AGENTS, "PERSONAL-AGENT-COMMONS-UNRESOLVABLE-01",
                    severity=SEVERITY_INFO, path=str(commons_dir),
                    current="commons agents dir not found — cannot classify agents",
                    expected="a resolvable <murmurent-repo>/agents directory",
                    handle=h, verify_state=VERIFY_UNVERIFIABLE,
                    notes="Could not resolve the commons; not a clean result.")]
    try:
        _af.load_manifest()
    except Exception as exc:  # noqa: BLE001
        return [_mk(AREA_AGENTS, "PERSONAL-AGENT-MANIFEST-UNREADABLE-01",
                    severity=SEVERITY_INFO, path=str(_af.manifest_path()),
                    current=f"agent-fork manifest unreadable: {exc}",
                    handle=h, verify_state=VERIFY_UNVERIFIABLE,
                    notes="Could not read fork provenance; not a clean result.")]
    try:
        statuses = _af.iter_status()
    except Exception as exc:  # noqa: BLE001
        return [_mk(AREA_AGENTS, "PERSONAL-AGENT-STATUS-UNVERIFIABLE-01",
                    severity=SEVERITY_INFO, path=str(_af.installed_agents_dir()),
                    current=f"could not read installed agents: {exc}",
                    handle=h, verify_state=VERIFY_UNVERIFIABLE)]

    if not statuses:
        return [_mk(AREA_AGENTS, "PERSONAL-AGENT-NONE-01",
                    severity=SEVERITY_INFO, path=str(_af.installed_agents_dir()),
                    current="no installed agents to check",
                    handle=h)]

    out: list[Finding] = []
    for st in statuses:
        name = st.name
        commons_path = _af.commons_agent_path(name)
        installed_path = _af.installed_agents_dir() / f"{name}.md"

        commons_meta: dict | None = None
        commons_body = ""
        if commons_path.is_file():
            try:
                commons_meta, commons_body = _parse_agent(
                    commons_path.read_text(encoding="utf-8"))
            except OSError:
                commons_meta, commons_body = None, ""
        guardian = _is_guardian(name, commons_meta)

        # --- pristine commons symlink ---------------------------------------
        if st.kind == "linked":
            out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-PRISTINE-01",
                           severity=SEVERITY_INFO, path=name,
                           current="pristine commons symlink",
                           expected="commons symlink (unmodified)", handle=h,
                           notes="guardian" if guardian else ""))
            continue

        # Read the working copy body once for fork/override/orphan cases.
        try:
            fork_text = installed_path.read_text(encoding="utf-8")
        except OSError as exc:
            out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-STATUS-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=name,
                           current=f"could not read agent file: {exc}", handle=h,
                           verify_state=VERIFY_UNVERIFIABLE))
            continue
        fork_meta, fork_body = _parse_agent(fork_text)

        # --- orphan: a real file with no commons origin ---------------------
        if commons_meta is None:
            out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-ORPHAN-01",
                           severity=SEVERITY_INFO, path=name,
                           current="orphan agent — no commons origin, no known "
                                   "group-toolkit source",
                           expected="awareness — a group-toolkit agent is fine; a "
                                    "stray file may not be",
                           handle=h, verify_state=VERIFY_VERIFIED,
                           notes="Orphans are surfaced for awareness, not as an error."))
            rg = _risk_grep(name, fork_body, guardian=guardian, handle=h)
            if rg:
                out.append(rg)
            continue

        # --- forked (tracked) or untracked override (user-file) -------------
        modified = True
        if st.kind == "forked":
            if st.in_commons is False:
                out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-FORK-ORPHANED-01",
                               severity=SEVERITY_WARN, path=name,
                               current="fork of a commons agent that no longer exists",
                               expected="the commons still ships this agent",
                               handle=h))
                rg = _risk_grep(name, fork_body, guardian=guardian, handle=h)
                if rg:
                    out.append(rg)
                continue
            modified = bool(st.locally_modified)
            if not modified:
                out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-FORK-CLEAN-01",
                               severity=SEVERITY_INFO, path=name,
                               current="personal fork, unmodified since fork point"
                                       + (" (commons has since changed)"
                                          if st.upstream_changed else ""),
                               expected="fork tracks the commons", handle=h,
                               notes="guardian" if guardian else ""))
                continue
            out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-FORK-MODIFIED-01",
                           severity=SEVERITY_INFO, path=name,
                           current="personal fork differs from the commons origin",
                           expected="review the diff below", handle=h,
                           notes="guardian" if guardian else ""))
        else:  # kind == "user-file" that shadows a commons agent → untracked override
            out.append(_mk(AREA_AGENTS, "PERSONAL-AGENT-UNTRACKED-OVERRIDE-01",
                           severity=_esc(SEVERITY_INFO, guardian), path=name,
                           current="hand-authored file shadows a commons agent "
                                   "(no fork provenance)",
                           expected="`murmurent agent fork` to track it, or unfork",
                           handle=h,
                           notes="guardian" if guardian else ""))

        out += _diff_fork(name, fork_meta, fork_body, commons_meta, commons_body,
                          guardian=guardian, handle=h)
        rg = _risk_grep(name, fork_body, guardian=guardian, handle=h)
        if rg:
            out.append(rg)
    return out


# ===========================================================================
# Items 2ii-2iv — local-repo content scanners (deterministic)
# ===========================================================================


def check_repo_content(handle: str, repos: list, env: dict | None) -> list[Finding]:
    """Items 2(ii)-2(iv). For each LOCAL murmurent-ready repo, scan its source
    files for out-of-root write sinks (``output``), insecure transports /
    in-URL credentials (``network``), and outbound/API egress (``egress``).

    Reuses the clinical-repo detection built for the ACL check
    (:func:`_clinical_repo_index` + :func:`_repo_is_clinical`) so a clinical
    repo escalates out-of-root writes and data-shipping egress to BLOCK. All
    matching is read-only grep — no file is written and no network call is made.
    The heavy lifting lives in :mod:`murmurent.core.repo_content_scan`; this
    wrapper only supplies the clinical predicate and keeps the check-function
    signature uniform with the rest of the audit."""
    clinical_paths, clinical_slugs = _clinical_repo_index(env)

    def _is_clinical(repo) -> bool:
        return _repo_is_clinical(repo, clinical_paths, clinical_slugs)

    return _rcs.scan_repos(handle, repos, env, _is_clinical)


# ===========================================================================
# Secrets — tracked-file content + git-history walk + GitHub alerts
# ===========================================================================
#
# Reuses the merged deterministic scanner (:mod:`murmurent.core.secret_scan`):
# ``scan_paths`` over tracked files (exactly what is pushed) and the bounded
# ``scan_history`` (added lines across reachable commits — catches a secret
# committed then deleted). GitHub's own secret-scanning alerts are queried per
# project repo via ``gh``. Every value is REDACTED at the scanner boundary; a
# Finding never carries raw secret material. Read-only throughout: only ``git
# log`` / ``git ls-files`` / ``gh api`` (GET) run — no checkout, no mutation.
#
# TODO(phase-3): semantic LLM secret triage (is this high-entropy string an
# actual live credential vs. a test fixture / example?) and rotation/remediation
# actions (open a rotation ticket, call the secret store) plug in here as a new
# ``security_agent_review`` reviewer consuming these deterministic hits as
# priors. NOT built in this phase.


def _secret_hit_to_finding(hit, rule: str, handle: str, *,
                           in_history: bool):
    """Translate a redacted :class:`secret_scan.SecretHit` into a personal-audit
    :class:`Finding`. The history-truncation sentinel becomes an ``unverifiable``
    info row; a real hit becomes a block (high-confidence) or warn (heuristic)
    row. ``hit.redacted`` is the ONLY representation of the value — never the raw
    secret."""
    from . import secret_scan as _ss

    if hit.rule == _ss.HISTORY_TRUNCATED_RULE:
        return _mk(AREA_SECRETS, "PERSONAL-SECRET-HISTORY-TRUNCATED-01",
                   severity=SEVERITY_INFO, path=hit.path,
                   current="git-history secret scan hit its commit/time budget; "
                           "older commits were not scanned",
                   expected="informational — deep history not fully covered",
                   handle=handle, verify_state=VERIFY_UNVERIFIABLE, notes=hit.hint)

    sev = SEVERITY_BLOCK if hit.severity == _ss.SEVERITY_BLOCK else SEVERITY_WARN
    loc = f"line {hit.line}" if hit.line else "unknown line"
    where = f", commit {hit.commit[:9]}" if (in_history and hit.commit) else ""
    fix = ("remove the secret, ROTATE the credential, and load it from "
           "env/secret store")
    if in_history:
        fix += "; then purge it from history (e.g. git filter-repo) after rotating"
    return _mk(AREA_SECRETS, rule, severity=sev, path=hit.path,
               current=f"{hit.rule}: redacted secret {hit.redacted} ({loc}{where})",
               expected="no secret material in tracked files or git history",
               fix=fix, handle=handle, notes=hit.hint)


def _check_github_secret_alerts(handle: str, projects: list[_cp.CertProject],
                                env: dict | None) -> list[Finding]:
    """Query GitHub secret-scanning alerts for each project's repo. OPEN alerts
    ⇒ warn (metadata only — GitHub never returns the secret itself). ``gh``
    absent / not-enabled / 403 / 404 ⇒ a single ``unverifiable`` row per repo —
    NEVER a false clean. Read-only: ``gh api`` GET only."""
    import json as _json

    out: list[Finding] = []
    gh_ok = _pp._gh_available()
    for cp in projects:
        slug = (cp.github_repo or "").strip()
        if not slug or "/" not in slug:
            continue  # unprovisioned repos are covered by the github area
        if not gh_ok:
            out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-GH-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=slug,
                           current="gh CLI not installed/authenticated — cannot "
                                   "read GitHub secret-scanning alerts",
                           expected="`gh auth login` so alerts can be read",
                           fix="gh auth login", handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE,
                           notes="Could not query secret-scanning; not a clean result."))
            continue
        err = ""
        res = None
        try:
            res = _pp._gh(["api", f"repos/{slug}/secret-scanning/alerts",
                           "-f", "state=open", "--paginate"])
        except Exception as exc:  # noqa: BLE001 — timeout / OS error
            err = str(exc)
        if res is None or res.returncode != 0:
            detail = (getattr(res, "stderr", "") or err or "").strip()
            first = detail.splitlines()[0] if detail else "unknown error"
            out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-GH-UNVERIFIABLE-01",
                           severity=SEVERITY_INFO, path=slug,
                           current=f"could not read GitHub secret-scanning alerts "
                                   f"({first})",
                           expected="secret scanning enabled + access to read alerts",
                           handle=handle, project=cp.name,
                           verify_state=VERIFY_UNVERIFIABLE,
                           notes="Common causes: secret scanning not enabled (403), "
                                 "repo/endpoint not found (404), or no gh access."))
            continue
        try:
            alerts = _json.loads(res.stdout or "[]")
            if not isinstance(alerts, list):
                alerts = []
        except (ValueError, TypeError):
            alerts = []
        open_alerts = [a for a in alerts
                       if str((a or {}).get("state", "")).lower() == "open"]
        if open_alerts:
            types: dict[str, int] = {}
            for a in open_alerts:
                t = (a.get("secret_type_display_name")
                     or a.get("secret_type") or "unknown")
                types[str(t)] = types.get(str(t), 0) + 1
            summary = ", ".join(f"{k}×{v}" for k, v in sorted(types.items()))
            out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-GH-ALERT-01",
                           severity=SEVERITY_WARN, path=slug,
                           current=f"{len(open_alerts)} open GitHub secret-scanning "
                                   f"alert(s): {summary}",
                           expected="zero open secret-scanning alerts",
                           fix="rotate the exposed credential(s), then resolve the "
                               "alert(s) on GitHub",
                           handle=handle, project=cp.name,
                           notes="GitHub returns alert metadata only (type/location), "
                                 "never the secret value."))
        else:
            out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-GH-OK-01",
                           severity=SEVERITY_INFO, path=slug,
                           current="no open GitHub secret-scanning alerts",
                           handle=handle, project=cp.name))
    return out


def check_secrets(handle: str, repos: list, projects: list[_cp.CertProject],
                  env: dict | None) -> list[Finding]:
    """Secret detection for the personal audit. For each LOCAL murmurent-ready
    repo: scan tracked-file CONTENT (what a push publishes) and run the bounded
    git-history walk (catches secrets committed then deleted). Plus GitHub
    secret-scanning alerts per project repo. Confirmed local secrets BLOCK
    (redacted); GitHub alerts warn; missing prerequisites are ``unverifiable``.
    Findings are rolled up per directory so a messy repo does not flood."""
    from . import secret_scan as _ss

    out: list[Finding] = []
    scanned_any = False
    for repo in repos:
        if not getattr(repo, "is_murmurent_ready", False):
            continue
        root = Path(getattr(repo, "path", ""))
        if not root.is_dir():
            continue
        scanned_any = True

        # -- tracked-file content (bounded by file count) --------------------
        tracked = [str(root / p)
                   for p in _ss._git(root, ["ls-files", "-z"]).split("\0") if p]
        if len(tracked) > SECRETS_MAX_TRACKED_FILES:
            tracked = tracked[:SECRETS_MAX_TRACKED_FILES]
            out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-SCAN-TRUNCATED-01",
                           severity=SEVERITY_INFO, path=str(root),
                           current=f"scanned the first {SECRETS_MAX_TRACKED_FILES} "
                                   "tracked files; some were not examined",
                           expected="informational — a very large repo was only "
                                    "partially scanned",
                           handle=handle, verify_state=VERIFY_UNVERIFIABLE))
        for hit in _ss.scan_paths(tracked):
            out.append(_secret_hit_to_finding(
                hit, "PERSONAL-SECRET-IN-REPO-01", handle, in_history=False))

        # -- bounded git-history walk ----------------------------------------
        for hit in _ss.scan_history(root,
                                    max_commits=SECRETS_HISTORY_MAX_COMMITS,
                                    max_seconds=SECRETS_HISTORY_MAX_SECONDS):
            out.append(_secret_hit_to_finding(
                hit, "PERSONAL-SECRET-IN-HISTORY-01", handle, in_history=True))

    # Green "checked, clean" row when local scans found nothing real.
    real_rules = {"PERSONAL-SECRET-IN-REPO-01", "PERSONAL-SECRET-IN-HISTORY-01"}
    if scanned_any and not any(f.rule in real_rules for f in out):
        out.append(_mk(AREA_SECRETS, "PERSONAL-SECRET-CLEAN-01",
                       severity=SEVERITY_INFO, path="(local mm-ready repos)",
                       current="no secrets in tracked content or recent history",
                       handle=handle))

    # -- GitHub secret-scanning alerts per project repo ----------------------
    out += _check_github_secret_alerts(handle, projects, env)

    return rollup_by_directory(out)


# ===========================================================================
# Orchestrator
# ===========================================================================


def _local_repos() -> tuple[list, str | None]:
    """Scan this machine's local git repos via the repo inventory (no SSH — the
    ``local`` host runs the scan script in a local shell). Best-effort."""
    try:
        return _inv.list_machine_repos(LOCAL_HOST)
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def _github_repos(env: dict | None) -> tuple[list, str | None]:
    """Best-effort GitHub repo list for the lab org (item 6). Empty on any
    failure — never fatal."""
    try:
        from .lab import load_lab_config
        org = load_lab_config().github_org
    except Exception:  # noqa: BLE001
        org = ""
    if not org:
        return [], "no github org configured"
    try:
        return _inv.list_github_repos(org)
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def run_personal_audit(handle: str | None = None,
                       env: dict | None = None) -> PersonalAuditReport:
    """Run the full personal audit LOCALLY and return a
    :class:`PersonalAuditReport`. NO SSH; every reconciler is ``apply=False``;
    ACL checks ``stat`` only. Missing prerequisites yield ``unverifiable``
    findings so the report never silently lies.

    ``handle`` defaults to the resolved current member (env / user-file / gh).
    When no handle resolves, identity-dependent checks (github/slack/cert) are
    skipped with a single ``unverifiable`` finding; the filesystem checks
    (repos/vault/non-mm) still run."""
    when = _iso(_now())
    findings: list[Finding] = []

    # -- resolve identity -----------------------------------------------------
    if handle:
        resolved = _norm(handle)
    else:
        ident = _identity.resolve(allow_unknown=True)
        resolved = "" if ident.source == "unknown" else _norm(ident.handle)

    # -- local filesystem inventory (identity-independent) --------------------
    repos, repo_err = _local_repos()
    inventory_keys = {
        _inv._canonical_url(r.origin_url) for r in repos if r.origin_url
    }
    if repo_err:
        findings.append(_mk(AREA_REPOS, "PERSONAL-INVENTORY-UNVERIFIABLE-01",
                            severity=SEVERITY_INFO, path=LOCAL_HOST,
                            current=f"repo inventory scan failed: {repo_err}",
                            handle=resolved or None,
                            verify_state=VERIFY_UNVERIFIABLE, when=when))

    gh_repos, _gh_err = _github_repos(env)

    # -- identity-dependent checks -------------------------------------------
    projects: list[_cp.CertProject] = []
    if not resolved:
        findings.append(_mk(AREA_CERT, "PERSONAL-NO-HANDLE-01",
                            severity=SEVERITY_INFO, path="(identity)",
                            current="could not resolve your murmurent handle",
                            expected="set $MURMURENT_USER or run `gh auth login`",
                            verify_state=VERIFY_UNVERIFIABLE, when=when,
                            notes="Skipped GitHub/Slack/cert checks (need a handle)."))
    else:
        projects = _my_projects(resolved, env)
        findings += check_github(resolved, projects, env)
        findings += check_slack(resolved, projects, env)
        findings += check_cert(resolved, projects, env)

    # -- filesystem checks (run regardless of handle) -------------------------
    findings += check_repo_acls(resolved, repos, env)
    findings += check_vault_acls(resolved, env)
    findings += check_clinical_containment(resolved, repos, env)
    findings += check_non_mm(resolved, repos, gh_repos, inventory_keys, env)
    findings += check_agent_integrity(resolved, env)
    findings += check_repo_content(resolved, repos, env)
    findings += check_secrets(resolved, repos, projects, env)

    return PersonalAuditReport(handle=resolved or "unknown",
                               generated_at=when, findings=findings)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def persist(report: PersonalAuditReport) -> Path:
    """Write the report as JSONL under
    ``~/.murmurent/security/local/personal-<date>.jsonl`` and refresh the
    ``latest.jsonl`` symlink. Returns the dated path."""
    out_dir = PERSIST_ROOT / LOCAL_HOST
    out_dir.mkdir(parents=True, exist_ok=True)
    date = report.generated_at[:10]
    target = out_dir / f"personal-{date}.jsonl"
    write_jsonl(target, report.findings)
    latest = out_dir / "personal-latest.jsonl"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(target.name)
    except OSError:
        pass
    return target


def run_and_persist(handle: str | None = None,
                    env: dict | None = None) -> tuple[PersonalAuditReport, Path]:
    """Convenience: run the audit + persist it. Returns ``(report, path)``."""
    report = run_personal_audit(handle=handle, env=env)
    path = persist(report)
    return report, path


__all__ = [
    "PersonalAuditReport", "run_personal_audit", "persist", "run_and_persist",
    "check_github", "check_slack", "check_cert", "check_repo_acls",
    "check_vault_acls", "check_clinical_containment", "check_non_mm",
    "check_agent_integrity", "check_repo_content", "check_secrets",
    "ALL_AREAS", "AREA_GITHUB", "AREA_SLACK", "AREA_CERT", "AREA_REPOS",
    "AREA_VAULT", "AREA_NON_MM", "AREA_AGENTS", "AREA_OUTPUT", "AREA_NETWORK",
    "AREA_EGRESS", "AREA_SECRETS", "LOCAL_HOST", "CERT_WARN_DAYS", "REB_WARN_DAYS",
]
