"""Tests for :mod:`murmurent.core.keyring` (Phase 1 MVP).

Weighted toward the security-negative assertions: a ``server``-role machine must
NOT be able to open a ``mayor``-only box even though it holds the file, and an
unauthorised machine must open nothing. Multi-machine is simulated by flipping
``MURMURENT_HOME`` (per-machine identity) while sharing ``MURMURENT_LAB_INFO_ROOT``
(the one repo every machine pulls).
"""

from __future__ import annotations

import os
import stat

import pytest

from murmurent.core import age_crypto as A
from murmurent.core import keyring as K

pytestmark = pytest.mark.skipif(not A.age_available(), reason="age not installed")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _use_machine(monkeypatch, home):
    """Switch 'this machine' by pointing MURMURENT_HOME at a per-machine dir."""
    monkeypatch.setenv("MURMURENT_HOME", str(home))


def _init(monkeypatch, home) -> str:
    _use_machine(monkeypatch, home)
    return K.ensure_identity()


# --------------------------------------------------------------------------- #
# unit — no age needed for this one
# --------------------------------------------------------------------------- #
def test_recipients_for_maps_roles(monkeypatch, tmp_path):
    K.save_recipients({"version": 1, "machines": [
        {"label": "laptop", "recipient": "age1laptop", "role": "mayor"},
        {"label": "server", "recipient": "age1server", "role": "server"},
    ]})
    assert K.recipients_for({"consumers": ["mayor", "server"]}) == ["age1laptop", "age1server"]
    # a mayor-only secret must never include the server key
    assert K.recipients_for({"consumers": ["mayor"]}) == ["age1laptop"]


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
def test_init_is_idempotent_and_stable(monkeypatch, tmp_path):
    home = tmp_path / "h1"
    rec1 = _init(monkeypatch, home)
    assert rec1.startswith("age1")
    assert K.ensure_identity() == rec1          # idempotent
    assert K.identity_recipient() == rec1        # readable back from file
    mode = stat.S_IMODE(K.identity_path().stat().st_mode)
    assert mode == 0o600


# --------------------------------------------------------------------------- #
# single-machine round trip
# --------------------------------------------------------------------------- #
def test_seed_and_unlock_same_machine(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("slack-token", "xoxb-SECRET",
                 target=str(tmp_path / "out" / "slack-token"),
                 consumers=["mayor", "server"])
    assert K.unlock_secret("slack-token") == "xoxb-SECRET"


# --------------------------------------------------------------------------- #
# multi-machine: the core happy path
# --------------------------------------------------------------------------- #
def test_second_machine_obtains_secret(monkeypatch, tmp_path):
    # machine 1 (mayor) seeds
    rec1 = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec1, "laptop", "mayor")
    K.set_secret("slack-token", "xoxb-REAL",
                 target=str(tmp_path / "out" / "slack-token"),
                 consumers=["mayor", "server"])

    # machine 2 makes its own identity
    rec2 = _init(monkeypatch, tmp_path / "h2")
    assert rec2 != rec1

    # machine 1 authorises machine 2 (server) → re-locks the box to include it
    _use_machine(monkeypatch, tmp_path / "h1")
    res = K.authorize(rec2, "server-prod", "server")
    assert "slack-token" in res["relocked"]

    # machine 2 syncs and obtains the exact bytes
    _use_machine(monkeypatch, tmp_path / "h2")
    items = {i.name: i for i in K.sync(apply=True)}
    assert items["slack-token"].action == "write"
    target = tmp_path / "out" / "slack-token"
    assert target.read_text() == "xoxb-REAL"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    # idempotent: a second sync writes nothing
    assert K.sync(apply=True)[0].action == "unchanged"


