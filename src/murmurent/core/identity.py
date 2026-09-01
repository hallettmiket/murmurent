"""
Purpose: Resolve the murmurent identity of the current user.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Environment (``MURMURENT_USER``), ``~/.murmurent/user`` (the saved
       Western netname), or ``gh api user`` as final fallback.
Output: ``Identity`` dataclass with the resolved handle and source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ENV_VAR = "MURMURENT_USER"
USER_FILE = Path.home() / ".murmurent" / "user"
IdentitySource = Literal["env", "user_file", "gh", "unknown"]


class IdentityError(RuntimeError):
    """Raised when the current user's identity cannot be resolved."""


@dataclass(frozen=True)
class Identity:
    """The resolved current-user identity."""

    handle: str
    source: IdentitySource

    @property
    def at_handle(self) -> str:
        """Return the handle with a leading ``@`` (e.g. ``@allie``)."""
        return self.handle if self.handle.startswith("@") else f"@{self.handle}"


def _normalize(handle: str) -> str:
    """Strip leading ``@`` and surrounding whitespace from ``handle``."""
    return handle.strip().lstrip("@")


def from_env() -> Identity | None:
    """Return an :class:`Identity` from ``MURMURENT_USER`` if set, else ``None``."""
    value = os.environ.get(ENV_VAR)
    if not value:
        return None
    handle = _normalize(value)
    if not handle:
        return None
    return Identity(handle=handle, source="env")


def from_user_file() -> Identity | None:
    """Return an :class:`Identity` from ``~/.murmurent/user`` if present, else ``None``.

    This file is written by the dashboard's "Remember me on this machine"
    flow and stores the user's **Western netname**. It must be consulted
    before ``gh api user`` because a member's GitHub login is often
    different from their Western netname — the Streamlit app already
    knows this; the FastAPI server should too.
    """
    if not USER_FILE.is_file():
        return None
    try:
        text = USER_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    handle = _normalize(text)
    if not handle:
        return None
    return Identity(handle=handle, source="user_file")


def from_gh() -> Identity | None:
    """Return an :class:`Identity` from ``gh api user`` if available, else ``None``."""
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(
            ["gh", "api", "user"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    login = payload.get("login")
    if not isinstance(login, str) or not login.strip():
        return None
    return Identity(handle=_normalize(login), source="gh")


def resolve(*, allow_unknown: bool = False) -> Identity:
    """Resolve the current user.

    Resolution order: ``MURMURENT_USER`` env var, then ``~/.murmurent/user``
    (the saved Western netname), then ``gh api user``.

    Parameters
    ----------
    allow_unknown:
        If ``True``, return ``Identity(handle="unknown", source="unknown")``
        when no source resolves. Otherwise raise :class:`IdentityError`.
    """
    for resolver in (from_env, from_user_file, from_gh):
        identity = resolver()
        if identity is not None:
            return identity
    if allow_unknown:
        return Identity(handle="unknown", source="unknown")
    raise IdentityError(
        f"Could not resolve current user. Set ${ENV_VAR}, save your "
        f"Western netname to {USER_FILE}, or run `gh auth login`."
    )
