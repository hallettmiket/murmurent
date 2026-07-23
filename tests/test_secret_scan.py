"""
Purpose: Tests for `core.secret_scan` (deterministic secret-CONTENT scanner)
         and the `murmurent security secrets-scan` CLI gate.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-23
Input: pytest `tmp_path` + a real temp git repo for staged-scan tests.
Output: pytest cases covering detectors, placeholder/allowlist suppression,
        staged-vs-working-tree scanning, and the CLI exit-code contract.
"""

from __future__ import annotations

import subprocess

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core.secret_scan import (
    HISTORY_TRUNCATED_RULE,
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    redact,
    scan_file,
    scan_history,
    scan_staged,
    scan_text,
)

# A synthetic AWS key id: AKIA + exactly 16 uppercase-alnum chars (valid
# shape, not a real credential).
FAKE_AWS = "AKIA" + "IOSFODNN7ABCD123"
# A synthetic classic GitHub PAT (36 chars after ghp_).
FAKE_GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
PRIVATE_KEY_LINE = "-----BEGIN RSA PRIVATE KEY-----"


def _rules(hits) -> set[str]:
    return {h.rule for h in hits}


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def test_detects_private_key_block():
    hits = scan_text(f"{PRIVATE_KEY_LINE}\nMIIEpAIBAAKC...\n", "key.pem")
    assert any(h.rule == "PRIVATE-KEY-BLOCK" and h.severity == SEVERITY_BLOCK
               for h in hits)


def test_detects_aws_access_key():
    hits = scan_text(f'aws_key = "{FAKE_AWS}"\n', "cfg.py")
    assert "AWS-ACCESS-KEY-ID" in _rules(hits)
    block = [h for h in hits if h.rule == "AWS-ACCESS-KEY-ID"][0]
    assert block.severity == SEVERITY_BLOCK
    # Never emit the raw secret.
    assert FAKE_AWS not in block.redacted
    assert block.redacted.startswith("AKIA")


def test_detects_github_token():
    hits = scan_text(f'TOKEN={FAKE_GHP}\n', "deploy.sh")
    assert "GITHUB-PAT-CLASSIC" in _rules(hits)


def test_detects_generic_api_key_assignment_as_warn():
    hits = scan_text('api_key = "s3cr3tValue12345"\n', "settings.py")
    warns = [h for h in hits if h.rule == "GENERIC-SECRET-ASSIGNMENT"]
    assert warns and warns[0].severity == SEVERITY_WARN
    assert "s3cr3tValue12345" not in warns[0].redacted


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

def test_placeholder_value_not_flagged():
    hits = scan_text('API_KEY = "your-key-here"\n', "settings.py")
    assert hits == []


def test_env_indirection_not_flagged():
    hits = scan_text('api_key = os.environ["API_KEY"]\n', "settings.py")
    # os.environ isn't a quoted literal at all, but guard anyway.
    assert not any(h.rule == "GENERIC-SECRET-ASSIGNMENT" for h in hits)


def test_allowlist_pragma_suppresses_line():
    line = f'api_key = "s3cr3tValue12345"  # pragma: allowlist secret\n'
    assert scan_text(line, "settings.py") == []


def test_noqa_secret_suppresses_line():
    line = f'token = "{FAKE_GHP}"  # noqa: secret\n'
    assert scan_text(line, "deploy.sh") == []


def test_redact_never_reveals_full_value():
    r = redact("AKIAIOSFODNN7ABCDEFGH")
    assert "IOSFODNN" not in r
    assert r.startswith("AKIA") and r.endswith("FGH")


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def test_scan_file_skips_binary(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01" + FAKE_AWS.encode() + b"\x00")
    assert scan_file(f) == []


def test_scan_file_reads_text(tmp_path):
    f = tmp_path / "cfg.py"
    f.write_text(f'aws = "{FAKE_AWS}"\n')
    assert "AWS-ACCESS-KEY-ID" in _rules(scan_file(f))


# ---------------------------------------------------------------------------
# Staged scanning (real temp git repo)
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def test_scan_staged_finds_secret_in_staged_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "cfg.py").write_text(f'aws = "{FAKE_AWS}"\n')
    _git(repo, "add", "cfg.py")
    hits = scan_staged(repo)
    assert "AWS-ACCESS-KEY-ID" in _rules(hits)
    assert hits[0].path == "cfg.py"


