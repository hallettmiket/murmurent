"""Tests for the Phase A registrar layer.

Covers:
  - ``is_registrar`` honours the sentinel file
  - Registry I/O round-trip (read → write → read)
  - ``bootstrap_from_existing_lab_mgmt`` idempotency + lab.md reading
  - ``build_registrar_response`` follows pointers, deduplicates members,
    and surfaces unresolved entries without crashing
  - ``GET /api/registrar/dashboard`` gates on identity (403 for non-registrar)
"""

from __future__ import annotations

import datetime as _dt
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import registrar
from murmurent.core.registrar import (
    CollaborationEntry,
    CoreEntry,
    LabEntry,
    Registry,
)
from murmurent.dashboard import registrar_snapshot as rs
from murmurent.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect every registrar-touched path into tmp_path."""
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(
        registrar, "REGISTRAR_SENTINEL", tmp_path / "registrar_sentinel"
    )
    # A registrar only exists within a centre — the machine sentinel is honoured
    # only once a centre is bootstrapped (a fresh install grants nobody registrar
    # access). These tests model a registrar's environment, so treat the centre as
    # bootstrapped. (Mock rather than write centre.md, since some tests mkdir the
    # lab_info dir themselves.)
    from murmurent.core import centre_init as _ci
    monkeypatch.setattr(_ci, "is_initialised", lambda env=None: True)
    # Also block other resolvers so the test doesn't leak the real user.
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    return tmp_path


def _make_lab_mgmt(root: Path, *, lab_id: str, pi: str, members: list[tuple[str, str]]) -> Path:
    """Scaffold a fake lab-mgmt repo with lab.md and members/."""
    lab_dir = root / f"{lab_id}-lab-mgmt"
    (lab_dir / "members").mkdir(parents=True)
    (lab_dir / "lab.md").write_text(
        "---\n"
        f"lab: {lab_id}\n"
        f"name: {lab_id.title()} Lab\n"
        f"pi: '@{pi}'\n"
        "institution: Western University\n"
        "created: 2026-01-01\n"
        "---\n\n# the lab\n",
        encoding="utf-8",
    )
    for handle, role in members:
        (lab_dir / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: {handle.title()}\n"
            f"role: {role}\n"
            "status: active\n"
            "certifications:\n  - TCPS_2:2030-12-31\n"
            "---\n",
            encoding="utf-8",
        )
    return lab_dir


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_is_registrar_false_when_sentinel_missing(isolated):
    assert registrar.is_registrar("mhallet") is False
    assert registrar.registrar_handle() is None


def test_is_registrar_true_for_declared_handle(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    assert registrar.registrar_handle() == "mhallet"
    assert registrar.is_registrar("mhallet") is True
    assert registrar.is_registrar("@mhallet") is True
    assert registrar.is_registrar("MHALLET") is True
    assert registrar.is_registrar("bob") is False


def test_is_registrar_ignores_blank_lines(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("\n\n  mhallet  \n# comment\n", encoding="utf-8")
    assert registrar.registrar_handle() == "mhallet"


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------


def test_read_registry_empty_when_file_missing(isolated):
    reg = registrar.read_registry()
    assert reg.labs == []
    assert reg.cores == []
    assert reg.collaborations == []


def test_registry_round_trip(isolated):
    original = Registry(
        labs=[
            LabEntry(name="hallett", pi="@mhallet",
                     lab_mgmt_path="/tmp/x", status="active",
                     created="2026-05-08", github_org="hallettmiket"),
        ],
        cores=[
            CoreEntry(name="imaging", pi="@cassie",
                      lab_mgmt_path="/tmp/y", status="active"),
        ],
        collaborations=[
            CollaborationEntry(
                name="dcis_imaging",
                pis=["@mhallet", "@cassie"],
                groups=["hallett", "imaging"],
                member_subset={"hallett": ["@allie"], "imaging": ["@bob"]},
            ),
        ],
    )
    registrar.write_registry(original)
    reread = registrar.read_registry()

    assert [l.name for l in reread.labs] == ["hallett"]
    assert reread.labs[0].pi == "@mhallet"
    assert reread.labs[0].github_org == "hallettmiket"
    assert [c.name for c in reread.cores] == ["imaging"]
    assert reread.collaborations[0].pis == ["@mhallet", "@cassie"]
    assert reread.collaborations[0].member_subset == {
        "hallett": ["@allie"], "imaging": ["@bob"],
    }


def test_read_registry_skips_malformed_entries(isolated):
    """One bad section shouldn't blank the whole registrar dashboard."""
    bad = {
        "version": 1,
        "labs": {
            "good": {"pi": "@x", "lab_mgmt_path": "/tmp/x"},
            "bad": "not a dict — should be skipped",
        },
    }
    registrar.registry_path().parent.mkdir(parents=True)
    registrar.registry_path().write_text(yaml.safe_dump(bad), encoding="utf-8")
    reg = registrar.read_registry()
    assert [l.name for l in reg.labs] == ["good"]


def test_read_registry_handles_completely_malformed_yaml(isolated):
    registrar.registry_path().parent.mkdir(parents=True)
    registrar.registry_path().write_text(": : :\n", encoding="utf-8")
    reg = registrar.read_registry()
    assert reg.labs == []  # fail safe — not a crash


# ---------------------------------------------------------------------------
# bootstrap_from_existing_lab_mgmt
# ---------------------------------------------------------------------------


def test_bootstrap_reads_labmd_and_seeds_registry(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc")],
    )
    reg = registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    assert [l.name for l in reg.labs] == ["hallett"]
    assert reg.labs[0].pi == "@mhallet"
    assert reg.labs[0].lab_mgmt_path == str(lab_dir)


