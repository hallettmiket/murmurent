"""Tests for :mod:`wigamig.hooks.audit`."""

from __future__ import annotations

import datetime as _dt
import io
import json

import pytest

from wigamig.hooks import audit


def test_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("WIGAMIG_AUDIT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "outcome": "ok",
        "duration_ms": 12,
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = audit.main(stdin=stdin, stdout=stdout)
    assert code == 0
    assert json.loads(stdout.getvalue())["decision"] == "allow"

    today = _dt.date.today().isoformat()
    log_path = tmp_path / f"{today}.log"
    assert log_path.is_file()
    line = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["member"] == "@allie"
    assert entry["tool"] == "Bash"
    assert "ls" in entry["args_summary"]


def test_truncates_long_args(tmp_path, monkeypatch):
    monkeypatch.setenv("WIGAMIG_AUDIT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    big = "x" * 5000
    payload = {"tool_name": "Bash", "tool_input": {"command": big}}
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    audit.main(stdin=stdin, stdout=stdout)
    today = _dt.date.today().isoformat()
    line = (tmp_path / f"{today}.log").read_text(encoding="utf-8").splitlines()[-1]
    entry = json.loads(line)
    assert len(entry["args_summary"]) <= 200
