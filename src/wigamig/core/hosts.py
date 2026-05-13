"""
Purpose: Per-machine registry of hosts wigamig can drive (locally + over SSH).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-13
Input: ``~/.wigamig/hosts.yaml`` (env-overridable via ``$WIGAMIG_HOSTS_FILE``).
Output: :class:`Host` dataclasses + ``read`` / ``write`` / ``resolve`` helpers.

The hosts file declares **where wigamig can install or open a project**.
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
      lab-server:
        kind: ssh
        ssh_host: lab-server         # alias in ~/.ssh/config
        remote_user: the_pi
        project_root: /home/the_pi/repos
        lab_vm_root: /data/lab_vm
        vault_root: /home/the_pi/Obsidian
        mount_point: ~/Mounts/lab-server-vault   # SSHFS mount on laptop

"local" is always defined — if the user removes it, ``read()`` re-adds
the default. Other hosts (``ssh`` kind) are added by ``wigamig host add``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILE = Path.home() / ".wigamig" / "hosts.yaml"
ENV_VAR = "WIGAMIG_HOSTS_FILE"
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
]
