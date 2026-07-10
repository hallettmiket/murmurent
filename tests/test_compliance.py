"""Tests for the Phase-14 Western training compliance feature."""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.core import compliance, membership


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    return tmp_path


def _seed_compliance(root, body):
    (root / "lab-mgmt" / "compliance.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_config_falls_back_when_missing(world):
    cfg = compliance.load_config()
    codes = {s.code for s in cfg.required}
    # Default fallback includes WHMIS + TCPS_2.
    assert "WHM103" in codes
    assert "TCPS_2" in codes


def test_load_config_reads_full_catalog(world):
    _seed_compliance(world, """\
---
required:
  - code: WHM103
    name: WHMIS
    short: whmis
    cadence_years: 3
    audience: all
  - code: BIOS01
    name: Biosafety
    short: biosafety
    cadence_years: 3
    audience: lab
  - code: WSCC01
    name: Western Safe Campus
    short: wscc
    cadence_years: null
    audience: all
yellow_threshold_days: 45
---
""")
    cfg = compliance.load_config()
    codes = [s.code for s in cfg.required]
    assert codes == ["WHM103", "BIOS01", "WSCC01"]
    assert cfg.yellow_threshold_days == 45
    bios = next(s for s in cfg.required if s.code == "BIOS01")
    assert bios.cadence_years == 3
    assert bios.audience == "lab"
    wscc = next(s for s in cfg.required if s.code == "WSCC01")
    assert wscc.cadence_years is None  # one-time


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def test_status_ok_for_far_future_expiry(world):
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob",
        member_certs=["WHM103:2030-01-01"],
        config=cfg,
        today=_dt.date(2026, 5, 8),
    )
    whmis = next(s for s in statuses if s.code == "WHM103")
    assert whmis.status == "ok"
    assert whmis.expires == "2030-01-01"


def test_status_expiring_within_yellow_window(world):
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob",
        member_certs=["WHM103:2026-06-15"],   # 38 days from 2026-05-08
        config=cfg,
        today=_dt.date(2026, 5, 8),
    )
    whmis = next(s for s in statuses if s.code == "WHM103")
    assert whmis.status == "expiring"


def test_status_expired_in_past(world):
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob",
        member_certs=["WHM103:2025-01-01"],
        config=cfg,
        today=_dt.date(2026, 5, 8),
    )
    whmis = next(s for s in statuses if s.code == "WHM103")
    assert whmis.status == "expired"


def test_status_missing_when_required_but_absent(world):
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob",
        member_certs=[],   # nothing declared
        config=cfg,
        today=_dt.date(2026, 5, 8),
    )
    whmis = next(s for s in statuses if s.code == "WHM103")
    assert whmis.status == "missing"


def test_status_n_a_for_optional_when_absent(world):
    _seed_compliance(world, """\
---
required:
  - code: LAS01
    name: Laser
    short: laser
    cadence_years: 3
    audience: optional
---
""")
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob", member_certs=[], config=cfg, today=_dt.date(2026, 5, 8),
    )
    las = next(s for s in statuses if s.code == "LAS01")
    assert las.status == "n/a"


def test_status_one_time_completed(world):
    _seed_compliance(world, """\
---
required:
  - code: WSCC01
    name: WSCC
    short: wscc
    cadence_years: null
    audience: all
---
""")
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob", member_certs=["WSCC01:completed"],
        config=cfg, today=_dt.date(2026, 5, 8),
    )
    wscc = next(s for s in statuses if s.code == "WSCC01")
    assert wscc.status == "one_time"


def test_status_explicit_n_a(world):
    cfg = compliance.load_config()
    statuses = compliance.compute_member_status(
        handle="bob", member_certs=["WHM103:n/a"],
        config=cfg, today=_dt.date(2026, 5, 8),
    )
    whmis = next(s for s in statuses if s.code == "WHM103")
    assert whmis.status == "n/a"


# ---------------------------------------------------------------------------
# Snapshot integration
# ---------------------------------------------------------------------------


def test_snapshot_training_compliance_block(world, monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    membership.add(handle="the_pi", full_name="Mike Hallett", role="pi",
                   certifications=["WHM103:2030-12-31"])
    membership.add(handle="bob", full_name="Bob", role="postdoc",
                   certifications=["WHM103:2025-01-01"])  # expired

    from murmurent.dashboard import snapshot
    resp = snapshot.build_response("the_pi", today=_dt.date(2026, 5, 8))
    tc = resp.training_compliance
    assert any(s.code == "WHM103" for s in tc.required)
    handles = {m.handle for m in tc.members}
    assert {"the_pi", "bob"} <= handles
    bob_row = next(m for m in tc.members if m.handle == "bob")
    bob_whmis = next(c for c in bob_row.certs if c.code == "WHM103")
    assert bob_whmis.status == "expired"
