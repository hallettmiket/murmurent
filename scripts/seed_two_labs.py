"""
Purpose: Wipe the dashboard's fake data and reseed with two labs (hallett +
         vdumeaux), three non-PI members per lab, two projects per lab
         (one standard + one clinical), and a cross-lab collaboration.
         Certifications are seeded with deliberate variety so the
         compliance panel shows ok / expiring / expired / missing /
         completed / n/a in the same grid.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-14
Input: None (paths are constants below). Reads compliance.md from
       ``~/repos/lab_mgmt`` to keep the cert spec authoritative.
Output:
  ~/repos/lab_mgmt/                  (hallett lab — primary)
    members/{mhallet,mu1,mu2,mu3}.md
    projects/{mp1,mp2}.md
  ~/.wigamig/lab_info/
    _registry.yaml                   (lists hallett + vdumeaux + collab)
    labs/vdumeaux/lab-mgmt/          (full lab-mgmt scaffold)
    collaborations/mhallet_vdumeaux/

The script is idempotent: re-running wipes targeted directories and
rewrites every file. Preserved: lab.md (your lab_base/slack edits) and
compliance.md (the institution-wide cert spec). Untouched: ~/.wigamig/
{user,registrar,machine.yaml,dashboard.log} so the in-flight dashboard
session keeps working.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = Path.home()
REPOS = HOME / "repos"
HALLETT_REPO = REPOS / "lab_mgmt"
LAB_INFO     = HOME / ".wigamig" / "lab_info"
VDUMEAUX_REPO = LAB_INFO / "labs" / "vdumeaux" / "lab-mgmt"
COLLAB_DIR    = LAB_INFO / "collaborations" / "mhallet_vdumeaux"

# Fake project repos from the old tutorial seed. The dashboard finds them
# via CHARTER.md in any ~/repos/<name>/ subdir, so we delete them outright.
OLD_PROJECT_REPOS = (
    "bbb_drug_screen",
    "blah_blee",
    "candi",
    "dcis_sc_tutorial",
)

# Working clones the dashboard should surface in the new state. Created as
# minimal git repos with CHARTER.md + MEMBERS + README.md.
NEW_PROJECT_REPOS = ("mp1", "mp2", "vp1", "vp2")

TODAY = _dt.date(2026, 5, 14)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print(f"  wrote {path}")


def wipe_dir_contents(path: Path, keep: set[str] | None = None) -> None:
    """Remove all files+subdirs in ``path`` except those whose top-level
    name is in ``keep``. Idempotent: missing ``path`` is a no-op."""
    keep = keep or set()
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        print(f"  wiped {child}")


def fm_dump(meta: dict, body: str = "") -> str:
    """YAML frontmatter + markdown body, matching the lab-mgmt convention."""
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n{body.rstrip()}\n"


def cert_date(offset_days: int) -> str:
    """ISO date offset from TODAY. Negative = past (expired)."""
    return (TODAY + _dt.timedelta(days=offset_days)).isoformat()


# ---------------------------------------------------------------------------
# Member specs — designed for compliance-grid variety
# ---------------------------------------------------------------------------

# Cert codes in compliance.md (institution-wide):
#   WHM103  WHMIS                          (3yr cadence, audience=all)
#   HSAW01  Health & Safety Awareness      (one-time,  audience=all)
#   WSCC01  Western Safe Campus            (one-time,  audience=all)
#   GBSVE1  Gender-Based Violence          (one-time,  audience=all)
#   BIAR1E  Anti-Racism                    (one-time,  audience=all)
#   BIOS01  Biosafety                      (3yr cadence, audience=lab)
#   LBHW01  Laboratory Safety              (3yr cadence, audience=lab)
#   TCPS_2  Human Research Ethics          (3yr cadence, audience=clinical)
#   LAS01, RAD01W, XRAY01, AODAT1 — audience=optional, omit unless relevant

def certs_pi() -> list[str]:
    """All-OK profile, used for both PIs."""
    return [
        f"WHM103:{cert_date(720)}",
        "HSAW01:completed",
        "WSCC01:completed",
        "GBSVE1:completed",
        "BIAR1E:completed",
        f"BIOS01:{cert_date(700)}",
        f"LBHW01:{cert_date(700)}",
        f"TCPS_2:{cert_date(760)}",
        "TOTP:enrolled",
        "signing_key:registered",
    ]


MEMBER_SPECS: dict[str, dict] = {
    # ── hallett lab ──────────────────────────────────────────────────────
    "mhallet": dict(
        full_name="Mike Hallett",
        role="lead", lab="hallett",
        email="hallett.mike.t@gmail.com",
        orcid="0000-0003-1234-5678",
        github="hallettmiket",
        office="SSC-2418",
        certs=certs_pi(),
    ),
    "mu1": dict(
        full_name="mu1 (postdoc, hallett — fake)",
        role="postdoc", lab="hallett",
        email="mu1@uwo.ca",
        certs=[
            f"WHM103:{cert_date(480)}",          # ok
            "HSAW01:completed",
            "WSCC01:completed",
            "GBSVE1:completed",
            "BIAR1E:completed",
            f"BIOS01:{cert_date(27)}",            # expiring (within 60d)
            f"LBHW01:{cert_date(630)}",           # ok
            # TCPS_2 missing — not on a clinical project
            "TOTP:enrolled",
            "signing_key:registered",
        ],
    ),
    "mu2": dict(
        full_name="mu2 (grad student, hallett — fake)",
        role="phd_student", lab="hallett",
        email="mu2@uwo.ca",
        certs=[
            f"WHM103:{cert_date(320)}",           # ok
            "HSAW01:completed",
            "WSCC01:completed",
            # GBSVE1 missing
            "BIAR1E:completed",
            f"BIOS01:{cert_date(-210)}",          # expired
            f"LBHW01:{cert_date(450)}",           # ok
            f"TCPS_2:{cert_date(45)}",            # expiring (clinical project)
            "TOTP:enrolled",
            "signing_key:registered",
        ],
    ),
    "mu3": dict(
        full_name="mu3 (grad student, hallett, cross-lab collab — fake)",
        role="phd_student", lab="hallett",
        email="mu3@uwo.ca",
        certs=[
            f"WHM103:{cert_date(610)}",           # ok
            "HSAW01:completed",
            "WSCC01:completed",
            "GBSVE1:completed",
            # BIAR1E missing
            f"BIOS01:{cert_date(540)}",           # ok
            f"LBHW01:{cert_date(540)}",           # ok
            f"TCPS_2:{cert_date(670)}",           # ok (needed for clinical collab)
            "TOTP:enrolled",
            "signing_key:registered",
        ],
    ),
    # ── vdumeaux lab ─────────────────────────────────────────────────────
    "vdumeaux": dict(
        full_name="V. Dumeaux",
        role="lead", lab="vdumeaux",
        email="vdumeaux@uwo.ca",
        orcid="0000-0002-9999-1111",
        github="vdumeaux",
        office="SSC-2402",
        certs=certs_pi(),
    ),
    "vu1": dict(
        full_name="vu1 (postdoc, vdumeaux — fake)",
        role="postdoc", lab="vdumeaux",
        email="vu1@uwo.ca",
        certs=[
            f"WHM103:{cert_date(660)}",           # ok
            "HSAW01:completed",
            "WSCC01:completed",
            "GBSVE1:completed",
            "BIAR1E:completed",
            f"BIOS01:{cert_date(660)}",           # ok
            f"LBHW01:{cert_date(660)}",           # ok
            "TOTP:enrolled",
            "signing_key:registered",
        ],
    ),
    "vu2": dict(
        full_name="vu2 (grad student, vdumeaux — fake)",
        role="phd_student", lab="vdumeaux",
        email="vu2@uwo.ca",
        certs=[
            f"WHM103:{cert_date(230)}",           # ok
            "HSAW01:completed",
            "WSCC01:completed",
            "GBSVE1:completed",
            # BIAR1E missing
            f"BIOS01:{cert_date(-150)}",          # expired
            f"LBHW01:{cert_date(320)}",           # ok
            "TOTP:enrolled",
            # signing_key missing (lab-key not yet registered)
        ],
    ),
    "vu3": dict(
        full_name="vu3 (grad student, vdumeaux, cross-lab collab — fake)",
        role="phd_student", lab="vdumeaux",
        email="vu3@uwo.ca",
        certs=[
            f"WHM103:{cert_date(380)}",           # ok
            "HSAW01:completed",
            "WSCC01:completed",
            "GBSVE1:completed",
            "BIAR1E:completed",
            f"BIOS01:{cert_date(515)}",           # ok
            f"LBHW01:{cert_date(515)}",           # ok
            f"TCPS_2:{cert_date(-130)}",          # EXPIRED (clinical collab — blocking)
            "TOTP:enrolled",
            "signing_key:registered",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Project specs
# ---------------------------------------------------------------------------

PROJECT_SPECS: dict[str, dict] = {
    # ── hallett lab ──────────────────────────────────────────────────────
    "mp1": dict(
        lab="hallett",
        sensitivity="standard",
        lead="@mhallet",
        members=["@mhallet", "@mu1", "@mu2"],
        description="hallett lab project 1 — standard sensitivity (GitHub remote)",
    ),
    "mp2": dict(
        lab="hallett",
        sensitivity="clinical",
        lead="@mhallet",
        members=["@mhallet", "@mu2", "@mu3"],
        description="hallett lab project 2 — clinical (private bare-repo remote)",
    ),
    # ── vdumeaux lab ─────────────────────────────────────────────────────
    "vp1": dict(
        lab="vdumeaux",
        sensitivity="standard",
        lead="@vdumeaux",
        members=["@vdumeaux", "@vu1", "@vu2"],
        description="vdumeaux lab project 1 — standard sensitivity (GitHub remote)",
    ),
    "vp2": dict(
        lab="vdumeaux",
        sensitivity="clinical",
        lead="@vdumeaux",
        members=["@vdumeaux", "@vu2", "@vu3"],
        description="vdumeaux lab project 2 — clinical (private bare-repo remote)",
    ),
}


# ---------------------------------------------------------------------------
# Members + projects renderers
# ---------------------------------------------------------------------------

def render_member(handle: str, spec: dict) -> str:
    meta = {
        "handle": f"@{handle}",
        "full_name": spec["full_name"],
        "role": spec["role"],
        "status": "active",
        "lab": spec["lab"],
        "contact": {
            "email": spec.get("email", f"{handle}@uwo.ca"),
            **({"orcid": spec["orcid"]} if "orcid" in spec else {}),
            **({"github": spec["github"]} if "github" in spec else {}),
        },
        "location": {
            "office": spec.get("office", "SSC-2418"),
            "address": "1151 Richmond St",
            "city": "London, ON N6A 3K7, Canada",
            "department":
                "Schulich School of Dentristy and Medicine · Department of Biochemistry",
        },
        "certifications": spec["certs"],
        "created": TODAY.isoformat(),
    }
    body = (
        f"# @{handle}\n\n"
        f"Seed profile for the fake testing persona **@{handle}**.\n\n"
        f"All compliance state is in the `certifications:` frontmatter; "
        f"edit through the dashboard."
    )
    return fm_dump(meta, body)


def render_project(name: str, spec: dict) -> str:
    meta = {
        "project": name,
        "path": str(HOME / "repos" / name),
        "sensitivity": spec["sensitivity"],
        "lead": spec["lead"],
        "created": TODAY.isoformat(),
        "members": list(spec["members"]),
    }
    body = (
        f"# {name}\n\n{spec['description']}\n\n"
        f"Seed registry entry. Edit the project repo's `CHARTER.md` to change "
        f"the canonical metadata; this file mirrors it for cross-project lookups."
    )
    return fm_dump(meta, body)


# ---------------------------------------------------------------------------
# Lab + collaboration renderers
# ---------------------------------------------------------------------------

def render_vdumeaux_lab_md() -> str:
    meta = {
        "lab": "vdumeaux",
        "name": "Dumeaux Lab",
        "pi": "@vdumeaux",
        "institution": "Western University",
        "department":
            "Schulich School of Dentristy and Medicine · Department of Biochemistry",
        "website": "https://vdumeaux.science",
        "lab_base": "biodatsci.schulich.uwo.ca:/data/lab_vm/wigamig",
        "github_org": "vdumeaux",
        "git_repos_subpath": "repos",
        "admins": [],
        "created": TODAY.isoformat(),
    }
    body = "# Dumeaux Lab — group config\n\nSeed data for the cross-lab testing setup."
    return fm_dump(meta, body)


def render_collaboration() -> str:
    meta = {
        "collaboration": "mhallet_vdumeaux",
        "pis": ["@mhallet", "@vdumeaux"],
        "groups": ["hallett", "vdumeaux"],
        "member_subset": {
            "hallett":  ["@mhallet", "@mu3"],
            "vdumeaux": ["@vdumeaux", "@vu3"],
        },
        "oracle_vault": "wigamig_collab_mhallet_vdumeaux",
        "created": TODAY.isoformat(),
    }
    body = (
        "# Collaboration: mhallet × vdumeaux\n\n"
        "Cross-lab collaboration between the Hallett lab and the Dumeaux lab. "
        "PIs: @mhallet, @vdumeaux. Member subset: @mu3 (hallett) + @vu3 (vdumeaux). "
        "Project files live in `projects/`; the collaboration's own Obsidian vault "
        "is rooted at `oracle/`."
    )
    return fm_dump(meta, body)


def render_charter(name: str, spec: dict) -> str:
    """A minimal CHARTER.md the dashboard's iter_local_projects() will find.

    Clinical-sensitivity charters get the extra REB / data_residency fields
    required by ``wigamig.core.charter.validate_charter``.
    """
    meta = {
        "project": name,
        # ``lab:`` is what the dashboard uses to scope project visibility
        # across labs — without it, every lab on a laptop sees every other
        # lab's projects (the #10 cross-lab leakage). See snapshot.build_response.
        "lab": spec["lab"],
        "lead": spec["lead"],
        "sensitivity": spec["sensitivity"],
        "created": TODAY.isoformat(),
        # All seed projects use repo_kind=github for now. The
        # repo_kind=local path needs a local-filesystem local_repo_root
        # (used to do `git init --bare`), which only works when the
        # dashboard runs on the lab server. The bare-repo-over-SSH flow
        # for sensitive projects lands with the cross-lab work (#10).
        # `sensitivity:` is preserved below so the UI still distinguishes
        # clinical projects.
        "repo_kind": "github",
        "members": list(spec["members"]),
    }
    if spec["sensitivity"] == "clinical":
        meta.update({
            "reb_number": f"REB-{TODAY.year}-{name.upper()}",
            "reb_expires": cert_date(720),  # 2 years out
            "data_residency": "Canada",
        })
    body = (
        f"# {name}\n\n{spec['description']}\n\n"
        f"Seed project — fake testing data. The canonical metadata is in this "
        f"file's frontmatter; `MEMBERS` mirrors the member handles."
    )
    return fm_dump(meta, body)


def render_members_file(spec: dict) -> str:
    lines = ["# wigamig project MEMBERS — one handle per line."]
    lines.extend(spec["members"])
    return "\n".join(lines) + "\n"


def render_registry() -> str:
    reg = {
        "version": 1,
        "labs": {
            "hallett": {
                "pi": "@mhallet",
                "lab_mgmt_path": str(HALLETT_REPO),
                "status": "active",
                "created": TODAY.isoformat(),
                "slack_workspace": "TDUD7D20Y",
                "oracle_vault": "lab_oracle/",
            },
            "vdumeaux": {
                "pi": "@vdumeaux",
                "lab_mgmt_path": str(VDUMEAUX_REPO),
                "status": "active",
                "created": TODAY.isoformat(),
                "github_org": "vdumeaux",
                "oracle_vault": "lab_oracle/",
            },
        },
        "cores": {},
        "collaborations": {
            "mhallet_vdumeaux": {
                "pis": ["@mhallet", "@vdumeaux"],
                "groups": ["hallett", "vdumeaux"],
                "member_subset": {
                    "hallett":  ["@mhallet", "@mu3"],
                    "vdumeaux": ["@vdumeaux", "@vu3"],
                },
                "oracle_vault": "wigamig_collab_mhallet_vdumeaux",
                "status": "active",
                "created": TODAY.isoformat(),
            },
        },
    }
    return yaml.safe_dump(reg, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"=== Seeding two-lab testing setup (today = {TODAY.isoformat()}) ===\n")

    # ── Wipe hallett lab_mgmt data (preserve config + spec) ─────────────
    print("[1/5] Wiping hallett lab data (keeping lab.md, compliance.md, README.md)")
    for sub in ("members", "projects", "audit", "dashboards",
                "inventory", "keys", "requests"):
        wipe_dir_contents(HALLETT_REPO / sub)
    # Also clear stale untracked stragglers we don't want.
    for stale in ("oracle-publish.log",):
        p = HALLETT_REPO / stale
        if p.is_file():
            p.unlink()
            print(f"  wiped {p}")
    print()

    # ── Wipe lab_info registrar layer (except registrar.md) ─────────────
    print("[2/5] Wiping registrar registry (keeping registrar.md)")
    for sub in ("labs", "cores", "collaborations"):
        wipe_dir_contents(LAB_INFO / sub)
    # _registry.yaml is rewritten below.
    print()

    # ── Re-seed hallett members + projects ─────────────────────────────
    print("[3/5] Seeding hallett lab members + projects")
    for handle in ("mhallet", "mu1", "mu2", "mu3"):
        write(HALLETT_REPO / "members" / f"{handle}.md",
              render_member(handle, MEMBER_SPECS[handle]))
    for proj in ("mp1", "mp2"):
        write(HALLETT_REPO / "projects" / f"{proj}.md",
              render_project(proj, PROJECT_SPECS[proj]))
    # Empty subdir placeholders so the dashboard finds the dirs.
    for sub in ("audit", "dashboards", "inventory", "keys", "requests"):
        (HALLETT_REPO / sub).mkdir(exist_ok=True)
        (HALLETT_REPO / sub / ".gitkeep").touch()
    print()

    # ── Create vdumeaux lab-mgmt under lab_info/labs/vdumeaux/ ──────────
    print("[4/5] Seeding vdumeaux lab")
    VDUMEAUX_REPO.mkdir(parents=True, exist_ok=True)
    write(VDUMEAUX_REPO / "lab.md", render_vdumeaux_lab_md())
    # Copy compliance.md verbatim from hallett — institution-wide cert spec.
    src_comp = HALLETT_REPO / "compliance.md"
    if src_comp.is_file():
        (VDUMEAUX_REPO / "compliance.md").write_text(
            src_comp.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  copied compliance.md -> {VDUMEAUX_REPO / 'compliance.md'}")
    for handle in ("vdumeaux", "vu1", "vu2", "vu3"):
        write(VDUMEAUX_REPO / "members" / f"{handle}.md",
              render_member(handle, MEMBER_SPECS[handle]))
    for proj in ("vp1", "vp2"):
        write(VDUMEAUX_REPO / "projects" / f"{proj}.md",
              render_project(proj, PROJECT_SPECS[proj]))
    for sub in ("audit", "dashboards", "inventory", "keys", "requests"):
        (VDUMEAUX_REPO / sub).mkdir(exist_ok=True)
        (VDUMEAUX_REPO / sub / ".gitkeep").touch()
    print()

    # ── Collaboration + registry ────────────────────────────────────────
    print("[5/7] Writing collaboration + _registry.yaml")
    COLLAB_DIR.mkdir(parents=True, exist_ok=True)
    write(COLLAB_DIR / "collaboration.md", render_collaboration())
    (COLLAB_DIR / "projects").mkdir(exist_ok=True)
    (COLLAB_DIR / "projects" / ".gitkeep").touch()
    (COLLAB_DIR / "oracle").mkdir(exist_ok=True)
    (COLLAB_DIR / "oracle" / ".gitkeep").touch()
    write(LAB_INFO / "_registry.yaml", render_registry())
    print()

    # ── Delete old project repos (they have CHARTER.md → dashboard sees them) ─
    print("[6/7] Removing old fake project repos")
    for name in OLD_PROJECT_REPOS:
        p = REPOS / name
        if p.is_dir():
            shutil.rmtree(p)
            print(f"  removed {p}")
    print()

    # ── Scaffold new project repos with CHARTER.md + MEMBERS ──────────────
    print("[7/7] Scaffolding new project repos")
    for name in NEW_PROJECT_REPOS:
        spec = PROJECT_SPECS[name]
        repo = REPOS / name
        if repo.is_dir():
            # idempotent: wipe contents but keep .git if present
            for child in repo.iterdir():
                if child.name == ".git":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        repo.mkdir(parents=True, exist_ok=True)
        write(repo / "CHARTER.md", render_charter(name, spec))
        write(repo / "MEMBERS", render_members_file(spec))
        write(repo / "README.md",
              f"# {name}\n\n{spec['description']}\n\nSeed project from "
              f"`scripts/seed_two_labs.py`. Edit CHARTER.md to update metadata.\n")
        if not (repo / ".git").is_dir():
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)],
                           check=False)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
            subprocess.run(["git", "-C", str(repo), "commit", "-q",
                            "-m", f"seed {name}"], check=False)
            print(f"  git init + initial commit @ {repo}")
    print()

    # ── Clear stale per-machine state that references gone projects ─────
    workspaces = HOME / ".wigamig" / "workspaces"
    installs   = HOME / ".wigamig" / "installations"
    if workspaces.is_dir() or installs.is_dir():
        print("(also wiping ~/.wigamig/workspaces and installations of old projects)")
        for d in (workspaces, installs):
            if d.is_dir():
                for child in d.iterdir():
                    if any(old in child.name for old in OLD_PROJECT_REPOS):
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        print(f"  wiped {child}")

    print("\n=== Done. Restart the dashboard to pick up the new state. ===")


if __name__ == "__main__":
    main()
