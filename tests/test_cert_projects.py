"""
Tests for core/cert_projects.py — the lab-scoped cert-project registry
(idempotent upsert, member de-dup, status flips, member lens).
"""

from __future__ import annotations

import pytest

from murmurent.core import cert_projects as CP


@pytest.fixture(autouse=True)
def _lab_mgmt(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab_mgmt"))


def test_upsert_creates_then_adds_members():
    CP.upsert("rna_atlas", lab="lab_mh", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"}, today="2026-07-09")
    CP.upsert("rna_atlas", lab="lab_mh", member="bob",
              cert={"fingerprint": "fb", "card_id": "cB"}, today="2026-07-10")
    p = CP.get("rna_atlas")
    assert p.lab == "lab_mh" and p.status == "active" and p.created == "2026-07-09"
    assert p.members == ("@allie", "@bob")           # bob normalized to @bob
    assert {c["handle"] for c in p.certs} == {"@allie", "@bob"}


def test_upsert_is_idempotent_and_replaces_cert():
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "old", "card_id": "c1"})
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "new", "card_id": "c2"})   # re-issue
    p = CP.get("p")
    assert p.members == ("@allie",)                  # not duplicated
    assert len(p.certs) == 1 and p.certs[0]["fingerprint"] == "new"


def test_set_status_and_member_lens():
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "f", "card_id": "c"})
    assert [x.name for x in CP.projects_for_member("allie")] == ["p"]
    CP.set_status("p", "archived")
    assert CP.get("p").status == "archived"
    assert CP.projects_for_member("allie") == []     # archived drops out of the lens


def test_set_status_missing_is_noop():
    assert CP.set_status("ghost", "archived") is None


def test_iter_projects_skips_and_sorts():
    CP.upsert("beta", lab="lab_mh")
    CP.upsert("alpha", lab="lab_mh")
    assert [p.name for p in CP.iter_projects()] == ["alpha", "beta"]


def test_enrichment_fields_round_trip():
    CP.upsert("p", lab="lab_mh", lead="@the_pi", sensitivity="Clinical",
              choreography="hub", code_repo="~/repos/p", github_repo="org/p")
    p = CP.get("p")
    assert p.lead == "@the_pi" and p.sensitivity == "clinical"   # normalized
    assert p.choreography == "hub" and p.code_repo == "~/repos/p"
    assert p.github_repo == "org/p"


def test_membership_upsert_preserves_metadata():
    CP.upsert("p", lab="lab_mh", lead="@the_pi", sensitivity="restricted",
              code_repo="~/repos/p")
    # a later membership-only upsert (as issue_project_card does) must NOT wipe
    # the previously-set project metadata
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "f", "card_id": "c"})
    p = CP.get("p")
    assert p.sensitivity == "restricted" and p.lead == "@the_pi"
    assert p.code_repo == "~/repos/p" and "@allie" in p.members


def test_set_status_preserves_metadata():
    CP.upsert("p", lab="lab_mh", sensitivity="clinical", code_repo="~/repos/p")
    CP.set_status("p", "archived")
    p = CP.get("p")
    assert p.status == "archived" and p.sensitivity == "clinical"
    assert p.code_repo == "~/repos/p"


def test_slack_channel_for():
    assert CP.slack_channel_for("ghost") == ""            # unregistered → ""
    CP.upsert("p", lab="lab_mh")
    assert CP.slack_channel_for("p") == ""                # registered, no channel
    CP.upsert("p", lab="lab_mh", slack_channel_id="C42")
    assert CP.slack_channel_for("p") == "C42"


def test_project_name_for_cwd(monkeypatch, tmp_path):
    from murmurent.core import repo as R
    # not in a project repo → None
    monkeypatch.chdir(tmp_path)
    assert CP.project_name_for_cwd() is None
    # a repo with CHARTER carrying a project name → that name
    proj = tmp_path / "myrepo"
    (proj).mkdir()
    (proj / R.CHARTER_FILENAME).write_text(
        "---\nproject: rna_atlas\n---\n", encoding="utf-8")
    assert CP.project_name_for_cwd(proj) == "rna_atlas"
    # CHARTER without a project field → falls back to the dir name
    p2 = tmp_path / "barerepo"
    p2.mkdir()
    (p2 / R.CHARTER_FILENAME).write_text("---\nlead: '@x'\n---\n", encoding="utf-8")
    assert CP.project_name_for_cwd(p2) == "barerepo"


def test_write_rejects_dangling_symlink(monkeypatch, tmp_path):
    """A dangling lab-mgmt symlink fails cleanly (CertProjectError), not with an
    opaque FileExistsError deep in mkdir."""
    link = tmp_path / "lab_mgmt_link"
    link.symlink_to(tmp_path / "does_not_exist")
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(link))
    with pytest.raises(CP.CertProjectError, match="dangling symlink"):
        CP.upsert("p", lab="lab_mh")


