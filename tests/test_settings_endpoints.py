"""Tests for the three settings endpoints + machine.yaml round-trip.

Covers:
  - POST /api/machine/settings: writes ~/.murmurent/machine.yaml, round-trips
  - POST /api/member/settings: rewrites contact/location, preserves body,
    preserves unknown fields (certifications, obsidian, custom keys)
  - POST /api/lab/settings: PI-only, rewrites lab.md frontmatter,
    preserves body + unknown keys
  - Snapshot exposes machine_settings + falls back to legacy obsidian block
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core.frontmatter import parse_file
from murmurent.dashboard import machine_settings as ms_mod
from murmurent.dashboard import snapshot as snap_mod
from murmurent.dashboard.contract import MachineSettings
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Tmp filesystem with lab-mgmt + redirected machine.yaml."""
    lab_mgmt = tmp_path / "lab-mgmt"
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\n"
        "lab: hallett\n"
        "name: Hallett Lab\n"
        "pi: '@the_pi'\n"
        "institution: Western University\n"
        "department: Schulich\n"
        "website: https://example.org\n"
        "admins: []\n"
        "created: 2026-05-08\n"
        "---\n\n# Hallett Lab\n\nBody content that must be preserved.\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "the_pi.md").write_text(
        "---\n"
        "handle: '@the_pi'\n"
        "full_name: 'Mike Hallett'\n"
        "role: pi\n"
        "status: active\n"
        "lab: hallett\n"
        "contact:\n"
        "  email: stale@old.com\n"
        "  orcid: 0000-0000-0000-0000\n"
        "location:\n"
        "  office: OLD-100\n"
        "obsidian:\n"
        "  vault_path: /legacy/path\n"
        "  vault_name: legacy-vault\n"
        "certifications:\n"
        "  - TCPS_2:2030-12-31\n"
        "custom_key_we_should_preserve: keep_me\n"
        "created: 2026-05-07\n"
        "---\n\n# @the_pi\n\nProfile body that must survive.\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "bob.md").write_text(
        "---\n"
        "handle: '@bob'\nfull_name: 'Bob'\nrole: postdoc\nstatus: active\nlab: hallett\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("MURMURENT_USER", "the_pi")
    # Redirect machine.yaml so we don't touch the developer's real home.
    machine_yaml = tmp_path / "murmurent" / "machine.yaml"
    monkeypatch.setattr(ms_mod, "MACHINE_FILE", machine_yaml)

    return {"tmp": tmp_path, "lab_mgmt": lab_mgmt, "machine_yaml": machine_yaml}


# ---------------------------------------------------------------------------
# /api/machine/settings
# ---------------------------------------------------------------------------


