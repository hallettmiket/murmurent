"""Group-level member propagation — the PI's millwright.

When someone joins a group, the CENTRE side (mayor) already puts them in the
centre Slack workspace + its channel. The GROUP side — owned by the **PI** —
must put them in the group's OWN Slack workspace and its GitHub repo. That is
this module: the PI runs ``murmurent group-reconcile <group>`` and it diffs the
group roster against (a) the group's Slack workspace and (b) the group's GitHub
repo, and reports / applies the deltas.

PI-side by design: it reads the **group's own** bot token from
``~/.config/murmurent/groups/<group>/slack-token`` (never the mayor's) and the
PI's own ``gh`` for collaborator adds. All network calls go through injectable
seams so it is unit-testable without Slack/GitHub. Writes (GitHub collaborator
adds) only happen with ``apply=True``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GroupReconcileResult:
    group: str
    slack: list[str] = field(default_factory=list)     # human-readable lines
    github: list[str] = field(default_factory=list)
    lab_mgmt: list[str] = field(default_factory=list)  # read-only roster-repo access
    invite_url: str = ""
    applied: bool = False


def _group_slack_token_path(group: str) -> Path:
    return Path.home() / ".config" / "murmurent" / "groups" / group / "slack-token"


def resolve_group_slack_token(group: str, *, allow_file: bool = True) -> str:
    """The group's OWN Slack bot token: env ``MURMURENT_GROUP_SLACK_TOKEN`` first,
    then ``~/.config/murmurent/groups/<group>/slack-token`` (the PI's machine)."""
    tok = os.environ.get("MURMURENT_GROUP_SLACK_TOKEN", "").strip()
    if tok or not allow_file:
        return tok
    f = _group_slack_token_path(group)
    try:
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def write_group_slack_token(group: str, token: str) -> Path:
    """Store the group's own Slack bot token on disk, mode 0600, at the same
    path :func:`resolve_group_slack_token` reads from. Called by
    ``murmurent group-slack-setup`` once the token has been validated live —
    this is the ONLY writer for that path, so a PI has a supported way to
    hand murmurent their lab's bot token."""
    token = token.strip()
    if not token:
        raise ValueError("token is empty — refusing to write an empty slack-token file.")
    f = _group_slack_token_path(group)
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_CREAT's mode only applies to a freshly-created file, so chmod
    # afterward too — covers the re-run case where the file pre-existed
    # with looser permissions than 0600.
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    os.chmod(f, 0o600)
    return f


def group_roster(group: str, *, env: dict[str, str] | None = None) -> dict[str, dict]:
    """``{handle: {"email": ..., "github": ...}}`` for the group's active members.

    ``github`` is the member's GitHub login resolved via git_providers (from
    ``git_logins:`` or legacy ``contact.github``); "" if they haven't registered
    one.
    """
    from . import registrar as _R
    from . import git_providers as _gp
    from .frontmatter import parse_file as _pf
    reg = _R.read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == group), None)
    if entry is None or not entry.lab_mgmt_path:
        return {}
    members_dir = Path(entry.lab_mgmt_path).expanduser() / "members"
    out: dict[str, dict] = {}
    if not members_dir.is_dir():
        return out
    for mf in sorted(members_dir.glob("*.md")):
        try:
            meta = _pf(mf).meta or {}
        except Exception:  # noqa: BLE001
            continue
        if str(meta.get("status") or "active") != "active":
            continue
        handle = _R._normalize(str(meta.get("handle") or mf.stem))
        out[handle] = {
            "email": str(meta.get("email") or "").strip(),
            "github": _gp.parse_logins(meta).get("github", ""),
            "slack": str(meta.get("slack") or "").strip(),
        }
    return out


def _slack_user_exists(email: str, token: str):
    """True/False if ``email`` maps to a user in the group workspace; None on error."""
    if not (email and token):
        return None
    try:
        import httpx
        r = httpx.get("https://slack.com/api/users.lookupByEmail",
                      headers={"Authorization": f"Bearer {token}"},
                      params={"email": email}, timeout=5).json()
        if r.get("ok"):
            return True
        if r.get("error") == "users_not_found":
            return False
    except Exception:  # noqa: BLE001
        pass
    return None


