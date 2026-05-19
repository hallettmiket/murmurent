"""
Purpose: Consume the root-owned snapshot produced by
         ``/opt/wigamig/lab_sec_dump.sh`` (Tier 2) and emit
         :class:`Finding` rows the dashboard surfaces alongside
         Tier 1 results.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: Path to a snapshot directory on the lab server (read over the
       v3 mount; group-readable for lab members).
Output: ``list[Finding]`` covering NFSv4 ACL drift, sshd policy,
        lab-wide weak SSH keys, and auth.log anomalies.

The snapshot directory layout — see scripts/lab_sec_dump.sh:

    <snapshot_dir>/
      manifest.json       — script_version, attempts list
      acls_raw.txt        — nfs4_getfacl -R output for raw/
      acls_refined.txt    — same for refined/
      sshd_runtime.txt    — ``sshd -T`` output
      ssh_keys.jsonl      — one row per (member, key) — NO key bodies
      auth_summary.json   — per-user counts of publickey/password/failed

This module is pure-Python and side-effect-free with respect to the
snapshot. It never writes back to the snapshot dir and never proposes
mutations to /data/lab_vm/{raw,refined}.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from .security_acl import diff_raw, diff_refined, parse_nfs4_getfacl
from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SNAPSHOT,
    TIER_2,
)


SUPPORTED_SCRIPT_VERSIONS = ("1",)


@dataclass
class Tier2Result:
    findings: list[Finding] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    snapshot_age_hours: float = 0.0
    snapshot_path: str = ""


def consume_snapshot(snapshot_dir: Path, *, host: str,
                      lab_vm_root: str = "/data/lab_vm",
                      now: _dt.datetime | None = None) -> Tier2Result:
    """Read ``snapshot_dir`` and emit Tier 2 findings.

    Missing sub-files don't abort — each consumer is independent. The
    ``manifest.json`` ``attempts`` array tells the dashboard which
    sections were actually populated; we surface that as a snapshot-age
    + per-section status badge in the UI.

    ``host`` becomes the ``host`` field on every emitted Finding.
    ``lab_vm_root`` is rewritten into the suggested-fix strings so the
    PI sees paths on their v3 mount.
    """
    now = now or _dt.datetime.utcnow()
    now_iso = now.isoformat() + "Z"
    snapshot_dir = Path(snapshot_dir)
    result = Tier2Result(snapshot_path=str(snapshot_dir))

    # ----- manifest --------------------------------------------------------
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            result.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.warnings.append(f"manifest: parse failed ({exc})")
    else:
        result.warnings.append("manifest.json missing")

    script_version = str(result.manifest.get("script_version") or "")
    if script_version and script_version not in SUPPORTED_SCRIPT_VERSIONS:
        result.warnings.append(
            f"snapshot script_version={script_version!r} not supported by "
            f"this wigamig (expected one of {SUPPORTED_SCRIPT_VERSIONS}); "
            "results may be incomplete."
        )

    # Snapshot age — older than 7 days is suspicious; older than 30 days
    # gets a warn finding so the dashboard nudges the PI to re-dump.
    gen_at = result.manifest.get("generated_at")
    if gen_at:
        try:
            ts = _dt.datetime.fromisoformat(gen_at.rstrip("Z"))
            result.snapshot_age_hours = (now - ts).total_seconds() / 3600.0
        except ValueError:
            pass
    if result.snapshot_age_hours > 24 * 30:
        result.findings.append(_meta_finding(
            rule="TIER2-SNAPSHOT-STALE-01",
            severity=SEVERITY_WARN,
            host=host,
            current=f"snapshot is {result.snapshot_age_hours:.0f}h old",
            expected="< 720h (30 days)",
            fix="press 'Run sudo dump' on the security dashboard to refresh",
            now_iso=now_iso,
        ))

    # ----- ACL diffs (raw + refined) ---------------------------------------
    for kind, parser_fn in (
        ("raw", diff_raw),
        ("refined", diff_refined),
    ):
        acl_path = snapshot_dir / f"acls_{kind}.txt"
        if not acl_path.is_file():
            result.warnings.append(f"acls_{kind}.txt missing")
            continue
        try:
            text = acl_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result.warnings.append(f"acls_{kind}.txt: read failed ({exc})")
            continue
        acls = parse_nfs4_getfacl(text)
        result.findings.extend(parser_fn(
            acls, host=host, lab_vm_root=lab_vm_root, now_iso=now_iso,
        ))

    # ----- sshd policy -----------------------------------------------------
    sshd_path = snapshot_dir / "sshd_runtime.txt"
    if sshd_path.is_file():
        try:
            settings = _parse_sshd_T(sshd_path.read_text(encoding="utf-8"))
            result.findings.extend(_eval_sshd_policy(
                settings, host=host, now_iso=now_iso,
            ))
        except OSError as exc:
            result.warnings.append(f"sshd_runtime.txt: read failed ({exc})")

    # ----- ssh keys (lab-wide weak-key audit) ------------------------------
    keys_path = snapshot_dir / "ssh_keys.jsonl"
    if keys_path.is_file():
        try:
            result.findings.extend(_eval_ssh_keys(
                keys_path, host=host, now_iso=now_iso,
            ))
        except OSError as exc:
            result.warnings.append(f"ssh_keys.jsonl: read failed ({exc})")

    # ----- auth.log summary ------------------------------------------------
    auth_path = snapshot_dir / "auth_summary.json"
    if auth_path.is_file():
        try:
            summary = json.loads(auth_path.read_text(encoding="utf-8"))
            result.findings.extend(_eval_auth_summary(
                summary, host=host, now_iso=now_iso,
            ))
        except (OSError, json.JSONDecodeError) as exc:
            result.warnings.append(f"auth_summary.json: {exc}")

    return result


# ---------------------------------------------------------------------------
# sshd policy evaluation — converts ``sshd -T`` output to (key, value)
# pairs and checks the three policies we care about.
# ---------------------------------------------------------------------------

_SSHD_RECOMMENDED = {
    "passwordauthentication": "no",
    "permitrootlogin": ("no", "prohibit-password"),
    "permitemptypasswords": "no",
    "challengeresponseauthentication": "no",
    "kbdinteractiveauthentication": "no",
}


def _parse_sshd_T(text: str) -> dict[str, str]:
    """Parse ``sshd -T`` output into a lowercase-key dict.

    Lines are ``<key> <value>`` (no equals sign). Keys are returned in
    lowercase to make comparisons case-insensitive (sshd accepts both
    `PasswordAuthentication` and `passwordauthentication`).
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            out[parts[0].lower()] = parts[1].strip()
        else:
            out[parts[0].lower()] = ""
    return out


