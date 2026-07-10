"""Tests for :mod:`murmurent.core.ingest`."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from murmurent.core import ingest, lab_vm


def _make_source(root: Path) -> Path:
    src = root / "scope_export"
    src.mkdir()
    (src / "S001_R1.fastq.gz").write_bytes(b"\x1f\x8b\x08\x00fakebody")
    (src / "S001_R2.fastq.gz").write_bytes(b"\x1f\x8b\x08\x00fakebody")
    (src / "RunInfo.xml").write_text("<RunInfo/>", encoding="utf-8")
    (src / "run_qc.html").write_text("<html/>", encoding="utf-8")
    (src / "run_summary.pdf").write_bytes(b"%PDF-1.4 fake")
    return src


def test_plan_classifies_with_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "vm"))
    src = _make_source(tmp_path)
    plan = ingest.plan_ingest(
        project="dcis_sc_tutorial",
        experiment="1_sample_qc",
        source=src,
    )
    raw_names = {p.name for p in plan.raw_files}
    derived_names = {p.name for p in plan.derived_files}
    assert "S001_R1.fastq.gz" in raw_names
    assert "RunInfo.xml" in raw_names
    assert "run_qc.html" in derived_names
    assert "run_summary.pdf" in derived_names
    assert plan.profile is not None
    assert plan.profile.instrument == "illumina-novaseq"


def test_execute_ingest_chmods_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "vm"))
    src = _make_source(tmp_path)
    plan = ingest.plan_ingest(
        project="p",
        experiment="1_e",
        source=src,
    )
    result = ingest.execute_ingest(plan)
    assert result.raw_dir == lab_vm.experiment_raw_dir("p", "1_e")
    raw_file = result.raw_dir / "S001_R1.fastq.gz"
    assert raw_file.is_file()
    mode = stat.S_IMODE(os.stat(raw_file).st_mode)
    assert mode & stat.S_IWUSR == 0, f"raw file should not be writable: mode={oct(mode)}"
    assert all(len(c.sha256) == 64 for c in result.raw)
    assert all(len(c.sha256) == 64 for c in result.instrument_outputs)
    instr_dir = lab_vm.experiment_instrument_outputs_dir("p", "1_e")
    assert (instr_dir / "run_qc.html").is_file()


def test_unknown_instrument_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "vm"))
    src = _make_source(tmp_path)
    with pytest.raises(KeyError):
        ingest.plan_ingest(
            project="p",
            experiment="1_e",
            source=src,
            instrument="nonexistent",
        )
