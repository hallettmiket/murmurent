"""Tests for ``wigamig oracle publish`` (personal vault → Lab Oracle).

Covers the contract spelled out in [agents/oracle.md][1] and
[rules/oracle_schema.md][2]:

  - Required schema fields enforced before any file movement
  - sensitivity=clinical|restricted refused outright
  - Slug collision in lab_mgmt/oracle/ blocks publish
  - Successful publish copies the file, commits with the committer
    handle in the message, and removes the vault draft
  - Date prefix is added when the slug doesn't already have one

We use a real git repo under tmp_path so the commit step gets a true
exit code; the alternative (mocking subprocess) would mask actual git
misuse.

[1]: ../agents/oracle.md
[2]: ../rules/oracle_schema.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wigamig.core import oracle_publish as _op


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Stand up an isolated personal-vault + lab-mgmt repo on disk.

    The lab-mgmt is a real git repo with a single seed commit so
    ``git commit`` has a parent to attach to. The personal-vault drafts
    dir is empty until a test populates it.
    """
    vault = tmp_path / "vault"
    (vault / "oracle" / "drafts").mkdir(parents=True)
    lab = tmp_path / "lab_mgmt"
    (lab / "oracle").mkdir(parents=True)
    # Real git repo so commit works.
    subprocess.run(["git", "init", "-q"], cwd=lab, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=lab, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=lab, check=True)
    (lab / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=lab, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=lab, check=True)

    monkeypatch.setenv("WIGAMIG_PERSONAL_ORACLE_DIR", str(vault / "oracle"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab))
    return {"vault": vault, "lab": lab}


def _write_draft(world, slug: str, *, sensitivity: str = "standard",
                 extra: str = "", omit: list[str] | None = None) -> Path:
    """Write a draft with valid frontmatter, optionally omitting fields
    or overriding sensitivity. Returns the draft path."""
    omit = omit or []
    fields = {
        "title": "Test entry",
        "date": "2026-05-16",
        "project": "general",
        "sensitivity": sensitivity,
        "tags": ["test", "schema"],
        "sources": ["@the_pi"],
    }
    for k in omit:
        fields.pop(k, None)
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v if not isinstance(v, list) else v}")
    if extra:
        lines.append(extra)
    lines.append("---")
    lines.append("")
    lines.append("# Test entry")
    lines.append("")
    lines.append("Body goes here.")
    p = world["vault"] / "oracle" / "drafts" / f"{slug}.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_publish_copies_commits_and_removes_draft(world):
    _write_draft(world, "chrm_p14_fix")
    result = _op.publish_draft("chrm_p14_fix", committer="@the_pi", commit=True)

    assert result.source.name == "chrm_p14_fix.md"
    # Date prefix added from frontmatter (no prefix on the slug).
    assert result.target.name == "2026-05-16_chrm_p14_fix.md"
    assert result.target.is_file()
    # Source draft removed so the vault doesn't carry duplicates.
    assert not result.source.exists()
    # Real commit landed.
    assert result.commit_sha and len(result.commit_sha) >= 7
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s%n%b"],
        cwd=world["lab"], capture_output=True, text=True, check=True,
    ).stdout
    assert "oracle: publish 'Test entry' from @the_pi" in log
    # File is tracked, no pending changes.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=world["lab"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status == ""


def test_publish_preserves_date_prefix_when_slug_already_dated(world):
    """If the user named their draft 2026-05-16_foo, the date prefix is
    used as-is and not duplicated."""
    _write_draft(world, "2026-05-16_already_dated")
    result = _op.publish_draft("2026-05-16_already_dated", committer="@the_pi")
    assert result.target.name == "2026-05-16_already_dated.md"


def test_dry_run_skips_commit_but_lands_file(world):
    _write_draft(world, "dryrun_entry")
    result = _op.publish_draft("dryrun_entry", committer="@the_pi", commit=False)
    assert result.target.is_file()
    assert result.commit_sha is None
    # File present in workdir but uncommitted.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=world["lab"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status  # untracked file shows up


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------


def test_publish_refuses_clinical_sensitivity(world):
    _write_draft(world, "clinical_finding", sensitivity="clinical")
    with pytest.raises(_op.SensitivityBlocked, match="clinical"):
        _op.publish_draft("clinical_finding", committer="@the_pi")
    # Lab repo untouched.
    assert list((world["lab"] / "oracle").iterdir()) == []
    # Vault draft preserved so the user can re-classify.
    assert (world["vault"] / "oracle" / "drafts" / "clinical_finding.md").exists()


def test_publish_refuses_restricted_sensitivity(world):
    _write_draft(world, "secret_thing", sensitivity="restricted")
    with pytest.raises(_op.SensitivityBlocked):
        _op.publish_draft("secret_thing", committer="@the_pi")


def test_publish_refuses_missing_required_field(world):
    _write_draft(world, "no_project", omit=["project"])
    with pytest.raises(_op.SchemaViolation, match="project"):
        _op.publish_draft("no_project", committer="@the_pi")


def test_publish_refuses_when_target_already_exists(world):
    """Two drafts with the same date+slug would collide in lab_mgmt;
    we refuse rather than silently overwrite an approved lab entry."""
    target = world["lab"] / "oracle" / "2026-05-16_collide.md"
    target.write_text("existing lab entry\n")
    _write_draft(world, "collide")
    with pytest.raises(_op.TargetExists):
        _op.publish_draft("collide", committer="@the_pi")
    # Vault draft preserved.
    assert (world["vault"] / "oracle" / "drafts" / "collide.md").exists()


def test_publish_refuses_unknown_slug(world):
    with pytest.raises(_op.DraftNotFound):
        _op.publish_draft("never_written", committer="@the_pi")


def test_publish_refuses_invalid_slug_characters(world):
    """Reject shell-suspicious slugs (path traversal, spaces) before
    they reach the filesystem layer."""
    with pytest.raises(_op.OracleError, match="invalid slug"):
        _op.publish_draft("../../etc/passwd", committer="@the_pi")
    with pytest.raises(_op.OracleError, match="invalid slug"):
        _op.publish_draft("has spaces", committer="@the_pi")


# ---------------------------------------------------------------------------
# Listing + path resolution
# ---------------------------------------------------------------------------


def test_iter_vault_drafts_returns_sorted_md_files(world):
    _write_draft(world, "b_draft")
    _write_draft(world, "a_draft")
    (world["vault"] / "oracle" / "drafts" / "not_md.txt").write_text("noise")
    paths = _op.iter_vault_drafts()
    assert [p.name for p in paths] == ["a_draft.md", "b_draft.md"]


def test_iter_vault_drafts_empty_when_dir_missing(world):
    """A fresh install has no drafts/ subdir yet. We return [] rather
    than raising so the CLI can say 'no drafts' instead of erroring."""
    import shutil
    shutil.rmtree(world["vault"] / "oracle" / "drafts")
    assert _op.iter_vault_drafts() == []


def test_personal_oracle_dir_honors_env_override(world):
    """The env var is the canonical override path for tests + scripted
    setups where Obsidian isn't installed."""
    p = _op.personal_oracle_dir()
    assert p == world["vault"] / "oracle"
