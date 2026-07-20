"""Tests for ``murmurent agent {list, fork, drift, unfork}`` + :mod:`core.agent_forks`.

Pins the load-bearing invariants:
  * a fork is a NON-symlink real file in ~/.claude/agents/ (so setup.sh preserves it)
  * the canonical copy + manifest live under ~/.murmurent/agent_forks/ (git-trackable)
  * drift keys on the fork-time commons hash: upstream-changed vs locally-modified
  * unfork restores the commons symlink and drops the manifest entry
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import agent_forks as _af

COMMONS = {
    "blacksmith": "---\nname: blacksmith\nfreeze: personal\ndescription: the workhorse\n---\n# blacksmith\n",
    "oracle": "---\nname: oracle\nfreeze: personal\ndescription: memory\n---\n# oracle\n",
}


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated commons + CC agents dir + fork home, all under tmp (same fs so
    hardlinks work). Installed dir starts with symlinks into the commons, the
    way setup.sh leaves it."""
    commons_agents = tmp_path / "commons" / "agents"
    commons_agents.mkdir(parents=True)
    for name, text in COMMONS.items():
        (commons_agents / f"{name}.md").write_text(text)

    cc_agents = tmp_path / "dot_claude" / "agents"
    cc_agents.mkdir(parents=True)
    for name in COMMONS:
        (cc_agents / f"{name}.md").symlink_to(commons_agents / f"{name}.md")

    wig_home = tmp_path / "wig_home"

    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(tmp_path / "commons"))
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc_agents))
    monkeypatch.setenv("MURMURENT_HOME", str(wig_home))
    return {
        "commons": commons_agents,
        "cc": cc_agents,
        "home": wig_home,
    }


# ---------------------------------------------------------------------------
# core: status
# ---------------------------------------------------------------------------


def test_status_linked(world):
    st = _af.status_for("oracle")
    assert st is not None and st.kind == "linked"


def test_status_missing_agent_is_none(world):
    assert _af.status_for("nope") is None


# ---------------------------------------------------------------------------
# core: fork
# ---------------------------------------------------------------------------


def test_fork_makes_real_file_and_manifest(world):
    res = _af.fork_agent("blacksmith")
    dest = world["cc"] / "blacksmith.md"
    # The load-bearing property: NOT a symlink, so setup.sh preserves it.
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_text() == COMMONS["blacksmith"]
    # Canonical copy lives in the git-trackable fork home.
    canonical = world["home"] / "agent_forks" / "blacksmith.md"
    assert canonical.is_file()
    assert res.method == "hardlink"
    assert os.stat(dest).st_ino == os.stat(canonical).st_ino  # one inode, two paths
    # Manifest records provenance for drift.
    manifest = _af.load_manifest()["forks"]
    assert "blacksmith" in manifest
    assert manifest["blacksmith"]["source_sha"] == res.source_sha
    assert manifest["blacksmith"]["forked_at"]

    st = _af.status_for("blacksmith")
    assert st.kind == "forked" and not st.upstream_changed and not st.locally_modified


def test_fork_unknown_agent_errors(world):
    with pytest.raises(_af.AgentForkError) as exc:
        _af.fork_agent("segmenter")
    assert "not a known commons agent" in str(exc.value)


def test_fork_refuses_existing_then_force(world):
    _af.fork_agent("blacksmith")
    with pytest.raises(_af.AgentForkError) as exc:
        _af.fork_agent("blacksmith")
    assert "already forked" in str(exc.value)
    # --force re-snapshots against the (now advanced) commons.
    (world["commons"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\nupstream edit\n")
    res = _af.fork_agent("blacksmith", force=True)
    assert _af.status_for("blacksmith").upstream_changed is False
    assert res.source_sha == _af._sha256_file(world["commons"] / "blacksmith.md")


# ---------------------------------------------------------------------------
# core: drift indicators
# ---------------------------------------------------------------------------


def test_drift_upstream_changed(world):
    _af.fork_agent("blacksmith")
    (world["commons"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\nnew commons line\n")
    st = _af.status_for("blacksmith")
    assert st.upstream_changed and not st.locally_modified and not st.diverged


def test_drift_locally_modified(world):
    _af.fork_agent("blacksmith")
    (world["cc"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\nmy tweak\n")
    st = _af.status_for("blacksmith")
    assert st.locally_modified and not st.upstream_changed


def test_drift_diverged(world):
    _af.fork_agent("blacksmith")
    (world["commons"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\ncommons\n")
    (world["cc"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\nmine\n")
    st = _af.status_for("blacksmith")
    assert st.upstream_changed and st.locally_modified and st.diverged


def test_orphaned_when_commons_drops_agent(world):
    _af.fork_agent("blacksmith")
    (world["commons"] / "blacksmith.md").unlink()
    st = _af.status_for("blacksmith")
    assert st.kind == "forked" and st.in_commons is False


# ---------------------------------------------------------------------------
# core: unfork
# ---------------------------------------------------------------------------


def test_unfork_restores_symlink(world):
    _af.fork_agent("blacksmith")
    _af.unfork_agent("blacksmith")
    dest = world["cc"] / "blacksmith.md"
    assert dest.is_symlink()
    assert "blacksmith" not in _af.load_manifest()["forks"]
    assert not (world["home"] / "agent_forks" / "blacksmith.md").exists()


def test_unfork_untracked_requires_force(world):
    with pytest.raises(_af.AgentForkError):
        _af.unfork_agent("oracle")  # a plain symlink, never forked


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_fork_list_drift_unfork(world):
    runner = CliRunner()

    res = runner.invoke(cli, ["agent", "fork", "blacksmith"])
    assert res.exit_code == 0, res.output
    assert "Forked" in res.output

    res = runner.invoke(cli, ["agent", "list"])
    assert res.exit_code == 0, res.output
    assert "blacksmith" in res.output and "forked" in res.output

    # No upstream change yet.
    res = runner.invoke(cli, ["agent", "drift"])
    assert res.exit_code == 0, res.output
    assert "up to date" in res.output.lower()

    # Advance the commons → drift flags it.
    (world["commons"] / "blacksmith.md").write_text(COMMONS["blacksmith"] + "\nupstream\n")
    res = runner.invoke(cli, ["agent", "drift", "blacksmith"])
    assert res.exit_code == 0, res.output
    assert "UPSTREAM" in res.output

    res = runner.invoke(cli, ["agent", "unfork", "blacksmith", "--force"])
    assert res.exit_code == 0, res.output
    assert (world["cc"] / "blacksmith.md").is_symlink()


def test_cli_fork_unknown_agent_exits_nonzero(world):
    res = CliRunner().invoke(cli, ["agent", "fork", "segmenter"])
    assert res.exit_code != 0
    assert "not a known commons agent" in res.output


def test_cli_unfork_confirmation_abort(world):
    _af.fork_agent("blacksmith")
    res = CliRunner().invoke(cli, ["agent", "unfork", "blacksmith"], input="n\n")
    assert res.exit_code != 0  # aborted
    assert (world["cc"] / "blacksmith.md").is_file()
    assert not (world["cc"] / "blacksmith.md").is_symlink()  # still forked
