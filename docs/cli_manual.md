---
date: 2026-05-05
tags: [wigamig, manual]
---

# Wigamig CLI — User Manual

> Working draft. Companion to [[group_level]] design.
> Updated as new commands emerge in the design conversation.
> Re-read in full before every edit; keep it consistent with [[group_level]].

## Overview

The wigamig CLI manages the configuration that lets your local Claude Code instance act as a member of a wigamig-enabled group. It does **not** run agents — it manages agent installation, group membership, role assignments, projects, and the day-to-day verbs that touch group artefacts.

Design choice: a thin CLI is preferred over a GUI until a concrete onboarding pain demands one.

## Conventions

- All commands accept `--help`.
- All mutating commands write an audit entry to the group's lab-management repo.
- The CLI uses your GitHub identity for attribution; assignments and approvals are signed where possible.
- Where a command is restricted (PI-only, lab_manager-only), this is enforced by the lab-management repo's branch-protection rules, not by the CLI alone — the CLI's check is a first line, not the final line.

## Installation

For **first-time** setup as a new member, use `wigamig onboard` (see the Onboarding section below) — it does install plus key generation, profile push, and PR.

For **subsequent** installs (e.g. on a second machine, or after a fresh OS) where the member is already registered:

```
wigamig install
```

Effects:
- Clones or updates the wigamig repo (default `~/repos/wigamig`).
- Creates `~/.claude/agents/` if absent.
- Symlinks `frozen` agents from the group registry; copies `personal` agents.
- Configures `~/.claude/settings.json` with group-derived permissions and MCP servers.
- Initialises `~/.claude/agent-memory/` for the agents installed.

`wigamig install` does **not** generate an age key or push a member profile — those are one-time onboarding events.

## Command reference

### Agents

| Command | Effect | Notes |
|---|---|---|
| `wigamig agent list [--group <g>]` | List available agents in the registry | Shows freeze flag |
| `wigamig agent add <name>` | Install an agent locally | Symlink if `frozen`, copy if `personal` |
| `wigamig agent remove <name>` | Uninstall an agent | Memory is preserved unless `--purge` |
| `wigamig agent update` | Pull latest registry; re-link frozen, leave personal alone | Reports drift on personal copies |

### Preferences

