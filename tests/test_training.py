"""
Phase 2d tests: training catalog + per-member training records.

Covers core.training:
  - iter_trainings / get_training (reader)
  - list_member_trainings (per-member roll)
  - has_completed (current vs expired)
  - TrainingRecord.is_current (with + without expiry)
  - check_service_prereqs (pass-through when no requirement;
    pass when current record present; fail with actionable reason
    when missing or expired)
"""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.core import registrar as R
from wigamig.core import services as S
from wigamig.core import training as T


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
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
    return tmp_path


def _write_training(world, slug, *, name=None, status="active", **fm):
    """Write training catalog file under cores/biocore/lab-mgmt/training/."""
    import yaml as _y
    T.training_dir("biocore").mkdir(parents=True, exist_ok=True)
    meta = {
        "training": slug, "name": name or slug, "core": "biocore",
        "status": status,
    }
    meta.update(fm)
    yaml_text = _y.safe_dump(meta, sort_keys=False).rstrip()
    body = f"# {meta['name']}\n\nBody for {slug}."
    T.training_path("biocore", slug).write_text(
        f"---\n{yaml_text}\n---\n\n{body}\n", encoding="utf-8",
    )


def _write_member(world, handle, *, trainings=None, **extra):
    """Write a member file with a training: list (optional)."""
    import yaml as _y
    meta = {"handle": f"@{handle}", "role": "postdoc", "status": "active"}
    meta.update(extra)
    if trainings:
        meta["training"] = trainings
    yaml_text = _y.safe_dump(meta, sort_keys=False).rstrip()
    (world / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\n{yaml_text}\n---\n\n# @{handle}\n", encoding="utf-8",
    )


# ---- iter_trainings + get_training -------------------------------------

def test_iter_trainings_empty_when_dir_missing(world):
    assert T.iter_trainings("biocore") == []


def test_iter_trainings_reads_catalog(world):
    _write_training(world, "itc_basic", name="ITC basic safety",
                    duration_min=30, refresher_years=2,
                    trainers=["@gary"], location="MSB 323")
    out = T.iter_trainings("biocore")
    assert len(out) == 1
    t = out[0]
    assert t.slug == "itc_basic"
    assert t.name == "ITC basic safety"
    assert t.duration_min == 30
    assert t.refresher_years == 2
    assert t.trainers == ["@gary"]


def test_iter_trainings_filters_retired_by_default(world):
    _write_training(world, "current", status="active")
    _write_training(world, "old", status="retired")
    assert [t.slug for t in T.iter_trainings("biocore")] == ["current"]


def test_iter_trainings_include_retired(world):
    _write_training(world, "current", status="active")
    _write_training(world, "old", status="retired")
    out = T.iter_trainings("biocore", include_retired=True)
    assert sorted(t.slug for t in out) == ["current", "old"]


def test_iter_trainings_refresher_explicit_none(world):
    """refresher_years: null means no expiry — distinct from missing
    (which defaults to 2 years for safety)."""
    _write_training(world, "no_expiry", refresher_years=None)
    t = T.get_training("biocore", "no_expiry")
    assert t.refresher_years is None


def test_iter_trainings_skips_unparseable(world):
    _write_training(world, "ok")
    T.training_path("biocore", "broken").write_text(
        "---\n: bad: yaml\n---\n", encoding="utf-8",
    )
    out = T.iter_trainings("biocore")
    assert [t.slug for t in out] == ["ok"]


def test_get_training_returns_none_when_missing(world):
    assert T.get_training("biocore", "ghost") is None


# ---- list_member_trainings ---------------------------------------------

def test_list_member_trainings_empty_when_missing_member(world):
    assert T.list_member_trainings("@nobody") == []


def test_list_member_trainings_empty_when_no_training_field(world):
    _write_member(world, "alice")
    assert T.list_member_trainings("@alice") == []


