"""Tests for SSH-side adopt — :mod:`wigamig.core.remote_adopt` and the
``POST /api/inventory/adopt`` branch that fires it.

We can't hit a real SSH host in tests, so :class:`Remote` is monkey-
patched: ``Remote.run`` returns a canned :class:`RemoteResult` whose
stdout matches what the real remote script would emit. This pins the
contract on both sides — script shape AND parser/probe handling.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import hosts as _hosts
from wigamig.core import remote as _remote
from wigamig.core import remote_adopt as _radopt
from wigamig.dashboard import snapshot as snap_mod
from wigamig.dashboard.server import create_app


# ---------------------------------------------------------------------------
# Script-rendering tests (no SSH involved)
# ---------------------------------------------------------------------------


def test_script_quotes_path():
    """Paths with spaces must survive the SSH bash -lc round-trip."""
    s = _radopt.build_remote_adopt_script(
        clone_path="/home/u/my repos/foo",
        project="foo",
        charter_text="---\nproject: foo\n---\n# foo\n",
        agents=["blacksmith"],
    )
    assert "'/home/u/my repos/foo'" in s


def test_script_filters_unsafe_agent_names():
    """Agent names matched by ``[A-Za-z0-9_-]+`` only — anything else
    is silently dropped so the bash ``for a in <names>`` loop can't be
    poisoned via a crafted POST body."""
    s = _radopt.build_remote_adopt_script(
        clone_path="/tmp/foo",
        project="foo",
        charter_text="---\nproject: foo\n---\n# foo\n",
        agents=["blacksmith", "evil; rm -rf /", "../bad", "ok_name"],
    )
    assert "blacksmith" in s
    assert "ok_name" in s
    assert "rm -rf" not in s
    assert "../bad" not in s


def test_script_refuses_unsafe_project_name():
    """Project name flows into ``$HOME/repos/<project>`` paths and the
    CLAUDE.md heading — must be ``[A-Za-z0-9_-]+`` or we refuse."""
    with pytest.raises(_radopt.RemoteAdoptError):
        _radopt.build_remote_adopt_script(
            clone_path="/tmp/x",
            project="bad name; rm",
            charter_text="---\nproject: x\n---\n",
            agents=[],
        )


def test_script_refuses_charter_containing_delimiter():
    """Defence-in-depth: if the charter body somehow contained our
    heredoc delimiter literally, we'd terminate the heredoc early and
    the rest of the body would run as shell. Refuse the write."""
    with pytest.raises(_radopt.RemoteAdoptError):
        _radopt.build_remote_adopt_script(
            clone_path="/tmp/x", project="x",
            charter_text="something __WIGAMIG_CHARTER_EOF__ injected\n",
            agents=[],
        )


def test_script_uses_quoted_heredoc():
    """Charter content must NOT be interpolated by the remote shell —
    use ``<<'EOF'`` not ``<<EOF`` so ``$VAR`` in the charter stays
    literal."""
    s = _radopt.build_remote_adopt_script(
        clone_path="/tmp/x", project="x",
        charter_text="---\nproject: x\n---\n# $HOME\n",
        agents=[],
    )
    assert "<<'__WIGAMIG_CHARTER_EOF__'" in s


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def test_parse_records_status_and_required():
    """Mirror of remote_install.parse_output behaviour — ``charter`` is
    the only required step (vs install where ``wigamig`` + ``repo`` are
    required because install may need to clone). Agent rows all share
    the ``cc_agent`` name (the agent name is in the detail); same as
    the install script, so the parser stays uniform across both flows.
    """
    out = "\n".join([
        "charter:ok:wrote /tmp/x/CHARTER.md",
        "cc_agent:ok:blacksmith -> wigamig/agents/blacksmith.md",
        "cc_agent:warn:bogus (no bogus.md in wigamig commons)",
        "cc_claude_md:ok:created /tmp/x/CLAUDE.md",
    ])
    probes = _radopt.parse_remote_adopt_output(out)
    by_status = [(p.name, p.status, p.required) for p in probes]
    assert ("charter", "ok", True) in by_status
    cc_rows = [p for p in probes if p.name == "cc_agent"]
    assert len(cc_rows) == 2
    assert cc_rows[0].status == "ok"
    assert cc_rows[1].status == "warn"


def test_parse_drops_malformed_lines():
    """Unparseable lines (no triple-colon) are dropped silently — they
    sometimes appear from login banners or shell init noise."""
    out = "Welcome to biodatsci\ncharter:ok:wrote /x/CHARTER.md\nrandom garbage\n"
    probes = _radopt.parse_remote_adopt_output(out)
    assert len(probes) == 1
    assert probes[0].name == "charter"


# ---------------------------------------------------------------------------
# Endpoint integration (with mocked Remote)
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated home + lab_mgmt + a registered SSH host."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "wigamig_commons"
    (commons / "agents").mkdir(parents=True)
    lab_mgmt = tmp_path / "lab_mgmt"
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@mhallet'\n---\n"
    )
    (lab_mgmt / "members" / "mhallet.md").write_text(
        "---\nhandle: '@mhallet'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\nlab: hallett\n---\n"
    )
    hosts_file = tmp_path / "hosts.yaml"
    installs = home / ".wigamig" / "installations"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(hosts_file))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    # INSTALLATIONS_DIR was captured at module-import time using the
    # real Path.home() — setenv(HOME) is too late. Patch the module
    # attribute so the endpoint's `from .snapshot import INSTALLATIONS_DIR`
    # picks up the tmp path.
    monkeypatch.setattr(snap_mod, "INSTALLATIONS_DIR", installs)
    _hosts.add(_hosts.Host(
        name="biodatsci", kind="ssh", ssh_host="biodatsci",
        remote_user="mhallet", project_root="/home/UWO/mhallet/repos",
        lab_vm_root="/data/lab_vm/wigamig",
    ))
    return {"home": home, "lab_mgmt": lab_mgmt, "tmp": tmp_path}


def _mock_remote(monkeypatch, *, probe_verdict: str = "OK",
                 adopt_stdout: str | None = None):
    """Replace Remote.run with a canned responder.

    The endpoint first runs a probe (``[ -d $path/.git ]`` → echoes
    OK / NOGIT / NOPATH) and then the batched adopt script. We map by
    looking at the command — probe is short, script is long.
    """
    calls: list[str] = []
    def fake_run(self, command, *, check=True, timeout=60):
        calls.append(command)
        if "[ -d" in command and "/.git" in command and "fi" in command and len(command) < 200:
            stdout = probe_verdict + "\n"
        else:
            # The adopt script. Default success output if none provided.
            stdout = adopt_stdout or "\n".join([
                "charter:ok:wrote /home/UWO/mhallet/repos/demo/CHARTER.md",
                "cc_agent:ok:blacksmith -> wigamig/agents/blacksmith.md",
                "cc_claude_md:ok:created /home/UWO/mhallet/repos/demo/CLAUDE.md",
            ]) + "\n"
        return _remote.RemoteResult(
            host="biodatsci", command=command,
            returncode=0, stdout=stdout, stderr="",
        )
    monkeypatch.setattr(_remote.Remote, "run", fake_run)
    return calls


def test_remote_adopt_happy_path(world, monkeypatch):
    """Full SSH adopt: probe says OK, script lands CHARTER + agents +
    CLAUDE.md, local lab_mgmt + manifest still written."""
    calls = _mock_remote(monkeypatch)
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/home/UWO/mhallet/repos/demo",
        "project": "demo",
        "lead": "@mhallet",
        "members": ["@mhallet"],
        "agents": ["blacksmith"],
        "host": "biodatsci",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["host"] == "biodatsci"
    # Local side effects: lab_mgmt registry + installation manifest.
    assert (world["lab_mgmt"] / "projects" / "demo.md").is_file()
    manifest = world["home"] / ".wigamig" / "installations" / "demo.yaml"
    assert manifest.is_file()
    m = yaml.safe_load(manifest.read_text())
    assert m["ssh_remote"] == "biodatsci"
    assert m["machine_type"] == "lab_server"
    assert m["access"] == "ssh"
    # Probes include the remote-adopt records.
    probe_names = [p["name"] for p in body["probes"]]
    assert "charter" in probe_names
    assert "cc_agent" in probe_names
    # We made at least two SSH calls: the path probe + the adopt script.
    assert len(calls) >= 2


def test_remote_adopt_refuses_when_path_missing(world, monkeypatch):
    """If the probe says NOPATH the endpoint 400s before running the
    adopt script — saves an SSH round-trip on a guaranteed failure."""
    _mock_remote(monkeypatch, probe_verdict="NOPATH")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/home/UWO/mhallet/repos/ghost",
        "project": "ghost", "lead": "@x", "members": ["@x"],
        "host": "biodatsci",
    })
    assert res.status_code == 400
    assert "does not exist on biodatsci" in res.json()["detail"]


def test_remote_adopt_refuses_non_git(world, monkeypatch):
    _mock_remote(monkeypatch, probe_verdict="NOGIT")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/home/UWO/mhallet/repos/not_a_repo",
        "project": "not_a_repo", "lead": "@x", "members": ["@x"],
        "host": "biodatsci",
    })
    assert res.status_code == 400
    assert "not a git working tree" in res.json()["detail"]


def test_remote_adopt_refuses_unknown_host(world, monkeypatch):
    """A 404 — not 400 — because the host name itself is the missing
    resource. Same status the GET /api/hosts/<name>/test path uses
    for unregistered hosts."""
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/anywhere",
        "project": "x", "lead": "@x", "members": ["@x"],
        "host": "no_such_host",
    })
    assert res.status_code == 404


def test_remote_adopt_charter_already_exists_returns_ok(world, monkeypatch):
    """If CHARTER already exists on the remote the script emits
    ``charter:ok:already exists...`` — the endpoint surfaces this as
    a 200 (not 409) because nothing was clobbered and the user can
    safely re-run."""
    _mock_remote(monkeypatch, adopt_stdout="\n".join([
        "charter:ok:already exists at /home/UWO/mhallet/repos/demo/CHARTER.md (preserved)",
        "cc_agent:ok:blacksmith -> wigamig/agents/blacksmith.md",
    ]) + "\n")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/home/UWO/mhallet/repos/demo",
        "project": "demo", "lead": "@x", "members": ["@x"],
        "host": "biodatsci",
    })
    assert res.status_code == 200
    body = res.json()
    charter_p = next(p for p in body["probes"] if p["name"] == "charter")
    assert charter_p["status"] == "ok"
    assert "preserved" in charter_p["detail"]


def test_remote_adopt_charter_fail_surfaces_as_422(world, monkeypatch):
    """If the remote script emits ``charter:fail:...`` (e.g. the
    working tree disappeared between the probe and the heredoc), we
    surface as 422 so the modal renders red status."""
    _mock_remote(monkeypatch, adopt_stdout="charter:fail:not a git working tree: /home/x\n")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": "/home/UWO/mhallet/repos/demo",
        "project": "demo", "lead": "@x", "members": ["@x"],
        "host": "biodatsci",
    })
    assert res.status_code == 422