Personal preferences profile lives at `~/.claude/wigamig-preferences.yaml` (local; never committed to group repos). Sets standardised cross-cutting fields once across all installed `personal` agents. See [Tool preferences](group_level.md#tool-preferences-defaults--overrides) for the controlled vocabulary.

| Command | Effect |
|---|---|
| `wigamig preference show` | Print the effective preferences profile |
| `wigamig preference set <field> <value>` | Set a standardised field; warns if `<field>` is not in the centre + guild vocabulary |
| `wigamig preference unset <field>` | Remove a field (agents fall back to registry default) |
| `wigamig preference validate` | Check the profile + every installed agent's `defaults` against the controlled vocabulary; prints warnings (typos, unknown enum values, missing-but-expected fields) |

### Groups

| Command | Effect |
|---|---|
| `wigamig group list` | List groups visible from your identity |
| `wigamig group join <group>` | Request membership; PI approves |
| `wigamig group leave <group>` | Remove yourself from a group |

### Roles (PI-only commands marked)

| Command | Effect |
|---|---|
| `wigamig role list [--group <g>]` | List roles and current operators |
| `wigamig role describe <role>` | Print charter, cardinality, current operators |
| `wigamig role assign <role> <member>` *PI* | Open a role-transition issue |
| `wigamig role revoke <role> <member>` *PI* | Open a revoke issue |
| `wigamig role transfer <role> <from> <to>` *PI* | Open a transfer issue |
| `wigamig role ack <issue>` | Acknowledge a proposed assignment (proposed operator) |

### Projects

| Command | Effect |
|---|---|
| `wigamig project list` | List projects you are a member of |
| `wigamig project describe <name>` | Charter, MEMBERS, status |
| `wigamig project new <name> --charter <file> --members <list>` *PI/proposer* | Create a new project |
| `wigamig project members <name>` | Print MEMBERS |
| `wigamig project admit <name> <member>` *PI* | Add a member |
| `wigamig project release <name> <member>` *PI* | Remove a member |
| `wigamig project pause <name>` *PI* | Mark inactive |
| `wigamig project resume <name>` *PI* | Mark active |
| `wigamig project end <name> --reason <r>` *PI* | Terminal event |
| `wigamig project archive <name>` *PI* | Archive repo + data |

### Experiments

Experiments follow the lab project structure: `exp/<integer>_<slug>/` in the project repo, with raw and refined data on the lab VM.

| Command | Effect |
|---|---|
| `wigamig experiment new --project <project> --name <slug>` | Scaffold `exp/<next-int>_<slug>/` with `README.md`, `run_all.py` skeleton, `notebook.md` template; create `/data/lab_vm/wigamig/raw/<project>/<exp>/` and `/data/lab_vm/wigamig/refined/<project>/<exp>/`; open `notebook.md` in Obsidian |
| `wigamig experiment list [--project <project>]` | List experiments and their `status` |
| `wigamig experiment status <project> <slug> --set <state>` | Update the `status` field on a notebook entry |
| `wigamig experiment ingest <project> <slug> <source> [--instrument <t>] [--accept] [--dry-run]` | Classify files in `<source>` as raw vs derived (instrument profile + generic patterns), present for mandatory review, then copy: raw → `/data/lab_vm/wigamig/raw/<project>/<slug>/` (chmod a-w), derived → `.../refined/<project>/<slug>/instrument_outputs/`. Compute SHA-256; update `raw_data:`, `instrument_outputs:`, `checksums:` in `notebook.md`. See [Ingest classification](group_level.md#ingest-classification-raw-vs-derived). |
| `wigamig experiment attach <project> <slug> <file>` | Place a documentation file (photo of paper notebook page, sketch) into the appropriate subfolder; downsamples camera photos; never used for data files |

### Inventory

Inventory is served by the **`inventory` MCP server**, not by CLI subcommands. Any agent in CC calls these tools directly:

| Tool | Effect |
|---|---|
| `inventory_list(filter)` | List reagents matching a filter (`--low`, `--expiring <days>`) |
| `inventory_show(name)` | Print frontmatter + body |
| `inventory_provision(plan_path)` | Compute `plan ∩ inventory`; report gaps and expiring lots |
| `inventory_set(name, fields)` *lab_manager* | Update fields; auto-bumps `last_updated` |
| `inventory_add(name, vendor, catalog_no, ...)` *lab_manager* | Create a new reagent file |
| `inventory_order(name)` *lab_manager* | Open an order issue in the lab-management repo |

The `last_updated` field is set by the MCP on every write, by a pre-commit hook for direct edits, and by a GitHub Action on push as a backstop for web-UI edits.

### Squads (subgroups)

| Command | Effect | Authority |
|---|---|---|
| `wigamig squad form --scope <project\|experiment\|sea> --target <name> --lead @<handle> --members <list>` | Create a squad with a lead and members | PI for project; project lead for sub-squads |
| `wigamig squad list [--scope <s>] [--member @<h>]` | Browse squads | Anyone |
| `wigamig squad describe <name>` | Print charter, lead, members, audit | Anyone |
| `wigamig squad invite <name> @<handle>` | Propose adding a member | Lead |
| `wigamig squad release <name> @<handle>` | Remove a member | Lead |
| `wigamig squad transfer-lead <name> @<new>` | Open a lead-transfer issue | PI for project; project lead for sub |
| `wigamig squad dissolve <name>` | End the squad | Lead, with PI sign-off for project-level |
| `wigamig squad promote <name> --to <scope>` | Upgrade scope (e.g. experiment → project) | PI |

### SEAs

Operational verbs (request → claim → complete; see also Finalisation below):

| Command | Effect |
|---|---|
| `wigamig sea request --to <member-or-squad> --kind <skill\|experiment\|analysis> --description <...>` | File an SEA request |
| `wigamig sea list [--mine] [--incoming] [--outgoing]` | Browse SEAs |
| `wigamig sea claim <id>` | Declare you'll perform an offered SEA |
| `wigamig sea complete <id> --delivery <path>` | Mark operational completion with a delivery artefact |
| `wigamig sea decline <id> --reason <r>` | Refuse with reason |

### Finalisation (analysis stages)

The finalisation choreography runs at SEA / experiment / project scope. `<scope>` ∈ `sea`, `experiment`, `projects`.

| Command | Effect | Authority |
|---|---|---|
| `wigamig <scope> examine <id>` | Trigger common agents to write their sections of the deliberation document | Squad lead |
| `wigamig <scope> conclude <id> [--statement <path>]` | Close the deliberation; optionally promote a statement to a finding | Squad lead with squad approvals |
| `wigamig finalize <scope> <id>` | Umbrella: runs `examine` then `conclude` end-to-end | Squad lead |
| `wigamig <scope> reopen <id>` | Re-open a concluded deliberation (e.g. when new evidence arrives) | Squad lead; PI sign-off for project scope |

### Discussions

| Command | Effect | Authority |
|---|---|---|
| `wigamig discuss new --project <p> --topic <t> [--participants <list>]` | Scaffold `discussions/<date>_<topic>.md`, open in editor | Any project member |
| `wigamig discuss list [--project <p>] [--open]` | Browse discussions; `--open` filters to non-decided | Anyone |
| `wigamig discuss close <id> --outcome <decided\|open\|blocked\|tabled> [--decision <text>]` | Set the outcome on a discussion | Project lead (for `decided`) |

### Teach (protocols and skills)

| Command | Effect | Authority |
|---|---|---|
| `wigamig teach protocol --name <n> [--scope project\|group\|center] [--from-experiment <p> <e>]` | Scaffold a protocol; `--from-experiment` extracts a draft from a notebook entry | Author at project scope; group lead promotes to group; PI to centre |
| `wigamig teach skill --name <n> [--scope group\|center]` | Scaffold a Claude Code skill | Group lead at group scope; PI at centre |
| `wigamig teach promote <name> --to <wider-scope>` | Move a protocol or skill to a wider scope | Group lead / PI |

### Freeze

| Command | Effect | Authority |
|---|---|---|
| `wigamig freeze <project> --purpose <text> [--include-raw]` | Compute manifest, create tag, encrypt bundle. Tag created only after PI approves the manifest PR. | Project lead initiates; PI approves |
| `wigamig freeze list <project>` | List past freezes with their purposes and dates | Anyone with project access |
| `wigamig freeze restore <project> <tag> [--to <path>]` | Extract a freeze into a temp location for inspection (read-only; never modifies the live project) | Anyone with project access |

### Sensitivity and compliance

| Command | Effect | Authority |
|---|---|---|
| `wigamig project sensitivity <project> [--set <standard\|restricted\|clinical>]` | Read or change a project's sensitivity tier | PI; raising allowed; lowering requires PR + audit |
| `wigamig compliance status [--project <p>]` | Show your compliance state per project (required + elected controls; missing items in red) | Member |
| `wigamig compliance certify <cert-name> --expires <date>` | Record a certification (e.g. TCPS 2) on your member profile | Member; PI verifies |
| `wigamig audit verify <repo>` | Walk the audit chain, verify signatures and tamper-evident hash chain | Anyone with repo access |
| `wigamig secret rotate <scope> <name>` | Rotate and re-encrypt a secret (`personal`, `group`, or `project` scope) | Scope-appropriate authority |
| `wigamig breach <project> --description <text>` | Open a breach incident in the lab-management repo; notify PI; start the PHIPA 24-hour clock; draft the IPC notification | Any project member |

### Choreographies

Choreographies are CC skills, not CLI subcommands. Invoke them inside Claude Code:

- `choreography:list` — list available choreographies in centre, guild, and project scope.
- `choreography:apply <name> --to <project>` — scaffold a project against a choreography recipe.
- `choreography:status <project>` — report progress against the recipe.

### Dashboard

| Command | Effect |
|---|---|
| `wigamig dashboard` | Open the local Streamlit dashboard (includes the Outstanding analysis panel) |
| `wigamig dashboard --pi` | Open the PI view (rejected if you're not a PI); adds escalated-from-members nags |
| `wigamig dashboard --snapshot` | Print the latest markdown snapshot from the lab-management repo |
| `wigamig dashboard --outstanding` | Print only the Outstanding analysis panel (terminal-friendly summary) |

### Onboarding

| Command | Effect |
|---|---|
| `wigamig onboard <group> --profile <profile>` | One-shot setup for a new member: clone wigamig, install agents per profile, configure MCP, generate age key, push key + member profile via PR |
| `wigamig doctor` | Verify local install is healthy: agents present, MCP servers reachable, age key registered, group memberships visible |
| `wigamig offboard --member @<handle>` *PI* | Mirror of onboard: revoke roles, release from projects, archive age key, mark profile alumni |

### Verbs (day-to-day)

Note: `provision` is no longer a CLI command; it is a tool on the `inventory` MCP and is called from inside CC by any agent.

| Command | Effect |
|---|---|
| `wigamig push <project> [--message <m>]` | Push current branch as `member/<handle>/<topic>` (direct, no review) |
| `wigamig push <project> --finalize` | Open a PR from the personal branch to `main`; trigger bot + human reviews per path rules |
| `wigamig push <project> --refined <exp>` | Recompute checksums in `/data/lab_vm/wigamig/refined/<project>/<exp>/`, update notebook `refined_data` + `checksums`, push to personal branch |
| `wigamig pull <project>` | Fetch latest |
| `wigamig cite <reference>` | Resolve and insert a citation; checks group oracle |
| `wigamig audit <target>` | Invoke `adversary` on a path or PR |
| `wigamig publish <artefact> --to <oracle>` | Promote a finding to the group oracle |
| `wigamig request-sea --to <member> --kind <skill\|experiment\|analysis> --description <...>` | File an SEA request on the group request board |
| `wigamig review <PR-url>` | Open a review session |
| `wigamig capture` | Open `inbox/YYYY-MM-DD_HHMM.md` for a quick note |
| `wigamig triage` | Run `/process-inbox`-equivalent flow on `inbox/` |

## Examples

### First-time setup

```
$ wigamig onboard hallett --profile student
Cloning wigamig... done.
Installing agents (profile: student): bookworm, adversary, blacksmith, artist
  bookworm:    personal (copied)
  adversary:   frozen   (symlink)
  blacksmith:  personal (copied)
  artist:      personal (copied)
Configuring MCP servers: inventory, oracle, request_board
Generated age key. Public key: age1...
Opened PR #87 in lab_mgmt: "Onboard @newuser"

# (PI approves PR and runs `wigamig project admit` for each project in onboarding issue)

$ wigamig doctor
All checks passed.
```

### Daily flow on a project

```
$ wigamig pull dcis_imaging
# work in Claude Code on member/the_pi/qc-batch-3 ...
$ wigamig audit src/qc.py
$ wigamig push dcis_imaging --message "add QC for batch 3"
Pushed to member/the_pi/qc-batch-3 (direct; no review).

# later, when ready to merge:
$ wigamig push dcis_imaging --finalize
Opened PR #14: member/the_pi/qc-batch-3 → main
Triggered: adversary (src/**), security_guard (always)
```

### Updating refined data after a run

```
$ wigamig push dcis_imaging --refined 3_titration
Recomputed SHA-256 for 5 files in /data/lab_vm/wigamig/refined/dcis_imaging/3_titration/
Updated exp/3_titration/notebook.md (refined_data, checksums).
Pushed to member/the_pi/3_titration-analysis (direct).
```

### Scaffolding a new experiment

```
$ wigamig experiment new --project dcis_imaging --name titration
Created exp/3_titration/
  README.md, run_all.py, notebook.md
  pages/, sketches/, data/
  notebook.md frontmatter pre-filled: experiment=3_titration, date=2026-05-06, performer=@the_pi
Created /data/lab_vm/wigamig/raw/dcis_imaging/3_titration/
Created /data/lab_vm/wigamig/refined/dcis_imaging/3_titration/
Opening notebook.md in Obsidian.
```

### Ingesting raw instrument data

```
$ wigamig experiment ingest dcis_imaging 3_titration ~/Downloads/scope_export
Copied 12 files to /data/lab_vm/wigamig/raw/dcis_imaging/3_titration/
Computed SHA-256 checksums.
Set /data/lab_vm/wigamig/raw/dcis_imaging/3_titration/ to chmod a-w (read-only).
Updated raw_data and checksums in exp/3_titration/notebook.md.
```

### Reagent check before tomorrow's experiment

`provision` is no longer a CLI command. From inside CC:

```
> what's missing for tomorrow's titration?

[CC calls inventory_provision via the inventory MCP]
Missing:    anti-CD31      (no stock)
Expired:    4-OHT          (expiry 2026-05-04)
OK:         3 items in stock and within shelf life
```

### Publishing a finding to the group oracle

```
$ wigamig publish notes/abcb1_finding.md --to group
Published to hallett group oracle as findings/2026-05-05_abcb1.md
Audit entry written to lab_mgmt/oracle-publish.log
```

### PI assigns a role

```
$ wigamig role assign lab_manager @member_a
Opened transition issue #42 in lab_mgmt
Awaiting acknowledgement from @member_a and handoff from @prev_admin.
```

### Proposed operator acknowledges

```
$ wigamig role ack 42
Acknowledged role-transition #42 (lab_manager → @member_a)
```

### Birth of a project

```
$ wigamig project new dcis_imaging \
    --charter charter.md \
    --members @core_lead,@the_pi,@member_a
Created repo hallettmiket/dcis_imaging
MEMBERS:    3
Lab VM ACL synced.
Registered in lab_mgmt/projects/dcis_imaging.md
```

## Open

- Authentication / who-am-I (GitHub auth + lab VM SSH; SSO?).
- MCP server configuration (Slack, inventory, Zotero) — should `install` configure these or a separate `wigamig mcp` subcommand?
- Offline mode (lab VM unreachable): which commands degrade gracefully, which fail closed?
- How `wigamig` interacts with Claude Code's own `/install`-style flows.