def test_scan_staged_ignores_working_tree_only_secret(tmp_path):
    repo = _init_repo(tmp_path)
    # Commit a clean file, stage nothing new.
    (repo / "cfg.py").write_text("clean = 1\n")
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "init")
    # Now write a secret to the working tree WITHOUT staging it.
    (repo / "cfg.py").write_text(f'aws = "{FAKE_AWS}"\n')
    hits = scan_staged(repo)
    assert hits == []


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------

def test_cli_exits_2_on_block_hit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "cfg.py").write_text(f'aws = "{FAKE_AWS}"\n')
    _git(repo, "add", "cfg.py")
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Run with cwd inside the repo so --staged sees it.
        import os
        os.chdir(repo)
        result = runner.invoke(cli, ["security", "secrets-scan", "--staged"])
    assert result.exit_code == 2
    assert FAKE_AWS not in result.output  # never leak the raw secret


def test_cli_exits_0_when_clean(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "cfg.py").write_text("clean = 1\n")
    _git(repo, "add", "cfg.py")
    runner = CliRunner()
    with runner.isolated_filesystem():
        import os
        os.chdir(repo)
        result = runner.invoke(cli, ["security", "secrets-scan", "--staged"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Git-history walk (real temp git repo)
# ---------------------------------------------------------------------------

def test_scan_history_finds_secret_committed_then_deleted(tmp_path):
    repo = _init_repo(tmp_path)
    # Commit a secret...
    (repo / "cfg.py").write_text(f'aws = "{FAKE_AWS}"\n')
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "add secret")
    # ...then delete the file in a later commit.
    _git(repo, "rm", "-q", "cfg.py")
    _git(repo, "commit", "-q", "-m", "remove secret")
    # A clean commit on top, so HEAD's tree has no secret at all.
    (repo / "ok.py").write_text("clean = 1\n")
    _git(repo, "add", "ok.py")
    _git(repo, "commit", "-q", "-m", "clean")

    hits = scan_history(repo)
    real = [h for h in hits if h.rule != HISTORY_TRUNCATED_RULE]
    assert "AWS-ACCESS-KEY-ID" in _rules(real)
    # It records the file, a commit-ish, and never the raw secret.
    hit = next(h for h in real if h.rule == "AWS-ACCESS-KEY-ID")
    assert hit.path == "cfg.py"
    assert hit.commit  # some commit-ish attributed
    assert FAKE_AWS not in hit.redacted


def test_scan_history_clean_repo_has_no_secret_hits(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "ok.py").write_text("clean = 1\n")
    _git(repo, "add", "ok.py")
    _git(repo, "commit", "-q", "-m", "clean")
    hits = scan_history(repo)
    assert [h for h in hits if h.rule != HISTORY_TRUNCATED_RULE] == []


def test_scan_history_bounded_emits_truncation_notice(tmp_path):
    repo = _init_repo(tmp_path)
    for i in range(4):
        (repo / f"f{i}.py").write_text(f"x = {i}\n")
        _git(repo, "add", f"f{i}.py")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    # Cap below the commit count → must flag truncation, never a secret.
    hits = scan_history(repo, max_commits=1)
    assert any(h.rule == HISTORY_TRUNCATED_RULE for h in hits)
    assert all(h.severity == "info" for h in hits
               if h.rule == HISTORY_TRUNCATED_RULE)


def test_scan_history_not_a_git_repo_returns_empty(tmp_path):
    # No git init here — scan_history must degrade gracefully, not raise.
    assert scan_history(tmp_path) == []


def test_scan_history_respects_allowlist_pragma(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "cfg.py").write_text(
        f'aws = "{FAKE_AWS}"  # pragma: allowlist secret\n')
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "suppressed")
    hits = scan_history(repo)
    assert [h for h in hits if h.rule != HISTORY_TRUNCATED_RULE] == []


def test_cli_history_flag_exits_2_on_block_hit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "cfg.py").write_text(f'aws = "{FAKE_AWS}"\n')
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "add secret")
    _git(repo, "rm", "-q", "cfg.py")
    _git(repo, "commit", "-q", "-m", "remove secret")
    runner = CliRunner()
    with runner.isolated_filesystem():
        import os
        os.chdir(repo)
        result = runner.invoke(cli, ["security", "secrets-scan", "--history"])
    assert result.exit_code == 2
    assert FAKE_AWS not in result.output  # never leak the raw secret
