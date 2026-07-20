"""Tests for :mod:`murmurent.hooks.raw_guard` (the raw-data guard CC hook)."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from murmurent.hooks import raw_guard


def _run(payload: dict, env: dict[str, str] | None = None) -> dict:
    """Pipe ``payload`` through the hook and return a normalised
    decision dict in the legacy ``{"decision": "allow"|"deny", "reason": ...}``
    shape so older test assertions keep working.

    CC's modern wire format is ``hookSpecificOutput.permissionDecision``
    for denies and empty stdout for allows; this helper translates back
    so we don't have to rewrite every test."""
    if env is not None:
        os.environ.update(env)
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = raw_guard.main(stdin=stdin, stdout=stdout)
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
    return data   # unchanged for unfamiliar shapes


def test_write_into_legacy_raw_denied(monkeypatch, tmp_path):
    """Dual-name: the legacy raw/ tree is still blocked."""
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz")},
    }
    decision = _run(payload)
    assert decision["decision"] == "deny"
    assert "immutable" in decision["reason"].lower()


def test_write_into_immutable_denied(monkeypatch, tmp_path):
    """The new immutable/ tree is blocked."""
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "immutable" / "p" / "1_e" / "x.fastq.gz")},
    }
    assert _run(payload)["decision"] == "deny"


def test_new_env_var_honored(monkeypatch, tmp_path):
    """MURMURENT_DATA_ROOT resolves the immutable tree for the hook."""
    monkeypatch.delenv("MURMURENT_LAB_VM_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    for sub in ("immutable", "raw"):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / sub / "p" / "1_e" / "x.fastq.gz")},
        }
        assert _run(payload)["decision"] == "deny"


def test_write_outside_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "refined" / "x.csv")},
    }
    assert _run(payload)["decision"] == "allow"


def test_bash_redirect_into_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "log.txt"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo done > {target}"},
    }
    decision = _run(payload)
    assert decision["decision"] == "deny"


def test_bash_rm_on_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"rm {target}"},
    }
    assert _run(payload)["decision"] == "deny"


def test_bash_chmod_writable_on_raw_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"chmod -R u+w {target}"},
    }
    assert _run(payload)["decision"] == "deny"


def test_bash_read_on_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    target = tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"zcat {target} | head"},
    }
    assert _run(payload)["decision"] == "allow"


def test_read_tool_on_raw_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "raw" / "p" / "1_e" / "x.fastq.gz")},
    }
    assert _run(payload)["decision"] == "allow"


def test_stale_wigamig_path_no_longer_hardcoded(monkeypatch, tmp_path):
    """The stale ``/data/lab_vm/wigamig/raw`` branding was removed; protection now
    follows the configured data root only, not a hardcoded lab-specific path."""
    monkeypatch.delenv("MURMURENT_DATA_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/data/lab_vm/wigamig/raw/some_proj/exp/x.fastq.gz"},
    }
    assert _run(payload)["decision"] == "allow"


def test_empty_stdin_allows():
    """CC modern protocol: empty stdout == allow."""
    stdout = io.StringIO()
    code = raw_guard.main(stdin=io.StringIO(""), stdout=stdout)
    assert code == 0
    assert stdout.getvalue() == ""
