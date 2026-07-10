"""
Tests for `core.security_acl` + `core.security_tier2`.

Uses fixture snapshot text built from Dr. Dumeaux's NFSv4 reference
(see docs/security-dashboard.md). The dump format is `nfs4_getfacl -R`:

    # file: /root/data4/lab_vm/raw
    A:fdg:Users@uwo.ca:tcy
    D:fdi:OWNER@:Dd
    ...
    # file: /root/data4/lab_vm/raw/dcis/sample.bam
    A:fi:OWNER@:rxtTcy
    ...

The diff functions must:
  - emit RAW-DENY-DELETE-MISSING-01 when raw/<dir> lacks D:fdi:{OWNER,GROUP}@:Dd
  - emit RAW-FILE-WRITABLE-01 when a raw/<file> has w/a/D/C on OWNER@/GROUP@ allow ACEs
  - emit REFINED-EXCEPTION-DETECTED-01 when refined/<dir> has GROUP@ ≤ tcy
  - NOT emit drift findings on properly-configured directories.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from murmurent.core import security_acl as A
from murmurent.core import security_tier2 as T2
from murmurent.core.security_findings import (
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SNAPSHOT,
    TIER_2,
)


# ---- Parser ---------------------------------------------------------------

def test_parse_single_ace_line():
    text = (
        "# file: /root/data4/lab_vm/raw\n"
        "A:fdg:Users@uwo.ca:tcy\n"
    )
    out = A.parse_nfs4_getfacl(text)
    assert len(out) == 1
    assert out[0].path == "/root/data4/lab_vm/raw"
    assert len(out[0].aces) == 1
    ace = out[0].aces[0]
    assert ace.type == "A"
    assert ace.flags == "fdg"
    assert ace.principal == "Users@uwo.ca"
    assert ace.perms == "tcy"
    assert ace.is_group_principal


def test_parse_handles_empty_flags():
    text = (
        "# file: /x\n"
        "A::OWNER@:rwaDdxtTnNcCoy\n"
    )
    out = A.parse_nfs4_getfacl(text)
    ace = out[0].aces[0]
    assert ace.flags == ""
    assert ace.principal == "OWNER@"


def test_parse_multiple_files():
    text = (
        "# file: /root/data4/lab_vm/raw\n"
        "D:fdi:OWNER@:Dd\n"
        "D:fdi:GROUP@:Dd\n"
        "A::OWNER@:rwaDdxtTnNcCoy\n"
        "\n"
        "# file: /root/data4/lab_vm/raw/dcis/x.bam\n"
        "A:fi:OWNER@:rxtTcy\n"
        "A:fi:GROUP@:rxtTcy\n"
    )
    out = A.parse_nfs4_getfacl(text)
    assert len(out) == 2
    assert len(out[0].aces) == 3
    assert len(out[1].aces) == 2


def test_parse_tolerates_extra_comments_and_blanks():
    text = (
        "# file: /x\n"
        "# owner: mhallet\n"
        "# group: ssmd-ud-vmlab\n"
        "\n"
        "A::OWNER@:rwa\n"
    )
    out = A.parse_nfs4_getfacl(text)
    assert len(out[0].aces) == 1


def test_parse_skips_malformed_lines():
    text = (
        "# file: /x\n"
        "A::OWNER@:rwa\n"
        "garbage line that is not an ACE\n"
        "A::GROUP@:r\n"
    )
    out = A.parse_nfs4_getfacl(text)
    # Garbage line skipped, both real ACEs kept.
    assert len(out[0].aces) == 2


# ---- diff_raw -------------------------------------------------------------

# Canonical raw/ root ACL (Dumeaux's template).
RAW_ROOT_OK = (
    "# file: /root/data4/lab_vm/raw\n"
    "D::OWNER@:Dd\n"
    "D::GROUP@:Dd\n"
    "D:fdi:OWNER@:Dd\n"
    "D:fdi:GROUP@:Dd\n"
    "A::OWNER@:rwaDdxtTnNcCoy\n"
    "A::GROUP@:rwaxtTnNcy\n"
    "A:di:OWNER@:rwaDdxtTnNcCoy\n"
    "A:di:GROUP@:rwaxtTnNcy\n"
    "A:fi:OWNER@:rxtTcy\n"
    "A:fi:GROUP@:rxtTcy\n"
)

# Same root WITHOUT the inherited Deny-delete (drift).
RAW_ROOT_MISSING_DENY = (
    "# file: /root/data4/lab_vm/raw\n"
    "A::OWNER@:rwaDdxtTnNcCoy\n"
    "A::GROUP@:rwaxtTnNcy\n"
    "A:di:OWNER@:rwaDdxtTnNcCoy\n"
)

# A file under raw with the canonical inherited read-only ACEs (OK).
RAW_FILE_OK = (
    "# file: /root/data4/lab_vm/raw/dcis/sample.bam\n"
    "A::OWNER@:rxtTcy\n"
    "A::GROUP@:rxtTcy\n"
)

# Same file but with a write bit on OWNER@ (defect).
RAW_FILE_WRITABLE = (
    "# file: /root/data4/lab_vm/raw/dcis/leaked.bam\n"
    "A::OWNER@:rwxtTcy\n"   # has 'w' — forbidden
    "A::GROUP@:rxtTcy\n"
)


def test_diff_raw_passes_canonical_root():
    acls = A.parse_nfs4_getfacl(RAW_ROOT_OK)
    out = A.diff_raw(acls, host="biodatsci")
    # No RAW-DENY-DELETE-MISSING-01 — both inherited Deny ACEs present.
    rules = {f.rule for f in out}
    assert "RAW-DENY-DELETE-MISSING-01" not in rules
    # All findings (if any) are info-level (e.g. unexpected principals — none here).
    assert all(f.severity != SEVERITY_BLOCK for f in out)


def test_diff_raw_flags_missing_deny_inheritance():
    acls = A.parse_nfs4_getfacl(RAW_ROOT_MISSING_DENY)
    out = A.diff_raw(acls, host="biodatsci")
    # OWNER@ AND GROUP@ both missing -> two findings.
    deny_findings = [f for f in out if f.rule == "RAW-DENY-DELETE-MISSING-01"]
    assert len(deny_findings) == 2
    for f in deny_findings:
        assert f.severity == SEVERITY_BLOCK
        assert f.source == SOURCE_SNAPSHOT
        assert f.tier == TIER_2
        # Path rewritten to v3 mount.
        assert f.path == "/data/lab_vm/raw"
        # Suggested fix mentions the v4 path so the PI knows where to act.
        assert "nfs4_setfacl" in f.suggested_fix


def test_diff_raw_passes_read_only_file():
    acls = A.parse_nfs4_getfacl(RAW_FILE_OK)
    out = A.diff_raw(acls, host="biodatsci")
    # No RAW-FILE-WRITABLE-01.
    assert not any(f.rule == "RAW-FILE-WRITABLE-01" for f in out)


def test_diff_raw_flags_writable_file():
    acls = A.parse_nfs4_getfacl(RAW_FILE_WRITABLE)
    out = A.diff_raw(acls, host="biodatsci")
    writable = [f for f in out if f.rule == "RAW-FILE-WRITABLE-01"]
    assert len(writable) == 1
    f = writable[0]
    assert f.severity == SEVERITY_BLOCK
    assert "forbidden bits" in f.current_state
    assert "w" in f.current_state
    assert f.project == "dcis"  # extracted from path


def test_diff_raw_flags_unexpected_principal():
    text = (
        "# file: /root/data4/lab_vm/raw\n"
        "A::OWNER@:rwa\n"
        "A:fdg:somebody_random@uwo.ca:rwx\n"
    )
    acls = A.parse_nfs4_getfacl(text)
    out = A.diff_raw(acls, host="biodatsci")
    unexpected = [f for f in out if f.rule == "RAW-UNEXPECTED-PRINCIPAL-01"]
    assert len(unexpected) == 1
    assert unexpected[0].severity == SEVERITY_INFO


# ---- diff_refined ---------------------------------------------------------

REFINED_ROOT_OK = (
    "# file: /root/data4/lab_vm/refined\n"
    "A::OWNER@:rwaDxtTnNcCy\n"
    "A::GROUP@:rwaDxtTnNcy\n"
    "A::EVERYONE@:tcy\n"
    "A:fdg:Administrators@uwo.ca:rwaDdxtTnNcCoy\n"
    "A::OWNER@:rwaDdxtTnNcCoy\n"
    "A:fdi:OWNER@:rwaDdxtTnNcCoy\n"
    "A:fdg:Users@uwo.ca:rxtncy\n"
    "A:dg:Users@uwo.ca:way\n"
)

REFINED_BC_DCIS_EXCEPTION = (
    "# file: /root/data4/lab_vm/refined/bc_dcis\n"
    "A:fd:emucaki@uwo.ca:rwaDdxtTnNcCoy\n"
    "A:fd:OWNER@:rwaDdxtTnNcCoy\n"
    "A:fd:vdumeaux@uwo.ca:rwaDdxtTnNcCoy\n"
    "A:fdg:Administrators@uwo.ca:rwaDdxtTnNcCoy\n"
    "A::OWNER@:tcy\n"
    "A::GROUP@:tcy\n"   # <-- metadata-only GROUP@ -> exception pattern
    "A::EVERYONE@:tcy\n"
)


def test_diff_refined_passes_canonical_root():
    acls = A.parse_nfs4_getfacl(REFINED_ROOT_OK)
    out = A.diff_refined(acls, host="biodatsci")
    drift = [f for f in out if f.rule == "REFINED-PATTERN-DRIFT-01"]
    assert drift == []


def test_diff_refined_flags_pattern_drift_when_uwo_users_absent():
    # Strip the Users@uwo.ca ACEs -> drift.
    text = "\n".join(
        line for line in REFINED_ROOT_OK.splitlines()
        if "Users@uwo.ca" not in line
    ) + "\n"
    acls = A.parse_nfs4_getfacl(text)
    out = A.diff_refined(acls, host="biodatsci")
    drift = [f for f in out if f.rule == "REFINED-PATTERN-DRIFT-01"]
    assert len(drift) == 1
    assert drift[0].severity == SEVERITY_WARN


def test_diff_refined_detects_bc_dcis_exception():
    acls = A.parse_nfs4_getfacl(REFINED_BC_DCIS_EXCEPTION)
    out = A.diff_refined(acls, host="biodatsci")
    exc = [f for f in out if f.rule == "REFINED-EXCEPTION-DETECTED-01"]
    assert len(exc) == 1
    f = exc[0]
    assert f.severity == SEVERITY_INFO          # PI vets, not auto-drift
    assert f.project == "bc_dcis"
    assert "metadata-only" in f.current_state


# ---- Tier 2 consumer ------------------------------------------------------

def _build_fixture_snapshot(tmp_path: Path, *, generated_at: str = "2026-05-19T12:00:00Z") -> Path:
    """Create a directory mirroring lab_sec_dump.sh output, with content
    that exercises every section of the consumer."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "manifest.json").write_text(json.dumps({
        "script_version": "1",
        "generated_at": generated_at,
        "hostname": "biodatsci",
        "output_dir": str(snap),
        "lab_group": "ssmd-ud-vmlab",
        "v4_root": "/root/data4/lab_vm",
        "attempts": [],
    }), encoding="utf-8")
    (snap / "acls_raw.txt").write_text(RAW_ROOT_MISSING_DENY + RAW_FILE_WRITABLE,
                                         encoding="utf-8")
    (snap / "acls_refined.txt").write_text(REFINED_ROOT_OK + REFINED_BC_DCIS_EXCEPTION,
                                            encoding="utf-8")
    (snap / "sshd_runtime.txt").write_text(
        "passwordauthentication yes\n"           # block-severity defect
        "permitrootlogin yes\n"                  # warn
        "permitemptypasswords no\n"
        "pubkeyauthentication yes\n",
        encoding="utf-8",
    )
    # 4 keys across 2 users: alice has ssh-rsa (weak); bob has ed25519 only.
    keys = [
        {"user": "alice", "type": "ssh-rsa", "comment": "alice@old-mac",
         "authorized_keys_mode": "600",
         "authorized_keys_mtime": _dt.datetime(2025, 1, 1).timestamp()},
        {"user": "alice", "type": "ssh-ed25519", "comment": "alice@new",
         "authorized_keys_mode": "600",
         "authorized_keys_mtime": _dt.datetime(2025, 1, 1).timestamp()},
        {"user": "bob", "type": "ssh-ed25519", "comment": "bob@laptop",
         "authorized_keys_mode": "644",  # too permissive
         "authorized_keys_mtime": _dt.datetime(2026, 5, 1).timestamp()},
    ]
    (snap / "ssh_keys.jsonl").write_text(
        "\n".join(json.dumps(k) for k in keys) + "\n",
        encoding="utf-8",
    )
    (snap / "auth_summary.json").write_text(json.dumps({
        "alice": {"publickey": 12, "password": 0, "failed": 3, "ips": ["1.1.1.1"]},
        "bob":   {"publickey": 5,  "password": 2, "failed": 250, "ips": ["2.2.2.2"]},
    }), encoding="utf-8")
    return snap


