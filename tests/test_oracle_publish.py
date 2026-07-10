"""Tests for ``murmurent oracle publish`` (personal vault → Lab Oracle).

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

from murmurent.core import oracle_publish as _op


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
        "sources": ["@mhallet"],
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
    result = _op.publish_draft("chrm_p14_fix", committer="@mhallet", commit=True)

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
    assert "oracle: publish 'Test entry' from @mhallet" in log
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
    result = _op.publish_draft("2026-05-16_already_dated", committer="@mhallet")
    assert result.target.name == "2026-05-16_already_dated.md"


def test_dry_run_skips_commit_but_lands_file(world):
    _write_draft(world, "dryrun_entry")
    result = _op.publish_draft("dryrun_entry", committer="@mhallet", commit=False)
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
        _op.publish_draft("clinical_finding", committer="@mhallet")
    # Lab repo untouched.
    assert list((world["lab"] / "oracle").iterdir()) == []
    # Vault draft preserved so the user can re-classify.
    assert (world["vault"] / "oracle" / "drafts" / "clinical_finding.md").exists()


def test_publish_refuses_restricted_sensitivity(world):
    _write_draft(world, "secret_thing", sensitivity="restricted")
    with pytest.raises(_op.SensitivityBlocked):
        _op.publish_draft("secret_thing", committer="@mhallet")


def test_publish_refuses_missing_required_field(world):
    _write_draft(world, "no_project", omit=["project"])
    with pytest.raises(_op.SchemaViolation, match="project"):
        _op.publish_draft("no_project", committer="@mhallet")


def test_publish_refuses_when_target_already_exists(world):
    """Two drafts with the same date+slug would collide in lab_mgmt;
    we refuse rather than silently overwrite an approved lab entry."""
    target = world["lab"] / "oracle" / "2026-05-16_collide.md"
    target.write_text("existing lab entry\n")
    _write_draft(world, "collide")
    with pytest.raises(_op.TargetExists):
        _op.publish_draft("collide", committer="@mhallet")
    # Vault draft preserved.
    assert (world["vault"] / "oracle" / "drafts" / "collide.md").exists()


def test_publish_refuses_unknown_slug(world):
    with pytest.raises(_op.DraftNotFound):
        _op.publish_draft("never_written", committer="@mhallet")


def test_publish_refuses_invalid_slug_characters(world):
    """Reject shell-suspicious slugs (path traversal, spaces) before
    they reach the filesystem layer."""
    with pytest.raises(_op.OracleError, match="invalid slug"):
        _op.publish_draft("../../etc/passwd", committer="@mhallet")
    with pytest.raises(_op.OracleError, match="invalid slug"):
        _op.publish_draft("has spaces", committer="@mhallet")


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


# ---------------------------------------------------------------------------
# probe_personal_oracle — the Full Disk Access read probe (oracle doctor)
# ---------------------------------------------------------------------------


def _write_entry(dir_: Path, name: str) -> Path:
    """Minimal schema-shaped entry — the probe only needs a readable
    ``.md`` file, not valid frontmatter."""
    p = dir_ / name
    p.write_text("---\ntitle: x\n---\n\nbody\n", encoding="utf-8")
    return p


def test_probe_ok_when_entry_is_readable(world):
    """Happy path: dir resolves, an entry exists, and the read succeeds."""
    _write_entry(world["vault"] / "oracle", "2026-05-16_readable.md")
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_OK
    assert probe.sample and probe.sample.endswith("2026-05-16_readable.md")
    assert probe.path == str(world["vault"] / "oracle")


def test_probe_empty_when_dir_has_no_entries(world):
    """Dir resolves + readable but holds no entries yet — a benign state,
    NOT the blocked/FDA failure."""
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_EMPTY


def test_probe_missing_when_dir_absent(world):
    """Resolved path doesn't exist yet (fresh install / agent hasn't
    written). Distinct from 'blocked'."""
    import shutil
    shutil.rmtree(world["vault"] / "oracle")
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_MISSING


def test_probe_unregistered_when_no_vault(monkeypatch):
    """No env override and no Obsidian registry → unregistered, and the
    probe never raises."""
    monkeypatch.delenv("WIGAMIG_PERSONAL_ORACLE_DIR", raising=False)
    monkeypatch.setattr(_op, "personal_oracle_dir",
                        lambda: (_ for _ in ()).throw(_op.OracleError("no vault")))
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_UNREGISTERED
    assert "no vault" in probe.detail


def test_probe_blocked_on_listing_eperm(world, monkeypatch):
    """The classic iCloud/Full-Disk-Access symptom: the dir stats fine
    but enumerating its contents raises PermissionError. Must report
    BLOCKED with the actionable FDA hint, not degrade to empty."""
    _write_entry(world["vault"] / "oracle", "2026-05-16_x.md")

    def _boom(self, *_a, **_kw):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(Path, "rglob", _boom)
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_BLOCKED
    assert "Full Disk Access" in probe.detail


def test_probe_blocked_on_read_eperm(world, monkeypatch):
    """Enumeration can succeed while a per-file read is denied. That is
    still a BLOCKED result — the read is what the MCP actually needs."""
    _write_entry(world["vault"] / "oracle", "2026-05-16_x.md")

    real_read = Path.read_text

    def _boom(self, *a, **kw):
        if self.suffix == ".md":
            raise PermissionError("Operation not permitted")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _boom)
    probe = _op.probe_personal_oracle()
    assert probe.status == _op.PROBE_BLOCKED
    assert probe.sample and probe.sample.endswith("2026-05-16_x.md")
