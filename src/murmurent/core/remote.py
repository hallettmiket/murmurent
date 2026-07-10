"""
Purpose: One-place SSH chokepoint for every remote operation murmurent makes.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-13
Input: A :class:`~murmurent.core.hosts.Host` of kind ``ssh``.
Output: :class:`RemoteResult` (stdout, stderr, returncode), plus an audit
        line appended to ``~/.wigamig/remote_audit.log``.

Everything that crosses the SSH boundary funnels through :class:`Remote`
so we have exactly one place to:
  - enforce ``BatchMode=yes`` (no silent password prompts)
  - audit every call (timestamp, host, command summary, returncode)
  - inject ``bash -lc`` so the remote user's login PATH is active
  - surface clear errors when the host is unreachable

The class deliberately does NOT depend on the dashboard or the CLI; it
imports only from :mod:`core.hosts`. Tests mock ``subprocess.run``.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .hosts import Host, LOCAL_NAME

AUDIT_LOG_PATH = Path.home() / ".wigamig" / "remote_audit.log"
AUDIT_ENV_VAR = "WIGAMIG_REMOTE_AUDIT_LOG"
DEFAULT_TIMEOUT = 60  # seconds


class RemoteError(RuntimeError):
    """A remote SSH call failed (non-zero exit) or could not even connect."""

    def __init__(self, message: str, *, returncode: int, stdout: str, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class RemoteResult:
    """Outcome of a single SSH call."""

    host: str
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _audit_path(env: dict[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get(AUDIT_ENV_VAR, AUDIT_LOG_PATH)).expanduser()


def _append_audit(
    *,
    host: Host,
    command: str,
    returncode: int,
    duration_ms: int,
    env: dict[str, str] | None = None,
) -> None:
    path = _audit_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "host": host.name,
        "ssh_host": host.ssh_host,
        "kind": host.kind,
        "command": _summarise(command),
        "returncode": returncode,
        "duration_ms": duration_ms,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _summarise(command: str, max_len: int = 240) -> str:
    """Single-line summary suitable for the audit log."""
    one_line = " ".join(command.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Remote
# ---------------------------------------------------------------------------


class Remote:
    """Wrapper around ``subprocess.run`` for a single :class:`Host`.

    Local hosts execute commands directly via ``bash -lc``. SSH hosts go
    through ``ssh -o BatchMode=yes <ssh_host> bash -lc …``. Either way,
    every call is audited.
    """

    def __init__(self, host: Host):
        self.host = host

    # ---- public API ------------------------------------------------------

    def run(
        self,
        command: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        check: bool = True,
    ) -> RemoteResult:
        """Run ``command`` on ``self.host`` and return the result.

        ``command`` is a single shell line — wrapped in ``bash -lc`` on
        the far side so the user's login PATH is active. If ``check`` is
        True (default), a non-zero exit raises :class:`RemoteError`.
        """
        if not command or not command.strip():
            raise ValueError("Remote.run requires a non-empty command")
        argv = self._build_argv(command)
        start = _dt.datetime.now()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = _ms_since(start)
            _append_audit(
                host=self.host, command=command,
                returncode=124, duration_ms=duration_ms,
            )
            raise RemoteError(
                f"timeout after {timeout}s running on host {self.host.name!r}",
                returncode=124, stdout="", stderr=str(exc),
            ) from exc
        duration_ms = _ms_since(start)
        _append_audit(
            host=self.host, command=command,
            returncode=proc.returncode, duration_ms=duration_ms,
        )
        result = RemoteResult(
            host=self.host.name,
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
        if check and not result.ok:
            raise RemoteError(
                f"command failed on {self.host.name!r} (rc={proc.returncode}): "
                f"{_summarise(command, 120)}",
                returncode=proc.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def probe(self) -> RemoteResult:
        """Cheap connectivity check — runs ``true`` on the host."""
        return self.run("true", check=False, timeout=15)

    def murmurent_version(self) -> str:
        """Return the host's ``murmurent --version`` output (raises if missing)."""
        # `murmurent` may live under ~/.local/bin which the remote login
        # shell adds via .profile — the bash -lc wrapper handles that.
        res = self.run("murmurent --version", timeout=20)
        return res.stdout.strip()

    # ---- argv construction ----------------------------------------------

    def _build_argv(self, command: str) -> list[str]:
        """Return the argv we hand to subprocess.run."""
        wrapped = f"bash -lc {shlex.quote(command)}"
        if self.host.kind == "local" or self.host.name == LOCAL_NAME:
            # Local execution: still go through bash -lc so behaviour
            # mirrors the remote path (login PATH, profile sourcing).
            return ["bash", "-lc", command]
        if self.host.kind == "ssh":
            if not self.host.ssh_host:
                raise ValueError(
                    f"host {self.host.name!r}: ssh kind requires ssh_host"
                )
            return [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=15",
                self.host.ssh_host,
                wrapped,
            ]
        raise ValueError(f"unknown host kind: {self.host.kind!r}")


def _ms_since(start: _dt.datetime) -> int:
    delta = _dt.datetime.now() - start
    return int(delta.total_seconds() * 1000)


__all__ = [
    "Remote",
    "RemoteError",
    "RemoteResult",
    "AUDIT_LOG_PATH",
    "AUDIT_ENV_VAR",
    "DEFAULT_TIMEOUT",
]
