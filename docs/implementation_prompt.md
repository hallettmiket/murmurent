---
date: 2026-05-06
tags: [murmurent, prompt]
---

# Implementation prompt for Claude Code

> Hand this to Claude Code in a session opened at `~/repos/murmurent/`. It is the v1 scope for a smoke-test tutorial of murmurent at the group level.

## Read first

Before writing anything, read the design docs that this prompt is derived from. They are the source of truth — implement what they say; flag any deviation:

- [[group_level]] — full group-level design
- [[cli_manual]] — CLI surface
- [[diagrams]] — architecture diagrams (Mermaid)

The lab's global rules at `~/.claude/rules/` (code style, data storage, project structure, documentation) also apply.

## What we are building

A working smoke-test of the murmurent group-level design. Two real students will use it to walk through fake projects, find issues, and validate the design. Everything is fake — no real PHI, no real cross-group communication, no real security infrastructure. The smoke test is a faithful exercise of the design's *shape*; it is not a regulated production system.

## Cast (fake)

- `@mike` — PI (the user)
- `@allie` — postdoc, often a project lead
- `@bob` — senior PhD
- `@cassie` — junior PhD

## Two projects (fake)

**`dcis_sc_tutorial`** — clinical sensitivity. Charter declares:
- `sensitivity: clinical`
- `reb_number: WREM-2026-9999`
- `reb_expires: 2027-09-01`
- `data_residency: ca`
- `lead: '@allie'`
- `members: ['@mike', '@allie', '@bob', '@cassie']`
- `choreography: clinical_cohort`

Four experiments pre-scaffolded:

| Path | Lead | `status` | `analysis_status` |
|---|---|---|---|
| `exp/1_sample_qc/` | @allie | complete | examined |
| `exp/2_alignment_count_matrix/` | @bob | running | not_started |
| `exp/3_clustering/` | @cassie | planned | not_started |
| `exp/4_clinical_associations/` | @allie | planned | not_started |

**`bbb_drug_screen`** — standard sensitivity. Charter:
- `sensitivity: standard`
- `lead: '@bob'`
- `members: ['@mike', '@bob', '@allie']`
- `choreography: drug_discovery_litl`

One experiment:

| Path | Lead | `status` | `analysis_status` |
|---|---|---|---|
| `exp/1_pharmacophore_alignment/` | @bob | complete | concluded |

## Pre-seeded SEAs

In `dcis_sc_tutorial`:

| id | from | to | description | state |
|---|---|---|---|---|
| 1 | @allie | @bob | Re-generate count matrix with GRCh38.p14 + GENCODE 47 | claimed, in progress |
| 2 | @bob | @cassie | UMAPs coloured by ER, PR, grade | requested, unclaimed |
| 3 | @allie | @mike | Review statistical assumptions in DE pipeline | claimed, complete, awaiting examine |
| 4 | @cassie | @allie | Interpret cluster 7 marker genes — macrophages or DCs? | open |
| 5 | @allie | @bob | scVI vs Harmony batch-correction comparison | declined (out of scope for v1) |

In `bbb_drug_screen`:

| id | from | to | description | state |
|---|---|---|---|---|
| 10 | @bob | @allie | Pharmacophore alignment for compound set 3 | complete, finalised |

## Pre-seeded inventory (lab-mgmt repo)

| name | type | status | notes |
|---|---|---|---|
| `anti_cd31` | antibody | in_stock | expiry 2027-03-01 |
| `4_oht` | small molecule | expired | expiry 2026-04-01 (red) |
| `nebnext_kit` | library prep | low | yellow |
| `dapi` | stain | in_stock | plenty |
| `dmso` | solvent | in_stock | plenty |
| `livedead_stain` | viability | in_stock | expires in 14 days (yellow) |

## Compliance state to fake

- @allie: TCPS 2 ✓, TOTP ✓, signing key ✓ — green
- @bob: TCPS 2 expires in 30 days — yellow
- @cassie: TCPS 2 missing — red (would block `dcis_sc_tutorial` access in production; flag visually only in v1)
- @mike: all green; PI dashboard surfaces Cassie's red status