def test_bootstrap_is_idempotent(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    reg = registrar.read_registry()
    assert len(reg.labs) == 1  # not duplicated


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def test_snapshot_renders_lab_with_members(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc"), ("cassie", "student")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    resp = rs.build_registrar_response("mhallet")
    assert resp.registrar_handle == "@mhallet"
    assert len(resp.labs) == 1
    lab = resp.labs[0]
    assert lab.name == "hallett"
    assert lab.display_name == "Hallett Lab"
    assert lab.member_count == 3
    assert {m.handle for m in lab.members} == {"@mhallet", "@bob", "@cassie"}
    assert lab.unresolved is False
    assert resp.stats.total_labs == 1
    assert resp.stats.total_members == 3


def test_snapshot_dedupes_members_across_labs(isolated, tmp_path):
    lab_a = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc")],
    )
    lab_b = _make_lab_mgmt(
        tmp_path, lab_id="other", pi="otherpi",
        members=[("otherpi", "pi"), ("bob", "postdoc")],  # bob is in both
    )
    registrar.write_registry(Registry(labs=[
        LabEntry(name="hallett", pi="@mhallet", lab_mgmt_path=str(lab_a)),
        LabEntry(name="other", pi="@otherpi", lab_mgmt_path=str(lab_b)),
    ]))
    resp = rs.build_registrar_response("mhallet")
    # mhallet, bob, otherpi — deduped → 3 unique members
    assert resp.stats.total_members == 3
    assert resp.stats.total_labs == 2


def test_snapshot_flags_unresolved_pointer(isolated):
    registrar.write_registry(Registry(labs=[
        LabEntry(name="ghost", pi="@nobody", lab_mgmt_path="/does/not/exist"),
    ]))
    resp = rs.build_registrar_response("mhallet")
    assert len(resp.labs) == 1
    assert resp.labs[0].unresolved is True
    assert "does not exist" in (resp.labs[0].unresolved_reason or "")


def test_snapshot_never_reads_notebooks_or_oracles(isolated, tmp_path, monkeypatch):
    """Hard contract: the registrar dashboard must NOT call into
    notebook / oracle / sea / inventory snapshot helpers."""
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    # If we ever start importing these in registrar_snapshot, the test
    # will trip — guards against accidental leakage of lab-private data
    # into the centre-level dashboard.
    blocked = []
    def _sentinel(*a, **k):
        blocked.append("called")
        raise AssertionError("registrar must not access lab-private data")

    from murmurent.dashboard import snapshot as lab_snap
    for name in ("_notebook", "_personal_oracle", "_oracle_recent",
                 "_inventory", "_seas"):
        monkeypatch.setattr(lab_snap, name, _sentinel, raising=False)

    # Should succeed without ever calling those.
    rs.build_registrar_response("mhallet")
    assert blocked == []


# ---------------------------------------------------------------------------
# Endpoint gate
# ---------------------------------------------------------------------------


def test_endpoint_403_when_not_registrar(isolated):
    """Without a registrar sentinel, the endpoint must refuse."""
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 403
    assert "registrar" in res.text.lower()


def test_endpoint_200_when_registrar(isolated, tmp_path):
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[("mhallet", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["registrar_handle"] == "@mhallet"
    assert len(payload["labs"]) == 1
    assert payload["labs"][0]["name"] == "hallett"


def test_endpoint_user_override_query_param(isolated):
    """``?user=bob`` against a sentinel of ``mhallet`` must still 403."""
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard?user=bob")
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Phase B: create_lab
# ---------------------------------------------------------------------------


def _seed_registrar(isolated):
    """Declare mhallet as registrar; assume isolated fixture is active."""
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")


def test_create_lab_scaffolds_files_and_registry(isolated):
    _seed_registrar(isolated)
    entry = registrar.create_lab(
        name="ortega", display_name="Ortega Lab",
        pi_handle="jortega", pi_full_name="Jane Ortega",
        slack_workspace="T01ABC", github_org="ortegalab",
        oracle_vault="wigamig_vault_ortega",
    )
    assert entry.name == "ortega"
    assert entry.pi == "@jortega"

    # Files on disk:
    lab_mgmt = Path(entry.lab_mgmt_path)
    assert (lab_mgmt / "lab.md").is_file()
    assert (lab_mgmt / "members" / "jortega.md").is_file()
    for sub in ("members", "projects", "requests", "audit"):
        assert (lab_mgmt / sub).is_dir()

    # Registry was updated:
    reg = registrar.read_registry()
    assert [l.name for l in reg.labs] == ["ortega"]
    assert reg.labs[0].pi == "@jortega"
    assert reg.labs[0].github_org == "ortegalab"


def test_create_lab_renders_labmd_frontmatter_correctly(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="jortega",
        institution="Western University",
        department="Schulich",
    )
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "lab.md").meta
    assert meta["lab"] == "ortega"
    assert meta["name"] == "Ortega Lab"
    assert meta["pi"] == "@jortega"
    assert meta["institution"] == "Western University"
    assert meta["department"] == "Schulich"
    assert "created" in meta


def test_create_lab_pi_member_file_has_pi_role(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab",
        pi_handle="jortega", pi_full_name="Jane Ortega",
    )
    from murmurent.core.frontmatter import parse_file
    member_md = registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "members" / "jortega.md"
    meta = parse_file(member_md).meta
    assert meta["handle"] == "@jortega"
    assert meta["full_name"] == "Jane Ortega"
    assert meta["role"] == "pi"
    assert meta["status"] == "active"
    assert meta["lab"] == "ortega"


def test_create_lab_refuses_duplicate_name(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="jortega",
    )
    with pytest.raises(registrar.LabAlreadyExists):
        registrar.create_lab(
            name="ortega", display_name="Ortega Lab 2", pi_handle="other",
        )


def test_create_lab_refuses_pi_already_leading(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="jortega",
    )
    with pytest.raises(registrar.PIAlreadyLeadsAnother):
        registrar.create_lab(
            name="other", display_name="Other Lab", pi_handle="jortega",
        )


def test_create_lab_refuses_invalid_name(isolated):
    _seed_registrar(isolated)
    for bad in ("UPPERCASE", "with space", "starts1with2digits-no-wait", "-leading-dash",
                "", "1starts_with_digit"):
        with pytest.raises(registrar.InvalidLabName):
            registrar.create_lab(name=bad, display_name="X", pi_handle="p")


def test_create_lab_normalises_pi_handle(isolated):
    """`@JOrtega` should land as `@jortega` in storage."""
    _seed_registrar(isolated)
    entry = registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="@JOrtega",
    )
    assert entry.pi == "@jortega"
    # And the member file path uses the normalised handle too.
    assert (Path(entry.lab_mgmt_path) / "members" / "jortega.md").is_file()


def test_create_lab_initialises_git_repo_and_commits(isolated):
    """Phase B audit trail: first create_lab() lays down a git repo
    on the lab_info root and records the change as a commit."""
    _seed_registrar(isolated)
    root = registrar.lab_info_root()
    assert not (root / ".git").exists()
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="jortega",
    )
    assert (root / ".git").is_dir(), "lab_info root must auto-init as a git repo"
    # At least one commit, mentioning the lab name + PI in the subject.
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "ortega" in log
    assert "@jortega" in log


