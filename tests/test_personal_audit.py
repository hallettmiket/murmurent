"""Tests for core.personal_audit — the LOCAL member-initiated security audit
(issue #63 Phase 1).

The orchestrator is pure aggregation over existing reconcilers/inventory, so
these tests monkeypatch those seams (reconcile_github / reconcile_slack /
list_machine_repos / identity / verify_local_identity / slack token) and assert
the Finding shape: severity, category, and the new verify_state three-state.
"""

from __future__ import annotations

import datetime as _dt
import os

import pytest

from murmurent.core import cert_projects as CP
from murmurent.core import cert_provision as CPROV
from murmurent.core import group_reconcile as GR
from murmurent.core import issuance as ISS
from murmurent.core import personal_audit as PA
from murmurent.core import project_provision as PP
from murmurent.core import repo as REPO
from murmurent.core import repo_inventory as INV
from murmurent.core import vault_sync as VS
from murmurent.core.repo_inventory import RepoOnHost


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _proj(name="proj1", *, lead="@alice", members=("@alice", "@bob"),
          sensitivity="standard", github_repo="org/proj1",
          slack_channel_id="C1", repos=(), reb_expires="", lab="hallett"):
    return CP.CertProject(
        name=name, lab=lab, status="active", lead=lead, sensitivity=sensitivity,
        github_repo=github_repo, slack_channel_id=slack_channel_id,
        members=tuple(members), repos=tuple(repos), reb_expires=reb_expires)


def _repo_on_host(path, *, ready=True, infra=False, is_git=True, origin=""):
    return RepoOnHost(host="local", path=str(path), origin_url=origin,
                      has_marker=ready, has_claude_dir=ready,
                      is_murmurent_ready=ready, is_murmurent_infra=infra,
                      is_git=is_git)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Quiet the identity + external seams so tests don't touch gh/slack/net."""
    monkeypatch.setenv("MURMURENT_USER", "alice")
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "dot"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "labmgmt"))
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path / "repos"))
    # No cards / no crypto by default.
    monkeypatch.setattr(ISS, "verify_local_identity", lambda **kw: ("no_card", ""))
    # No vault by default.
    monkeypatch.setattr(VS, "personal_vault_root", lambda: None)
    # No github org resolution (avoids gh).
    monkeypatch.setattr(PA, "_github_repos", lambda env: ([], None))
    monkeypatch.setattr(INV, "list_machine_repos", lambda h: ([], None))
    monkeypatch.setattr(CP, "iter_projects", lambda env=None: [])


# ---------------------------------------------------------------------------
# item 1 — GitHub
# ---------------------------------------------------------------------------


def test_github_in_sync_as_lead(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(PP, "_gh_available", lambda: True)
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: {"ok": True, "to_add": [], "to_remove": []})
    out = PA.check_github("alice", [p], None)
    rules = {f.rule for f in out}
    assert "PERSONAL-GH-IN-SYNC-01" in rules
    assert all(f.verify_state == "verified" for f in out)


def test_github_missing_member_warns(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(PP, "_gh_available", lambda: True)
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: {"ok": True, "to_add": ["bobgh"], "to_remove": []})
    (f,) = [x for x in PA.check_github("alice", [p], None)
            if x.rule == "PERSONAL-GH-MEMBER-MISSING-01"]
    assert f.severity == "warn"
    assert "bobgh" in f.current_state


def test_github_extra_collaborator_is_noted_not_error(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(PP, "_gh_available", lambda: True)
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: {"ok": True, "to_add": [], "to_remove": ["stranger"]})
    (f,) = [x for x in PA.check_github("alice", [p], None)
            if x.rule == "PERSONAL-GH-EXTRA-COLLAB-01"]
    assert f.severity == "info"          # noted, not a drift
    assert "not in the project" in f.current_state


def test_github_gh_absent_is_unverifiable(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(PP, "_gh_available", lambda: False)
    # reconcile must NOT be consulted when gh is absent.
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: pytest.fail("reconcile called with gh absent"))
    (f,) = PA.check_github("alice", [p], None)
    assert f.verify_state == "unverifiable"
    assert f.severity == "info"          # could-not-verify, never a false drift


def test_github_member_no_access_warns(monkeypatch):
    p = _proj(lead="@carol", members=("@carol", "@alice"))
    monkeypatch.setattr(PP, "_gh_available", lambda: True)
    monkeypatch.setattr(CPROV, "member_github_map", lambda hs: {"alice": "alicegh"})
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: {"ok": True, "to_add": ["alicegh"], "to_remove": []})
    (f,) = [x for x in PA.check_github("alice", [p], None)
            if x.rule == "PERSONAL-GH-NO-ACCESS-01"]
    assert f.severity == "warn"


# ---------------------------------------------------------------------------
# item 4 — Slack
# ---------------------------------------------------------------------------


