"""Agent sync across machines via the personal vault (issue #80).

Pins the load-bearing invariants of the agent-sync phase:
  * ``agents/`` + ``agent_forks/`` are allowlist-TRACKED vault folders, so a
    member's net-new agents and commons forks reach GitHub via ``vault sync``
    (previously the allowlist gitignored ``agents/`` back out — the gap).
  * ``forks_dir()`` resolves under the registered vault (env pin > vault >
    legacy ``~/.murmurent/agent_forks``).
  * ``migrate_legacy_forks()`` moves an existing legacy fork home into the
    vault exactly once — idempotent, never overwrites a vault copy, keeps the
    member's live working-copy edits, and leaves an on-disk backup.
  * ``relink_vault_agents()`` materialises ``<vault>/agents/*.md`` (symlinks)
    and ``<vault>/agent_forks/*.md`` (hardlinks) into ``~/.claude/agents/`` —
    the step a second machine runs after a vault pull.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import agent_forks as _af
from murmurent.core import personal_agents as _pa
from murmurent.core import vault_provision as VP

FORK_BODY = "---\nname: blacksmith\nfreeze: personal\ndescription: forked\n---\n# mine\n"


def _register_vault(monkeypatch, tmp_path) -> Path:
    """A registered personal vault: machine.yaml pin pointing at a tmp vault."""
    from murmurent.dashboard import machine_settings as MS

    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    machine = tmp_path / "_machine_home" / "machine.yaml"
    machine.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(f"obsidian_vault_path: {vault}\n", encoding="utf-8")
    monkeypatch.setattr(MS, "MACHINE_FILE", machine)
    return vault


# ---------------------------------------------------------------------------
# allowlist: agents/ + agent_forks/ are tracked vault folders
# ---------------------------------------------------------------------------


def test_agent_dirs_are_tracked_and_scaffolded():
    assert "agents" in VP.MURMURENT_TRACKED_FOLDERS
    assert "agent_forks" in VP.MURMURENT_TRACKED_FOLDERS
    assert "agent_forks" in VP.VAULT_SUBDIRS
    gi = VP._allowlist_gitignore_lines()
    assert "!/agents/" in gi and "!/agent_forks/" in gi


def test_allowlist_gitignore_does_not_ignore_agent_files(tmp_path):
    """Real ``git check-ignore``: agent files survive the ``/*`` allowlist."""
    repo = tmp_path / "vault"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text(
        "\n".join(VP._allowlist_gitignore_lines()) + "\n", encoding="utf-8")
    for rel in ("agents/my_helper.md", "agent_forks/blacksmith.md",
                "agent_forks/agent_forks.yaml", "health/private.md"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    def ignored(rel: str) -> bool:
        return subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", rel]).returncode == 0

    assert not ignored("agents/my_helper.md")
    assert not ignored("agent_forks/blacksmith.md")
    assert not ignored("agent_forks/agent_forks.yaml")
    assert ignored("health/private.md")  # non-murmurent folders stay local


# ---------------------------------------------------------------------------
# forks_dir resolution
# ---------------------------------------------------------------------------


def test_forks_dir_prefers_registered_vault(monkeypatch, tmp_path):
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)
    vault = _register_vault(monkeypatch, tmp_path)
    assert _af.forks_dir() == vault / "agent_forks"


def test_forks_dir_falls_back_to_legacy_without_vault(monkeypatch):
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)
    # conftest isolates machine.yaml (empty) + MURMURENT_HOME → legacy home.
    assert _af.forks_dir() == Path(os.environ["MURMURENT_HOME"]) / "agent_forks"
    assert _af.forks_dir() == _af.legacy_forks_dir()


def test_forks_dir_env_pin_wins(monkeypatch, tmp_path):
    _register_vault(monkeypatch, tmp_path)
    monkeypatch.setenv(_af.ENV_FORKS_DIR, str(tmp_path / "pin"))
    assert _af.forks_dir() == tmp_path / "pin"


# ---------------------------------------------------------------------------
# legacy-home migration
# ---------------------------------------------------------------------------


def test_migrate_legacy_forks_moves_once_nondestructively(monkeypatch, tmp_path):
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)
    vault = _register_vault(monkeypatch, tmp_path)
    cc = tmp_path / "cc-agents"
    cc.mkdir()
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc))

    legacy = _af.legacy_forks_dir()
    legacy.mkdir(parents=True)
    (legacy / "blacksmith.md").write_text(FORK_BODY, encoding="utf-8")
    (legacy / "agent_forks.yaml").write_text(
        "forks:\n  blacksmith:\n    source_sha: abc\n    forked_at: '2026-07-01'\n",
        encoding="utf-8")
    # A live working copy carrying local edits (the copy-fallback drift case).
    (cc / "blacksmith.md").write_text(FORK_BODY + "my edit\n", encoding="utf-8")

    res = _af.migrate_legacy_forks()
    assert res["migrated"] is True
    new = vault / "agent_forks"
    assert (new / "agent_forks.yaml").is_file()
    # The member's live edits won over the stale legacy canonical…
    assert (new / "blacksmith.md").read_text() == FORK_BODY + "my edit\n"
    # …and the working copy is re-linked to the vault canonical (one inode).
    assert not (cc / "blacksmith.md").is_symlink()
    assert os.stat(cc / "blacksmith.md").st_ino == os.stat(new / "blacksmith.md").st_ino
    # Legacy home kept as an on-disk backup, nothing deleted.
    assert not legacy.exists()
    backup = legacy.with_name("agent_forks.migrated")
    assert (backup / "blacksmith.md").read_text() == FORK_BODY

    # Idempotent: a second run copies nothing and changes nothing.
    res2 = _af.migrate_legacy_forks()
    assert res2["copied"] == []
    assert (new / "blacksmith.md").read_text() == FORK_BODY + "my edit\n"


def test_migrate_never_overwrites_a_vault_copy(monkeypatch, tmp_path):
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)
    vault = _register_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(tmp_path / "cc-agents"))

    new = vault / "agent_forks"
    new.mkdir(parents=True)
    (new / "blacksmith.md").write_text("vault version\n", encoding="utf-8")
    legacy = _af.legacy_forks_dir()
    legacy.mkdir(parents=True)
    (legacy / "blacksmith.md").write_text("old legacy version\n", encoding="utf-8")

    res = _af.migrate_legacy_forks()
    assert "blacksmith.md" in res["skipped"]
    assert (new / "blacksmith.md").read_text() == "vault version\n"


def test_migrate_is_a_noop_without_a_vault(monkeypatch):
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)
    res = _af.migrate_legacy_forks()
    assert res["migrated"] is False
    assert "fork home unchanged" in res["detail"] or "nothing to migrate" in res["detail"]


# ---------------------------------------------------------------------------
# relink: materialise vault agents + forks into ~/.claude/agents
# ---------------------------------------------------------------------------


def _second_machine(monkeypatch, tmp_path) -> tuple[Path, Path]:
    """A machine whose vault pull already brought agents + forks, but whose
    ``~/.claude/agents/`` has never seen them."""
    vault = _register_vault(monkeypatch, tmp_path)
    cc = tmp_path / "cc-agents"
    cc.mkdir()
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc))
    monkeypatch.setenv("MURMURENT_PERSONAL_AGENTS_DIR", str(vault / "agents"))
    monkeypatch.delenv(_af.ENV_FORKS_DIR, raising=False)

    commons = tmp_path / "commons" / "agents"
    commons.mkdir(parents=True)
    (commons / "blacksmith.md").write_text(
        "---\nname: blacksmith\nfreeze: personal\ndescription: commons\n---\n",
        encoding="utf-8")
    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(tmp_path / "commons"))

    (vault / "agents").mkdir()
    (vault / "agents" / "my_helper.md").write_text(
        "---\nname: my_helper\nfreeze: personal\ndescription: mine\n---\n",
        encoding="utf-8")
    # A stray commons-named file in agents/ must NOT hijack the commons link.
    (vault / "agents" / "blacksmith.md").write_text("not a fork\n", encoding="utf-8")
    (vault / "agent_forks").mkdir()
    (vault / "agent_forks" / "blacksmith.md").write_text(FORK_BODY, encoding="utf-8")
    (vault / "agent_forks" / "agent_forks.yaml").write_text(
        "forks:\n  blacksmith:\n    source_sha: abc\n", encoding="utf-8")
    return vault, cc


def test_relink_materializes_vault_agents_and_forks(monkeypatch, tmp_path):
    vault, cc = _second_machine(monkeypatch, tmp_path)

    res = _pa.relink_vault_agents()

    link = cc / "my_helper.md"
    assert link.is_symlink()
    assert os.readlink(link) == str(vault / "agents" / "my_helper.md")
    fork = cc / "blacksmith.md"
    assert fork.is_file() and not fork.is_symlink()
    assert os.stat(fork).st_ino == os.stat(vault / "agent_forks" / "blacksmith.md").st_ino
    assert any(s["name"] == "blacksmith" for s in res["skipped"])  # the stray file

    # Idempotent: a second run keeps everything in place.
    res2 = _pa.relink_vault_agents()
    assert (cc / "my_helper.md").is_symlink()
    assert any(r["method"] == "already-linked" for r in res2["forks"])


def test_relink_keeps_a_diverged_local_fork(monkeypatch, tmp_path):
    vault, cc = _second_machine(monkeypatch, tmp_path)
    # A real local file that differs from the vault fork (NOT the same inode).
    (cc / "blacksmith.md").write_text("local divergent copy\n", encoding="utf-8")

    res = _pa.relink_vault_agents()
    assert (cc / "blacksmith.md").read_text() == "local divergent copy\n"
    assert any(s["name"] == "blacksmith" and "differs" in s["reason"]
               for s in res["skipped"])


def test_relink_without_vault_is_a_safe_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(tmp_path / "cc"))
    monkeypatch.setenv("MURMURENT_PERSONAL_AGENTS_DIR",
                       str(tmp_path / "novault" / "agents"))
    monkeypatch.setenv(_af.ENV_FORKS_DIR, str(tmp_path / "novault" / "agent_forks"))
    res = _pa.relink_vault_agents()
    assert res["personal"] == [] and res["forks"] == [] and res["skipped"] == []


def test_cli_agent_relink(monkeypatch, tmp_path):
    _second_machine(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli, ["agent", "relink"])
    assert res.exit_code == 0, res.output
    assert "my_helper" in res.output and "blacksmith" in res.output
    assert "Re-linked" in res.output
