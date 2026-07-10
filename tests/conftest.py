"""Global test guards.

The most important one: **never let the test suite make a live Slack call**,
even on a developer machine that has a real ``~/.config/murmurent/slack-token``.
Without this, tests that exercise notification paths (join requests, SEA
lifecycle, broadcasts) would resolve the real token from that file and post
fixture data (``@diego``, ``p_test``, …) into a real workspace channel.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_live_slack(monkeypatch):
    """Neutralise Slack token resolution for every test.

    Clears ambient env tokens and points the token-file fallback at a
    nonexistent path, so ``slack_notify._token()`` returns ``None`` by default
    and all posting/invite helpers no-op. A test that specifically needs a
    token still opts in with ``monkeypatch.setenv(...)`` (and mocks ``httpx``);
    env is checked before the file, so those keep working.
    """
    from murmurent.dashboard import slack_notify as _sn

    monkeypatch.delenv("MURMURENT_SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(_sn, "_TOKEN_FILE", Path("/nonexistent/wigamig-test-slack-token"))
    # Drop any token cached by a prior test. A test may itself monkeypatch
    # _token to a plain callable (no cache_clear), so guard the attribute.
    getattr(_sn._token, "cache_clear", lambda: None)()
    yield
    getattr(_sn._token, "cache_clear", lambda: None)()


@pytest.fixture(autouse=True)
def _no_autokey(monkeypatch):
    """Never mint an ed25519 keypair in the developer's real ``~/.murmurent`` just
    because a test invoked the CLI (the ``cli`` group callback auto-generates one
    on first run). Bootstrap tests opt back in with ``monkeypatch.delenv`` + an
    isolated ``MURMURENT_HOME``."""
    monkeypatch.setenv("MURMURENT_NO_AUTOKEY", "1")


@pytest.fixture(autouse=True)
def _isolate_wigamig_home(monkeypatch, tmp_path):
    """Point ``MURMURENT_HOME`` at a per-test temp dir. Everything that reads
    ``~/.murmurent`` at runtime — the dashboard's netname enforcement + card
    verification, key generation, the issuance/revocation stores — is then
    isolated, so a test can neither read nor pollute the developer's real home
    (a leaked ``identity.yaml`` there used to 403 unrelated dashboard tests).
    Tests that need a specific home simply set ``MURMURENT_HOME`` again."""
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "_wig_home"))


@pytest.fixture(autouse=True)
def _isolate_repos_root(monkeypatch, tmp_path):
    """Point ``MURMURENT_REPOS_ROOT`` at a per-test temp dir so anything that creates
    a lab-mgmt repo (``pi-init`` → ``~/repos/wigamig_<lab>``) never writes into the
    developer's real ``~/repos``."""
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path / "_repos"))