def test_create_lab_each_mutation_is_its_own_commit(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.create_lab(name="other", display_name="Other Lab", pi_handle="otherpi")
    log = subprocess.run(
        ["git", "-C", str(registrar.lab_info_root()), "log", "--oneline"],
        check=True, capture_output=True, text=True,
    ).stdout.strip().splitlines()
    # One commit per lab. (No bootstrap commit because the bootstrap
    # helper isn't called in this test.)
    assert len(log) == 2


# ---------------------------------------------------------------------------
# Endpoint: POST /api/registrar/lab
# ---------------------------------------------------------------------------


def test_endpoint_create_lab_403_when_not_registrar(isolated):
    client = TestClient(create_app())
    res = client.post("/api/registrar/lab", json={
        "name": "x", "display_name": "X", "pi_handle": "p",
    })
    assert res.status_code == 403


def test_endpoint_create_lab_200_when_registrar(isolated):
    _seed_registrar(isolated)
    client = TestClient(create_app())
    res = client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab",
        "pi_handle": "jortega", "pi_full_name": "Jane Ortega",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["lab"]["name"] == "ortega"
    assert body["lab"]["pi"] == "@jortega"
    # Now it should appear in the dashboard.
    res2 = client.get("/api/registrar/dashboard")
    assert res2.status_code == 200
    assert [l["name"] for l in res2.json()["labs"]] == ["ortega"]


def test_endpoint_create_lab_409_on_pi_conflict(isolated):
    _seed_registrar(isolated)
    client = TestClient(create_app())
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
    })
    res = client.post("/api/registrar/lab", json={
        "name": "other", "display_name": "Other Lab", "pi_handle": "jortega",
    })
    assert res.status_code == 409
    assert "PI" in res.text or "lead" in res.text


def test_endpoint_create_lab_400_on_invalid_name(isolated):
    _seed_registrar(isolated)
    client = TestClient(create_app())
    res = client.post("/api/registrar/lab", json={
        "name": "Invalid Name!", "display_name": "X", "pi_handle": "p",
    })
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Phase C: archive / unarchive / update_lab_metadata
# ---------------------------------------------------------------------------


def test_archive_lab_flips_status_and_preserves_files(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    lab_md = registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "lab.md"
    assert lab_md.is_file()

    entry = registrar.archive_lab("ortega")
    assert entry.status == "archived"
    # Files untouched:
    assert lab_md.is_file()
    # Registry reflects it:
    reg = registrar.read_registry()
    assert next(l.status for l in reg.labs if l.name == "ortega") == "archived"


def test_archive_lab_is_idempotent(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.archive_lab("ortega")
    # Second call is a no-op; should not raise.
    entry = registrar.archive_lab("ortega")
    assert entry.status == "archived"


def test_archive_lab_raises_when_missing(isolated):
    _seed_registrar(isolated)
    with pytest.raises(registrar.LabNotFound):
        registrar.archive_lab("nothing_here")


def test_archive_frees_pi_for_new_lab(isolated):
    """After archiving, the freed PI can lead a brand-new lab."""
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.archive_lab("ortega")
    # Should succeed — jortega is no longer leading an active lab.
    entry = registrar.create_lab(name="ortega2", display_name="Ortega Lab 2", pi_handle="jortega")
    assert entry.pi == "@jortega"


def test_unarchive_lab_brings_it_back(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.archive_lab("ortega")
    entry = registrar.unarchive_lab("ortega")
    assert entry.status == "active"


def test_unarchive_refuses_when_pi_now_leads_another(isolated):
    """Once a PI has taken over a new active lab, unarchiving the old
    one would violate one-PI-per-active-lab and must be refused."""
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.archive_lab("ortega")
    registrar.create_lab(name="ortega2", display_name="Ortega Lab 2", pi_handle="jortega")
    with pytest.raises(registrar.PIAlreadyLeadsAnother):
        registrar.unarchive_lab("ortega")


def test_archive_lands_its_own_audit_commit(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.archive_lab("ortega")
    log = subprocess.run(
        ["git", "-C", str(registrar.lab_info_root()), "log", "--oneline"],
        check=True, capture_output=True, text=True,
    ).stdout
    # Two commits: create then archive.
    assert "create lab ortega" in log
    assert "archive" in log.lower() or "archived" in log.lower()


# update_lab_metadata
# ---------------


def test_update_changes_display_name_and_persists_to_lab_md(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.update_lab_metadata("ortega", display_name="Ortega Group")

    from murmurent.core.frontmatter import parse_file
    meta = parse_file(registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "lab.md").meta
    assert meta["name"] == "Ortega Group"
    # Other fields untouched:
    assert meta["lab"] == "ortega"
    assert meta["pi"] == "@jortega"


def test_update_clears_optional_field_with_empty_string(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(
        name="ortega", display_name="Ortega Lab", pi_handle="jortega",
        slack_workspace="T01ABC",
    )
    registrar.update_lab_metadata("ortega", slack_workspace="")
    # Registry now has None:
    entry = next(l for l in registrar.read_registry().labs if l.name == "ortega")
    assert entry.slack_workspace is None
    # lab.md no longer has the key:
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "lab.md").meta
    assert "slack_workspace" not in meta


def test_update_pi_handoff_writes_new_member_file(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.update_lab_metadata(
        "ortega", pi_handle="kortega", pi_full_name="Kim Ortega",
    )
    members_dir = registrar.lab_info_root() / "labs" / "ortega" / "lab-mgmt" / "members"
    # Old member file preserved (lab roster decision, not registrar's).
    assert (members_dir / "jortega.md").is_file()
    # New PI gets a member file.
    new_pi_md = members_dir / "kortega.md"
    assert new_pi_md.is_file()
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(new_pi_md).meta
    assert meta["role"] == "pi"
    assert meta["handle"] == "@kortega"
    assert meta["full_name"] == "Kim Ortega"


def test_update_pi_handoff_refuses_when_target_already_leads(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    registrar.create_lab(name="other", display_name="Other Lab", pi_handle="otherpi")
    with pytest.raises(registrar.PIAlreadyLeadsAnother):
        registrar.update_lab_metadata("ortega", pi_handle="otherpi")


def test_update_is_a_no_op_when_no_fields_supplied(isolated):
    _seed_registrar(isolated)
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega")
    # No-op kwargs — must not raise, must not change anything.
    registrar.update_lab_metadata("ortega")
    entry = next(l for l in registrar.read_registry().labs if l.name == "ortega")
    assert entry.pi == "@jortega"
    assert entry.status == "active"


def test_update_lab_not_found(isolated):
    _seed_registrar(isolated)
    with pytest.raises(registrar.LabNotFound):
        registrar.update_lab_metadata("missing", display_name="x")


# Phase C endpoints
# ---------------


def _client_as_registrar(isolated):
    _seed_registrar(isolated)
    return TestClient(create_app())


def test_endpoint_archive_403_when_not_registrar(isolated):
    registrar.create_lab(name="ortega", display_name="Ortega Lab", pi_handle="jortega") \
        if False else None  # need registrar to bootstrap; do it manually:
    _seed_registrar(isolated)
    client = TestClient(create_app())
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
    })
    # Strip the sentinel to simulate a non-registrar caller.
    registrar.REGISTRAR_SENTINEL.unlink()
    res = client.post("/api/registrar/lab/ortega/archive")
    assert res.status_code == 403


def test_endpoint_archive_404_for_unknown_lab(isolated):
    client = _client_as_registrar(isolated)
    res = client.post("/api/registrar/lab/no_such_lab/archive")
    assert res.status_code == 404


def test_endpoint_archive_then_unarchive_round_trip(isolated):
    client = _client_as_registrar(isolated)
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
    })
    r1 = client.post("/api/registrar/lab/ortega/archive")
    assert r1.status_code == 200
    assert r1.json()["lab"]["status"] == "archived"
    r2 = client.post("/api/registrar/lab/ortega/unarchive")
    assert r2.status_code == 200
    assert r2.json()["lab"]["status"] == "active"


def test_endpoint_unarchive_409_when_pi_now_active_elsewhere(isolated):
    client = _client_as_registrar(isolated)
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
    })
    client.post("/api/registrar/lab/ortega/archive")
    client.post("/api/registrar/lab", json={
        "name": "ortega2", "display_name": "Ortega Lab 2", "pi_handle": "jortega",
    })
    res = client.post("/api/registrar/lab/ortega/unarchive")
    assert res.status_code == 409


def test_endpoint_edit_changes_metadata(isolated):
    client = _client_as_registrar(isolated)
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
        "slack_workspace": "T01ABC",
    })
    res = client.post("/api/registrar/lab/ortega/edit", json={
        "display_name": "Ortega Group",
        "slack_workspace": "",  # clear
        "github_org": "ortegahub",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lab"]["github_org"] == "ortegahub"
    assert body["lab"]["slack_workspace"] is None


def test_endpoint_edit_409_on_pi_conflict(isolated):
    client = _client_as_registrar(isolated)
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
    })
    client.post("/api/registrar/lab", json={
        "name": "other", "display_name": "Other Lab", "pi_handle": "otherpi",
    })
    res = client.post("/api/registrar/lab/ortega/edit", json={"pi_handle": "otherpi"})
    assert res.status_code == 409


