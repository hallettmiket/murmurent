"""Tests for :mod:`wigamig.hooks.context_inject`."""

from __future__ import annotations

import io
import json

import pytest

from wigamig.commands import project_cmd, sea_cmd
from wigamig.core.projects import find_project
from wigamig.hooks import context_inject


@pytest.fixture
def project_with_seas(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie,@bob,@cassie",
        description="A fake project for the smoke test. Edit me later.",
        sensitivity="standard",
        lead="@allie",
        skip_github=True,
    )
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="analysis", description="run X")
    repo = find_project("p")
    monkeypatch.chdir(repo.path)
    return repo


def _context(stdout: io.StringIO) -> str:
    """Pull additionalContext from the CC-modern hook output. Returns
    empty string when the hook chose to inject nothing (= allow)."""
    raw = stdout.getvalue().strip()
    if not raw:
        return ""
    data = json.loads(raw)
    return (data.get("hookSpecificOutput") or {}).get("additionalContext", "")


def test_injects_when_inside_project(project_with_seas):
    payload = {"user_prompt": "what's next?"}
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = context_inject.main(stdin=stdin, stdout=stdout)
    assert code == 0
    ctx = _context(stdout)
    # CC keeps the user_prompt verbatim; we only contribute extra context.
    assert "<system-reminder>" in ctx
    assert "project: p" in ctx
    assert "@allie" in ctx
    assert "SEAs you filed" in ctx


def test_no_injection_outside_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = {"user_prompt": "hi"}
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = context_inject.main(stdin=stdin, stdout=stdout)
    assert code == 0
    # Empty stdout == allow (no injection).
    assert stdout.getvalue() == ""


def test_role_lead_for_charter_lead(project_with_seas):
    payload = {"user_prompt": "..."}
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    context_inject.main(stdin=stdin, stdout=stdout)
    assert "(lead)" in _context(stdout)
