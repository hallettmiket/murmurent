# Choreographies (work in progress)

!!! warning "Work in progress"
    Choreographies are an area of active development. The recipes and
    verbs described here document the intended design; several parts are
    not yet implemented.

A **choreography** is a recurring multi-actor workflow recipe: a
documented pattern for how a project, experiment, or SEA is conducted,
with which agents, in what order, producing what artefacts.

## Choreographies

A **choreography** is a recurring multi-actor pattern: a recipe for how a project (or experiment) is conducted, with which agents, in what order, producing what artefacts.

The CLAUDE.md already names four: `drug_discovery_litl`, `clinical_cohort`, `method_benchmarking`, `imaging_phenotyping`. Each is documented as a markdown skill at `murmurent/choreographies/<name>.md`:

```markdown
---
name: drug_discovery_litl
description: Dry-lab Lab-in-the-Loop drug discovery
agents: [blacksmith, adversary, bookworm, lawyer]
artefacts:
  - hypotheses.md
  - candidates.csv
  - audit.md
  - fto_report.md
success_criteria:
  - candidates with FTO > 0.7
  - cross-validated leakage check passed
---

# drug_discovery_litl

## Steps
1. Generate candidate hypotheses (blacksmith)
2. Audit for data leakage and confounding (adversary)
3. Cross-reference literature for prior art (bookworm)
4. Freedom-to-operate check (lawyer)
5. Produce a candidate list with confidence scores

## Required squad shape
- Project lead (designated by PI)
- 1+ blacksmith operators
- adversary_chair operator
- bookworm operator
- 1 lawyer operator (often shared with another project)
```

### Adoption

A project adopts a choreography by setting `choreography: <name>` in its `CHARTER.md` frontmatter. The skill then:

- Scaffolds the project squad with the required shape (warns if members are missing for required roles).
- Files the initial SEAs as a starter set on the request board.
- Configures the right bots on the project repo's GitHub Actions.
- Records the adoption as an event in the project's audit log.

### Skill interface

Choreography is invoked as a CC skill:

- `choreography:list`: show available choreographies in the Murmurent repo and any group-level additions.
- `choreography:apply <name> --to <project>`: scaffold a project against the recipe.
- `choreography:status <project>`: report how far the project has progressed against the recipe's expected steps; flag missing artefacts.

### Where choreographies live

- **Centre-level**: `murmurent/choreographies/*.md`. Available to every group.
- **Group-level**: group-specific patterns maintained by the group.
- **Project-level**: a project may declare a one-off choreography in its repo at `CHOREOGRAPHY.md`, useful for unique work.

## Knowledge and continuity verbs

The day-to-day verbs handle moment-to-moment work. The verbs in this section produce **durable artefacts** that members will rely on later: discussions, transferable skills, and frozen states for citation.

### `discuss`: record a discussion or decision

**Purpose:** Slack threads and lab meetings are ephemeral. Decisions made in them deserve a persistent, citable record.

**Mechanism:** a discussion is a markdown file at `<project repo>/discussions/<date>_<topic>.md` (or `<lab-mgmt-repo>/discussions/...` for group-wide topics). Two flavours:
- **Synchronous recap**: written after a meeting / Slack thread, summarising the conversation and recording any decision.
- **Asynchronous thread**: written first; members add comments over time via PRs to the discussion file. Optionally mirrored as a GitHub Discussion on the project repo; the file remains the canonical record.

**Required frontmatter:**

| Field | Type | Notes |
|---|---|---|
| `date` | ISO date | When the discussion happened (or started, for async) |
| `topic` | str | Short title |
| `participants` | list[str] | GitHub handles |
| `outcome` | enum | `decided` / `open` / `blocked` / `tabled` |
| `decision` | str | Free-text decision (when `outcome: decided`) |
| `links` | list[wikilink] | Related findings, charters, SEAs, experiments |

**CLI:**
- `murmurent discuss new --project <p> --topic <t> [--participants <list>]`: scaffold a file, open in editor.
- `murmurent discuss list [--project <p>] [--open]`: browse.
- `murmurent discuss close <id> --outcome <decided|open|blocked|tabled> [--decision <text>]`: set outcome.

**Authority:** any project member may file a discussion; only the project lead may close one with `outcome: decided`.

### `teach`: codify a skill or protocol

**Purpose:** make knowledge transferable. Students leave; their methods leave with them unless captured.

**Mechanism:** two artefact kinds, three scopes:
- **Protocol**: a lab procedure (wet or dry). Lives at `<project repo>/src/protocols/<name>.md` (project-scoped), `<murmurent-repo>/<group>/protocols/<name>.md` (group-scoped), or `<murmurent-repo>/protocols/<name>.md` (centre-scoped).
- **Skill**: a Claude Code-discoverable instruction set the model invokes by name. Lives at `<murmurent-repo>/<group>/skills/<name>.md` or `<murmurent-repo>/skills/<name>.md`.