def test_slack_token_absent_is_unverifiable(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(GR, "resolve_group_slack_token", lambda g, **k: "")
    monkeypatch.setattr(CPROV, "reconcile_slack",
                        lambda *a, **k: pytest.fail("reconcile called with no token"))
    (f,) = PA.check_slack("alice", [p], None)
    assert f.verify_state == "unverifiable"
    assert f.severity == "info"


def test_slack_in_sync_as_lead(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(GR, "resolve_group_slack_token", lambda g, **k: "xoxb-tok")
    monkeypatch.setattr(CPROV, "reconcile_slack",
                        lambda *a, **k: {"ok": True, "to_invite": [], "to_kick": [],
                                         "unresolved": []})
    rules = {f.rule for f in PA.check_slack("alice", [p], None)}
    assert "PERSONAL-SLACK-IN-SYNC-01" in rules


def test_slack_missing_member_warns(monkeypatch):
    p = _proj(lead="@alice")
    monkeypatch.setattr(GR, "resolve_group_slack_token", lambda g, **k: "xoxb-tok")
    monkeypatch.setattr(CPROV, "reconcile_slack",
                        lambda *a, **k: {"ok": True, "to_invite": ["bob"], "to_kick": [],
                                         "unresolved": []})
    (f,) = [x for x in PA.check_slack("alice", [p], None)
            if x.rule == "PERSONAL-SLACK-MEMBER-MISSING-01"]
    assert f.severity == "warn"


# ---------------------------------------------------------------------------
# item 7 — cert / REB
# ---------------------------------------------------------------------------


def test_cert_no_card_is_unverifiable(monkeypatch):
    monkeypatch.setattr(ISS, "verify_local_identity", lambda **kw: ("no_card", ""))
    (f,) = [x for x in PA.check_cert("alice", [], None)
            if x.category == "cert"]
    assert f.verify_state == "unverifiable"


def test_cert_rejected_blocks(monkeypatch):
    monkeypatch.setattr(ISS, "verify_local_identity", lambda **kw: ("reject", "expired"))
    (f,) = [x for x in PA.check_cert("alice", [], None)
            if x.rule == "PERSONAL-CERT-INVALID-01"]
    assert f.severity == "block"


def test_clinical_reb_expired_blocks(monkeypatch):
    monkeypatch.setattr(ISS, "verify_local_identity", lambda **kw: ("ok", ""))
    monkeypatch.setattr(PA, "_own_card_valid_until", lambda env: None)
    past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=5)).date().isoformat()
    p = _proj(sensitivity="clinical", lead="@alice", reb_expires=past)
    (f,) = [x for x in PA.check_cert("alice", [p], None)
            if x.rule == "PERSONAL-REB-EXPIRED-01"]
    assert f.severity == "block"


def test_clinical_reb_expiring_warns(monkeypatch):
    monkeypatch.setattr(ISS, "verify_local_identity", lambda **kw: ("ok", ""))
    monkeypatch.setattr(PA, "_own_card_valid_until", lambda env: None)
    soon = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=10)).date().isoformat()
    p = _proj(sensitivity="clinical", lead="@alice", reb_expires=soon)
    (f,) = [x for x in PA.check_cert("alice", [p], None)
            if x.rule == "PERSONAL-REB-EXPIRING-01"]
    assert f.severity == "warn"


# ---------------------------------------------------------------------------
# item 2i + vault — ACLs
# ---------------------------------------------------------------------------


def test_repo_acl_owner_only_is_ok(tmp_path):
    d = tmp_path / "cleanrepo"
    d.mkdir()
    os.chmod(d, 0o700)
    (f,) = PA.check_repo_acls("alice", [_repo_on_host(d)], None)
    assert f.rule == "PERSONAL-ACL-OK-01"
    assert f.severity == "info"


def test_repo_acl_overshare_warns(tmp_path):
    d = tmp_path / "openrepo"
    d.mkdir()
    os.chmod(d, 0o755)          # group + world readable
    (f,) = PA.check_repo_acls("alice", [_repo_on_host(d)], None)
    assert f.rule == "PERSONAL-ACL-OVERSHARE-01"
    assert f.severity == "warn"


def test_clinical_repo_acl_escalates_to_block(tmp_path, monkeypatch):
    d = tmp_path / "clinrepo"
    d.mkdir()
    os.chmod(d, 0o755)
    # A clinical cert-project pointing at this repo path.
    cp = _proj(name="clin", sensitivity="clinical",
               repos=(CP.RepoRef(name="clin", role="code", path=str(d)),))
    monkeypatch.setattr(CP, "iter_projects", lambda env=None: [cp])
    (f,) = PA.check_repo_acls("alice", [_repo_on_host(d)], None)
    assert f.rule == "PERSONAL-ACL-CLINICAL-01"
    assert f.severity == "block"


