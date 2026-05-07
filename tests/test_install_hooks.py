"""Tests for :mod:`wigamig.commands.install_cmd`."""

from __future__ import annotations

import json

from wigamig.commands import install_cmd


def test_install_writes_settings(tmp_path):
    target = tmp_path / "settings.json"
    install_cmd.cmd_install(hooks=True, settings_path=target, backup=False)
    settings = json.loads(target.read_text(encoding="utf-8"))
    assert "hooks" in settings
    pre_entries = settings["hooks"]["PreToolUse"]
    matchers = [e["matcher"] for e in pre_entries]
    assert any("Write|Edit|Bash|NotebookEdit" in m for m in matchers)
    assert "wigamig-inventory" in settings["mcpServers"]


def test_install_idempotent(tmp_path):
    target = tmp_path / "settings.json"
    install_cmd.cmd_install(hooks=True, settings_path=target, backup=False)
    first = target.read_text(encoding="utf-8")
    install_cmd.cmd_install(hooks=True, settings_path=target, backup=False)
    second = target.read_text(encoding="utf-8")
    assert first == second


def test_install_preserves_unrelated(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps({"theme": "dark", "hooks": {"Stop": [{"matcher": ".*", "hooks": []}]}}),
        encoding="utf-8",
    )
    install_cmd.cmd_install(hooks=True, settings_path=target, backup=False)
    settings = json.loads(target.read_text(encoding="utf-8"))
    assert settings["theme"] == "dark"
    assert "Stop" in settings["hooks"]
    assert "PreToolUse" in settings["hooks"]
