"""Tests for :mod:`murmurent.core.charter`."""

from __future__ import annotations

import pytest

from murmurent.core.charter import CharterError, render_charter, validate_charter


def test_validate_minimal_standard():
    meta = {
        "project": "p",
        "lead": "@allie",
        "members": ["@allie", "@bob"],
        "sensitivity": "standard",
    }
    validate_charter(meta)


def test_clinical_requires_extra_fields():
    meta = {
        "project": "p",
        "lead": "@allie",
        "members": ["@allie"],
        "sensitivity": "clinical",
    }
    with pytest.raises(CharterError):
        validate_charter(meta)
    meta.update(reb_number="WREM-1", reb_expires="2027-01-01", data_residency="ca")
    validate_charter(meta)


def test_invalid_sensitivity_rejected():
    with pytest.raises(CharterError):
        validate_charter(
            {
                "project": "p",
                "lead": "@a",
                "members": ["@a"],
                "sensitivity": "private",
            }
        )


def test_render_charter_clinical_includes_reb():
    text = render_charter(
        project="dcis_sc_tutorial",
        lead="@allie",
        members=["@allie", "@bob"],
        sensitivity="clinical",
        description="A fake clinical project.",
        choreography="clinical_cohort",
        reb_number="WREM-2026-9999",
        reb_expires="2027-09-01",
        data_residency="ca",
    )
    assert "sensitivity: clinical" in text
    assert "reb_number: WREM-2026-9999" in text
    assert "reb_expires: 2027-09-01" in text
    assert "data_residency: ca" in text
    assert "choreography: clinical_cohort" in text


def test_render_charter_rejects_clinical_without_reb():
    with pytest.raises(CharterError):
        render_charter(
            project="p",
            lead="@a",
            members=["@a"],
            sensitivity="clinical",
            description="x",
        )
