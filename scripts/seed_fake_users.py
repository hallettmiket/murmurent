"""
Purpose: Seed /tmp with a fake murmurent data layout for the four tutorial
         personas (mhallet, allie, bob, cassie). Idempotent — safe to re-run.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-11
Input: None (all paths are constants below).
Output:
  /tmp/raw/            -- fake raw data directories per project
  /tmp/refined/        -- fake refined data directories per project
  /tmp/obsidian-lab/lab_oracle/
      lab-notebook/    -- daily notebook entries per user
      oracle/          -- placeholder oracle notes per user
"""

from __future__ import annotations

import datetime as _dt
import random
import textwrap
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

RAW_ROOT      = Path("/tmp/raw")
REFINED_ROOT  = Path("/tmp/refined")
VAULT_ROOT    = Path("/tmp/obsidian-lab/lab_oracle")
NOTEBOOK_ROOT = VAULT_ROOT / "lab-notebook"
ORACLE_ROOT   = VAULT_ROOT / "oracle"

PROJECTS = ["dcis_sc_tutorial", "bbb_drug_screen"]

USERS: dict[str, dict] = {
    "mhallet": {
        "full_name": "Mike Hallett",
        "projects": ["dcis_sc_tutorial", "bbb_drug_screen"],
        "role": "PI",
        "topics": ["single-cell DCIS", "drug screening", "bioconvergence"],
    },
    "allie": {
        "full_name": "Allie",
        "projects": ["dcis_sc_tutorial", "bbb_drug_screen"],
        "role": "postdoc",
        "topics": ["scRNA-seq analysis", "QC pipelines", "DCIS subtype classification"],
    },
    "bob": {
        "full_name": "Bob",
        "projects": ["dcis_sc_tutorial", "bbb_drug_screen"],
        "role": "senior PhD student",
        "topics": ["compound screening", "blood-brain barrier models", "ML features"],
    },
    "cassie": {
        "full_name": "Cassie",
        "projects": ["dcis_sc_tutorial"],
        "role": "junior PhD student",
        "topics": ["cell clustering", "trajectory analysis"],
    },
}

TODAY = _dt.date.today()
RNG = random.Random(20260511)


# ── Notebook entry templates ───────────────────────────────────────────────

NOTE_TEMPLATES = [
    """\
## Goals
- {goal_a}
- {goal_b}

## Progress
Spent most of the morning on {topic}. Made progress on the clustering step —
k=12 looks stable across bootstrap replicates (checked 20 random seeds).

## Blockers
Still waiting on the REB amendment approval before we can access the clinical covariates.

## Next
- Run the pipeline on the full cohort
- Update notebook.md for exp/3_clustering
""",
    """\
## Goals
- Review pull request for {goal_a}
- {goal_b}

## Progress
Finished the preliminary QC run. The knee-point plot looks clean; filtering at
500 genes/cell removes ~8 % of droplets. Will discuss with {colleague} tomorrow.

## Blockers
None today.

## Next
- Submit the SEA for the QC experiment
- Sync with PI on timeline
""",
    """\
## Goals
- {goal_a}

## Progress
{topic} — ran the clustering benchmark with three resolutions (0.2, 0.5, 0.8).
Resolution 0.5 gives the cleanest silhouette score (0.41). Will document in
the experiment notebook.

## Next
- Annotate cluster markers
- Push results to refined/dcis_sc_tutorial/3_clustering/
""",
]


def _random_note(handle: str, date: _dt.date) -> str:
    info = USERS[handle]
    topic = RNG.choice(info["topics"])
    colleagues = [h for h in USERS if h != handle]
    colleague = RNG.choice(colleagues)
    template = RNG.choice(NOTE_TEMPLATES)
    goals = RNG.sample(info["topics"], k=min(2, len(info["topics"])))
    goal_a = goals[0]
    goal_b = goals[-1]
    header = f"# {date.isoformat()} — {info['full_name']} ({info['role']})\n\n"
    body = template.format(
        goal_a=goal_a,
        goal_b=goal_b,
        topic=topic,
        colleague=colleague,
    )
    return header + body


# ── Raw / refined skeleton ─────────────────────────────────────────────────

def _seed_raw() -> None:
    for project in PROJECTS:
        proj_dir = RAW_ROOT / project
        proj_dir.mkdir(parents=True, exist_ok=True)
        readme = proj_dir / "README.md"
        if not readme.is_file():
            readme.write_text(
                f"# {project} — raw data\n\n"
                "This directory mirrors what would be delivered by the instrument core.\n"
                "Contents are placeholder files for the murmurent tutorial.\n",
                encoding="utf-8",
            )


def _seed_refined() -> None:
    for project in PROJECTS:
        for exp_slug in ["0_setup", "1_ingest", "2_qc", "3_clustering"]:
            exp_dir = REFINED_ROOT / project / exp_slug
            exp_dir.mkdir(parents=True, exist_ok=True)
            readme = exp_dir / "README.md"
            if not readme.is_file():
                readme.write_text(
                    f"# {project}/{exp_slug}\n\nFake refined output for the murmurent tutorial.\n",
                    encoding="utf-8",
                )
        # A couple of placeholder result files
        results = REFINED_ROOT / project / "2_qc"
        for fname in ["qc_summary.csv", "knee_plot.png"]:
            f = results / fname
            if not f.is_file():
                f.write_text(f"# placeholder {fname}\n", encoding="utf-8")


# ── Notebook ───────────────────────────────────────────────────────────────

def _seed_notebook() -> None:
    for handle, info in USERS.items():
        nb_dir = NOTEBOOK_ROOT / handle
        nb_dir.mkdir(parents=True, exist_ok=True)
        # Seed notebook entries for the past 14 days, skipping weekends randomly
        for offset in range(14, 0, -1):
            date = TODAY - _dt.timedelta(days=offset)
            # Skip some days to make the calendar look realistic
            if date.weekday() >= 5 and RNG.random() < 0.85:  # mostly skip weekends
                continue
            if date.weekday() < 5 and RNG.random() < 0.2:   # occasionally miss weekdays
                continue
            note_file = nb_dir / f"{date.isoformat()}.md"
            if not note_file.is_file():
                note_file.write_text(_random_note(handle, date), encoding="utf-8")


# ── Oracle placeholder ─────────────────────────────────────────────────────

def _seed_oracle() -> None:
    for handle in USERS:
        oracle_dir = ORACLE_ROOT / handle
        oracle_dir.mkdir(parents=True, exist_ok=True)
        memory_file = oracle_dir / "MEMORY.md"
        if not memory_file.is_file():
            info = USERS[handle]
            memory_file.write_text(
                f"# Oracle memory — @{handle}\n\n"
                f"- {info['full_name']} is a {info['role']} in the Hallett lab.\n"
                f"- Current projects: {', '.join(info['projects'])}.\n"
                f"- Research focus: {', '.join(info['topics'])}.\n",
                encoding="utf-8",
            )


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    _seed_raw()
    print(f"  raw/   → {RAW_ROOT}")
    _seed_refined()
    print(f"  refined/ → {REFINED_ROOT}")
    _seed_notebook()
    print(f"  notebooks → {NOTEBOOK_ROOT}")
    _seed_oracle()
    print(f"  oracle   → {ORACLE_ROOT}")
    print()
    print("Done. Access each user's dashboard with ?user=<handle>:")
    for handle in USERS:
        print(f"  http://127.0.0.1:8770/?user={handle}")


if __name__ == "__main__":
    main()