def test_list_member_trainings_reads_records(world):
    _write_member(world, "alice", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "by": "@gary", "valid_until": "2027-11-15"},
        {"name": "centrifuge_basic", "completed": "2024-06-02",
         "by": "@gary"},
    ])
    rows = T.list_member_trainings("@alice")
    assert len(rows) == 2
    assert rows[0].name == "itc_basic"
    assert rows[0].by == "@gary"
    assert rows[0].valid_until == "2027-11-15"
    assert rows[1].valid_until == ""


def test_list_member_trainings_drops_anonymous_rows(world):
    """A row without a name is meaningless; skip it."""
    _write_member(world, "alice", trainings=[
        {"completed": "2025-11-15"},          # no name
        {"name": "real", "completed": "2025-01-01"},
    ])
    rows = T.list_member_trainings("@alice")
    assert [r.name for r in rows] == ["real"]


# ---- TrainingRecord.is_current -----------------------------------------

def test_record_is_current_when_no_expiry():
    r = T.TrainingRecord(name="x", completed="2024-01-01")
    assert r.is_current() is True


def test_record_is_current_when_expiry_in_future():
    r = T.TrainingRecord(name="x", valid_until="2030-01-01")
    assert r.is_current(today=_dt.date(2026, 5, 22)) is True


def test_record_not_current_when_expired():
    r = T.TrainingRecord(name="x", valid_until="2024-01-01")
    assert r.is_current(today=_dt.date(2026, 5, 22)) is False


def test_record_malformed_expiry_fails_open():
    """A typo in valid_until shouldn't lock the user out of bookings —
    treat it as current (the audit log will surface the bad data)."""
    r = T.TrainingRecord(name="x", valid_until="never")
    assert r.is_current() is True


# ---- has_completed ------------------------------------------------------

def test_has_completed_true_when_record_current(world):
    _write_member(world, "alice", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    assert T.has_completed("@alice", "itc_basic") is True


def test_has_completed_false_when_record_expired(world):
    _write_member(world, "alice", trainings=[
        {"name": "itc_basic", "completed": "2020-01-01",
         "valid_until": "2022-01-01"},
    ])
    assert T.has_completed("@alice", "itc_basic",
                            today=_dt.date(2026, 5, 22)) is False


def test_has_completed_false_when_record_absent(world):
    _write_member(world, "alice")
    assert T.has_completed("@alice", "itc_basic") is False


# ---- check_service_prereqs ---------------------------------------------

def _service(training_required=None):
    return S.ServiceSummary(
        slug="svc", name="Svc", core="biocore",
        training_required=training_required,
    )


def test_check_prereqs_passes_when_service_has_no_requirement(world):
    _write_member(world, "alice")
    out = T.check_service_prereqs(
        member_handle="@alice", service=_service(training_required=None),
    )
    assert out.ok is True
    assert "no training requirement" in out.reason


def test_check_prereqs_passes_with_current_record(world):
    _write_member(world, "alice", trainings=[
        {"name": "itc_basic", "completed": "2025-11-15",
         "valid_until": "2030-11-15"},
    ])
    out = T.check_service_prereqs(
        member_handle="@alice",
        service=_service(training_required="itc_basic"),
    )
    assert out.ok is True


def test_check_prereqs_fails_when_record_missing(world):
    _write_member(world, "alice")
    out = T.check_service_prereqs(
        member_handle="@alice",
        service=_service(training_required="itc_basic"),
    )
    assert out.ok is False
    assert "no current record" in out.reason
    assert "itc_basic" in out.reason


def test_check_prereqs_fails_when_record_expired(world):
    _write_member(world, "alice", trainings=[
        {"name": "itc_basic", "completed": "2020-01-01",
         "valid_until": "2022-01-01"},
    ])
    out = T.check_service_prereqs(
        member_handle="@alice",
        service=_service(training_required="itc_basic"),
        today=_dt.date(2026, 5, 22),
    )
    assert out.ok is False


# ---- path helpers ------------------------------------------------------

def test_training_dir_matches_layout(world):
    assert T.training_dir("biocore") == (
        world / "lab_info" / "cores" / "biocore" / "lab-mgmt" / "training"
    )
