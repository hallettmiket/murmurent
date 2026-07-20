"""Tests for ``murmurent data migrate`` (:mod:`murmurent.commands.data_cmd`)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.commands import data_cmd


def _mkfile(p, text="x\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_migrate_renames_both(tmp_path):
    _mkfile(tmp_path / "raw" / "proj" / "1_e" / "reads.fastq")
    _mkfile(tmp_path / "refined" / "proj" / "1_e" / "results.csv")

    res = CliRunner().invoke(cli, ["data", "migrate", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output

    assert (tmp_path / "immutable" / "proj" / "1_e" / "reads.fastq").is_file()
    assert (tmp_path / "append_only" / "proj" / "1_e" / "results.csv").is_file()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "refined").exists()


def test_migrate_dry_run_changes_nothing(tmp_path):
    _mkfile(tmp_path / "raw" / "a.txt")
    _mkfile(tmp_path / "refined" / "b.txt")

    res = CliRunner().invoke(
        cli, ["data", "migrate", "--root", str(tmp_path), "--dry-run"]
    )
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output.lower()
    # Nothing moved.
    assert (tmp_path / "raw").is_dir()
    assert (tmp_path / "refined").is_dir()
    assert not (tmp_path / "immutable").exists()
    assert not (tmp_path / "append_only").exists()


def test_migrate_is_idempotent(tmp_path):
    _mkfile(tmp_path / "raw" / "a.txt")
    _mkfile(tmp_path / "refined" / "b.txt")

    first = CliRunner().invoke(cli, ["data", "migrate", "--root", str(tmp_path)])
    assert first.exit_code == 0, first.output

    # Second run: nothing left to move, still exits 0.
    second = CliRunner().invoke(cli, ["data", "migrate", "--root", str(tmp_path)])
    assert second.exit_code == 0, second.output
    assert "0 directory rename(s) applied" in second.output
    assert (tmp_path / "immutable" / "a.txt").is_file()
    assert (tmp_path / "append_only" / "b.txt").is_file()


def test_migrate_refuses_when_destination_exists(tmp_path):
    _mkfile(tmp_path / "raw" / "a.txt")
    (tmp_path / "immutable").mkdir()  # destination already present

    res = CliRunner().invoke(cli, ["data", "migrate", "--root", str(tmp_path)])
    assert res.exit_code != 0
    assert "conflict" in res.output.lower()
    # Left untouched.
    assert (tmp_path / "raw" / "a.txt").is_file()


def test_migrate_defaults_to_resolved_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("MURMURENT_LAB_VM_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    _mkfile(tmp_path / "raw" / "a.txt")

    res = CliRunner().invoke(cli, ["data", "migrate"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "immutable" / "a.txt").is_file()


def test_migrate_honors_legacy_env_var(tmp_path, monkeypatch):
    """Default root resolves via the legacy MURMURENT_LAB_VM_ROOT too."""
    monkeypatch.delenv("MURMURENT_DATA_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    _mkfile(tmp_path / "refined" / "b.txt")

    res = CliRunner().invoke(cli, ["data", "migrate"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "append_only" / "b.txt").is_file()


def test_plan_migration_statuses(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "append_only").mkdir()  # refined already migrated
    actions = {a.new.name: a.status for a in data_cmd.plan_migration(tmp_path)}
    assert actions["immutable"] == "rename"
    assert actions["append_only"] == "skip-migrated"
