"""
Phase 5a tests: per-job dir + manifest + auto-create on booking.

Covers:
  - Paths: cores_root, core_jobs_dir, job_dir, manifest_path honor
    MURMURENT_LAB_VM_ROOT and are NOT under top-level raw/refined
  - init_job creates raw/ + refined/ subdirs + manifest.json
  - init_job is idempotent
  - Manifest carries request_id, requester, requester_lab, fee
  - refresh_manifest picks up actual_charge after set_actual_charge
  - refresh_manifest picks up state changes
  - list_files walks recursively, returns relpaths
  - safe_resolve refuses '..' escapes + absolute paths
  - write_file persists bytes; refuses path escapes
  - create_request auto-inits the job dir; failure to init doesn't
    block booking (lab_vm_root unwritable on a member laptop)
"""

from __future__ import annotations

import json
import os

import pytest

from murmurent.core import jobs as J
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _book(**kw):
    defaults = dict(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
        fee_at_booking=SR.FeeSnapshot(tier="academic_internal",
                                        unit="per_run",
                                        base=80.0, total=80.0),
    )
    defaults.update(kw)
    return SR.create_request(**defaults)


# ---- paths --------------------------------------------------------------

def test_paths_respect_lab_vm_root(world):
    assert J.cores_root() == world / "lab_vm" / "cores"
    assert J.job_dir("biocore", "abc") == (
        world / "lab_vm" / "cores" / "biocore" / "jobs" / "abc"
    )


def test_job_dir_not_under_protected_raw_refined(world):
    """Critical: job dirs sit under cores/, NOT under top-level raw/refined
    where the raw_guard + protected_paths hooks block writes."""
    j = str(J.job_dir("biocore", "abc"))
    assert "/lab_vm/cores/biocore/jobs/" in j
    assert "/lab_vm/raw/" not in j
    assert "/lab_vm/refined/" not in j


# ---- init_job + manifest -----------------------------------------------

def test_init_job_creates_dirs_and_manifest(world):
    req = _book()
    jdir = J.init_job("biocore", req)
    assert (jdir / "raw").is_dir()
    assert (jdir / "refined").is_dir()
    assert (jdir / "manifest.json").is_file()


def test_init_job_idempotent(world):
    req = _book()
    p1 = J.init_job("biocore", req)
    # Add a stub file in raw/ to verify we don't blow away contents.
    (p1 / "raw" / "kept.bin").write_bytes(b"keep me")
    p2 = J.init_job("biocore", req)
    assert p1 == p2
    assert (p1 / "raw" / "kept.bin").is_file()


def test_manifest_has_request_metadata(world):
    req = _book()
    J.init_job("biocore", req)
    m = J.read_manifest("biocore", req.request_id)
    assert m["request_id"] == req.request_id
    assert m["requester"] == "@alice"
    assert m["requester_lab"] == "hallett"
    assert m["service"] == "itc"
    assert m["fee_at_booking"]["total"] == 80.0
    assert m["state"] == SR.STATE_SCHEDULED


def test_refresh_manifest_picks_up_actual_charge(world):
    req = _book()
    J.init_job("biocore", req)
    SR.transition_request(core="biocore", request_id=req.request_id,
                            to_state=SR.STATE_IN_PROGRESS)
    SR.transition_request(core="biocore", request_id=req.request_id,
                            to_state=SR.STATE_COMPLETED)
    SR.set_actual_charge(
        core="biocore", request_id=req.request_id,
        charge=SR.FeeSnapshot(tier="academic_internal", unit="per_run",
                                base=80.0, total=120.0),
        confirmed_by="@gary",
    )
    m = J.read_manifest("biocore", req.request_id)
    assert m["state"] == SR.STATE_COMPLETED
    assert m["actual_charge"]["total"] == 120.0


def test_refresh_manifest_tracks_state(world):
    req = _book()
    J.init_job("biocore", req)
    SR.transition_request(core="biocore", request_id=req.request_id,
                            to_state=SR.STATE_CANCELLED)
    m = J.read_manifest("biocore", req.request_id)
    assert m["state"] == SR.STATE_CANCELLED


def test_read_manifest_returns_none_when_missing(world):
    assert J.read_manifest("biocore", "ghost") is None


# ---- list_files --------------------------------------------------------

def test_list_files_recursive(world):
    req = _book()
    jdir = J.init_job("biocore", req)
    (jdir / "raw" / "s1.itc").write_bytes(b"X" * 100)
    (jdir / "refined" / "fit.png").write_bytes(b"P" * 50)
    rows = J.list_files("biocore", req.request_id)
    rels = sorted(r.relpath for r in rows)
    assert rels == ["manifest.json", "raw/s1.itc", "refined/fit.png"]
    by_rel = {r.relpath: r for r in rows}
    assert by_rel["raw/s1.itc"].size_bytes == 100


def test_list_files_unknown_job_empty(world):
    assert J.list_files("biocore", "ghost") == []


# ---- safe_resolve ------------------------------------------------------

def test_safe_resolve_refuses_dotdot(world):
    req = _book()
    J.init_job("biocore", req)
    with pytest.raises(J.JobError, match="escape"):
        J.safe_resolve("biocore", req.request_id, "../../etc/passwd")


def test_safe_resolve_refuses_absolute(world):
    req = _book()
    J.init_job("biocore", req)
    with pytest.raises(J.JobError, match="escape"):
        J.safe_resolve("biocore", req.request_id, "/etc/passwd")


def test_safe_resolve_unknown_job_raises(world):
    with pytest.raises(J.JobError, match="job dir not found"):
        J.safe_resolve("biocore", "ghost", "refined/fit.png")


# ---- write_file --------------------------------------------------------

def test_write_file_persists_bytes(world):
    req = _book()
    J.init_job("biocore", req)
    p = J.write_file("biocore", req.request_id,
                       "refined/fit.png", b"\x89PNG-stub")
    assert p.is_file()
    assert p.read_bytes() == b"\x89PNG-stub"


def test_write_file_refuses_escape(world):
    req = _book()
    J.init_job("biocore", req)
    with pytest.raises(J.JobError, match="escape"):
        J.write_file("biocore", req.request_id,
                       "../../oops.txt", b"x")


def test_write_file_creates_nested_dir(world):
    req = _book()
    J.init_job("biocore", req)
    p = J.write_file("biocore", req.request_id,
                       "refined/figs/v2/png.bin", b"x")
    assert p.is_file()


# ---- auto-init on create_request ---------------------------------------

def test_create_request_auto_inits_job_dir(world):
    req = _book()
    jdir = J.job_dir("biocore", req.request_id)
    assert jdir.is_dir()
    assert (jdir / "manifest.json").is_file()
    m = J.read_manifest("biocore", req.request_id)
    assert m["requester_lab"] == "hallett"


def test_create_request_survives_job_init_failure(monkeypatch, world):
    """When lab_vm_root is unwritable (e.g. on a member laptop without
    the lab mount), booking still succeeds — job dir is best-effort."""
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", "/this/path/cannot/exist/anywhere")
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
    )
    assert req.path.is_file()   # request itself created
