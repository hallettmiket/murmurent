"""
Tests for clone-first local identity (core/identity_bootstrap.py + the CLI
group callback + `identity-init` / `whoami`).

Verifies: the keypair is minted on the first real command (auto), the opt-out
flag is honoured, `identity-init` is idempotent and rotates on demand, and
`whoami` surfaces the handle + fingerprint (the member's unique ID).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import identity_bootstrap as IB
from murmurent.core import idkeys as K


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wig"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    # default: allow auto-keygen (conftest globally disables it)
    monkeypatch.delenv(IB.AUTOKEY_OFF, raising=False)


# ---- ensure_local_keypair (the AUTO path) ----------------------------------

def test_ensure_mints_then_is_idempotent():
    assert K.have_keys() is False
    fp = IB.ensure_local_keypair()
    assert fp and fp.startswith("SHA256:") and K.have_keys()
    assert IB.ensure_local_keypair() == fp  # idempotent


def test_ensure_respects_optout(monkeypatch):
    monkeypatch.setenv(IB.AUTOKEY_OFF, "1")
    assert IB.ensure_local_keypair() is None
    assert K.have_keys() is False


def test_local_identity_surfaces_handle_and_fingerprint():
    ident = IB.local_identity()
    assert ident["handle"] == "@allie"
    assert ident["fingerprint"] is None  # no key yet → None
    fp = IB.ensure_local_keypair()
    assert IB.local_identity()["fingerprint"] == fp


# ---- CLI group callback: first real command mints the key ------------------

def test_first_command_auto_mints_key():
    runner = CliRunner()
    assert K.have_keys() is False
    res = runner.invoke(cli, ["doctor"])  # any subcommand triggers the callback
    assert res.exit_code == 0
    assert K.have_keys() is True


def test_optout_blocks_auto_mint(monkeypatch):
    monkeypatch.setenv(IB.AUTOKEY_OFF, "1")
    runner = CliRunner()
    runner.invoke(cli, ["doctor"])
    assert K.have_keys() is False


# ---- identity-init ----------------------------------------------------------

def test_identity_init_creates_and_reports_fingerprint(monkeypatch):
    # disable the auto-callback so identity-init itself is what creates the key
    monkeypatch.setenv(IB.AUTOKEY_OFF, "1")
    runner = CliRunner()
    res = runner.invoke(cli, ["identity-init"])
    assert res.exit_code == 0
    assert "created" in res.output
    fp = K.local_fingerprint()
    assert fp and fp in res.output


def test_identity_init_idempotent_without_rotate():
    runner = CliRunner()
    runner.invoke(cli, ["identity-init"])
    fp1 = K.local_fingerprint()
    res = runner.invoke(cli, ["identity-init"])
    assert "already present" in res.output
    assert K.local_fingerprint() == fp1  # unchanged


def test_identity_init_rotate_changes_key():
    runner = CliRunner()
    runner.invoke(cli, ["identity-init"])
    fp1 = K.local_fingerprint()
    res = runner.invoke(cli, ["identity-init", "--rotate"])
    assert res.exit_code == 0 and "rotated" in res.output
    assert K.local_fingerprint() != fp1
    assert "stale" in res.output  # warns the card must be re-issued


# ---- whoami -----------------------------------------------------------------

def test_whoami_shows_handle_and_key_id():
    runner = CliRunner()
    runner.invoke(cli, ["identity-init"])
    res = runner.invoke(cli, ["whoami"])
    assert res.exit_code == 0
    assert "@allie" in res.output
    assert K.local_fingerprint() in res.output
    assert "none imported yet" in res.output  # no card yet


def test_whoami_before_any_key(monkeypatch):
    monkeypatch.setenv(IB.AUTOKEY_OFF, "1")  # keep whoami from minting via callback
    runner = CliRunner()
    res = runner.invoke(cli, ["whoami"])
    assert res.exit_code == 0
    assert "none yet" in res.output
