"""
Purpose: SSH dispatcher for the unprivileged Tier-1 security scanner.
         Reads ``scripts/murmurent_sec_scan.sh`` locally, ships it to the
         target host over a single SSH session, parses the JSONL output.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-19
Input: A registered :class:`core.hosts.Host` + scan options.
Output: ``ScanResult`` (findings + progress lines + any errors).

One SSH session per scan — the scanner script is base64-encoded and
piped into ``bash -s --``. Same idea as :mod:`core.remote_install` but
the payload is a full ~300-line script rather than an inline snippet,
hence the base64 wrapper (avoids shell-quoting hell).

The scanner is read-only by construction (no chmod/chown/rm in the
bash). This module never asks the user for a password and never
attempts ``sudo`` — Tier 2 is a separate path.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from . import hosts as _hosts
from . import remote as _remote
from .repo import murmurent_repo_root
from .security_findings import Finding, rollup_by_directory


SCANNER_SCRIPT = Path("scripts/murmurent_sec_scan.sh")


@dataclass
class ScanOptions:
    """Knobs the scanner accepts via CLI flags on the remote side."""

    lab_vm_root: str | None = None         # default: /data/lab_vm
    projects_root: str | None = None       # default: ~/repos on remote
    lab_group: str | None = None           # e.g. ssmd-u-hallettlab
    home_warn_gb: int = 100
    repo_large_mb: int = 50


@dataclass
class ScanResult:
    """Output of one scan invocation.

    ``progress`` carries the human-readable progress lines the scanner
    emits — useful for the SSE streamer; the CLI prints them to stderr.
    """

    findings: list[Finding] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    raw_lines: int = 0
    parse_errors: list[str] = field(default_factory=list)
    ssh_ok: bool = True
    ssh_error: str = ""


def _read_scanner_script() -> str:
    """Locate ``scripts/murmurent_sec_scan.sh`` in the murmurent repo."""
    repo = murmurent_repo_root()
    path = repo / SCANNER_SCRIPT
    if not path.is_file():
        raise FileNotFoundError(f"scanner script not found at {path}")
    return path.read_text(encoding="utf-8")


def _build_argv(opts: ScanOptions, host_name: str) -> list[str]:
    """Turn ScanOptions into the scanner's CLI flag list."""
    argv: list[str] = ["--host-name", host_name]
    if opts.lab_vm_root:
        argv += ["--lab-vm-root", opts.lab_vm_root]
    if opts.projects_root:
        argv += ["--projects-root", opts.projects_root]
    if opts.lab_group:
        argv += ["--lab-group", opts.lab_group]
    argv += ["--home-warn-gb", str(opts.home_warn_gb)]
    argv += ["--repo-large-mb", str(opts.repo_large_mb)]
    return argv


def _build_command(script: str, argv: list[str]) -> str:
    """Wrap the scanner script so it survives going through bash -lc.

    Approach: base64-encode the whole script, decode it on the remote
    side, pipe into ``bash -s -- <args>``. No quoting concerns — the
    base64 alphabet is shell-safe.
    """
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    # Quote each argv element for the remote shell. Use single quotes
    # since flag values are simple strings (paths, integers, group
    # names). The argv tokens come from us, not the user, but be
    # defensive anyway.
    quoted: list[str] = []
    for a in argv:
        # No single quotes in our values; if that ever changes use shlex.
        if "'" in a:
            raise ValueError(f"unsafe character in scanner arg: {a!r}")
        quoted.append(f"'{a}'")
    return f"echo '{b64}' | base64 -d | bash -s -- {' '.join(quoted)}"


def _parse_stream(stdout: str) -> tuple[list[Finding], list[str], list[str]]:
    """Parse the JSONL stream into (findings, progress, parse_errors)."""
    import json
    findings: list[Finding] = []
    progress: list[str] = []
    errors: list[str] = []
    for raw in (stdout or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # Silently ignore any line that isn't a JSON object — SSH MOTD
        # banners, login messages, sudo lecture text, etc. leak into the
        # stream. The scanner only ever emits ``{...}`` per line, so
        # anything else is environmental noise, not a parse error.
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"unparseable line: {raw[:120]} ({exc})")
            continue
        if isinstance(obj, dict) and obj.get("_kind") == "progress":
            progress.append(f"[{obj.get('ts', '')}] {obj.get('message', '')}")
            continue
        try:
            findings.append(Finding.from_dict(obj))
        except (TypeError, ValueError) as exc:
            errors.append(f"finding rejected: {exc}")
    return findings, progress, errors


def scan(host_obj: _hosts.Host, opts: ScanOptions | None = None,
         *, timeout: int = 600, rollup: bool = True) -> ScanResult:
    """Run the scanner on ``host_obj`` and return findings + progress.

    A scan over ``/data/lab_vm`` on biodatsci can legitimately take a
    few minutes (find walks plus a `du -sk ~`), so the default timeout
    is 10 minutes. Callers wanting an SSE-streamed UX can lower it and
    poll incrementally — this MVP returns the whole stdout at once.
    """
    opts = opts or ScanOptions()
    script = _read_scanner_script()
    argv = _build_argv(opts, host_obj.name)
    command = _build_command(script, argv)

    remote = _remote.Remote(host_obj)
    try:
        res = remote.run(command, check=False, timeout=timeout)
    except _remote.RemoteError as exc:
        return ScanResult(
            ssh_ok=False,
            ssh_error=(exc.stderr or str(exc)).strip() or "ssh failed",
        )

    findings, progress, errors = _parse_stream(res.stdout)
    if rollup:
        findings = rollup_by_directory(findings)
    return ScanResult(
        findings=findings,
        progress=progress,
        raw_lines=len(res.stdout.splitlines()),
        parse_errors=errors,
        ssh_ok=True,
        ssh_error="" if res.ok else (res.stderr or "").strip(),
    )


__all__ = ["ScanOptions", "ScanResult", "scan"]
