"""
Purpose: Per-core service catalog reader. Walks
         ``<lab_info>/cores/<core>/lab-mgmt/services/*.md`` and surfaces
         each entry as a :class:`ServiceSummary` the dashboard renders.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22
Input: ``<lab_info_root>/cores/<core>/lab-mgmt/services/<slug>.md`` files
       (frontmatter parsed via core.frontmatter).
Output: ``ServiceSummary`` per service for the catalog view; helper
        for one-service lookup.

A core's service catalog is the menu of bookable offerings it exposes
to the rest of the centre. Each service is one .md file at
``<lab_info>/cores/<core>/lab-mgmt/services/<slug>.md`` so all of the
existing per-core git-audit + frontmatter parsing infrastructure just
works.

This module is read-only by design. Mutation (add/edit/archive
services, change fees) flows through the registrar / core-leader
HTTP endpoints (added in Phase 2c) so each change leaves an audit-log
commit and a Slack notification.

Schema reference: ``docs/cores_plan.md §5a``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import parse_file
from .registrar import lab_info_root


SERVICES_SUBDIR = "lab-mgmt/services"   # relative to <lab_info>/cores/<core>/


@dataclass
class ServiceFee:
    """Per-service fee schedule. Money is CAD throughout wigamig."""

    unit: str = "per_run"          # per_run | per_hour | per_sample
    tiers: dict[str, float] = field(default_factory=dict)
    # Multiplicative modifiers applied on top of the tier rate.
    # Example: {"weekend": 1.25, "after_hours": 1.5}
    modifiers: dict[str, float] = field(default_factory=dict)


@dataclass
class ServiceSummary:
    """One service in a core's catalog.

    Field names follow the schema in ``docs/cores_plan.md §5a``. Optional
    fields default to None / empty container so a freshly-scaffolded
    service file doesn't need every section to render.
    """

    # Core identity
    slug: str                            # short id, matches filename stem
    name: str                            # display name (e.g. "MicroCal PEAQ-ITC")
    core: str                            # short core id (e.g. "biocore")
    # Categorisation
    capability: str = ""                 # one of the core's capabilities
    mode: str = "independent_data_collection"
    # Free-form
    description: str = ""
    body: str = ""                       # markdown body (for catalogue display)
    # Equipment block (optional but typical for instrument-backed services)
    equipment: dict[str, Any] = field(default_factory=dict)
    location: str = ""
    # Booking
    duration_default_min: int = 60       # default slot length
    duration_max_min: int = 240          # max bookable
    # Training + prereqs
    training_required: str | None = None    # references a training catalog entry
    prerequisites: list[str] = field(default_factory=list)
    # Fee schedule
    fee: ServiceFee = field(default_factory=ServiceFee)
    # Data delivery
    data_deliverable: dict[str, Any] = field(default_factory=dict)
    # Contact
    contact: dict[str, Any] = field(default_factory=dict)
    # Lifecycle
    status: str = "active"               # active | maintenance | retired
    created: str = ""
    # Where the file lives — useful for the editor to round-trip writes
    path: Path | None = None


VALID_STATUSES = ("active", "maintenance", "retired")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def core_lab_mgmt_path(core: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab_info>/cores/<core>/lab-mgmt/``.

    Resolves via the centre registrar's ``lab_info_root`` so the
    services reader doesn't reach into the registry's storage layer
    directly — callers stay decoupled from where lab_info lives on
    disk.
    """
    return lab_info_root(env) / "cores" / core / "lab-mgmt"


