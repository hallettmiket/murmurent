"""Tests for :mod:`wigamig.commands.push_cmd`."""

from __future__ import annotations

import subprocess

import pytest

from wigamig.commands import experiment_cmd, project_cmd, push_cmd
from wigamig.core import lab_vm
from wigamig.core.frontmatter import parse_file
from wigamig.core.projects import find_project


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    return find_project("p")


def test_push_creates_personal_branch(project):
    # Make a small change so there's something to commit on the personal branch.
    notes = project.path / "data" / "notes.md"
    notes.write_text("scratch notes\n", encoding="utf-8")

    push_cmd.cmd_push("p", message="add notes", finalize=False, refined=None, topic="notes")

    res = subprocess.run(
        ["git", "branch", "--list"],
        cwd=str(project.path),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "member/allie/notes" in res.stdout


def test_push_refined_recomputes_checksums(project):
    experiment_cmd.cmd_new("p", "alpha", performer=["@allie"])
    refined = lab_vm.experiment_refined_dir("p", "1_alpha")
    refined.mkdir(parents=True, exist_ok=True)
    (refined / "out_v1.csv").write_text("col\n1\n2\n", encoding="utf-8")
    (refined / "out_v2.csv").write_text("col\n3\n4\n", encoding="utf-8")

    push_cmd.cmd_push("p", message=None, finalize=False, refined="1_alpha", topic=None)

    notebook = project.path / "exp" / "1_alpha" / "notebook.md"
    parsed = parse_file(notebook)
    refined_paths = parsed.meta.get("refined_data") or []
    checksums = parsed.meta.get("checksums") or {}
    assert any("out_v1.csv" in p for p in refined_paths)
    assert any("out_v2.csv" in p for p in refined_paths)
    assert all(len(v) == 64 for v in checksums.values())


def test_finalize_refuses_from_main(project):
    notes = project.path / "data" / "notes.md"
    notes.write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(project.path), check=True)
    subprocess.run(["git", "commit", "-m", "wip on main"], cwd=str(project.path), check=True)
    with pytest.raises(Exception):
        push_cmd.cmd_push("p", message=None, finalize=True, refined=None, topic=None)
