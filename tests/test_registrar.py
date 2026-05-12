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

from wigamig.core import registrar
from wigamig.core.registrar import (
    CollaborationEntry,
    CoreEntry,
    LabEntry,
    Registry,
)
from wigamig.dashboard import registrar_snapshot as rs
from wigamig.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect every registrar-touched path into tmp_path."""
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(
        registrar, "REGISTRAR_SENTINEL", tmp_path / "registrar_sentinel"
    )
    # Also block other resolvers so the test doesn't leak the real user.
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
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
    assert registrar.is_registrar("the_pi") is False
    assert registrar.registrar_handle() is None


def test_is_registrar_true_for_declared_handle(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")
    assert registrar.registrar_handle() == "the_pi"
    assert registrar.is_registrar("the_pi") is True
    assert registrar.is_registrar("@the_pi") is True
    assert registrar.is_registrar("MHALLET") is True
    assert registrar.is_registrar("bob") is False


def test_is_registrar_ignores_blank_lines(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("\n\n  the_pi  \n# comment\n", encoding="utf-8")
    assert registrar.registrar_handle() == "the_pi"


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
            LabEntry(name="hallett", pi="@the_pi",
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
                pis=["@the_pi", "@cassie"],
                groups=["hallett", "imaging"],
                member_subset={"hallett": ["@allie"], "imaging": ["@bob"]},
            ),
        ],
    )
    registrar.write_registry(original)
    reread = registrar.read_registry()

    assert [l.name for l in reread.labs] == ["hallett"]
    assert reread.labs[0].pi == "@the_pi"
    assert reread.labs[0].github_org == "hallettmiket"
    assert [c.name for c in reread.cores] == ["imaging"]
    assert reread.collaborations[0].pis == ["@the_pi", "@cassie"]
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
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi"), ("bob", "postdoc")],
    )
    reg = registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    assert [l.name for l in reg.labs] == ["hallett"]
    assert reg.labs[0].pi == "@the_pi"
    assert reg.labs[0].lab_mgmt_path == str(lab_dir)


def test_bootstrap_is_idempotent(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    reg = registrar.read_registry()
    assert len(reg.labs) == 1  # not duplicated


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def test_snapshot_renders_lab_with_members(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi"), ("bob", "postdoc"), ("cassie", "student")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    resp = rs.build_registrar_response("the_pi")
    assert resp.registrar_handle == "@the_pi"
    assert len(resp.labs) == 1
    lab = resp.labs[0]
    assert lab.name == "hallett"
    assert lab.display_name == "Hallett Lab"
    assert lab.member_count == 3
    assert {m.handle for m in lab.members} == {"@the_pi", "@bob", "@cassie"}
    assert lab.unresolved is False
    assert resp.stats.total_labs == 1
    assert resp.stats.total_members == 3


def test_snapshot_dedupes_members_across_labs(isolated, tmp_path):
    lab_a = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi"), ("bob", "postdoc")],
    )
    lab_b = _make_lab_mgmt(
        tmp_path, lab_id="other", pi="otherpi",
        members=[("otherpi", "pi"), ("bob", "postdoc")],  # bob is in both
    )
    registrar.write_registry(Registry(labs=[
        LabEntry(name="hallett", pi="@the_pi", lab_mgmt_path=str(lab_a)),
        LabEntry(name="other", pi="@otherpi", lab_mgmt_path=str(lab_b)),
    ]))
    resp = rs.build_registrar_response("the_pi")
    # the_pi, bob, otherpi — deduped → 3 unique members
    assert resp.stats.total_members == 3
    assert resp.stats.total_labs == 2


def test_snapshot_flags_unresolved_pointer(isolated):
    registrar.write_registry(Registry(labs=[
        LabEntry(name="ghost", pi="@nobody", lab_mgmt_path="/does/not/exist"),
    ]))
    resp = rs.build_registrar_response("the_pi")
    assert len(resp.labs) == 1
    assert resp.labs[0].unresolved is True
    assert "does not exist" in (resp.labs[0].unresolved_reason or "")


def test_snapshot_never_reads_notebooks_or_oracles(isolated, tmp_path, monkeypatch):
    """Hard contract: the registrar dashboard must NOT call into
    notebook / oracle / sea / inventory snapshot helpers."""
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    # If we ever start importing these in registrar_snapshot, the test
    # will trip — guards against accidental leakage of lab-private data
    # into the centre-level dashboard.
    blocked = []
    def _sentinel(*a, **k):
        blocked.append("called")
        raise AssertionError("registrar must not access lab-private data")

    from wigamig.dashboard import snapshot as lab_snap
    for name in ("_notebook", "_personal_oracle", "_oracle_recent",
                 "_inventory", "_seas"):
        monkeypatch.setattr(lab_snap, name, _sentinel, raising=False)

    # Should succeed without ever calling those.
    rs.build_registrar_response("the_pi")
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
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="the_pi", members=[("the_pi", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["registrar_handle"] == "@the_pi"
    assert len(payload["labs"]) == 1
    assert payload["labs"][0]["name"] == "hallett"


def test_endpoint_user_override_query_param(isolated):
    """``?user=bob`` against a sentinel of ``the_pi`` must still 403."""
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard?user=bob")
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Phase B: create_lab
# ---------------------------------------------------------------------------


def _seed_registrar(isolated):
    """Declare the_pi as registrar; assume isolated fixture is active."""
    registrar.REGISTRAR_SENTINEL.write_text("the_pi\n", encoding="utf-8")


def test_create_lab_scaffolds_files_and_registry(isolated):
    _seed_registrar(isolated)
    entry = registrar.create_lab(
        name="ortega", display_name="Ortega Lab",
        pi_handle="jortega", pi_full_name="Jane Ortega",
        slack_workspace="T01ABC", github_org="ortegalab",
        oracle_vault="wigamig-vault-ortega",
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
    from wigamig.core.frontmatter import parse_file
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
    from wigamig.core.frontmatter import parse_file
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

    from wigamig.core.frontmatter import parse_file
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
    from wigamig.core.frontmatter import parse_file
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
    from wigamig.core.frontmatter import parse_file
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
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[
            ("the_pi", "pi", ["TCPS_2:2030-12-31"]),
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

    resp = rs.build_registrar_response("the_pi", today=_dt.date(2026, 5, 12))
    panel = resp.certs
    handles_by_group = {(r.group, r.handle) for r in panel.rows}
    assert ("hallett", "@the_pi") in handles_by_group
    assert ("hallett", "@bob") in handles_by_group
    assert ("ortega", "@jortega") in handles_by_group
    assert "TCPS_2" in [s.code for s in panel.cert_specs]


def test_cert_panel_aggregate_counts_issues(isolated, tmp_path):
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[
            ("the_pi", "pi", ["TCPS_2:2030-12-31"]),  # ok
            ("bob",     "postdoc", ["TCPS_2:2024-01-01"]),  # expired (today=2026-05)
            ("cassie",  "student", []),  # missing TCPS_2
        ],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    resp = rs.build_registrar_response("the_pi", today=_dt.date(2026, 5, 12))
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
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi", ["TCPS_2:2030-12-31"])],
        required_codes=[("TCPS_2", "TCPS 2", 3, "all")],
    )
    lab_b = _seed_lab_with_compliance(
        tmp_path, lab_id="ortega", pi="jortega",
        members=[("jortega", "pi", ["WHM103:2030-12-31"])],
        required_codes=[("WHM103", "WHMIS", None, "all")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_a)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_b)

    resp = rs.build_registrar_response("the_pi", today=_dt.date(2026, 5, 12))
    # Both cert codes surface in the column header, each with its
    # own short name + cadence for the JSX tooltip.
    seen_codes = [s.code for s in resp.certs.cert_specs]
    assert "TCPS_2" in seen_codes
    assert "WHM103" in seen_codes
    # the_pi's TCPS_2 status is ok; he has no row in ortega (different lab).
    the_pi_row = next(r for r in resp.certs.rows if r.handle == "@the_pi")
    assert the_pi_row.group == "hallett"
    assert any(c.code == "TCPS_2" and c.status == "ok" for c in the_pi_row.certs)


def test_cert_panel_skips_archived_labs(isolated, tmp_path):
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi", ["TCPS_2:2030-12-31"])],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    registrar.archive_lab("hallett")
    resp = rs.build_registrar_response("the_pi", today=_dt.date(2026, 5, 12))
    assert resp.certs.rows == []
    assert resp.certs.aggregate.members_total == 0


def test_cert_panel_endpoint_returns_panel(isolated, tmp_path):
    """The HTTP endpoint surfaces the cert panel in the JSON payload."""
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi", ["TCPS_2:2030-12-31"])],
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
    from wigamig.core import compliance
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
    from wigamig.core import compliance
    cfg = compliance.load_config_at(tmp_path / "no_such_file.md")
    # Falls back to the default set; should not raise.
    assert isinstance(cfg.required, list)


def test_registrar_cert_specs_use_same_fields_as_pi_dashboard(isolated, tmp_path):
    """Naming parity guard: the registrar surfaces ``code``, ``short``,
    ``name``, and ``cadence_years`` — the exact fields the PI's
    ``TrainingCompliancePanel`` reads. A future contract drift here
    would split the two dashboards apart, which is what this test
    exists to catch."""
    _seed_registrar(isolated)
    lab_dir = _seed_lab_with_compliance(
        tmp_path, lab_id="hallett", pi="the_pi",
        members=[("the_pi", "pi", ["TCPS_2:2030-12-31"])],
        required_codes=[("TCPS_2", "TCPS 2", 3, "all")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    resp = rs.build_registrar_response("the_pi", today=_dt.date(2026, 5, 12))
    spec = resp.certs.cert_specs[0]
    assert spec.code == "TCPS_2"
    assert spec.short == "tcps_2"      # <- this is what the JSX renders as the column header
    assert spec.name == "TCPS 2"       # <- this is what shows up in the tooltip
    assert spec.cadence_years == 3