def test_consume_snapshot_aggregates_all_sections(tmp_path):
    snap = _build_fixture_snapshot(tmp_path)
    res = T2.consume_snapshot(snap, host="biodatsci",
                               now=_dt.datetime(2026, 5, 19, 12, 0, 0))
    rules = {f.rule for f in res.findings}
    # ACL section
    assert "RAW-DENY-DELETE-MISSING-01" in rules
    assert "RAW-FILE-WRITABLE-01" in rules
    assert "REFINED-EXCEPTION-DETECTED-01" in rules
    # sshd section
    assert "SSHD-PWAUTH-01" in rules
    assert "SSHD-ROOTLOGIN-01" in rules
    # ssh keys section
    assert "AUTH-WEAK-KEYS-LAB-01" in rules
    assert "SSH-AUTHKEYS-PERM-LAB-01" in rules
    # auth.log section
    assert "AUTH-PWD-ATTEMPTS-01" in rules
    assert "AUTH-FAILED-BURST-01" in rules
    # Every Tier 2 finding carries source=snapshot + tier=tier2.
    assert all(f.source == SOURCE_SNAPSHOT for f in res.findings)
    assert all(f.tier == TIER_2 for f in res.findings)


def test_consume_snapshot_missing_files_does_not_abort(tmp_path):
    snap = tmp_path / "minimal"
    snap.mkdir()
    (snap / "manifest.json").write_text(json.dumps({
        "script_version": "1",
        "generated_at": "2026-05-19T12:00:00Z",
        "attempts": [],
    }), encoding="utf-8")
    res = T2.consume_snapshot(snap, host="biodatsci")
    # No findings (nothing to consume) but no exception either.
    assert isinstance(res.findings, list)
    # Warnings list every missing section.
    assert any("acls_raw" in w for w in res.warnings)


