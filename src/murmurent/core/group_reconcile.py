"""Group-level member propagation — the PI's cable_guy.

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
    chat. Needs the bot's ``files:write`` scope; falls back to (False, detail)
    if it's missing, exactly like the text path."""
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
    if not channel:
        return False, "couldn't open a DM (does the bot have the im:write scope?)"
    if file_content is not None:
        ok = _sn._upload_file(channel, filename=file_name, content=file_content,
                              initial_comment=text, token=tok)
        return (ok, "sent" if ok else
                "Slack file upload failed (does the bot have the files:write scope?)")
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
        return True, "invited/added"
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
    return _gh_add_collaborator(repo, login, permission="pull", runner=runner)


def group_reconcile(
    group: str,
    *,
    env: dict[str, str] | None = None,
    token: str | None = None,
    apply: bool = False,
    workspace_checker=None,     # (email) -> bool | None
    collaborator_adder=None,    # (repo, login) -> (bool, detail)
    lab_mgmt_granter=None,      # (repo, login) -> (bool, detail), read-only grant
) -> GroupReconcileResult:
    """Diff the group roster vs the group's Slack workspace + GitHub repo.

    Slack membership is read-only (Slack can't API-add to a workspace on
    free/Pro — a person not in it is flagged so the PI emails them the invite
    link). GitHub collaborator adds only happen with ``apply=True``.

    Also ensures every roster member with a GitHub login has **read-only**
    access to the lab_mgmt roster repo (when it has a GitHub remote) — the
    grant that lets their machine pull the roster for the Lab Members panel.
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
    repo = prof.get("github", "")
    lm_repo = lab_mgmt_repo_slug()

    if not roster:
        res.slack.append("(no members on the roster yet)")
        return res
    if not lm_repo:
        res.lab_mgmt.append("(lab_mgmt has no GitHub remote — push it so members "
                            "can pull the roster; see docs/lab_mgmt.md)")

    for handle, m in sorted(roster.items()):
        email, ghlogin = m["email"], m["github"]

        # --- group Slack workspace membership (read-only) ---
        if not prof.get("slack_workspace"):
            pass  # no group workspace configured — nothing to reconcile
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
            elif not apply:
                res.lab_mgmt.append(f"@{handle} ({ghlogin}): would grant read-only "
                                    f"access to {lm_repo} (run with --apply)")
            else:
                ok, detail = grant(lm_repo, ghlogin)
                res.lab_mgmt.append(f"@{handle} ({ghlogin}): "
                                    + (f"read access to {lm_repo} ✓" if ok
                                       else "FAILED — " + detail))

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
