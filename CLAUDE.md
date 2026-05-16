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

Oracles come in two tiers:

- **Personal Oracle** (one per user) — lives in the user's own Obsidian vault under `oracle/`. Every entry carries a `project:` frontmatter field so cross-project provenance stays explicit, but there's a single index per user, not a separate vault per project. Personal entries are never shared automatically.
- **Lab Oracle** (one per lab) — lives in `lab_mgmt/oracle/` in the lab-mgmt repo. Group-readable, version-controlled, reviewed before landing.

Moving a finding from personal → lab is an explicit **publish step** (`wigamig oracle publish <slug>` — see "Oracle workflow" below). This prevents accidental data cross-contamination between project A (g2+g3) and project B (g2+g4): the personal Oracle holds the working set; only what the user deliberately publishes ends up in the lab's shared memory.

Every Oracle entry — personal OR lab — must conform to the schema in [`rules/oracle_schema.md`](rules/oracle_schema.md): `project`, `sensitivity`, `tags`, `sources`, `date`, optional `related`. The schema is enforced at draft time by the Oracle agent itself.

Each project CLAUDE.md must declare:
- Which groups are collaborating
- Which data sources are in scope
- Whether findings from this project are eligible for the Lab Oracle (default: yes, unless the project carries `sensitivity: clinical` or `restricted`)

## Inherited Conventions from generic_cc

Code style, data storage, documentation standards, and project structure conventions are inherited directly from the generic_cc `rules/` layer. Key points:

- **Versioning:** Integer suffixes, higher = newer (`file_1.csv`, `file_2.csv`)
- **Project layout:** `exp/1_name/`, `exp/2_name/` with a `run_all` entry point per experiment
- **Data locations:** Raw → `/data/lab_vm/wigamig/raw/[project]/[experiment]/`; refined → `/data/lab_vm/wigamig/refined/`
- **Python style:** `black`, `isort`, `snake_case`, `pathlib`, type hints
- **R style:** tidyverse, `<-` assignment, `|>` pipe, `snake_case`

## Oracle workflow

Two tiers, one schema. See [`rules/oracle_schema.md`](rules/oracle_schema.md).

### Personal Oracle (one per user, lives in your Obsidian vault)

The `oracle` agent maintains `<vault>/oracle/` on your machine. Resolve the actual path with:

```bash
wigamig oracle path
```

Every entry must carry the required frontmatter (`title`, `date`, `project`, `sensitivity`, `tags`, `sources`). The agent refuses to write entries with missing fields.

### Lab Oracle (one per lab, lives in `lab_mgmt/oracle/`)

The `lab_oracle` agent is **read-only**. It surfaces what the whole lab has agreed to remember — entries promoted from individual personal Oracles after explicit user action.

### Promoting personal → lab

```bash
# In CC, ask the personal oracle to stage a draft:
#   "Oracle, stage 2026-05-16_chrm_p14 as a publish draft"
# That puts the file at <vault>/oracle/drafts/2026-05-16_chrm_p14.md

# Then from a terminal:
wigamig oracle vault-drafts                 # list staged drafts
wigamig oracle publish 2026-05-16_chrm_p14  # validates schema, refuses
                                            # clinical/restricted, copies to
                                            # lab_mgmt/oracle/, commits with
                                            # your handle
wigamig oracle publish 2026-05-16_chrm_p14 --push   # commit + push in one shot
```

The publish step **refuses entries with `sensitivity: clinical` or `restricted`** — those must stay personal. It also refuses if the lab already has an entry at the target path (you'd be silently overwriting peer-reviewed content).

### Search

Both tiers are searchable via the `wigamig-oracle` MCP server (registered by `wigamig install --hooks`). Tools: `oracle_search`, `oracle_get`, `oracle_list`. Filter by `project`, `tags`, `sensitivity`, or `kind` (personal | lab | both). See [agents/oracle.md](agents/oracle.md) and [agents/lab_oracle.md](agents/lab_oracle.md) for usage patterns.

## VSCode workflow

The wigamig repo ships a launcher + workspace config so VSCode opens in
a consistent 4-quadrant layout with live agent reporting.

### Opening the repo

```bash
scripts/open_wigamig.sh                   # opens wigamig itself
scripts/open_wigamig.sh ~/repos/<other>   # opens another repo with the same shell
```

The launcher (macOS only) enumerates displays via `AppKit.NSScreen`; if
a second monitor is attached, VSCode opens there, otherwise on the
laptop screen. Either way the window is sized to 80% of the chosen
display, centred. Subsequent opens restore VSCode's persisted layout —
**arrange the quadrants once and they stick**.

### Quadrant layout

| Pane | Contents |
|------|----------|
| TL | Claude Code (VSCode extension) |
| TR | Editor area |
| BL | tmux shell |
| BR | `tail -F ~/.wigamig/agents.log` — live subagent reporter |

Set this up once: open four terminals via `terminal.integrated.defaultLocation: editor` (already wired in `.vscode/settings.json`), drag them into a 2×2 split, run the right command in each, then leave the window arranged. VSCode persists editor-group state per folder.

### Title bar + chrome

`.vscode/settings.json` wires:
- `window.title` → `Wigamig — <repo>  ·  <active editor>  ·  <dirty>`
- `workbench.activityBar.location` → `end` (right side)
- `workbench.sideBar.location` → `right`
- `terminal.integrated.defaultLocation` → `editor`

VSCode has no native bold/large title font (that's OS chrome); the
text is what we can control.

### Live agent reporter (BR pane)

CC hooks in `.claude/settings.json` invoke `scripts/wigamig_log_agent_event.sh` on:
- `PreToolUse(Agent)` → writes `<agent>: starting — <description>` in a deterministic colour per agent
- `SubagentStop` → writes `<agent>: done`

The BR pane just runs `tail -F ~/.wigamig/agents.log`. Each agent's
colour is a hash of its name, so e.g. blacksmith is always cyan,
adversary always magenta — no per-session reshuffling.

**Known limit**: CC subagents return *one final message*, not a live
stream of their thinking. The reporter therefore shows agent start/end
boundaries, not granular progress. That's a CC architecture constraint,
not a missing feature.

## Slack Notifications

After every `git push`, post to `#claude-test` Slack channel (channel ID `C0B3D9DS6SE`) via `mcp__claude_ai_Slack__slack_send_message` with: repo name, branch, commit hash, commit message, and a one-line summary of changes. (Used to be `#claude-code` — moved 2026-05-12 because that channel got too noisy for non-dev members.)

Tool note: there are two Slack MCP servers wired up. Use `mcp__claude_ai_Slack__slack_send_message` — the bot for that integration has been invited to `#claude-test`. The other one (`mcp__slack__slack_post_message`) is a different bot identity that returns `not_in_channel` for this channel.