def _eval_sshd_policy(settings: dict[str, str], *, host: str,
                       now_iso: str) -> list[Finding]:
    findings: list[Finding] = []
    pw = settings.get("passwordauthentication", "?")
    if pw.lower() != "no":
        findings.append(_meta_finding(
            rule="SSHD-PWAUTH-01", severity=SEVERITY_BLOCK, host=host,
            current=f"PasswordAuthentication = {pw}",
            expected="PasswordAuthentication no",
            fix="edit /etc/ssh/sshd_config (and drop-ins) — set "
                 "'PasswordAuthentication no', then systemctl reload sshd",
            now_iso=now_iso,
        ))
    rl = settings.get("permitrootlogin", "?").lower()
    if rl not in ("no", "prohibit-password"):
        findings.append(_meta_finding(
            rule="SSHD-ROOTLOGIN-01", severity=SEVERITY_WARN, host=host,
            current=f"PermitRootLogin = {rl}",
            expected="PermitRootLogin no (or prohibit-password)",
            fix="edit /etc/ssh/sshd_config — set 'PermitRootLogin no', "
                 "then systemctl reload sshd",
            now_iso=now_iso,
        ))
    empty = settings.get("permitemptypasswords", "?").lower()
    if empty != "no":
        findings.append(_meta_finding(
            rule="SSHD-EMPTYPASSWORDS-01", severity=SEVERITY_BLOCK, host=host,
            current=f"PermitEmptyPasswords = {empty}",
            expected="PermitEmptyPasswords no",
            fix="edit /etc/ssh/sshd_config — set 'PermitEmptyPasswords no'",
            now_iso=now_iso,
        ))
    return findings


# ---------------------------------------------------------------------------
# Lab-wide SSH key audit
# ---------------------------------------------------------------------------

_WEAK_KEY_TYPES = {"ssh-rsa", "ssh-dss"}
_OLD_KEY_THRESHOLD_DAYS = 365 * 2  # 2 years


