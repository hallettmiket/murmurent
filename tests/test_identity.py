"""
Purpose: Unit tests for ``wigamig.core.identity``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Patched environment + monkeypatched ``gh`` resolver.
Output: pytest cases asserting resolution order and error behaviour.
"""

from __future__ import annotations

import pytest

from wigamig.core import identity
from wigamig.core.identity import ENV_VAR, Identity, IdentityError, resolve


def test_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "@allie")
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="allie", source="env")
    assert result.at_handle == "@allie"


def test_falls_back_to_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(identity, "from_gh", lambda: Identity(handle="bob", source="gh"))
    result = resolve()
    assert result == Identity(handle="bob", source="gh")


def test_unknown_when_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(identity, "from_gh", lambda: None)
    with pytest.raises(IdentityError):
        resolve()
    assert resolve(allow_unknown=True).source == "unknown"
