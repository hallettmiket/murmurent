"""
Purpose: The single source of truth for murmurent's sensitivity tiers.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: A sensitivity label as written in a cert-project record, a charter,
       a ``.murmurent.yaml`` marker or an Oracle entry's frontmatter.
Output: The canonical tier name, and a yes/no answer to "is this protected?".

Three tiers, from least to most sensitive:

- ``standard``: ordinary material that may be shared with the group.
- ``restricted``: material that is not yet the group's to hold, such as an
  unpublished result or a candidate molecule with a patent position.
- ``protected``: material that a data-use agreement or a research ethics board
  keeps inside the member's own account. Patient-derived records are the
  usual case.

The top tier used to be called ``clinical`` (renamed in #205 to match the
manuscript). Old records still say ``clinical``, so every reader passes the
label through :func:`normalize` or :func:`is_protected`, which treat the old
name exactly like ``protected``. Writers always emit ``protected``.
"""

from __future__ import annotations

from typing import Any

#: The three tiers, least sensitive first.
TIERS: tuple[str, ...] = ("standard", "restricted", "protected")

#: The most sensitive tier.
PROTECTED = "protected"

#: Former names, mapped to the tier they now mean.
LEGACY: dict[str, str] = {"clinical": "protected"}

#: Every label a reader accepts: the three tiers plus their former names.
ACCEPTED: tuple[str, ...] = TIERS + tuple(LEGACY)


def normalize(value: Any) -> str:
    """Return the canonical tier name for a sensitivity label.

    Parameters
    ----------
    value : Any
        The label as found in a record. ``None`` and blanks are allowed.

    Returns
    -------
    str
        ``""`` for a missing or blank label; the canonical tier for a current
        or legacy name (``"clinical"`` becomes ``"protected"``); otherwise the
        label lowercased and stripped but not changed, so a validator can still
        name the bad value in its error message.

    Examples
    --------
    >>> normalize(" Clinical ")
    'protected'
    >>> normalize("standard")
    'standard'
    """
    if value is None:
        return ""
    label = str(value).strip().lower()
    return LEGACY.get(label, label)


def is_protected(value: Any) -> bool:
    """Whether a sensitivity label means the top tier.

    True for ``"protected"`` and for its former name ``"clinical"``, in any
    case and with surrounding spaces.

    Parameters
    ----------
    value : Any
        The label as found in a record.

    Returns
    -------
    bool
    """
    return normalize(value) == PROTECTED


def is_valid(value: Any) -> bool:
    """Whether a label names a known tier, under its current or former name."""
    return normalize(value) in TIERS


__all__ = ["TIERS", "PROTECTED", "LEGACY", "ACCEPTED",
           "normalize", "is_protected", "is_valid"]