Both share a templated body:

```
## Purpose
[one paragraph why]

## Inputs
[required inputs / preconditions]

## Steps
1. ...
2. ...

## Pitfalls
[common failure modes]

## Worked example
[one fully-worked example with concrete values]
```

**CLI:**
- `murmurent teach protocol --name <n> [--scope project|group|center] [--from-experiment <project> <experiment>]`: scaffold a protocol; with `--from-experiment`, extracts a draft from the experiment's notebook entry as a starting point.
- `murmurent teach skill --name <n> [--scope group|center]`: scaffold a skill file.
- `murmurent teach promote <name> --to <wider-scope>`: move an existing protocol or skill to a wider scope (project → group → centre).

**Authority:** any member may author at project scope; group lead promotes to group; PI promotes to centre.

### `freeze`: snapshot a project state

**Purpose:** reproducibility and citation. When a paper is submitted, a thesis is defended, or a grant is reviewed, the project's exact state at that moment must remain pointable-to even as the project keeps evolving.

**Mechanism:** a freeze creates an immutable snapshot consisting of three parts:
- **Git tag** on the project repo: `freeze/<purpose>-<YYYY-MM-DD>` (e.g. `freeze/paper-submission-2026-05-06`).
- **Manifest** at `<project repo>/freezes/<tag>.md`, recording: tag name, reason, repo SHA, project MEMBERS at the time, choreography in effect (if any), per-experiment list of `raw_data` and `refined_data` paths with SHA-256 per file.
- **Encrypted bundle** at `$MURMURENT_LAB_VM_ROOT/refined/<project>/freezes/<tag>.tar.age`: refined data tarballed and encrypted with `age` to current MEMBERS plus the lab archive key. Optionally also `<tag>-raw.tar.age` for full archival (`--include-raw`).

Freezes are immutable. Re-freezing under the same purpose produces a new dated tag, never overwrites.

**CLI:**
- `murmurent freeze <project> --purpose <text> [--include-raw]`: compute manifest, create tag, encrypt bundle.
- `murmurent freeze list <project>`: list past freezes with their purposes and dates.
- `murmurent freeze restore <project> <tag> [--to <path>]`: extract a freeze into a temp location for inspection. Never modifies the live project.

**Authority:** project lead initiates; PI approves via PR review on the manifest commit. The git tag is created only after PI approval (an `on: push` Action listens for `freeze/...` manifest merges and creates the tag).

**Performance note:** computing checksums on a project with many gigabytes of refined data takes time. The freeze command runs in the background by default and notifies on completion.

### Verbs not added to Murmurent

