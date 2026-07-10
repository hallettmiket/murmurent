"""PI onboarding tracker + step-by-step DM reporter.

After a lab/core is approved and the PI is emailed the workspace invite, the
mayor runs ``murmurent onboard-check``. For each group whose PI has not been
onboarded yet it looks the PI up in the Slack workspace by email; once they have
joined it (a) adds them to the group's channel, (b) DMs them a step-by-step
acknowledgement (registrar -> cable_guy -> security_guard -> dashboard), and
(c) marks them onboarded so it never double-reports.

Polling by design: no Slack Events webhook to stand up. The mayor runs the
command (or a cron does) and it converges. Everything Slack is token-gated +
best-effort + injectable so the token-less test suite never hits the wire.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def _state_dir() -> Path:
    return _home() / "onboarding"


def _state_path(group: str) -> Path:
    return _state_dir() / f"{group}.json"


def is_pi_onboarded(group: str) -> bool:
    """True once the PI of ``group`` has been welcomed + wired into the channel."""
    p = _state_path(group)
    try:
        if p.is_file():
            return bool(json.loads(p.read_text(encoding="utf-8")).get("pi_onboarded_at"))
    except Exception:  # noqa: BLE001
        pass
    return False


def mark_pi_onboarded(group: str, *, when: str | None = None) -> None:
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = when or (_dt.datetime.now(_dt.timezone.utc).isoformat())
    _state_path(group).write_text(
        json.dumps({"group": group, "pi_onboarded_at": stamp}, indent=2),
        encoding="utf-8",
    )


@dataclass
class OnboardCheckResult:
    group: str
    pi: str = ""
    email: str = ""
    joined: bool = False          # PI is present in the Slack workspace
    added_to_channel: bool = False
    dmed: bool = False
    note: str = ""


def _active_groups(env):
    from . import registrar as _R
    reg = _R.read_registry(env)
    out = []
    for g in [*reg.labs, *reg.cores]:
        if str(getattr(g, "status", "active")) == "active":
            out.append((g.name, getattr(g, "pi", "")))
    return out


def _pi_email(group: str, pi: str, env) -> str:
    """The PI's email from the group's member file (written at lab creation)."""
    from . import group_reconcile as _gr
    from . import registrar as _R
    roster = _gr.group_roster(group, env=env)
    norm = _R._normalize(pi)
    return (roster.get(norm, {}) or {}).get("email", "") or ""


def run_onboard_check(
    group: str | None = None,
    *,
    env: dict[str, str] | None = None,
    token: str | None = None,
    workspace_checker=None,      # (email) -> bool | None
    channel_adder=None,          # (group, handle, email) -> bool
    dm_sender=None,              # (group, email) -> bool
) -> list[OnboardCheckResult]:
    """Converge onboarding for one group (or every active group).

    For each not-yet-onboarded group: resolve the PI's email, check whether they
    are in the workspace, and — once they are — add them to the group channel,
    DM the step-by-step acknowledgement, and mark them onboarded.
    """
    from . import centre_provision as _cp

    tok = token if token is not None else _cp.resolve_slack_token(allow_file=True)

    def _default_ws_check(email: str):
        from . import group_reconcile as _gr
        return _gr._slack_user_exists(email, tok)

    def _default_channel_adder(grp: str, handle: str, email: str) -> bool:
        probes = _cp.provision_member_to_group(
            grp, handle=handle, email=email, env=env, token=tok or None)
        return any(p.status == "ok" for p in probes)

    def _default_dm(grp: str, email: str) -> bool:
        from . import join_notify as _jn
        return _jn.notify_pi_onboarded(grp, email=email, env=env,
                                       channel_name=_channel_name(grp))

    ws_check = workspace_checker or _default_ws_check
    add_ch = channel_adder or _default_channel_adder
    send_dm = dm_sender or _default_dm

    groups = ([(group, _pi_of(group, env))] if group
              else _active_groups(env))
    results: list[OnboardCheckResult] = []
    for name, pi in groups:
        res = OnboardCheckResult(group=name, pi=pi)
        if is_pi_onboarded(name):
            res.joined = True
            res.note = "already onboarded"
            results.append(res)
            continue
        email = _pi_email(name, pi, env)
        res.email = email
        if not email:
            res.note = "no PI email on file — can't check workspace membership"
            results.append(res)
            continue
        inw = ws_check(email)
        if inw is None:
            res.note = "workspace lookup unavailable (no token / lookup failed)"
            results.append(res)
            continue
        if inw is False:
            res.note = "waiting — PI hasn't accepted the workspace invite yet"
            results.append(res)
            continue
        # PI is in the workspace → wire them up + welcome them.
        res.joined = True
        res.added_to_channel = bool(add_ch(name, pi, email))
        res.dmed = bool(send_dm(name, email))
        mark_pi_onboarded(name)
        res.note = "onboarded ✓ (added to channel + DM sent)" if res.dmed \
            else "PI is in the workspace; channel updated (DM skipped — no token?)"
        results.append(res)
    return results


def _pi_of(group: str, env) -> str:
    from . import registrar as _R
    reg = _R.read_registry(env)
    g = next((x for x in [*reg.labs, *reg.cores] if x.name == group), None)
    return getattr(g, "pi", "") if g else ""


def _channel_name(group: str) -> str:
    try:
        from ..dashboard import slack_notify as _sn
        return _sn.normalize_channel_name(group) or group
    except Exception:  # noqa: BLE001
        return group


__all__ = [
    "OnboardCheckResult", "run_onboard_check",
    "is_pi_onboarded", "mark_pi_onboarded",
]