def test_vault_overshare_blocks(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    v.mkdir()
    os.chmod(v, 0o755)
    monkeypatch.setattr(VS, "personal_vault_root", lambda: v)
    (f,) = PA.check_vault_acls("alice", None)
    assert f.severity == "block"       # vault over-share is always a block
    assert f.category == "vault"


# ---------------------------------------------------------------------------
# item V — clinical containment
# ---------------------------------------------------------------------------


def test_clinical_containment_leak_blocks(tmp_path, monkeypatch):
    # A clinical-tagged oracle entry living in a project repo (NOT the vault).
    repo_dir = tmp_path / "someproj"
    (repo_dir / "oracle").mkdir(parents=True)
    (repo_dir / "oracle" / "note.md").write_text(
        "---\ntitle: x\nsensitivity: clinical\n---\n\nbody\n", encoding="utf-8")
    monkeypatch.setattr(VS, "personal_vault_root", lambda: tmp_path / "vault")
    monkeypatch.setattr(REPO, "lab_mgmt_repo_root", lambda env=None: tmp_path / "nope")
    out = PA.check_clinical_containment("alice", [_repo_on_host(repo_dir)], None)
    leaks = [f for f in out if f.rule == "PERSONAL-CLINICAL-LEAK-01"]
    assert len(leaks) == 1
    assert leaks[0].severity == "block"


def test_clinical_containment_clean(tmp_path, monkeypatch):
    repo_dir = tmp_path / "clean"
    (repo_dir / "src").mkdir(parents=True)
    (repo_dir / "src" / "note.md").write_text(
        "---\ntitle: x\nsensitivity: standard\n---\n\nok\n", encoding="utf-8")
    monkeypatch.setattr(VS, "personal_vault_root", lambda: tmp_path / "vault")
    monkeypatch.setattr(REPO, "lab_mgmt_repo_root", lambda env=None: tmp_path / "nope")
    out = PA.check_clinical_containment("alice", [_repo_on_host(repo_dir)], None)
    assert [f.rule for f in out] == ["PERSONAL-CLINICAL-CONTAINED-01"]


# ---------------------------------------------------------------------------
# item 6 — non-MM repos
# ---------------------------------------------------------------------------


def test_non_mm_repo_flagged(tmp_path):
    ready = _repo_on_host(tmp_path / "ready", ready=True)
    plain = _repo_on_host(tmp_path / "plain", ready=False)
    infra = _repo_on_host(tmp_path / "murmurent", ready=False, infra=True)
    out = PA.check_non_mm("alice", [ready, plain, infra], [], set(), None)
    flagged = [f for f in out if f.rule == "PERSONAL-NON-MM-REPO-01"]
    assert [f.path for f in flagged] == [str(tmp_path / "plain")]


# ---------------------------------------------------------------------------
# end-to-end
# ---------------------------------------------------------------------------


def test_run_personal_audit_end_to_end(monkeypatch, tmp_path):
    p = _proj(lead="@alice")
    monkeypatch.setattr(CP, "iter_projects", lambda env=None: [p])
    monkeypatch.setattr(PP, "_gh_available", lambda: True)
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: {"ok": True, "to_add": [], "to_remove": []})
    monkeypatch.setattr(GR, "resolve_group_slack_token", lambda g, **k: "xoxb")
    monkeypatch.setattr(CPROV, "reconcile_slack",
                        lambda *a, **k: {"ok": True, "to_invite": [], "to_kick": [],
                                         "unresolved": []})
    report = PA.run_personal_audit(env=None)
    assert report.handle == "alice"
    # Every area present in the grouping map.
    areas = report.by_area()
    assert set(areas) >= set(PA.ALL_AREAS)
    # Headline is <=200 chars and leads with a verdict verb.
    assert len(report.headline()) <= 200
    assert report.headline().split()[0] in {"Clear", "Concerns", "BLOCKED"}


def test_no_handle_skips_identity_checks(monkeypatch):
    # Identity cannot resolve → single unverifiable finding, no gh/slack calls.
    from murmurent.core import identity as ID
    monkeypatch.delenv("MURMURENT_USER", raising=False)
    monkeypatch.setattr(ID, "resolve",
                        lambda **kw: ID.Identity(handle="unknown", source="unknown"))
    monkeypatch.setattr(CPROV, "reconcile_github",
                        lambda *a, **k: pytest.fail("gh consulted without a handle"))
    report = PA.run_personal_audit(env=None)
    assert any(f.rule == "PERSONAL-NO-HANDLE-01" and f.verify_state == "unverifiable"
               for f in report.findings)


def test_persist_writes_jsonl_and_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(CP, "iter_projects", lambda env=None: [])
    report = PA.run_personal_audit(env=None)
    # Point PERSIST_ROOT at a tmp dir so we don't touch the real home.
    monkeypatch.setattr(PA, "PERSIST_ROOT", tmp_path / "sec")
    path = PA.persist(report)
    assert path.is_file()
    latest = path.parent / "personal-latest.jsonl"
    assert latest.exists()
