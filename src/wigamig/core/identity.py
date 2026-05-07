"""
Purpose: Resolve the wigamig identity of the current user.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: Environment (``WIGAMIG_USER``) or ``gh api user`` as fallback.
Output: ``Identity`` dataclass with the resolved handle and source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

ENV_VAR = "WIGAMIG_USER"
IdentitySource = Literal["env", "gh", "unknown"]


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
    """Return an :class:`Identity` from ``WIGAMIG_USER`` if set, else ``None``."""
    value = os.environ.get(ENV_VAR)
    if not value:
        return None
    handle = _normalize(value)
    if not handle:
        return None
    return Identity(handle=handle, source="env")


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

    Resolution order: ``WIGAMIG_USER`` env var, then ``gh api user``.

    Parameters
    ----------
    allow_unknown:
        If ``True``, return ``Identity(handle="unknown", source="unknown")``
        when neither source resolves. Otherwise raise :class:`IdentityError`.
    """
    for resolver in (from_env, from_gh):
        identity = resolver()
        if identity is not None:
            return identity
    if allow_unknown:
        return Identity(handle="unknown", source="unknown")
    raise IdentityError(
        f"Could not resolve current user. Set ${ENV_VAR} or authenticate with `gh auth login`."
    )