def services_dir(core: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab_info>/cores/<core>/lab-mgmt/services/``."""
    return core_lab_mgmt_path(core, env) / "services"


def service_path(core: str, slug: str, env: dict[str, str] | None = None) -> Path:
    """Return the canonical path to ``services/<slug>.md`` for a core."""
    return services_dir(core, env) / f"{slug}.md"


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

def _coerce_fee(raw: Any) -> ServiceFee:
    """Build a ServiceFee from a frontmatter dict. Tolerant of partial
    or absent fee blocks — the calling editor surface fills them in."""
    if not isinstance(raw, dict):
        return ServiceFee()
    tiers_raw = raw.get("tiers") or {}
    mods_raw = raw.get("modifiers") or {}
    tiers: dict[str, float] = {}
    if isinstance(tiers_raw, dict):
        for k, v in tiers_raw.items():
            try:
                tiers[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    mods: dict[str, float] = {}
    if isinstance(mods_raw, dict):
        for k, v in mods_raw.items():
            try:
                mods[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return ServiceFee(
        unit=str(raw.get("unit") or "per_run"),
        tiers=tiers,
        modifiers=mods,
    )


def iter_services(
    core: str,
    *,
    include_retired: bool = False,
    env: dict[str, str] | None = None,
) -> list[ServiceSummary]:
    """Enumerate the catalog for ``core``. Empty list if no services/ dir.

    Defensive against malformed entries: a service file that fails to
    parse is silently skipped. Sort order is by slug for stable rendering
    in the dashboard.
    """
    sdir = services_dir(core, env)
    if not sdir.is_dir():
        return []
    out: list[ServiceSummary] = []
    for entry in sorted(sdir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        try:
            parsed = parse_file(entry)
        except Exception:
            continue
        meta = parsed.meta or {}
        status = str(meta.get("status") or "active").lower()
        if status == "retired" and not include_retired:
            continue
        slug = str(meta.get("service") or entry.stem)
        out.append(ServiceSummary(
            slug=slug,
            name=str(meta.get("name") or slug),
            core=str(meta.get("core") or core),
            capability=str(meta.get("capability") or ""),
            mode=str(meta.get("mode") or "independent_data_collection"),
            description=str(meta.get("description") or "").strip(),
            body=(parsed.body or "").strip(),
            equipment=dict(meta.get("equipment") or {}),
            location=str(meta.get("location") or ""),
            duration_default_min=int(meta.get("duration_default_min") or 60),
            duration_max_min=int(meta.get("duration_max_min") or 240),
            training_required=(meta.get("training_required") or None),
            prerequisites=[str(p) for p in (meta.get("prerequisites") or [])],
            fee=_coerce_fee(meta.get("fee")),
            data_deliverable=dict(meta.get("data_deliverable") or {}),
            contact=dict(meta.get("contact") or {}),
            status=status,
            created=str(meta.get("created") or ""),
            path=entry,
        ))
    return out


def get_service(
    core: str,
    slug: str,
    *,
    env: dict[str, str] | None = None,
) -> ServiceSummary | None:
    """Single-service lookup. Returns None if missing or unparseable."""
    for s in iter_services(core, include_retired=True, env=env):
        if s.slug == slug:
            return s
    return None


# ---------------------------------------------------------------------------
# Fee quoting
# ---------------------------------------------------------------------------

def quote_fee(
    service: ServiceSummary,
    *,
    tier: str,
    modifiers: list[str] | None = None,
) -> dict[str, Any]:
    """Compute the price for booking ``service`` at ``tier``, applying
    any active modifiers.

    Returns a dict shaped for direct embedding in a booking record's
    ``fee_at_booking`` field so prices are snapshotted at booking time
    (immune to subsequent fee schedule edits).
    """
    base = service.fee.tiers.get(tier)
    if base is None:
        raise ValueError(
            f"unknown tier {tier!r} for service {service.slug!r}; "
            f"valid tiers: {sorted(service.fee.tiers)}"
        )
    mods_applied: list[dict[str, Any]] = []
    total = float(base)
    for name in (modifiers or []):
        mul = service.fee.modifiers.get(name)
        if mul is None:
            continue
        total *= float(mul)
        mods_applied.append({"name": name, "factor": float(mul)})
    return {
        "tier": tier,
        "unit": service.fee.unit,
        "base": float(base),
        "modifiers_applied": mods_applied,
        "total": round(total, 2),
    }


__all__ = [
    "SERVICES_SUBDIR",
    "VALID_STATUSES",
    "ServiceFee",
    "ServiceSummary",
    "core_lab_mgmt_path",
    "services_dir",
    "service_path",
    "iter_services",
    "get_service",
    "quote_fee",
]