def test_endpoint_edit_partial_post_preserves_unsent_fields(isolated):
    """Posting only display_name must not clear pi_handle / github_org."""
    client = _client_as_registrar(isolated)
    client.post("/api/registrar/lab", json={
        "name": "ortega", "display_name": "Ortega Lab", "pi_handle": "jortega",
        "github_org": "ortegalab",
    })
    res = client.post("/api/registrar/lab/ortega/edit", json={"display_name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["lab"]["pi"] == "@jortega"
    assert res.json()["lab"]["github_org"] == "ortegalab"


# ---------------------------------------------------------------------------
# Phase C+: cross-group certifications panel
# ---------------------------------------------------------------------------


def _seed_lab_with_compliance(
    root: Path,
    *,
    lab_id: str,
    pi: str,
    members: list[tuple[str, str, list[str]]],
    required_codes: list[tuple[str, str, int | None, str]] | None = None,
) -> Path:
    """Scaffold a lab-mgmt repo with compliance.md and members carrying certs.

    ``members`` is a list of ``(handle, role, [cert_strings])``.
    ``required_codes`` is a list of ``(code, name, cadence_years, audience)``;
    defaults to TCPS_2 only when None.
    """
    lab_dir = root / f"{lab_id}-lab-mgmt"
    (lab_dir / "members").mkdir(parents=True)
    (lab_dir / "lab.md").write_text(
        f"---\nlab: {lab_id}\nname: {lab_id.title()} Lab\npi: '@{pi}'\n---\n",
        encoding="utf-8",
    )
    required = required_codes or [("TCPS_2", "TCPS 2", 3, "all")]
    required_yaml = "\n".join(
        f"  - code: {c}\n    name: {n}\n    short: {c.lower()}\n"
        f"    cadence_years: {('null' if y is None else y)}\n    audience: {a}"
        for (c, n, y, a) in required
    )
    (lab_dir / "compliance.md").write_text(
        "---\nrequired:\n" + required_yaml + "\n---\n",
        encoding="utf-8",
    )
    for handle, role, certs in members:
        cert_lines = "\n".join(f"  - {c}" for c in certs)
        (lab_dir / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: {handle.title()}\n"
            f"role: {role}\n"
            "status: active\n"
            "certifications:\n" + cert_lines + "\n"
            "---\n",
            encoding="utf-8",
        )
    return lab_dir


def test_cert_panel_renders_one_row_per_member_group(isolated, tmp_path):
    _seed_registrar(isolated)
    lab_a = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[
            ("mhallet", "pi", ["TCPS_2:2030-12-31"]),
            ("bob", "postdoc", ["TCPS_2:2028-06-15"]),
        ],
    )
    lab_b = _seed_lab_with_compliance(
        tmp_path, lab_id="ortega", pi="jortega",
        members=[
            ("jortega", "pi", ["TCPS_2:2027-06-15"]),
        ],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_a)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_b)

    resp = rs.build_registrar_response("mhallet", today=_dt.date(2026, 5, 12))
    panel = resp.certs
    handles_by_group = {(r.group, r.handle) for r in panel.rows}
    assert ("hallett", "@mhallet") in handles_by_group
    assert ("hallett", "@bob") in handles_by_group
    assert ("ortega", "@jortega") in handles_by_group
    assert "TCPS_2" in [s.code for s in panel.cert_specs]


def test_cert_panel_aggregate_counts_issues(isolated, tmp_path):
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[
            ("mhallet", "pi", ["TCPS_2:2030-12-31"]),  # ok
            ("bob",     "postdoc", ["TCPS_2:2024-01-01"]),  # expired (today=2026-05)
            ("cassie",  "student", []),  # missing TCPS_2
        ],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    resp = rs.build_registrar_response("mhallet", today=_dt.date(2026, 5, 12))
    a = resp.certs.aggregate
    assert a.members_total == 3
    assert a.expired_count == 1   # bob
    assert a.missing_count == 1   # cassie
    assert a.members_with_issues == 2