def test_render_retires_top_level_code_repo_but_reads_back(tmp_path):
    CP.upsert("p", lab="lab_mh", code_repo="/r/p", host="local")
    text = CP.project_path("p").read_text()
    # stage 6: top-level code_repo/host/remote_path are no longer written;
    # `repos:` is the on-disk representation (host lives nested inside it).
    assert "\ncode_repo:" not in text
    assert "\nhost:" not in text and "\nremote_path:" not in text
    assert "repos:" in text
    assert CP.get("p").code_repo == "/r/p"        # still derived on read


def test_old_format_file_with_code_repo_still_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lm"))
    d = tmp_path / "lm" / "cert_projects"
    d.mkdir(parents=True)
    (d / "old.md").write_text(
        "---\nproject: old\nlab: lab_mh\nstatus: active\n"
        "code_repo: /r/old\nhost: local\n---\n\n# old\n", encoding="utf-8")
    p = CP.get("old")
    assert p.code_repo == "/r/old"
    assert len(p.repos) == 1 and p.repos[0].role == "code" and p.repos[0].path == "/r/old"


def test_legacy_code_repo_reads_as_a_single_code_repo():
    # a pre-multi-repo project (only code_repo) reads with a synthesized repos list
    CP.upsert("legacy", lab="lab_mh", code_repo="/Users/x/repos/legacy", host="local")
    p = CP.get("legacy")
    assert len(p.repos) == 1
    r = p.repos[0]
    assert r.role == "code" and r.path == "/Users/x/repos/legacy" and r.name == "legacy"
    assert p.code_repo == "/Users/x/repos/legacy"          # mirror preserved


def test_multi_repo_project_round_trips():
    CP.upsert("rna_atlas", lab="lab_mh", code_repo="/Users/x/repos/rna_atlas")
    CP.add_repo("rna_atlas", role="manuscript", repo_name="rna_atlas_manuscript",
                path="/Users/x/repos/rna_atlas_manuscript", overleaf=True)
    p = CP.get("rna_atlas")
    roles = {r.role for r in p.repos}
    assert roles == {"code", "manuscript"}
    ms = next(r for r in p.repos if r.role == "manuscript")
    assert ms.name == "rna_atlas_manuscript" and ms.overleaf is True
    # code_repo mirror still points at the code repo
    assert p.code_repo == "/Users/x/repos/rna_atlas"


def test_add_repo_replaces_by_name_and_needs_project():
    CP.upsert("p", lab="lab_mh", code_repo="/r/p")
    CP.add_repo("p", role="data", repo_name="p_data", path="/r/p_data_v1")
    CP.add_repo("p", role="data", repo_name="p_data", path="/r/p_data_v2")  # replace
    data = [r for r in CP.get("p").repos if r.name == "p_data"]
    assert len(data) == 1 and data[0].path == "/r/p_data_v2"
    with pytest.raises(CP.CertProjectError, match="no cert-project"):
        CP.add_repo("ghost", path="/r/x")


def test_remove_repo_detaches_and_repromotes_primary():
    CP.upsert("p", lab="lab_mh", code_repo="/r/p")           # primary code repo "p"
    CP.add_repo("p", role="manuscript", repo_name="p_ms", path="/r/p_ms", overleaf=True)
    CP.add_repo("p", role="data", repo_name="p_data", path="/r/p_data")

    # Remove a non-primary repo.
    CP.remove_repo("p", "p_data")
    assert {r.name for r in CP.get("p").repos} == {"p", "p_ms"}

    # Removing the primary code repo promotes the next repo; no resurrection.
    CP.remove_repo("p", "p")
    left = CP.get("p")
    assert {r.name for r in left.repos} == {"p_ms"}
    assert left.code_repo == "/r/p_ms"          # mirror re-pointed, not stale "/r/p"

    # Errors: unknown repo, unknown project.
    with pytest.raises(CP.CertProjectError, match="no repo named"):
        CP.remove_repo("p", "nope")
    with pytest.raises(CP.CertProjectError, match="no cert-project"):
        CP.remove_repo("ghost", "x")


def test_remote_primary_repo_mirrors_host():
    CP.upsert("rp", lab="lab_mh", code_repo="~/repos/rp", host="lab-server",
              remote_path="/srv/rp")
    p = CP.get("rp")
    assert p.repos[0].host == "lab-server" and p.repos[0].remote_path == "/srv/rp"
    assert p.host == "lab-server" and p.remote_path == "/srv/rp"   # mirror


