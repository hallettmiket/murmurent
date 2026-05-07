"""
Purpose: Seed the wigamig smoke-test tutorial. Phase 1 scope: create the
         ``hallett-lab-mgmt`` repo locally, create the matching private GitHub
         repo under ``hallettmiket``, populate member profile files, generate
         per-persona age key pairs, and scaffold empty subdirectories.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-06
Input: ``WIGAMIG_LAB_MGMT_REPO`` env var (default ``~/repos/hallett-lab-mgmt``);
       ``gh`` CLI authenticated against the ``hallettmiket`` org;
       ``age-keygen`` available on PATH.
Output: ``~/repos/hallett-lab-mgmt/`` populated with members/, keys/, inventory/,
        projects/, dashboards/, audit/, roles/, onboarding/ + an initial commit
        pushed to ``hallettmiket/hallett-lab-mgmt`` (created private if absent).
        Private age keys are saved outside the repo at
        ``~/.config/wigamig/keys/<handle>.age-private`` (mode 0600).

The script is idempotent: re-running it does not overwrite existing files,
duplicate the GitHub repo, or rotate keys. It is safe to invoke after partial
failures.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_ORG = "hallettmiket"
LAB_MGMT_NAME = "hallett-lab-mgmt"
DEFAULT_LAB_MGMT_PATH = Path("~/repos") / LAB_MGMT_NAME
DEFAULT_KEYS_DIR = Path("~/.config/wigamig/keys")
TODAY = "2026-05-06"


@dataclass(frozen=True)
class Persona:
    """One of the four fake tutorial personas."""

    handle: str
    full_name: str
    role: str
    status: str
    certifications: list[str]


PERSONAS: tuple[Persona, ...] = (
    Persona(
        handle="mike",
        full_name="Mike Hallett (PI, fake tutorial persona)",
        role="pi",
        status="active",
        certifications=["TCPS_2:2030-12-31", "TOTP:enrolled", "signing_key:registered"],
    ),
    Persona(
        handle="allie",
        full_name="Allie (postdoc, fake tutorial persona)",
        role="postdoc",
        status="active",
        certifications=["TCPS_2:2027-06-15", "TOTP:enrolled", "signing_key:registered"],
    ),
    Persona(
        handle="bob",
        full_name="Bob (senior PhD, fake tutorial persona)",
        role="student",
        status="active",
        # TCPS 2 about to expire in 30 days from TODAY -> 2026-06-05.
        certifications=["TCPS_2:2026-06-05", "TOTP:enrolled", "signing_key:registered"],
    ),
    Persona(
        handle="cassie",
        full_name="Cassie (junior PhD, fake tutorial persona)",
        role="student",
        status="active",
        # TCPS 2 missing on purpose.
        certifications=["TOTP:pending", "signing_key:pending"],
    ),
)

EMPTY_SUBDIRS: tuple[str, ...] = (
    "members",
    "keys",
    "inventory",
    "projects",
    "dashboards",
    "audit",
    "roles",
    "onboarding",
)


# ---------------------------------------------------------------------------
# Logging / printing
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    """Print a status line to stdout."""
    print(f"[seed] {message}", flush=True)


def warn(message: str) -> None:
    """Print a warning line to stderr."""
    print(f"[seed][warn] {message}", file=sys.stderr, flush=True)


def fail(message: str) -> None:
    """Print an error and exit with code 1."""
    print(f"[seed][error] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def lab_mgmt_root() -> Path:
    """Resolve the lab-management repo root, honouring ``WIGAMIG_LAB_MGMT_REPO``."""
    return Path(os.environ.get("WIGAMIG_LAB_MGMT_REPO", DEFAULT_LAB_MGMT_PATH)).expanduser()


def keys_dir() -> Path:
    """Resolve the directory holding private age keys."""
    return Path(os.environ.get("WIGAMIG_KEYS_DIR", DEFAULT_KEYS_DIR)).expanduser()


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess. Returns the completed process; raises on non-zero ``check``."""
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def ensure_tool(name: str) -> None:
    """Exit with an error if ``name`` is not on PATH."""
    if shutil.which(name) is None:
        fail(f"required tool not found on PATH: {name}")


