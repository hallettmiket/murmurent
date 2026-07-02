"""
Purpose: "Create the world" — bootstrap a demo wigamig **centre** (the
         admin layer) so the mayor/registrar dashboard and the join flow
         can be demoed end-to-end without a live institution.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-02
Input:  A sandbox lab_info root (``$WIGAMIG_LAB_INFO_ROOT`` or ``--root``).
        REFUSES to run against the real ``~/.wigamig/lab_info`` unless
        ``--force`` is passed, so it can never clobber a live centre.
Output: A populated centre from the lab-meeting whiteboard:
          <root>/centre.md              (mayor @tbrowne + server profile)
          <root>/_registry.yaml         (EM core + MM/MH labs + registrars)
          <root>/cores/em/...           (Elisios lead; Hagar, Tim)
          <root>/labs/mm/...            (Yubing PI; Mohammad)
          <root>/labs/mh/...            (Harry PI; Mike)
          <root>/join_requests/*.md     (two pending, for a non-empty queue)
          <sibling>/hosts.yaml          (lab-server, sancty, biocore)

Unlike ``seed_two_labs.py`` (which seeds only labs and wipes the
registrar registry), this seeds the whole administrative layer via the
public API: ``centre_init.init_centre`` + ``registrar.create_lab`` /
``create_core`` + ``hosts.add`` + ``join_requests.file_request``.

Idempotent: re-running wipes only the seeded sandbox tree and rebuilds
it. It never writes the per-machine ``~/.wigamig/registrar`` sentinel
(``write_sentinel=False``) so it leaves your real identity alone.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import yaml

from wigamig.core import centre_init, hosts, join_requests
from wigamig.core import registrar as R


# ---------------------------------------------------------------------------
# The world (from the lab-meeting whiteboard)
# ---------------------------------------------------------------------------

CENTRE = {
    "name": "Demo Bioconvergence Centre",
    "institution": "Demo University",
    "unique_name": "demo",
    "founding_mayor": "@tbrowne",
    "slack_workspace": "T0DEMO000",
    "github_org": "wigamig-demo",
    "server_host": "lab-server.demo.edu",
    "server_account": "wigamig",
    "cc_install_path": "/opt/claude",
    "obsidian_vault": "/mayor/obsidian",
    "mayor_root": "/mayor/wigamig",
    "public_hub": "github.com/hallettmiket/wigamig_public#demo",
    "raw_root": "/data/lab_vm/raw",
    "refined_root": "/data/lab_vm/refined",
}

# kind: "core" | "lab"; leader is the PI / core-lead handle.
GROUPS = [
    {
        "kind": "core",
        "name": "em",
        "display_name": "EM Core",
        "leader": "@elisios",
        "leader_full_name": "Elisios",
        "members": [("@hagar", "Hagar"), ("@tim", "Tim")],
    },
    {
        "kind": "lab",
        "name": "mm",
        "display_name": "MM Lab",
        "leader": "@yubing",
        "leader_full_name": "Yubing",
        "members": [("@mohammad", "Mohammad")],
    },
    {
        "kind": "lab",
        "name": "mh",
        "display_name": "MH Lab",
        "leader": "@harry",
        "leader_full_name": "Harry",
        "members": [("@mike", "Mike")],
    },
]

# name → (kind, ssh_host). Machines column of the whiteboard.
MACHINES = [
    ("lab-server", "ssh", "lab-server.demo.edu"),
    ("sancty", "ssh", "sancty.demo.edu"),
    ("biocore", "ssh", "biocore.demo.edu"),
]

# Pending join requests so the /registrar queue is non-empty for demos.
PENDING_JOINS = [
    {
        "kind": "lab",
        "requester_email": "newpi@demo.edu",
        "proposed_name": "newlab",
        "proposed_pi": "@newpi",
        "institution_affiliation": "Demo University",
        "justification": "New wet-lab joining the centre; wants a project repo + Slack.",
    },
    {
        "kind": "pi",
        "requester_email": "visitor@other.edu",
        "proposed_name": "visitor",
        "proposed_pi": "@visitor",
        "institution_affiliation": "Other University",
        "justification": "External collaborator requesting read access to a shared SEA.",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_member(handle: str, full_name: str, group_name: str) -> str:
    """Minimal member file matching the shape create_lab writes for the PI."""
    meta = {
        "handle": handle if handle.startswith("@") else f"@{handle}",
        "full_name": full_name,
        "role": "staff",
        "status": "active",
        "lab": group_name,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip()
    at = handle if handle.startswith("@") else f"@{handle}"
    return f"---\n{yaml_text}\n---\n\n# {at}\n"


def _resolve_env(root: str | None) -> dict[str, str]:
    """Build a sandbox env dict: pins lab_info + a sibling hosts.yaml so a
    seed never leaks host rows into the real ~/.wigamig/hosts.yaml."""
    env = dict(os.environ)
    if root:
        env["WIGAMIG_LAB_INFO_ROOT"] = root
    lab_info = env.get("WIGAMIG_LAB_INFO_ROOT")
    if lab_info:
        env.setdefault(
            "WIGAMIG_HOSTS_FILE", str(Path(lab_info).parent / "hosts.yaml")
        )
    return env


def _guard(env: dict[str, str], force: bool) -> Path:
    """Refuse to seed over the real centre unless --force."""
    target = R.lab_info_root(env)
    real = Path.home() / ".wigamig" / "lab_info"
    if target.resolve() == real.resolve() and not force:
        raise SystemExit(
            f"refusing to seed the real centre at {target}.\n"
            "Set WIGAMIG_LAB_INFO_ROOT to a sandbox (e.g. /tmp/wgm/lab_info) "
            "or pass --force if you really mean it."
        )
    return target


def _wipe(target: Path, env: dict[str, str]) -> None:
    """Idempotency: remove the seeded tree (safe — guarded to a sandbox)."""
    for sub in ("cores", "labs", "join_requests", "collaborations"):
        shutil.rmtree(target / sub, ignore_errors=True)
    for f in ("centre.md", "_registry.yaml"):
        (target / f).unlink(missing_ok=True)
    hosts_file = env.get("WIGAMIG_HOSTS_FILE")
    if hosts_file:
        Path(hosts_file).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed(root: str | None = None, *, force: bool = False) -> Path:
    env = _resolve_env(root)
    target = _guard(env, force)
    target.mkdir(parents=True, exist_ok=True)
    _wipe(target, env)

    # 1. Centre profile + mayor-as-first-registrar (no real-sentinel write).
    centre_init.init_centre(env=env, write_sentinel=False, **CENTRE)
    print(f"[1/4] centre initialised: {CENTRE['name']} (@{CENTRE['founding_mayor'].lstrip('@')} mayor)")

    # 2. Cores + labs with their leaders, then non-leader members.
    for g in GROUPS:
        if g["kind"] == "core":
            entry = R.create_core(
                name=g["name"], display_name=g["display_name"],
                leader_handle=g["leader"], leader_full_name=g["leader_full_name"],
                slack_workspace=CENTRE["slack_workspace"],
                github_org=CENTRE["github_org"],
                institution=CENTRE["institution"], env=env,
            )
        else:
            entry = R.create_lab(
                name=g["name"], display_name=g["display_name"],
                pi_handle=g["leader"], pi_full_name=g["leader_full_name"],
                slack_workspace=CENTRE["slack_workspace"],
                github_org=CENTRE["github_org"],
                institution=CENTRE["institution"], env=env,
            )
        members_dir = Path(entry.lab_mgmt_path) / "members"
        members_dir.mkdir(parents=True, exist_ok=True)
        for handle, full_name in g["members"]:
            (members_dir / f"{handle.lstrip('@')}.md").write_text(
                _render_member(handle, full_name, g["name"]), encoding="utf-8"
            )
        roster = ", ".join([g["leader"]] + [h for h, _ in g["members"]])
        print(f"[2/4] {g['kind']} {g['name']}: {roster}")

    # 3. Machines.
    for name, kind, ssh_host in MACHINES:
        try:
            hosts.add(hosts.Host(name=name, kind=kind, ssh_host=ssh_host,
                                 description=f"seeded demo host ({name})"), env=env)
        except hosts.HostAlreadyExists:
            pass
    print(f"[3/4] machines: {', '.join(n for n, _, _ in MACHINES)}")

    # 4. Pending join requests (non-empty registrar queue).
    for jr in PENDING_JOINS:
        join_requests.file_request(env=env, **jr)
    print(f"[4/4] {len(PENDING_JOINS)} pending join requests queued")

    print(f"\nDemo centre ready at {target}")
    print("Browse it:  wigamig centre-status   (with the same WIGAMIG_LAB_INFO_ROOT)")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed a demo wigamig centre.")
    ap.add_argument("--root", help="lab_info root to seed (else $WIGAMIG_LAB_INFO_ROOT)")
    ap.add_argument("--force", action="store_true",
                    help="allow seeding the real ~/.wigamig/lab_info (dangerous)")
    args = ap.parse_args()
    seed(args.root, force=args.force)


if __name__ == "__main__":
    main()
