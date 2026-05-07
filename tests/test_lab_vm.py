"""Tests for :mod:`wigamig.core.lab_vm`."""

from __future__ import annotations

from pathlib import Path

from wigamig.core import lab_vm


def test_lab_vm_root_default(monkeypatch):
    monkeypatch.delenv("WIGAMIG_LAB_VM_ROOT", raising=False)
    assert lab_vm.lab_vm_root() == Path("~/lab_vm/data").expanduser()


def test_lab_vm_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    assert lab_vm.lab_vm_root() == tmp_path
    assert lab_vm.raw_root() == tmp_path / "raw"
    assert lab_vm.refined_root() == tmp_path / "refined"


def test_experiment_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    raw, refined = lab_vm.ensure_experiment_dirs("p", "1_e")
    assert raw == tmp_path / "raw" / "p" / "1_e"
    assert refined == tmp_path / "refined" / "p" / "1_e"
    assert raw.is_dir() and refined.is_dir()


def test_is_under_raw(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    raw_file = tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz"
    refined_file = tmp_path / "refined" / "p" / "1_e" / "x.csv"
    assert lab_vm.is_under_raw(raw_file)
    assert not lab_vm.is_under_raw(refined_file)
    # Only-prefix matches should not pollute neighbouring dirs.
    assert not lab_vm.is_under_raw(tmp_path / "rawish")