def test_consume_snapshot_warns_on_unsupported_script_version(tmp_path):
    snap = tmp_path / "future"
    snap.mkdir()
    (snap / "manifest.json").write_text(json.dumps({
        "script_version": "99",
        "generated_at": "2026-05-19T12:00:00Z",
        "attempts": [],
    }), encoding="utf-8")
    res = T2.consume_snapshot(snap, host="biodatsci")
    assert any("script_version" in w for w in res.warnings)


def test_consume_snapshot_emits_stale_warning_after_30_days(tmp_path):
    snap = _build_fixture_snapshot(
        tmp_path, generated_at="2026-04-01T12:00:00Z",
    )
    res = T2.consume_snapshot(
        snap, host="biodatsci",
        now=_dt.datetime(2026, 5, 19, 12, 0, 0),
    )
    assert any(f.rule == "TIER2-SNAPSHOT-STALE-01" for f in res.findings)
    assert res.snapshot_age_hours > 24 * 30


# ---- Phase 1c: per-core ACL diff routing -----------------------------------

def test_consume_snapshot_routes_per_core_acl_files(tmp_path):
    """A v7 snapshot may contain acls_core_<core>_<kind>.txt per core.
    The consumer should diff each, retag rule ids with the CORE- prefix,
    and set the project field to the core's name so the dashboard
    groups findings by core.
    """
    snap = _build_fixture_snapshot(tmp_path)
    # Add a per-core raw dump that's missing the inherited Deny ACEs
    # (same shape as RAW_ROOT_MISSING_DENY but for biocore).
    (snap / "acls_core_biocore_raw.txt").write_text(
        "# file: /root/data4/lab_vm/wigamig/core/biocore/raw\n"
        "A::OWNER@:rwaDdxtTnNcCoy\n"
        "A::GROUP@:rwaxtTnNcy\n"
        "A:di:OWNER@:rwaDdxtTnNcCoy\n",
        encoding="utf-8",
    )
    res = T2.consume_snapshot(snap, host="biodatsci",
                              now=_dt.datetime(2026, 5, 19, 12, 0, 0))
    core_findings = [f for f in res.findings if f.category == "core_raw"]
    assert len(core_findings) >= 1
    # Rule was retagged.
    rules = {f.rule for f in core_findings}
    assert "CORE-RAW-DENY-DELETE-MISSING-01" in rules
    # project field carries the core's short id.
    assert all(f.project == "biocore" for f in core_findings)
    # rule_doc_anchor points at the new rule id, not the lab one.
    assert all("CORE-RAW-" in f.rule_doc_anchor for f in core_findings)


