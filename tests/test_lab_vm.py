"""Tests for :mod:`murmurent.core.lab_vm` (incl. the dual-name transition)."""

from __future__ import annotations

from pathlib import Path

from murmurent.core import lab_vm


def _clear_env(monkeypatch):
    monkeypatch.delenv("MURMURENT_DATA_ROOT", raising=False)
    monkeypatch.delenv("MURMURENT_LAB_VM_ROOT", raising=False)


def test_data_root_default(monkeypatch):
    _clear_env(monkeypatch)
    assert lab_vm.data_root() == Path("~/lab_vm/data").expanduser()
    assert lab_vm.lab_vm_root() == Path("~/lab_vm/data").expanduser()


def test_data_root_prefers_new_env(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    assert lab_vm.data_root() == tmp_path


def test_data_root_falls_back_to_legacy_env(monkeypatch, tmp_path):
    """Legacy MURMURENT_LAB_VM_ROOT still works when the new var is unset."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    assert lab_vm.data_root() == tmp_path


def test_data_root_new_env_wins_over_legacy(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path / "new"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "old"))
    assert lab_vm.data_root() == tmp_path / "new"


def test_subdirs_use_new_names_when_fresh(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    assert lab_vm.immutable_root() == tmp_path / "immutable"
    assert lab_vm.append_only_root() == tmp_path / "append_only"
    # Legacy aliases resolve to the same new-name dirs.
    assert lab_vm.raw_root() == tmp_path / "immutable"
    assert lab_vm.refined_root() == tmp_path / "append_only"


def test_subdirs_honor_legacy_dirs_until_migrated(monkeypatch, tmp_path):
    """If only the legacy raw/refined dir exists on disk, resolve to it."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    (tmp_path / "raw").mkdir()
    (tmp_path / "refined").mkdir()
    assert lab_vm.immutable_root() == tmp_path / "raw"
    assert lab_vm.append_only_root() == tmp_path / "refined"


def test_experiment_dirs_new_names(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    immutable, append_only = lab_vm.ensure_experiment_dirs("p", "1_e")
    assert immutable == tmp_path / "immutable" / "p" / "1_e"
    assert append_only == tmp_path / "append_only" / "p" / "1_e"
    assert immutable.is_dir() and append_only.is_dir()


def test_is_under_raw(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    immutable_file = tmp_path / "immutable" / "p" / "1_e" / "x.fastq.gz"
    append_only_file = tmp_path / "append_only" / "p" / "1_e" / "x.csv"
    assert lab_vm.is_under_raw(immutable_file)
    assert not lab_vm.is_under_raw(append_only_file)
    # Only-prefix matches should not pollute neighbouring dirs.
    assert not lab_vm.is_under_raw(tmp_path / "immutableish")