- **schedule**: not a Murmurent verb. Calendars (Google Calendar, iCal) handle scheduling; a `calendar` MCP lets agents read events. The dashboard's "upcoming" panel pulls from notebook `status: planned` frontmatter, SEA deadlines, and the calendar MCP.
- **transfer_role**: already designed in [Role transitions](#role-transitions). CLI: `murmurent role transfer`.
- **archive_project**: CLI: `murmurent project archive`.

## The finalisation choreography

After a SEA, experiment, or project's operational work is **complete**, the squad takes the result through the finalisation choreography, a deliberation choreography that produces a permanent record of what the result means. The choreography runs at each scope (SEA, experiment, project) with the same shape; what differs is what it integrates.

**Why this exists**: students often run experiments and move on without interpreting the result. The choreography is the structural pressure that makes "what does this mean?" a default step rather than an optional one. The dashboard makes outstanding finalisation visible.

### Two parallel tracks

A SEA, experiment, or project has two parallel state tracks:

- **Operational** (`status:`): `planned` → `running` → `complete | failed | inconclusive`. The work itself.
- **Analysis** (`analysis_status:`): `not_started` → `examined` → `concluded`. The deliberation about the work.

A failed experiment can be analytically concluded: we examined the failure, decided what it means, and moved on with that knowledge. Both tracks are visible on the dashboard; outstanding work in the analysis track is what the dashboard surfaces.

### Stages

**1. Complete (operational).** The work is done; the delivery exists. Reached by `murmurent sea complete <id>` (or by the experiment / project completing its operational lifecycle).

**2. Examine.** The squad's common agents weigh in on the result. Each produces a section in the deliberation document:

- **Bookworm**: literature support / contradiction; relevant prior work; missing citations.
- **Artist**: visualizations (tables of values with standard errors, comparisons to public datasets, figure drafts).
- **Adversary**: methodological critique (controls, sample size, confounders, statistical assumptions, leakage, did the assay actually measure what we think).
- **Blacksmith**: computational comparison to public datasets, optional GUI for inspection, replication checks.
- **Conscience**: framing concerns (EDID-relevant language, problematic categorisations).
- **Lawyer**: any IP / patent angle.

Bots run frozen versions for reproducibility. Triggered by `<scope> examine <id>`.

**3. Conclude.** The squad members engage with the agent contributions, write their own reflections, attempt a statement. The statement is flexible: it can be a clean claim, a list of partial findings, an explicit "no consensus" with member positions, an artefact reference (the gel image is the finding), or a "next steps" if the question can't yet be resolved. Triggered by `<scope> conclude <id>`.

The point is going through the ritual; the optional output is a finding.

### The deliberation document

The always-produced artefact of the choreography lives at:

- `<project repo>/deliberations/sea/<sea-id>.md`: SEA scope
- `<project repo>/deliberations/exp/<experiment>.md`: experiment scope
- `<project repo>/deliberations/project.md`: project scope (one per project)

Structure:

```markdown
---
scope: sea | experiment | project
target: <id>
operational_status: complete | failed | inconclusive
analysis_status: not_started | examined | concluded
examined_at: 2026-05-06
concluded_at: 2026-05-12
---

## Agent contributions
### Bookworm
...
### Adversary
...
### Artist
...
[etc.]

## Member reflections
### @the_pi
...
### @member_a
...

## Group oracle context
- Contradicts: [[oracle/findings/2025-11-12_efflux]]
- Extends: [[oracle/findings/2026-01-08_pin1]]
- Novel relative to existing knowledge.

## Attempted statement
[flexible: claim, partial findings, explicit non-consensus,
 artefact reference, or next steps]

## Caveats and dissent
- adversary: controls failed in 2/8 replicates (recorded as caveat)
- @member_b: dissents on the molecular interpretation; sees this as a phenocopy

## Approval log
- @member_a: approved 2026-05-12
- @member_b: approved with dissent 2026-05-12
- @the_pi (PI): approved 2026-05-13
```

Dissenting agent contributions and member positions live in `Caveats and dissent`: they travel with the artefact into the oracle if the deliberation is promoted to a finding.

### Multi-scope: same choreography, three levels

| Scope | Inputs | Output | Initiator |
|---|---|---|---|
| **SEA** | Delivery + agent contributions | SEA deliberation document; optional SEA finding | SEA squad lead |
| **Experiment** | All concluded SEAs under the experiment + notebook entry + data | Experiment deliberation document; optional experiment finding | Experiment squad lead (may differ from any SEA squad lead) |
| **Project** | All concluded experiments + charter + choreography in effect | Project deliberation document; optional project findings | Project lead, with PI |

At experiment scope, inputs include SEAs that did not reach consensus: unresolved SEAs feed forward as open questions for the experiment-level deliberation to integrate or set aside.

At project scope, finalisation typically aligns with paper / freeze / grant-submission moments. The project deliberation document is often the basis for a paper's introduction, discussion, and limitations sections.

### Promotion to findings

Only when the squad chooses to promote does a deliberation produce a finding:

- The squad lead extracts the agreed statement (claim + caveats + cross-references) into `<project repo>/findings/<scope>/<id>.md`.
- A PR with this addition merges to `main`.
- The merge Action auto-publishes to the group oracle (per [push mechanics](#push-mechanics-branches-prs-and-bots)).
- Each squad member's personal oracle receives a private copy at the same time.

If no consensus is promoted, the deliberation document still exists as a citable artefact in the project repo. It may be revisited as part of a higher-scope deliberation later.

### Verbs

| Verb | Effect | Authority |
|---|---|---|
| `<scope> examine <id>` | Triggers common agents to write their sections of the deliberation doc | Squad lead |
| `<scope> conclude <id> [--statement <path>]` | Closes the deliberation; optionally promotes a statement to a finding | Squad lead with squad approvals |
| `finalize <scope> <id>` | Umbrella: runs examine then conclude in one flow | Squad lead |
| `<scope> reopen <id>` | Re-opens a concluded deliberation (e.g. new evidence arrives) | Squad lead; PI sign-off for project scope |

`<scope>` ∈ `sea`, `experiment`, `project`.

### Authority by scope

- **SEA scope**: SEA squad initiates and concludes. PI present by default; may opt out with `--no-pi`.
- **Experiment scope**: experiment squad lead initiates. All SEA leads under the experiment are members. PI present.
- **Project scope**: project lead initiates. PI is always present: this is one of the defaults that does not allow `--no-pi`.

### Periodic curation shrinks

With front-door curation handled by this choreography, the `oracle_curator` role's periodic work shrinks to:

- **Cross-reference health**: when a new finding supersedes an old one, propagate the link.
- **Citation rot**: detect oracle entries citing entries that have since been superseded.
- **Tag drift**: re-tag entries as the group's tag vocabulary evolves.
- **Stranded deliberations**: deliberations that didn't promote a finding may, over time, become inputs to higher-scope deliberations. Curator surfaces these to relevant squads.

The weekly light touch becomes "review the cross-link health report" rather than "review every entry." Monthly deep cleans become rarer and shorter. The bulk of curation now happens by construction at each finalisation.
