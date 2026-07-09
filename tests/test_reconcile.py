"""Tests for :mod:`wigamig.core.reconcile` and the
``wigamig reconcile`` CLI wrapper.

What we pin:
  * Each detector finds the drift it's supposed to (orphan
    installation, orphan registry, missing CHARTER, unadopted
    clones counted via the cached inventory).
  * Dry-run is non-mutating: actionable findings appear in the
    report but the manifest / registry are untouched.
  * ``apply=True`` archives orphan manifests under
    ``installations/.archive/<name>_<date>.yaml`` and flips
    ``status: archived`` in the registry frontmatter (without
    deleting the file).
  * SSH probes are mocked at the Remote layer so the tests don't
    touch a real network.
  * The CLI exits 1 when actionable drift is found and ``--apply``
    wasn't passed, so cron / CI can branch on it.
"""

from __future__ import annotations

import yaml
import pytest
from pathlib import Path

from wigamig.core import hosts as _hosts
from wigamig.core import reconcile as _rec
from wigamig.core import remote as _remote
from wigamig.dashboard import snapshot as _snap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated $HOME + lab_mgmt + installations + inventory cache."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    installations = home / ".wigamig" / "installations"
    installations.mkdir(parents=True)
    inv_dir = home / ".wigamig" / "inventory"
    inv_dir.mkdir(parents=True)
    lab_mgmt = tmp_path / "lab_mgmt"
    (lab_mgmt / "projects").mkdir(parents=True)
    hosts_file = tmp_path / "hosts.yaml"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(hosts_file))
    # Redirect runtime constants the detectors read.
    monkeypatch.setattr(_snap, "INSTALLATIONS_DIR", installations)
    from wigamig.core import repo_inventory as _ri
    monkeypatch.setattr(_ri, "INVENTORY_DIR", inv_dir)
    return {
        "home": home, "repos": home / "repos",
        "installations": installations, "inv_dir": inv_dir,
        "lab_mgmt": lab_mgmt,
    }


def _write_manifest(installations: Path, project: str, *,
                    ssh_remote: str | None = None) -> Path:
    p = installations / f"{project}.yaml"
    p.write_text(yaml.safe_dump({
        "project": project,
        "member": "@the_pi",
        "machine_type": "lab_server" if ssh_remote else "laptop",
        "ssh_remote": ssh_remote,
        "status": "active",
    }), encoding="utf-8")
    return p


def _write_registry(lab_mgmt: Path, project: str, *,
                    host: str = "local", path: str | None = None,
                    remote_path: str | None = None,
                    status: str | None = None) -> Path:
    """Create a cert-project entry (the authoritative project registry that
    reconcile now reads). ``path`` is the local code_repo; ``host``/``remote_path``
    mark a remote-tree project. Returns the cert-project file path."""
    from wigamig.core import cert_projects as _cp
    rp = (remote_path or "/home/u/repos/" + project) if host != "local" else ""
    _cp.upsert(project, lab="hallett", member="@the_pi",
               code_repo=(path or "/repos/" + project), host=host,
               remote_path=rp, status=(status or "active"))
    return _cp.project_path(project)


def _make_clone(repos: Path, name: str, with_charter: bool = True) -> Path:
    p = repos / name
    (p / ".git").mkdir(parents=True)
    if with_charter:
        (p / "CHARTER.md").write_text(
            "---\nproject: " + name + "\nsensitivity: standard\n"
            "lead: '@the_pi'\nmembers:\n  - '@the_pi'\n---\n# " + name + "\n",
            encoding="utf-8",
        )
    return p


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def test_detect_orphan_installation_local(world):
    """A local install manifest whose ``~/repos/<project>`` working
    tree was deleted is reported as orphan_installation, actionable."""
    _write_manifest(world["installations"], "gone")
    # Note: NO clone dir for "gone" — that's the orphan.
    findings = _rec.detect_orphan_installations()
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "orphan_installation"
    assert f.target == "gone"
    assert f.host == "local"
    assert f.severity == "actionable"