def test_machine_settings_round_trip(world):
    client = TestClient(create_app())
    payload = {
        "obsidian_vault_path": "/Users/me/vault",
        # ``obsidian_vault_name`` is intentionally not sent — the server
        # derives it from the path's basename. An explicit value, if sent,
        # is ignored. See machine_settings._derive_vault_name.
        "notebook_subfolder": "notes",
        "oracle_subfolder": "memory",
    }
    res = client.post("/api/machine/settings", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    on_disk = yaml.safe_load(world["machine_yaml"].read_text())
    for k, v in payload.items():
        assert on_disk[k] == v
    # Vault name is derived: basename of the path.
    assert on_disk["obsidian_vault_name"] == "vault"


def test_machine_settings_persists_machine_name(world):
    """The "this machine" editor's friendly name round-trips through
    machine.yaml (display only — the host-registry key stays "local")."""
    client = TestClient(create_app())
    res = client.post("/api/machine/settings",
                      json={"machine_name": "my-laptop", "wigamig_base": "~/wigamig"})
    assert res.status_code == 200, res.text
    on_disk = yaml.safe_load(world["machine_yaml"].read_text())
    assert on_disk["machine_name"] == "my-laptop"
    assert ms_mod.load().machine_name == "my-laptop"


def test_machine_settings_preflight_creates_subdirs(world, tmp_path):
    """Saving wigamig_base materializes the four standard subfolders and
    reports each in the preflight ``probes`` list with green status."""
    base = tmp_path / "wigamig_root"
    payload = {
        "wigamig_base": str(base),
        "obsidian_vault_path": str(tmp_path / "vault"),
        "notebook_subfolder": "lab-notebook",
        "oracle_subfolder": "oracle",
    }
    (tmp_path / "vault").mkdir()
    res = TestClient(create_app()).post("/api/machine/settings", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall"] in ("ok", "warn")
    names = {p["name"]: p for p in body["probes"]}
    # One merged "large-file location" row (was set/not-protected/exists trio).
    assert names["large-file location"]["status"] == "ok"
    for sub in ("raw", "refined", "lab_notebooks"):
        assert names[sub]["status"] == "ok", names[sub]
        assert (base / sub).is_dir()
    # Personal-vault probe (relabelled from "obsidian vault" in issue #25).
    assert names["personal vault"]["status"] == "ok"
    # Lab-vault probe (the lab-mgmt clone) is also surfaced.
    assert "lab vault (lab-mgmt clone)" in names


def test_probe_tolerates_shell_escaped_vault_path(tmp_path):
    """A path pasted from a terminal (backslash-escaped spaces, quotes) must
    still resolve — otherwise a folder that exists reads as "does not exist"."""
    from murmurent.core import preflight as P

    real = tmp_path / "My Vault"
    real.mkdir()
    escaped = str(tmp_path) + "/My\\ Vault"
    assert P.clean_pasted_path(escaped) == str(real)
    assert P.probe_obsidian_vault(escaped).status == "ok"
    assert P.probe_obsidian_vault(f'"{real}"').status == "ok"


def test_machine_settings_obsidian_na_is_not_a_warning(world, tmp_path):
    """Entering "NA" for the Obsidian vault is an explicit "no vault here" —
    a clean green check, not a yellow warning about a forgotten field, and
    no bogus vault name is derived from it."""
    res = TestClient(create_app()).post("/api/machine/settings", json={
        "wigamig_base": str(tmp_path / "base"),
        "obsidian_vault_path": "NA",
    })
    assert res.status_code == 200, res.text
    names = {p["name"]: p for p in res.json()["probes"]}
    assert names["personal vault"]["status"] == "ok"
    assert "not applicable" in names["personal vault"]["detail"]
    on_disk = yaml.safe_load(world["machine_yaml"].read_text())
    assert on_disk["obsidian_vault_name"] is None


def test_machine_settings_rejects_protected_lab_vm_paths(world):
    """``/data/lab_vm/raw`` is a hard refuse — re-routing murmurent writes
    through it would defeat the raw_guard hook."""
    res = TestClient(create_app()).post("/api/machine/settings", json={
        "wigamig_base": "/data/lab_vm/raw",
    })
    assert res.status_code == 422
    assert "protected" in res.json()["detail"].lower()


def test_machine_settings_allows_lab_vm_parent(world, tmp_path, monkeypatch):
    """``/data/lab_vm`` itself is OK — only its raw/ + refined/ children
    are off-limits. Use a tmp_path proxy to avoid touching the real
    /data/lab_vm during the test, but the validation logic is the same.
    """
    # Use a tmp lab_vm root rather than the real one for write-safety.
    fake_lv = tmp_path / "fake_lab_vm"
    res = TestClient(create_app()).post("/api/machine/settings", json={
        "wigamig_base": str(fake_lv),
        "obsidian_vault_path": "",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall"] in ("ok", "warn")
    assert (fake_lv / "raw").is_dir()


def test_machine_settings_load_falls_back_to_legacy_obsidian(world):
    """Until the user saves once, machine settings should still surface
    the values from the member profile's old ``obsidian:`` block so
    nothing visually disappears during the migration."""
    legacy = {"vault_path": "/legacy/path", "vault_name": "legacy-vault",
              "notebook_subfolder": "lab-notebook", "oracle_subfolder": "oracle"}
    s = ms_mod.load(legacy_obsidian=legacy)
    assert s.obsidian_vault_path == "/legacy/path"
    assert s.obsidian_vault_name == "legacy-vault"


def test_machine_settings_wins_over_legacy_after_save(world):
    # The client may send an explicit obsidian_vault_name (legacy clients
    # still do), but the server always derives it from the path's basename.
    # Re-loading reflects the derived name, not the originally-sent one.
    ms_mod.write(MachineSettings(
        obsidian_vault_path="/new/path", obsidian_vault_name="new-vault",
        notebook_subfolder="nb", oracle_subfolder="or",
    ))
    legacy = {"vault_path": "/legacy/path", "vault_name": "legacy-vault"}
    s = ms_mod.load(legacy_obsidian=legacy)
    assert s.obsidian_vault_path == "/new/path"
    assert s.obsidian_vault_name == "path"  # basename of "/new/path"


# ---------------------------------------------------------------------------
# /api/member/settings
# ---------------------------------------------------------------------------


def test_member_settings_rewrites_contact_and_location(world):
    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={
        "email": "new@example.edu", "orcid": "0000-0001-1111-1111",
        "office": "MSB-360",
    })
    assert res.status_code == 200, res.text

    parsed = parse_file(world["lab_mgmt"] / "members" / "the_pi.md")
    meta = parsed.meta
    assert meta["contact"]["email"] == "new@example.edu"
    assert meta["contact"]["orcid"] == "0000-0001-1111-1111"
    assert meta["location"]["office"] == "MSB-360"


def test_member_settings_persists_handles_top_level(world):
    """official_handle + slack_handle are per-person handles that persist to the
    top level of the member frontmatter (official_handle / slack), where the
    roster model reads them — not into the contact block (GH #23)."""
    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={
        "official_handle": "@the_pit", "slack_handle": "@mike.h",
    })
    assert res.status_code == 200, res.text

    meta = parse_file(world["lab_mgmt"] / "members" / "the_pi.md").meta
    # Stored top-level, @-stripped, and NOT tucked inside contact:.
    assert meta["official_handle"] == "the_pit"
    assert meta["slack"] == "mike.h"
    assert "official_handle" not in meta.get("contact", {})
    assert "slack" not in meta.get("contact", {})


def test_member_settings_blank_handles_are_removed(world):
    """Blanking a handle drops the key rather than storing an empty string."""
    client = TestClient(create_app())
    client.post("/api/member/settings", json={
        "official_handle": "the_pit", "slack_handle": "mike.h",
    })
    client.post("/api/member/settings", json={
        "official_handle": "", "slack_handle": "",
    })
    meta = parse_file(world["lab_mgmt"] / "members" / "the_pi.md").meta
    assert "official_handle" not in meta
    assert "slack" not in meta


def test_member_settings_preserves_body_and_unknown_keys(world):
    """Certifications, obsidian, custom keys, and the body must survive."""
    client = TestClient(create_app())
    client.post("/api/member/settings", json={"email": "x@y.z"})

    parsed = parse_file(world["lab_mgmt"] / "members" / "the_pi.md")
    meta = parsed.meta
    # Untouched fields:
    assert meta["handle"] == "@the_pi"
    assert meta["role"] == "pi"
    assert meta["certifications"] == ["TCPS_2:2030-12-31"]
    assert meta["obsidian"] == {"vault_path": "/legacy/path", "vault_name": "legacy-vault"}
    assert meta["custom_key_we_should_preserve"] == "keep_me"
    # Body preserved:
    assert "Profile body that must survive." in parsed.body


def test_member_settings_partial_post_preserves_unmentioned_fields(world):
    """A POST that only contains ``email`` must not wipe orcid/office/etc.

    Regression test for the smoke-test bug where a partial curl POST
    nuked the user's other contact + location fields because the
    endpoint treated unset Pydantic fields as 'remove'.
    """
    client = TestClient(create_app())
    # First seed a rich profile.
    client.post("/api/member/settings", json={
        "email": "a@b.c", "orcid": "0000-9999-0000-0000",
        "office": "MSB-360", "city": "London",
    })
    # Now POST only email — everything else must survive.
    client.post("/api/member/settings", json={"email": "new@b.c"})

    meta = parse_file(world["lab_mgmt"] / "members" / "the_pi.md").meta
    assert meta["contact"]["email"] == "new@b.c"
    assert meta["contact"]["orcid"] == "0000-9999-0000-0000"
    assert meta["location"]["office"] == "MSB-360"
    assert meta["location"]["city"] == "London"


def test_member_settings_drops_blank_fields(world):
    """Posting an empty string for a field should *remove* it, not store ''."""
    client = TestClient(create_app())
    # First seed orcid, then blank it.
    client.post("/api/member/settings", json={"orcid": "0000-0000-0000-0000"})
    client.post("/api/member/settings", json={"orcid": ""})

    meta = parse_file(world["lab_mgmt"] / "members" / "the_pi.md").meta
    assert "orcid" not in meta.get("contact", {})


def test_member_settings_silently_drops_obsidian_fields(world):
    """Old clients may still post obsidian_vault_path; we ignore it because
    those fields moved to ~/.murmurent/machine.yaml."""
    client = TestClient(create_app())
    client.post("/api/member/settings", json={
        "obsidian_vault_path": "/should/not/land/here",
        "obsidian_vault_name": "should-not-land-here",
        "email": "kept@example.edu",
    })
    meta = parse_file(world["lab_mgmt"] / "members" / "the_pi.md").meta
    # contact.email was applied:
    assert meta["contact"]["email"] == "kept@example.edu"
    # The pre-existing obsidian block is unchanged (we didn't touch it):
    assert meta["obsidian"]["vault_path"] == "/legacy/path"


def test_member_nonwriter_edit_stages_and_never_touches_roster(world, monkeypatch, tmp_path):
    """A non-PI member's profile edit is STAGED to their own profile.yaml and
    never committed to the read-only roster clone (#34 Option C) — even before
    the PI has added them to the roster. This is the fix for the unpushable-
    local-commit divergence that used to strand member edits."""
    monkeypatch.setenv("MURMURENT_USER", "bob")            # a member, not the PI
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "bob-home"))
    from murmurent.core import member_profile as mp

    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={
        "email": "bob@example.edu", "office": "MSB-1", "slack_handle": "@bobby",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("staged") is True and body["probes"] == []

    # The roster clone was NOT modified (bob's record is untouched; no commit).
    bob_meta = parse_file(world["lab_mgmt"] / "members" / "bob.md").meta
    assert "contact" not in bob_meta and "location" not in bob_meta

    # The edit landed in bob's own profile.yaml, in roster shape, for the PI to
    # ingest on the next sync.
    staged = mp.staged_roster_profile("bob")
    assert staged["contact"]["email"] == "bob@example.edu"
    assert staged["location"]["office"] == "MSB-1"
    assert staged["slack"] == "bobby"


def test_member_missing_from_roster_still_stages_no_404(world, monkeypatch, tmp_path):
    """A non-writer with no roster file at all stages cleanly (no 404) — the
    roster-file-missing 404 now only guards the writer (PI) path."""
    monkeypatch.setenv("MURMURENT_USER", "ghost")
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "ghost-home"))
    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={"email": "x@y.z"})
    assert res.status_code == 200, res.text
    assert res.json().get("staged") is True
    assert not (world["lab_mgmt"] / "members" / "ghost.md").exists()