def test_cert_panel_uses_each_groups_own_compliance(isolated, tmp_path):
    """A cert that's required in lab A might be unknown to lab B; the
    registrar must read each group's compliance.md, not a single global."""
    _seed_registrar(isolated)
    lab_a = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi", ["TCPS_2:2030-12-31"])],
        required_codes=[("TCPS_2", "TCPS 2", 3, "all")],
    )
    lab_b = _seed_lab_with_compliance(
        tmp_path, lab_id="ortega", pi="jortega",
        members=[("jortega", "pi", ["WHM103:2030-12-31"])],
        required_codes=[("WHM103", "WHMIS", None, "all")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_a)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_b)

    resp = rs.build_registrar_response("mhallet", today=_dt.date(2026, 5, 12))
    # Both cert codes surface in the column header, each with its
    # own short name + cadence for the JSX tooltip.
    seen_codes = [s.code for s in resp.certs.cert_specs]
    assert "TCPS_2" in seen_codes
    assert "WHM103" in seen_codes
    # mhallet's TCPS_2 status is ok; he has no row in ortega (different lab).
    mhallet_row = next(r for r in resp.certs.rows if r.handle == "@mhallet")
    assert mhallet_row.group == "hallett"
    assert any(c.code == "TCPS_2" and c.status == "ok" for c in mhallet_row.certs)


def test_cert_panel_skips_archived_labs(isolated, tmp_path):
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi", ["TCPS_2:2030-12-31"])],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    registrar.archive_lab("hallett")
    resp = rs.build_registrar_response("mhallet", today=_dt.date(2026, 5, 12))
    assert resp.certs.rows == []
    assert resp.certs.aggregate.members_total == 0


def test_cert_panel_endpoint_returns_panel(isolated, tmp_path):
    """The HTTP endpoint surfaces the cert panel in the JSON payload."""
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi", ["TCPS_2:2030-12-31"])],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert "certs" in body
    specs = body["certs"]["cert_specs"]
    assert [s["code"] for s in specs] == ["TCPS_2"]
    # Short name + full name surface, matching the PI dashboard.
    assert specs[0]["short"] == "tcps_2"
    assert specs[0]["name"] == "TCPS 2"
    assert len(body["certs"]["rows"]) == 1


def test_load_config_at_reads_arbitrary_path(tmp_path):
    """The new load_config_at must work without env vars set."""
    from murmurent.core import compliance
    p = tmp_path / "compliance.md"
    p.write_text(
        "---\nrequired:\n"
        "  - code: TCPS_2\n    name: TCPS 2\n    short: tcps2\n"
        "    cadence_years: 3\n    audience: all\n"
        "---\n",
        encoding="utf-8",
    )
    cfg = compliance.load_config_at(p)
    assert len(cfg.required) == 1
    assert cfg.required[0].code == "TCPS_2"


def test_load_config_at_returns_default_when_missing(tmp_path):
    from murmurent.core import compliance
    cfg = compliance.load_config_at(tmp_path / "no_such_file.md")
    # Falls back to the default set; should not raise.
    assert isinstance(cfg.required, list)


# ---------------------------------------------------------------------------
# Phase C+: registrar's own profile (centre-level contact)
# ---------------------------------------------------------------------------


def test_read_profile_empty_when_file_missing(isolated):
    assert registrar.read_profile() == {}


def test_write_profile_round_trip(isolated):
    _seed_registrar(isolated)
    registrar.write_profile({
        "full_name": "Mike Hallett",
        "title": "Centre Director",
        "email": "mh@uwo.ca",
        "office": "MSB-360",
    })
    meta = registrar.read_profile()
    assert meta["full_name"] == "Mike Hallett"
    assert meta["title"] == "Centre Director"
    assert meta["email"] == "mh@uwo.ca"
    assert meta["office"] == "MSB-360"
    assert registrar.profile_path().is_file()


def test_write_profile_partial_post_preserves_other_fields(isolated):
    """Saving just ``office`` must not blank ``email`` from a prior write."""
    _seed_registrar(isolated)
    registrar.write_profile({"email": "mh@uwo.ca", "office": "OLD-100"})
    registrar.write_profile({"office": "MSB-360"})  # only office
    meta = registrar.read_profile()
    assert meta["email"] == "mh@uwo.ca"
    assert meta["office"] == "MSB-360"


def test_write_profile_empty_string_clears_field(isolated):
    _seed_registrar(isolated)
    registrar.write_profile({"email": "mh@uwo.ca"})
    registrar.write_profile({"email": ""})
    meta = registrar.read_profile()
    assert "email" not in meta


def test_write_profile_creates_audit_commit(isolated):
    _seed_registrar(isolated)
    registrar.write_profile({"full_name": "Mike Hallett"})
    log = subprocess.run(
        ["git", "-C", str(registrar.lab_info_root()), "log", "--oneline"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "profile" in log.lower()


def test_endpoint_profile_403_when_not_registrar(isolated):
    client = TestClient(create_app())
    res = client.post("/api/registrar/profile", json={"full_name": "x"})
    assert res.status_code == 403


def test_endpoint_profile_persists_changes(isolated):
    _seed_registrar(isolated)
    client = TestClient(create_app())
    res = client.post("/api/registrar/profile", json={
        "full_name": "Mike Hallett",
        "email": "mh@uwo.ca",
    })
    assert res.status_code == 200, res.text
    # Snapshot now reflects the new values.
    dash = client.get("/api/registrar/dashboard").json()
    assert dash["profile"]["full_name"] == "Mike Hallett"
    assert dash["profile"]["email"] == "mh@uwo.ca"
    assert dash["profile"]["handle"] == "@mhallet"


def test_snapshot_profile_handle_always_set(isolated):
    """Even with no profile file, the snapshot's profile carries the handle."""
    _seed_registrar(isolated)
    resp = rs.build_registrar_response("mhallet")
    assert resp.profile.handle == "@mhallet"


# ---------------------------------------------------------------------------
# Cross-link gate: is_registrar flag on the lab dashboard's identity block
# ---------------------------------------------------------------------------


def test_lab_dashboard_identity_has_is_registrar_flag(isolated, tmp_path, monkeypatch):
    """The lab dashboard exposes ``member.is_registrar=True`` only for the
    handle declared in ~/.wigamig/registrar — used to gate the
    "→ registrar" cross-link in the PI dashboard footer."""
    _seed_registrar(isolated)
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi")],
    )
    # Point the lab dashboard at the seeded lab-mgmt + provide the
    # other roots its snapshot expects.
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos_empty"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm_empty"))
    (tmp_path / "repos_empty").mkdir()
    (tmp_path / "lab_vm_empty").mkdir()
    client = TestClient(create_app())
    res = client.get("/api/dashboard")
    assert res.status_code == 200, res.text
    assert res.json()["member"]["is_registrar"] is True


