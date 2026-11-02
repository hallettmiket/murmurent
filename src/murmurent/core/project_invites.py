"""
Purpose: add a project member by email (#258). An email is an invitation,
         not a lookup: nothing can turn an address into a murmurent handle for
         a person murmurent has never met. So the address is first looked up
         on this lab's roster and on every other lab's records this machine
         holds; when that finds nobody, a pending invitation is recorded on
         the project and the invitation the lead sends is drafted (the enroll
         command, where to send the file, the trust root to expect). When the
         enrollment arrives, the handle takes the invitation's place.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-02
Input:   the project record, the lab roster, the registry of groups this
         machine knows, this machine's identity card.
Output:  an updated project record; a drafted email (optionally opened in the
         mail client).
"""

from __future__ import annotations

import datetime as _dt
import re
import shutil
import subprocess
import urllib.parse

from . import cert_projects as _cp

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_email(text: str) -> bool:
    """True for something that reads as an email address, not a handle."""
    return bool(_EMAIL.match(str(text or "").strip()))


def resolve_email(email: str, *, env: dict | None = None) -> str:
    """The handle murmurent knows ``email`` by: this lab's roster first, then
    every lab or core in the registry whose records are on this machine.
    Empty when nobody has that address."""
    want = str(email or "").strip().lower()
    if not want:
        return ""
    try:
        from . import membership as _mem
        for rec in _mem.iter_members():
            if str(rec.email or "").strip().lower() == want:
                return rec.handle.lstrip("@").lower()
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import registrar as _reg
        reg = _reg.read_registry(env)
        for group in [*reg.labs, *reg.cores]:
            for handle, addr in _reg.group_email_map(group.name, env=env).items():
                if str(addr).strip().lower() == want:
                    return handle.lstrip("@").lower()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _lab_and_root(env: dict | None = None) -> tuple[str, str]:
    """This machine's lab and the trust root a newcomer must pin to import a
    card signed here: the root pinned for the local card's realm."""
    try:
        from . import idcert as _cert
        from . import identity_card as _ic
        local = _ic.local_card(env=env) or {}
        realm = str(local.get("centre") or "")
        roles = local.get("roles") or []
        lab = str((roles[0] if roles else {}).get("group") or "")
        return lab, (_cert.load_pinned_root(realm) or "") if realm else ""
    except Exception:  # noqa: BLE001
        return "", ""


def invitation_text(project: str, email: str, *, actor: str = "",
                    env: dict | None = None) -> dict:
    """The invitation the lead sends: ``{subject, body, mailto}``."""
    lab, root = _lab_and_root(env)
    who = f"@{actor.lstrip('@')}" if actor else "the project lead"
    lines = [
        f"Hello,",
        "",
        f"You have been added to the murmurent project '{project}'"
        + (f" (lab {lab})" if lab else "") + f" by {who}. To finish joining:",
        "",
        "1. Install murmurent if you have not: https://github.com/hallettmiket/murmurent",
        "   then run `murmurent init` once.",
        f"2. Run:  murmurent enroll --project {project}",
        f"   and send the file it writes (enroll.json) back to {who}.",
        "3. Your signed project card comes back as a bundle.json. Import it with:",
        f"   murmurent import-card bundle.json" + (f" --trust-root {root}" if root else ""),
    ]
    if root:
        lines += [
            "   The --trust-root part is needed the first time: it pins the key of "
            + (f"lab {lab}'s PI" if lab else "the lab's PI")
            + ", who signs the card. The key above is that root; it will also be "
              "in the message that brings your card, so you can compare the two.",
        ]
    lines += ["", f"Regards,", who]
    body = "\n".join(lines)
    subject = f"Joining the murmurent project {project}"
    mailto = (f"mailto:{email}?subject={urllib.parse.quote(subject)}"
              f"&body={urllib.parse.quote(body)}")
    return {"subject": subject, "body": body, "mailto": mailto}


def open_mail_draft(mailto: str, *, opener=None) -> bool:
    """Open the draft in the mail client (macOS ``open``, Linux ``xdg-open``),
    as the join flow does. ``opener`` may be a program path or a callable
    taking the mailto link. False when there is no opener or it fails."""
    if callable(opener):
        return bool(opener(mailto))
    cmd = opener if opener is not None else (shutil.which("open") or shutil.which("xdg-open"))
    if not cmd:
        return False
    try:
        subprocess.run([cmd, mailto], check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def invite(project: str, email: str, *, actor: str = "", env: dict | None = None,
           open_mail: bool = False, opener=None) -> dict:
    """Record ``email`` as invited to ``project`` and draft the invitation.
    Idempotent: inviting the same address again refreshes the date and the
    draft. Returns ``{"invited": True, "email", "draft", "opened", "project"}``;
    raises when the project does not exist."""
    cp = _cp.get(project, env)
    if cp is None:
        raise _cp.CertProjectError(f"no cert-project named {project!r}")
    addr = str(email).strip().lower()
    rows = [dict(r) for r in cp.invited if str(r.get("email") or "").lower() != addr]
    rows.append({"email": addr, "by": f"@{actor.lstrip('@')}" if actor else "",
                 "at": _dt.date.today().isoformat()})
    _cp.upsert(project, lab=cp.lab, invited=rows, env=env)
    draft = invitation_text(project, addr, actor=actor, env=env)
    opened = open_mail_draft(draft["mailto"], opener=opener) if open_mail else False
    return {"invited": True, "project": project, "email": addr, "draft": draft,
            "opened": opened}


def invited_email_of(enrollment: dict | None) -> str:
    """The email an enrollment request carries, lower-cased, or ''."""
    if not isinstance(enrollment, dict):
        return ""
    return str((enrollment.get("payload") or {}).get("email") or "").strip().lower()


def settle_invite(project: str, email: str, *, env: dict | None = None) -> bool:
    """Drop ``email`` from the project's invitations once its owner has a
    handle on the member list. True when an invitation was there."""
    cp = _cp.get(project, env)
    if cp is None or not cp.invited:
        return False
    addr = str(email or "").strip().lower()
    kept = [dict(r) for r in cp.invited if str(r.get("email") or "").lower() != addr]
    if len(kept) == len(cp.invited):
        return False
    _cp.upsert(project, lab=cp.lab, invited=kept, env=env)
    return True


def withdraw(project: str, email: str, *, env: dict | None = None) -> bool:
    """Take an invitation back. Same as :func:`settle_invite`, named for the
    lead who changed their mind."""
    return settle_invite(project, email, env=env)


__all__ = ["is_email", "resolve_email", "invitation_text", "open_mail_draft",
           "invite", "invited_email_of", "settle_invite", "withdraw"]