def test_alive_local_install_no_finding(world):
    """When the working tree IS present, no finding fires."""
    _make_clone(world["repos"], "alive")
    _write_manifest(world["installations"], "alive")
    findings = _rec.detect_orphan_installations()
    assert findings == []


def test_detect_orphan_installation_unknown_ssh_host(world):
    """If a manifest references an SSH host that's been removed from
    the registry, we treat the install as orphaned (the user can't
    reach the clone any more, so wigamig shouldn't list it)."""
    _write_manifest(world["installations"], "stranded", ssh_remote="ghost_host")
    findings = _rec.detect_orphan_installations()
    assert len(findings) == 1
    assert findings[0].host == "ghost_host"
    assert "not registered" in findings[0].detail


def test_detect_orphan_installation_remote_ssh_probe(world, monkeypatch):
    """SSH-resident installs: one batched SSH call per host, results
    parsed into ALIVE/GONE. Mocked at the Remote layer."""
    _hosts.add(_hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server",
                           project_root="/home/u/repos"))
    _write_manifest(world["installations"], "still_here", ssh_remote="lab-server")
    _write_manifest(world["installations"], "deleted_there", ssh_remote="lab-server")

    def fake_run(self, command, *, check=True, timeout=30):
        # The batched probe checks two paths in one call.
        stdout = (
            "ALIVE:/home/u/repos/still_here\n"
            "GONE:/home/u/repos/deleted_there\n"
        )
        return _remote.RemoteResult(host="lab-server", command=command,
                                    returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(_remote.Remote, "run", fake_run)

    findings = _rec.detect_orphan_installations()
    targets = [f.target for f in findings]
    assert "deleted_there" in targets
    assert "still_here" not in targets


def test_ssh_probe_failure_is_conservative(world, monkeypatch):
    """If the SSH probe itself fails (host down, auth issue), we
    must NOT report every install on that host as orphaned — a
    transient outage shouldn't auto-trigger deactivations."""
    _hosts.add(_hosts.Host(name="lab-server", kind="ssh", ssh_host="lab-server",
                           project_root="/home/u/repos"))
    _write_manifest(world["installations"], "maybe_alive", ssh_remote="lab-server")

    def fake_run(self, command, *, check=True, timeout=30):
        raise _remote.RemoteError("network unreachable", returncode=255,
                                  stdout="", stderr="ssh: connect failed")
    monkeypatch.setattr(_remote.Remote, "run", fake_run)

    findings = _rec.detect_orphan_installations()
    assert findings == [], "transient SSH failure must not orphan installs"


def test_detect_orphan_registry_local(world):
    """A lab_mgmt registry entry pointing at a deleted local path
    is reported actionable."""
    _write_registry(world["lab_mgmt"], "stale_reg",
                    path=str(world["repos"] / "stale_reg"))
    # No clone dir at that path.
    findings = _rec.detect_orphan_registries()
    targets = [f.target for f in findings]
    assert "stale_reg" in targets


def test_archived_registry_skipped(world):
    """Already-archived registry entries are not re-reported on
    subsequent runs."""
    _write_registry(world["lab_mgmt"], "old_proj",
                    path="/nope", status="archived")
    findings = _rec.detect_orphan_registries()
    assert findings == []


def test_detect_missing_charter(world):
    """Working tree present, CHARTER.md deleted — warn, no auto-fix."""
    _make_clone(world["repos"], "charterless", with_charter=False)
    _write_manifest(world["installations"], "charterless")
    findings = _rec.detect_missing_charters()
    assert len(findings) == 1
    assert findings[0].kind == "missing_charter"
    assert findings[0].severity == "warn"
    assert "CHARTER.md is missing" in findings[0].detail


def test_detect_unadopted_clones_from_cached_inventory(world):
    """The detector reads the most recent cached inventory and rolls
    up unadopted clone counts by host."""
    # Write a minimal inventory cache file.
    inv = {
        "generated_at": "2026-05-17T00:00:00+00:00",
        "rows": [
            {
                "key": "x", "name": "x",
                "clones": [
                    {"host": "local", "path": "/x", "is_wigamig_installed": False},
                    {"host": "lab-server", "path": "/x", "is_wigamig_installed": False},
                ],
            },
            {
                "key": "y", "name": "y",
                "clones": [
                    {"host": "local", "path": "/y", "is_wigamig_installed": True},
                ],
            },
        ],
    }
    inv_path = world["inv_dir"] / "inventory_2026-05-17T000000.yaml"
    inv_path.write_text(yaml.safe_dump(inv), encoding="utf-8")
    findings = _rec.detect_unadopted_clones()
    by_host = {f.host: f for f in findings}
    assert "local" in by_host and "lab-server" in by_host
    assert by_host["local"].severity == "info"
    assert "1 git clones" in by_host["local"].detail
    assert "1 git clones" in by_host["lab-server"].detail


# ---------------------------------------------------------------------------
# Apply step
# ---------------------------------------------------------------------------


def test_apply_archives_orphan_manifest(world):
    """``apply=True`` moves the orphan manifest into the .archive/
    subdir with a date suffix; the original file is gone."""
    manifest = _write_manifest(world["installations"], "to_archive")
    report = _rec.reconcile(apply=True)
    assert not manifest.exists()
    archive_dir = world["installations"] / ".archive"
    assert archive_dir.is_dir()
    archived = list(archive_dir.glob("to_archive_*.yaml"))
    assert len(archived) == 1
    # Report records what was applied.
    assert any(f.target == "to_archive" for f in report.applied)


def test_apply_flips_registry_status_archived(world):
    """``apply=True`` on an orphan registry adds ``status: archived``
    + ``archived_at`` to the frontmatter; the file is preserved
    (lab history is shared, not deleted)."""
    reg = _write_registry(world["lab_mgmt"], "to_flip",
                          path=str(world["repos"] / "to_flip"))
    _rec.reconcile(apply=True)
    assert reg.exists()
    text = reg.read_text()
    assert "status: archived" in text
    assert "archived_at:" in text


def test_dry_run_does_not_mutate(world):
    """Without ``apply``, neither the manifest nor the registry is
    touched even when actionable findings exist."""
    manifest = _write_manifest(world["installations"], "untouched")
    reg = _write_registry(world["lab_mgmt"], "untouched_reg",
                          path=str(world["repos"] / "untouched_reg"))
    before_m = manifest.read_text()
    before_r = reg.read_text()
    report = _rec.reconcile(apply=False)
    assert manifest.read_text() == before_m
    assert reg.read_text() == before_r
    # Findings still recorded.
    assert len(report.findings) >= 2
    assert report.applied == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_exits_1_on_actionable_dry_run(world):
    """When there's actionable drift and ``--apply`` wasn't passed,
    the CLI returns exit code 1 so cron / CI can branch."""
    _write_manifest(world["installations"], "dirty")
    from wigamig.commands.reconcile_cmd import cmd_reconcile
    rc = cmd_reconcile(apply=False, slack_body=False)
    assert rc == 1


def test_cli_exits_0_when_clean(world):
    """Clean state → exit 0."""
    from wigamig.commands.reconcile_cmd import cmd_reconcile
    rc = cmd_reconcile(apply=False, slack_body=False)
    assert rc == 0


def test_cli_exits_0_after_apply(world):
    """After ``--apply`` repairs the actionable findings, exit 0."""
    _write_manifest(world["installations"], "dirty")
    from wigamig.commands.reconcile_cmd import cmd_reconcile
    rc = cmd_reconcile(apply=True, slack_body=False)
    assert rc == 0
