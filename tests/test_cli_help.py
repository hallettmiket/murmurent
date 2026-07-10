"""
Purpose: Smoke-test that ``murmurent --help`` exposes the full command tree
         expected by ``docs/cli_manual.md``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``click.testing.CliRunner``.
Output: pytest cases asserting the top-level command tree and that
        ``murmurent agent list`` runs against the repo's agents directory.
"""

from __future__ import annotations

from click.testing import CliRunner

from murmurent.cli import cli

EXPECTED_TOP_LEVEL = [
    "agent",
    "audit",
    "breach",
    "capture",
    "cite",
    "compliance",
    "dashboard",
    "discuss",
    "doctor",
    "experiment",
    "finalize",
    "freeze",
    "group",
    "install",
    "offboard",
    "onboard",
    "preference",
    "project",
    "publish",
    "pull",
    "push",
    "request-sea",
    "review",
    "role",
    "sea",
    "secret",
    "squad",
    "teach",
    "triage",
]


def test_help_lists_all_top_level_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    for name in EXPECTED_TOP_LEVEL:
        assert name in result.output, f"missing {name} in --help output"


def test_agent_list_runs() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "list"])
    assert result.exit_code == 0, result.output
    # Names should appear; rich tables wrap, so check a couple of distinctive ones.
    for expected in ("oracle", "security_guard"):
        assert expected in result.output


def test_stub_commands_emit_v1_message() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_oracle_doctor_reports_ok_when_readable(tmp_path, monkeypatch) -> None:
    """`murmurent oracle doctor` actually reads an entry and reports OK
    (exit 0) when the vault is accessible."""
    oracle_dir = tmp_path / "vault" / "oracle"
    oracle_dir.mkdir(parents=True)
    (oracle_dir / "2026-05-16_x.md").write_text(
        "---\ntitle: x\n---\n\nbody\n", encoding="utf-8"
    )
    monkeypatch.setenv("MURMURENT_PERSONAL_ORACLE_DIR", str(oracle_dir))
    result = CliRunner().invoke(cli, ["oracle", "doctor"])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_oracle_doctor_blocked_exits_nonzero(tmp_path, monkeypatch) -> None:
    """A Full-Disk-Access denial must exit non-zero with the actionable
    hint — the whole point of the probe is to be loud, not silent."""
    from murmurent.core import oracle_publish as _op

    monkeypatch.setattr(
        _op, "probe_personal_oracle",
        lambda: _op.VaultProbe(
            status=_op.PROBE_BLOCKED,
            detail="Operation not permitted — grant Full Disk Access.",
            path="/some/vault/oracle",
        ),
    )
    result = CliRunner().invoke(cli, ["oracle", "doctor"])
    assert result.exit_code != 0
    assert "Full Disk Access" in result.output