## Tech stack

- Python 3.12; `uv` for dependencies.
- `click` for the CLI.
- `pytest` for tests.
- `streamlit` for the dashboard viewer.
- Anthropic's `mcp` Python SDK for the inventory MCP server.
- Simulated lab VM at `~/lab_vm/data/{raw, refined, clinical}`. Use env var `MURMURENT_LAB_VM_ROOT` (default `~/lab_vm/data`) so production can swap to `/data/lab_vm/`.

### Repos and GitHub

All four repos live at `~/repos/<name>/` locally **and** are pushed to GitHub under the `hallettmiket` org:

| Local | GitHub | State |
|---|---|---|
| `~/repos/murmurent/` | `hallettmiket/murmurent` | Already exists (currently has design docs + assets); add the CLI, agents, choreographies, scripts on a feature branch, PR to main when ready |
| `~/repos/lab_mgmt/` | `hallettmiket/lab_mgmt` | New; created by seed script via `gh repo create --private` |
| `~/repos/dcis_sc_tutorial/` | `hallettmiket/dcis_sc_tutorial` | New; created by seed script; private |
| `~/repos/bbb_drug_screen/` | `hallettmiket/bbb_drug_screen` | New; created by seed script; private |

Use `gh` CLI for repo creation, branch pushes, and PR opens. Verify `gh auth status` is healthy before starting Phase 1; document any setup the user has to do (e.g. `gh auth login`).

For the existing `murmurent` repo: do not force-push or rewrite history. Add new code on a feature branch (`feat/cli-v1` or similar), push, and open a PR for review. The user merges manually.

For the three new repos: seed script creates them, pushes initial commit, sets default branch to `main`, applies branch protection (no direct push to `main`; PR required) where the user's permissions allow.

## v1 scope — build these

### CLI subcommands (functional)

- `murmurent install`, `murmurent onboard`, `murmurent doctor`
- `murmurent project list / describe / new / admit`
- `murmurent project sensitivity <p> [--set <tier>]`
- `murmurent experiment new / list / ingest`
- `murmurent sea request / list / claim / complete / decline`
- `murmurent sea examine / conclude`
- `murmurent finalize <scope> <id>`
- `murmurent push` (with `--finalize`)
- `murmurent dashboard` (and `--snapshot`, `--outstanding`)
- `murmurent compliance status`
- `murmurent preference show / set`
- `murmurent agent list`

Other subcommands referenced in the design may stub out with a clear "not implemented in v1" message.

### Hooks

Deployed to `~/.claude/hooks/`, registered in `~/.claude/settings.json`:

