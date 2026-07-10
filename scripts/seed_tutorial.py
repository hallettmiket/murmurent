"""
Purpose: Seed the wigamig smoke-test tutorial. Phase 1 scope: lab-mgmt repo +
         members + age keys. Phase 2 scope: also seed the two project repos
         (``dcis_sc_tutorial`` and ``bbb_drug_screen``) with charters,
         experiments, lab-VM dirs, and clearly-fake instrument data.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``WIGAMIG_LAB_MGMT_REPO`` env var (default ``~/repos/lab_mgmt``);
       ``WIGAMIG_LAB_VM_ROOT`` env var (default ``~/lab_vm/data``);
       ``gh`` CLI authenticated against the ``hallettmiket`` org;
       ``age-keygen`` available on PATH.
Output: ``~/repos/lab_mgmt/`` populated with members/, keys/, inventory/,
        projects/, dashboards/, audit/, roles/, onboarding/. Private age keys
        saved at ``~/.config/wigamig/keys/<handle>.age-private`` (mode 0600).
        ``~/repos/dcis_sc_tutorial/`` and ``~/repos/bbb_drug_screen/`` populated
        with the lab project layout, four + one experiments respectively,
        ``CHARTER.md``, ``MEMBERS``, and lab-VM raw + refined dirs scaffolded
        with fake data.

The script is idempotent: re-running it does not overwrite existing files,
duplicate GitHub repos, or rotate keys. It is safe to invoke after partial
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

# Make the wigamig package importable when running this script from a checkout
# without `pip install -e .` (e.g. inside the seed flow on a fresh machine).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_PATH = _REPO_ROOT / "src"
if _SRC_PATH.is_dir() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from murmurent.commands import experiment_cmd, project_cmd  # noqa: E402
from murmurent.core import deliberation, inventory, lab_vm  # noqa: E402
from murmurent.core import sea as sea_core  # noqa: E402
from murmurent.core.projects import find_project  # noqa: E402

# Importing the fake-data generator lets us call it without spawning a
# subprocess; the file lives next to this one.
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import fake_data  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_ORG = "hallettmiket"
LAB_MGMT_NAME = "lab_mgmt"
DEFAULT_LAB_MGMT_PATH = Path("~/repos") / LAB_MGMT_NAME
DEFAULT_KEYS_DIR = Path("~/.config/wigamig/keys")
TODAY = "2026-05-07"


# ---------------------------------------------------------------------------
# Project + experiment seed configuration (phase 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentSeed:
    """One experiment to scaffold inside a project repo."""

    slug: str
    lead: str
    status: str
    analysis_status: str


@dataclass(frozen=True)
class ProjectSeed:
    """One project to scaffold (repo + experiments + GH)."""

    name: str
    sensitivity: str
    lead: str
    members: tuple[str, ...]
    description: str
    choreography: str | None
    reb_number: str | None = None
    reb_expires: str | None = None
    data_residency: str | None = None
    experiments: tuple[ExperimentSeed, ...] = ()


PROJECT_SEEDS: tuple[ProjectSeed, ...] = (
    ProjectSeed(
        name="dcis_sc_tutorial",
        sensitivity="clinical",
        lead="@allie",
        members=("@mhallet", "@allie", "@bob", "@cassie"),
        description=(
            "Single-cell DCIS tutorial project for the wigamig smoke-test. All data "
            "is clearly fake: clinicopathology rows use OHIPs of the form "
            "0000-000-NNN, FASTQ files are random-base sequences, count matrices are "
            "uniform integers. Used to exercise the clinical-sensitivity controls "
            "(REB-bounded access, PHI hooks, raw-data guard) without touching real PHI."
        ),
        choreography="clinical_cohort",
        reb_number="WREM-2026-9999",
        reb_expires="2027-09-01",
        data_residency="ca",
        experiments=(
            ExperimentSeed("sample_qc", "@allie", "complete", "examined"),
            ExperimentSeed("alignment_count_matrix", "@bob", "running", "not_started"),
            ExperimentSeed("clustering", "@cassie", "planned", "not_started"),
            ExperimentSeed("clinical_associations", "@allie", "planned", "not_started"),
        ),
    ),
    ProjectSeed(
        name="bbb_drug_screen",
        sensitivity="standard",
        lead="@bob",
        members=("@mhallet", "@bob", "@allie"),
        description=(
            "Blood-brain-barrier drug-screen tutorial project for the wigamig "
            "smoke-test. All compound data is clearly fake (FAKE_CMP_NNNN). "
            "Used to exercise the drug-discovery LitL choreography."
        ),
        choreography="drug_discovery_litl",
        experiments=(ExperimentSeed("pharmacophore_alignment", "@bob", "complete", "concluded"),),
    ),
)


# ---------------------------------------------------------------------------
# Phase 3: SEA seed configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeaSeed:
    """One pre-seeded SEA per the umbrella prompt."""

    project: str
    id: int
    from_handle: str
    to_handle: str
    kind: str
    description: str
    state: str
    delivery: str | None = None
    decline_reason: str | None = None
    deliberation: str | None = None  # 'partial' | 'complete' | None


SEA_SEEDS: tuple[SeaSeed, ...] = (
    SeaSeed(
        project="dcis_sc_tutorial",
        id=1,
        from_handle="@allie",
        to_handle="@bob",
        kind="experiment",
        description="Re-generate count matrix with GRCh38.p14 + GENCODE 47",
        state="claimed",
    ),
    SeaSeed(
        project="dcis_sc_tutorial",
        id=2,
        from_handle="@bob",
        to_handle="@cassie",
        kind="analysis",
        description="UMAPs coloured by ER, PR, grade",
        state="requested",
    ),
    SeaSeed(
        project="dcis_sc_tutorial",
        id=3,
        from_handle="@allie",
        to_handle="@mhallet",
        kind="analysis",
        description="Review statistical assumptions in DE pipeline",
        state="complete",
        delivery="findings/de_pipeline_review.md",
        deliberation="partial",
    ),
    SeaSeed(
        project="dcis_sc_tutorial",
        id=4,
        from_handle="@cassie",
        to_handle="@allie",
        kind="analysis",
        description="Interpret cluster 7 marker genes - macrophages or DCs?",
        state="requested",
    ),
    SeaSeed(
        project="dcis_sc_tutorial",
        id=5,
        from_handle="@allie",
        to_handle="@bob",
        kind="analysis",
        description="scVI vs Harmony batch-correction comparison",
        state="declined",
        decline_reason="Out of scope for v1; revisit after baseline DE is finalised.",
    ),
    SeaSeed(
        project="bbb_drug_screen",
        id=10,
        from_handle="@bob",
        to_handle="@allie",
        kind="analysis",
        description="Pharmacophore alignment for compound set 3",
        state="concluded",
        delivery="findings/pharmacophore_alignment_set_3.md",
        deliberation="complete",
    ),
)


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
        handle="mhallet",
        full_name="Mike Hallett (PI, Western username)",
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
# Phase 2: project + experiment seeding
# ---------------------------------------------------------------------------


def seed_project(seed: ProjectSeed, *, skip_github: bool) -> Path:
    """Create the project repo (idempotent) and return its local path."""
    members_csv = ",".join(seed.members)
    log(f"seeding project {seed.name} ({seed.sensitivity})")
    summary = project_cmd.cmd_new(
        seed.name,
        charter_path=None,
        members_csv=members_csv,
        description=seed.description,
        sensitivity=seed.sensitivity,
        choreography=seed.choreography,
        reb_number=seed.reb_number,
        reb_expires=seed.reb_expires,
        data_residency=seed.data_residency,
        lead=seed.lead,
        skip_github=skip_github,
    )
    return summary.path


def seed_experiments(project: ProjectSeed) -> None:
    """Scaffold each experiment in ``project`` (idempotent)."""
    project_path = Path("~/repos").expanduser() / project.name
    exp_root = project_path / "exp"
    for exp in project.experiments:
        existing = [
            p for p in exp_root.glob("*_*") if p.is_dir() and p.name.split("_", 1)[1] == exp.slug
        ]
        if existing:
            log(f"experiment {project.name}/{existing[0].name} exists; skipping scaffold")
            _ensure_experiment_status(existing[0], exp)
            continue
        experiment_cmd.cmd_new(
            project.name,
            exp.slug,
            status=exp.status,
            analysis_status=exp.analysis_status,
            performer=[exp.lead],
        )


def _ensure_experiment_status(exp_dir: Path, target: ExperimentSeed) -> None:
    """Re-flip status on a previously-seeded experiment if it has drifted."""
    notebook = exp_dir / "notebook.md"
    if not notebook.is_file():
        return
    text = notebook.read_text(encoding="utf-8")
    needs_write = False
    for field, value in (("status", target.status), ("analysis_status", target.analysis_status)):
        for prefix in (f"{field}: ",):
            if f"\n{prefix}" in text:
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith(prefix) and line.strip() != f"{prefix.strip()} {value}":
                        lines[i] = f"{prefix}{value}"
                        needs_write = True
                text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if needs_write:
        notebook.write_text(text, encoding="utf-8")


def seed_fake_data(staging_root: Path) -> dict[str, Path]:
    """Generate fake instrument-export bundles into ``staging_root``.

    Returns a dict mapping bundle-name to the staging directory containing it.
    """
    import random

    rng = random.Random(20260507)
    seq_dir = staging_root / "dcis_sequencing"
    clin_dir = staging_root / "dcis_clinical"
    counts_dir = staging_root / "dcis_counts"
    bbb_dir = staging_root / "bbb_compounds"
    seq_dir.mkdir(parents=True, exist_ok=True)
    clin_dir.mkdir(parents=True, exist_ok=True)
    counts_dir.mkdir(parents=True, exist_ok=True)
    bbb_dir.mkdir(parents=True, exist_ok=True)
    fake_data.generate_dcis_sequencing(seq_dir, rng=random.Random(20260507))
    fake_data.generate_dcis_clinical(clin_dir, rng=random.Random(20260508))
    fake_data.generate_dcis_counts(counts_dir, rng=random.Random(20260509))
    fake_data.generate_bbb_compounds(bbb_dir, rng=random.Random(20260510))
    return {
        "dcis_sequencing": seq_dir,
        "dcis_clinical": clin_dir,
        "dcis_counts": counts_dir,
        "bbb_compounds": bbb_dir,
    }


def stage_data_into_lab_vm(bundles: dict[str, Path]) -> None:
    """Copy generated files directly into the lab-VM raw / refined trees.

    For the seed we don't go through ``wigamig experiment ingest`` because the
    interactive prompt would block the non-interactive script. We populate the
    lab-VM tree by hand so the smoke-test acceptance step can exercise ingest
    against a *fresh* source directory (`scripts/fake_data.py` regenerates it).
    """
    import shutil as _sh

    # Pre-stage some clinicopath/count data straight into refined as a stand-in
    # for already-completed runs (matches the experiment status table: 1_sample_qc
    # is `complete + examined`, 2_alignment_count_matrix is `running`, etc.).
    refined_qc = lab_vm.experiment_refined_dir("dcis_sc_tutorial", "1_sample_qc")
    refined_qc.mkdir(parents=True, exist_ok=True)
    for src in bundles["dcis_clinical"].iterdir():
        dest = refined_qc / src.name
        if not dest.exists():
            _sh.copy2(src, dest)

    refined_counts = lab_vm.experiment_refined_dir("dcis_sc_tutorial", "2_alignment_count_matrix")
    refined_counts.mkdir(parents=True, exist_ok=True)
    for src in bundles["dcis_counts"].iterdir():
        dest = refined_counts / src.name
        if not dest.exists():
            _sh.copy2(src, dest)

    refined_bbb = lab_vm.experiment_refined_dir("bbb_drug_screen", "1_pharmacophore_alignment")
    refined_bbb.mkdir(parents=True, exist_ok=True)
    for src in bundles["bbb_compounds"].iterdir():
        dest = refined_bbb / src.name
        if not dest.exists():
            _sh.copy2(src, dest)


# ---------------------------------------------------------------------------
# Phase 3: SEA + deliberation seeding
# ---------------------------------------------------------------------------


INVENTORY_SEEDS: tuple[dict[str, object], ...] = (
    {
        "name": "anti_cd31",
        "vendor": "FAKE Biolabs",
        "catalog_no": "FB-CD31-001",
        "lot": "AB-2026-04",
        "qty": 0.5,
        "unit": "mg",
        "expiry": "2027-03-01",
        "location": "freezer-A / shelf-2",
        "status": "in_stock",
        "protocols": ["[[src/protocols/ihc_panel_v1.md]]"],
    },
    {
        "name": "4_oht",
        "vendor": "FAKE Sigma",
        "catalog_no": "F-OHT-100MG",
        "lot": "2025-44",
        "qty": 12.0,
        "unit": "mg",
        "expiry": "2026-04-01",
        "location": "fridge-2 / shelf-1",
        "status": "expired",
    },
    {
        "name": "nebnext_kit",
        "vendor": "FAKE NEB",
        "catalog_no": "FN-NEXT-24",
        "lot": "L-26-009",
        "qty": 3.0,
        "unit": "rxn",
        "expiry": "2026-12-31",
        "location": "freezer-B / box-3",
        "status": "low",
        "protocols": ["[[src/protocols/library_prep_v2.md]]"],
    },
    {
        "name": "dapi",
        "vendor": "FAKE ThermoFisher",
        "catalog_no": "FT-DAPI-1ML",
        "lot": "T-26-101",
        "qty": 5.0,
        "unit": "mL",
        "expiry": "2028-01-15",
        "location": "fridge-1 / shelf-3",
        "status": "in_stock",
    },
    {
        "name": "dmso",
        "vendor": "FAKE Sigma",
        "catalog_no": "FS-DMSO-500ML",
        "lot": "2025-22",
        "qty": 2.0,
        "unit": "L",
        "expiry": "2030-01-01",
        "location": "shelf-RT-A",
        "status": "in_stock",
    },
    {
        "name": "livedead_stain",
        "vendor": "FAKE Invitrogen",
        "catalog_no": "FI-LD-1KIT",
        "lot": "L-26-204",
        "qty": 1.0,
        "unit": "kit",
        "expiry": "2026-05-21",  # ~14 days from TODAY
        "location": "freezer-A / shelf-1",
        "status": "in_stock",
    },
)


def seed_inventory() -> None:
    """Pre-populate the six umbrella-prompt inventory items (idempotent)."""
    for spec in INVENTORY_SEEDS:
        path = inventory.item_path(spec["name"])  # type: ignore[arg-type]
        if path.is_file():
            log(f"inventory item {spec['name']} exists; skipping")
            continue
        item = inventory.InventoryItem(
            name=spec["name"],  # type: ignore[arg-type]
            vendor=spec.get("vendor"),  # type: ignore[arg-type]
            catalog_no=spec.get("catalog_no"),  # type: ignore[arg-type]
            lot=spec.get("lot"),  # type: ignore[arg-type]
            qty=spec.get("qty"),  # type: ignore[arg-type]
            unit=spec.get("unit"),  # type: ignore[arg-type]
            expiry=spec.get("expiry"),  # type: ignore[arg-type]
            location=spec.get("location"),  # type: ignore[arg-type]
            status=spec.get("status", "in_stock"),  # type: ignore[arg-type]
            protocols=list(spec.get("protocols") or []),  # type: ignore[arg-type]
        )
        inventory.write_item(item)
        log(f"wrote inventory item {item.name} ({item.status})")


def seed_seas() -> None:
    """Pre-populate the six SEAs from the umbrella prompt."""
    for sd in SEA_SEEDS:
        repo = find_project(sd.project)
        if repo is None:
            warn(f"project {sd.project!r} not found; skipping SEA {sd.id}")
            continue
        path = sea_core.sea_path(repo, sd.id)
        if path.is_file():
            log(f"SEA {sd.project}/{sd.id} exists; skipping")
        else:
            new_sea = sea_core.Sea(
                id=sd.id,
                from_handle=sd.from_handle,
                to_handle=sd.to_handle,
                kind=sd.kind,
                description=sd.description,
                state="requested",
            )
            sea_core.write_sea(repo, new_sea)
            log(f"filed SEA {sd.project}/{sd.id}: {sd.from_handle} -> {sd.to_handle}")
        # Drive lifecycle into target state.
        sea = sea_core.parse_sea(path if path.is_file() else sea_core.sea_path(repo, sd.id))
        target_chain = _state_chain(sd)
        for next_state in target_chain:
            if sea.state == next_state:
                continue
            try:
                if next_state == "claimed":
                    sea_core.claim(sea)
                elif next_state == "complete":
                    sea_core.complete(sea, delivery=sd.delivery or "(seed)")
                elif next_state == "examined":
                    sea_core.mark_examined(sea)
                elif next_state == "concluded":
                    sea_core.mark_concluded(sea)
                elif next_state == "declined":
                    sea_core.decline(sea, reason=sd.decline_reason or "(seed)")
            except sea_core.SeaTransitionError:
                continue
        sea_core.write_sea(repo, sea)
        if sd.deliberation == "partial":
            _ensure_partial_deliberation(repo, sd)
        elif sd.deliberation == "complete":
            _ensure_complete_deliberation(repo, sd)


def _state_chain(sd: SeaSeed) -> list[str]:
    """Return the lifecycle path needed to land at ``sd.state``."""
    if sd.state == "requested":
        return []
    if sd.state == "claimed":
        return ["claimed"]
    if sd.state == "complete":
        return ["claimed", "complete"]
    if sd.state == "examined":
        return ["claimed", "complete", "examined"]
    if sd.state == "concluded":
        return ["claimed", "complete", "examined", "concluded"]
    if sd.state == "declined":
        return ["declined"]
    return []


def _ensure_partial_deliberation(repo, sd: SeaSeed) -> None:
    delib_path = deliberation.deliberation_path(repo, "sea", str(sd.id))
    if delib_path.is_file():
        return
    delib_path.parent.mkdir(parents=True, exist_ok=True)
    delib_path.write_text(
        deliberation.render_deliberation(
            scope="sea",
            target=str(sd.id),
            operational_status="complete",
            analysis_status="examined",
            examined_at=TODAY,
        ),
        encoding="utf-8",
    )
    log(f"wrote partial deliberation for SEA {sd.id}")


def _ensure_complete_deliberation(repo, sd: SeaSeed) -> None:
    delib_path = deliberation.deliberation_path(repo, "sea", str(sd.id))
    if delib_path.is_file():
        return
    delib_path.parent.mkdir(parents=True, exist_ok=True)
    text = deliberation.render_deliberation(
        scope="sea",
        target=str(sd.id),
        operational_status="complete",
        analysis_status="concluded",
        examined_at=TODAY,
        concluded_at=TODAY,
    )
    text = text.replace(
        "_(filled in during conclude — claim, partial findings, explicit non-consensus, artefact reference, or next steps)_",
        f"Squad finalised SEA {sd.id}: {sd.description}. See {sd.delivery}.",
        1,
    )
    delib_path.write_text(text, encoding="utf-8")
    log(f"wrote complete deliberation for SEA {sd.id}")


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
    parser.add_argument(
        "--skip-projects",
        action="store_true",
        help="Skip the phase-2 project + experiment seeding.",
    )
    parser.add_argument(
        "--fake-data-staging",
        type=Path,
        default=Path("~/lab_vm/staging/fake_instrument_export").expanduser(),
        help="Where to drop the generated fake instrument-export bundles.",
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
        log("skipping github (--skip-github) for lab-mgmt")
    else:
        ensure_github_repo(LAB_MGMT_NAME)
        ensure_remote_and_push(repo_root, LAB_MGMT_NAME)

    if not args.skip_projects:
        log("seeding projects + experiments")
        for seed in PROJECT_SEEDS:
            seed_project(seed, skip_github=args.skip_github)
            seed_experiments(seed)
            project_dir = Path("~/repos").expanduser() / seed.name
            if has_uncommitted_changes(project_dir):
                run(["git", "add", "-A"], cwd=project_dir)
                run(
                    ["git", "commit", "-m", f"seed experiments for {seed.name}"],
                    cwd=project_dir,
                )
            if not args.skip_github:
                run(
                    ["git", "push", "-u", "origin", "main"],
                    cwd=project_dir,
                    check=False,
                )
        log(f"generating fake instrument-export bundles in {args.fake_data_staging}")
        bundles = seed_fake_data(args.fake_data_staging)
        log("staging fake data into the lab-VM refined tree (raw left empty for ingest demo)")
        stage_data_into_lab_vm(bundles)

        log("seeding inventory items")
        seed_inventory()
        log("seeding pre-populated SEAs + deliberation docs")
        seed_seas()
        for project_seed in PROJECT_SEEDS:
            project_dir = Path("~/repos").expanduser() / project_seed.name
            if has_uncommitted_changes(project_dir):
                run(["git", "add", "-A"], cwd=project_dir)
                run(
                    ["git", "commit", "-m", f"seed SEAs + deliberations for {project_seed.name}"],
                    cwd=project_dir,
                )
                if not args.skip_github:
                    run(
                        ["git", "push", "-u", "origin", "main"],
                        cwd=project_dir,
                        check=False,
                    )
        log("regenerating per-member dashboards")
        from murmurent.commands import dashboard_cmd  # noqa: PLC0415

        for path in dashboard_cmd.cmd_generate_all():
            log(f"wrote dashboard: {path}")

        # After project commits, push lab-mgmt one more time so the
        # `projects/` registry entries + dashboards reach origin.
        if not args.skip_github:
            committed = stage_and_commit(
                repo_root,
                "phase-5 seed: register projects + initial dashboards",
            )
            if committed:
                run(["git", "push", "-u", "origin", "main"], cwd=repo_root, check=False)
    else:
        log("skipping project seed (--skip-projects)")

    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
