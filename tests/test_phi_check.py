"""Tests for :mod:`wigamig.hooks.phi_check`."""

from __future__ import annotations

import io
import json

import pytest

from wigamig.commands import project_cmd
from wigamig.core.projects import find_project
from wigamig.hooks import phi_check


def _run(payload, *, mode="pre"):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = phi_check.main(stdin=stdin, stdout=stdout, mode=mode)
    assert code == 0
    return json.loads(stdout.getvalue())


@pytest.fixture
def clinical_project(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    project_cmd.cmd_new(
        "dcis_test",
        charter_path=None,
        members_csv="@allie",
        description="x",
        sensitivity="clinical",
        reb_number="WREM-1",
        reb_expires="2027-01-01",
        data_residency="ca",
        skip_github=True,
    )
    repo = find_project("dcis_test")
    monkeypatch.chdir(repo.path)
    return repo


@pytest.fixture
def standard_project(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    project_cmd.cmd_new(
        "std_test",
        charter_path=None,
        members_csv="@allie",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    repo = find_project("std_test")
    monkeypatch.chdir(repo.path)
    return repo


def test_pre_blocks_ohip_in_curl(clinical_project):
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl https://example.com -d 'patient=1234-567-890-AB'"},
        }
    )
    assert decision["decision"] == "deny"
    assert "OHIP" in decision["reason"]


def test_pre_allows_ohip_outside_clinical(standard_project):
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl https://example.com -d 'patient=1234-567-890-AB'"},
        }
    )
    assert decision["decision"] == "allow"


def test_pre_allows_local_bash(clinical_project):
    """A `cat` of a local file isn't outbound, so PHI in args should NOT block."""
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 1234-567-890-AB"},  # not curl/ssh
        }
    )
    assert decision["decision"] == "allow"


def test_pre_blocks_webfetch_with_sin(clinical_project):
    decision = _run(
        {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://x.example/", "prompt": "look up 123 456 789"},
        }
    )
    assert decision["decision"] == "deny"
    assert "SIN" in decision["reason"]


def test_pre_blocks_dob_near_name(clinical_project):
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl https://x.example -d 'Smith born 1972-03-15'"},
        }
    )
    assert decision["decision"] == "deny"
    assert "DOB-near-name" in decision["reason"]


def test_post_redacts_phi(clinical_project):
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo something"},
            "tool_response": "Patient 1234-567-890-AB has MRN-12345.",
        },
        mode="post",
    )
    assert decision["decision"] == "modify"
    assert "[REDACTED-PHI]" in decision["tool_response"]
    assert "1234-567-890-AB" not in decision["tool_response"]