# --------------------------------------------------------------------------- #
# SECURITY-NEGATIVE — the assertions that matter most
# --------------------------------------------------------------------------- #
def test_server_role_cannot_open_mayor_only_box(monkeypatch, tmp_path):
    """The crown-jewel promise: a server-role machine holds the file but the
    box has no slot for it, so it cannot decrypt."""
    rec1 = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec1, "laptop", "mayor")
    rec2 = _init(monkeypatch, tmp_path / "h2")
    _use_machine(monkeypatch, tmp_path / "h1")
    K.authorize(rec2, "server-prod", "server")

    # mayor-only secret
    K.set_secret("root-key", "TOP-SECRET-CA",
                 target=str(tmp_path / "out" / "root-key"),
                 consumers=["mayor"])

    # the box exists and the server can read the FILE, but not its contents
    assert K.secret_box_path("root-key").is_file()
    _use_machine(monkeypatch, tmp_path / "h2")           # now "the server"
    with pytest.raises(K.KeyringError):
        K.unlock_secret("root-key")

    # and sync skips it rather than erroring/leaking
    actions = {i.name: i.action for i in K.sync(apply=True)}
    assert actions["root-key"] == "skip-not-entitled"
    assert not (tmp_path / "out" / "root-key").exists()


def test_unauthorized_machine_opens_nothing(monkeypatch, tmp_path):
    rec1 = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec1, "laptop", "mayor")
    K.set_secret("slack-token", "xoxb", target=str(tmp_path / "o" / "s"),
                 consumers=["mayor", "server"])
    # a machine that never got authorised
    _init(monkeypatch, tmp_path / "h3")
    assert K.this_machine() is None
    with pytest.raises(K.KeyringError):
        K.sync(apply=True)
    with pytest.raises(K.KeyringError):
        K.unlock_secret("slack-token")


