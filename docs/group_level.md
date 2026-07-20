---
date: 2026-05-05
tags: [murmurent, design]
---

# Murmurent: Group-Level Design

> Working draft. Conversation between Mike Hallett and Claude Code, started 2026-05-05.
> Destined to become a Claude Code system prompt for group-level operations.
> Re-read in full before every edit; keep the document internally consistent.
> See companions: [[cli_manual]], [[diagrams]].
> Origin notes: [[Murmurent notes]].
>
> **⚠ Project model superseded (2026-07):** the project-birth flow described
> below (PI approval scaffolds a fresh repo + charter) predates the
> certificate-based model. Projects are now a set of *existing* repos +
> machines + cryptographically certified members, with the creator as lead:
> [project_intra.md](project_intra.md) is the source of truth.

## Taxonomy

The four-level taxonomy used throughout this document:

- **Project**: highest unit. Single **lead** (often the PI but removable). Spans one or more repos. Has a charter.
- **Repo**: a lab-convention repository (`~/repos/<name>/` with `exp/<n>_<slug>/` inside). One or more per project.
- **Experiment**: a unit of work in a repo (`exp/<n>_<slug>/`). Has a notebook entry.
- **SEA**: atomic, callable unit of service (Skill, Experiment-as-event, or Analysis). Multiple per experiment; sometimes free-standing.
- **Squad**: the subgroup that performs a project, experiment, or SEA. Has a lead and members. Nestable.

(History note: an earlier draft used "investigation" as the highest unit; that term has been replaced by "project". When reviewing older artefacts that still say "investigation", read it as "project".)

## Scope

Group-level only: one PI, multiple members. Center- and factory-level concerns are noted only where they constrain the group; they are not designed here.

Explicitly out of scope for this iteration:
- Shared agent brains (shared memory). Agents are defined once at the group level, but each person runs their own instance with their own memory.
- A full GUI. A thin CLI is sufficient until a concrete onboarding pain exists.

## Mental model

A **group** g consists of people p1...pn, usually with one PI. Members participate in **projects**. Each project:

- has a participant subset of the group (its MEMBERS)
- is supported by experiments (wet or dry), literature, observations, and other artefacts
- accumulates predominantly semi-structured data: markdown + YAML frontmatter, with structured DBs (e.g. SQLite) where schemas are hard

## Repos used by a group

A group operates across three classes of repo. Each plays a distinct role; scope should not be mixed across them.

