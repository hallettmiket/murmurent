"""
Purpose: orchestrate project-membership changes end to end — issue/revoke the
member's project certificate, DM the bundle over the project's Slack workspace,
and keep the private project channel in sync (invite on add, kick on remove).

The crypto layer (``issuance`` / ``idcert``) is the enforcement; everything
Slack/GitHub here is best-effort with injectable seams (same philosophy as
``cert_provision``), so a missing token degrades to "certs issued, DM/pass the
bundle by hand" rather than blocking membership.

Author: Mike Hallett (with Claude Code)
Input: the cert-project registry + lab roster + this machine's signing key
       (the PI's for creation, the LEAD's for member adds).
Output: signed card bundles (DM'd when possible), updated registry, synced
        Slack channel membership.
"""

from __future__ import annotations

import json

from . import cert_projects as _cp
from . import cert_provision as _cprov
from . import issuance as _iss
from . import revocation as _rev


class ProjectMemberError(RuntimeError):
    """A project-membership change could not be completed."""


def _default_dm_sender(workspace: str, *, text: str, slack: str = "",
                       email: str = "", token: str | None = None):
    from . import group_reconcile as _gr
    return _gr.send_group_dm(workspace, text=text, slack=slack, email=email,
                             token=token)


def _member_contact(handle: str) -> tuple[str, str]:
    """(slack, email) for ``handle`` from the roster; empty strings if unknown."""
    try:
        from . import membership as _mem
        rec = _mem.get(handle)
        return rec.slack or "", rec.email or ""
    except Exception:  # noqa: BLE001
        return "", ""


def _dm_bundle(project: str, handle: str, bundle: dict, *,
               kind: str = "project card", env: dict | None = None,
               dm_sender=None) -> dict:
    """DM the signed bundle to ``handle`` over the project's Slack workspace.
    Returns ``{"sent", "detail", "workspace"}`` — never raises."""
    dm_sender = dm_sender or _default_dm_sender
    try:
        workspace, token = _cprov.resolve_project_slack(project, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "detail": str(exc), "workspace": ""}
    slack, email = _member_contact(handle)
    text = (
        f"Your murmurent {kind} for project '{project}' is ready. Save the JSON "
        f"below as bundle.json, then run:\n\n    murmurent import-card bundle.json\n\n"
        f"```\n{json.dumps(bundle, indent=2)}\n```")
    ok, detail = dm_sender(workspace, text=text, slack=slack, email=email,
                           token=token or None)
    return {"sent": bool(ok), "detail": str(detail), "workspace": workspace}


def add_member(project: str, handle: str, *, lab: str | None = None,
               env: dict | None = None, enrollment: dict | None = None,
               dm: bool = True, dm_sender=None, inviter=None) -> dict:
    """Add ``handle`` to ``project``: the LEAD signs their project card (against
    the roster-attested pubkey, or a PoP ``enrollment`` for keyless/external
    members), the bundle is DM'd over the project's workspace, and they are
    invited to the private channel.

    Runs on the lead's machine — ``issuance`` refuses if the local key is not
    the delegated lead key (the crypto gate; HTTP authz is just the UI gate).
    Returns a structured summary; a member without a recorded key and no
    enrollment yields ``{"ok": False, "error": "no_recorded_key", ...}`` so the
    caller can fall back to the enrollment ceremony."""
    try:
        if enrollment is not None:
            bundle = _iss.issue_project_card_pop(handle, enrollment=enrollment,
                                                 project=project, lab=lab, env=env)
        else:
            bundle = _iss.issue_project_card_from_roster(handle, project=project,
                                                         lab=lab, env=env)
    except _iss.NoRecordedKey as exc:
        return {"ok": False, "error": "no_recorded_key", "detail": str(exc),
                "handle": handle, "fallback": "enrollment"}

    out: dict = {"ok": True, "handle": handle, "project": project,
                 "group": bundle["group"], "bundle": bundle,
                 "dm": {"sent": False, "detail": "not attempted"},
                 "slack": None}
    if dm:
        out["dm"] = _dm_bundle(project, handle, bundle, env=env,
                               dm_sender=dm_sender)
    # Channel sync (item 8): invite the new member. Best-effort — reconcile
    # diffs the whole certified set, so a missed invite heals on the next run.
    try:
        out["slack"] = _cprov.reconcile_slack(project, env=env, inviter=inviter,
                                              remove_extras=False)
    except Exception as exc:  # noqa: BLE001
        out["slack"] = {"ok": False, "error": str(exc)}
    return out