def test_staged_member_edit_overlays_own_dashboard(world, monkeypatch, tmp_path):
    """After staging, the member's OWN dashboard reflects the edit immediately
    (overlay), even though the roster hasn't been synced yet."""
    monkeypatch.setenv("MURMURENT_USER", "bob")
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "bob-home"))
    client = TestClient(create_app())
    client.post("/api/member/settings", json={"email": "bob@example.edu"})

    payload = client.get("/api/dashboard?user=bob").json()
    assert payload["member_settings"]["email"] == "bob@example.edu"


# ---------------------------------------------------------------------------
# /api/lab/settings
# ---------------------------------------------------------------------------


def test_lab_settings_pi_only(world, monkeypatch):
    monkeypatch.setenv("MURMURENT_USER", "bob")  # not the PI
    client = TestClient(create_app())
    res = client.post("/api/lab/settings", json={"display_name": "Hacked Lab"})
    assert res.status_code == 403


def test_lab_settings_pi_can_write(world):
    client = TestClient(create_app())
    res = client.post("/api/lab/settings", json={
        "display_name": "Hallett Lab 2.0",
        "website": "https://new.example.org",
        "admins": ["@allie", "@bob"],
    })
    assert res.status_code == 200, res.text

    meta = parse_file(world["lab_mgmt"] / "lab.md").meta
    assert meta["name"] == "Hallett Lab 2.0"  # display_name → name
    assert meta["website"] == "https://new.example.org"
    assert meta["admins"] == ["@allie", "@bob"]
    # Pre-existing fields preserved:
    assert meta["lab"] == "hallett"
    assert meta["institution"] == "Western University"
    # PyYAML parses an unquoted ISO date as a date object; what matters
    # for preservation is that the value round-trips, regardless of type.
    assert meta["created"] in ("2026-05-08", _dt.date(2026, 5, 8))


