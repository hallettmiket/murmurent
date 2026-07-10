"""
Purpose: Read the lab's required-training config from
         ``<lab-mgmt>/compliance.md`` and compute each member's
         per-cert status. Powers the dashboard's training-compliance
         panel.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``<lab-mgmt>/compliance.md`` (cert catalog) and
       ``<lab-mgmt>/members/<handle>.md`` (per-member ``certifications:``).
Output: ``ComplianceConfig`` + ``MemberStatus`` dataclasses.

Member cert format::

    certifications:
      - WHM103:2027-04-01      # date-cadence cert with renewal
      - HSAW01:completed       # one-time course
      - LAS01:n/a              # not applicable to this person
      - TCPS_2:2030-12-31      # legacy format also recognised

Status values for the dashboard:

    ok        valid + not expiring within yellow_threshold_days
    expiring  valid but within yellow_threshold_days of expiry
    expired   past expiry (date in the past)
    missing   cert is required for this person but not declared
    n/a       cert exists but value is "n/a" (declined / not applicable)
    one_time  one-time cert that's been completed (no expiry)
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_file
from .repo import lab_mgmt_repo_root

COMPLIANCE_FILE = "compliance.md"
DEFAULT_YELLOW_DAYS = 60

# Hard-coded fallback when no compliance.md exists yet (fresh setup).
_DEFAULT_REQUIRED: list[dict] = [
    {"code": "WHM103",  "name": "WHMIS", "short": "whmis", "cadence_years": 3, "audience": "all"},
    {"code": "TCPS_2",  "name": "TCPS 2", "short": "tcps2", "cadence_years": 3, "audience": "clinical"},
]


@dataclass(frozen=True)
class CertSpec:
    """One required cert from compliance.md."""

    code: str
    name: str
    short: str
    cadence_years: int | None  # None = one-time
    audience: str  # all | lab | clinical | optional


@dataclass(frozen=True)
class CertStatus:
    """One member's status for one cert."""

    code: str
    status: str  # ok | expiring | expired | missing | n/a | one_time
    expires: str | None = None
    raw_value: str | None = None


@dataclass(frozen=True)
class ComplianceConfig:
    required: list[CertSpec]
    yellow_threshold_days: int = DEFAULT_YELLOW_DAYS


@dataclass(frozen=True)
class MemberStatus:
    handle: str
    full_name: str
    role: str
    member_status: str  # active | inactive
    certs: list[CertStatus] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Read config
# ---------------------------------------------------------------------------


def compliance_file() -> Path:
    return lab_mgmt_repo_root() / COMPLIANCE_FILE


def load_config() -> ComplianceConfig:
    """Read ``<lab-mgmt>/compliance.md``; fall back to a sensible default."""
    return load_config_at(compliance_file())


def load_config_at(path: Path) -> ComplianceConfig:
    """Read a compliance.md from any path.

    Phase B+ multi-lab callers (e.g. the registrar) need to read each
    lab's own compliance.md, not the single one resolved through
    ``lab_mgmt_repo_root()``. ``load_config()`` stays the
    single-lab-default entry point and now delegates here.
    """
    if not path.is_file():
        return ComplianceConfig(
            required=[CertSpec(**spec) for spec in _DEFAULT_REQUIRED],
            yellow_threshold_days=DEFAULT_YELLOW_DAYS,
        )
    parsed = parse_file(path)
    meta = parsed.meta or {}
    raw = meta.get("required") or []
    out: list[CertSpec] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                CertSpec(
                    code=str(entry["code"]),
                    name=str(entry.get("name") or entry["code"]),
                    short=str(entry.get("short") or entry["code"]).lower(),
                    cadence_years=(
                        int(entry["cadence_years"])
                        # Accept ``null``, ``~``, ``None``/``none`` — the
                        # last two are common hand-edit mistakes since
                        # users coming from Python type ``None`` rather
                        # than the YAML-correct ``null``.
                        if entry.get("cadence_years") not in (None, "null", "None", "none", "~")
                        else None
                    ),
                    audience=str(entry.get("audience") or "all"),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    yellow = int(meta.get("yellow_threshold_days") or DEFAULT_YELLOW_DAYS)
    return ComplianceConfig(required=out, yellow_threshold_days=yellow)


# ---------------------------------------------------------------------------
# Per-member status
# ---------------------------------------------------------------------------


def compute_member_status(
    *,
    handle: str,
    member_certs: list[str],
    config: ComplianceConfig,
    today: _dt.date,
) -> list[CertStatus]:
    """Match a member's declared certs against the required set.

    ``member_certs`` is the raw frontmatter list (``["WHM103:2027-...",
    ...]``). The function returns one CertStatus per cert in
    ``config.required``.
    """
    parsed: dict[str, str] = {}
    for entry in member_certs or []:
        s = str(entry)
        if ":" in s:
            code, value = s.split(":", 1)
            parsed[code.strip()] = value.strip()
        else:
            parsed[s.strip()] = ""

    out: list[CertStatus] = []
    for spec in config.required:
        raw_value = parsed.get(spec.code)
        if raw_value is None:
            # Optional certs that are missing don't read as "missing" —
            # they read as n/a (most members don't need them).
            status = "n/a" if spec.audience == "optional" else "missing"
            out.append(CertStatus(code=spec.code, status=status, raw_value=None))
            continue
        out.append(_classify(spec, raw_value, config, today))
    return out


def _classify(
    spec: CertSpec, raw: str, config: ComplianceConfig, today: _dt.date
) -> CertStatus:
    val = raw.strip().lower()
    if val in {"n/a", "na", "declined", "not_applicable"}:
        return CertStatus(code=spec.code, status="n/a", raw_value=raw)
    # One-time cert path
    if spec.cadence_years is None:
        if val in {"", "missing"}:
            return CertStatus(code=spec.code, status="missing", raw_value=raw)
        # any non-empty value reads as completed
        return CertStatus(code=spec.code, status="one_time", raw_value=raw)
    # Date-cadence path: try to parse as ISO date
    try:
        expires = _dt.date.fromisoformat(raw)
    except ValueError:
        # Pre-completed but undated — count as ok-but-cant-confirm
        return CertStatus(code=spec.code, status="missing", raw_value=raw)
    delta = (expires - today).days
    if delta < 0:
        return CertStatus(code=spec.code, status="expired",
                          expires=expires.isoformat(), raw_value=raw)
    if delta <= config.yellow_threshold_days:
        return CertStatus(code=spec.code, status="expiring",
                          expires=expires.isoformat(), raw_value=raw)
    return CertStatus(code=spec.code, status="ok",
                      expires=expires.isoformat(), raw_value=raw)
