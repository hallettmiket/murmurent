"""
Purpose: Resolve a ``requester_lab`` string to its source — a known
         lab in the centre registrar, an external customer file, or
         unknown — so booking + invoicing know how to bill and where
         to deliver data.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

The booking endpoint stamps ``requester_lab`` on every service
request. Today that's mostly the calling user's own lab. As cores
accept bookings from cross-lab + external clients, ``requester_lab``
becomes a routing key — the invoice generator needs to know whether
to assemble a Western lab-fund invoice or an external PO invoice;
the data-delivery MCP needs to know which group ACL to grant.

Resolution rules:

  1. Local lab match: ``load_lab_config().lab == requester_lab`` →
     ``lab`` (this is the most common path today).
  2. Centre registrar lab match: any ``LabEntry.name`` in the centre
     ``_registry.yaml`` → ``lab``.
  3. External-customer file match:
     ``<lab_mgmt>/external_customers/<requester_lab>.md`` → ``external``.
  4. Otherwise → ``unknown`` (caller decides whether to refuse or
     proceed with a warning).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import external_customers as _ext
from . import lab as _lab
from . import registrar as _reg


KIND_LAB = "lab"
KIND_EXTERNAL = "external"
KIND_UNKNOWN = "unknown"


@dataclass
class LabResolution:
    """Outcome of resolving a ``requester_lab`` string."""

    name: str                              # normalised lookup key
    kind: str                              # KIND_LAB | KIND_EXTERNAL | KIND_UNKNOWN
    display_name: str = ""                 # human-readable
    pi_or_contact: str = ""                # @handle for labs; email for external
    source_path: str = ""                  # where the resolution came from
    billing_meta: dict[str, Any] = field(default_factory=dict)


def resolve(
    requester_lab: str,
    *, env: dict[str, str] | None = None,
) -> LabResolution:
    """Look up ``requester_lab`` in the lab roster + external customers.
    Always returns a LabResolution; ``kind`` flags how the caller
    should treat it."""
    raw = (requester_lab or "").strip().lower()
    if not raw:
        return LabResolution(name="", kind=KIND_UNKNOWN)

    # 1) local lab.md
    try:
        local = _lab.load_lab_config()
        if (local.lab or "").lower() == raw:
            return LabResolution(
                name=raw, kind=KIND_LAB,
                display_name=local.name or raw,
                pi_or_contact=f"@{local.pi}" if local.pi else "",
                source_path=str(local.path) if local.path else "",
            )
    except Exception:
        pass

    # 2) centre registrar lab entries
    try:
        reg = _reg.read_registry(env=env)
        for e in reg.labs:
            if e.name.lower() == raw:
                return LabResolution(
                    name=raw, kind=KIND_LAB,
                    display_name=e.name,
                    pi_or_contact=e.pi,
                    source_path=e.lab_mgmt_path,
                )
    except Exception:
        pass

    # 3) external customer
    cust = _ext.get_customer(raw, env=env)
    if cust is not None:
        return LabResolution(
            name=raw, kind=KIND_EXTERNAL,
            display_name=cust.name,
            pi_or_contact=cust.billing_contact or cust.contact_name,
            source_path=str(cust.path) if cust.path else "",
            billing_meta={
                "kind": cust.kind,
                "po_number": cust.po_number,
                "tax_id": cust.tax_id,
                "billing_address": cust.billing_address,
                "contact_name": cust.contact_name,
            },
        )
    return LabResolution(name=raw, kind=KIND_UNKNOWN)


def is_known(requester_lab: str, *, env: dict[str, str] | None = None) -> bool:
    return resolve(requester_lab, env=env).kind != KIND_UNKNOWN


__all__ = [
    "KIND_LAB", "KIND_EXTERNAL", "KIND_UNKNOWN",
    "LabResolution", "resolve", "is_known",
]
