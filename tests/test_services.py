"""
Tests for core.services — per-core service catalog reader + fee quoter.

Covers Phase 2a of the cores rollout (docs/cores_plan.md §11):

  - iter_services empty when services/ dir missing
  - iter_services parses a fully-populated entry (all schema fields)
  - iter_services tolerates partial / minimal frontmatter
  - iter_services filters retired entries by default; include_retired surfaces them
  - iter_services silently skips malformed entries
  - get_service single-service lookup
  - quote_fee: tier+modifier maths
  - quote_fee: unknown tier raises
  - quote_fee: unknown modifier ignored (defensive)
"""

from __future__ import annotations

import pytest

from murmurent.core import registrar as R
from murmurent.core import services as S


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(
        name="biocore", display_name="BioCORE",
        leader_handle="@gary",
    )
    # The create_core call scaffolds lab-mgmt but not services/ — make it.
    (tmp_path / "lab_info" / "cores" / "biocore" / "lab-mgmt" / "services").mkdir()
    return tmp_path


def _write_service(world, slug, *, name=None, status="active", **fm):
    """Write services/<slug>.md with arbitrary frontmatter."""
    import yaml as _y
    meta = {
        "service": slug,
        "name": name or slug,
        "core": "biocore",
        "status": status,
    }
    meta.update(fm)
    yaml_text = _y.safe_dump(meta, sort_keys=False).rstrip()
    body = f"# {meta['name']}\n\nMarkdown body for {slug}."
    (S.services_dir("biocore")).joinpath(f"{slug}.md").write_text(
        f"---\n{yaml_text}\n---\n\n{body}\n", encoding="utf-8",
    )


# ---- iter_services -------------------------------------------------------

def test_iter_services_empty_when_no_services_dir(world):
    # Delete the services dir created by the fixture.
    sdir = S.services_dir("biocore")
    sdir.rmdir()
    assert S.iter_services("biocore") == []


def test_iter_services_empty_dir(world):
    assert S.iter_services("biocore") == []


def test_iter_services_full_schema(world):
    _write_service(
        world, "itc_microcal_peaq",
        name="MicroCal PEAQ-ITC",
        capability="structure_function_interaction",
        mode="independent_data_collection",
        description="Isothermal titration calorimetry.",
        equipment={"manufacturer": "Malvern", "model": "PEAQ-ITC"},
        location="MSB 323, room A",
        duration_default_min=90,
        duration_max_min=240,
        training_required="itc_basic_training",
        prerequisites=["≥ 10 µM sample", "matched buffer"],
        fee={
            "unit": "per_run",
            "tiers": {"academic_internal": 80.0, "academic_external": 130.0,
                      "industry": 260.0},
            "modifiers": {"weekend": 1.25, "after_hours": 1.5},
        },
        data_deliverable={"format": ".itc files + PNG", "delivery": "per_job_acl"},
        contact={"email": "biocore@uwo.ca"},
        created="2026-05-22",
    )
    out = S.iter_services("biocore")
    assert len(out) == 1
    s = out[0]
    assert s.slug == "itc_microcal_peaq"
    assert s.name == "MicroCal PEAQ-ITC"
    assert s.core == "biocore"
    assert s.capability == "structure_function_interaction"
    assert s.mode == "independent_data_collection"
    assert s.equipment["manufacturer"] == "Malvern"
    assert s.duration_default_min == 90
    assert s.training_required == "itc_basic_training"
    assert "matched buffer" in s.prerequisites
    assert s.fee.tiers["academic_internal"] == 80.0
    assert s.fee.modifiers["weekend"] == 1.25
    assert s.data_deliverable["format"] == ".itc files + PNG"
    assert s.contact["email"] == "biocore@uwo.ca"
    assert s.status == "active"
    assert s.created == "2026-05-22"


def test_iter_services_minimal_schema(world):
    """A service with only the required fields still parses cleanly."""
    _write_service(world, "minimum")
    out = S.iter_services("biocore")
    assert len(out) == 1
    s = out[0]
    assert s.slug == "minimum"
    assert s.fee.tiers == {}             # defaults
    assert s.duration_default_min == 60
    assert s.training_required is None
    assert s.prerequisites == []