def test_lab_dashboard_is_registrar_false_for_non_registrar(isolated, tmp_path, monkeypatch):
    """Switching to a non-registrar handle flips the flag false."""
    _seed_registrar(isolated)
    # This models a single-lab install with NO centre registry, so the scoping
    # gate must fall through and let the lab member in. Undo the fixture's
    # "centre initialised" mock for this case.
    from murmurent.core import centre_init as _ci
    monkeypatch.setattr(_ci, "is_initialised", lambda env=None: False)
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc")],
    )
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_dir))
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos_empty"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm_empty"))
    (tmp_path / "repos_empty").mkdir()
    (tmp_path / "lab_vm_empty").mkdir()
    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=bob")
    assert res.status_code == 200, res.text
    assert res.json()["member"]["is_registrar"] is False


# ---------------------------------------------------------------------------
# Phase E: cores (parallel to labs, different terminology)
# ---------------------------------------------------------------------------


def test_create_core_scaffolds_files(isolated):
    _seed_registrar(isolated)
    entry = registrar.create_core(
        name="imaging", display_name="Imaging Core",
        leader_handle="dlee", leader_full_name="Diane Lee",
        slack_workspace="T01ABC",
    )
    assert entry.name == "imaging"
    assert entry.pi == "@dlee"
    assert entry.slack_workspace == "T01ABC"
    core_dir = registrar.lab_info_root() / "cores" / "imaging" / "lab-mgmt"
    assert (core_dir / "lab.md").is_file()
    assert (core_dir / "members" / "dlee.md").is_file()


def test_create_core_lab_md_declares_core_short_id(isolated):
    """The frontmatter uses ``core:`` (not ``lab:``) for the short ID."""
    _seed_registrar(isolated)
    registrar.create_core(
        name="imaging", display_name="Imaging Core", leader_handle="dlee",
    )
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(
        registrar.lab_info_root() / "cores" / "imaging" / "lab-mgmt" / "lab.md"
    ).meta
    assert meta["core"] == "imaging"
    assert meta["name"] == "Imaging Core"
    assert meta["pi"] == "@dlee"


def test_create_core_member_file_uses_core_leader_role(isolated):
    _seed_registrar(isolated)
    registrar.create_core(
        name="imaging", display_name="Imaging Core",
        leader_handle="dlee", leader_full_name="Diane Lee",
    )
    from murmurent.core.frontmatter import parse_file
    member_md = registrar.lab_info_root() / "cores" / "imaging" / "lab-mgmt" / "members" / "dlee.md"
    meta = parse_file(member_md).meta
    assert meta["handle"] == "@dlee"
    assert meta["role"] == "core_leader"
    assert meta["lab"] == "imaging"  # group field; lab key shared with labs for plumbing


def test_create_core_name_collides_with_existing_lab(isolated):
    """Cores and labs share the same name namespace — a name can be one
    or the other, not both. This avoids ambiguity in collaborations."""
    _seed_registrar(isolated)
    registrar.create_lab(name="hallett", display_name="Hallett Lab", pi_handle="mhallet")
    with pytest.raises(registrar.LabAlreadyExists, match="collides"):
        registrar.create_core(name="hallett", display_name="Hallett Core", leader_handle="other")


def test_create_core_refuses_when_leader_already_runs_a_lab(isolated):
    """One-leader-per-active-group spans both labs AND cores."""
    _seed_registrar(isolated)
    registrar.create_lab(name="hallett", display_name="Hallett Lab", pi_handle="mhallet")
    with pytest.raises(registrar.PIAlreadyLeadsAnother, match="lab 'hallett'"):
        registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="mhallet")


def test_create_core_frees_after_archive_of_lab(isolated):
    """Archive a lab → its PI can now lead a core."""
    _seed_registrar(isolated)
    registrar.create_lab(name="hallett", display_name="Hallett Lab", pi_handle="mhallet")
    registrar.archive_lab("hallett")
    entry = registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="mhallet")
    assert entry.pi == "@mhallet"


def test_archive_unarchive_core_round_trip(isolated):
    _seed_registrar(isolated)
    registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="dlee")
    archived = registrar.archive_core("imaging")
    assert archived.status == "archived"
    unarchived = registrar.unarchive_core("imaging")
    assert unarchived.status == "active"


def test_unarchive_core_refuses_when_leader_now_runs_another(isolated):
    _seed_registrar(isolated)
    registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="dlee")
    registrar.archive_core("imaging")
    registrar.create_lab(name="hallett", display_name="Hallett Lab", pi_handle="dlee")
    with pytest.raises(registrar.PIAlreadyLeadsAnother):
        registrar.unarchive_core("imaging")


def test_update_core_metadata(isolated):
    _seed_registrar(isolated)
    registrar.create_core(
        name="imaging", display_name="Imaging Core", leader_handle="dlee",
        slack_workspace="T01ABC",
    )
    registrar.update_core_metadata("imaging", display_name="Imaging Facility", slack_workspace="")
    entry = next(c for c in registrar.read_registry().cores if c.name == "imaging")
    assert entry.slack_workspace is None
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(
        registrar.lab_info_root() / "cores" / "imaging" / "lab-mgmt" / "lab.md"
    ).meta
    assert meta["name"] == "Imaging Facility"
    assert "slack_workspace" not in meta


def test_update_core_leader_handoff_creates_new_member_file(isolated):
    _seed_registrar(isolated)
    registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="dlee")
    registrar.update_core_metadata("imaging", leader_handle="kpark", leader_full_name="Kim Park")
    members_dir = registrar.lab_info_root() / "cores" / "imaging" / "lab-mgmt" / "members"
    assert (members_dir / "dlee.md").is_file()  # untouched
    assert (members_dir / "kpark.md").is_file()  # new
    from murmurent.core.frontmatter import parse_file
    meta = parse_file(members_dir / "kpark.md").meta
    assert meta["role"] == "core_leader"
    assert meta["full_name"] == "Kim Park"


# Phase E endpoints
# -----------------


def _client_as_registrar_phase_e(isolated):
    _seed_registrar(isolated)
    return TestClient(create_app())


def test_endpoint_create_core_403_when_not_registrar(isolated):
    client = TestClient(create_app())
    res = client.post("/api/registrar/core", json={
        "name": "imaging", "display_name": "Imaging Core", "leader_handle": "dlee",
    })
    assert res.status_code == 403