def resolve_group_slack_user_id(email: str, token: str) -> str | None:
    """The Slack user id for ``email`` in the group's OWN workspace, or None
    if not found / on error. Same call as :func:`_slack_user_exists` but
    returns the id so a caller can DM them directly."""
    if not (email and token):
        return None
    try:
        import httpx
        r = httpx.get("https://slack.com/api/users.lookupByEmail",
                      headers={"Authorization": f"Bearer {token}"},
                      params={"email": email}, timeout=5).json()
        if r.get("ok"):
            return (r.get("user") or {}).get("id") or None
    except Exception:  # noqa: BLE001
        pass
    return None


def resolve_slack_id_or_name(slack: str, token: str) -> str:
    """Resolve a member's Slack handle to a user id. Accepts a raw member id
    (``U…``/``W…``, used directly) or a username / display name / real name,
    which is matched against ``users.list``. Returns "" on no match. Never
    raises."""
    import re as _re
    s = (slack or "").strip().lstrip("@")
    if not s:
        return ""
    if _re.fullmatch(r"[UW][A-Z0-9]{6,}", s):     # already a Slack member id
        return s
    target = s.lower()
    try:
        import httpx
        cursor = ""
        for _ in range(10):
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            r = httpx.get("https://slack.com/api/users.list",
                          headers={"Authorization": f"Bearer {token}"},
                          params=params, timeout=8)
            d = r.json()
            if not d.get("ok"):
                return ""
            for u in d.get("members", []):
                prof = u.get("profile", {}) or {}
                names = {str(u.get("name") or "").lower(),
                         str(prof.get("display_name") or "").lower(),
                         str(prof.get("real_name") or "").lower()}
                if target in names and not u.get("deleted"):
                    return str(u.get("id") or "")
            cursor = (d.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
    except Exception:  # noqa: BLE001
        return ""
    return ""


def send_group_dm(group: str, *, text: str, slack_user_id: str = "",
                   email: str = "", slack: str = "",
                   token: str | None = None,
                   file_content: str | None = None,
                   file_name: str = "bundle.json") -> tuple[bool, str]:
    """DM ``text`` to a member via the group's OWN Slack workspace (the token
    from :func:`resolve_group_slack_token`, or ``token`` to override).

    Resolution order for the recipient: an explicit ``slack_user_id``; then the
    member's ``slack`` handle/id (from their enrollment); then ``email`` via
    ``users.lookupByEmail``. Never raises — a Slack outage or missing token can't
    break card issuance; the caller falls back to manual delivery. Returns
    ``(ok, detail)``.

    When ``file_content`` is given it is uploaded as a real, downloadable file
    named ``file_name`` (default ``bundle.json``), with ``text`` riding along as
    the accompanying message — so a card bundle arrives as an attachment the
    member can save with one click, not as plain text they must copy out of the
    chat. Needs the bot's ``files:write`` scope.

    If the upload can't happen (most often a missing ``files:write`` scope) the
    bundle is NOT dropped: it degrades to posting the bundle inline as text so
    the member still receives it — ``(True, detail)`` where ``detail`` names the
    scope gap so the PI knows why it arrived as text and how to fix it. Only when
    BOTH the upload and the text fallback fail is ``(False, detail)`` returned."""
    from ..dashboard import slack_notify as _sn

    tok = token if token is not None else resolve_group_slack_token(group)
    if not tok:
        return False, (f"no Slack token for '{group}' — run "
                        f"`murmurent group-slack-setup {group}` first")

    uid = slack_user_id
    if not uid and slack:
        uid = resolve_slack_id_or_name(slack, tok)
    if not uid:
        if not email and not slack:
            return False, "no Slack handle or email on file — can't resolve their Slack account"
        if email:
            uid = resolve_group_slack_user_id(email, tok)
        if not uid:
            who = slack or email
            return False, f"couldn't find {who} in the group's Slack workspace"

    channel = _sn._open_dm(uid, tok)
    if not channel and email and not slack_user_id:
        # The Slack id in an enrollment often belongs to the member's account
        # in another workspace (user_not_found here). Their email finds the
        # account in this one.
        by_email = resolve_group_slack_user_id(email, tok)
        if by_email and by_email != uid:
            channel = _sn._open_dm(by_email, tok)
    if not channel:
        return False, "couldn't open a DM (does the bot have the im:write scope?)"
    if file_content is not None:
        up = _sn._upload_file(channel, filename=file_name, content=file_content,
                              initial_comment=text, token=tok)
        if up.ok:
            return True, "sent"
        # Graceful degradation: the upload failed. Rather than deliver nothing,
        # post the bundle inline as text so the member still receives it — never
        # lose the bundle (#13) — and surface the *actual* Slack error (which
        # step failed + its code) so the PI knows precisely why it arrived as
        # text and how to fix it, instead of a generic "probably a missing
        # scope" guess (#22).
        why = _sn.upload_error_hint(up)
        fallback = (
            f"{text}\n\n"
            f"(Couldn't attach {file_name} as a downloadable file. Copy "
            f"everything between the ``` fences below into a file named "
            f"{file_name}.)\n```\n{file_content}\n```")
        if _sn._post(channel, fallback, token=tok):
            return True, (
                f"sent as inline text — {why}. The bundle is in the message; "
                f"fix the upload for a downloadable {file_name} attachment "
                f"next time.")
        return False, (f"Slack file upload failed ({why}) and the inline-text "
                       f"fallback ALSO failed (missing chat:write scope?) — "
                       f"send the bundle to the member by hand")
    ok = _sn._post(channel, text, token=tok)
    return (ok, "sent" if ok else "Slack post failed")


def _gh_add_collaborator(repo: str, login: str, *, permission: str | None = None,
                         runner=subprocess.run):
    """PUT repos/{repo}/collaborators/{login} via gh. Returns (ok, detail).

    ``permission=None`` keeps GitHub's default for the endpoint (push) —
    right for project repos members contribute to. Pass ``"pull"`` for
    read-only access (the lab_mgmt roster repo).
    """
    if not (repo and login):
        return False, "missing repo or login"
    cmd = ["gh", "api", "-X", "PUT", f"repos/{repo}/collaborators/{login}"]
    if permission:
        cmd += ["-f", f"permission={permission}"]
    proc = runner(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, "invited (read-only)" if permission == "pull" else "invited/added"
    detail = (proc.stderr or proc.stdout or "gh error").strip().splitlines()
    return False, (detail[0][:120] if detail else "gh error")


def lab_mgmt_repo_slug() -> str:
    """``owner/name`` of the lab_mgmt roster repo on GitHub, from the local
    clone's ``origin`` URL. '' when there's no clone, no remote, or a
    non-GitHub remote — callers treat that as "nothing to reconcile".
    """
    from .repo import lab_mgmt_repo_root
    root = lab_mgmt_repo_root()
    if not (root / ".git").exists():
        return ""
    try:
        proc = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    url = proc.stdout.strip()
    for prefix in ("git@github.com:", "https://github.com/",
                   "http://github.com/", "ssh://git@github.com/"):
        if url.startswith(prefix):
            slug = url[len(prefix):]
            return slug[:-4] if slug.endswith(".git") else slug
    return ""


def grant_lab_mgmt_read(login: str, *, repo: str = "", runner=subprocess.run):
    """Give ``login`` read-only (pull) access to the lab_mgmt roster repo.

    This is what lets a member's machine clone/pull the roster — the GH
    side of the Lab Members panel. Read-only on purpose: the PI stays the
    only writer, so member-side ``git pull --ff-only`` can never conflict.
    Returns (ok, detail); (False, reason) when no repo is resolvable.
    """
    repo = repo or lab_mgmt_repo_slug()
    if not repo:
        return False, "lab_mgmt has no GitHub remote — push it first (see docs/lab_mgmt.md)"
    # The repo owner (usually the PI) can't be invited to their own repo —
    # GitHub rejects it with a 422. They already have full access.
    owner = repo.split("/", 1)[0]
    login = login.strip().lstrip("@")
    if login.lower() == owner.lower():
        return True, "repo owner — already has full access"
    ok, detail = _gh_add_collaborator(repo, login, permission="pull", runner=runner)
    if ok or "cannot assign" not in detail.lower():
        return ok, detail
    # A repository owned by a personal account (not an organisation) refuses
    # ``permission=pull`` from the API with "Cannot assign <login> permission
    # of read", even for a member who already has read-only access; the web
    # page allows it, the API does not. The fallback is to invite with the
    # default (write) permission and then set the pending invitation to
    # read-only, which the invitations endpoint does accept.
    return _grant_via_invitation(repo, login, runner=runner)


def _grant_via_invitation(repo: str, login: str, *, runner=subprocess.run):
    """Invite ``login`` with GitHub's default permission, then turn the
    pending invitation read-only. Returns (ok, detail); ``detail`` says
    plainly when the member ended up with write access instead."""
    import json
    try:
        proc = runner(["gh", "api", "-X", "PUT", f"repos/{repo}/collaborators/{login}"],
                      capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "gh error").strip().splitlines()
        return False, (err[0][:120] if err else "gh error")
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        body = None
    inv_id = (body or {}).get("id") if isinstance(body, dict) else None
    if not inv_id:
        # 204: already a collaborator. The API cannot change an existing
        # collaborator's permission on a personal-account repo.
        return True, "already a collaborator (write)"
    try:
        patch = runner(["gh", "api", "-X", "PATCH", f"repos/{repo}/invitations/{inv_id}",
                        "-f", "permissions=read"], capture_output=True, text=True)
        downgraded = patch.returncode == 0
    except (OSError, subprocess.SubprocessError):
        downgraded = False
    if downgraded:
        return True, "invited (read-only)"
    return True, "invited (write)"


# ---------------------------------------------------------------------------
# Invitation tracking. A collaborator PUT creates an *invitation*, which the
# member must accept within seven days; GitHub neither resends nor reports it
# unless asked. Reading the repo's invitations alongside its collaborators is
# what tells the PI "invited, not accepted" apart from "has access".
# ---------------------------------------------------------------------------

INVITATION_DAYS = 7   # GitHub expires an unaccepted repository invitation after this


def _gh_json(args: list[str], *, runner=subprocess.run):
    """Run ``gh api`` and parse its JSON. ``None`` on any failure."""
    import json
    try:
        proc = runner(["gh", "api", *args], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except ValueError:
        return None


def lab_mgmt_access_state(repo: str, *, runner=subprocess.run) -> dict | None:
    """Who can actually read ``repo`` right now, and who is still only invited.

    Returns ``{"collaborators": {login, ...}, "invitations": {login: inv}}``
    where each ``inv`` is ``{"id", "created_at", "expired", "url"}`` (logins
    lowercased), or ``None`` when GitHub could not be asked (``gh`` missing or
    not signed in as someone who can read the repo's invitations). Callers
    treat ``None`` as "unknown", never as "nobody has access".
    """
    if not repo:
        return None
    collabs = _gh_json([f"repos/{repo}/collaborators", "--paginate"], runner=runner)
    invites = _gh_json([f"repos/{repo}/invitations", "--paginate"], runner=runner)
    if not isinstance(collabs, list) or not isinstance(invites, list):
        return None
    state = {"collaborators": set(), "invitations": {}, "roles": {}}
    for c in collabs:
        login = str((c or {}).get("login") or "").lower()
        if login:
            state["collaborators"].add(login)
            state["roles"][login] = str((c or {}).get("role_name") or "")
    for inv in invites:
        login = str(((inv or {}).get("invitee") or {}).get("login") or "").lower()
        if not login:
            continue
        state["invitations"][login] = {
            "id": inv.get("id"),
            "created_at": str(inv.get("created_at") or ""),
            "expired": bool(inv.get("expired")),
            "url": str(inv.get("html_url") or f"https://github.com/{repo}/invitations"),
        }
    return state


def _invitation_age_days(created_at: str) -> int | None:
    from datetime import datetime, timezone
    try:
        made = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - made).days)


def describe_member_access(login: str, state: dict | None) -> tuple[str, str]:
    """Classify one member's access from :func:`lab_mgmt_access_state`.

    Returns ``(kind, detail)`` with ``kind`` one of ``"access"`` (accepted
    collaborator), ``"pending"`` (invited, not yet accepted), ``"expired"``
    (invited, never accepted, now dead), ``"none"`` (never invited, or the
    invitation was declined) or ``"unknown"`` (GitHub could not be asked).
    """
    if state is None:
        return "unknown", "GitHub could not be asked (is `gh` signed in as the repo owner?)"
    key = login.strip().lstrip("@").lower()
    if key in state["collaborators"]:
        role = (state.get("roles") or {}).get(key, "")
        if role and role not in ("read", "pull"):
            return "access", f"has {role} access"
        return "access", "has read access"
    inv = state["invitations"].get(key)
    if inv is None:
        return "none", "not invited"
    age = _invitation_age_days(inv["created_at"])
    if inv["expired"] or (age is not None and age >= INVITATION_DAYS):
        return "expired", (f"invitation sent {age} days ago was never accepted and has "
                           f"expired" if age is not None else "invitation has expired")
    left = INVITATION_DAYS - age if age is not None else None
    when = (f"sent {age} days ago, expires in {left} day{'s' if left != 1 else ''}"
            if age is not None else "sent")
    return "pending", f"invitation {when}, not yet accepted: {inv['url']}"


def _gh_delete_invitation(repo: str, invitation_id, *, runner=subprocess.run) -> bool:
    if not (repo and invitation_id):
        return False
    try:
        proc = runner(["gh", "api", "-X", "DELETE",
                       f"repos/{repo}/invitations/{invitation_id}"],
                      capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def resend_lab_mgmt_invitation(login: str, state: dict, *, repo: str = "",
                               runner=subprocess.run) -> tuple[bool, str]:
    """Drop ``login``'s expired invitation to the records repo and send a new
    one. GitHub keeps an expired invitation on the books, and a fresh PUT just
    returns it, so it has to be deleted first."""
    repo = repo or lab_mgmt_repo_slug()
    inv = (state or {}).get("invitations", {}).get(login.strip().lstrip("@").lower())
    if inv and not _gh_delete_invitation(repo, inv.get("id"), runner=runner):
        return False, "could not remove the expired invitation"
    return grant_lab_mgmt_read(login, repo=repo, runner=runner)


def records_clone_command(slug: str, group: str) -> str:
    """The one command that puts the records repo where murmurent looks.

    ``gh repo clone`` rather than ``git clone git@github.com:...``: it uses
    whatever protocol the member signed in to ``gh`` with, so a member who
    followed the setup guide (HTTPS) is not sent an SSH URL that fails with
    "Permission denied (publickey)" and looks like a missing invitation.
    """
    from . import repo as _repo
    if not slug:
        return ""
    return (f"gh repo clone {slug} "
            f"{_repo.repos_root_for_display()}/{_repo.lab_repo_path(group).name}")


def invitation_nudge_text(group: str, slug: str, access_url: str) -> str:
    """The DM a member gets while their records-repo invitation sits unaccepted."""
    return (f"Your invitation to the '{group}' lab records repository "
            f"({slug}) on GitHub has not been accepted yet. Accept it here:\n"
            f"    {access_url}\n"
            f"then clone the records:\n"
            f"    {records_clone_command(slug, group)}\n"
            f"Until then your dashboard cannot see the lab's members, projects "
            f"or oracle. Not sure which GitHub account was invited? Run "
            f"`murmurent doctor`.")


def records_access_for_new_member(github_login: str, group: str, *,
                                  granter=None) -> dict:
    """Give a freshly carded member read access to the lab records repo on
    GitHub, and say exactly what they should run next (#232).

    Returns ``{"ok", "detail", "repo", "clone_command"}``. ``ok`` is False
    when the login is missing, the records repo is not on GitHub, or GitHub
    refused; ``detail`` says which, and names ``murmurent group-reconcile
    <group> --apply`` as the way to grant it later. ``clone_command`` is set
    whenever the repo is on GitHub, since the member still needs it.
    """
    grant = granter or (lambda login: grant_lab_mgmt_read(login))
    slug = lab_mgmt_repo_slug()
    later = f"grant it later with:  murmurent group-reconcile {group} --apply"
    clone = records_clone_command(slug, group)
    login = (github_login or "").strip().lstrip("@")
    if not slug:
        return {"ok": False, "repo": "", "clone_command": "",
                "detail": ("the lab records repo is not on GitHub yet, so the member "
                           "cannot be given access to it; push it first (see "
                           "docs/lab_mgmt.md), then " + later)}
    if not login:
        return {"ok": False, "repo": slug, "clone_command": clone,
                "detail": ("the member gave no GitHub username at `murmurent init`, "
                           "so they cannot be invited to the lab records; ask them "
                           "for it, add it to their roster record, then " + later)}
    try:
        ok, detail = grant(login)
    except Exception as exc:  # noqa: BLE001 - a GitHub hiccup must not undo the card
        ok, detail = False, str(exc)
    if not ok:
        detail = f"GitHub did not accept the invitation for {login}: {detail}; {later}"
    else:
        detail = (f"{login} invited to {slug} (read-only): {detail}. They must accept "
                  f"the invitation within {INVITATION_DAYS} days (GitHub email, or "
                  f"https://github.com/{slug}/invitations); `murmurent group-reconcile "
                  f"{group}` shows whether they have")
    return {"ok": bool(ok), "repo": slug, "clone_command": clone, "detail": detail}


def _note_write(res: "GroupReconcileResult", repo: str) -> None:
    """One line, once per run, on why a member has write rather than read."""
    url = f"https://github.com/{repo}/settings/access"
    if any(url in line for line in res.lab_mgmt):
        return
    res.lab_mgmt.append(f"    (a personal-account repo cannot grant read-only through the API; "
                        f"after they accept, set members to Read at {url})")


def _reconcile_records_access(res: "GroupReconcileResult", *, handle: str, login: str,
                              member: dict, repo: str, group: str, access: dict | None,
                              apply: bool, grant, resend, dm) -> None:
    """One member's line(s) in the lab_mgmt section, and the writes behind them."""
    kind, detail = describe_member_access(login, access)
    who = f"@{handle} ({login})"
    if kind == "access":
        if detail == "has read access":
            res.lab_mgmt.append(f"{who}: read access ✓")
        else:
            res.lab_mgmt.append(f"{who}: {detail} ✓ (more than read-only)")
            _note_write(res, repo)
        return
    if kind == "pending":
        res.lab_mgmt.append(f"{who}: {detail}")
        if apply:
            url = (access["invitations"].get(login.lower()) or {}).get("url", "")
            ok, why = dm(member, invitation_nudge_text(group, repo, url))
            res.lab_mgmt.append(f"    reminder DM {'sent ✓' if ok else 'not sent — ' + why}")
        return
    if kind == "expired":
        if not apply:
            res.lab_mgmt.append(f"{who}: {detail} (run with --apply to resend it)")
            return
        ok, why = resend(repo, login, access)
        res.lab_mgmt.append(f"{who}: {detail}; "
                            + ("resent ✓" if ok else "resend FAILED — " + why))
        if ok:
            ok2, why2 = dm(member, invitation_nudge_text(
                group, repo, f"https://github.com/{repo}/invitations"))
            res.lab_mgmt.append(f"    reminder DM {'sent ✓' if ok2 else 'not sent — ' + why2}")
        return
    # "none" (never invited, or declined) and "unknown" (GitHub unreadable)
    if not apply:
        res.lab_mgmt.append(f"{who}: would grant read-only access to {repo} "
                            "(run with --apply)")
        return
    ok, why = grant(repo, login)
    if not ok:
        res.lab_mgmt.append(f"{who}: FAILED — {why}")
        return
    res.lab_mgmt.append(f"{who}: {why} ✓ — accept within {INVITATION_DAYS} days")
    if "write" in why:
        _note_write(res, repo)
    ok2, why2 = dm(member, invitation_nudge_text(
        group, repo, f"https://github.com/{repo}/invitations"))
    res.lab_mgmt.append(f"    invitation DM {'sent ✓' if ok2 else 'not sent — ' + why2}")


def group_reconcile(
    group: str,
    *,
    env: dict[str, str] | None = None,
    token: str | None = None,
    apply: bool = False,
    workspace_checker=None,     # (email) -> bool | None
    collaborator_adder=None,    # (repo, login) -> (bool, detail)
    lab_mgmt_granter=None,      # (repo, login) -> (bool, detail), read-only grant
    access_fetcher=None,        # (repo) -> state dict | None, see lab_mgmt_access_state
    invitation_resender=None,   # (repo, login, state) -> (bool, detail)
    dm_sender=None,             # (member dict, text) -> (bool, detail)
) -> GroupReconcileResult:
    """Diff the group roster vs the group's Slack workspace + GitHub repo.

    Slack membership is read-only (Slack can't API-add to a workspace on
    free/Pro — a person not in it is flagged so the PI emails them the invite
    link). GitHub collaborator adds only happen with ``apply=True``.

    Also ensures every roster member with a GitHub login has **read-only**
    access to the lab_mgmt roster repo (when it has a GitHub remote) — the
    grant that lets their machine pull the roster for the Lab Members panel.
    A grant is only an invitation, so each member is reported as one of: has
    access, invited but not yet accepted (with the accept link), invitation
    expired (``--apply`` resends it), or never invited. With ``--apply`` and
    a group Slack token, a member whose invitation is waiting is sent the
    accept link by DM.
    """
    from . import registrar as _R
    prof = _R.read_group_profile(group, env=env)
    roster = group_roster(group, env=env)
    res = GroupReconcileResult(group=group, invite_url=prof.get("slack_invite_url", ""),
                               applied=apply)
    tok = token if token is not None else resolve_group_slack_token(group)
    check = workspace_checker or (lambda email: _slack_user_exists(email, tok))
    add = collaborator_adder or (lambda repo, login: _gh_add_collaborator(repo, login))
    grant = lab_mgmt_granter or (lambda repo, login: grant_lab_mgmt_read(login, repo=repo))
    fetch_access = access_fetcher or lab_mgmt_access_state
    resend = invitation_resender or (
        lambda repo, login, state: resend_lab_mgmt_invitation(login, state, repo=repo))
    if dm_sender is None:
        def dm_sender(member: dict, text: str) -> tuple[bool, str]:
            if not tok:
                return False, "no group Slack token"
            return send_group_dm(group, text=text, token=tok,
                                 slack=(member.get("slack") or ""),
                                 email=(member.get("email") or ""))
    repo = prof.get("github", "")
    lm_repo = lab_mgmt_repo_slug()

    if not roster:
        res.slack.append("(no members on the roster yet)")
        return res
    access = None
    if not lm_repo:
        res.lab_mgmt.append("(lab_mgmt has no GitHub remote — push it so members "
                            "can pull the roster; see docs/lab_mgmt.md)")
    else:
        access = fetch_access(lm_repo)
        if access is None:
            res.lab_mgmt.append(f"(could not read who has access to {lm_repo}: `gh` must "
                                "be signed in as the repo owner; grants below are sent "
                                "blind and acceptance cannot be checked)")

    for handle, m in sorted(roster.items()):
        email, ghlogin = m["email"], m["github"]
        slack_id = (m.get("slack") or "").strip()

        # --- group Slack workspace membership (read-only) ---
        if not prof.get("slack_workspace"):
            pass  # no group workspace configured — nothing to reconcile
        elif slack_id:
            # A recorded Slack user id IS proof of workspace membership — you
            # only get a ``U…`` id for a member of the workspace. Trust it and
            # do NOT email-lookup or tell the PI to "invite" someone we can DM.
            res.slack.append(f"@{handle}: in the group workspace ✓ (slack {slack_id})")
        elif not tok:
            res.slack.append(f"@{handle}: no group Slack token "
                             "(~/.config/murmurent/groups/{}/slack-token) — skipped".format(group))
        elif not email:
            res.slack.append(f"@{handle}: no email on file — can't check workspace membership")
        else:
            inw = check(email)
            if inw is True:
                res.slack.append(f"@{handle}: in the group workspace ✓")
            elif inw is False:
                res.slack.append(f"@{handle}: NOT in the group workspace — send them the invite link")
            else:
                res.slack.append(f"@{handle}: workspace lookup failed (check the token/scopes)")

        # --- lab_mgmt roster repo: read-only access for every member ---
        if lm_repo:
            if not ghlogin:
                res.lab_mgmt.append(f"@{handle}: no GitHub login on file — "
                                    "they need to register one")
            elif ghlogin.lower() == lm_repo.split("/", 1)[0].lower():
                res.lab_mgmt.append(f"@{handle} ({ghlogin}): owns {lm_repo} ✓")
            else:
                _reconcile_records_access(
                    res, handle=handle, login=ghlogin, member=m, repo=lm_repo,
                    group=group, access=access, apply=apply, grant=grant,
                    resend=resend, dm=dm_sender)

        # --- group GitHub repo collaborator ---
        if not repo:
            continue
        if not ghlogin:
            res.github.append(f"@{handle}: no GitHub login on file — they need to register one")
        elif not apply:
            res.github.append(f"@{handle} ({ghlogin}): would add to {repo} (run with --apply)")
        else:
            ok, detail = add(repo, ghlogin)
            res.github.append(f"@{handle} ({ghlogin}): "
                              + ("added to " + repo + " ✓" if ok else "FAILED — " + detail))
    return res