def test_clone_location_round_trips():
    CP.upsert("rp", lab="lab_mh", code_repo="~/repos/rp",
              host="lab-server", remote_path="/srv/rp")
    p = CP.get("rp")
    assert p.host == "lab-server" and p.remote_path == "/srv/rp"
    # membership upsert preserves clone location
    CP.upsert("rp", lab="lab_mh", member="@allie")
    p2 = CP.get("rp")
    assert p2.host == "lab-server" and p2.remote_path == "/srv/rp"


def test_backfill_from_charter(monkeypatch, tmp_path):
    """Existing CHARTER code-projects are mirrored into the cert-project registry
    with their name/lab/sensitivity/lead/members and a code_repo link."""
    from murmurent.core import charter as _charter
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    repo = tmp_path / "repos" / "dcis_sc"
    repo.mkdir(parents=True)
    (repo / "CHARTER.md").write_text(
        "---\nproject: dcis_sc\nlab: hallett\nsensitivity: clinical\n"
        "lead: '@allie'\nchoreography: clinical_cohort\n"
        "reb_number: WREM-1\nreb_expires: '2027-01-01'\ndata_residency: ca\n"
        "members: ['@allie', '@bob']\n---\n\n# dcis_sc\n", encoding="utf-8")

    touched = CP.backfill_from_charter()
    assert "dcis_sc" in touched
    p = CP.get("dcis_sc")
    assert p.lab == "hallett" and p.sensitivity == "clinical" and p.lead == "@allie"
    assert p.choreography == "clinical_cohort"
    assert str(repo) in p.code_repo
    assert set(p.members) == {"@allie", "@bob"}
    # idempotent: a second run doesn't duplicate members
    CP.backfill_from_charter()
    assert list(CP.get("dcis_sc").members).count("@allie") == 1


def test_enrichment_fields_stage1_round_trip():
    """Stage 1: the fields migrated off CHARTER survive a write→read cycle."""
    CP.upsert("p", lab="lab_mh", sensitivity="clinical",
              reb_number="WREM-42", reb_expires="2027-01-01", data_residency="ca",
              repo_kind="local", local_repo_root="/srv/repos",
              remote_url="/srv/repos/p.git", slack_channel_name="proj-p",
              github_repo="org/p", decommissioned_at="2026-07-01T00:00:00Z",
              decommissioned_by="@mhallet")
    p = CP.get("p")
    assert p.reb_number == "WREM-42" and p.reb_expires == "2027-01-01"
    assert p.data_residency == "ca"
    assert p.repo_kind == "local" and p.local_repo_root == "/srv/repos"
    assert p.remote_url == "/srv/repos/p.git"
    assert p.slack_channel_name == "proj-p" and p.github_repo == "org/p"
    assert p.decommissioned_at == "2026-07-01T00:00:00Z"
    assert p.decommissioned_by == "@mhallet"
    # to_dict carries them all
    d = p.to_dict()
    assert d["reb_number"] == "WREM-42" and d["repo_kind"] == "local"


def test_membership_upsert_preserves_stage1_fields():
    CP.upsert("p", lab="lab_mh", sensitivity="clinical", reb_number="R1",
              reb_expires="2027-01-01", data_residency="ca", repo_kind="local")
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "f", "card_id": "c"})
    p = CP.get("p")
    assert p.reb_number == "R1" and p.data_residency == "ca"
    assert p.repo_kind == "local" and "@allie" in p.members


def test_validate_project_clinical_requires_reb():
    CP.upsert("p", lab="lab_mh", sensitivity="clinical")
    with pytest.raises(CP.CertProjectValidationError, match="reb_number"):
        CP.validate_project(CP.get("p"))
    CP.upsert("p", lab="lab_mh", sensitivity="clinical", reb_number="R1",
              reb_expires="2027-01-01", data_residency="ca")
    CP.validate_project(CP.get("p"))     # now valid — no raise


def test_validate_project_rejects_bad_sensitivity_and_choreography():
    CP.upsert("p", lab="lab_mh", sensitivity="standard", choreography="not_a_real_one")
    with pytest.raises(CP.CertProjectValidationError, match="choreography"):
        CP.validate_project(CP.get("p"))