def test_consume_snapshot_handles_no_core_files_gracefully(tmp_path):
    """A v6 snapshot (no per-core files) shouldn't break the consumer.
    Just no core findings, and the legacy lab findings still flow."""
    snap = _build_fixture_snapshot(tmp_path)
    res = T2.consume_snapshot(snap, host="biodatsci",
                              now=_dt.datetime(2026, 5, 19, 12, 0, 0))
    core_findings = [f for f in res.findings
                     if f.category in ("core_raw", "core_refined")]
    assert core_findings == []
    # Lab-level findings still present.
    assert any(f.rule == "RAW-DENY-DELETE-MISSING-01" for f in res.findings)


def test_consume_snapshot_per_core_refined_exception(tmp_path):
    """A core's refined/<project>/ with the locked-down GROUP@ pattern
    (bc_dcis-style) gets CORE-REFINED-EXCEPTION-DETECTED-01."""
    snap = _build_fixture_snapshot(tmp_path)
    (snap / "acls_core_biocore_refined.txt").write_text(
        REFINED_ROOT_OK.replace(
            "/root/data4/lab_vm/refined",
            "/root/data4/lab_vm/wigamig/core/biocore/refined",
        )
        + REFINED_BC_DCIS_EXCEPTION.replace(
            "/root/data4/lab_vm/refined/bc_dcis",
            "/root/data4/lab_vm/wigamig/core/biocore/refined/locked_project",
        ),
        encoding="utf-8",
    )
    res = T2.consume_snapshot(snap, host="biodatsci",
                              now=_dt.datetime(2026, 5, 19, 12, 0, 0))
    core_refined = [f for f in res.findings if f.category == "core_refined"]
    rules = {f.rule for f in core_refined}
    assert "CORE-REFINED-EXCEPTION-DETECTED-01" in rules
    # Per-core findings tagged with core name as the project.
    assert all(f.project == "biocore" for f in core_refined)


def test_supported_versions_includes_v7():
    assert "7" in T2.SUPPORTED_SCRIPT_VERSIONS
