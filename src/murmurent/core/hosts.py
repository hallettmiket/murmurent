"""
Purpose: Per-machine registry of hosts murmurent can drive (locally + over SSH).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-13
Input: ``~/.murmurent/hosts.yaml`` (env-overridable via ``$MURMURENT_HOSTS_FILE``).
Output: :class:`Host` dataclasses + ``read`` / ``write`` / ``resolve`` helpers.

The hosts file declares **where murmurent can install or open a project**.
On a freshly installed laptop the file may be missing, in which case the
"local" host is synthesised on the fly (with sensible defaults).

Example ``hosts.yaml``::

    version: 1
    hosts:
      local:
        kind: local
        project_root: ~/repos
        lab_vm_root: ~/lab_vm/data
        vault_root: ~/Documents/Obsidian
      biodatsci:
        kind: ssh
        ssh_host: biodatsci         # alias in ~/.ssh/config
        remote_user: mhallet
        project_root: /home/mhallet/repos
        lab_vm_root: /data/lab_vm
        vault_root: /home/mhallet/Obsidian
        mount_point: ~/Mounts/biodatsci-vault   # SSHFS mount on laptop

"local" is always defined — if the user removes it, ``read()`` re-adds
the default. Other hosts (``ssh`` kind) are added by ``murmurent host add``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILE = Path.home() / ".murmurent" / "hosts.yaml"
ENV_VAR = "MURMURENT_HOSTS_FILE"
LOCAL_NAME = "local"
VALID_KINDS = frozenset({"local", "ssh"})


class HostError(ValueError):
    """Base class for host-registry invariant violations."""


class HostNotFound(HostError):
    """No host with that name in the registry."""


class HostAlreadyExists(HostError):
    """Refused: a host with that name is already registered."""


class InvalidHost(HostError):
    """Refused: host payload violates a schema rule (kind, ssh_host, etc.)."""


@dataclass(frozen=True)
class Host:
    """One row in ``hosts.yaml``.

    ``kind == "local"`` ignores ``ssh_host`` / ``remote_user``; the
    laptop's filesystem is the project root. ``kind == "ssh"`` drives
    every operation via the ``Remote`` chokepoint in :mod:`core.remote`.
    """

    name: str
    kind: str = "local"
    ssh_host: str = ""
    remote_user: str = ""
    project_root: str = "~/repos"
    lab_vm_root: str = "~/lab_vm/data"
    vault_root: str = "~/Documents/Obsidian"
    mount_point: str = ""  # SSHFS mount path on the laptop, for ssh kind
    description: str = ""
    # Extra directories to scan for git clones during repo-inventory.
    # Entries beginning with "/" are treated as absolute on the remote
    # host; others are resolved relative to $HOME. Empty tuple means
    # "use whatever the inventory scanner's default is" (currently
    # ~/repo + ~/repos).
    scan_dirs: tuple[str, ...] = ()

    def is_remote(self) -> bool:
        return self.kind == "ssh"


# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------


def hosts_file(env: dict[str, str] | None = None) -> Path:
    """Return the hosts.yaml path (env-overridable for tests)."""
    source = os.environ if env is None else env
    return Path(source.get(ENV_VAR, DEFAULT_FILE)).expanduser()


# ---------------------------------------------------------------------------
# Coercion / validation
# ---------------------------------------------------------------------------


def _str(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _coerce_scan_dirs(raw: Any) -> tuple[str, ...]:
    """Accept a list/tuple of strings; silently drop empties + non-strs
    rather than rejecting the whole host. Trims surrounding whitespace
    so ``- repos `` is treated the same as ``- repos``.
    """
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        s = entry.strip()
        if s:
            out.append(s)
    return tuple(out)


def _coerce_host(name: str, raw: dict[str, Any]) -> Host:
    kind = _str(raw.get("kind"), "local") or "local"
    if kind not in VALID_KINDS:
        raise InvalidHost(f"host {name!r}: kind must be one of {sorted(VALID_KINDS)}")
    ssh_host = _str(raw.get("ssh_host"))
    if kind == "ssh" and not ssh_host:
        raise InvalidHost(f"host {name!r}: ssh kind requires ssh_host")
    return Host(
        name=name,
        kind=kind,
        ssh_host=ssh_host,
        remote_user=_str(raw.get("remote_user")),
        project_root=_str(raw.get("project_root"), "~/repos") or "~/repos",
        lab_vm_root=_str(raw.get("lab_vm_root"), "~/lab_vm/data") or "~/lab_vm/data",
        vault_root=_str(raw.get("vault_root"), "~/Documents/Obsidian") or "~/Documents/Obsidian",
        mount_point=_str(raw.get("mount_point")),
        description=_str(raw.get("description")),
        scan_dirs=_coerce_scan_dirs(raw.get("scan_dirs")),
    )


def _default_local() -> Host:
    return Host(
        name=LOCAL_NAME,
        kind="local",
        project_root="~/repos",
        lab_vm_root="~/lab_vm/data",
        vault_root="~/Documents/Obsidian",
        description="this laptop",
    )


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def read(env: dict[str, str] | None = None) -> dict[str, Host]:
    """Return a name → :class:`Host` mapping. Always includes ``local``.

    Missing file is the "fresh install" state — we synthesise a
    local-only registry without writing it (so a read-only filesystem
    or a dry-run never surprises). Malformed entries are skipped one by
    one rather than blanking the whole table.
    """
    path = hosts_file(env)
    out: dict[str, Host] = {LOCAL_NAME: _default_local()}
    if not path.is_file():
        return out
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return out
    if not isinstance(data, dict):
        return out
    raw_hosts = data.get("hosts") or {}
    if not isinstance(raw_hosts, dict):
        return out
    for name, payload in raw_hosts.items():
        if not isinstance(payload, dict):
            continue
        try:
            host = _coerce_host(str(name), payload)
        except InvalidHost:
            continue
        out[host.name] = host
    return out


def resolve(name: str, env: dict[str, str] | None = None) -> Host:
    """Return the host with ``name`` or raise :class:`HostNotFound`."""
    registry = read(env)
    if name in registry:
        return registry[name]
    raise HostNotFound(f"no host registered as {name!r}; known: {sorted(registry)}")


def write(hosts: dict[str, Host], env: dict[str, str] | None = None) -> Path:
    """Serialise ``hosts`` to ``hosts.yaml``. Creates parent dirs.

    The ``local`` entry is always retained (re-added if absent) so the
    registry is never empty after a write.
    """
    if LOCAL_NAME not in hosts:
        hosts = {LOCAL_NAME: _default_local(), **hosts}
    path = hosts_file(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"version": 1, "hosts": {}}
    for name, host in hosts.items():
        row: dict[str, Any] = {"kind": host.kind}
        if host.ssh_host:    row["ssh_host"]    = host.ssh_host
        if host.remote_user: row["remote_user"] = host.remote_user
        row["project_root"]  = host.project_root
        row["lab_vm_root"]   = host.lab_vm_root
        row["vault_root"]    = host.vault_root
        if host.mount_point: row["mount_point"] = host.mount_point
        if host.description: row["description"] = host.description
        if host.scan_dirs:   row["scan_dirs"]   = list(host.scan_dirs)
        payload["hosts"][name] = row
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def add(host: Host, env: dict[str, str] | None = None) -> Path:
    """Append ``host`` to the registry. Refuses if the name already exists."""
    registry = read(env)
    if host.name in registry and host.name != LOCAL_NAME:
        # `local` is always re-derived; overwriting it is fine. Other
        # names must be removed first to prevent silent override.
        raise HostAlreadyExists(f"host {host.name!r} already registered")
    registry[host.name] = host
    return write(registry, env)


def remove(name: str, env: dict[str, str] | None = None) -> Path:
    """Drop ``name`` from the registry. Refuses to remove ``local``."""
    if name == LOCAL_NAME:
        raise InvalidHost("cannot remove the built-in 'local' host")
    registry = read(env)
    if name not in registry:
        raise HostNotFound(f"no host registered as {name!r}")
    del registry[name]
    return write(registry, env)


def update_scan_dirs(
    name: str,
    scan_dirs: tuple[str, ...] | list[str],
    env: dict[str, str] | None = None,
) -> Host:
    """Replace ``name``'s ``scan_dirs`` field, leaving every other field
    untouched. Returns the updated :class:`Host`.

    Works for every kind including ``local`` — when the user sets scan
    dirs for the laptop, this materialises the auto-derived ``local``
    row into ``hosts.yaml`` so the value actually persists across
    process restarts.
    """
    cleaned = _coerce_scan_dirs(scan_dirs)
    registry = read(env)
    if name not in registry:
        raise HostNotFound(f"no host registered as {name!r}")
    current = registry[name]
    updated = Host(
        name=current.name,
        kind=current.kind,
        ssh_host=current.ssh_host,
        remote_user=current.remote_user,
        project_root=current.project_root,
        lab_vm_root=current.lab_vm_root,
        vault_root=current.vault_root,
        mount_point=current.mount_point,
        description=current.description,
        scan_dirs=cleaned,
    )
    registry[name] = updated
    write(registry, env)
    return updated


__all__ = [
    "Host",
    "HostError",
    "HostNotFound",
    "HostAlreadyExists",
    "InvalidHost",
    "LOCAL_NAME",
    "VALID_KINDS",
    "hosts_file",
    "read",
    "resolve",
    "write",
    "add",
    "remove",
    "update_scan_dirs",
]