def test_backfill_copies_all_charter_fields(monkeypatch, tmp_path):
    """Migration round-trip: every field on a CHARTER survives into the cert record."""
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    repo = tmp_path / "repos" / "dcis_sc"
    repo.mkdir(parents=True)
    (repo / "CHARTER.md").write_text(
        "---\nproject: dcis_sc\nlab: hallett\nsensitivity: clinical\n"
        "lead: '@allie'\nchoreography: clinical_cohort\n"
        "reb_number: WREM-1\nreb_expires: '2027-01-01'\ndata_residency: ca\n"
        "repo_kind: local\nlocal_repo_root: /srv/repos\n"
        "remote_url: /srv/repos/dcis_sc.git\n"
        "slack_channel_id: C99\nslack_channel_name: proj-dcis\n"
        "github_repo: org/dcis_sc\n"
        "members: ['@allie', '@bob']\n---\n\n# dcis_sc\n", encoding="utf-8")

    touched = CP.backfill_from_charter()
    assert "dcis_sc" in touched
    p = CP.get("dcis_sc")
    assert p.sensitivity == "clinical" and p.reb_number == "WREM-1"
    assert p.reb_expires == "2027-01-01" and p.data_residency == "ca"
    assert p.repo_kind == "local" and p.local_repo_root == "/srv/repos"
    assert p.remote_url == "/srv/repos/dcis_sc.git"
    assert p.slack_channel_id == "C99" and p.slack_channel_name == "proj-dcis"
    assert p.github_repo == "org/dcis_sc"
    assert p.choreography == "clinical_cohort"
    assert set(p.members) == {"@allie", "@bob"}
    CP.validate_project(p)               # a fully-migrated clinical project validates


def test_migrate_charters_backfills_then_deletes(monkeypatch, tmp_path):
    """migrate_charters copies every field, verifies it, then removes the CHARTER."""
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    repo = tmp_path / "repos" / "proj"
    repo.mkdir(parents=True)
    charter = repo / "CHARTER.md"
    charter.write_text(
        "---\nproject: proj\nlab: lab_mh\nsensitivity: restricted\n"
        "lead: '@allie'\nmembers: ['@allie', '@bob']\nrepo_kind: local\n"
        "---\n\n# proj\n", encoding="utf-8")

    out = CP.migrate_charters()
    assert out["migrated"] == ["proj"] and out["deleted"] == ["proj"]
    assert not charter.exists()                       # CHARTER removed after verify
    p = CP.get("proj")
    assert p.sensitivity == "restricted" and p.repo_kind == "local"
    assert set(p.members) == {"@allie", "@bob"}


def test_migrate_charters_keep_leaves_files(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_PROJECTS_ROOT", str(tmp_path / "repos"))
    repo = tmp_path / "repos" / "proj"
    repo.mkdir(parents=True)
    charter = repo / "CHARTER.md"
    charter.write_text(
        "---\nproject: proj\nlab: lab_mh\nsensitivity: standard\n"
        "lead: '@allie'\nmembers: ['@allie']\n---\n\n# proj\n", encoding="utf-8")
    out = CP.migrate_charters(delete=False)
    assert out["migrated"] == ["proj"] and out["deleted"] == []
    assert charter.exists()                           # left in place
    assert CP.get("proj") is not None


def test_remove_member_drops_member_and_cert():
    CP.upsert("p", lab="lab_mh", lead="@allie", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"})
    CP.upsert("p", lab="lab_mh", member="@bob",
              cert={"fingerprint": "fb", "card_id": "cB"})
    out = CP.remove_member("p", "bob")
    assert out.members == ("@allie",)
    assert {c["handle"] for c in out.certs} == {"@allie"}
    # metadata untouched
    assert out.lead == "@allie" and out.status == "active"


def test_remove_member_refuses_the_lead():
    CP.upsert("p", lab="lab_mh", lead="@allie", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"})
    with pytest.raises(CP.CertProjectError, match="lead"):
        CP.remove_member("p", "@allie")


def test_remove_member_requires_project():
    with pytest.raises(CP.CertProjectError, match="no cert-project"):
        CP.remove_member("ghost", "@allie")


def test_slack_workspace_round_trips():
    CP.upsert("p", lab="lab_mh", slack_workspace="shared_ws")
    assert CP.get("p").slack_workspace == "shared_ws"
    # metadata-free membership upsert keeps it
    CP.upsert("p", lab="lab_mh", member="@allie",
              cert={"fingerprint": "fa", "card_id": "cA"})
    p = CP.get("p")
    assert p.slack_workspace == "shared_ws"
    assert p.to_dict()["slack_workspace"] == "shared_ws"
    # empty default when never set
    CP.upsert("q", lab="lab_mh")
    assert CP.get("q").slack_workspace == ""


def test_upsert_commits_to_lab_mgmt_git(monkeypatch, tmp_path):
    """A cert-project mutation must land in git — the dashboard reads
    cert_projects/ from each member's OWN lab-mgmt clone, so an uncommitted
    record is invisible to the lab. (Regression: cert_projects never persisted.)"""
    import subprocess
    root = tmp_path / "lab_mgmt"
    (root / "members").mkdir(parents=True)
    for a in (["init", "-b", "main"], ["config", "user.email", "t@t"],
              ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(root))

    CP.upsert("proj_x", lab="mh", code_repo="/r/proj_x")

    tracked = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True).stdout
    assert "cert_projects/proj_x.md" in tracked      # committed, not just written