def test_endpoint_create_core_409_on_lab_namespace_collision(isolated):
    client = _client_as_registrar_phase_e(isolated)
    client.post("/api/registrar/lab", json={
        "name": "hallett", "display_name": "Hallett Lab", "pi_handle": "mhallet",
    })
    res = client.post("/api/registrar/core", json={
        "name": "hallett", "display_name": "Hallett Core", "leader_handle": "other",
    })
    assert res.status_code == 409


def test_endpoint_core_archive_unarchive_round_trip(isolated):
    client = _client_as_registrar_phase_e(isolated)
    client.post("/api/registrar/core", json={
        "name": "imaging", "display_name": "Imaging Core", "leader_handle": "dlee",
    })
    r1 = client.post("/api/registrar/core/imaging/archive")
    assert r1.status_code == 200
    assert r1.json()["core"]["status"] == "archived"
    r2 = client.post("/api/registrar/core/imaging/unarchive")
    assert r2.status_code == 200
    assert r2.json()["core"]["status"] == "active"


def test_endpoint_core_edit_preserves_unsent_fields(isolated):
    client = _client_as_registrar_phase_e(isolated)
    client.post("/api/registrar/core", json={
        "name": "imaging", "display_name": "Imaging Core",
        "leader_handle": "dlee", "github_org": "imaging-core",
    })
    res = client.post("/api/registrar/core/imaging/edit", json={"display_name": "Renamed"})
    assert res.status_code == 200
    body = res.json()["core"]
    assert body["leader"] == "@dlee"
    assert body["github_org"] == "imaging-core"


def test_dashboard_payload_renders_core_with_leader_field(isolated):
    """The contract field is ``leader`` (not ``pi``) for cores —
    matches the UI's "Core leader" label."""
    client = _client_as_registrar_phase_e(isolated)
    client.post("/api/registrar/core", json={
        "name": "imaging", "display_name": "Imaging Core",
        "leader_handle": "dlee", "slack_workspace": "T01ABC",
    })
    body = client.get("/api/registrar/dashboard").json()
    cores = body["cores"]
    assert len(cores) == 1
    assert cores[0]["leader"] == "@dlee"
    assert cores[0]["slack_workspace"] == "T01ABC"
    assert cores[0]["display_name"] == "Imaging Core"
    # And the stats counter sees it.
    assert body["stats"]["total_cores"] == 1


def test_collaboration_can_span_lab_and_core(isolated, tmp_path):
    """Cores participate in collaborations the same way labs do."""
    _seed_registrar(isolated)
    # One lab the registrar-on-this-machine isn't tied to.
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("allie", "postdoc")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    # And a core created via the registrar.
    registrar.create_core(name="imaging", display_name="Imaging Core", leader_handle="dlee")
    collab = registrar.create_collaboration(
        name="dcis_imaging",
        pis=["@mhallet", "@dlee"],
        groups=["hallett", "imaging"],
        member_subset={
            "hallett": ["@mhallet"],
            "imaging": ["@dlee"],
        },
    )
    assert collab.groups == ["hallett", "imaging"]


# ---------------------------------------------------------------------------
# Phase D: collaborations (multi-PI, multi-group)
# ---------------------------------------------------------------------------


def _seed_two_labs_for_collab(isolated_world, tmp_path):
    """Set up two registered labs (hallett + ortega) so collaboration
    tests have something realistic to wire across."""
    _seed_registrar(isolated_world)
    lab_a = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("allie", "postdoc"), ("bob", "student")],
    )
    lab_b = _make_lab_mgmt(
        tmp_path, lab_id="ortega", pi="jortega",
        members=[("jortega", "pi"), ("cassie", "postdoc")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_a)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_b)


