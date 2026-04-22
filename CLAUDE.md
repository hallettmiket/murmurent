# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What wigamig Is

wigamig is a multi-project, multi-group agentic AI infrastructure for a bioconvergence research center. It extends [generic_cc](https://github.com/hallettmiket/generic_cc) from a single-lab configuration hub into a three-tier shared commons that supports shifting collaborations across research groups — not a fixed pipeline, but a village where different groups (g1, g2, g3, …) team up on different projects at different times.

The village metaphor is intentional: Lab-in-the-Loop (LitL) drug discovery is one choreography that can happen here, but the center also runs imaging, clinical-data, and method-development choreographies in parallel, each involving different subsets of groups.

## Architecture: Three Tiers

### Tier 1 — The Commons (`~/.claude/` via symlinks to this repo)

Center-wide agents and rules available to every project regardless of discipline. These map to the seven generic_cc residents plus any center-level additions:

- **Oracle** — cross-project institutional memory (`~/.claude/agent-memory/oracle/MEMORY.md`)
- **Bookworm** — literature and database integration
- **Blacksmith** — computation, modeling, feature engineering
- **Artist** — visualization and communication
- **Adversary** — methodology audit and peer review
- **Conscience** — equity, bias, and EDI oversight
- **Saul Goodman** — patent intelligence and freedom-to-operate

Commons agents are maintained here and distributed via `scripts/setup.sh`, just as in generic_cc.

### Tier 2 — The Guilds (`guilds/<group-name>/agents/`)

Discipline-specific agents owned by individual research groups or shared cores. A chemistry group might maintain a `MEDCHEM` agent; an imaging core a `SEGMENTER`; a clinical group a `COHORT` agent. Guild agents are version-controlled in this repo under `guilds/` and symlinked into group-level Claude configs.

```
guilds/
├── chemistry/
│   └── agents/
│       └── medchem.md
├── imaging/
│   └── agents/
│       └── segmenter.md
└── clinical/
    └── agents/
        └── cohort.md
```

### Tier 3 — Project Namespaces (`projects/<project-name>/`)

Each active collaboration gets a project directory that composes whichever commons + guild agents it needs, plus any project-specific agents. The project's CLAUDE.md names which groups are collaborating and which choreography pattern applies.

```
projects/
└── dcis_imaging_genomics/       # g2 + g3 + g5 collaboration
    ├── CLAUDE.md                # names groups, choreography, data governance rules
    └── agents/
        └── project_specific.md  # override or extend commons agents
```

## Choreography Catalog

Each recurring collaboration pattern is a named choreography. Document new ones here as they emerge.

| Name | Description | Key Agents |
|------|-------------|------------|
| `drug_discovery_litl` | Dry-lab LitL: design → audit → wet-lab closure | Blacksmith, Adversary, Bookworm, Saul Goodman |
| `clinical_cohort` | Cohort analysis with data governance | Cohort (guild), Conscience, Adversary |
| `method_benchmarking` | Tool/method development and comparison | Blacksmith, Adversary, Artist |
| `imaging_phenotyping` | Image analysis with phenotypic readouts | Segmenter (guild), Blacksmith, Artist |

## Setup

```bash
# Install commons layer (symlinks agents/ and rules/ into ~/.claude/)
bash scripts/setup.sh

# Launch the monitoring dashboard (Conductor + agent windows)
bash scripts/start_agents.sh [project_directory]
```

The setup script follows the same symlink pattern as generic_cc: agent definitions are version-controlled here; agent memory stays local in `~/.claude/agent-memory/`.

## Data Governance Between Groups

Because groups collaborate in shifting combinations, Oracle instances are **per-project**, not center-wide. There is an explicit **publish step** when a finding should become shared center knowledge. This prevents accidental data cross-contamination between project A (g2+g3) and project B (g2+g4).

Each project CLAUDE.md must declare:
- Which groups are collaborating
- Which data sources are in scope
- Whether Oracle memory for this project can be published to the center Oracle

## Inherited Conventions from generic_cc

Code style, data storage, documentation standards, and project structure conventions are inherited directly from the generic_cc `rules/` layer. Key points:

- **Versioning:** Integer suffixes, higher = newer (`file_1.csv`, `file_2.csv`)
- **Project layout:** `exp/1_name/`, `exp/2_name/` with a `run_all` entry point per experiment
- **Data locations:** Raw → `/data/lab_vm/raw/[project]/[experiment]/`; refined → `/data/lab_vm/refined/`
- **Python style:** `black`, `isort`, `snake_case`, `pathlib`, type hints
- **R style:** tidyverse, `<-` assignment, `|>` pipe, `snake_case`

## Slack Notifications

After every `git push`, post to `#claude-code` Slack channel via `mcp__slack__slack_post_message` with: repo name, branch, commit hash, commit message, and a one-line summary of changes.