def test_lab_settings_preserves_body(world):
    client = TestClient(create_app())
    client.post("/api/lab/settings", json={"display_name": "Renamed"})
    parsed = parse_file(world["lab_mgmt"] / "lab.md")
    assert "Body content that must be preserved." in parsed.body


def test_lab_settings_pi_handle_normalised(world):
    """Posting 'the_pi' (no @) must persist as '@the_pi'."""
    client = TestClient(create_app())
    client.post("/api/lab/settings", json={"pi_handle": "newpi"})
    meta = parse_file(world["lab_mgmt"] / "lab.md").meta
    assert meta["pi"] == "@newpi"


# ---------------------------------------------------------------------------
# Snapshot integration
# ---------------------------------------------------------------------------


def test_snapshot_response_includes_machine_settings(world):
    """The dashboard payload must carry a MachineSettings block. The
    vault name is always derived from the path's last segment."""
    ms_mod.write(MachineSettings(
        obsidian_vault_path="/my/laptop/vault",
        obsidian_vault_name="ignored-on-write",
        notebook_subfolder="lab-notebook",
        oracle_subfolder="oracle",
    ))
    client = TestClient(create_app())
    res = client.get("/api/dashboard")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["machine_settings"]["obsidian_vault_path"] == "/my/laptop/vault"
    assert payload["machine_settings"]["obsidian_vault_name"] == "vault"
