"""
Purpose: Public lab/core/admin/pi join-request queue for a wigamig
         centre. Modelled exactly on ``collaboration_requests.py``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Anyone at the institution can submit a join request via the public
``/join`` form (no auth). Submissions land at:

    <lab_info>/join_requests/<id>.md

The registrar approves or declines from the dashboard's "Pending
joins" panel. Approval dispatches by ``kind``:

  - lab    → ``registrar.create_lab`` + (Phase 2g) ``centre_provision.provision_lab_onboarding``
  - core   → ``registrar.create_core`` + analogous provisioning
  - admin  → adds the handle to ``_registry.yaml:registrars:``
  - pi     → records the PI's intent to lead a lab; the lab record
             follows separately (a PI without a lab is just a member)

For ``kind=lab`` / ``kind=core``, the request file's ``probes:``
field accumulates the auto-provisioning probes (slack, github,
fs_acl) so the dashboard can poll progress + offer a retry button
on failure.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import dump_document, parse_file
from .registrar import (
    _git_commit_all, _git_init_if_needed, lab_info_root,
)


JOIN_REQUESTS_SUBDIR = "join_requests"
REQUEST_ID_RE = _re.compile(r"^(\d{4})\.md$")
VALID_KINDS = ("lab", "core", "admin", "pi")
VALID_STATES = ("pending", "approved", "declined", "provisioned", "failed")


class JoinRequestError(ValueError):
    """Join request mutation failed."""


class JoinRequestNotFound(JoinRequestError):
    """No request with the requested id."""


class JoinRequestStateError(JoinRequestError):
    """Illegal state transition (e.g. approving a declined request)."""


@dataclass
class JoinRequest:
    """One join-request record."""

    id: int
    kind: str                              # lab|core|admin|pi
    requester_email: str
    proposed_name: str                     # short slug
    proposed_pi: str                       # @handle (the PI of the proposed lab/core, or self for admin/pi kinds)
    institution_affiliation: str           # free-text
    justification: str = ""
    proposed_members: list[str] = field(default_factory=list)
    state: str = "pending"
    created_at: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
    decline_reason: str = ""
    # probes is a list of {kind, severity, summary, apply_hint?}
    probes: list[dict[str, str]] = field(default_factory=list)
    # Provenance for requests ingested from the wigamig_public hub:
    # the source GitHub issue as "owner/repo#N" (empty for dashboard/CLI
    # submissions). When set, the decision is reported back as an issue
    # comment instead of an email DM (the public form collects no email).
    source_issue: str = ""
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "requester_email": self.requester_email,
            "proposed_name": self.proposed_name,
            "proposed_pi": self.proposed_pi,
            "institution_affiliation": self.institution_affiliation,
            "justification": self.justification,
            "proposed_members": list(self.proposed_members),
            "state": self.state,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "decline_reason": self.decline_reason,
            "probes": list(self.probes),
        }
        if self.source_issue:
            meta["source_issue"] = self.source_issue
        return meta


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def requests_dir(env: dict[str, str] | None = None) -> Path:
    return lab_info_root(env) / JOIN_REQUESTS_SUBDIR


def request_path(req_id: int, env: dict[str, str] | None = None) -> Path:
    return requests_dir(env) / f"{req_id:04d}.md"


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def parse_request(path: Path) -> JoinRequest:
    parsed = parse_file(path)
    meta = parsed.meta or {}
    return JoinRequest(
        id=int(meta.get("id") or 0),
        kind=str(meta.get("kind") or "lab").lower(),
        requester_email=str(meta.get("requester_email") or "").strip(),
        proposed_name=str(meta.get("proposed_name") or "").strip(),
        proposed_pi=str(meta.get("proposed_pi") or "").strip(),
        institution_affiliation=str(meta.get("institution_affiliation") or "").strip(),
        justification=str(meta.get("justification") or ""),
        proposed_members=[str(m) for m in (meta.get("proposed_members") or [])],
        state=str(meta.get("state") or "pending"),
        created_at=str(meta.get("created_at") or ""),
        resolved_at=str(meta.get("resolved_at") or ""),
        resolved_by=str(meta.get("resolved_by") or ""),
        decline_reason=str(meta.get("decline_reason") or ""),
        probes=list(meta.get("probes") or []),
        source_issue=str(meta.get("source_issue") or "").strip(),
        body=(parsed.body or "").strip(),
        path=path,
    )


def iter_requests(
    *,
    state: str | None = None,
    env: dict[str, str] | None = None,
) -> list[JoinRequest]:
    rdir = requests_dir(env)
    if not rdir.is_dir():
        return []
    out: list[JoinRequest] = []
    for child in sorted(rdir.iterdir()):
        if not REQUEST_ID_RE.match(child.name):
            continue
        try:
            out.append(parse_request(child))
        except Exception:
            continue
    if state:
        out = [r for r in out if r.state == state]
    out.sort(key=lambda r: r.id)
    return out


def get_request(
    req_id: int, env: dict[str, str] | None = None,
) -> JoinRequest:
    p = request_path(req_id, env)
    if not p.is_file():
        raise JoinRequestNotFound(f"join request not found: {req_id}")
    return parse_request(p)


def next_request_id(env: dict[str, str] | None = None) -> int:
    used = [r.id for r in iter_requests(env=env)]
    return (max(used) + 1) if used else 1


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _default_body(req: JoinRequest) -> str:
    parts = [
        f"# Join request #{req.id:04d} — {req.kind} `{req.proposed_name}`",
        "",
        f"Requester: {req.requester_email}",
        f"Proposed PI: {req.proposed_pi}",
        f"Institution: {req.institution_affiliation}",
        "",
    ]
    if req.justification.strip():
        parts += ["## Justification", "", req.justification.strip(), ""]
    if req.proposed_members:
        parts.append("## Proposed members")
        parts.append("")
        for m in req.proposed_members:
            parts.append(f"- {m}")
        parts.append("")
    return "\n".join(parts)


def write_request(
    req: JoinRequest, env: dict[str, str] | None = None,
    *, audit_action: str = "update",
) -> Path:
    rdir = requests_dir(env)
    rdir.mkdir(parents=True, exist_ok=True)
    body = req.body or _default_body(req)
    p = request_path(req.id, env)
    p.write_text(dump_document(req.to_meta(), body), encoding="utf-8")
    req.path = p
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root, f"join_requests/{req.id:04d}: {audit_action}")
    return p


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def parse_join_form(text: str) -> dict[str, str]:
    """Parse the encrypted-email join form (``key: value`` lines, ``#``
    comments ignored) into a field dict. Recognised keys: kind, institution,
    name, pi, email, justification. Leading ``@`` on ``pi`` is preserved."""
    fields: dict[str, str] = {}
    known = {"kind", "institution", "name", "pi", "email", "justification"}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        # strip trailing inline "# comment"
        val = _re.split(r"\s+#", val.strip(), maxsplit=1)[0].strip()
        if key in known and val:
            fields[key] = val
    return fields


def file_request_from_form(
    text: str, *, source: str = "encrypted-email", env: dict[str, str] | None = None,
) -> JoinRequest:
    """Parse a decrypted join form and file the request. ``source`` is a short
    provenance note (e.g. the sender email) recorded in the audit action."""
    f = parse_join_form(text)
    return file_request(
        kind=f.get("kind", "pi"),
        requester_email=f.get("email", ""),
        proposed_name=f.get("name", ""),
        proposed_pi=f.get("pi", ""),
        institution_affiliation=f.get("institution", ""),
        justification=f.get("justification", ""),
        env=env,
    )


def _notify_safe(event: str, req: "JoinRequest", env) -> None:
    """Fire a Slack notification for a join event. Best-effort: any failure
    (import error, Slack down, no token) is swallowed so the request
    lifecycle is never affected. See core/join_notify.py."""
    try:
        from . import join_notify
        if event == "new":
            join_notify.notify_new_request(req, env=env)
        elif event == "decision":
            # Dashboard/CLI requests → DM the requester by email (no-op if
            # they gave none). Hub-ingested requests → comment on the
            # source GitHub issue (the public form collects no email).
            join_notify.notify_decision(req, env=env)
            if req.source_issue:
                from . import join_ingest
                join_ingest.comment_decision_on_issue(req, env=env)
    except Exception:  # noqa: BLE001 — notification must never break the flow
        pass


def file_request(
    *,
    kind: str,
    requester_email: str,
    proposed_name: str,
    proposed_pi: str,
    institution_affiliation: str = "",
    justification: str = "",
    proposed_members: list[str] | None = None,
    source_issue: str = "",
    env: dict[str, str] | None = None,
) -> JoinRequest:
    """Persist a new join request. Returns the saved request.

    ``requester_email`` is required for dashboard/CLI submissions. It may
    be empty **only** when ``source_issue`` is set (a request ingested
    from the wigamig_public hub, whose public form collects no email — the
    decision is reported back as a comment on that issue instead)."""
    kind_clean = (kind or "").strip().lower()
    if kind_clean not in VALID_KINDS:
        raise JoinRequestError(
            f"kind must be one of {VALID_KINDS} (got {kind!r})"
        )
    if not (requester_email or "").strip() and not (source_issue or "").strip():
        raise JoinRequestError(
            "requester_email is required (or source_issue for hub-ingested requests)"
        )
    if not (proposed_name or "").strip():
        raise JoinRequestError("proposed_name is required")
    if kind_clean in ("lab", "core") and not (proposed_pi or "").strip():
        raise JoinRequestError(
            f"proposed_pi is required for kind={kind_clean!r}"
        )
    req = JoinRequest(
        id=next_request_id(env),
        kind=kind_clean,
        requester_email=(requester_email or "").strip(),
        proposed_name=proposed_name.strip().lower(),
        proposed_pi=(proposed_pi.strip() if proposed_pi else ""),
        institution_affiliation=institution_affiliation.strip(),
        justification=justification.strip(),
        proposed_members=list(proposed_members or []),
        source_issue=(source_issue or "").strip(),
        state="pending",
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    filed_by = requester_email or source_issue or "unknown"
    write_request(req, env, audit_action=f"filed by {filed_by}")
    _notify_safe("new", req, env)
    return req


def _set_resolved(req: JoinRequest, resolver: str, state: str) -> None:
    req.state = state
    req.resolved_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    req.resolved_by = resolver.lstrip("@")


def approve(
    *,
    req_id: int,
    actor: str,
    provision: bool = True,
    env: dict[str, str] | None = None,
    token: str | None = None,
) -> JoinRequest:
    """Move a pending request → approved + dispatch the create / provision.

    For ``kind=lab`` / ``kind=core`` this also (when ``provision=True``)
    invokes ``centre_provision.provision_lab_onboarding`` (see 2g) and
    appends the probes to the request file.

    Returns the updated request.
    """
    from . import registrar as _R
    req = get_request(req_id, env)
    if req.state not in ("pending", "failed"):
        raise JoinRequestStateError(
            f"cannot approve request in state {req.state!r}"
        )

    pi_handle = req.proposed_pi
    if req.kind == "lab":
        try:
            _R.create_lab(
                name=req.proposed_name,
                display_name=req.proposed_name,
                pi_handle=pi_handle,
                env=env,
            )
        except Exception as exc:
            req.probes.append({
                "kind": "create_lab", "severity": "block",
                "summary": f"create_lab failed: {exc}",
            })
            _set_resolved(req, actor, "failed")
            write_request(req, env, audit_action=f"approve failed: {exc}")
            return req
    elif req.kind == "core":
        try:
            _R.create_core(
                name=req.proposed_name,
                display_name=req.proposed_name,
                leader_handle=pi_handle,
                env=env,
            )
        except Exception as exc:
            req.probes.append({
                "kind": "create_core", "severity": "block",
                "summary": f"create_core failed: {exc}",
            })
            _set_resolved(req, actor, "failed")
            write_request(req, env, audit_action=f"approve failed: {exc}")
            return req
    elif req.kind == "admin":
        # Add the handle to _registry.yaml:registrars:.
        reg = _R.read_registry(env)
        norm = _R._normalize(pi_handle or req.requester_email)
        if norm and norm not in reg.registrars:
            reg.registrars.append(norm)
            _R.write_registry(reg, env)
    elif req.kind == "pi":
        # No infra action: the PI's intent is recorded; the lab record
        # follows separately (via a kind=lab request).
        pass

    # Provisioning (Slack / GitHub / FS ACLs) only fires for lab+core.
    if provision and req.kind in ("lab", "core"):
        try:
            from . import centre_provision as _cp
            probes = _cp.provision_lab_onboarding(
                req.proposed_name, env=env, token=token,
            )
            req.probes.extend([
                {"kind": p.name, "severity": p.status,
                 "summary": p.detail or ""}
                for p in probes
            ])
            has_block = any(p.status == "block" for p in probes)
            has_warn = any(p.status == "warn" for p in probes)
            if has_block:
                _set_resolved(req, actor, "failed")
            elif has_warn:
                # Warnings (e.g. gh not installed) are non-fatal but
                # surface so the registrar can hit "remediate".
                _set_resolved(req, actor, "provisioned")
            else:
                _set_resolved(req, actor, "provisioned")
        except Exception as exc:
            req.probes.append({
                "kind": "provision", "severity": "block",
                "summary": f"provisioning errored: {exc}",
            })
            _set_resolved(req, actor, "failed")
    else:
        _set_resolved(req, actor, "approved")

    write_request(req, env, audit_action=f"approved by @{actor.lstrip('@')}")
    _notify_safe("decision", req, env)
    return req


def decline(
    *,
    req_id: int,
    actor: str,
    reason: str,
    env: dict[str, str] | None = None,
) -> JoinRequest:
    if not (reason or "").strip():
        raise JoinRequestError("decline reason is required")
    req = get_request(req_id, env)
    if req.state not in ("pending", "failed"):
        raise JoinRequestStateError(
            f"cannot decline request in state {req.state!r}"
        )
    req.decline_reason = reason.strip()
    _set_resolved(req, actor, "declined")
    write_request(req, env, audit_action=f"declined by @{actor.lstrip('@')}")
    _notify_safe("decision", req, env)
    return req


__all__ = [
    "JOIN_REQUESTS_SUBDIR", "VALID_KINDS", "VALID_STATES",
    "JoinRequestError", "JoinRequestNotFound", "JoinRequestStateError",
    "JoinRequest",
    "requests_dir", "request_path",
    "parse_request", "iter_requests", "get_request",
    "next_request_id", "write_request",
    "file_request", "approve", "decline",
]