def test_tampered_box_fails_closed(monkeypatch, tmp_path):
    rec1 = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec1, "laptop", "mayor")
    K.set_secret("s", "value", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    box = K.secret_box_path("s")
    body = box.read_text()
    # flip a character in the armored body
    box.write_text(body[:-6] + ("A" if body[-6] != "A" else "B") + body[-5:])
    with pytest.raises(K.KeyringError):
        K.unlock_secret("s")


# --------------------------------------------------------------------------- #
# behaviour edge cases
# --------------------------------------------------------------------------- #
def test_dry_run_does_not_write(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    target = tmp_path / "o" / "s"
    K.set_secret("s", "v", target=str(target), consumers=["mayor"])
    items = K.sync(apply=False)
    assert items[0].action == "would-write"
    assert not target.exists()          # dry-run wrote nothing


def test_update_value_re_locks_and_backs_up(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    target = tmp_path / "o" / "s"
    K.set_secret("s", "v1", target=str(target), consumers=["mayor"])
    K.sync(apply=True)
    assert target.read_text() == "v1"
    # rotate the value
    K.set_secret("s", "v2", target=str(target), consumers=["mayor"])
    assert K.unlock_secret("s") == "v2"
    K.sync(apply=True)
    assert target.read_text() == "v2"
    assert target.with_suffix(target.suffix + ".bak").read_text() == "v1"   # backed up


def test_reauthorize_updates_role_not_duplicate(monkeypatch, tmp_path):
    rec1 = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec1, "laptop", "mayor")
    rec2 = _init(monkeypatch, tmp_path / "h2")
    _use_machine(monkeypatch, tmp_path / "h1")
    K.authorize(rec2, "box2", "server")
    K.authorize(rec2, "box2", "server")            # same machine again
    machines = K.load_recipients()["machines"]
    assert sum(1 for m in machines if m["recipient"] == rec2) == 1   # no duplicate


def test_lock_without_recipients_raises(monkeypatch, tmp_path):
    _init(monkeypatch, tmp_path / "h1")            # identity but nobody authorised
    # manifest entry whose role nobody holds
    K.save_manifest({"version": 1, "secrets": [
        {"name": "x", "target": str(tmp_path / "x"), "mode": "0600", "consumers": ["server"]}]})
    with pytest.raises(K.KeyringError):
        K.lock_secret("x", "v")


def test_bad_role_rejected(monkeypatch, tmp_path):
    _init(monkeypatch, tmp_path / "h1")
    with pytest.raises(K.KeyringError):
        K.authorize("age1whatever", "m", "wizard")


# --------------------------------------------------------------------------- #
# CLI smoke — the group is wired in
# --------------------------------------------------------------------------- #
def test_cli_group_registered():
    from click.testing import CliRunner

    from murmurent.cli import cli
    res = CliRunner().invoke(cli, ["keyring", "--help"])
    assert res.exit_code == 0
    assert "init" in res.output and "authorize" in res.output and "sync" in res.output


def test_cli_status_reflects_role(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from murmurent.cli import cli
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    # --no-pull: there is no remote here; show the local roster
    res = CliRunner().invoke(cli, ["keyring", "status", "--no-pull"])
    assert res.exit_code == 0
    assert "role=mayor" in res.output and "authorised:  yes" in res.output


# --------------------------------------------------------------------------- #
# health check
# --------------------------------------------------------------------------- #
def test_health_check_healthy(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("slack", "v", target=str(tmp_path / "o" / "slack"),
                 consumers=["mayor", "server"])
    K.sync(apply=True)
    checks = K.health_check()
    assert all(c.status != "fail" for c in checks)
    assert any(c.name == "secret:slack" and c.status == "ok" for c in checks)


def test_health_check_no_identity(monkeypatch, tmp_path):
    _use_machine(monkeypatch, tmp_path / "empty")     # never init'd
    checks = K.health_check()
    assert checks[-1].name == "machine identity" and checks[-1].status == "fail"


def test_health_check_reports_no_leak(monkeypatch, tmp_path):
    recA = _init(monkeypatch, tmp_path / "h1")
    K.authorize(recA, "laptop", "mayor")
    recB = _init(monkeypatch, tmp_path / "h2")
    _use_machine(monkeypatch, tmp_path / "h1")
    K.authorize(recB, "srv", "server")
    K.set_secret("slack", "v", target=str(tmp_path / "o" / "slack"),
                 consumers=["mayor", "server"])
    K.set_secret("ca", "TOP-SECRET", target=str(tmp_path / "o" / "ca"),
                 consumers=["mayor"])                  # mayor-only
    _use_machine(monkeypatch, tmp_path / "h2")         # the server
    K.sync(apply=True)
    checks = K.health_check()
    assert all(c.status != "fail" for c in checks)     # NO leak reported
    ca = next(c for c in checks if c.name == "secret:ca")
    assert ca.status == "ok" and "refused" in ca.detail


def test_cli_check_exit_codes(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from murmurent.cli import cli
    _use_machine(monkeypatch, tmp_path / "empty")
    assert CliRunner().invoke(cli, ["keyring", "check", "--no-pull"]).exit_code != 0
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("s", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    K.sync(apply=True)
    r = CliRunner().invoke(cli, ["keyring", "check", "--no-pull"])
    assert r.exit_code == 0 and "HEALTHY" in r.output


# --------------------------------------------------------------------------- #
# Phase 2 — rotate / revoke / atomic writes / --push
# --------------------------------------------------------------------------- #
def test_rotate_secret_changes_value(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("slack", "v1", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    K.rotate_secret("slack", "v2")
    assert K.unlock_secret("slack") == "v2"
    with pytest.raises(K.KeyringError):
        K.rotate_secret("does-not-exist", "x")


def test_revoke_removes_relocks_and_flags(monkeypatch, tmp_path):
    recA = _init(monkeypatch, tmp_path / "h1")
    K.authorize(recA, "laptop", "mayor")
    recB = _init(monkeypatch, tmp_path / "h2")
    _use_machine(monkeypatch, tmp_path / "h1")
    K.authorize(recB, "srv", "server")
    K.set_secret("slack", "tok", target=str(tmp_path / "o" / "s"),
                 consumers=["mayor", "server"])
    K.set_secret("ca", "secret", target=str(tmp_path / "o" / "ca"), consumers=["mayor"])

    _use_machine(monkeypatch, tmp_path / "h2")          # B can open slack before revoke
    assert K.unlock_secret("slack") == "tok"

    _use_machine(monkeypatch, tmp_path / "h1")          # mayor revokes B
    res = K.revoke("srv")
    assert res["role"] == "server"
    assert res["must_rotate"] == ["slack"]              # only what B's role could read
    assert "slack" in res["relocked"]

    _use_machine(monkeypatch, tmp_path / "h2")          # B can no longer open the re-locked box
    with pytest.raises(K.KeyringError):
        K.unlock_secret("slack")

    _use_machine(monkeypatch, tmp_path / "h1")
    with pytest.raises(K.KeyringError):
        K.revoke("ghost")


def test_bak_backup_is_private(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    target = tmp_path / "o" / "s"
    K.set_secret("s", "v1", target=str(target), consumers=["mayor"])
    K.sync(apply=True)
    K.rotate_secret("s", "v2")
    K.sync(apply=True)
    bak = target.with_suffix(target.suffix + ".bak")
    assert bak.read_text() == "v1"
    assert stat.S_IMODE(bak.stat().st_mode) == 0o600    # the OLD secret is not world-readable


def test_cli_set_secret_push_commits(monkeypatch, tmp_path):
    import subprocess

    from click.testing import CliRunner

    from murmurent.cli import cli
    li = tmp_path / "_lab_info_git"
    li.mkdir()
    subprocess.run(["git", "init", "-q", str(li)], check=True)
    subprocess.run(["git", "-C", str(li), "config", "user.email", "t@e.invalid"], check=True)
    subprocess.run(["git", "-C", str(li), "config", "user.name", "t"], check=True)
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    r = CliRunner().invoke(cli, ["keyring", "set-secret", "s", "--value", "v",
                                 "--target", str(tmp_path / "o" / "s"),
                                 "--consumers", "mayor", "--push"])
    assert r.exit_code == 0
    log = subprocess.run(["git", "-C", str(li), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "set secret s" in log


def test_push_tolerates_untracked_files(monkeypatch, tmp_path):
    """A no-op/other-files situation must not be misreported as a commit failure
    (git's 'nothing added to commit but untracked files present')."""
    import subprocess

    from click.testing import CliRunner

    from murmurent.cli import cli
    li = tmp_path / "_li"
    li.mkdir()
    subprocess.run(["git", "init", "-q", str(li)], check=True)
    subprocess.run(["git", "-C", str(li), "config", "user.email", "t@e.invalid"], check=True)
    subprocess.run(["git", "-C", str(li), "config", "user.name", "t"], check=True)
    (li / "other-governance-file.md").write_text("untracked\n")   # unrelated
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    r = CliRunner().invoke(cli, ["keyring", "set-secret", "s", "--value", "v",
                                 "--target", str(tmp_path / "o" / "s"),
                                 "--consumers", "mayor", "--push"])
    assert r.exit_code == 0
    assert "commit failed" not in r.output


def test_set_secret_stores_portable_target(monkeypatch, tmp_path):
    """A target under the current home is stored ~-relative so a peer with a
    different username unpacks under ITS own home (regression: a shell-expanded
    ~ used to hardcode /Users/<me>/... into the manifest)."""
    import os
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    abs_home_target = os.path.join(os.path.expanduser("~"), ".config/murmurent/demo")
    K.set_secret("demo", "v", target=abs_home_target, consumers=["mayor"])
    entry = next(s for s in K.load_manifest()["secrets"] if s["name"] == "demo")
    assert entry["target"] == "~/.config/murmurent/demo"          # re-tilded
    K.set_secret("d2", "v", target="/var/lib/murmurent/x", consumers=["mayor"])
    e2 = next(s for s in K.load_manifest()["secrets"] if s["name"] == "d2")
    assert e2["target"] == "/var/lib/murmurent/x"                 # outside home → absolute kept


def test_set_secret_no_recipients_leaves_no_dangling_entry(monkeypatch, tmp_path):
    """A lock failure must NOT persist a manifest entry with no matching box."""
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")                          # only a mayor in the roster
    with pytest.raises(K.KeyringError):
        K.set_secret("x", "v", target=str(tmp_path / "o" / "x"), consumers=["server"])
    assert K._secret_by_name("x") is None                        # manifest not polluted
    assert not K.secret_box_path("x").is_file()                  # no box either


def test_set_secret_rejects_bad_mode(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    with pytest.raises(K.KeyringError):
        K.set_secret("x", "v", target=str(tmp_path / "o" / "x"),
                     mode="0999", consumers=["mayor"])           # 9 is not octal


def test_sync_repairs_mode_drift(monkeypatch, tmp_path):
    import os
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    target = tmp_path / "o" / "x"
    K.set_secret("x", "v", target=str(target), mode="0600", consumers=["mayor"])
    K.sync(apply=True)
    os.chmod(target, 0o644)                                       # drift the mode
    items = {i.name: i for i in K.sync(apply=True)}
    assert items["x"].action == "mode-fixed"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert K.sync(apply=True)[0].action == "unchanged"           # idempotent after repair


def test_health_check_tolerates_bad_mode(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("x", "v", target=str(tmp_path / "o" / "x"), consumers=["mayor"])
    K.sync(apply=True)
    man = K.load_manifest()
    man["secrets"][0]["mode"] = "0999"                           # hand-edit an invalid mode
    K.save_manifest(man)
    sc = next(c for c in K.health_check() if c.name == "secret:x")   # must not raise
    assert sc.status == "fail" and "invalid mode" in sc.detail


def test_corrupt_keyring_files_raise_clear_error(monkeypatch, tmp_path):
    K.keyring_dir().mkdir(parents=True, exist_ok=True)
    (K.keyring_dir() / "recipients.yaml").write_text("- not\n- a\n- mapping\n")
    with pytest.raises(K.KeyringError):
        K.load_recipients()
    (K.keyring_dir() / "manifest.yaml").write_text("secrets: [oops\n")   # unclosed → YAMLError
    with pytest.raises(K.KeyringError):
        K.load_manifest()


# --------------------------------------------------------------------------- #
# Phase 3 — repo-side verify
# --------------------------------------------------------------------------- #
def test_verify_repo_healthy(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("slack", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    checks = K.verify_repo()
    assert all(c.status != "fail" for c in checks)
    assert any(c.name == "secret:slack" and c.status == "ok" for c in checks)


def test_verify_repo_detects_missing_box_and_orphan(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("slack", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    K.secret_box_path("slack").unlink()                    # box gone → fail
    assert any(c.name == "secret:slack" and c.status == "fail" for c in K.verify_repo())
    K.set_secret("slack", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    (K.secrets_dir() / "ghost.age").write_text("x")        # box with no manifest → orphan warn
    assert any(c.name.startswith("orphan:") and c.status == "warn" for c in K.verify_repo())


def test_verify_repo_flags_unopenable_secret(monkeypatch, tmp_path):
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("s", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    man = K.load_manifest()
    man["secrets"][0]["consumers"] = ["server"]            # no server machine in roster
    K.save_manifest(man)
    sc = next(c for c in K.verify_repo() if c.name == "secret:s")
    assert sc.status == "warn" and "open" in sc.detail


def test_cli_verify_exit_codes(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from murmurent.cli import cli
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    K.set_secret("s", "v", target=str(tmp_path / "o" / "s"), consumers=["mayor"])
    r = CliRunner().invoke(cli, ["keyring", "verify", "--no-pull"])
    assert r.exit_code == 0 and "VALID" in r.output
    K.secret_box_path("s").unlink()
    assert CliRunner().invoke(cli, ["keyring", "verify", "--no-pull"]).exit_code != 0


# --------------------------------------------------------------------------- #
# Phase 3 — reconcile auto-sync
# --------------------------------------------------------------------------- #
def test_reconcile_keyring_autosync_heals(monkeypatch, tmp_path):
    from murmurent.commands.reconcile_cmd import _keyring_autosync
    rec = _init(monkeypatch, tmp_path / "h1")
    K.authorize(rec, "laptop", "mayor")
    target = tmp_path / "o" / "s"
    K.set_secret("s", "v", target=str(target), consumers=["mayor"])
    assert not target.exists()
    _keyring_autosync(apply=True)                 # reconcile loop self-heals
    assert target.read_text() == "v"


def test_reconcile_autosync_noop_without_keyring(monkeypatch, tmp_path):
    from murmurent.commands.reconcile_cmd import _keyring_autosync
    _use_machine(monkeypatch, tmp_path / "empty")  # no identity
    _keyring_autosync(apply=True)                  # must be a silent, non-fatal no-op