- **Murmurent repo**: center-wide; holds the agent registry under `guilds/<group>/agents/` and the install tooling.
- **Lab-management repo**: group-scoped; holds the role registry (`roles/`), inventory (`inventory/`), audit logs, the project registry, and group-wide protocols. One per group.
- **Project repos**: project-scoped; one per active project. Holds `CHARTER.md`, `MEMBERS`, `exp/`, `src/`, `findings/`, etc. (the lab's standard project layout). Private to MEMBERS.

## Three layers within the group

1. **Agent registry**: definitions for every agent the group recognises, version-controlled in the Murmurent repo at `guilds/<group>/agents/`.
2. **Role registry**: group-level roles, each with cardinality (singleton / quota / open) and current operator(s). Lives in the lab-management repo. Only the PI mutates assignments.
3. **Workspaces**: each member's local Claude Code environment, with the agents they have chosen to install, free to evolve on their own machine (subject to the freeze cascade below).

## Agent classification: the freeze cascade

Each agent has a **default freeze flag** in the registry. The effective flag for any given invocation cascades through three levels:

1. **Registry default**: `frozen` or `personal`, set in the agent's frontmatter.
   - `frozen` for safety-critical agents whose drift would erode group consistency or compliance: `conscience`, `security_guard`, `adversary` when used in code review, anything that gates outgoing artefacts.
   - `personal` for stylistic agents where individual variation is acceptable: `artist`, often `bookworm`.
2. **Role override**: when an agent is run as part of a role, the role can override the default. Example: `bookworm` is `personal` by default; the `bookworm_curator` role overrides to `frozen` because the curator's output is consumed by the rest of the group.
3. **Bot pinning**: when the agent runs in a GitHub Actions context (or any other shared CI), it always runs `frozen`, regardless of the default or role flag. Bots write to shared artefacts; reproducibility forbids drift.

Effective flag = bot pin (if applicable) ∨ role override (if applicable) ∨ registry default.

The cascade is enforced by the install tooling and by the bot's workflow file (which references the registry version explicitly).

### Tool preferences (defaults + overrides)

Each agent's frontmatter may declare a `defaults` block listing the tools, libraries, formats, or styles the agent uses unless told otherwise:

```yaml
---
name: artist
freeze: personal
defaults:
  plotting: matplotlib
  figure_size: 8x6
  presentation: quarto
  colormap: viridis
---
```

#### Standardised vocabulary vs free-form

Some preferences are cross-cutting (multiple agents care): plotting library, figure size, citation style, prose style. Some are agent-specific (only one agent ever uses them): Zotero collection name, GPU id, patent jurisdictions.

**Cross-cutting fields use a controlled vocabulary** so a member can set them once and have every relevant agent honour the setting. The vocabulary is documented at `murmurent/preferences.md` and updated via PR (adding a field requires a brief justification: why does this need to be cross-cutting?).

| Field | Type | Used by |
|---|---|---|
| `language` | enum (`en`/`fr`/...) | all text-producing agents |
| `prose_style` | enum (`academic`/`terse`/`casual`) | all text-producing agents |
| `audience` | enum (`lab`/`domain-experts`/`lay`) | artist, conscience, bookworm |
| `plotting` | str (`matplotlib`/`seaborn`/`plotnine`/`altair`/...) | artist, blacksmith |
| `figure_size` | str (e.g. `8x6`) | artist, blacksmith |
| `colormap` | str (`viridis`/`cividis`/`inferno`/...) | artist, blacksmith |
| `presentation` | enum (`quarto`/`reveal`/`beamer`/`keynote`) | artist, occasionally bookworm |
| `citation_style` | str (`nature`/`vancouver`/`apa`/`chicago`) | bookworm, conscience, artist (captions) |
| `language_runtime` | str (e.g. `python-3.12`/`r-4.4`) | blacksmith |
| `package_manager` | enum (`uv`/`pip`/`poetry`/`conda`/`renv`) | blacksmith |
| `audit_verbosity` | enum (`terse`/`standard`/`verbose`) | adversary |

**Agent-specific fields** stay free-form; the agent picks its own field names. Examples: `bookworm.zotero_collection`, `lawyer.jurisdictions`, `blacksmith.gpu_id`.

**Guild-level extensions to the vocabulary** are supported. The chemistry guild may add `mol_format: smiles | inchi | mol2` as a standardised field for its agents at `murmurent/guilds/chemistry/preferences.md`. The centre vocabulary is the base; guilds extend it.

#### Personal preferences profile

A member can set the cross-cutting fields once, applied across all their installed `personal` agents:

```yaml
# ~/.claude/murmurent-preferences.yaml
language: en
prose_style: academic
plotting: seaborn
figure_size: 10x8
colormap: viridis
citation_style: nature
audience: domain-experts
```

The profile is **local**: never committed to the lab-management repo or any group artefact. It expresses individual preference rather than group policy. The member's preferences travel with them across machines via whatever personal sync they prefer (dotfiles repo, manual copy).

#### Resolution order

When an agent asks "what plotting library should I use?", the answer cascades:

1. **Conversation override** ("use altair this time"): always wins.
2. **Agent's local `defaults`**: set on the agent file directly.
3. **Personal preferences profile** (`~/.claude/murmurent-preferences.yaml`): fills in any standardised field not set in (2).
4. **Registry default** (centre, optionally extended by guild): `frozen` agents stop here; `personal` agents only fall through to here for fields not set in (2) or (3).

A member who sets `plotting: seaborn` once in their profile gets seaborn from every personal agent unprompted. To override for a single agent (e.g. `bookworm` uses pandoc-style citations regardless), they edit that agent's local copy.

#### Validation

`murmurent install` checks each installed agent's `defaults` against the centre + guild vocabulary:

- **Standard fields**: validate type / enum. Unknown enum values are flagged.
- **Possible misspellings**: free-form fields with Levenshtein distance < 3 to a standardised field name produce a warning ("did you mean `figure_size`?").
- **Missing-but-expected**: an agent that produces figures without `plotting` or `figure_size` produces a warning.

All checks **warn rather than hard-reject**. The controlled vocabulary will lag actual practice; rejection would bottleneck adding new fields. Members fix warnings either by aligning to the vocabulary or by extending the vocabulary via PR to `murmurent/preferences.md`.

#### Why this layout

A postdoc doing Bayesian work overrides `framework: pytorch` to `framework: pyro` in their personal `blacksmith.md` (agent-specific, free-form). They also set `prose_style: academic` once in their profile and every text-producing agent obeys (cross-cutting, standardised). The chemistry guild's `artist` may default to `plotnine` and add `mol_format: smiles` as a guild-level standardised field. None of these collide; each lives at the right scope.

## Tier separation (recap)

- **Personal agent:** definition copied to the person's `~/.claude/agents/`. Per-person memory. Evolution allowed if `personal`.
- **Group-registered agent:** definition in `guilds/<group>/agents/`. Members install on demand.
- **Group-role agent:** registered agent + a role assignment held by a specific member. The agent runs in that member's CC environment but its charter and permissions belong to the role.

We are explicitly NOT pursuing shared brains in this iteration.

## Interactions inside a group

Six categories of member-to-member interaction:

1. **Codev**: code development. Mediated by git and GitHub PR review. Already well-served by current practice; agents participate by reading/writing artefacts in the repo, not by talking to each other.
2. **Experimentation**: wet or dry experiments produce data and observations.
3. **Observation**: informal capture (transcripts, photos, voice memos), triaged from `inbox/` into project notes.
4. **Literature**: papers read, summarised, cited. Lives in Zotero + bookworm.
5. **Resource sharing**: reagents, equipment, datasets, lab inventory.
6. **Discussion / mentoring**: Slack, meeting notes, instruction.

**Core insight:** agents do not need to talk to each other if they communicate through the artefacts they read and write. Git is the transport layer, the artefact is the message, and the commit log is the audit trail. This generalises beyond codev: observations, literature notes, and SEA requests can all be artefact-mediated.

GitHub Actions bots are the natural mechanism for headless agent participation. The same agent definition that a member runs locally can be invoked by an Action on PR open / push / schedule, posting back through PR reviews, comments, or commits. No shared memory, no ad-hoc protocol, and a full audit trail at no additional cost.

## Verb table: a typical day for a researcher

Verbs that touch the group (solo work in a personal vault is not listed). Initial set of 10; will grow. Each verb maps to a CLI command (see [[cli_manual]]).

| Verb | What it does | Touches | Scope / visibility |
|---|---|---|---|
| capture | drop a raw transcript/note in `inbox/` | personal vault | private until triaged |
| triage | process inbox into a structured note | vault → project repo | project MEMBERS |
| push | submit a result/observation to a project | project repo (commit + push) | project MEMBERS only |
| pull | fetch latest project state | project repo | project MEMBERS |
| cite | reference a paper or prior finding | Zotero, group oracle | as source allows |
| request_sea | ask another member for a Skill / Experiment / Analysis | group request board | group |
| audit | invoke adversary on a piece of work | local + project repo | scope of work |
| publish | promote a finding from project → group | group oracle (curated) | group |
| provision | check / order reagents or equipment | `inventory/` in lab-management repo (served by the inventory MCP) | group |
| review | comment on / approve a PR | project repo | project MEMBERS |

For verbs not in this day-to-day table, see:
- [Squads](#squads-subgroups) for `form` / `invite` / `release` / `transfer_lead` / `dissolve` / `promote`.
- [SEAs](#sea-verbs) for `request` / `claim` / `complete` / `decline`.
- [Role transitions](#role-transitions) for `assign` / `revoke` / `transfer_role`.
- [Project lifecycle](#project-lifecycle) for `birth` / `admit` / `release` / `pause` / `resume` / `end` / `archive_project`.
- [Knowledge and continuity verbs](#knowledge-and-continuity-verbs) for `discuss` / `teach` / `freeze`.
- `schedule` is intentionally not a Murmurent verb: calendars and a `calendar` MCP cover it.

## Privacy and access

- **Personal**: lives in the person's vault and `~/.claude/agent-memory/`. Never leaves their machine.
- **Project-scoped**: lives in a private GitHub repo (one per project) with a checked-in `MEMBERS` file as the source of truth. Filesystem ACL on `$MURMURENT_LAB_VM_ROOT/refined/<project>/` is synced from MEMBERS.
- **Group-shared**: agent definitions in the Murmurent repo; curated findings in a group oracle; readable to all group members.
- **Sensitive artefacts that must travel** (cloud, email, off-VM): wrap in `age` with MEMBERS as the recipient list. Re-encrypt on membership change.

## Inventory and shared resources

Inventory is hard in labs chiefly because nobody updates it, rather than because of a structured-versus-unstructured data question. The tool most likely to be maintained is the one with the lowest update friction. Obsidian-with-frontmatter is competitive with a spreadsheet on update friction and far better for: attaching catalog photos and vendor notes, versioning, grep-querying from CC, living in the same toolchain as everything else.

**Decision: inventory is semi-structured markdown in the lab-management repo.** Inventory is **group-scoped**, never project-scoped: every member needs access regardless of which project they are working on.

### Layout

One markdown file per reagent or kit:

```
<lab-mgmt-repo>/
├── inventory/
│   ├── anti_cd31.md
│   ├── 4_oht.md
│   └── ...
└── ...
```

### Schema (frontmatter)

| Field | Type | Notes |
|---|---|---|
| `name` | str | Canonical name |
| `lot` | str | Current lot number |
| `qty` | number | Current quantity |
| `unit` | str | mg, mL, units, vials |
| `expiry` | ISO date | YYYY-MM-DD |
| `location` | str | Freezer / shelf / box |
| `vendor` | str | |
| `catalog_no` | str | |
| `last_updated` | ISO date | Auto-set on edit |
| `status` | enum | `in_stock` / `low` / `out` / `expired` / `on_order` |
| `protocols` | list[wikilink] | Protocols that consume this reagent |

Body holds free-form notes: vendor link, MSDS, prep procedure, photos of label or catalog page.

### Inventory MCP

The `provision` operation, and inventory access in general, are exposed as an **MCP server** (the `inventory` MCP), not as CLI subcommands. Any agent in any member's CC instance can call its tools:

- `inventory_list(filter)`: list reagents matching a filter (e.g. `--low`, `--expiring 30`).
- `inventory_show(name)`: return frontmatter + body of one reagent.
- `inventory_provision(plan_path)`: compute `plan ∩ inventory`, report gaps and expiring lots.
- `inventory_set(name, fields)` (*lab_manager only*): update fields, auto-bump `last_updated`.
- `inventory_order(name)` (*lab_manager only*): open an order issue in the lab-management repo.

The MCP wraps the markdown files. Permissions are enforced by the MCP server (read = group, write = `lab_manager`); the lab-management repo's branch protection is the second line of defence for write paths that bypass the MCP.

### `last_updated` mechanism

`last_updated` must be auto-set regardless of how the file was edited. Three redundant layers:

1. **Inventory MCP** sets it on every write (primary path; covers programmatic edits by agents).
2. **Pre-commit hook** in the lab-management repo updates `last_updated` for any `inventory/*.md` file in the staged set (covers direct edits via Obsidian, vim, IDE).
3. **GitHub Action on push** does the same as the hook (backstop for edits via the GitHub web UI, which doesn't run pre-commit hooks).

The field is reliable regardless of the editing tool.

### Permissions

- Read: every group member.
- Write: `lab_manager` role only (enforced by the inventory MCP and by branch protection on the lab-management repo).

### Migration path

If the lab outgrows markdown (≥1000 items, multiple writers per day, complex queries), keep the same frontmatter schema and migrate to SQLite + an inventory MCP server. The schema transfers; the editing UX changes only for the `lab_manager`. New fields can be added in either model.

### Why not SQL today

- Schema rigidity: catalog photos, vendor links, prep notes don't fit cleanly.
- Tooling separate from the rest of Murmurent.
- Adds a server to operate.
- For lab-scale (hundreds of items, infrequent updates), the marginal benefit is small.

## Project lifecycle

A project has a lifecycle of distinct events. Each event is auditable and produces specific artefacts. The lifecycle is intentionally short: it has just enough structure to make access, attribution, and archival unambiguous.

### Birth

- A proposer (PI or designate) submits a **charter**: a one-paragraph statement of why the project exists, expected scope, choreography type, **sensitivity tier** (`standard` / `restricted` / `clinical`; see [Sensitivity tiers](#sensitivity-tiers-and-project-level-controls)), and an initial MEMBERS list. `clinical` charters require additional fields (REB number, REB expiry, data residency).
- PI approval creates: a private GitHub repo named for the project, scaffolded to the lab's standard project layout (`exp/`, `src/`, `findings/`, `obsolete/`, `data/`); `MEMBERS` populated; both `$MURMURENT_LAB_VM_ROOT/raw/<project>/` and `$MURMURENT_LAB_VM_ROOT/refined/<project>/` directories with ACL synced from MEMBERS; an entry in the group's project registry.
- Charter is committed as `CHARTER.md` in the new repo. Significant scope changes later are themselves auditable amendments to that file.

### Active

- Members exercise the verbs (`push`, `pull`, `audit`, `publish`, etc.) against the project repo.
- The charter is the contract for what is in scope.

### Admit / Release

- **admit**: PI signs the event; MEMBERS updated; ACL re-synced; any `age`-encrypted artefacts in the repo are re-encrypted to include the new recipient.
- **release**: a member departs (graduates, leaves the group, finishes their rotation). Their work and attribution stay in the repo; their read/write access is removed; outstanding role assignments inside the project transfer or revoke; `age`-encrypted artefacts re-encrypted without them.

### Pause / Resume

- A project can be marked **inactive** without ending: useful for waiting on data, an external collaborator, or a cycle gap.
- Repo stays open, no new pushes expected, ACL unchanged. **resume** is a single audit event with no MEMBERS reset.

### End

- Terminal event with a recorded reason: published, abandoned, hypothesis disproven, scope merged into another project, defunded.
- Required artefacts: a final summary written to `SUMMARY.md`, curated findings published to the group oracle (tagged with the project name), audit entry.

### Archive

- Repo archived on GitHub (read-only).
- Data on lab VM moved to `$MURMURENT_LAB_VM_ROOT/refined/<project>/ARCHIVE-YYYY-MM-DD/`.
- MEMBERS frozen as the final access list. Former members retain read access for citation and recall.
- Any `age`-encrypted bundles re-encrypted once with the frozen MEMBERS list and a long-lived archive key.

### Required events / artefacts

| Event | Required artefacts |
|---|---|
| birth | charter, MEMBERS, repo (scaffolded to lab project layout), lab-VM `raw/` + `refined/` dirs, registry entry |
| admit | updated MEMBERS, audit entry, re-synced ACL, re-encrypted bundles |
| release | updated MEMBERS, audit entry, re-synced ACL, role transfers, re-encrypted bundles |
| pause | audit entry with reason |
| resume | audit entry |
| end | final summary, oracle publish, audit entry |
| archive | data move, repo archive, frozen MEMBERS, archive-key re-encrypt, audit entry |

## Experiments and lab notebooks

Lab notebooks contain photos, drawings, sketches, numbers, text, and small data files. All experiments performed in a project must sit together, accessible to every MEMBER, with no platform lock-in (no Notion) and no schema rigidity (no SQL).

**Decision: each experiment is a folder inside the project repo, following the lab's standard project structure.** Data files (raw measurements, large outputs) live on the lab VM under `$MURMURENT_LAB_VM_ROOT/raw/` and `$MURMURENT_LAB_VM_ROOT/refined/`, never in the repo. The notebook entry **links** to data files; it does not embed them.

This aligns with the lab's global rules: `~/.claude/rules/data-storage.md` and `~/.claude/rules/project-structure.md`.

### Project repo layout

```
<project_repo>/                 ← e.g. ~/repos/brca_imaging/
├── CHARTER.md
├── MEMBERS
├── README.md
├── exp/
│   ├── 1_titration/
│   │   ├── README.md                 ← per lab convention
│   │   ├── run_all.py                ← entry point for the experiment's analysis
│   │   ├── notebook.md               ← lab notebook entry: frontmatter + text + image embeds
│   │   ├── pages/                    ← photos of paper notebook pages (downsampled)
│   │   ├── sketches/                 ← drawings (PNG/PDF)
│   │   ├── data/                     ← very small committed data only
│   │   └── ...                       ← scripts
│   └── 2_qpcr/
├── src/
│   ├── protocols/                    ← reusable protocols cited by experiments
│   ├── literature/                   ← Zotero exports
│   ├── ready_to_delete.md            ← per lab convention; tracks refined files safe to delete
│   └── ...                           ← shared code
├── findings/                         ← curated outputs promoted at project level
├── obsolete/                         ← deprecated code/data not yet ready to delete
└── data/                             ← group-shared very small data (per lab convention)
```

Experiment folders follow the lab's `<integer>_<good_name>/` convention; date lives in the notebook frontmatter.

### Data locations (raw / refined)

Per the lab's data-storage rule, data does **not** live in the repo:

- **Raw data:** `$MURMURENT_LAB_VM_ROOT/raw/<project>/<experiment>/...`. Read-only. Never modified by code; only copied from instrument/collaborator. Names preserved verbatim.
- **Refined data:** `$MURMURENT_LAB_VM_ROOT/refined/<project>/<experiment>/...`. Outputs of `run_all` and other analyses. Mirrors the repo's `exp/` layout one-to-one.
- **Versioning:** integer suffix on filenames; largest = newest (per lab convention).
- **`src/ready_to_delete.md`:** tracks refined files safe to delete; checked when refined storage gets tight.

The notebook entry links to data; it never holds it.

### `notebook.md`: required frontmatter

| Field | Type | Notes |
|---|---|---|
| `experiment` | str | Experiment slug (e.g. `1_titration`) |
| `date` | ISO date | When the experiment was performed |
| `performer` | list[str] | GitHub handles of who ran it |
| `project` | wikilink | Parent project |
| `protocol` | wikilink | Protocol used (`src/protocols/<name>.md`) |
| `equipment` | list[str] | Instruments used |
| `reagents` | list | Names from `inventory/`; matched by the inventory MCP |
| `raw_data` | list[path] | Files in `$MURMURENT_LAB_VM_ROOT/raw/...` consumed by this experiment |
| `refined_data` | list[path] | Files in `$MURMURENT_LAB_VM_ROOT/refined/...` produced by this experiment's analyses |
| `instrument_outputs` | list[path] | Instrument-derived files (thumbnails, PDFs, QC reports) in `$MURMURENT_LAB_VM_ROOT/refined/<project>/<experiment>/instrument_outputs/`. Populated by `experiment ingest`. |
| `checksums` | dict | SHA-256 for each file in `raw_data`, `refined_data`, `instrument_outputs` (auto-computed) |
| `status` | enum | Operational: `planned` / `running` / `complete` / `failed` / `inconclusive` |
| `analysis_status` | enum | Intellectual: `not_started` / `examined` / `concluded`. See [The finalisation choreography](#the-finalisation-choreography). |
| `examined_at` | ISO date | When the examine stage completed (if reached) |
| `concluded_at` | ISO date | When the conclude stage completed (if reached) |
| `tags` | list[str] | Kebab-case |

Body: free-form. Embed photos with `![](pages/p1.jpg)`. Reference data files by absolute path. Cross-reference findings with `[[findings/...]]`.

### What stays in the repo (and what doesn't)

- **In the repo:** notebook entry, photos of paper notebook pages (downsampled), sketches, very small data, code, protocols, charter, MEMBERS, README, `ready_to_delete.md`.
- **Not in the repo:** raw measurements, large refined outputs (figures > a few MB, processed arrays, image stacks). These live under `/data/lab_vm/`.
- **No git LFS.** LFS would either break the read-only-raw rule, couple data lifetime to GitHub billing, or duplicate what the lab VM already provides. The lab VM is the canonical data store; the repo holds documentation and code.

### Capture tooling

Use what you already have:
- iPhone Files / AirDrop → drag into the experiment's `pages/`, `sketches/`, or `data/`.
- Scanbot or Genius Scan → paper notebook pages → JPG, downsampled.
- Apple Pencil → PNG.
- Spreadsheets → CSV in `data/`.
- Obsidian opens the project repo as a vault.

For raw instrument data: `murmurent experiment ingest <project> <exp> <source>` copies the instrument files, computes checksums, sets the raw directory `chmod a-w`, and updates the notebook's `raw_data` and `checksums` fields. Classification of raw vs derived files is described below.

### Ingest classification (raw vs derived)

Instrument export folders rarely contain only true raw data. They typically mix:

- **True raw**: `scan_001.czi`, `run_001.fastq.gz`. Goes to `$MURMURENT_LAB_VM_ROOT/raw/<project>/<experiment>/`, immutable.
- **Instrument-derived**: thumbnails, summary PDFs, QC HTML reports. Goes to `$MURMURENT_LAB_VM_ROOT/refined/<project>/<experiment>/instrument_outputs/`. Stays writable (regeneratable).
- **Ambiguous**: metadata XML, software-aligned BAMs, instrument-software overlays. Depends on the instrument and the lab's convention.

Because raw is immutable once committed, classification has to happen before the `chmod a-w`. Three layers, in order:

#### 1. Instrument profiles

A YAML file per known instrument at `murmurent/instruments/<type>.yaml` (centre default) or `lab-mgmt-repo/instruments/<type>.yaml` (lab override) declares which extensions and patterns are raw vs derived. Example:

```yaml
---
instrument: zeiss-confocal
description: Zeiss LSM confocal microscope
detect_marker: '*.czi'
raw:
  extensions: [czi, lsm]
  patterns: ['metadata*.xml']
derived:
  extensions: [pdf, html, png]
  patterns: ['*thumbnail*', '*preview*', '*_qc.*']
---
```

`detect_marker` lets the CLI auto-detect the instrument when `--instrument` is not given. The Murmurent repo ships starter profiles for common instruments (Zeiss confocal, Illumina sequencers, common mass-spec); labs add their own.

#### 2. Generic fallback patterns

When no instrument profile matches, files matching these patterns default to derived; everything else defaults to raw:

- Extensions: `.pdf`, `.html`
- Filename patterns: `*thumbnail*`, `*preview*`, `*summary*`, `*report*`, `*_qc.*`

The fallback fires with an explicit warning so the user knows the classification is heuristic and should be reviewed.

#### 3. Mandatory review

Before any copy or `chmod`, the CLI shows the proposed classification and waits for explicit acceptance:

```
$ murmurent experiment ingest brca_imaging 3_titration ~/Downloads/scope_export
Detected instrument: zeiss-confocal (from .czi files)
Proposed classification:
  → $MURMURENT_LAB_VM_ROOT/raw/brca_imaging/3_titration/
    scan_001.czi   scan_002.czi   scan_003.czi   metadata.xml
  → $MURMURENT_LAB_VM_ROOT/refined/brca_imaging/3_titration/instrument_outputs/
    thumbnail_001.png   summary.pdf   qc_report.html
[a]ccept  [r]eview file-by-file  [c]ancel ?
```

Review is mandatory. The cost of a misclassification (a derived file permanently stuck in raw, or a true-raw file landing somewhere mutable) outweighs the friction of one prompt per ingest.

#### CLI flags

| Flag | Effect |
|---|---|
| `--instrument <type>` | Explicit profile selection; overrides auto-detect |
| `--accept` | Skip the interactive prompt (for scripting). Warns that review is recommended |
| `--dry-run` | Show classification without copying anything |

#### After acceptance

- Raw files → `$MURMURENT_LAB_VM_ROOT/raw/<project>/<experiment>/`; directory then `chmod a-w`.
- Derived files → `$MURMURENT_LAB_VM_ROOT/refined/<project>/<experiment>/instrument_outputs/`; remain writable.
- SHA-256 computed for both groups.
- `notebook.md` updated: `raw_data:` lists raw files, new `instrument_outputs:` field lists the derived files, `checksums:` covers both.

### Why not eLabFTW or shared-filesystem alternatives

- **eLabFTW** (open source ELN): richer UI, electronic signatures, search, audit. The right answer if regulatory compliance (e.g. 21 CFR Part 11) is required. For academic biology day-to-day, folder-in-repo + lab VM is enough.
- **Shared filesystem** (Nextcloud, Syncthing): handles large binaries without LFS, but loses PR-based review, branch isolation, and the artefact-as-message model agents rely on. Not needed once data lives on the lab VM.

### Verb support

`murmurent experiment new --project brca_imaging --name titration` scaffolds:
- `exp/<next-int>_titration/` in the project repo with `README.md`, `run_all.py` skeleton, `notebook.md` template (auto-filled `experiment`, `date`, `performer`), `pages/`, `sketches/`, `data/` subfolders.
- `$MURMURENT_LAB_VM_ROOT/raw/brca_imaging/<next-int>_titration/` (writeable until raw is loaded; then `chmod a-w`).
- `$MURMURENT_LAB_VM_ROOT/refined/brca_imaging/<next-int>_titration/`.

Then opens `notebook.md` in Obsidian.

## Push mechanics: branches, PRs, and bots

The `push` verb covers a wide range of artefacts (notebook entries, code, photos, findings, charter amendments). Forcing PR review on all of them creates intolerable friction for in-progress work; allowing direct push to all of them undermines review where it matters.

**Decision: branch protection by path.** Different artefacts get different rules. The boundary between "direct push" and "PR required" matches the social contract: nobody objects to a member writing in their own notebook; everyone has a stake in what gets published as a finding.

### Default path: personal branch, PR to main

Each member works on branches named `member/<github-handle>/<topic>` in the project repo.

- `murmurent push <project>` → push the current branch as a personal branch. Direct push, no review.
- `murmurent push <project> --finalize` → open a PR from the personal branch to `main`. Bot and human reviews per the path rules.

The CLI inspects the diff and, if any changed path requires PR, refuses direct push and offers to open one instead.

### Branch protection rules

| Path | Requirement |
|---|---|
| `CHARTER.md` | PR + PI approval |
| `MEMBERS` | PR + PI approval |
| `findings/**` | PR + reviewer (PI or designate) |
| `src/protocols/**` | PR + reviewer |
| `src/**` (code) | PR + reviewer |
| `exp/<n>_<slug>/notebook.md` with `status: complete` | PR + reviewer |
| `exp/<n>_<slug>/notebook.md` with `status: planned\|running` | direct push to personal branch |
| `exp/<n>_<slug>/{pages,sketches,data}/**` | direct push |
| `obsolete/**` | direct push |
| `roles/**` (lab-management repo only) | PR + PI approval |
| `inventory/**` (lab-management repo only) | PR + lab_manager (or via inventory MCP) |

### Bot reviews on PR

Each PR triggers GitHub Actions per the paths involved. Bots always run frozen versions of the agents (per the freeze cascade).

| Bot | Triggers on | Effect |
|---|---|---|
| `adversary` | `src/**`, `*.py`, `*.R`, `*.ipynb` | Posts a review comment with methodology / leakage / cross-validation concerns |
| `conscience` | `findings/**`, `CHARTER.md` | Reviews EDID concerns; flags problematic language or framing |
| `security_guard` | every PR | Scans the diff for restricted file paths or accidental secrets |
| `bookworm` | `findings/**`, `notebook.md` finalisations | Checks that citations are present and resolvable |

### Auto-publish on merge

When a PR merges to `main`, a merge Action runs:

- `findings/**` changes → auto-published to the group oracle (the `oracle` MCP exposes a `publish` tool the Action calls).
- `notebook.md` with `status: complete` → audit entry written to the project registry; refined-data checksums re-verified.
- `MEMBERS` change → ACL re-sync on the lab VM; `age` re-encrypt of any encrypted bundles.

### Refined-data updates

When an analysis produces new files in `$MURMURENT_LAB_VM_ROOT/refined/<project>/<exp>/`, the notebook's `refined_data:` and `checksums:` fields need updating. This is a frequent operation; it should not require PR review.

- `murmurent push <project> --refined <exp>` recomputes checksums for files in `$MURMURENT_LAB_VM_ROOT/refined/<project>/<exp>/`, updates the notebook's `refined_data:` and `checksums:` fields, and pushes to the member's personal branch.
- The eventual `--finalize` PR rolls all those personal-branch updates into `main` along with the status flip to `complete`.

### Why path-based, not all-PR or all-direct

- **All-PR** creates friction on every notebook keystroke. Members stop using the tool, or push less, and the artefact-as-message model breaks.
- **All-direct** removes review where review is the point (charter changes, findings, completed experiments).
- **Path-based** puts the review boundary at the artefact-type boundary. The rule is legible: "what gets reviewed is what others depend on."

## Group-level agents assignable to individuals

The PI maintains a **role registry**. Each role:

- references an agent definition in the group's registry
- has cardinality: `singleton`, `quota: N`, or `open`
- has zero or more current operators (members assigned to run it)
- has an audit log of operator changes (handoff dates, transferring PI signature)

Initial role examples:

- **lab_manager**: singleton; typically the admin assistant. Owns inventory, supply orders, scheduling, reagent provisioning.
- **sysadmin**: singleton or pair; permissions, repos, lab VM, backup integrity.
- **bookworm_curator**: quota of 2; curates the group's Zotero library on behalf of all members.
- **oracle_curator**: quota of 2; annual rotation. Facilitates finalisation choreographies (ensures all expected agents have weighed in, statements are well-formed, cross-references are correct) and handles periodic legacy maintenance of the group oracle.
- **adversary_chair**: rotating; runs adversarial review on group-bound submissions (papers, grants).
- **conscience_chair**: rotating or singleton; EDID review on outgoing artefacts.

Only the PI may assign or revoke a role. Role transitions are first-class events with an audited handoff.

### Role registry file format

One markdown file per role, in the group's lab-management repo at `roles/<role>.md`:

```markdown
---
role: lab_manager
agent: lab_manager
cardinality: singleton
---

# lab_manager

## Charter
Owns inventory, supply orders, scheduling, reagent provisioning. Authorised
to mutate the inventory database. Authorised to spend up to $X without
explicit PI approval.

## Current operators
- @member_a (since 2026-04-01)

## Audit log
- 2026-04-01: assigned @member_a (PI: @the_pi, signed)
- 2026-01-15: revoked @prev_admin (handoff complete)
- 2026-01-01: assigned @prev_admin (PI: @the_pi, signed)
```

## Role transitions

A role transition (assign / revoke / transfer) is a first-class auditable event. Transitions are not lightweight: they touch credentials, permissions, in-flight obligations, and possibly agent memory.

### Steps

1. **Initiate**: issue filed in the group's lab-management repo, labelled `role-transition`. Names: role, current operator (if any), proposed operator, effective date, reason.
2. **Acknowledge**: proposed operator comments on the issue accepting the role and confirming they have read the charter.
3. **Handoff checklist**: current operator works through:
   - Document the current state of the role's responsibilities (open requests, pending orders, active reviews).
   - Rotate credentials where rotation is possible; share securely otherwise (1Password, age envelope).
   - Update permissions: filesystem ACLs, GitHub team membership, MCP server credentials, lab VM accounts.
   - Transfer or archive the agent's local memory if the role's continuity depends on it.
   - Update the role registry file: replace operator(s), append to audit log.
4. **PI sign-off**: PI closes the issue with a signed approval comment (commit-signed where possible).
5. **Audit entry**: appended to `roles/<role>.md` with previous operator, new operator, effective date, PI signature.

### Unilateral transitions

If the current operator cannot participate (left without handoff, deceased, terminated), the PI initiates the transition with an explicit `unilateral` flag. The audit entry records the absence of operator acknowledgement and notes any credentials that had to be rotated rather than transferred.

### Quota and cardinality enforcement

The CLI's `roles assign` command refuses to exceed cardinality without an explicit `--force` flag, which itself appears in the audit log. This makes accidental violations visible.

## Onboarding flow

Adding a new member to a group is a multi-stage choreography. Goals: low friction for the new user, auditable, revocable, with `age` keys handled correctly so encrypted artefacts remain accessible.

### Stage 1: Invitation

The PI files an issue in the lab-management repo titled `Onboard @<github-handle>`. The issue specifies:
- Which **onboarding profile** to apply (e.g. `student`, `postdoc`, `pi-collab`, `core-staff`).
- Which projects to admit the user to (initial MEMBERS).
- Any role assignments at the start.
- Any restrictions (read-only on certain projects, no write to lab-management, etc.).

Reusable profiles live at `lab-mgmt-repo/onboarding/<profile>.md`. Each profile is a YAML+markdown spec listing: agents-to-install, default projects, default role, default permissions.

### Stage 2: Local setup

The new user runs:

```
murmurent onboard <group> --profile student
```

This:
- Clones the Murmurent repo (default `~/repos/murmurent`).
- Installs agents per the profile, applying the freeze cascade (symlinks for `frozen`, copies for `personal`).
- Configures MCP servers (inventory, oracle, request board) in `~/.claude/settings.json`.
- Generates a personal `age` key pair; pushes the public key to `lab-mgmt-repo/keys/<github-handle>.age`.
- Creates `lab-mgmt-repo/members/<github-handle>.md` with a profile stub (interests, contact, current projects).
- Opens a PR with the key + member profile.

### Stage 3: Approval

- PI reviews the PR and approves the public key + profile.
- For each project listed in the onboarding issue, PI runs `murmurent project admit <project> @<handle>`. Each admit is a normal admit event in the project lifecycle (audit entry, ACL re-sync, re-encryption of `age` bundles to include the new recipient).
- PI assigns starting roles via `murmurent role assign`. Each is a normal role transition.

### Stage 4: Confirmation

- New user verifies they can pull each project they were admitted to.
- New user runs `murmurent doctor` to confirm install integrity.
- Onboarding issue is closed.

### Required artefacts

| Artefact | Location |
|---|---|
| Onboarding issue | lab-management repo issues |
| Onboarding profile | `murmurent/onboarding/<profile>.md` (centre) or `lab-mgmt-repo/onboarding/<profile>.md` (lab override) |
| Member profile note | `lab-mgmt-repo/members/<github-handle>.md` |
| Member age public key | `lab-mgmt-repo/keys/<github-handle>.age` |
| Audit entries | one per project admit, one per role assignment |

### Profile catalog

Four profiles ship as centre defaults at `murmurent/onboarding/<profile>.md`. Each lab can override or extend at `lab-mgmt-repo/onboarding/<profile>.md`: lab-specific version wins when both exist. New lab-specific profiles (e.g. `clinical-fellow` for a translational lab) are just additional files.

#### `student`

Graduate or undergraduate student joining the group under a supervisor.

```yaml
---
profile: student
description: Graduate or undergraduate student joining the group
---

agents:
  - bookworm
  - blacksmith
  - artist
  - adversary
  - conscience
  - security_guard
default_projects: []          # PI admits explicitly
default_roles: []
permissions: member
lead_eligible: false
expiry: null
```

`lawyer` excluded by default: IP concerns rarely matter for students; can be added later via `murmurent agent add`.

#### `postdoc`

Independent researcher; eligible to lead projects.

```yaml
---
profile: postdoc
description: Independent researcher; eligible to lead
---

agents:
  - bookworm
  - blacksmith
  - artist
  - adversary
  - conscience
  - security_guard
  - lawyer
default_projects: []
default_roles: []             # rotating roles like adversary_chair assigned later
permissions: member
lead_eligible: true
expiry: null
```

#### `pi-collab`

External PI collaborating on a specific project.

```yaml
---
profile: pi-collab
description: External PI collaborating on a specific project
---

agents:
  - bookworm
  - adversary
  - artist
  # blacksmith excluded — collaborators run their own infrastructure
default_projects: []          # the collaboration project admitted explicitly
default_roles: []             # often co-lead on the collaboration project
permissions: scoped           # only the projects they are admitted to; no group-wide read
lead_eligible: true
expiry: 12_months_default     # renewable
```

Scoped permissions matter: `pi-collab` cannot browse other group projects.

#### `visitor`

Visiting student or sabbatical scientist; short-term, observation-mostly.

```yaml
---
profile: visitor
description: Short-term visitor (visiting student, sabbatical, etc.)
---

agents:
  - bookworm
  - artist
default_projects: []
default_roles: []
permissions: read_only        # cannot push, cannot complete SEAs, cannot mutate inventory
lead_eligible: false
expiry: 3_months_default      # required; renewable
```

### A note on cores and factories

Core facilities (sequencing centres, mass-spec, imaging cores) are **not** modelled as a profile within a regular group. Each core is its own group: its own people, its own specialised agents, its own inventory, its own choreographies. Cross-group collaboration (a sequencing-core member working on another group's project) is handled by admitting them to that project as an external member, exactly as for any other cross-group case. The (deferred) centre-level design will spell out how groups and cores interconnect; nothing in the present group-level design needs a `core-staff` member type.

### Layering

Profiles describe the **baseline** install. Roles, project memberships, and permission elevations are layered separately via the normal flow (PI runs `murmurent role assign`, `murmurent project admit`). A student who will act as `bookworm_curator` gets the `student` profile and then has the role assigned. This keeps the profile count from exploding combinatorially.

### Validation

`murmurent install` and `murmurent onboard` check the resolved profile:
- Warns if a referenced agent doesn't exist in the registry.
- Warns if a referenced role doesn't exist.
- Warns if `expiry` is missing for `pi-collab` or `visitor` (these are time-bounded by default).

Consistent with the warn-not-reject philosophy used elsewhere.

### Offboarding (mirror)

Triggered by the PI when a member leaves:
- Each project runs `release`; each role runs `revoke` or `transfer`.
- Member age key is moved from `keys/` to `keys/archive/`: preserved for decrypting historical bundles, not used for new ones.
- Member profile note marked `status: alumni` with departure date; not deleted (preserves attribution on past work).
- A final summary of contributions is appended to the member profile note.

## Squads (subgroups)

A **squad** is the subgroup that actually performs a project, experiment, or SEA. It has a lead and members. Squads can be nested: a project squad has experiment squads inside, which have SEA squads inside.

Group membership ≠ squad membership. Not every group member is in every squad. The PI is default-present in every squad but can opt out (`--no-pi`) when their day-to-day involvement isn't useful.

### Authority cascade

| Authority | Can do |
|---|---|
| **PI** | Project birth/end, charter amendments, role assignments, project-lead transfers |
| **Project lead** | Form/dissolve sub-squads, transfer experiment/SEA leads, admit/release at project level |
| **Sub-squad lead** (experiment, SEA) | Invite/release members within their scope |
| **Member** | Claim, complete, decline SEAs assigned to them |

Project-lead is assigned by the PI. Sub-squad leads are assigned by the project lead.

### Squad verbs

| Verb | What it does | Authority |
|---|---|---|
| `form` | Create a squad with a lead, initial members, and a scope (project / experiment / SEA) | PI for project-level; project lead for experiment/SEA-level |
| `invite` | Propose adding a member; member accepts | Lead |
| `release` | Remove a member from the squad | Lead |
| `transfer_lead` | Handoff lead to another member | PI for project-level; project lead for sub-squads |
| `dissolve` | End the squad (project end, experiment closure, or SEA done) | Lead, with PI sign-off for project-level |
| `promote` | Upgrade a sub-squad's scope (e.g. experiment → project when work grows) | PI |

### SEA verbs

| Verb | What it does |
|---|---|
| `request` | File an SEA request on the group request board, naming target squad or member |
| `claim` | Declare you'll perform an offered SEA |
| `complete` | Mark an SEA complete with a delivery artefact |
| `decline` | Refuse an SEA, with reason |

### Squad registry

Each squad has a markdown file in the lab-management repo at `squads/<scope>/<name>.md`:

```markdown
---
squad: brca_imaging
scope: project
lead: '@member_a'
members: ['@the_pi', '@member_b']
pi_present: true
status: active
parent: null
---

# Squad: brca_imaging

## Charter
[link to project charter]

## Sub-squads
- exp/3_titration (lead: @member_b)

## Audit log
- 2026-04-01: formed (PI: @the_pi, lead: @member_a)
- 2026-04-15: invited @member_b
```

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

- `choreography:list`: show available choreographies in the Murmurent repo and any guild-level additions.
- `choreography:apply <name> --to <project>`: scaffold a project against the recipe.
- `choreography:status <project>`: report how far the project has progressed against the recipe's expected steps; flag missing artefacts.

### Where choreographies live

- **Centre-level**: `murmurent/choreographies/*.md`. Available to every group.
- **Guild-level**: `murmurent/guilds/<group>/choreographies/*.md`. Group-specific patterns.
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
- **Protocol**: a lab procedure (wet or dry). Lives at `<project repo>/src/protocols/<name>.md` (project-scoped), `<murmurent-repo>/guilds/<group>/protocols/<name>.md` (group-scoped), or `<murmurent-repo>/protocols/<name>.md` (centre-scoped).
- **Skill**: a Claude Code-discoverable instruction set the model invokes by name. Lives at `<murmurent-repo>/guilds/<group>/skills/<name>.md` or `<murmurent-repo>/skills/<name>.md`.

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
- **archive_project**: already in [Project lifecycle](#project-lifecycle). CLI: `murmurent project archive`.

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

## Dashboards

Each member has a dashboard. The PI gets an enhanced version of it. Two implementations sharing the same underlying data.

### Markdown snapshot

`lab-mgmt-repo/dashboards/<github-handle>.md`: regenerated nightly by a GitHub Action and on relevant events (PR merge, role assignment, squad change). Grep-able, version-controlled, readable in Obsidian, consumable by CC. This is the canonical source of truth for what's in a member's view.

### Live local view

`murmurent dashboard --hifi` opens a local FastAPI web application that reads the snapshot plus live MCP queries (inventory, oracle, request board) plus local git state. Member-level by default; PI sees additional sections automatically (based on identity).

### Member dashboard contents

- **Identity**: handle, email, group, status (active, on leave, alumni).
- **Agents**: name, effective freeze flag, install type (symlink vs copy), last sync, drift status for personal copies.
- **Squads**: project / experiment / SEA scope, role (lead vs member), status.
- **SEAs**:
  - Outgoing: requests you've made of others, with status.
  - Incoming: assigned to you, with status and deadlines.
- **Outstanding analysis**: SEAs / experiments / projects where you are a squad member or lead and `analysis_status != concluded`. Sorted by age since `complete`. Visual escalation: subtle yellow at >2 weeks unexamined; red and escalated to squad lead + PI dashboards at >2 months. The panel header reads "what does each result mean?" (pedagogical purpose stated explicitly).
- **Security and compliance**: per-project sensitivity badge (`standard` / `restricted` / `clinical`), the controls required for that tier, and your compliance status (TCPS 2 certified ✓, TOTP enrolled ✓, signing key registered ✓, etc.). Missing required controls render in red with a one-click action to resolve. Includes an **Elected upgrades** subsection where you toggle stricter-than-required controls (always-on 2FA, always age-encrypted off-VM transfers, etc.). Required and elected stay distinct: you can layer stricter controls but cannot opt out of required ones. See [Sensitivity tiers](#sensitivity-tiers-and-project-level-controls).
- **Quick MCP queries**: inventory search bar (low / expiring shortcuts), oracle latest, request board.
- **Recent activity**: your commits, your PRs, oracle publishes touching projects you're in.
- **Storage / compute**: your workspace size, your share of `$MURMURENT_LAB_VM_ROOT/refined/`, GitHub Action minutes consumed.
- **Notifications**: PR reviews waiting on you, SEAs assigned, role transitions to ack, oracle digests.
- **Quick actions**: new experiment, push, request SEA, open a project repo.

### PI dashboard adds

- **Group overview**: members (active / alumni), projects (active / paused / archived), squads, role holders.
- **Audit**: recent admits / releases, role transitions, charter amendments, sensitive PR merges, inventory orders.
- **Accounting**: budget vs spend, outstanding orders.
- **Compute**: lab VM CPU/GPU per member or per project, storage usage by project, GitHub Action minutes.
- **Onboarding queue**: open onboarding issues, pending key/profile PRs.
- **Oracle**: pending publishes, recent findings, oracle health (size, last curation).
- **Risk**: stale roles, frozen agents needing update, encrypted bundles needing re-encryption, unmerged personal branches > 30 days old.
- **Compliance grid**: across all `clinical` projects in the group, a member-by-control matrix. Members with expiring or expired certifications, missing 2FA enrollments, or pending REB renewals surface here. Drives onboarding-style "fix this" actions on individual member dashboards.

### Implementation notes

- The Streamlit app reads the markdown snapshot for any data it can find there, falling back to live MCP queries for things that need to be fresh (current inventory state, oracle latest).
- A `dashboard` MCP exposes tools for the snapshot generator (`list_squads_for_member`, `recent_activity`, `compute_usage`) so other agents can query the same data without duplicating logic.
- The snapshot generation script is a GitHub Action that the lab-management repo runs on a cron (nightly at 04:00 local) plus event triggers.

## Hooks and permissions: current state and gaps

We have several layers of access control designed but the assistant-level layer is missing. Listed explicitly to avoid overstating the system's security.

### What is designed

- **Filesystem ACLs** on `$MURMURENT_LAB_VM_ROOT/raw/<project>/` and `$MURMURENT_LAB_VM_ROOT/refined/<project>/`, synced from MEMBERS.
- **Branch protection** on `main` of project repos, per-path rules.
- **MCP server-level permissions**: read = group, write = role-restricted (e.g. `lab_manager`).
- **age encryption** for off-VM artefacts; recipients = current MEMBERS.
- **Audit trail** via git commits (signed where possible) plus role-registry audit logs and oracle publish logs.
- **Freeze cascade** for agents (registry default → role override → bot pinning).

### What is missing (and important)

- **Claude Code hooks** (`PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`). The assistant-level gate. Not yet designed. Necessary for: refusing a Read of a file outside the current project's MEMBERS; refusing a Bash that touches `$MURMURENT_LAB_VM_ROOT/raw/`; logging every tool call to an audit stream; injecting current-project context on `UserPromptSubmit`.
- **`settings.json` allowlists** per agent. We should specify the minimum tool set each agent needs and refuse the rest.
- **Secret management**. We've gestured at 1Password for shared secrets and at age private keys for individual ones; we have not specified where API keys and lab VM tokens live, how they're rotated, or how access is revoked.
- **Lab VM authentication**: SSH vs SSO, key rotation cadence, revocation procedure on member release.
- **Audit log integrity**: signed commits, protected branches in the lab-management repo (no force-push), commit-signing keys tied to identities.
- **Cross-MCP authentication**: how the inventory MCP knows the caller is the `lab_manager`. Likely a shared header signed by the user's age key, but not yet specified.
- **Encryption-at-rest** on the lab VM. If the VM is stolen, what's protected and what isn't.

### A reasonable order to close these

1. ~~CC hooks for the most consequential cases (raw-data reads, secrets, cross-project access).~~ **Designed below.**
2. ~~`settings.json` allowlists per agent, generated from each agent's frontmatter declaring its required tools.~~ **Designed below.**
3. ~~Audit log integrity (signed commits, protected branches).~~ **Designed below.**
4. ~~Cross-MCP authentication (shared signing scheme).~~ **Designed below.**
5. ~~Secret management policy.~~ **Designed below.**
6. ~~Lab VM auth specifics.~~ **Designed below.**
7. ~~Encryption-at-rest.~~ **Designed below.**

Plus a project-level sensitivity-tier framework that layers extra controls (`standard` → `restricted` → `clinical`): see [Sensitivity tiers and project-level controls](#sensitivity-tiers-and-project-level-controls).

## Claude Code hooks (gap #1, design)

Seven hooks compose the Murmurent protection layer. Each is a small script registered in `~/.claude/settings.json`. Hook scripts live in the Murmurent repo at `murmurent/hooks/` and are symlinked into `~/.claude/hooks/` by `murmurent install`. The CC harness invokes them with the tool call (or prompt) on stdin as JSON; the hook responds with JSON declaring allow / deny / modify.

### Active project context

Several hooks need to know which Murmurent project the member is currently working in. Resolution order:

1. `MURMURENT_PROJECT` environment variable, if set.
2. Walk up from `cwd` until a `.murmurent-project` marker file (or `CHARTER.md`) is found; the project name is read from that file.
3. Fall back to "no active project": non-protected operations only.

This is computed once per CC session and cached. Most hooks short-circuit when no active project is resolved.

### Hook 1: Raw-data guard (`PreToolUse`)

**Purpose:** prevent any modification of `$MURMURENT_LAB_VM_ROOT/raw/`. The lab's data-storage rule is absolute: raw data is read-only, ever.

**Trigger:** `Write`, `Edit`, `Bash`, `NotebookEdit`.

**Logic:**
- For `Write` / `Edit` / `NotebookEdit`: deny if the target path is inside `$MURMURENT_LAB_VM_ROOT/raw/`.
- For `Bash`: parse the command. Deny if it contains output redirection (`>`, `>>`, `tee`) into a raw path, or destructive operations (`rm`, `mv`, `cp <src> <raw-target>`, `chmod +w`) targeting raw.
- `Read`, `Glob`, `Grep` against raw are explicitly allowed (raw is meant to be read).

**Implementation pattern (Python, ~40 lines):**

```python
import json, sys, re, shlex
RAW_PREFIX = "$MURMURENT_LAB_VM_ROOT/raw/"
DESTRUCTIVE = {"rm", "mv", "cp", "tee", "dd", "chmod"}
call = json.load(sys.stdin)
tool, args = call["tool_name"], call["tool_input"]
def deny(reason): print(json.dumps({"decision": "deny", "reason": reason})); sys.exit(0)
if tool in {"Write", "Edit", "NotebookEdit"}:
    if args.get("file_path", "").startswith(RAW_PREFIX): deny("raw is read-only")
elif tool == "Bash":
    cmd = args.get("command", "")
    if re.search(rf"(>|>>|tee)\s+['\"]?{re.escape(RAW_PREFIX)}", cmd): deny("redirect into raw")
    tokens = shlex.split(cmd, comments=True)
    for i, tok in enumerate(tokens):
        if tok.split("/")[-1] in DESTRUCTIVE:
            if any(arg.startswith(RAW_PREFIX) for arg in tokens[i+1:]): deny("destructive op on raw")
print(json.dumps({"decision": "allow"}))
```

### Hook 2: Cross-project access guard (`PreToolUse`)

**Purpose:** refuse tool calls that touch other projects' repos or data dirs when the member isn't in their MEMBERS.

**Trigger:** every tool call that takes a file path (Read, Write, Edit, Glob, Grep, Bash, NotebookEdit).

**Logic:**
- Identify each path argument in the tool call.
- For each path, check if it's inside another Murmurent project's repo (`~/repos/<other>/`) or data dir (`/data/lab_vm/{raw,refined}/<other>/`).
- For each such "foreign" path, fetch the MEMBERS file of that project (cached locally for 5 min).
- If the current member's GitHub handle isn't in MEMBERS, deny.
- The active project itself is always allowed (no MEMBERS lookup needed; CC was started inside it).

**Edge cases:**
- A project with no MEMBERS file (legacy or external repo) is treated as "no access": fail closed.
- Symlinks are resolved before checking.
- Paths inside `~/.claude/`, `~/.config/`, or other infrastructure dirs are exempt.

### Hook 3: Audit log (`PostToolUse`)

**Purpose:** record every tool call locally for member-side audit; periodically upload an encrypted digest to the lab-management repo.

**Trigger:** every tool call (after execution).

**Logic:**
- Append a single jsonl line to `~/.claude/murmurent-audit/YYYY-MM-DD.log`:

```json
{"ts": "2026-05-06T10:14:22Z", "member": "@the_pi", "project": "brca_imaging",
 "tool": "Bash", "args_summary": "git push origin member/...", "outcome": "ok",
 "duration_ms": 412}
```

- A nightly cron (or a `Stop` hook) bundles `YYYY-MM-DD.log`, encrypts it with `age` to the PI + member age public keys, and pushes to `lab-mgmt-repo/audit/<handle>/<date>.log.age`.
- Members can read their own logs; PI can read all (because PI has access to their own decrypted copy via the `age -r` recipient list).

### Hook 4: Secret leak prevention (`PreToolUse` + `PostToolUse`)

**Purpose:** catch accidental leak of API keys, age private keys, GitHub tokens, etc.

**Trigger:**
- `PreToolUse`: any tool call whose arguments could carry a secret outward (`Bash` invoking `curl/wget/ssh`, `WebFetch`, `mcp__slack__*post_message`, `Write` with a target outside the lab VM).
- `PostToolUse`: any tool call whose output is going back to the model.

**Logic:**
- Patterns: `age1[a-z0-9]{58}`, `AGE-SECRET-KEY-[A-Z0-9]+`, `sk-ant-[A-Za-z0-9_-]{90,}` (Anthropic API), `ghp_[A-Za-z0-9]{36}` (GitHub PAT), `xoxb-[A-Za-z0-9-]+` (Slack bot), `-----BEGIN ([A-Z ]+) PRIVATE KEY-----`.
- Pre-call: deny with a redacted message indicating the pattern type (not the value).
- Post-call: redact matches in the result before it returns to the model. Log a counter (number of redactions per session).

### Hook 5: Project context injection (`UserPromptSubmit`)

**Purpose:** when a user prompt is submitted inside a Murmurent project, inject relevant context as system reminders so the model has fresh awareness without the user having to re-explain.

**Trigger:** every user prompt submission.

**Logic:**
- Resolve the active project; if none, do nothing.
- Read `CHARTER.md` (just the first paragraph), `MEMBERS`, the member's role in the project squad, and a list of active SEAs assigned to or from the member.
- Prepend a `<system-reminder>` block to the prompt with this context.

**Output shape:**

```
<system-reminder>
Active project: brca_imaging (lead: @member_a)
Your role: member
Charter (excerpt): Integrate imaging features with clinical outcomes for breast cancer biopsies...
Active SEAs:
- incoming #43: segment 12 batch-3 slides (claimed, due 2026-05-12)
- outgoing #41: clinical metadata join (assigned to @member_b, in progress)
</system-reminder>
```

### Hook 6: Session summary (`Stop`)

**Purpose:** at session end, write a brief summary to the member's activity log; surface anything that should be acted on.

**Trigger:** session stop.

**Logic:**
- Compose a short summary: project worked on, files touched, tool calls counted, any errors or denied calls.
- Append to `~/.claude/murmurent-audit/sessions.log`.
- If the session touched files in an active SEA's delivery path, prompt the user (in CC's stop output) to consider marking the SEA `complete`.
- Never auto-pushes to git: surfacing the suggestion to the user is enough.

### Hook 7: Frozen-agent integrity check (session-start, via first `UserPromptSubmit`)

**Purpose:** ensure frozen agents are still symlinks to the registry version; refuse the session if a frozen agent has been turned into a local copy.

**Trigger:** first `UserPromptSubmit` of a session (skipped on subsequent prompts using a session-marker file).

**Logic:**
- For each agent in `~/.claude/agents/` whose registry version is `frozen`, verify the local file is a symlink and resolves to the registry path.
- If not, deny the prompt with a clear message: "Frozen agent `conscience` has been modified locally. Run `murmurent agent update` to restore." Refuse to continue.
- This catches the case where someone copied a frozen agent and modified it (intentional bypass attempt or accident).

### Settings.json registration

The Murmurent install script writes the seven hooks into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {"match": {"tool_name": "Write|Edit|Bash|NotebookEdit"},
       "command": ["python3", "~/.claude/hooks/raw_guard.py"]},
      {"match": {"tool_name": "*"},
       "command": ["python3", "~/.claude/hooks/xproject_guard.py"]},
      {"match": {"tool_name": "Bash|WebFetch|Write|mcp__slack__*"},
       "command": ["python3", "~/.claude/hooks/secrets_pre.py"]}
    ],
    "PostToolUse": [
      {"match": {"tool_name": "*"},
       "command": ["python3", "~/.claude/hooks/audit.py"]},
      {"match": {"tool_name": "*"},
       "command": ["python3", "~/.claude/hooks/secrets_post.py"]}
    ],
    "UserPromptSubmit": [
      {"command": ["python3", "~/.claude/hooks/context_inject.py"]},
      {"command": ["python3", "~/.claude/hooks/frozen_check.py"]}
    ],
    "Stop": [
      {"command": ["python3", "~/.claude/hooks/session_summary.py"]}
    ]
  }
}
```

### Failure modes and degradation

- If a hook script crashes, CC sees no decision and proceeds with the default permission. To prevent silent degradation, hooks log to `~/.claude/murmurent-audit/hook-errors.log`; `murmurent doctor` checks the log size and warns if hooks are failing.
- Lab-management repo unreachable: hooks fall back to local cached MEMBERS / config files. Stale by up to 5 minutes. The active project's MEMBERS is always available because the project is cloned locally.

## Tool allowlists per agent (gap #2, design)

Each agent declares the tools it actually needs in frontmatter; the install tooling enforces this at two layers: the agent's own `tools:` field (which CC respects per-agent) and the global `~/.claude/settings.json` `permissions` (which is the user-prompt gate).

### Agent frontmatter additions

Two new fields:

- `required_tools`: minimum set the agent needs to do its job. Translated to the CC `tools:` field on the installed agent.
- `denied_tools`: tools this agent must never invoke, even if the global permissions allow them. Subtracted from `tools:`.

Example:

```yaml
---
name: bookworm
freeze: personal
description: Literature and database specialist
required_tools:
  - Read
  - Grep
  - Glob
  - WebFetch
  - WebSearch
  - mcp__zotero__*
  - mcp__oracle__*
denied_tools:
  - Bash
  - Write
  - Edit
  - NotebookEdit
defaults:
  citation_style: nature
  zotero_collection: my_lab
---
```

A bookworm should never need Bash; if a session is running bookworm and somehow invokes Bash, that indicates a bug.

### Generation of settings.json

`murmurent install` reads `required_tools` and `denied_tools` for every installed agent and produces:

- **Agent definitions**: when copying or symlinking an agent into `~/.claude/agents/<name>.md`, ensures the file's `tools:` field is exactly `required_tools - denied_tools`. (For symlinks to frozen agents, the registry definition already has the right `tools:`; install verifies.)
- **`~/.claude/settings.json` `permissions.allow`**: the union of all installed agents' `required_tools`. These tools are auto-allowed (no user prompt) globally, because some installed agent legitimately needs them.
- **`~/.claude/settings.json` `permissions.deny`**: a baseline list of inherently risky patterns that no Murmurent agent should ever invoke:

```json
"deny": [
  "Bash(rm -rf *)",
  "Bash(git push --force *)",
  "Bash(git push -f *)",
  "Bash(curl * | sh)",
  "Bash(wget * | sh)",
  "Write($MURMURENT_LAB_VM_ROOT/raw/**)",
  "Edit($MURMURENT_LAB_VM_ROOT/raw/**)",
  "Bash(chmod +w $MURMURENT_LAB_VM_ROOT/raw/**)"
]
```

These deny rules trip before hooks fire, providing a redundant safeguard against the most consequential cases.

### Audit during install

`murmurent install` performs a sanity pass over each agent's declared tools:

- Warn if an agent declares `Bash` without also declaring at least one specific Bash pattern in `denied_tools` to scope risk.
- Warn if an agent declares broad `mcp__*` wildcards rather than specific MCP server prefixes.
- Refuse if an agent declares a tool that doesn't exist in the harness or any registered MCP server.

### Drift detection

`murmurent doctor` compares the installed agents' actual `tools:` with the declared `required_tools - denied_tools`. Drift on a personal agent is reported (members may have intentionally edited). Drift on a frozen agent is a hard error: frozen agents must match the registry exactly.

### Why this layout

- **Agent-level `tools:`** is the authoritative restriction on what one agent can do. CC honours it per-agent.
- **Global `permissions.allow`** is about user-experience: it suppresses prompts for tools that any installed agent legitimately uses. Without it, the user is asked to approve every Read.
- **Global `permissions.deny`** is the always-on safety net regardless of agent.
- **Hooks** are the dynamic protection layer that responds to context the static lists can't capture (cross-project paths, secret patterns, raw-data writes via Bash).

Layered together: static permission lists block the obvious; hooks block the contextual; the audit log records what happened either way.

## Server-side security (gaps #3–#7, design)

These five gaps cover the layers below the assistant: audit log integrity, authentication between members and MCP servers, secret handling, lab VM access, and at-rest encryption. Designed so ordinary projects pay a small overhead while sensitive projects can lock down further (see [Sensitivity tiers](#sensitivity-tiers-and-project-level-controls)).

### Gap #3: Audit log integrity

The audit trail is only as good as our ability to prove it wasn't rewritten.

- **Signed commits** required on the lab-management repo and every project repo (gpg or sigstore). Branch protection rejects unsigned commits to `main`.
- **Branch protection**: no force-push, no history rewrite, no merge without review on `main` of any murmurent-managed repo.
- **Tamper-evident chain** for sensitive projects: each audit-log entry includes the SHA-256 of the previous entry. `murmurent audit verify <repo>` walks the chain and validates both signatures and hashes; breaks are reported explicitly.
- **Retention** controlled by REB approval. Default 10 years post-publication (Tri-Council guidance), longer if the REB requires. Archive-encrypted bundles outlive the project repo.

For non-sensitive projects: signed commits + branch protection are enough. The chain is unnecessary.

### Gap #4: Cross-MCP authentication

The inventory MCP treats the caller as `lab_manager` only by assertion. That needs enforcement.

- **Murmurent session token** at session start: a JWT-equivalent signed by the member's age private key. Issued by `murmurent install` / `murmurent onboard`; refreshed on session start.
- **TTL by sensitivity**: 8 hours for `standard` projects; 4 hours for `restricted`; 15 minutes with explicit refresh for `clinical`.
- **MCP-side verification**: each MCP server caches the public-key registry from `lab-mgmt-repo/keys/` and verifies the token's signature on every call. Role checks happen inside the MCP: `inventory_set` reads the caller's identity from the token, looks up the role registry, refuses if not `lab_manager`.
- **Server-side log** on every MCP host plus the existing per-member audit log.
- **2FA on token issuance** for any project at `clinical` sensitivity: TOTP / YubiKey challenge before the token is issued.

This makes "PI-only" enforced by the MCP rather than only advised by the CLI.

### Gap #5: Secret management

Three tiers, three storage strategies:

- **Personal** (member API keys, age private keys): `~/.config/murmurent/secrets/` (file mode 600), wrapped by macOS Keychain or 1Password where available. Never committed anywhere. Rotated on device loss.
- **Group-shared** (lab VM service tokens, group API keys, group's age archive key): `lab-mgmt-repo/secrets/<name>.age`, encrypted with `age` to the role-holders authorised for the secret. Rotated every 90 days for active services; immediately on member release.
- **Project-scoped** (project API keys, third-party tokens): in the project repo as `secrets/<name>.age`, encrypted to project MEMBERS. Rotated on member release.

Enforcement:
- A **git pre-commit hook** in every Murmurent repo blocks plaintext secret patterns (extending the secret-leak hook in gap #1).
- `murmurent secret rotate <scope> <name>` rotates and re-encrypts.
- For `clinical` projects, any secret touching PHI requires PI sign-off (PR review on the encrypted blob) at creation and at every rotation.

### Gap #6: Lab VM authentication

- **SSH keys only**, no passwords. Public keys at `lab-mgmt-repo/ssh_keys/<handle>.pub`.
- **Per-member accounts** on the VM (no shared accounts); UID matches GitHub handle where possible.
- **Nightly key sync** (Ansible-style script) deploys keys to the VM. Removal on offboard happens immediately, not on next sync.
- **Time-bounded keys**: `pi-collab` and `visitor` profile keys carry an `expires_at` that the sync respects.
- **2FA for sensitive projects**: any account with access to a `clinical` project's data dirs is forced to TOTP / YubiKey on top of the SSH key.
- **VPN-only from outside the institution**. The institutional VPN is the perimeter.
- **Connection log** on the VM, mirrored to the lab-management repo's audit area nightly (encrypted with `age`).

### Gap #7: Encryption at rest

- **Lab VM full-disk encryption** with LUKS. `/data/lab_vm/` partition unlocked at boot via TPM + admin passphrase.
- **Per-project FS keys for `clinical` projects**: data lives in a dedicated encrypted volume `/data/lab_vm/clinical/<project>/`, mounted only when the project is active. Key held by PI plus one trustee.
- **Encrypted backups**: rclone or duplicity wrapping the data with `age` envelopes. Backup keys held offline.
- **Project repos**: GitHub's at-rest encryption suffices for `standard`; `restricted` adds age-encrypted off-VM artefacts; `clinical` keeps data out of the repo entirely (see Sensitivity tiers).

## Sensitivity tiers and project-level controls

Each project declares a sensitivity tier in its `CHARTER.md` frontmatter. The tier is **project-level**: projects in the same group can be at different tiers. Tiers govern which controls apply to whom.

### Tier definitions

| Tier | Examples | Controls layered on `standard` |
|---|---|---|
| `standard` | Most basic-research projects | (baseline: signed commits, branch protection, MEMBERS-scoped repos, age for off-VM transfer) |
| `restricted` | Unpublished collaborator data, IP-sensitive work | + per-project secret keys; off-VM artefacts must be age-encrypted; 4-hour MCP token TTL |
| `clinical` | PHI / human-subject regulated data | + REB number in CHARTER, TCPS 2 (CORE-2022) certification per member with annual renewal, **no data in the repo** (only methods/code), per-project encrypted FS volume, 2FA SSH, 15-minute MCP token TTL with TOTP refresh, PHI pattern detection in hooks, BAA-tier API or de-identification mandatory for any LLM-mediated step |

### Policy file

The control-per-tier matrix is single-sourced at `murmurent/sensitivity-policy.yaml` (centre default), with lab override at `lab-mgmt-repo/sensitivity-policy.yaml`. Adding a new tier or amending controls is a PR.

```yaml
# murmurent/sensitivity-policy.yaml (excerpt)
tiers:
  standard:
    mcp_token_ttl: 8h
    data_in_repo: allowed
    ssh_2fa: false
  restricted:
    mcp_token_ttl: 4h
    off_vm_must_be_age_encrypted: true
    ssh_2fa: false
  clinical:
    mcp_token_ttl: 15m
    mcp_token_2fa: true
    data_in_repo: forbidden
    fs_encryption: per_project_volume
    ssh_2fa: true
    member_certifications_required: [tcps2_core_2022]
    api_constraint: baa_or_deidentified
```

### CHARTER frontmatter

A `clinical` charter must declare additional fields:

```yaml
---
project: brca_clinical_imaging
lead: '@member_a'
sensitivity: clinical
reb_number: WREM-2026-0142
reb_expires: 2027-08-01
data_residency: ca
---
```

`murmurent project new` validates these; CI re-validates on every charter change.

### Sensitive-project-mode controls in detail

For `sensitivity: clinical`:

- **No data in repo**: notebook frontmatter's `raw_data:` and `refined_data:` paths point only to lab VM locations. Checksums also stay on the VM, not in the repo. A pre-commit hook refuses commits that introduce data files into a clinical repo.
- **Per-project encrypted volume** on lab VM. Mounted only while the project is active; unmounted on session end.
- **PHI pattern detection** extends the secret-leak hook with patterns: OHIP (10-digit + 2-letter version code), MRN-style identifiers, SIN, DOB-near-name proximity. Outbound calls (WebFetch, mcp__slack, Anthropic API) refuse to send any prompt or argument matching these patterns.
- **Member certifications**: each clinical-project member holds current TCPS 2 (CORE-2022) certification, recorded in `lab-mgmt-repo/members/<handle>.md` with expiry date. Auto-revocation on expiry.
- **REB-bounded access**: when the REB approval expires or amends, member access auto-pauses pending re-approval.
- **`murmurent breach <project> --description <text>`**: opens an incident in the lab-management repo, notifies PI immediately, starts the PHIPA 24-hour clock, drafts the IPC notification.

### Honest flag: LLM API and PHI

Sending any PHI-containing prompt to the Claude API itself violates PHIPA unless on Anthropic Enterprise with a BAA-equivalent and verified Canadian residency. Three options, usually combined:

- **De-identify aggressively** before any prompt; hooks enforce by refusing prompts matching PHI patterns.
- **Anthropic Enterprise tier with BAA / equivalent**, with verified residency.
- **Keep data-touching analyses outside CC**: CC handles methods, code, deliberations, and writing; the actual PHI-touching analysis runs locally on the lab VM without LLM mediation.

This is a constraint of using any LLM tool on regulated data rather than a Murmurent limitation.

### Dashboard reflection: required vs elected

Each member's dashboard adds a **Security and compliance** panel:

- **Per-project block**: sensitivity badge, the controls required for that tier, the member's compliance status (TCPS 2 certified ✓, TOTP enrolled ✓, signing key registered ✓, etc.). Missing required controls show in red.
- **Outstanding required**: aggregated list of any required control the member doesn't currently satisfy. Clicking takes them to the action that resolves it.
- **Elected upgrades**: members can opt into stricter controls than required (e.g. always-on 2FA, always age-encrypt off-VM artefacts even for standard projects). Toggles on the dashboard; persisted in the personal preferences profile.
- **PI view**: across-all-clinical-projects compliance grid; flags members whose certifications are expiring or expired.

The required-vs-elected distinction is enforced: a member cannot opt out of a control their project requires, but can layer stricter controls on top.

### CLI

| Command | Effect | Authority |
|---|---|---|
| `murmurent project sensitivity <project> [--set <tier>]` | Read or change a project's sensitivity tier | PI (raising tier always allowed; lowering requires PR + audit) |
| `murmurent compliance status [--project <p>]` | Show your compliance state | Member |
| `murmurent compliance certify <cert-name> --expires <date>` | Record a certification (e.g. TCPS 2) | Member; verified by PI |
| `murmurent audit verify <repo>` | Walk the audit chain, verify signatures and hash chain | Anyone with repo access |
| `murmurent secret rotate <scope> <name>` | Rotate and re-encrypt a secret | Scope-appropriate authority |
| `murmurent breach <project> --description <text>` | Open a breach incident; start PHIPA clock | Any project member |

## Open questions

- Interaction between this group-level design and the (separate) center- and factory-level designs.
- Hooks and permissions design pass (see dedicated section above).

## Glossary

- **Project**: highest unit of work in the group. Has a single lead, a charter, and one or more repos. Multi-person, multi-experiment, accumulates semi-structured data. (Replaces the earlier term "investigation".)
- **Repo**: a lab-convention repository (`~/repos/<name>/` with `exp/<n>_<slug>/` inside). One or more per project.
- **Experiment**: a unit of work within a project repo. Lives in `exp/<integer>_<good_name>/` (per the lab's project-structure convention); date is in the notebook frontmatter. Has its own `notebook.md` entry.
- **SEA**: Skill, Experiment, or Analysis. Atomic, callable unit of service exchanged between people, groups, factories. Multiple per experiment; sometimes free-standing.
- **SEA verbs**: `request`, `claim`, `complete`, `decline`.
- **Squad**: subgroup that performs a project, experiment, or SEA. Has a lead and members. Nestable.
- **Lead**: the member responsible for a squad's progress. Distinct from PI.
- **Notebook entry**: the `notebook.md` inside an experiment folder; markdown with required frontmatter and embedded media.
- **Charter**: one-paragraph statement of purpose and scope, committed as `CHARTER.md` in a project repo.
- **MEMBERS**: file in a project repo enumerating participants with access.
- **Verb**: an action a member performs that touches group artefacts.
- **Role**: a group-level agent assignment held by a specific member, with cardinality and audit.
- **Operator**: the member currently running a role's agent.
- **Codev**: code development via git / GitHub PR review.
- **Frozen agent**: must run from the group-registry version (no per-member drift). Default for safety-critical agents; forced for bots.
- **Personal agent**: members may copy and modify locally. Default for stylistic agents.
- **Freeze cascade**: the resolution order for an agent's effective freeze flag: bot pin → role override → registry default.
- **Lab-management repo**: the group-scoped repo that holds roles, inventory, audit logs, dashboards, squad registry, and the project registry. Distinct from per-project repos.
- **Choreography**: a recurring multi-actor pattern with a documented recipe. Adopted by a project via `choreography:` in its CHARTER frontmatter.
- **Finalisation choreography**: multi-scope deliberation ritual (SEA / experiment / project): `examine` → `conclude`. Always produces a deliberation document; optionally a finding.
- **Deliberation document**: markdown artefact produced by the finalisation choreography. Contains agent contributions, member reflections, group-oracle context, an attempted statement (which may or may not be a clean consensus), caveats, dissent, and approval log.
- **examine / conclude**: the two analysis-track stages following operational `complete`. `analysis_status: not_started → examined → concluded`.
- **Operational status vs analysis status**: two parallel state tracks on every SEA / experiment / project. Operational tracks the work; analysis tracks the deliberation.
- **Dashboard**: markdown snapshot + Streamlit app showing each member's agents, squads, SEAs, **outstanding analysis**, and (for PIs) group-wide audit/accounting/compute.
- **Discussion**: persistent record of a meeting / Slack thread / async deliberation, filed at `discussions/<date>_<topic>.md` with outcome (decided / open / blocked / tabled).
- **Protocol**: codified procedure for a wet or dry experiment. Project- / group- / centre-scoped.
- **Skill**: a Claude Code-discoverable instruction set, invoked by name. Group- or centre-scoped.
- **Freeze**: immutable snapshot of a project at a point in time: git tag + manifest + age-encrypted bundle. Used for paper / thesis / grant submission moments.
- **oracle_curator**: group-level role responsible for facilitating finalisation choreographies and handling periodic legacy maintenance (cross-reference health, citation rot, tag drift). Quotaed to 2; annual rotation.
- **Standardised vocabulary**: controlled list of cross-cutting `defaults` field names documented at `murmurent/preferences.md`; guilds extend via `murmurent/guilds/<group>/preferences.md`. Used for fields multiple agents share (plotting, citation_style, prose_style, etc.).
- **Personal preferences profile**: `~/.claude/murmurent-preferences.yaml`, local to each member's machine, sets standardised fields once for all `personal` agents. Never committed to group repos.
- **Onboarding profile**: YAML+markdown spec at `murmurent/onboarding/<profile>.md` (centre default) or `lab-mgmt-repo/onboarding/<profile>.md` (lab override) bundling agents-to-install, default permissions, lead eligibility, and expiry for a class of new member. Four centre defaults: `student`, `postdoc`, `pi-collab`, `visitor`. Cores are themselves groups, not profiles within a group.
- **Sensitivity tier**: project-level property declared in `CHARTER.md` frontmatter: `standard` / `restricted` / `clinical`. Controls per tier defined in `murmurent/sensitivity-policy.yaml`. Projects in the same group can be at different tiers.
- **PHIPA / TCPS 2 / REB**: Personal Health Information Protection Act (Ontario), Tri-Council Policy Statement on research ethics, Research Ethics Board. Together they govern `clinical` projects.
- **Required vs elected controls**: required controls come from a project's sensitivity tier; elected controls are stricter-than-required preferences a member opts into. Members cannot opt out of required.
