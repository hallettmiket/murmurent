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
                       email: str = "", token: str | None = None,
                       file_content: str | None = None,
                       file_name: str = "bundle.json"):
    from . import group_reconcile as _gr
    return _gr.send_group_dm(workspace, text=text, slack=slack, email=email,
                             token=token, file_content=file_content,
                             file_name=file_name)


def _member_contact(handle: str) -> tuple[str, str]:
    """(slack, email) for ``handle`` from the roster; empty strings if unknown."""
    try:
        from . import membership as _mem
        rec = _mem.get(handle)
        return rec.slack or "", rec.email or ""
    except Exception:  # noqa: BLE001
        return "", ""


def bundle_dm_text(project: str, bundle: dict, *, kind: str = "project card") -> str:
    """The message that travels with a signed bundle. It names the trust root
    the member must pin and gives the exact command, as the lab member-card
    path always has; a member from another group has nothing pinned for this
    lab and would otherwise be stopped at import (issue #252)."""
    info = _iss.trust_root_of(bundle)
    lines = [
        f"Your murmurent {kind} for project '{project}' is ready. Your signed "
        f"bundle.json is attached to this message. Download it, then run:",
        "",
        f"    {info['import_command']}",
        "",
    ]
    if info["self_rooted"]:
        lab = f"lab '{info['lab']}'" if info["lab"] else "the lab"
        lines.append(
            f"The --trust-root part is needed once: it pins the key of the PI of "
            f"{lab}, who signed this card. {info['confirm']}")
    else:
        lines.append(info["confirm"])
    return "\n".join(lines)


def enrollment_steps_text(project: str) -> str:
    """The steps a pending member (no key on record here) needs to finish
    joining ``project``; sent by direct message when the lead records them
    (issue #252). Mirrors what the dashboard's enrollment window shows."""
    return "\n".join([
        f"You have been added to the murmurent project '{project}', but your key "
        f"is not on record here yet. To finish joining, on your own machine run:",
        "",
        f"    murmurent enroll --project {project}",
        "",
        f"and send the file it writes (enroll.json) back to the project lead, "
        f"who issues your project card with it. The card then arrives here as a "
        f"bundle.json with the command to import it. (If murmurent is not "
        f"installed yet: https://github.com/hallettmiket/murmurent, then "
        f"`murmurent init`.)",
    ])


def dm_enrollment_steps(project: str, handle: str, *, env: dict | None = None,
                        dm_sender=None) -> dict:
    """Direct-message the enrollment steps to a pending member over the
    project's workspace. The roster has no contact for someone from another
    group, so their murmurent handle is tried as a Slack name as well. Returns
    ``{"sent", "detail", "workspace"}``; never raises."""
    dm_sender = dm_sender or _default_dm_sender
    try:
        workspace, token = _cprov.resolve_project_slack(project, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "detail": str(exc), "workspace": ""}
    slack, email = _member_contact(handle)
    slack = slack or str(handle).lstrip("@")
    ok, detail = dm_sender(workspace, text=enrollment_steps_text(project),
                           slack=slack, email=email, token=token or None)
    return {"sent": bool(ok), "detail": str(detail), "workspace": workspace}


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
    text = bundle_dm_text(project, bundle, kind=kind)
    ok, detail = dm_sender(workspace, text=text, slack=slack, email=email,
                           token=token or None,
                           file_content=json.dumps(bundle, indent=2),
                           file_name="bundle.json")
    return {"sent": bool(ok), "detail": str(detail), "workspace": workspace}


def record_pending_member(project: str, handle: str, *, lab: str | None = None,
                          env: dict | None = None) -> bool:
    """Put ``handle`` on ``project``'s member list without a certificate: the
    way a lead adds someone from another group whose key this lab has never
    seen. They show as "no cert" until their enrollment request is pasted in
    (``add_member`` with ``enrollment``), which can happen any time later.
    Returns False when the project record does not exist."""
    cp = _cp.get(project, env)
    if cp is None:
        return False
    _cp.upsert(project, lab=lab or cp.lab, member=str(handle).lstrip("@"), env=env)
    return True


