"""Tests for :mod:`wigamig.hooks.raw_guard` (the raw-data guard CC hook)."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from wigamig.hooks import raw_guard


def _run(payload: dict, env: dict[str, str] | None = None) -> dict:
    """Pipe ``payload`` through the hook and return the parsed decision."""
    if env is not None:
        os.environ.update(env)
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = raw_guard.main(stdin=stdin, stdout=stdout)
    assert code == 0
    return json.loads(stdout.getvalue())


def test_write_into_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz")},
    }
    decision = _run(payload)
    assert decision["decision"] == "deny"
    assert "raw" in decision["reason"].lower()


def test_write_outside_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "refined" / "x.csv")},
    }
    assert _run(payload)["decision"] == "allow"


def test_bash_redirect_into_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "log.txt"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo done > {target}"},
    }
    decision = _run(payload)
    assert decision["decision"] == "deny"


def test_bash_rm_on_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"rm {target}"},
    }
    assert _run(payload)["decision"] == "deny"


def test_bash_chmod_writable_on_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"chmod -R u+w {target}"},
    }
    assert _run(payload)["decision"] == "deny"


def test_bash_read_on_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"zcat {target} | head"},
    }
    assert _run(payload)["decision"] == "allow"


def test_read_tool_on_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz")},
    }
    assert _run(payload)["decision"] == "allow"


def test_production_path_blocked_even_with_env(monkeypatch, tmp_path):
    """The production /data/lab_vm/wigamig/raw is always blocked, regardless of env."""
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/data/lab_vm/wigamig/raw/some_proj/exp/x.fastq.gz"},
    }
    assert _run(payload)["decision"] == "deny"


def test_empty_stdin_allows():
    stdout = io.StringIO()
    code = raw_guard.main(stdin=io.StringIO(""), stdout=stdout)
    assert code == 0
    assert json.loads(stdout.getvalue())["decision"] == "allow"
