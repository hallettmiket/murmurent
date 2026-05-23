"""
Calendar slot normalisation: Google rejects ISO8601 without seconds.

Smoke discovery — curl bookings with `T14:00-04:00` (no seconds) hit
HTTP 400; the dashboard's date+time picker was fine because it
always emitted `T14:00:00-04:00`. Fix lives in
calendar_google._normalize_iso_for_google and runs unconditionally
inside create_event so EVERY caller is safe.
"""

from __future__ import annotations

from wigamig.core.calendar_google import _normalize_iso_for_google as N


def test_adds_seconds_when_missing():
    assert N("2026-05-28T14:00-04:00") == "2026-05-28T14:00:00-04:00"


def test_passes_through_when_present():
    assert N("2026-05-28T14:00:00-04:00") == "2026-05-28T14:00:00-04:00"


def test_passes_through_with_microseconds():
    assert N("2026-05-28T14:00:00.500-04:00") == "2026-05-28T14:00:00-04:00"


def test_empty_returns_empty():
    assert N("") == ""


def test_unparseable_returns_unchanged():
    """Let Google's own error surface for genuinely malformed input."""
    assert N("tomorrow morning") == "tomorrow morning"


def test_z_suffix_normalises():
    """`Z` (UTC) is valid ISO; preserved (or rendered as +00:00)."""
    out = N("2026-05-28T14:00Z")
    # Either form is acceptable to Google; both have a seconds component.
    assert out in ("2026-05-28T14:00:00+00:00", "2026-05-28T14:00:00Z")