def add_member(project: str, handle: str, *, lab: str | None = None,
               env: dict | None = None, enrollment: dict | None = None,
               dm: bool = True, dm_sender=None, inviter=None,
               record_pending: bool = False, actor: str = "",
               open_mail: bool = False, mail_opener=None) -> dict:
    """Add ``handle`` to ``project``: the LEAD signs their project card (against
    the roster-attested pubkey, or a PoP ``enrollment`` for keyless/external
    members), the bundle is DM'd over the project's workspace, and they are
    invited to the private channel.

    Runs on the lead's machine — ``issuance`` refuses if the local key is not
    the delegated lead key (the crypto gate; HTTP authz is just the UI gate).
    Returns a structured summary; a member without a recorded key and no
    enrollment yields ``{"ok": False, "error": "no_recorded_key", ...}`` so the
    caller can fall back to the enrollment ceremony.

    ``record_pending=True`` (the dashboard's typed-handle path) also writes the
    handle onto the project record in that case, so a person from another
    group is a member of the project at once, shown as awaiting a certificate,
    and the enrollment can be finished later from their row. The reply then
    carries ``"recorded": True``.

    ``handle`` may be an email address (#258). One murmurent already knows,
    on this lab's roster or on another lab's records this machine holds,
    becomes that handle. Any other is recorded as an invitation on the
    project and the reply carries the drafted email to send
    (``{"ok": False, "error": "invited", "draft": {...}}``); ``open_mail``
    opens it in the mail client. When the enrollment later arrives, the
    handle takes the invitation's place."""
    from . import project_invites as _inv
    if _inv.is_email(handle):
        resolved = _inv.resolve_email(handle, env=env)
        if not resolved:
            try:
                out = _inv.invite(project, handle, actor=actor, env=env,
                                  open_mail=open_mail, opener=mail_opener)
            except _cp.CertProjectError as exc:
                raise ProjectMemberError(str(exc)) from exc
            return {"ok": False, "error": "invited", "handle": "", "recorded": True,
                    "dm": {"sent": False, "detail": "not attempted"}, **out}
        handle = resolved
    try:
        if enrollment is not None:
            bundle = _iss.issue_project_card_pop(handle, enrollment=enrollment,
                                                 project=project, lab=lab, env=env)
            # The person murmurent had only an email for now has a handle.
            invited_as = _inv.invited_email_of(enrollment)
            if invited_as:
                _inv.settle_invite(project, invited_as, env=env)
        else:
            bundle = _iss.issue_project_card_from_roster(handle, project=project,
                                                         lab=lab, env=env)
    except _iss.NoRecordedKey as exc:
        out = {"ok": False, "error": "no_recorded_key", "detail": str(exc),
               "handle": handle, "fallback": "enrollment", "recorded": False,
               "dm": {"sent": False, "detail": "not attempted"}}
        if record_pending:
            out["recorded"] = record_pending_member(project, handle, lab=lab, env=env)
            if out["recorded"] and dm:
                # Tell them what to do next, so the lead does not have to
                # (issue #252). Best-effort: an outsider may not be in the
                # workspace yet, and then the lead sends the steps by hand.
                out["dm"] = dm_enrollment_steps(project, handle, env=env,
                                                dm_sender=dm_sender)
        return out

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
    # Access follows membership (#255): collaborator access on every GitHub
    # repository the project lists, and the guest invite for someone from
    # another group where the workspace allows it. Both best-effort.
    try:
        out["github"] = _cprov.reconcile_github(project, env=env, remove_extras=False)
    except Exception as exc:  # noqa: BLE001
        out["github"] = {"ok": False, "error": str(exc), "problems": [str(exc)]}
    out["guests"] = None
    try:
        norm = str(handle).lstrip("@").lower()
        if norm in {h.lstrip("@").lower() for h in _cprov.outside_members(project, env=env)}:
            out["guests"] = _cprov.invite_outside_members(project, env=env)
    except Exception as exc:  # noqa: BLE001
        out["guests"] = {"ok": False, "error": str(exc)}
    return out


