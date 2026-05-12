"""Tests for the three settings endpoints + machine.yaml round-trip.

Covers:
  - POST /api/machine/settings: writes ~/.wigamig/machine.yaml, round-trips
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

from wigamig.core.frontmatter import parse_file
from wigamig.dashboard import machine_settings as ms_mod
from wigamig.dashboard import snapshot as snap_mod
from wigamig.dashboard.contract import MachineSettings
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Tmp filesystem with lab-mgmt + redirected machine.yaml."""
    lab_mgmt = tmp_path / "lab-mgmt"
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\n"
        "lab: hallett\n"
        "name: Hallett Lab\n"
        "pi: '@mhallet'\n"
        "institution: Western University\n"
        "department: Schulich\n"
        "website: https://example.org\n"
        "admins: []\n"
        "created: 2026-05-08\n"
        "---\n\n# Hallett Lab\n\nBody content that must be preserved.\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "mhallet.md").write_text(
        "---\n"
        "handle: '@mhallet'\n"
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
        "---\n\n# @mhallet\n\nProfile body that must survive.\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "bob.md").write_text(
        "---\n"
        "handle: '@bob'\nfull_name: 'Bob'\nrole: postdoc\nstatus: active\nlab: hallett\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    # Redirect machine.yaml so we don't touch the developer's real home.
    machine_yaml = tmp_path / "wigamig" / "machine.yaml"
    monkeypatch.setattr(ms_mod, "MACHINE_FILE", machine_yaml)

    return {"tmp": tmp_path, "lab_mgmt": lab_mgmt, "machine_yaml": machine_yaml}


# ---------------------------------------------------------------------------
# /api/machine/settings
# ---------------------------------------------------------------------------


def test_machine_settings_round_trip(world):
    client = TestClient(create_app())
    payload = {
        "obsidian_vault_path": "/Users/me/vault",
        "obsidian_vault_name": "my-vault",
        "notebook_subfolder": "notes",
        "oracle_subfolder": "memory",
    }
    res = client.post("/api/machine/settings", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    on_disk = yaml.safe_load(world["machine_yaml"].read_text())
    # Every field we sent must round-trip. Other fields with defaults
    # (e.g. ``lab_base``) may also be present, set to ``None``.
    for k, v in payload.items():
        assert on_disk[k] == v


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
    ms_mod.write(MachineSettings(
        obsidian_vault_path="/new/path", obsidian_vault_name="new-vault",
        notebook_subfolder="nb", oracle_subfolder="or",
    ))
    legacy = {"vault_path": "/legacy/path", "vault_name": "legacy-vault"}
    s = ms_mod.load(legacy_obsidian=legacy)
    assert s.obsidian_vault_path == "/new/path"
    assert s.obsidian_vault_name == "new-vault"


# ---------------------------------------------------------------------------
# /api/member/settings
# ---------------------------------------------------------------------------


def test_member_settings_rewrites_contact_and_location(world):
    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={
        "email": "new@uwo.ca", "orcid": "0000-0001-1111-1111",
        "office": "MSB-360",
    })
    assert res.status_code == 200, res.text

    parsed = parse_file(world["lab_mgmt"] / "members" / "mhallet.md")
    meta = parsed.meta
    assert meta["contact"]["email"] == "new@uwo.ca"
    assert meta["contact"]["orcid"] == "0000-0001-1111-1111"
    assert meta["location"]["office"] == "MSB-360"


def test_member_settings_preserves_body_and_unknown_keys(world):
    """Certifications, obsidian, custom keys, and the body must survive."""
    client = TestClient(create_app())
    client.post("/api/member/settings", json={"email": "x@y.z"})

    parsed = parse_file(world["lab_mgmt"] / "members" / "mhallet.md")
    meta = parsed.meta
    # Untouched fields:
    assert meta["handle"] == "@mhallet"
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

    meta = parse_file(world["lab_mgmt"] / "members" / "mhallet.md").meta
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

    meta = parse_file(world["lab_mgmt"] / "members" / "mhallet.md").meta
    assert "orcid" not in meta.get("contact", {})


def test_member_settings_silently_drops_obsidian_fields(world):
    """Old clients may still post obsidian_vault_path; we ignore it because
    those fields moved to ~/.wigamig/machine.yaml."""
    client = TestClient(create_app())
    client.post("/api/member/settings", json={
        "obsidian_vault_path": "/should/not/land/here",
        "obsidian_vault_name": "should-not-land-here",
        "email": "kept@uwo.ca",
    })
    meta = parse_file(world["lab_mgmt"] / "members" / "mhallet.md").meta
    # contact.email was applied:
    assert meta["contact"]["email"] == "kept@uwo.ca"
    # The pre-existing obsidian block is unchanged (we didn't touch it):
    assert meta["obsidian"]["vault_path"] == "/legacy/path"


def test_member_settings_404_when_member_file_missing(world, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "ghost")
    client = TestClient(create_app())
    res = client.post("/api/member/settings", json={"email": "x@y.z"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# /api/lab/settings
# ---------------------------------------------------------------------------


def test_lab_settings_pi_only(world, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "bob")  # not the PI
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
    """Posting 'mhallet' (no @) must persist as '@mhallet'."""
    client = TestClient(create_app())
    client.post("/api/lab/settings", json={"pi_handle": "newpi"})
    meta = parse_file(world["lab_mgmt"] / "lab.md").meta
    assert meta["pi"] == "@newpi"


# ---------------------------------------------------------------------------
# Snapshot integration
# ---------------------------------------------------------------------------


def test_snapshot_response_includes_machine_settings(world):
    """The dashboard payload must carry a MachineSettings block."""
    ms_mod.write(MachineSettings(
        obsidian_vault_path="/my/laptop/vault",
        obsidian_vault_name="laptop-vault",
        notebook_subfolder="lab-notebook",
        oracle_subfolder="oracle",
    ))
    client = TestClient(create_app())
    res = client.get("/api/dashboard")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["machine_settings"]["obsidian_vault_path"] == "/my/laptop/vault"
    assert payload["machine_settings"]["obsidian_vault_name"] == "laptop-vault"
