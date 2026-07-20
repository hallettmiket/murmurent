"""End-to-end tests for the project + experiment commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.commands import experiment_cmd, project_cmd
from murmurent.core import lab_vm
from murmurent.core.frontmatter import parse_file


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Point all murmurent env vars to ``tmp_path`` so tests don't touch real dirs."""
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_USER", "allie")
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    yield tmp_path


def test_project_new_creates_repo_and_registry(isolated_env):
    summary = project_cmd.cmd_new(
        "dcis_sc_tutorial",
        charter_path=None,
        members_csv="@the_pi,@allie,@bob,@cassie",
        description="Fake clinical project for the smoke test.",
        sensitivity="clinical",
        choreography="clinical_cohort",
        reb_number="WREM-2026-9999",
        reb_expires="2027-09-01",
        data_residency="ca",
        lead="@allie",
        skip_github=True,
    )
    assert summary.sensitivity == "clinical"
    assert summary.lead == "@allie"
    assert summary.path.is_dir()
    assert (summary.path / "CHARTER.md").is_file()
    assert (summary.path / "MEMBERS").is_file()
    assert (summary.path / "exp").is_dir()
    assert lab_vm.project_raw_dir("dcis_sc_tutorial").is_dir()
    registry = isolated_env / "lab-mgmt" / "cert_projects" / "dcis_sc_tutorial.md"
    assert registry.is_file()


def test_project_list_shows_member_projects(isolated_env):
    project_cmd.cmd_new(
        "dcis_sc_tutorial",
        charter_path=None,
        members_csv="@allie,@bob",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "list"])
    assert result.exit_code == 0
    assert "dcis_sc_tutorial" in result.output


def test_experiment_new_then_status(isolated_env):
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie,@bob",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    exp_dir = experiment_cmd.cmd_new("p", "alpha", performer=["@allie"])
    assert exp_dir.name == "1_alpha"
    assert (exp_dir / "notebook.md").is_file()
    assert (exp_dir / "run_all.py").is_file()
    assert lab_vm.experiment_raw_dir("p", "1_alpha").is_dir()

    parsed = parse_file(exp_dir / "notebook.md")
    assert parsed.meta["status"] == "planned"

    experiment_cmd.cmd_status("p", "alpha", "running")
    parsed = parse_file(exp_dir / "notebook.md")
    assert parsed.meta["status"] == "running"


def test_experiment_ingest_updates_notebook(isolated_env, tmp_path):
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    experiment_cmd.cmd_new("p", "alpha", performer=["@allie"])

    src = tmp_path / "src"
    src.mkdir()
    (src / "S001.fastq.gz").write_bytes(b"\x1f\x8b" + b"abc")
    (src / "run_qc.html").write_text("<html/>")

    exit_code = experiment_cmd.cmd_ingest(
        "p", "alpha", str(src), instrument=None, accept=True, dry_run=False
    )
    assert exit_code == 0
    notebook = isolated_env / "repos" / "p" / "exp" / "1_alpha" / "notebook.md"
    parsed = parse_file(notebook)
    raw = parsed.meta.get("immutable_data") or []
    instr = parsed.meta.get("instrument_outputs") or []
    checksums = parsed.meta.get("checksums") or {}
    assert any("S001.fastq.gz" in p for p in raw)
    assert any("run_qc.html" in p for p in instr)
    assert checksums and all(len(v) == 64 for v in checksums.values())


def test_project_describe_shows_clinical_metadata(isolated_env):
    project_cmd.cmd_new(
        "dcis_sc_tutorial",
        charter_path=None,
        members_csv="@the_pi,@allie,@bob,@cassie",
        description="Fake clinical.",
        sensitivity="clinical",
        choreography="clinical_cohort",
        reb_number="WREM-2026-9999",
        reb_expires="2027-09-01",
        data_residency="ca",
        lead="@allie",
        skip_github=True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "describe", "dcis_sc_tutorial"])
    assert result.exit_code == 0, result.output
    assert "sensitivity: clinical" in result.output
    assert "WREM-2026-9999" in result.output
    assert "@cassie" in result.output


def test_project_admit_appends_member(isolated_env):
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie,@bob",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    project_cmd.cmd_admit("p", "@cassie")
    members_file = (isolated_env / "repos" / "p" / "MEMBERS").read_text()
    assert "@cassie" in members_file


def test_project_sensitivity_get_and_set(isolated_env):
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "sensitivity", "p"])
    assert result.exit_code == 0
    assert "standard" in result.output

    result = runner.invoke(cli, ["project", "sensitivity", "p", "--set", "restricted"])
    assert result.exit_code == 0
    parsed = parse_file(isolated_env / "repos" / "p" / "CHARTER.md")
    assert parsed.meta["sensitivity"] == "restricted"