def test_create_collaboration_scaffolds_and_registers(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    entry = registrar.create_collaboration(
        name="dcis_imaging",
        pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={
            "hallett": ["@mhallet", "@allie"],
            "ortega":  ["@jortega"],
        },
    )
    assert entry.name == "dcis_imaging"
    assert entry.pis == ["@mhallet", "@jortega"]
    assert entry.oracle_vault == "wigamig_collab_dcis_imaging"
    collab_md = registrar.lab_info_root() / "collaborations" / "dcis_imaging" / "collaboration.md"
    assert collab_md.is_file()
    # projects/ and oracle/ scaffolded
    assert (registrar.lab_info_root() / "collaborations" / "dcis_imaging" / "projects").is_dir()
    assert (registrar.lab_info_root() / "collaborations" / "dcis_imaging" / "oracle").is_dir()


def test_create_collaboration_refuses_fewer_than_two_groups(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="at least 2 groups"):
        registrar.create_collaboration(
            name="dcis_solo",
            pis=["@mhallet", "@jortega"],
            groups=["hallett"],
            member_subset={"hallett": ["@mhallet"]},
        )


def test_create_collaboration_refuses_fewer_than_two_pis(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="at least 2 PIs"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet"],
            groups=["hallett", "ortega"],
            member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
        )


def test_create_collaboration_refuses_unknown_group(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="unknown group"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet", "@jortega"],
            groups=["hallett", "ghostlab"],
            member_subset={"hallett": ["@mhallet"], "ghostlab": []},
        )


def test_create_collaboration_refuses_archived_group(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.archive_lab("ortega")
    with pytest.raises(registrar.InvalidCollaboration, match="archived"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet", "@jortega"],
            groups=["hallett", "ortega"],
            member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
        )


def test_create_collaboration_requires_each_groups_pi(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="must be listed"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet", "@allie"],  # @jortega missing
            groups=["hallett", "ortega"],
            member_subset={"hallett": ["@mhallet", "@allie"], "ortega": ["@allie"]},
        )


def test_create_collaboration_subset_must_match_real_members(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="not a member"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet", "@jortega"],
            groups=["hallett", "ortega"],
            member_subset={
                "hallett": ["@mhallet"],
                "ortega":  ["@jortega", "@ghost_member"],  # not in ortega
            },
        )


def test_create_collaboration_subset_must_include_pis(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    with pytest.raises(registrar.InvalidCollaboration, match="must include"):
        registrar.create_collaboration(
            name="dcis_imaging",
            pis=["@mhallet", "@jortega"],
            groups=["hallett", "ortega"],
            member_subset={
                "hallett": ["@mhallet"],
                "ortega":  ["@cassie"],  # missing @jortega
            },
        )


def test_create_collaboration_refuses_duplicate(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.create_collaboration(
        name="dcis_imaging", pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    )
    with pytest.raises(registrar.CollaborationAlreadyExists):
        registrar.create_collaboration(
            name="dcis_imaging", pis=["@mhallet", "@jortega"],
            groups=["hallett", "ortega"],
            member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
        )


def test_create_collaboration_commits_audit_trail(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.create_collaboration(
        name="dcis_imaging", pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    )
    log = subprocess.run(
        ["git", "-C", str(registrar.lab_info_root()), "log", "--oneline"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "create collaboration dcis_imaging" in log


def test_archive_unarchive_collaboration(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.create_collaboration(
        name="dcis_imaging", pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    )
    archived = registrar.archive_collaboration("dcis_imaging")
    assert archived.status == "archived"
    unarchived = registrar.unarchive_collaboration("dcis_imaging")
    assert unarchived.status == "active"


def test_unarchive_collaboration_revalidates_invariants(isolated, tmp_path):
    """If a contributing group was archived since the collab was created,
    unarchiving the collab must fail (the groups must be active)."""
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.create_collaboration(
        name="dcis_imaging", pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    )
    registrar.archive_collaboration("dcis_imaging")
    registrar.archive_lab("ortega")
    with pytest.raises(registrar.InvalidCollaboration, match="archived"):
        registrar.unarchive_collaboration("dcis_imaging")


def test_update_collaboration_partial_edit(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    registrar.create_collaboration(
        name="dcis_imaging", pis=["@mhallet", "@jortega"],
        groups=["hallett", "ortega"],
        member_subset={"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    )
    # Add @cassie to ortega's subset; nothing else changes.
    updated = registrar.update_collaboration(
        "dcis_imaging",
        member_subset={
            "hallett": ["@mhallet"],
            "ortega":  ["@jortega", "@cassie"],
        },
    )
    assert "@cassie" in updated.member_subset["ortega"]
    assert updated.pis == ["@mhallet", "@jortega"]  # untouched


# Phase D endpoints
# -----------------


def _seed_collab_world(isolated, tmp_path):
    _seed_two_labs_for_collab(isolated, tmp_path)
    return TestClient(create_app())


def test_endpoint_create_collaboration_403_when_not_registrar(isolated, tmp_path):
    """No registrar sentinel → endpoint refuses."""
    # Don't call _seed_registrar; that's the missing piece.
    _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[("mhallet","pi")])
    client = TestClient(create_app())
    res = client.post("/api/registrar/collaboration", json={
        "name": "x", "pis": ["@a", "@b"], "groups": ["g1", "g2"], "member_subset": {},
    })
    assert res.status_code == 403


def test_endpoint_create_collaboration_400_on_invariant_violation(isolated, tmp_path):
    client = _seed_collab_world(isolated, tmp_path)
    res = client.post("/api/registrar/collaboration", json={
        "name": "dcis_imaging",
        "pis": ["@mhallet"],  # only 1 PI → fails
        "groups": ["hallett", "ortega"],
        "member_subset": {"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    })
    assert res.status_code == 400
    assert "PI" in res.text


def test_endpoint_create_collaboration_409_on_duplicate(isolated, tmp_path):
    client = _seed_collab_world(isolated, tmp_path)
    payload = {
        "name": "dcis_imaging",
        "pis": ["@mhallet", "@jortega"],
        "groups": ["hallett", "ortega"],
        "member_subset": {"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    }
    assert client.post("/api/registrar/collaboration", json=payload).status_code == 200
    assert client.post("/api/registrar/collaboration", json=payload).status_code == 409


def test_endpoint_create_archive_round_trip(isolated, tmp_path):
    client = _seed_collab_world(isolated, tmp_path)
    client.post("/api/registrar/collaboration", json={
        "name": "dcis_imaging",
        "pis": ["@mhallet", "@jortega"],
        "groups": ["hallett", "ortega"],
        "member_subset": {"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    })
    r = client.post("/api/registrar/collaboration/dcis_imaging/archive")
    assert r.status_code == 200
    assert r.json()["collaboration"]["status"] == "archived"
    r2 = client.post("/api/registrar/collaboration/dcis_imaging/unarchive")
    assert r2.status_code == 200
    assert r2.json()["collaboration"]["status"] == "active"


def test_endpoint_edit_collaboration_partial(isolated, tmp_path):
    client = _seed_collab_world(isolated, tmp_path)
    client.post("/api/registrar/collaboration", json={
        "name": "dcis_imaging",
        "pis": ["@mhallet", "@jortega"],
        "groups": ["hallett", "ortega"],
        "member_subset": {"hallett": ["@mhallet"], "ortega": ["@jortega"]},
        "oracle_vault": "wigamig_collab_dcis",
    })
    # Change just the oracle vault.
    r = client.post("/api/registrar/collaboration/dcis_imaging/edit", json={
        "oracle_vault": "wigamig_collab_dcis-renamed",
    })
    assert r.status_code == 200
    body = r.json()["collaboration"]
    assert body["oracle_vault"] == "wigamig_collab_dcis-renamed"
    assert body["pis"] == ["@mhallet", "@jortega"]  # untouched
    assert body["groups"] == ["hallett", "ortega"]  # untouched


def test_dashboard_payload_surfaces_collaboration(isolated, tmp_path):
    """The /api/registrar/dashboard payload includes created collabs."""
    client = _seed_collab_world(isolated, tmp_path)
    client.post("/api/registrar/collaboration", json={
        "name": "dcis_imaging",
        "pis": ["@mhallet", "@jortega"],
        "groups": ["hallett", "ortega"],
        "member_subset": {"hallett": ["@mhallet"], "ortega": ["@jortega"]},
    })
    body = client.get("/api/registrar/dashboard").json()
    names = [c["name"] for c in body["collaborations"]]
    assert "dcis_imaging" in names
    assert body["stats"]["total_collaborations"] == 1


def test_registrar_cert_specs_use_same_fields_as_pi_dashboard(isolated, tmp_path):
    """Naming parity guard: the registrar surfaces ``code``, ``short``,
    ``name``, and ``cadence_years`` — the exact fields the PI's
    ``TrainingCompliancePanel`` reads. A future contract drift here
    would split the two dashboards apart, which is what this test
    exists to catch."""
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi", ["TCPS_2:2030-12-31"])],
        required_codes=[("TCPS_2", "TCPS 2", 3, "all")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    resp = rs.build_registrar_response("mhallet", today=_dt.date(2026, 5, 12))
    spec = resp.certs.cert_specs[0]
    assert spec.code == "TCPS_2"
    assert spec.short == "tcps_2"      # <- this is what the JSX renders as the column header
    assert spec.name == "TCPS 2"       # <- this is what shows up in the tooltip
    assert spec.cadence_years == 3
