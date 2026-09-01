"""
Purpose: Opt-in session authentication for the registrar dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-03

The dashboard historically trusted ``?user=<handle>`` from the query string:
every privileged endpoint resolved the caller from it and gated on
``is_registrar(handle)``, but the handle was attacker-controlled. Fine on a
localhost laptop; a hole the moment the dashboard is exposed (e.g. on the
murmurent server behind Caddy).

**Model — shared registrar secret → signed session cookie (Option A):**
the registrar sets one secret (``$MURMURENT_DASHBOARD_SECRET`` or
``~/.murmurent/dashboard_secret``). A login exchanges the secret for a
short-lived, HMAC-signed cookie; a middleware then requires that cookie on
every *mutating* request (POST/PUT/PATCH/DELETE), except a small public
allowlist. The secret proves membership of the trusted operator group;
per-user accountability continues via the claimed handle + the role-audit
log. Per-user credentials / GitHub OAuth are natural later upgrades.

**Opt-in:** when no secret is configured, ``auth_enabled()`` is False and the
middleware is a no-op — the laptop/dev flow and the whole test suite are
unchanged. Enforcement only turns on once a secret exists.

No third-party dependency: tokens are ``base64url(payload).base64url(hmac)``
using stdlib ``hmac``/``hashlib``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

ENV_VAR = "MURMURENT_DASHBOARD_SECRET"
SECRET_FILE = Path.home() / ".murmurent" / "dashboard_secret"
COOKIE_NAME = "wigamig_session"
DEFAULT_TTL = 12 * 3600  # 12 hours


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------

def configured_secret() -> str | None:
    """The dashboard secret from the env var, else the secret file, else None.

    Read at call time (never cached) so a test can set/clear it and the
    deployment can rotate it without a restart of this module.
    """
    v = os.environ.get(ENV_VAR)
    if v and v.strip():
        return v.strip()
    try:
        if SECRET_FILE.is_file():
            t = SECRET_FILE.read_text(encoding="utf-8").strip()
            return t or None
    except OSError:
        pass
    return None


def auth_enabled() -> bool:
    """True iff a secret is configured (i.e. enforcement is on)."""
    return configured_secret() is not None


def check_secret(candidate: str) -> bool:
    """Constant-time compare of a presented secret against the configured one."""
    s = configured_secret()
    if not s:
        return False
    return hmac.compare_digest((candidate or "").strip(), s)


# ---------------------------------------------------------------------------
# Signed tokens
# ---------------------------------------------------------------------------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload_b64: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"),
                   hashlib.sha256).digest()
    return _b64(mac)


def mint_token(handle: str, role: str, secret: str, *,
               ttl: int = DEFAULT_TTL, now: int | None = None) -> str:
    """Return a signed ``payload.signature`` session token."""
    ts = int(now if now is not None else time.time())
    payload = {"h": (handle or "").lstrip("@"), "r": role or "", "exp": ts + ttl}
    pb = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{pb}.{_sign(pb, secret)}"


def verify_token(token: str, secret: str, *, now: int | None = None) -> dict | None:
    """Return the token payload if the signature is valid and unexpired, else None."""
    if not token or "." not in token or not secret:
        return None
    pb, _, sig = token.rpartition(".")
    if not hmac.compare_digest(sig, _sign(pb, secret)):
        return None
    try:
        payload = json.loads(_unb64(pb))
    except (ValueError, json.JSONDecodeError):
        return None
    ts = int(now if now is not None else time.time())
    try:
        if int(payload.get("exp", 0)) < ts:
            return None
    except (TypeError, ValueError):
        return None
    return payload


# ---------------------------------------------------------------------------
# Request gating
# ---------------------------------------------------------------------------

# Mutating requests to these path prefixes are allowed WITHOUT a session, so
# that authentication + first-run bootstrap + the public join form still work
# once enforcement is on.
_PUBLIC_MUTATION_PREFIXES = (
    "/api/login",              # authenticate / logout / select
    "/api/centre/init",        # first-run mayor bootstrap (409s once a centre exists)
    "/api/centre/join_requests",  # the public /join form submit
)

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_public_mutation(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path == p
               for p in _PUBLIC_MUTATION_PREFIXES)


def request_needs_session(method: str, path: str) -> bool:
    """True iff (with enforcement on) this request must carry a valid session."""
    if method.upper() not in _MUTATING_METHODS:
        return False
    return not is_public_mutation(path)


__all__ = [
    "ENV_VAR", "SECRET_FILE", "COOKIE_NAME", "DEFAULT_TTL",
    "configured_secret", "auth_enabled", "check_secret",
    "mint_token", "verify_token",
    "is_public_mutation", "request_needs_session",
]
