"""
Purpose: Smoke-test that ``wigamig --help`` exposes the full command tree
         expected by ``docs/cli_manual.md``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``click.testing.CliRunner``.
Output: pytest cases asserting the top-level command tree and that
        ``wigamig agent list`` runs against the repo's agents directory.
"""

from __future__ import annotations

from click.testing import CliRunner

from wigamig.cli import cli

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
