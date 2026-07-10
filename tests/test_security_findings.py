"""
Tests for `core.security_findings`: Finding dataclass, JSONL round-trip,
roll-up logic, and remote-side parser.
"""

from __future__ import annotations

import json

import pytest

from murmurent.core.security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_AGENT,
    SOURCE_SCANNER,
    TIER_1,
    TIER_2,
    read_jsonl,
    rollup_by_directory,
    stable_finding_id,
    write_jsonl,
)


def _make(severity="warn", path="/data/lab_vm/raw/dcis/x.bam",
          rule="RAW-IMMUTABLE-01", host="biodatsci", **kw) -> Finding:
    defaults = dict(
        severity=severity, category="raw", rule=rule, host=host, path=path,
        current_state="0664 mhallet:ssmd", expected_state="0444",
        suggested_fix=f"chmod 0444 {path}", detected_at="2026-05-19T12:00:00Z",
    )
    defaults.update(kw)
    return Finding(**defaults)


def test_finding_id_is_stable_and_collision_resistant():
    a = _make(path="/a/b/c", rule="R1")
    b = _make(path="/a/b/c", rule="R1")
    c = _make(path="/a/b/d", rule="R1")
    assert a.id == b.id
    assert a.id != c.id
    assert len(a.id) == 12


def test_stable_finding_id_independent_of_construction():
    fid = stable_finding_id("h1", "/x", "R1")
    assert _make(host="h1", path="/x", rule="R1").id == fid


def test_severity_validation():
    with pytest.raises(ValueError):
        _make(severity="critical")


def test_source_and_tier_validation():
    with pytest.raises(ValueError):
        _make(source="bogus")
    with pytest.raises(ValueError):
        _make(tier="tier3")


def test_jsonl_roundtrip(tmp_path):
    findings = [
        _make(severity=SEVERITY_BLOCK, path="/data/lab_vm/raw/p/a.bam"),
        _make(severity=SEVERITY_WARN, rule="SSH-WEAK-KEY-01",
              category="ssh", path="/home/mhallet/.ssh/authorized_keys:3"),
        _make(severity=SEVERITY_INFO, rule="HOME-SIZE-OK",
              category="home", path="/home/mhallet"),
    ]
    path = tmp_path / "out.jsonl"
    n = write_jsonl(path, findings)
    assert n == 3
    loaded = read_jsonl(path)
    assert len(loaded) == 3
    # ids should be reconstructed identically.
    assert [f.id for f in loaded] == [f.id for f in findings]
    # severities preserved.
    assert [f.severity for f in loaded] == [SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO]


def test_jsonl_skips_garbage_lines(tmp_path):
    path = tmp_path / "messy.jsonl"
    path.write_text(
        "not-json\n"
        + _make().to_json_line() + "\n"
        + json.dumps({"severity": "bogus", "category": "x", "rule": "Y",
                      "host": "h", "path": "/", "current_state": "",
                      "expected_state": "", "suggested_fix": "",
                      "detected_at": ""}) + "\n"   # bad severity -> skipped
        + "\n"
        + _make(rule="R2").to_json_line() + "\n",
        encoding="utf-8",
    )
    loaded = read_jsonl(path)
    assert len(loaded) == 2  # garbage + bad-severity dropped
    assert loaded[0].rule == "RAW-IMMUTABLE-01"
    assert loaded[1].rule == "R2"


def test_read_jsonl_missing_file_returns_empty(tmp_path):
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_from_dict_drops_unknown_fields():
    d = _make().to_dict()
    d["future_field_we_do_not_know"] = 42
    f = Finding.from_dict(d)
    assert f.rule == "RAW-IMMUTABLE-01"


# ---- rollup_by_directory -------------------------------------------------

def test_rollup_collapses_sibling_cluster():
    """Six files in the same parent dir, same rule -> one parent finding."""
    findings = [
        _make(path=f"/data/lab_vm/raw/dcis/sample{i}.bam")
        for i in range(6)
    ]
    out = rollup_by_directory(findings, threshold=5)
    assert len(out) == 1
    rolled = out[0]
    assert rolled.is_directory
    assert rolled.aggregate_count == 6
    assert rolled.path == "/data/lab_vm/raw/dcis"
    assert "chmod -R" in rolled.suggested_fix


def test_rollup_preserves_below_threshold():
    findings = [
        _make(path=f"/data/lab_vm/raw/dcis/sample{i}.bam")
        for i in range(3)
    ]
    out = rollup_by_directory(findings, threshold=5)
    assert len(out) == 3
    assert all(not f.is_directory for f in out)


def test_rollup_preserves_mixed_rules():
    """Cluster only collapses within (rule, parent) groups."""
    findings = [
        _make(rule="R-A", path=f"/x/a/file{i}.txt") for i in range(6)
    ] + [
        _make(rule="R-B", path=f"/x/a/file{i}.txt") for i in range(3)
    ]
    out = rollup_by_directory(findings, threshold=5)
    # R-A → 1 parent row; R-B (3) → 3 individual rows
    assert sum(1 for f in out if f.is_directory) == 1
    assert sum(1 for f in out if not f.is_directory) == 3


def test_rollup_max_severity_wins():
    findings = [
        _make(path="/p/x.txt", severity=SEVERITY_WARN),
        _make(path="/p/y.txt", severity=SEVERITY_BLOCK),
        _make(path="/p/z.txt", severity=SEVERITY_INFO),
        _make(path="/p/w.txt", severity=SEVERITY_WARN),
        _make(path="/p/v.txt", severity=SEVERITY_INFO),
    ]
    out = rollup_by_directory(findings, threshold=5)
    assert len(out) == 1
    assert out[0].severity == SEVERITY_BLOCK


# ---- remote-side parser --------------------------------------------------

def test_security_remote_parses_progress_and_findings():
    from murmurent.core.security_remote import _parse_stream
    stdout = (
        '{"_kind":"progress","message":"starting","ts":"12:00:00"}\n'
        + _make(rule="R1").to_json_line() + "\n"
        + '\n'  # blank
        + 'REMINDER: Please run CPU-intensive processes with nice\n'  # SSH MOTD
        + '{"_kind":"progress","message":"done","ts":"12:00:05"}\n'
        + _make(rule="R2", path="/other").to_json_line() + "\n"
    )
    findings, progress, errors = _parse_stream(stdout)
    assert len(findings) == 2
    assert [f.rule for f in findings] == ["R1", "R2"]
    assert len(progress) == 2
    assert "starting" in progress[0]
    assert "done" in progress[1]
    # Non-JSON banner text (MOTDs, sudo lectures, etc.) is silently
    # dropped — only malformed JSON objects count as parse errors.
    assert errors == []


def test_security_remote_records_malformed_json_object_as_error():
    from murmurent.core.security_remote import _parse_stream
    stdout = (
        _make(rule="R1").to_json_line() + "\n"
        + '{"severity": "warn", "unclosed-brace\n'  # starts with { but invalid
    )
    findings, _progress, errors = _parse_stream(stdout)
    assert len(findings) == 1
    assert len(errors) == 1
    assert "unparseable" in errors[0]