1. **Raw-data guard** (`PreToolUse`, matches `Write|Edit|Bash|NotebookEdit`): refuses tool calls that mutate paths under `$MURMURENT_LAB_VM_ROOT/raw/`.
2. **Project-context injection** (`UserPromptSubmit`): walks cwd to find active project (marker: `CHARTER.md`), reads charter, MEMBERS, active SEAs, prepends as `<system-reminder>`.
3. **PHI pattern detection** (`PreToolUse` + `PostToolUse`, only when active project's `sensitivity == clinical`): refuses outbound prompts containing OHIP-shaped, MRN-shaped, SIN-shaped, or DOB-near-name patterns; redacts in returned content.
4. **Audit log** (`PostToolUse`): appends jsonl per call to `~/.claude/murmurent-audit/YYYY-MM-DD.log`.

### MCP server

Inventory MCP at `src/murmurent/mcp/inventory_server.py`. Tools:
- `inventory_list(filter)` — supports `low`, `expiring <days>`, `out`.
- `inventory_show(name)`.
- `inventory_provision(plan_path)` — reads frontmatter `reagents:` from a notebook entry, intersects with inventory, returns gaps and expiring lots.
- `inventory_set(name, fields)` — lab_manager only (v1: hardcode `@mike`).
- `inventory_add(name, vendor, catalog_no, ...)` — lab_manager only.
- `inventory_order(name)` — lab_manager only; opens an order issue file.

Register in `~/.claude/settings.json` under `mcpServers`. Wraps the markdown files in `lab_mgmt/inventory/`.

### Dashboard

- **Snapshot generator** (Python script): walks lab-mgmt repo, both project repos, and the simulated lab VM; produces `lab_mgmt/dashboards/<handle>.md` for each member with all panels populated. Idempotent.
- **Streamlit viewer**: reads the snapshot, calls inventory MCP live for the inventory panel; renders Outstanding analysis (yellow at >2 weeks since `complete` and not `examined`; red at >2 months); renders Security and compliance with red for missing required.
- Member view by default; PI view auto-enabled when run as `@mike` (env var `MURMURENT_USER`).
- `murmurent dashboard` opens Streamlit on localhost.
- `murmurent dashboard --snapshot` prints the markdown.
- `murmurent dashboard --outstanding` prints the Outstanding analysis section as a terminal summary.

### Seed script

`scripts/seed_tutorial.py`. Idempotent. Run once to populate everything locally **and** push to GitHub:

- Creates the three new GitHub repos (`lab_mgmt`, `dcis_sc_tutorial`, `bbb_drug_screen`) under `hallettmiket` via `gh repo create --private` if they don't already exist.
- `~/repos/lab_mgmt/` with all directories (`members/`, `keys/`, `inventory/`, `projects/`, `dashboards/`, `audit/`, `roles/`, `onboarding/`).
- Member files for the four personas.
- Dummy age public keys (use `age-keygen` once per persona; commit publics, store privates locally).
- Project registry entries.
- The two project repos with `CHARTER.md`, `MEMBERS`, the lab project layout (`exp/`, `src/`, `findings/`, `obsolete/`, `data/`, `seas/`, `deliberations/`).
- All five experiments scaffolded with `notebook.md` in the right `status` / `analysis_status` states.
- All six SEAs pre-populated as registry files in `<project>/seas/<id>.md`.
- For SEAs in the `awaiting examine` or `complete, finalised` states: a partially or fully filled deliberation document.
- Inventory items.
- Fake data files in the simulated lab VM:
  - Fake FASTQ for `dcis_sc_tutorial/1_sample_qc/` — random-base sequences in valid `.fastq.gz` format.
  - Fake count matrix CSV.
  - Fake clinicopathology table with clearly-fake OHIP strings (`0000-000-001`, `0000-000-002`, ...) and fake clinical fields (grade, ER, PR).
  - Fake compound table for `bbb_drug_screen`.
- After local creation, the seed script `git init`/`git add`/`git commit`/`git push -u origin main` for each new repo. The `murmurent` repo (already on GitHub) gets new code on a feature branch with a PR opened, not direct-to-main.

### Tutorial document

`~/repos/murmurent/TUTORIAL.md`. Day-by-day walkthrough:

- **Day 1 (each student solo)**: `murmurent install`; explore the dashboard; locate both project repos; understand `MEMBERS`.
- **Day 2 (each student solo)**: claim a pre-seeded SEA; do (synthetic) work; push to personal branch; open PR.
- **Day 3 (collaborative, all three online)**: finalise SEA #3 (Allie's methodology review with Mike). Each squad member invokes the relevant CC agents to fill the deliberation document. Squad approves. Statement promoted to a finding.
- **Day 4 (deliberate breakage)**: try to paste fake OHIP into a `dcis_sc_tutorial` prompt; try to write to a raw-data path; try to read another project's repo as a non-member.
- **Day 5 (debrief)**: file smoke-test issues using the template at `SMOKE_TEST_ISSUES_TEMPLATE.md`.

## Defer to v2 (do not build)

- Squad CLI (squads exist as concepts; for v1 the project's MEMBERS *is* the project squad).
- Role assignment CLI (roles are static, set in the seed script).
- `discuss`, `teach`, `freeze` verbs (mention in tutorial; do not implement).
- `breach`, `audit verify`, `secret rotate` (mention; do not implement).
- Real `age` encryption flow beyond key generation (the keys are placeholders).
- Real cross-group SEAs / federation.
- Automated agent invocation during `examine` — students invoke each agent manually in their CC session and paste the contribution into the deliberation document. This is intentional for v1; it exercises each agent live.
- Group oracle as a real MCP (oracle is a folder of markdown files in lab-mgmt-repo; auto-publish on PR merge writes a file there).
- Onboarding profile installer beyond what `seed_tutorial.py` provides.
- The 5 server-side security gaps (audit-log integrity, cross-MCP auth, secret management, lab-VM auth, encryption-at-rest) — design exists, defer implementation.

## Acceptance criteria

The smoke test passes when each of these stories runs end-to-end:

1. Each persona's CC instance can run `murmurent install`, then `murmurent dashboard` and see their populated dashboard.
2. As @bob, claim SEA #1 (already claimed in seed; verify behaviour for already-claimed), work in `exp/2_alignment_count_matrix/`, run a fake analysis script, push to a personal branch.
3. As @allie, run `murmurent sea examine 3`; the deliberation document is scaffolded with empty agent-contribution sections; manually invoke bookworm and adversary in CC to fill in their sections; commit; run `murmurent sea conclude 3` and gather approvals.
4. As any persona inside `dcis_sc_tutorial`, paste the string `1234-567-890-AB` into a CC prompt — the PHI hook refuses with a clear message naming the pattern type.
5. As any persona, attempt to write to a file under `$MURMURENT_LAB_VM_ROOT/raw/dcis_sc_tutorial/` — the raw-data guard refuses with a clear message.
6. Inside CC in any persona's session, ask "what reagents do we have low or expiring?" — CC calls `inventory_list` via the MCP and reports correctly: `4_oht` expired, `nebnext_kit` low, `livedead_stain` expiring soon.
7. As @mike, run `murmurent dashboard` and see the PI compliance grid surface @cassie's missing TCPS 2 certification in red.
8. All four repos are visible at `https://github.com/hallettmiket/{murmurent, lab_mgmt, dcis_sc_tutorial, bbb_drug_screen}` (the latter three private), with the seed content committed.

## Build order

Use your judgement, but suggested order:

1. Python package skeleton; `murmurent --help` works; CI-friendly project layout.
2. Agent registry: port the seven `~/repos/generic_cc/agents/*.md` agents and add `security_guard.md`. Add the new frontmatter fields (`freeze`, `required_tools`, `denied_tools`, `defaults`).
3. Seed script: writes the lab-mgmt repo and the two project repos with all frontmatter, members, charters, inventory, SEAs, fake data.
4. Repo-discovery and frontmatter-parsing utilities.
5. Project + experiment + ingest commands. Raw-data guard hook.
6. Push mechanics. PR creation via `gh pr create`.
7. SEA commands + finalisation flow. Deliberation document templates.
8. Inventory MCP. PHI hook. Project-context injection hook. Audit log hook.
9. Dashboard snapshot generator and Streamlit viewer.
10. Tutorial doc, troubleshooting guide, issue template.

After each step, run pytest and verify the relevant acceptance-criteria story still works.

## Style notes

- Lab convention is in `~/.claude/rules/`. Follow it: type hints, snake_case, pathlib, f-strings, numpy-style docstrings. Run `black` and `isort` before commits.
- All file headers per `~/.claude/rules/documentation.md`.
- Versioning per the lab's integer-suffix rule when output files have multiple iterations.
- Don't add features beyond v1 scope; if something tempting appears, log it as a v2 issue and move on.
- Don't deviate from the design docs silently; if a design doc is wrong, flag it and propose an amendment.

## Operational notes

- All data is fake; clearly-fake values for any PHI-shaped patterns.
- The lab VM is simulated locally; document the production swap clearly in the tutorial.
- All repos are private on GitHub; verify `gh auth status` before the seed script runs.
- Branch protection is applied programmatically where `gh` permissions allow; documented manually otherwise in TUTORIAL.md.
- Anthropic API costs from the inventory MCP and finalisation choreography are minor (small calls); flag if usage looks unusual.