def _realm_and_group(project: str, cp, *, lab: str | None, env: dict | None) -> tuple[str, str]:
    """``(trust realm, <lab>/<project>)`` for the ledger. ``project_context``
    needs a PI role on this machine; a project lead who is not the PI (#255)
    has the same realm on their own card, so fall back to that."""
    try:
        return _iss.project_context(project, lab=lab or cp.lab or None, env=env)
    except _iss.IssuanceError:
        from . import identity_card as _ic
        local = _ic.local_card(env=env) or {}
        centre = str(local.get("centre") or "")
        if not centre:
            raise
        return centre, _iss.project_group(lab or cp.lab, project)


def can_sign_revocations(centre: str) -> bool:
    """True when a revocation list this machine signs verifies for ``centre``:
    it holds the centre root key, or its own key is the pinned root (a PI who
    is their own lab's root)."""
    from . import centre_root as _cr
    from . import idcert as _cert
    from . import idkeys as _k
    if _cr.have_root_key():
        return True
    if not _k.have_keys():
        return False
    try:
        pinned = _cert.load_pinned_root(centre)
        return bool(pinned) and _k.encode_public(_k.load_private().public_key()) == pinned
    except Exception:  # noqa: BLE001
        return False


def _removal_dm_text(project: str, actor: str) -> str:
    who = f"@{actor.lstrip('@')}" if actor else "the project lead"
    return (f"You have been removed from the murmurent project '{project}' by {who}. "
            f"Your access to its Slack channel and its GitHub repositories has been "
            f"taken away, and your project card no longer verifies. If this is a "
            f"mistake, ask {who} to add you again.")


def remove_member(project: str, handle: str, *, lab: str | None = None,
                  env: dict | None = None, kicker=None, actor: str = "",
                  dm: bool = True, dm_sender=None, collab_remover=None,
                  uid_resolver=None) -> dict:
    """Remove ``handle`` from ``project`` (#255): revoke their project card,
    drop them from the record, take them out of the project channel and off
    every GitHub repository the project lists, and tell them by direct message.
    Refuses to remove the LEAD: that is delete-the-project (or a future
    transfer-lead), never a silent edit.

    The card is revoked on the spot when this machine can sign the lab's
    revocation list (the PI's machine). A project lead who is not the PI
    removes the member all the same: the card id is written to the record's
    ``pending_revocations`` and the PI's machine folds it into the list on its
    next ``murmurent project reconcile``. The reply says which happened in
    ``revoked`` / ``revocation_pending``, and lists ``problems`` for whatever
    could not be done."""
    cp = _cp.get(project, env)
    if cp is None:
        raise ProjectMemberError(f"no cert-project named {project!r}")
    norm = str(handle).lstrip("@").lower()
    if cp.lead and cp.lead.lstrip("@").lower() == norm:
        raise ProjectMemberError(
            f"@{norm} is the project lead — delete the project (or transfer "
            "the lead) instead of removing them")
    problems: list[str] = []

    # 1. Revoke the card. Revoke by card_id ONLY: the fingerprint is the
    #    member's key, shared by their lab card and every other project card,
    #    so revoking it would cancel all of them. The card id is in this
    #    machine's ledger when it issued the card, and in the shared record's
    #    ``certs`` either way.
    centre, group = _realm_and_group(project, cp, lab=lab, env=env)
    entry = _rev.project_ledger(centre, group).get(norm) or {}
    card_id = entry.get("card_id") or next(
        (c.get("card_id") for c in cp.certs
         if str(c.get("handle") or "").lstrip("@").lower() == norm and c.get("card_id")), "")
    revoked = False
    pending = False
    if card_id:
        if can_sign_revocations(centre):
            _rev.revoke_with_local_key(centre, card_id=card_id)
            revoked = True
        else:
            pending = True

    # 2. Registry: drop from members + certs; note the revocation the PI must sign.
    _cp.remove_member(project, handle, env=env)
    if pending:
        import datetime as _dt
        cur = _cp.get(project, env)
        rows = [dict(r) for r in cur.pending_revocations
                if str(r.get("card_id")) != str(card_id)]
        rows.append({"handle": f"@{norm}", "card_id": card_id,
                     "by": f"@{actor.lstrip('@')}" if actor else "",
                     "at": _dt.date.today().isoformat()})
        _cp.upsert(project, lab=cur.lab, pending_revocations=rows, env=env)
        problems.append(f"@{norm}'s card is not revoked yet: this machine cannot sign "
                        f"the lab's revocation list. The PI runs `murmurent project "
                        f"reconcile {project} --apply` to finish it.")

    # 3. The person's own access: channel, every repository, and a message.
    out: dict = {"ok": True, "handle": handle, "project": project,
                 "revoked": revoked, "revocation_pending": pending,
                 "slack": None, "github": None,
                 "dm": {"sent": False, "detail": "not attempted"}, "problems": problems}
    try:
        out["slack"] = _cprov.kick_member(project, handle, env=env, kicker=kicker,
                                          uid_resolver=uid_resolver)
        if not out["slack"].get("ok") and cp.slack_channel_id:
            problems.append(f"Slack: {out['slack'].get('detail')}")
    except Exception as exc:  # noqa: BLE001
        out["slack"] = {"ok": False, "error": str(exc)}
        problems.append(f"Slack: {exc}")
    try:
        out["github"] = _cprov.remove_collaborator_everywhere(project, handle, env=env,
                                                              remover=collab_remover)
        problems += list(out["github"].get("problems") or [])
    except Exception as exc:  # noqa: BLE001
        out["github"] = {"ok": False, "error": str(exc)}
        problems.append(f"GitHub: {exc}")
    if dm:
        dm_sender = dm_sender or _default_dm_sender
        try:
            workspace, token = _cprov.resolve_project_slack(project, env=env)
            slack, email = _member_contact(handle)
            ok, detail = dm_sender(workspace, text=_removal_dm_text(project, actor),
                                   slack=slack or norm, email=email, token=token or None)
            out["dm"] = {"sent": bool(ok), "detail": str(detail), "workspace": workspace}
        except Exception as exc:  # noqa: BLE001
            out["dm"] = {"sent": False, "detail": str(exc), "workspace": ""}
        if not out["dm"]["sent"]:
            problems.append(f"@{norm} was not told by direct message ({out['dm']['detail']})")
    return out