def remove_member(project: str, handle: str, *, lab: str | None = None,
                  env: dict | None = None, kicker=None) -> dict:
    """Remove ``handle`` from ``project``: revoke their project card (CRL),
    drop them from the registry, kick them from the private channel, and drop
    their GitHub collaborator access. Refuses to remove the LEAD — that is
    delete-the-project (or a future transfer-lead), never a silent edit.

    Runs where a CRL-signing key lives (the PI's machine, or the standalone
    PI == lead case)."""
    cp = _cp.get(project, env)
    if cp is None:
        raise ProjectMemberError(f"no cert-project named {project!r}")
    norm = str(handle).lstrip("@").lower()
    if cp.lead and cp.lead.lstrip("@").lower() == norm:
        raise ProjectMemberError(
            f"@{norm} is the project lead — delete the project (or transfer "
            "the lead) instead of removing them")

    # 1. Revoke the card. The per-project ledger knows this handle's card;
    #    a member with no issued card (uncertified) has nothing to revoke.
    centre, group = _iss.project_context(project, lab=lab or cp.lab or None, env=env)
    entry = _rev.project_ledger(centre, group).get(norm) or {}   # ledger keys are bare handles
    revoked = False
    if entry.get("card_id") or entry.get("fingerprint"):
        _rev.revoke_with_local_key(centre, card_id=entry.get("card_id") or None,
                                   fingerprint=entry.get("fingerprint") or None)
        revoked = True

    # 2. Registry: drop from members + certs.
    _cp.remove_member(project, handle, env=env)

    # 3. Channel + repo sync (item 8): the reconcile diff kicks them. Best-effort.
    out: dict = {"ok": True, "handle": handle, "project": project,
                 "revoked": revoked, "slack": None, "github": None}
    try:
        out["slack"] = _cprov.reconcile_slack(project, env=env, kicker=kicker,
                                              remove_extras=True)
    except Exception as exc:  # noqa: BLE001
        out["slack"] = {"ok": False, "error": str(exc)}
    try:
        out["github"] = _cprov.reconcile_github(project, env=env)
    except Exception as exc:  # noqa: BLE001
        out["github"] = {"ok": False, "error": str(exc)}
    return out


def create_project_certs(project: str, *, lab: str, lead: str,
                         members: list[str] | None = None,
                         env: dict | None = None, dm: bool = True,
                         dm_sender=None) -> dict:
    """Certify a freshly-created project, on the PI's machine at approve time.

    The creator (``lead``) gets the project's delegation card — they control
    who joins from here on. Two shapes:

    - **creator == PI**: self-delegation; the PI's key IS the lead key, so
      every roster-keyed member gets their project card right now (DM'd).
      Members without a recorded key land in ``pending_enrollment``.
    - **creator == member**: only the LEAD card is issued (+ DM'd) — the
      lead's private key lives on THEIR machine, so member cards are theirs
      to issue (one click from their dashboard once the lead card is
      imported). Members land in ``awaiting_lead``.
    """
    from . import identity_card as _ic
    local = _ic.local_card(env=env) or {}
    pi_handle = str(local.get("netname") or "").lstrip("@").lower()
    lead_norm = str(lead or "").lstrip("@").lower()
    out: dict = {"lead": None, "issued": [], "pending_enrollment": [],
                 "awaiting_lead": [], "errors": []}

    try:
        lead_bundle = _iss.issue_project_lead_card(lead, project=project,
                                                   lab=lab or None, env=env)
    except _iss.NoRecordedKey as exc:
        out["errors"].append({"handle": lead, "error": "lead_pending_enrollment",
                              "detail": str(exc)})
        return out
    except _iss.IssuanceError as exc:
        out["errors"].append({"handle": lead, "error": "lead_card_failed",
                              "detail": str(exc)})
        return out
    lead_dm = {"sent": False, "detail": "not attempted"}
    if dm and lead_norm != pi_handle:
        # The PI's own lead card needs no DM — it is already stored locally.
        lead_dm = _dm_bundle(project, lead,
                             {"lead_card": lead_bundle["lead_card"],
                              "pi_card": lead_bundle["pi_card"]},
                             kind="project LEAD card", env=env,
                             dm_sender=dm_sender)
    out["lead"] = {"handle": lead, "dm": lead_dm}

    others = [m for m in (members or [])
              if str(m).lstrip("@").lower() != lead_norm]
    if lead_norm != pi_handle:
        # creator == member: the lead signs member cards from THEIR machine.
        out["awaiting_lead"] = [str(m) for m in others]
        return out

    for m in others:
        try:
            bundle = _iss.issue_project_card_from_roster(m, project=project,
                                                         lab=lab or None, env=env)
        except _iss.NoRecordedKey:
            out["pending_enrollment"].append(str(m))
            continue
        except _iss.IssuanceError as exc:
            out["errors"].append({"handle": str(m), "error": "issue_failed",
                                  "detail": str(exc)})
            continue
        entry = {"handle": str(m), "dm": {"sent": False, "detail": "not attempted"}}
        if dm:
            entry["dm"] = _dm_bundle(project, m, bundle, env=env,
                                     dm_sender=dm_sender)
        out["issued"].append(entry)
    return out


__all__ = ["ProjectMemberError", "add_member", "remove_member",
           "create_project_certs"]
