"""
Purpose: Thin wrappers around the `age` CLI for the encrypted-email join flow.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-03

A prospective member encrypts their join form to the centre's **age public
key** (published in the wigamig_public directory) and emails the ciphertext.
The mayor decrypts it locally with the centre's **private key**. Nothing about
the member is ever readable in transit or on GitHub.

`age` (https://age-encryption.org) is a single small binary; we shell out to
it rather than take a Python dependency. `keygen`/`encrypt`/`decrypt` raise
``AgeError`` on any failure (missing binary, bad key, malformed ciphertext).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class AgeError(RuntimeError):
    """An `age` operation failed (missing binary, bad key, etc.)."""


def age_available() -> bool:
    return shutil.which("age") is not None and shutil.which("age-keygen") is not None


def default_key_path() -> Path:
    """Where the mayor's private key lives (per-machine, mode 0600)."""
    return Path.home() / ".wigamig" / "age" / "mayor.key"


def keygen(key_path: Path | None = None) -> str:
    """Generate an age key pair. Write the **private** key to ``key_path``
    (0600) and return the **public** recipient (``age1…``), which is safe to
    publish. Refuses to overwrite an existing key."""
    if shutil.which("age-keygen") is None:
        raise AgeError("age-keygen not found; install age (https://age-encryption.org).")
    path = key_path or default_key_path()
    if path.exists():
        raise AgeError(f"key already exists at {path}; refusing to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["age-keygen", "-o", str(path)],
                           capture_output=True, text=True, check=False)
    except OSError as exc:
        raise AgeError(f"age-keygen failed: {exc}") from exc
    if r.returncode != 0:
        raise AgeError(f"age-keygen failed: {r.stderr.strip()}")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    # age-keygen prints "Public key: age1..." to stderr; also present as a
    # comment line in the key file.
    m = re.search(r"(age1[0-9a-z]+)", (r.stderr or "") + "\n" + path.read_text(encoding="utf-8"))
    if not m:
        raise AgeError("could not determine the public recipient from age-keygen output")
    return m.group(1)


def encrypt(recipient: str, plaintext: str) -> str:
    """Return ASCII-armored ciphertext of ``plaintext`` encrypted to
    ``recipient`` (an ``age1…`` public key)."""
    if shutil.which("age") is None:
        raise AgeError("age not found; install age (https://age-encryption.org).")
    if not (recipient or "").startswith("age1"):
        raise AgeError(f"not a valid age recipient: {recipient!r}")
    try:
        r = subprocess.run(["age", "-a", "-r", recipient],
                           input=plaintext, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise AgeError(f"age encrypt failed: {exc}") from exc
    if r.returncode != 0:
        raise AgeError(f"age encrypt failed: {r.stderr.strip()}")
    return r.stdout


def decrypt(ciphertext: str, key_path: Path | None = None) -> str:
    """Decrypt armored ``ciphertext`` with the private key at ``key_path``
    (default: the mayor key). Returns the plaintext."""
    if shutil.which("age") is None:
        raise AgeError("age not found; install age (https://age-encryption.org).")
    path = key_path or default_key_path()
    if not path.is_file():
        raise AgeError(f"no private key at {path}; run `wigamig centre-age-keygen` first.")
    try:
        r = subprocess.run(["age", "-d", "-i", str(path)],
                           input=ciphertext, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise AgeError(f"age decrypt failed: {exc}") from exc
    if r.returncode != 0:
        raise AgeError(f"age decrypt failed: {r.stderr.strip()}")
    return r.stdout


__all__ = ["AgeError", "age_available", "default_key_path",
           "keygen", "encrypt", "decrypt"]