def _eval_ssh_keys(path: Path, *, host: str, now_iso: str) -> list[Finding]:
    now = _dt.datetime.fromisoformat(now_iso.rstrip("Z"))
    by_user: dict[str, list[dict]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        by_user.setdefault(row.get("user", "?"), []).append(row)

    findings: list[Finding] = []
    for user, rows in sorted(by_user.items()):
        weak = [r for r in rows if r.get("type") in _WEAK_KEY_TYPES]
        if weak:
            findings.append(_meta_finding(
                rule="AUTH-WEAK-KEYS-LAB-01",
                severity=SEVERITY_WARN,
                host=host,
                path=f"/home/.../{user}/.ssh/authorized_keys",
                current=f"{user}: {len(weak)} weak key(s) — {', '.join(r['type'] for r in weak)}",
                expected="ssh-ed25519 only",
                fix=f"ask @{user} to replace {', '.join(r['comment'] for r in weak)} with ed25519",
                now_iso=now_iso,
            ))
        # Old-key check (mtime > 2y)
        for r in rows:
            mtime_epoch = float(r.get("authorized_keys_mtime", 0) or 0)
            if mtime_epoch <= 0:
                continue
            age_days = (now.timestamp() - mtime_epoch) / 86400.0
            if age_days > _OLD_KEY_THRESHOLD_DAYS:
                findings.append(_meta_finding(
                    rule="AUTH-OLD-KEY-LAB-01",
                    severity=SEVERITY_INFO,
                    host=host,
                    path=f"/home/.../{user}/.ssh/authorized_keys",
                    current=f"{user}: authorized_keys mtime {age_days:.0f} days ago",
                    expected="key rotation < 2 years",
                    fix=f"ask @{user} to rotate keys",
                    now_iso=now_iso,
                ))
                break  # one finding per user is enough
        # authorized_keys mode != 0600
        mode = (rows[0] or {}).get("authorized_keys_mode") if rows else ""
        if mode and mode not in ("600", "400"):
            findings.append(_meta_finding(
                rule="SSH-AUTHKEYS-PERM-LAB-01",
                severity=SEVERITY_WARN,
                host=host,
                path=f"/home/.../{user}/.ssh/authorized_keys",
                current=f"{user}: authorized_keys mode = {mode}",
                expected="0600",
                fix=f"ssh {user}@<host> chmod 0600 ~/.ssh/authorized_keys",
                now_iso=now_iso,
            ))
    return findings


# ---------------------------------------------------------------------------
# auth.log summary evaluation
# ---------------------------------------------------------------------------

def _eval_auth_summary(summary: dict, *, host: str, now_iso: str) -> list[Finding]:
    findings: list[Finding] = []
    for user, stats in sorted(summary.items()):
        if not isinstance(stats, dict):
            continue
        pwd = int(stats.get("password", 0))
        failed = int(stats.get("failed", 0))
        if pwd > 0:
            findings.append(_meta_finding(
                rule="AUTH-PWD-ATTEMPTS-01",
                severity=SEVERITY_WARN,
                host=host,
                path=f"@{user}",
                current=f"{user}: {pwd} password-auth login(s) in last 30d",
                expected="publickey only",
                fix="verify whether the password-auth was intentional; "
                    "if not, lock the account or rotate password",
                now_iso=now_iso,
            ))
        if failed > 100:
            findings.append(_meta_finding(
                rule="AUTH-FAILED-BURST-01",
                severity=SEVERITY_INFO,
                host=host,
                path=f"@{user}",
                current=f"{user}: {failed} failed-auth attempts in last 30d "
                         f"from IPs {', '.join(stats.get('ips', [])[:5])}",
                expected="< 100",
                fix="review for brute-force; consider fail2ban or a "
                    "TCP-level rate limit",
                now_iso=now_iso,
            ))
    return findings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _meta_finding(*, rule: str, severity: str, host: str,
                   current: str, expected: str, fix: str, now_iso: str,
                   path: str | None = None) -> Finding:
    return Finding(
        severity=severity,
        category="sshd" if rule.startswith("SSHD") else
                 "auth" if rule.startswith("AUTH") else
                 "tier2",
        rule=rule,
        host=host,
        path=path or "(server-wide)",
        current_state=current,
        expected_state=expected,
        suggested_fix=fix,
        detected_at=now_iso,
        source=SOURCE_SNAPSHOT,
        tier=TIER_2,
        owner_handle=None,
        project=None,
        rule_doc_anchor=f"docs/security-dashboard.md#{rule}",
        notes="",
    )


__all__ = [
    "Tier2Result",
    "SUPPORTED_SCRIPT_VERSIONS",
    "consume_snapshot",
]