def gh_repo_exists(slug: str) -> bool:
    """Return True if ``<org>/<slug>`` already exists on GitHub."""
    result = subprocess.run(
        ["gh", "repo", "view", f"{GITHUB_ORG}/{slug}", "--json", "name"],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Filesystem scaffolding
# ---------------------------------------------------------------------------


def write_text_idempotent(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` if it does not already exist. Return True if written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def scaffold_lab_mgmt(repo_root: Path) -> None:
    """Create the lab-management repo directory layout and README."""
    repo_root.mkdir(parents=True, exist_ok=True)
    for sub in EMPTY_SUBDIRS:
        sub_path = repo_root / sub
        sub_path.mkdir(parents=True, exist_ok=True)
        gitkeep = sub_path / ".gitkeep"
        if not gitkeep.exists() and not any(sub_path.iterdir()):
            gitkeep.write_text("", encoding="utf-8")

    readme = repo_root / "README.md"
    write_text_idempotent(
        readme,
        (
            f"# {LAB_MGMT_NAME}\n\n"
            "Lab-management repo for the Hallett group, seeded by the wigamig "
            "tutorial smoke-test (phase 1).\n\n"
            "Holds member profiles, public age keys, inventory, project registry, "
            "dashboards, audit logs, role registry, and onboarding profiles.\n\n"
            "All content here is **fake** — no real PHI, no real credentials.\n"
        ),
    )

    gitignore = repo_root / ".gitignore"
    write_text_idempotent(
        gitignore,
        ".DS_Store\n*.age-private\n",
    )


def write_member_profiles(repo_root: Path, personas: Iterable[Persona]) -> None:
    """Write ``members/<handle>.md`` for each persona (idempotent)."""
    for persona in personas:
        path = repo_root / "members" / f"{persona.handle}.md"
        if path.exists():
            log(f"member profile exists: {path.name}")
            continue
        cert_lines = "\n".join(f"  - {c}" for c in persona.certifications)
        content = (
            "---\n"
            f"handle: '@{persona.handle}'\n"
            f"full_name: {persona.full_name!r}\n"
            f"role: {persona.role}\n"
            f"status: {persona.status}\n"
            "certifications:\n"
            f"{cert_lines}\n"
            f"created: {TODAY}\n"
            "---\n\n"
            f"# @{persona.handle}\n\n"
            f"Profile for the fake tutorial persona **@{persona.handle}**.\n\n"
            "Edit this file to record interests, current projects, and any\n"
            "non-credentialing context. All compliance state is in the\n"
            "`certifications:` frontmatter.\n"
        )
        write_text_idempotent(path, content)
        log(f"wrote {path}")


# ---------------------------------------------------------------------------
# Age key generation
# ---------------------------------------------------------------------------


def generate_age_key_pair(handle: str, repo_root: Path) -> None:
    """Generate a placeholder age key pair for ``handle`` if not already present.

    Public key committed to ``<lab-mgmt>/keys/<handle>.age``;
    private key written outside the repo at
    ``$WIGAMIG_KEYS_DIR/<handle>.age-private`` (mode 0600).
    """
    public_path = repo_root / "keys" / f"{handle}.age"
    private_path = keys_dir() / f"{handle}.age-private"

    if public_path.exists() and private_path.exists():
        log(f"age key already present for @{handle}")
        return
    if public_path.exists() ^ private_path.exists():
        warn(
            f"@{handle}: only one of public/private age key exists "
            f"({public_path}, {private_path}); regenerating both"
        )
        public_path.unlink(missing_ok=True)
        private_path.unlink(missing_ok=True)

    keys_dir().mkdir(parents=True, exist_ok=True)
    # age-keygen refuses to overwrite; ensure the destination does not exist.
    private_path.unlink(missing_ok=True)

    result = subprocess.run(
        ["age-keygen", "-o", str(private_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    # age-keygen writes the public key to stderr in the form "Public key: age1...".
    # Some versions also write it as a comment in the file; parse from stderr first.
    public_key: str | None = None
    for line in (result.stderr or "").splitlines():
        if line.lower().startswith("public key:"):
            public_key = line.split(":", 1)[1].strip()
            break
    if public_key is None:
        for line in private_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# public key:"):
                public_key = line.split(":", 1)[1].strip()
                break
    if not public_key:
        fail(f"could not determine public key for @{handle}; check age-keygen output")

    private_path.chmod(0o600)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        (
            f"# wigamig age public key for @{handle} (fake tutorial persona)\n"
            f"# generated {TODAY}\n"
            f"{public_key}\n"
        ),
        encoding="utf-8",
    )
    log(f"generated age key for @{handle} -> {public_path.name}")


# ---------------------------------------------------------------------------
# Git + GitHub
# ---------------------------------------------------------------------------


def ensure_git_initialised(repo_root: Path) -> None:
    """Initialise the lab-mgmt repo as a git repo on ``main`` if not already."""
    if (repo_root / ".git").exists():
        return
    run(["git", "init", "-b", "main"], cwd=repo_root)


def has_uncommitted_changes(repo_root: Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        check=True,
        text=True,
        capture_output=True,
    )
    return bool(result.stdout.strip())


def has_any_commits(repo_root: Path) -> bool:
    """Return True if the repo already has at least one commit on the current branch."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(repo_root),
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def stage_and_commit(repo_root: Path, message: str) -> bool:
    """Stage tracked + new files (excluding age-private) and commit if there's anything."""
    run(["git", "add", "-A"], cwd=repo_root)
    # ``-A`` respects the .gitignore we wrote, so private keys never enter the index.
    if not has_uncommitted_changes(repo_root) and has_any_commits(repo_root):
        return False
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(repo_root),
        check=True,
        text=True,
        capture_output=True,
    )
    if not result.stdout.strip():
        return False
    run(["git", "commit", "-m", message], cwd=repo_root)
    return True


def ensure_github_repo(slug: str) -> None:
    """Create ``<org>/<slug>`` private on GitHub if it does not exist."""
    if gh_repo_exists(slug):
        log(f"github.com/{GITHUB_ORG}/{slug} already exists; skipping create")
        return
    run(
        [
            "gh",
            "repo",
            "create",
            f"{GITHUB_ORG}/{slug}",
            "--private",
            "--description",
            "Hallett group lab-management repo (wigamig tutorial smoke-test)",
            "--confirm",
        ],
        check=False,
    )


def ensure_remote_and_push(repo_root: Path, slug: str) -> None:
    """Configure the ``origin`` remote and push ``main`` (if there's anything to push)."""
    remote_url = f"git@github.com:{GITHUB_ORG}/{slug}.git"
    existing = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_root),
        check=False,
        text=True,
        capture_output=True,
    )
    if existing.returncode != 0:
        run(["git", "remote", "add", "origin", remote_url], cwd=repo_root)
    elif existing.stdout.strip() != remote_url:
        run(["git", "remote", "set-url", "origin", remote_url], cwd=repo_root)

    if not has_any_commits(repo_root):
        warn("no commits yet; skipping push")
        return
    run(["git", "push", "-u", "origin", "main"], cwd=repo_root, check=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip the GitHub create/push step (for local-only smoke testing).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    ensure_tool("git")
    ensure_tool("age-keygen")
    if not args.skip_github:
        ensure_tool("gh")

    repo_root = lab_mgmt_root()
    log(f"lab-mgmt repo root: {repo_root}")
    log(f"private age key dir: {keys_dir()}")

    scaffold_lab_mgmt(repo_root)
    write_member_profiles(repo_root, PERSONAS)
    for persona in PERSONAS:
        generate_age_key_pair(persona.handle, repo_root)

    # Make sure the keys/ directory at least has a README so the public-key
    # files committed alongside it remain discoverable.
    keys_readme = repo_root / "keys" / "README.md"
    write_text_idempotent(
        keys_readme,
        (
            "# keys/\n\n"
            "Public age keys for group members. Private keys are stored outside the repo at\n"
            "`~/.config/wigamig/keys/<handle>.age-private` (mode 0600).\n\n"
            "All keys here are placeholders for the wigamig tutorial smoke-test.\n"
        ),
    )

    ensure_git_initialised(repo_root)
    committed = stage_and_commit(repo_root, "phase-1 seed: lab-management scaffold + members")
    if committed:
        log("committed initial scaffold")
    else:
        log("no new changes to commit")

    if args.skip_github:
        log("skipping github (--skip-github)")
        return 0

    ensure_github_repo(LAB_MGMT_NAME)
    ensure_remote_and_push(repo_root, LAB_MGMT_NAME)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