def test_iter_services_sorted_by_slug(world):
    _write_service(world, "zeta")
    _write_service(world, "alpha")
    _write_service(world, "middle")
    assert [s.slug for s in S.iter_services("biocore")] == ["alpha", "middle", "zeta"]


def test_iter_services_filters_retired_by_default(world):
    _write_service(world, "live", status="active")
    _write_service(world, "old", status="retired")
    out = S.iter_services("biocore")
    assert [s.slug for s in out] == ["live"]


def test_iter_services_include_retired(world):
    _write_service(world, "live", status="active")
    _write_service(world, "old", status="retired")
    out = S.iter_services("biocore", include_retired=True)
    assert sorted(s.slug for s in out) == ["live", "old"]


def test_iter_services_includes_maintenance(world):
    """maintenance status surfaces by default — it's a paused-but-not-dead state."""
    _write_service(world, "live", status="active")
    _write_service(world, "paused", status="maintenance")
    statuses = {s.status for s in S.iter_services("biocore")}
    assert statuses == {"active", "maintenance"}


def test_iter_services_skips_unparseable(world):
    _write_service(world, "ok")
    # Write a broken yaml entry.
    S.services_dir("biocore").joinpath("broken.md").write_text(
        "---\n: invalid yaml: : :\n---\n", encoding="utf-8",
    )
    out = S.iter_services("biocore")
    assert [s.slug for s in out] == ["ok"]


def test_iter_services_skips_non_md_files(world):
    _write_service(world, "real")
    S.services_dir("biocore").joinpath("README.txt").write_text("not yaml")
    out = S.iter_services("biocore")
    assert [s.slug for s in out] == ["real"]


def test_iter_services_unknown_core_returns_empty(world):
    assert S.iter_services("never_registered") == []


# ---- get_service ---------------------------------------------------------

def test_get_service_returns_match(world):
    _write_service(world, "abc", name="ABC Service")
    s = S.get_service("biocore", "abc")
    assert s is not None and s.name == "ABC Service"


def test_get_service_returns_none_when_missing(world):
    assert S.get_service("biocore", "ghost") is None


def test_get_service_finds_retired(world):
    _write_service(world, "retired_one", status="retired")
    s = S.get_service("biocore", "retired_one")
    assert s is not None
    assert s.status == "retired"


# ---- quote_fee -----------------------------------------------------------

def _make_service():
    return S.ServiceSummary(
        slug="x", name="x", core="biocore",
        fee=S.ServiceFee(
            unit="per_run",
            tiers={"academic_internal": 80.0, "industry": 260.0},
            modifiers={"weekend": 1.25, "after_hours": 1.5, "overtime": 1.5},
        ),
    )


def test_quote_fee_base_tier_no_modifiers():
    q = S.quote_fee(_make_service(), tier="academic_internal")
    assert q["tier"] == "academic_internal"
    assert q["base"] == 80.0
    assert q["total"] == 80.0
    assert q["modifiers_applied"] == []


def test_quote_fee_single_modifier():
    q = S.quote_fee(_make_service(), tier="academic_internal",
                    modifiers=["weekend"])
    assert q["total"] == 100.0   # 80 * 1.25
    assert q["modifiers_applied"] == [{"name": "weekend", "factor": 1.25}]


def test_quote_fee_multiple_modifiers_compound():
    q = S.quote_fee(_make_service(), tier="industry",
                    modifiers=["weekend", "after_hours"])
    # 260 * 1.25 * 1.5 = 487.5
    assert q["total"] == 487.5
    assert len(q["modifiers_applied"]) == 2


def test_quote_fee_unknown_tier_raises():
    with pytest.raises(ValueError, match="unknown tier"):
        S.quote_fee(_make_service(), tier="bogus")


def test_quote_fee_unknown_modifier_ignored():
    q = S.quote_fee(_make_service(), tier="academic_internal",
                    modifiers=["nonexistent"])
    assert q["total"] == 80.0
    assert q["modifiers_applied"] == []


# ---- path helpers --------------------------------------------------------

def test_services_dir_matches_layout(world):
    assert S.services_dir("biocore") == (
        world / "lab_info" / "cores" / "biocore" / "lab-mgmt" / "services"
    )


def test_service_path_matches_layout(world):
    assert S.service_path("biocore", "abc") == (
        world / "lab_info" / "cores" / "biocore" / "lab-mgmt" / "services" / "abc.md"
    )
