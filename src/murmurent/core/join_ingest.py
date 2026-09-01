"""
Purpose: Ingest join requests filed as GitHub issues on the global
         ``murmurent_public`` hub into this centre's local ``join_requests/``
         queue (Phase 2, increment 2). One-shot poll — schedule it from a
         routine/cron; each run only processes issues not seen before.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-03

Flow per run:
  1. Resolve the hub repo (``owner/repo``) + this centre's ``unique_name``
     from ``centre.md``.
  2. Fetch open issues labelled ``join-request`` from the hub.
  3. Skip any whose ``Institution`` field isn't this centre (they belong to
     a different centre) and any already ingested (dedup by the
     ``source_issue`` recorded on existing requests — robust across re-runs
     with no reliance on GitHub labels).
  4. Parse the issue-form body → {institution, kind, proposed_name,
     pi_handle, justification} and create a local join_request with
     ``source_issue = "owner/repo#N"`` and **no email** (the public form
     collects none — privacy).
  5. Comment on the issue ("received, routed as #NNNN") and best-effort
     label it. The decision is later reported back the same way via
     ``comment_decision_on_issue`` (wired from join_requests._notify_safe).

All GitHub I/O is injectable (``fetcher`` / ``commenter`` / ``labeler`` /
``closer``) so tests never shell out; the live defaults use the ``gh`` CLI.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Callable

from . import join_requests as JR
from . import centre_init as CI

log = logging.getLogger("murmurent.join_ingest")

# kind tokens we accept as centre-level join requests. "member" is a
# per-lab flow (routed to the lab's PI), not a centre registrar action.
_CENTRE_KINDS = ("lab", "core", "pi")
INGEST_LABEL = "ingested"
JOIN_LABEL = "join-request"

# Issue-form heading → our field name (headings come from
# docs/murmurent_public/.github/ISSUE_TEMPLATE/join.yml).
_FIELD_HEADINGS = {
    "institution": "institution",
    "what are you requesting?": "kind",
    "proposed name": "proposed_name",
    "pi / lead handle": "pi_handle",
    "justification": "justification",
}


class JoinIngestError(RuntimeError):
    """Ingest could not run (e.g. no hub configured)."""


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def _hub_repo(env=None) -> str:
    """Return the hub as ``owner/repo`` from ``centre.public_hub`` (which
    looks like ``github.com/owner/repo#label``), or ``""`` if unset."""
    profile = CI.read_centre(env)
    raw = (profile.public_hub if profile else "") or ""
    if not raw:
        return ""
    # Strip scheme + trailing #anchor, keep owner/repo.
    s = raw.split("#", 1)[0].strip()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^github\.com/", "", s)
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _centre_unique_name(env=None) -> str:
    profile = CI.read_centre(env)
    return (profile.install_id if profile else "").strip().lower()


# ---------------------------------------------------------------------------
# Issue-form parsing
# ---------------------------------------------------------------------------

def parse_issue_form(body: str) -> dict[str, str]:
    """Parse a rendered GitHub issue-form body (``### Heading`` blocks)
    into a {field: value} dict. Unknown headings are ignored; the GitHub
    "_No response_" placeholder maps to an empty string."""
    fields: dict[str, str] = {}
    if not body:
        return fields
    # Split into (heading, value) on '### ' section markers.
    sections = re.split(r"(?m)^###\s+", body)
    for sec in sections:
        if not sec.strip():
            continue
        line, _, rest = sec.partition("\n")
        heading = line.strip().lower()
        field = _FIELD_HEADINGS.get(heading)
        if not field:
            continue
        value = rest.strip()
        if value.lower() in ("_no response_", "_none_", ""):
            value = ""
        fields[field] = value
    return fields


def _kind_token(dropdown_value: str) -> str:
    """'lab — start a new lab (...)' → 'lab'."""
    v = (dropdown_value or "").strip().lower()
    # first alphabetic token before a space / em-dash / hyphen
    m = re.match(r"[a-z]+", v)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Live gh backends (injectable)
# ---------------------------------------------------------------------------

def _gh(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=30, check=False)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _live_fetch_issues(repo: str) -> list[dict]:
    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--label", JOIN_LABEL,
             "--state", "open", "--json", "number,title,body,url,labels",
             "--limit", "100"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if r.returncode != 0:
            log.warning("gh issue list failed: %s", r.stderr.strip())
            return []
        return json.loads(r.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log.warning("gh issue list error: %s", exc)
        return []


def _live_comment(repo: str, number: int, body: str) -> bool:
    rc, _ = _gh(["issue", "comment", str(number), "--repo", repo, "--body", body])
    return rc == 0


def _live_label(repo: str, number: int, label: str) -> bool:
    rc, _ = _gh(["issue", "edit", str(number), "--repo", repo,
                 "--add-label", label])
    return rc == 0


def _live_close(repo: str, number: int) -> bool:
    rc, _ = _gh(["issue", "close", str(number), "--repo", repo])
    return rc == 0


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

FetcherFn = Callable[[str], list[dict]]
CommenterFn = Callable[[str, int, str], bool]
LabelerFn = Callable[[str, int, str], bool]


def ingest(
    *,
    env=None,
    fetcher: FetcherFn | None = None,
    commenter: CommenterFn | None = None,
    labeler: LabelerFn | None = None,
) -> list[JR.JoinRequest]:
    """Poll the hub once and file new requests. Returns the created
    JoinRequests (empty list if nothing new). Raises JoinIngestError only
    when the centre has no hub configured; individual issue failures are
    logged and skipped, never fatal."""
    repo = _hub_repo(env)
    if not repo:
        raise JoinIngestError(
            "no public hub configured — set `public_hub` in centre.md "
            "(e.g. github.com/<org>/murmurent_public#<unique_name>)."
        )
    centre_name = _centre_unique_name(env)
    fetcher = fetcher or _live_fetch_issues
    commenter = commenter or _live_comment
    labeler = labeler or _live_label

    already = {r.source_issue for r in JR.iter_requests(env=env) if r.source_issue}
    created: list[JR.JoinRequest] = []

    for issue in fetcher(repo):
        try:
            number = int(issue.get("number"))
        except (TypeError, ValueError):
            continue
        source = f"{repo}#{number}"
        if source in already:
            continue  # dedup — already ingested on a prior run
        fields = parse_issue_form(issue.get("body") or "")

        # Route only issues addressed to THIS centre.
        inst = (fields.get("institution") or "").strip().lower()
        if centre_name and inst and inst != centre_name:
            continue  # belongs to a different centre; leave it untouched

        kind = _kind_token(fields.get("kind", ""))
        if kind not in _CENTRE_KINDS:
            # e.g. "member" — a per-lab flow. Note it and move on without
            # creating a centre request; mark seen so we don't re-comment.
            commenter(repo, number,
                      "Thanks! Member onboarding is handled by the lab's PI, "
                      "not the centre registrar — please contact the lab you "
                      "want to join directly.")
            labeler(repo, number, INGEST_LABEL)
            already.add(source)
            continue

        name = (fields.get("proposed_name") or "").strip()
        pi = (fields.get("pi_handle") or "").strip()
        if not name or (kind in ("lab", "core") and not pi):
            commenter(repo, number,
                      "This request is missing a required field (proposed "
                      "name, or PI handle for a lab/core). Please edit the "
                      "issue with the missing detail.")
            continue  # don't mark seen — let them fix + reprocess

        try:
            req = JR.file_request(
                kind=kind,
                requester_email="",             # public form collects none
                proposed_name=name,
                proposed_pi=pi,
                institution_affiliation=fields.get("institution", "") or centre_name,
                justification=fields.get("justification", ""),
                source_issue=source,
                env=env,
            )
        except JR.JoinRequestError as exc:
            log.warning("skipping issue %s: %s", source, exc)
            continue

        created.append(req)
        already.add(source)
        commenter(
            repo, number,
            f"Received — routed to the **{centre_name or 'centre'}** registrar "
            f"as join request #{req.id:04d}. The registrar will review and "
            f"follow up here.",
        )
        labeler(repo, number, INGEST_LABEL)

    return created


# ---------------------------------------------------------------------------
# Decision → comment back on the source issue
# ---------------------------------------------------------------------------

def _split_source(source_issue: str) -> tuple[str, int] | None:
    m = re.match(r"^(?P<repo>[^#]+)#(?P<n>\d+)$", (source_issue or "").strip())
    if not m:
        return None
    return m.group("repo"), int(m.group("n"))


def comment_decision_on_issue(
    req: JR.JoinRequest,
    *,
    env=None,
    commenter: CommenterFn | None = None,
    closer: Callable[[str, int], bool] | None = None,
) -> bool:
    """Best-effort: post the approve/decline outcome as a comment on the
    request's source GitHub issue, and close the issue on a terminal
    decision. Never raises. No-op if the request has no source issue."""
    parsed = _split_source(req.source_issue)
    if not parsed:
        return False
    repo, number = parsed
    commenter = commenter or _live_comment
    closer = closer or _live_close

    if req.state in ("approved", "provisioned"):
        text = (f"✅ Approved — your request was accepted by the "
                f"**{req.proposed_name}** {req.kind}. Welcome; the registrar "
                f"will follow up with next steps.")
        close = req.state == "provisioned"
    elif req.state == "declined":
        reason = f" Reason: {req.decline_reason}" if req.decline_reason else ""
        text = f"❌ Declined.{reason}"
        close = True
    elif req.state == "failed":
        text = ("⚠️ Approved, but provisioning hit a snag; the registrar is "
                "resolving it.")
        close = False
    else:
        return False

    try:
        ok = bool(commenter(repo, number, text))
        if close:
            closer(repo, number)
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("comment_decision_on_issue failed for %s: %s",
                    req.source_issue, exc)
        return False


__all__ = [
    "JoinIngestError", "ingest", "parse_issue_form",
    "comment_decision_on_issue",
]
