"""
Purpose: Probe + bootstrap the lab's master folders on its lab_base server.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: A ``lab_base`` string in ``host:/abs/path`` form (e.g.
       ``biodatsci.schulich.uwo.ca:/data/lab_vm/wigamig``).
Output: ``[Probe]`` describing each subfolder check / mkdir.

The lab_base subtree on biodatsci is the central place every project on
that server resolves its raw/, refined/, repos/, notebooks/, lab_oracle/
underneath. Until a lab is first set up, those folders may not exist;
this module probes for them over SSH and creates the missing ones on
explicit request (never on a passive read — the user must press a
button so directory-creation isn't a hidden side effect).

Cached status (``~/.murmurent/master_folders.yaml``):
    {hallett: {host: ..., path: ..., overall: ok|warn|fail,
               checked: 2026-05-15T11:50:00, subdirs: {...}}}

The snapshot reads this file to render the dashboard's persistent green
light. Live re-probes happen only when the user explicitly clicks
"check" or "init"; otherwise we'd burn an SSH connection on every
dashboard refresh.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import hosts as _hosts
from . import remote as _remote
from .preflight import Probe

# Order matters for display — raw + refined come first because they
# hold the data; the rest are housekeeping. There used to be a ``repos``
# entry for "lab-local bare repos" (i.e. a self-hosted GitHub stand-in),
# but the lab decided git origins are managed by external providers
# (GitHub today, GITEA later) — not by a folder on the lab server.
# Working clones live in each user's ``~/repos/``.
MASTER_SUBDIRS: tuple[str, ...] = ("raw", "refined", "notebooks", "lab_oracle")

CACHE_FILE = Path.home() / ".murmurent" / "master_folders.yaml"


@dataclass
class LabBase:
    """Parsed ``host:/abs/path`` value with the host and remote path
    separated. Local-only labs (no host: prefix) keep ``host=None``;
    those probes run on the local filesystem instead of via SSH.
    """

    host: str | None
    path: str

    @property
    def is_remote(self) -> bool:
        return bool(self.host)

    def remote_subdir(self, sub: str) -> str:
        """Absolute remote path of one subfolder, ssh-host stripped."""
        return f"{self.path.rstrip('/')}/{sub.lstrip('/')}"


def parse_lab_base(value: str | None) -> LabBase | None:
    """Split ``host:/abs/path`` into its components.

    Returns ``None`` if ``value`` is empty / unset. Falls back to a
    local LabBase when there is no ``host:`` prefix (typical for
    single-machine dev setups). Tilde paths are expanded so the SSH
    side doesn't see a literal ``~``.
    """
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    # Split on the first ``:/`` to keep the leading drive letter / IPv6
    # bracket alone (we don't expect those on biodatsci but the strict
    # rule is "first ':/' if it sits between non-empty halves").
    i = s.find(":/")
    if i < 0:
        # Local-only — expand ~ for the user's home.
        return LabBase(host=None, path=os.path.expanduser(s))
    host = s[:i]
    path = s[i + 1 :]
    return LabBase(host=host or None, path=os.path.expanduser(path))


def _build_host(lab_base: LabBase) -> _hosts.Host:
    """Return a Host object usable with :class:`Remote`.

    Prefer a registered host (its ``~/.ssh/config`` aliases and any
    remote_user the user configured), and synthesize a transient one
    when biodatsci-or-similar isn't yet in ``hosts.yaml``. The
    transient version uses the bare hostname and lets ssh's own config
    pick up the username.
    """
    name = lab_base.host or "local"
    if not lab_base.is_remote:
        return _hosts.Host(
            name="local", kind="local", ssh_host="", remote_user="",
            project_root="~/repos", lab_vm_root=lab_base.path,
            vault_root="", mount_point="", description="local lab_base",
        )
    # First-match wins from the registered hosts whose ssh_host equals
    # the lab_base host. Falls back to name == host. Failing that,
    # synthesize.
    try:
        for h in _hosts.read().values():
            if h.ssh_host == lab_base.host or h.name == lab_base.host:
                return h
    except Exception:
        pass
    return _hosts.Host(
        name=lab_base.host, kind="ssh", ssh_host=lab_base.host,
        remote_user="", project_root="~/repos", lab_vm_root=lab_base.path,
        vault_root="", mount_point="",
        description="transient (lab_base host not in hosts.yaml)",
    )


def _build_batched_script(base_path: str, *, create: bool) -> str:
    """Return a single shell snippet that probes (and optionally creates)
    all master folders in one SSH session.

    Format: each subdir prints one line ``<name>:<status>:<full_path>``
    on stdout. ``status`` is one of ``present``, ``created``, ``missing``,
    ``error``. The caller parses these lines into Probe rows.

    Doing this in one shell snippet is the whole point: biodatsci has a
    3-strike auth lockout (30 minutes), so we batch what used to be 5-11
    separate SSH connections into exactly one auth handshake.
    """
    base = base_path.rstrip("/")
    create_block = (
        f'  if mkdir -p "$full" 2>/dev/null && [ -d "$full" ]; then\n'
        f'    echo "$d:created:$full"\n'
        f'  else\n'
        f'    echo "$d:error:$full"\n'
        f'  fi\n'
        if create else
        f'  echo "$d:missing:$full"\n'
    )
    return (
        f'BASE={base!r}; '
        f'for d in {" ".join(MASTER_SUBDIRS)}; do '
        f'full="$BASE/$d"; '
        f'if [ -d "$full" ]; then echo "$d:present:$full"; '
        f'else \n{create_block}fi; done'
    )


def _parse_batched_output(stdout: str, lab_base: LabBase, *, create: bool) -> list[Probe]:
    """Convert the line-per-subdir output from :func:`_build_batched_script`
    into a list of Probes the UI can render.

    Missing entries (the host returned no line for a subdir) become a
    yellow 'no response' probe rather than silently disappearing.
    """
    by_name: dict[str, tuple[str, str]] = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        name, status, full = parts
        by_name[name] = (status, full)

    probes: list[Probe] = []
    for sub in MASTER_SUBDIRS:
        entry = by_name.get(sub)
        if entry is None:
            probes.append(Probe(
                name=sub, status="warn",
                detail="no response from remote (output truncated?)",
                required=False,
            ))
            continue
        status, full = entry
        host_prefix = f"{lab_base.host}:" if lab_base.is_remote else ""
        if status == "present":
            probes.append(Probe(
                name=sub, status="ok",
                detail=f"{host_prefix}{full} (already exists)",
                required=False,
            ))
        elif status == "created":
            probes.append(Probe(
                name=sub, status="ok",
                detail=f"created {host_prefix}{full}",
                required=False,
            ))
        elif status == "missing":
            probes.append(Probe(
                name=sub, status="warn",
                detail=f"missing — {host_prefix}{full}",
                required=False,
            ))
        else:  # "error"
            probes.append(Probe(
                name=sub, status="fail",
                detail=f"mkdir failed for {host_prefix}{full}",
                required=False,
            ))
    return probes


def run(lab_base_value: str | None, *, create: bool) -> dict:
    """Probe the master folders for ``lab_base_value``.

    ``create=False`` → check only (used by passive dashboard reads).
    ``create=True``  → ``mkdir -p`` missing folders. Either way, the
    return shape is ``{host, path, overall, probes, checked}`` so the
    JSX can render rows the same way as the host-test probe block.

    Errors at the lab_base parsing stage (empty / malformed) come back
    as a single ``lab_base`` probe with status ``fail`` so the UI still
    has something to render.
    """
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    parsed = parse_lab_base(lab_base_value)
    if parsed is None:
        return {
            "host": None, "path": None,
            "overall": "fail",
            "checked": now,
            "probes": [Probe(
                name="lab_base", status="fail",
                detail="no lab_base configured for this lab — set it on Lab Settings first",
                required=True,
            ).to_dict()],
        }
    host = _build_host(parsed)
    remote = _remote.Remote(host)
    # ONE batched SSH session — biodatsci has a 3-strike auth lockout
    # (30 minutes), so we never split this into per-subdir round-trips.
    # The script prints ``<name>:<status>:<full>`` lines we parse below.
    script = _build_batched_script(parsed.path, create=create)
    try:
        result = remote.run(script, check=False, timeout=45)
    except _remote.RemoteError as exc:
        return {
            "host": parsed.host, "path": parsed.path,
            "overall": "fail",
            "checked": now,
            "probes": [
                Probe(name="ssh", status="fail",
                      detail=(exc.stderr or str(exc)).strip() or "connection failed",
                      required=True).to_dict(),
            ],
        }
    # Auth / connection failures land here too (returncode != 0 with
    # nothing useful on stdout). Surface the stderr unedited so the user
    # sees ``Permission denied`` etc. and the UI can do its own
    # lockout-detection on the message.
    if not result.ok and not (result.stdout or "").strip():
        return {
            "host": parsed.host, "path": parsed.path,
            "overall": "fail",
            "checked": now,
            "probes": [
                Probe(name="ssh", status="fail",
                      detail=(result.stderr or "").strip() or f"rc={result.returncode}",
                      required=True).to_dict(),
            ],
        }
    probes = _parse_batched_output(result.stdout, parsed, create=create)
    overall = (
        "fail" if any(p.status == "fail" for p in probes)
        else "warn" if any(p.status == "warn" for p in probes)
        else "ok"
    )
    return {
        "host": parsed.host, "path": parsed.path,
        "overall": overall,
        "checked": now,
        "probes": [p.to_dict() for p in probes],
    }


# ---------------------------------------------------------------------------
# Cached status (consumed by the dashboard's persistent green-light)
# ---------------------------------------------------------------------------


def cache_load() -> dict:
    """Read the master-folders cache. Returns ``{}`` on missing/malformed."""
    if not CACHE_FILE.is_file():
        return {}
    try:
        data = yaml.safe_load(CACHE_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def cache_save(lab_name: str, result: dict) -> None:
    """Persist the last probe result for ``lab_name``.

    Best-effort: write failure is silently ignored so a transient
    permissions issue doesn't break the running endpoint.
    """
    data = cache_load()
    data[lab_name] = result
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except OSError:
        pass


def cached_summary(lab_name: str) -> dict | None:
    """Return ``{overall, checked, host, path}`` for the dashboard
    indicator, or ``None`` if we've never probed this lab."""
    data = cache_load()
    entry = data.get(lab_name)
    if not isinstance(entry, dict):
        return None
    return {
        "overall": entry.get("overall"),
        "checked": entry.get("checked"),
        "host": entry.get("host"),
        "path": entry.get("path"),
    }
