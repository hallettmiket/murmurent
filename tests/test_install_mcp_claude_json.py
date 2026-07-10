"""
Test that `murmurent install --hooks` also writes MCP entries to
``~/.claude.json`` (where Claude Code actually reads them) — not just
``~/.claude/settings.json`` (a legacy murmurent location CC ignores).

Smoke-discovered bug: agents in fresh CC sessions couldn't see any
murmurent MCP because we were writing to the wrong file.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from murmurent.commands import install_cmd


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    """Redirect ~ to tmp so the install doesn't touch the real ~/.claude.json."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_install_writes_to_claude_json(fake_home):
    settings_path = fake_home / ".claude" / "settings.json"
    install_cmd.cmd_install(hooks=True, settings_path=settings_path,
                              backup=False)
    claude_json = fake_home / ".claude.json"
    assert claude_json.is_file()
    data = json.loads(claude_json.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    assert "murmurent-inventory" in servers
    assert "murmurent-oracle" in servers
    assert "murmurent-core-data" in servers


def test_install_preserves_user_added_mcps(fake_home):
    """User-installed entries (slack, etc.) must survive a re-run."""
    claude_json = fake_home / ".claude.json"
    claude_json.write_text(json.dumps({
        "mcpServers": {
            "slack": {"command": "npx", "args": ["-y", "@anything/slack"]},
            "murmurent-inventory": {"command": "python", "args": ["-m", "stale"]},
        },
        "otherKey": {"preserved": True},
    }), encoding="utf-8")
    settings_path = fake_home / ".claude" / "settings.json"
    install_cmd.cmd_install(hooks=True, settings_path=settings_path,
                              backup=False)
    data = json.loads(claude_json.read_text(encoding="utf-8"))
    # User's slack entry stays.
    assert data["mcpServers"]["slack"]["command"] == "npx"
    # Murmurent entries are refreshed to current spec (stale stub replaced).
    assert data["mcpServers"]["murmurent-inventory"]["args"] == [
        "-m", "murmurent.mcp.inventory_server",
    ]
    # Non-MCP keys preserved.
    assert data["otherKey"] == {"preserved": True}


def test_install_is_idempotent(fake_home):
    settings_path = fake_home / ".claude" / "settings.json"
    install_cmd.cmd_install(hooks=True, settings_path=settings_path,
                              backup=False)
    first = (fake_home / ".claude.json").read_text(encoding="utf-8")
    install_cmd.cmd_install(hooks=True, settings_path=settings_path,
                              backup=False)
    second = (fake_home / ".claude.json").read_text(encoding="utf-8")
    assert first == second