def apply_pending_revocations(project: str, *, env: dict | None = None) -> dict:
    """On a machine that can sign the lab's revocation list, revoke every card a
    lead removed elsewhere (#255) and clear the record's ``pending_revocations``.
    Returns ``{applied: [...], pending: [...], detail}``; never raises."""
    cp = _cp.get(project, env)
    if cp is None or not cp.pending_revocations:
        return {"applied": [], "pending": [], "detail": ""}
    try:
        centre, _group = _realm_and_group(project, cp, lab=None, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"applied": [], "pending": [dict(r) for r in cp.pending_revocations],
                "detail": str(exc)}
    if not can_sign_revocations(centre):
        return {"applied": [], "pending": [dict(r) for r in cp.pending_revocations],
                "detail": "this machine cannot sign the lab's revocation list; the PI's can"}
    applied = []
    for row in cp.pending_revocations:
        if row.get("card_id"):
            _rev.revoke_with_local_key(centre, card_id=str(row["card_id"]))
        applied.append(dict(row))
    _cp.upsert(project, lab=cp.lab, pending_revocations=[], env=env)
    return {"applied": applied, "pending": [], "detail": ""}


def remove_from_all_projects(handle: str, *, env: dict | None = None, actor: str = "",
                             dm: bool = True, **seams) -> list[dict]:
    """Remove ``handle`` from every active project that lists them (#255):
    what leaving the lab means for their projects. A project they lead is
    reported, not changed. One entry per project, each the reply of
    :func:`remove_member` or ``{project, ok: False, error}``."""
    norm = str(handle).lstrip("@").lower()
    results: list[dict] = []
    for cp in _cp.projects_for_member(norm, env):
        if cp.lead and cp.lead.lstrip("@").lower() == norm:
            results.append({"project": cp.name, "ok": False,
                            "error": f"@{norm} leads {cp.name}: delete the project or "
                                     "transfer the lead first"})
            continue
        try:
            results.append(remove_member(cp.name, norm, env=env, actor=actor, dm=dm, **seams))
        except Exception as exc:  # noqa: BLE001
            results.append({"project": cp.name, "ok": False, "error": str(exc)})
    return results


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
           "create_project_certs", "bundle_dm_text", "enrollment_steps_text",
           "dm_enrollment_steps", "can_sign_revocations", "apply_pending_revocations",
           "remove_from_all_projects"]
