---
date: 2026-05-06
tags: [wigamig, prompt]
---

# Phase 2 prompt: Project, experiment, ingest

> Phase 2 of 5. Phase 1 has shipped: Python package, CLI skeleton, agent registry, core utilities, lab-mgmt repo with member files.
>
> Read first: `docs/implementation_prompt.md`, `docs/group_level.md`, `docs/cli_manual.md`, `docs/implementation_prompt_phase_1_foundation.md`.

## Goal

Members can create projects and experiments, ingest fake instrument data with the classification + review flow, and the raw-data guard hook prevents mutating raw on the simulated lab VM.

## Preconditions

- Phase 1 PR merged to `main` of `wigamig`
- `hallett-lab-mgmt` exists locally and on GitHub
- Member files for the four personas exist
- `gh` authenticated

## Deliverables

1. **Project commands** (functional in v1)
   - `wigamig project new <name> --charter <file> --members <list>` — scaffold local project repo (per the lab project structure: `exp/`, `src/`, `findings/`, `obsolete/`, `data/`, `seas/`, `deliberations/`); create GitHub repo `hallettmiket/<name>` private; register in `lab-mgmt/projects/<name>.md`
   - `wigamig project list` — projects user is a member of
   - `wigamig project describe <name>` — charter, MEMBERS, status, sensitivity badge
   - `wigamig project admit <name> <member>` — update MEMBERS, open PR
   - `wigamig project sensitivity <name> [--set <tier>]` — read or change sensitivity tier
   - CHARTER frontmatter validator: `sensitivity` required; `clinical` requires `reb_number`, `reb_expires`, `data_residency`

2. **Experiment commands**
   - `wigamig experiment new --project <p> --name <slug>` — scaffold `exp/<n>_<slug>/` with `README.md`, `run_all.py`, `notebook.md` template, `pages/`, `sketches/`, `data/`; create lab VM dirs at `$WIGAMIG_LAB_VM_ROOT/raw/<p>/<exp>/` and `refined/<p>/<exp>/`
   - `wigamig experiment list [--project <p>]`
   - `wigamig experiment ingest <project> <slug> <source>` — full classification + review + copy + chmod per design
   - `wigamig experiment status <project> <slug> --set <state>`

3. **Instrument profile** at `instruments/illumina-novaseq.yaml` per design (raw extensions: `fastq`, `fastq.gz`; derived patterns: `*thumbnail*`, `*qc.html*`, `*summary.pdf*`)

4. **Raw-data guard hook** at `src/wigamig/hooks/raw_guard.py`
   - Refuses Write/Edit/Bash/NotebookEdit mutating `$WIGAMIG_LAB_VM_ROOT/raw/`
   - Independent test harness piping fake JSON through stdin
   - Manual `~/.claude/settings.json` registration documented in a draft `TUTORIAL.md` snippet (full hook installer is phase 4)

5. **Fake data generator** at `scripts/fake_data.py`
   - Fake FASTQ files (random bases, valid `.fastq.gz` format)
   - Fake clinicopathology table CSV with clearly-fake OHIP strings (`0000-000-001`, `0000-000-002`, ...) and fake fields (sample_id, grade, ER, PR, age_at_diagnosis)
   - Fake compound table for `bbb_drug_screen`
   - Fake count matrix CSV (gene × cell)

6. **Seed script v2** extends v1
   - Creates `~/repos/dcis_sc_tutorial/` and `~/repos/bbb_drug_screen/` locally + on GitHub (private)
   - Charters with the right sensitivity tiers per umbrella prompt
   - All five experiments scaffolded with `notebook.md` in correct `status` / `analysis_status` states (per umbrella prompt's experiment table)
   - Fake data generated and placed in `$WIGAMIG_LAB_VM_ROOT/`

## Acceptance criteria

- [ ] `WIGAMIG_USER=allie wigamig project list` shows both projects
- [ ] `wigamig project describe dcis_sc_tutorial` shows clinical sensitivity, REB number, four members
- [ ] `wigamig experiment list --project dcis_sc_tutorial` shows the four experiments with their status
- [ ] `wigamig experiment ingest dcis_sc_tutorial 1_sample_qc <fresh-source-dir>` runs the classification + mandatory review prompt
- [ ] After ingest: raw chmod a-w; `notebook.md` `raw_data` and `checksums` populated
- [ ] Raw-data guard refuses an attempted modification of a raw file (test via the hook harness)
- [ ] PR opened on `hallettmiket/wigamig` from `feat/phase-2-projects`
- [ ] Both project repos exist on GitHub with seed content

## Deferred to phase 3

- Push mechanics
- SEA verbs
- Finalisation choreography
