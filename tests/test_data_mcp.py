"""Tests for the ``murmurent-data`` MCP server's tool implementations.

We exercise the python-level ``tool_*`` functions directly — same pattern
as ``tests/test_oracle_mcp.py`` for ``murmurent-oracle``. The FastMCP wiring
is only exercised when the SDK is installed and the server runs, which is out
of scope for unit tests.

Coverage:
  - ``tool_list`` returns each file's relative path, size, and type; skips
    ``.gitkeep``; recurses into subfolders
  - a missing / unregistered vault degrades to an empty list (no raise)
  - ``tool_read`` returns text for text-like files, byte-capped with a note
  - ``tool_read`` returns abs-path metadata (not content) for binaries
  - path-traversal outside ``murmurent_data/`` is refused
  - the install_cmd registration puts murmurent-data in mcpServers
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murmurent.mcp import data_server as srv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def personal(monkeypatch, tmp_path):
    """A personal murmurent_data/ folder with a text file, a nested file,
    a binary, and a .gitkeep (which must be skipped)."""
    root = tmp_path / "vault" / "murmurent_data"
    (root / "protocols").mkdir(parents=True)
    (root / ".gitkeep").write_text("", encoding="utf-8")
    (root / "notes.md").write_text("# Reference\n\nSome protocol notes.\n",
                                   encoding="utf-8")
    (root / "protocols" / "assay.txt").write_text("step 1\nstep 2\n",
                                                   encoding="utf-8")
    (root / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n binary bytes")
    monkeypatch.setenv(srv.ENV_DATA, str(root))
    return root


@pytest.fixture
def lab(monkeypatch, tmp_path):
    """A lab (lab-mgmt) murmurent_data/ folder, resolved via the lab-mgmt env."""
    lab_root = tmp_path / "lab_mgmt"
    data = lab_root / "murmurent_data"
    data.mkdir(parents=True)
    (data / "sop.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(lab_root))
    return data


# ---------------------------------------------------------------------------
# tool_list
# ---------------------------------------------------------------------------


def test_list_personal_returns_files_with_metadata(personal):
    rows = srv.tool_list("personal")
    by_path = {r["path"]: r for r in rows}
    assert set(by_path) == {"notes.md", "protocols/assay.txt", "figure.png"}
    assert by_path["notes.md"]["type"] == "md"
    assert by_path["protocols/assay.txt"]["type"] == "txt"
    assert by_path["figure.png"]["size_bytes"] > 0


def test_list_skips_gitkeep(personal):
    paths = {r["path"] for r in srv.tool_list("personal")}
    assert ".gitkeep" not in paths


def test_list_lab_vault(lab):
    rows = srv.tool_list("lab")
    assert [r["path"] for r in rows] == ["sop.csv"]
    assert rows[0]["type"] == "csv"


def test_list_unregistered_vault_is_empty(monkeypatch, tmp_path):
    """No env, no vault → empty list rather than an exception."""
    monkeypatch.delenv(srv.ENV_DATA, raising=False)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "nope"))
    monkeypatch.setattr(srv, "_safe_personal_dir", lambda: None)
    assert srv.tool_list("personal") == []
    assert srv.tool_list("lab") == []


def test_list_invalid_vault_raises(personal):
    with pytest.raises(ValueError, match="vault must be one of"):
        srv.tool_list("nonsense")


# ---------------------------------------------------------------------------
# tool_read
# ---------------------------------------------------------------------------


def test_read_text_file_returns_content(personal):
    out = srv.tool_read("notes.md")
    assert out["ok"] is True
    assert out["is_text"] is True
    assert "protocol notes" in out["content"]
    assert out["truncated"] is False
    assert out["path"] == "notes.md"


def test_read_nested_text_file(personal):
    out = srv.tool_read("protocols/assay.txt")
    assert out["ok"] is True and out["is_text"] is True
    assert out["content"].startswith("step 1")


def test_read_binary_returns_abspath_not_content(personal):
    out = srv.tool_read("figure.png")
    assert out["ok"] is True
    assert out["is_text"] is False
    assert "content" not in out
    assert out["abs_path"].endswith("figure.png")
    assert "note" in out


def test_read_truncates_large_text(personal, monkeypatch):
    big = personal / "big.md"
    big.write_text("x" * 5000, encoding="utf-8")
    monkeypatch.setattr(srv, "MAX_TEXT_BYTES", 100)
    out = srv.tool_read("big.md")
    assert out["truncated"] is True
    assert len(out["content"]) == 100
    assert "truncated" in out["note"]


def test_read_missing_file_errors(personal):
    out = srv.tool_read("does_not_exist.md")
    assert out["ok"] is False
    assert "not found" in out["error"]


def test_read_path_traversal_refused(personal):
    """A ``..`` escape out of murmurent_data/ must be refused."""
    out = srv.tool_read("../oracle/secret.md")
    assert out["ok"] is False
    assert "escapes" in out["error"]


def test_read_absolute_path_outside_root_refused(personal, tmp_path):
    outsider = tmp_path / "elsewhere.md"
    outsider.write_text("nope\n", encoding="utf-8")
    out = srv.tool_read(str(outsider))
    assert out["ok"] is False and "escapes" in out["error"]


def test_read_lab_vault(lab):
    out = srv.tool_read("sop.csv", vault="lab")
    assert out["ok"] is True and out["is_text"] is True
    assert "a,b" in out["content"]


def test_read_unregistered_vault_errors(monkeypatch):
    monkeypatch.setattr(srv, "_safe_personal_dir", lambda: None)
    out = srv.tool_read("whatever.md")
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# Install registration
# ---------------------------------------------------------------------------


def test_install_registers_data_mcp(tmp_path):
    """`murmurent install --hooks` must add murmurent-data to mcpServers
    alongside murmurent-oracle."""
    from murmurent.commands import install_cmd
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    install_cmd.cmd_install(hooks=True, settings_path=settings, backup=False)
    data = json.loads(settings.read_text())
    assert "murmurent-data" in data["mcpServers"]
    spec = data["mcpServers"]["murmurent-data"]
    assert spec["args"] == ["-m", "murmurent.mcp.data_server"]
