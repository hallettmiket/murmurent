"""Tests for :mod:`murmurent.hooks.phi_check`."""

from __future__ import annotations

import io
import json

import pytest

from murmurent.commands import project_cmd
from murmurent.core.projects import find_project
from murmurent.hooks import phi_check


def _run(payload, *, mode="pre"):
    """Normalise CC-modern hook output back to the legacy decision
    shape tests assert on (see test_raw_guard._run for rationale)."""
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = phi_check.main(stdin=stdin, stdout=stdout, mode=mode)
    assert code == 0
    raw = stdout.getvalue().strip()
    if not raw:
        return {"decision": "allow"}
    data = json.loads(raw)
    hso = data.get("hookSpecificOutput") or {}
    pd = hso.get("permissionDecision")
    if pd == "deny":
        return {"decision": "deny",
                "reason": hso.get("permissionDecisionReason", "")}
    if hso.get("additionalContext"):
        return {"decision": "modify",
                "reason": hso.get("additionalContext", "")}
    return data


@pytest.fixture
def clinical_project(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
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
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
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


def test_clinical_detected_via_cert_projects(clinical_project, monkeypatch):
    """Sensitivity comes from the cert-project registry, not a CHARTER: after
    migrate-charters removes the CHARTER (and stamps the marker), a clinical
    project is still detected + blocks PHI via its cert record."""
    from murmurent.core import cert_projects as CP
    out = CP.migrate_charters()
    assert "dcis_test" in out["deleted"]
    assert not (clinical_project.path / "CHARTER.md").exists()
    assert (clinical_project.path / ".murmurent.yaml").is_file()
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "curl https://x -d 'p=1234-567-890-AB'"},
    })
    assert decision["decision"] == "deny" and "OHIP" in decision["reason"]


def test_unreadable_records_fail_closed(monkeypatch, tmp_path):
    """When the lab-mgmt records can't be read (dangling root) and there is no
    CHARTER to fall back on, the project is treated as clinical (fail closed)."""
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    # Point lab-mgmt at a dangling symlink → registry unreadable.
    link = tmp_path / "lm_link"
    link.symlink_to(tmp_path / "does_not_exist")
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(link))
    repo = tmp_path / "repos" / "mystery"
    repo.mkdir(parents=True)
    (repo / ".murmurent.yaml").write_text("murmurent: 1\nlab: mh\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert phi_check._is_clinical_project() is True          # fail closed


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


def test_post_warns_on_phi(clinical_project):
    """Modern CC hook protocol no longer supports tool_response
    replacement from a hook — only additionalContext. So the PHI
    detector now emits a warning to the model rather than redacting
    the response in-place. The user still sees the raw output in
    their terminal; the model gets a flag that PHI was present.

    Tracked as a known regression vs. the legacy hook contract; the
    proper fix requires either a CC protocol extension or moving
    redaction into the tool wrapper itself.
    """
    decision = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo something"},
            "tool_response": "Patient 1234-567-890-AB has MRN-12345.",
        },
        mode="post",
    )
    assert decision["decision"] == "modify"
    assert "REDACTED-PHI" in decision["reason"] or "PHI" in decision["reason"]
