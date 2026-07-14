"""Tests for ``murmurent repo {list, status, adopt}`` + :mod:`core.adopt`'s
read-only side.

The write path (adopt_clone → projectize) is already pinned by
test_inventory_adopt.py (through the HTTP endpoint) and
test_projectize.py (the chokepoint itself); here we pin:

  * adoption_status verdicts (plain clone / partial / adopted / missing)
  * find_manifest_for path match + project-name fallback
  * the CLI surface: adopt writes CHARTER, status exit codes (0/1/2)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import adopt as _adopt
from murmurent.core import projectize as _proj


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated home + commons; installations dir redirected so the CLI
    default (projectize.INSTALLATIONS_DIR_DEFAULT, computed at import
    time from the real $HOME) can't leak manifests into ~/.murmurent."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "commons"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    installations = home / ".murmurent" / "installations"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(commons))
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setattr(_proj, "INSTALLATIONS_DIR_DEFAULT", installations)
    return {"home": home, "repos": home / "repos", "installations": installations}


def _make_clone(repos: Path, name: str) -> Path:
    p = repos / name
    (p / ".git").mkdir(parents=True)
    return p


# ---------------------------------------------------------------------------
# adoption_status
# ---------------------------------------------------------------------------


def test_status_plain_clone(world):
    clone = _make_clone(world["repos"], "grace")
    st = _adopt.adoption_status(str(clone))
    assert st.is_git and not st.adopted
    assert st.verdict == "plain clone"


def test_status_partial_then_adopted(world):
    clone = _make_clone(world["repos"], "dcis")
    (clone / "CHARTER.md").write_text("---\nproject: dcis\n---\n")
    assert _adopt.adoption_status(str(clone)).verdict == "partial"
    (clone / ".claude" / "agents").mkdir(parents=True)
    st = _adopt.adoption_status(str(clone))
    assert st.adopted and st.verdict == "adopted"


def test_status_missing_and_not_git(world):
    assert _adopt.adoption_status(str(world["repos"] / "nope")).verdict == "missing"
    plain = world["repos"] / "notes"
    plain.mkdir()
    assert _adopt.adoption_status(str(plain)).verdict == "not a git repo"


def test_find_manifest_path_match_and_name_fallback(world):
    inst = world["installations"]
    inst.mkdir(parents=True)
    clone = _make_clone(world["repos"], "hockey_stats")
    # Manifest recording a stale path — the project-name fallback should
    # still associate it with the same-named clone on the same host.
    (inst / "hockey_stats.yaml").write_text(yaml.safe_dump({
        "project": "hockey_stats",
        "ssh_remote": None,
        "repos": [{"name": "hockey_stats", "path": "/old/home/repos/hockey_stats"}],
    }))
    assert _adopt.find_manifest_for(
        str(clone), installations_dir=inst
    ) == inst / "hockey_stats.yaml"
    # Exact path match wins outright.
    (inst / "other.yaml").write_text(yaml.safe_dump({
        "project": "other",
        "ssh_remote": None,
        "repos": [{"name": "other", "path": str(clone)}],
    }))
    assert _adopt.find_manifest_for(
        str(clone), installations_dir=inst
    ) == inst / "other.yaml"
    # Wrong host never matches.
    assert _adopt.find_manifest_for(
        str(clone), host="biodatsci", installations_dir=inst
    ) is None


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_adopt_then_status(world):
    clone = _make_clone(world["repos"], "hockey_stats")
    runner = CliRunner()
    res = runner.invoke(cli, [
        "repo", "adopt", str(clone),
        "--lead", "@mhallet", "--agents", "blacksmith",
        "--description", "Personal hockey analytics.",
    ])
    assert res.exit_code == 0, res.output
    assert "Adopted hockey_stats on local" in res.output
    assert "project: hockey_stats" in (clone / "CHARTER.md").read_text()
    assert (clone / ".claude" / "agents" / "blacksmith.md").is_symlink()

    res = runner.invoke(cli, ["repo", "status", str(clone)])
    assert res.exit_code == 0, res.output
    assert "✓ adopted" in res.output


def test_cli_status_exit_codes(world):
    runner = CliRunner()
    clone = _make_clone(world["repos"], "grace")
    # Plain clone → 1.
    assert runner.invoke(cli, ["repo", "status", str(clone)]).exit_code == 1
    # Unknown name → 2 (searched across registered hosts; only local here).
    res = runner.invoke(cli, ["repo", "status", "no_such_repo"])
    assert res.exit_code == 2
    assert "not found" in res.output


def test_cli_adopt_refuses_existing_charter(world):
    clone = _make_clone(world["repos"], "dcis")
    (clone / "CHARTER.md").write_text("---\nproject: dcis\n---\n")
    res = CliRunner().invoke(cli, ["repo", "adopt", str(clone), "--lead", "@mhallet"])
    assert res.exit_code != 0
    assert "already exists" in res.output


def test_cli_adopt_requires_lead(world, monkeypatch):
    monkeypatch.delenv("MURMURENT_USER", raising=False)
    clone = _make_clone(world["repos"], "grace")
    res = CliRunner().invoke(cli, ["repo", "adopt", str(clone)])
    assert res.exit_code != 0
    assert "--lead" in res.output
