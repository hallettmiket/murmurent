"""
Purpose: Unit tests for ``murmurent.core.identity``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Patched environment + monkeypatched ``gh`` resolver.
Output: pytest cases asserting resolution order and error behaviour.
"""

from __future__ import annotations

import pytest

from murmurent.core import identity
from murmurent.core.identity import ENV_VAR, Identity, IdentityError, resolve


def test_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "@allie")
    monkeypatch.setattr(identity, "from_user_file", lambda: None)
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="allie", source="env")
    assert result.at_handle == "@allie"


def test_user_file_beats_gh(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The saved Western netname must win over the GitHub login.

    Reproduces the bug where a user with Western netname ``the_pi`` and
    GitHub login ``mth`` was rendered as ``mth`` because the FastAPI
    server only consulted ``gh api user`` and not ``~/.murmurent/user``.
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    fake_user_file = tmp_path / "user"
    fake_user_file.write_text("the_pi\n", encoding="utf-8")
    monkeypatch.setattr(identity, "USER_FILE", fake_user_file)
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="mth", source="gh"))
    result = resolve()
    assert result == Identity(handle="the_pi", source="user_file")


def test_user_file_ignored_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(identity, "USER_FILE", tmp_path / "nope")
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="bob", source="gh")


def test_user_file_ignored_when_blank(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    blank = tmp_path / "user"
    blank.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(identity, "USER_FILE", blank)
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="bob", source="gh")


def test_falls_back_to_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(identity, "from_user_file", lambda: None)
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="bob", source="gh")


def test_unknown_when_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(identity, "from_user_file", lambda: None)
    monkeypatch.setattr(identity, "from_gh", lambda: None)
    with pytest.raises(IdentityError):
        resolve()
    assert resolve(allow_unknown=True).source == "unknown"
