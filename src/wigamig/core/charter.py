"""
Purpose: Validate and render project ``CHARTER.md`` documents.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: Charter frontmatter dictionaries (parsed by :mod:`wigamig.core.frontmatter`)
       or template inputs for new charters.
Output: Validation errors raised on bad charters; rendered markdown for new ones.
"""

from __future__ import annotations

from typing import Any, Iterable

from .frontmatter import FrontmatterError

VALID_SENSITIVITY_TIERS: tuple[str, ...] = ("standard", "restricted", "clinical")
VALID_CHOREOGRAPHIES: tuple[str, ...] = (
    "drug_discovery_litl",
    "clinical_cohort",
    "method_benchmarking",
    "imaging_phenotyping",
)
COMMON_REQUIRED_FIELDS: tuple[str, ...] = (
    "project",
    "lead",
    "members",
    "sensitivity",
)
CLINICAL_EXTRA_FIELDS: tuple[str, ...] = ("reb_number", "reb_expires", "data_residency")


class CharterError(FrontmatterError):
    """Raised when a charter is malformed or fails validation."""


def validate_charter(meta: dict[str, Any], *, context: str = "") -> None:
    """Validate a parsed charter ``meta`` dict.

    Checks that the common required fields are present and well-formed and, for
    ``sensitivity: clinical`` charters, that the clinical-specific fields are also
    present.

    Parameters
    ----------
    meta:
        Charter frontmatter as a dict (typically from
        :func:`wigamig.core.frontmatter.parse_file`).
    context:
        Optional string included in error messages (e.g. file path).

    Raises
    ------
    CharterError
        If validation fails.
    """
    suffix = f" in {context}" if context else ""
    missing = [f for f in COMMON_REQUIRED_FIELDS if f not in meta]
    if missing:
        raise CharterError(f"CHARTER missing required field(s){suffix}: {', '.join(missing)}")

    sensitivity = meta.get("sensitivity")
    if sensitivity not in VALID_SENSITIVITY_TIERS:
        raise CharterError(
            f"CHARTER sensitivity{suffix} must be one of "
            f"{VALID_SENSITIVITY_TIERS!r}; got {sensitivity!r}"
        )

    if sensitivity == "clinical":
        missing_clin = [f for f in CLINICAL_EXTRA_FIELDS if f not in meta]
        if missing_clin:
            raise CharterError(
                f"CHARTER with sensitivity: clinical{suffix} missing field(s): "
                f"{', '.join(missing_clin)}"
            )

    members = meta.get("members")
    if not isinstance(members, list) or not members:
        raise CharterError(f"CHARTER members{suffix} must be a non-empty list")
    for handle in members:
        if not isinstance(handle, str) or not handle.strip():
            raise CharterError(f"CHARTER members{suffix} must be a list of '@handle' strings")

    choreography = meta.get("choreography")
    if choreography is not None and choreography not in VALID_CHOREOGRAPHIES:
        # Not fatal in v1; the choreography catalog can be extended at the lab
        # level. Surface as an error here only if an explicit invalid value was
        # passed.
        raise CharterError(
            f"CHARTER choreography{suffix} {choreography!r} is not in the "
            f"known catalog {VALID_CHOREOGRAPHIES!r}"
        )


def render_charter(
    *,
    project: str,
    lead: str,
    members: Iterable[str],
    sensitivity: str,
    description: str,
    choreography: str | None = None,
    reb_number: str | None = None,
    reb_expires: str | None = None,
    data_residency: str | None = None,
    created: str | None = None,
    repo_kind: str = "github",
    remote_url: str | None = None,
) -> str:
    """Render a CHARTER.md markdown document with validated frontmatter.

    Parameters mirror the design's CHARTER frontmatter. Clinical projects must
    pass ``reb_number``, ``reb_expires``, and ``data_residency``.

    ``repo_kind`` records where the project's git origin lives —
    ``"github"`` (the historic default) or ``"local"`` (a bare repo on
    the lab VM). ``remote_url`` is stored alongside so a future reader
    knows where to ``git clone`` from without inspecting ``.git/config``.
    """
    members_list = list(members)
    meta: dict[str, Any] = {
        "project": project,
        "lead": lead,
        "members": members_list,
        "sensitivity": sensitivity,
    }
    if choreography is not None:
        meta["choreography"] = choreography
    if sensitivity == "clinical":
        if not (reb_number and reb_expires and data_residency):
            raise CharterError(
                "Clinical charter requires reb_number, reb_expires, and data_residency"
            )
        meta["reb_number"] = reb_number
        meta["reb_expires"] = reb_expires
        meta["data_residency"] = data_residency
    if created is not None:
        meta["created"] = created

    validate_charter(meta, context=f"render_charter({project})")

    members_yaml = "\n".join(f"  - {h!r}" for h in members_list)
    extra_lines: list[str] = []
    if choreography is not None:
        extra_lines.append(f"choreography: {choreography}")
    if sensitivity == "clinical":
        extra_lines.extend(
            [
                f"reb_number: {reb_number}",
                f"reb_expires: {reb_expires}",
                f"data_residency: {data_residency}",
            ]
        )
    if created is not None:
        extra_lines.append(f"created: {created}")
    # repo_kind is always emitted (even for the github default) so any
    # downstream reader can rely on its presence; remote_url is only
    # emitted when we know it (post-push).
    extra_lines.append(f"repo_kind: {repo_kind}")
    if remote_url is not None:
        extra_lines.append(f"remote_url: {remote_url!r}")

    extra = ("\n".join(extra_lines) + "\n") if extra_lines else ""

    return (
        "---\n"
        f"project: {project}\n"
        f"lead: {lead!r}\n"
        f"sensitivity: {sensitivity}\n"
        f"{extra}"
        "members:\n"
        f"{members_yaml}\n"
        "---\n\n"
        f"# {project}\n\n"
        f"{description}\n"
    )


def render_members_file(members: Iterable[str]) -> str:
    """Render a ``MEMBERS`` file body. One handle per line; preserves leading ``@``."""
    lines = ["# wigamig project MEMBERS — one handle per line."]
    for handle in members:
        lines.append(handle)
    return "\n".join(lines) + "\n"
