---
date: 2026-05-05
tags: [murmurent, manual]
---

# Murmurent CLI: User Manual

> Working draft. Companion to [[group_level]] design.
> Updated as new commands emerge in the design conversation.
> Re-read in full before every edit; keep it consistent with [[group_level]].
>
> **⚠ Project lifecycle superseded (2026-07):** the `project new / admit /
> release` flow below predates the certificate-based project model. Projects
> are now a set of *existing* repos + machines + certified members, created
> from the dashboard and managed with the identity commands in the next
> section: see [project_intra.md](project_intra.md).

## Overview

The Murmurent CLI manages the configuration that lets your local Claude Code instance act as a member of a murmurent-enabled group. It does **not** run agents: it manages agent installation, group membership, role assignments, projects, and the day-to-day verbs that touch group artefacts.

Design choice: a thin CLI is preferred over a GUI until a concrete onboarding need demands one.

## Conventions

- All commands accept `--help`.
- All mutating commands write an audit entry to the group's lab-management repo.
- The CLI uses your GitHub identity for attribution; assignments and approvals are signed where possible.
- Where a command is restricted (PI-only, lab_manager-only), this is enforced by the lab-management repo's branch-protection rules, not by the CLI alone: the CLI's check is a first line of enforcement only.

## Installation

For **first-time** setup as a new member, use `murmurent onboard` (see the Onboarding section below): it does install plus key generation, profile push, and PR.

For **subsequent** installs (e.g. on a second machine, or after a fresh OS) where the member is already registered:

```
murmurent install
```

Effects:
- Clones or updates the Murmurent repo (default `~/repos/murmurent`).
- Creates `~/.claude/agents/` if absent.
- Symlinks `frozen` agents from the group registry; copies `personal` agents.
- Configures `~/.claude/settings.json` with group-derived permissions and MCP servers.
- Initialises `~/.claude/agent-memory/` for the agents installed.
- Links the plain-English writing style into `~/.claude/output-styles/` (select it with `/config` → *Output style*).
- Turns off Claude Code's feedback survey in `~/.claude/settings.json`, unless you set `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` yourself.
- Creates the **Murmurent Dashboard** icon (skip with `--no-launcher`). `murmurent launcher` re-creates it; `murmurent launcher --remove` deletes it; `--user <handle>` makes it always open as that handle.

`murmurent install` does **not** generate an age key or push a member profile: those are one-time onboarding events.

### This computer's settings

Stored in `~/.murmurent/machine.yaml`. Each applies to this computer only.

| Command | Effect |
|---|---|
| `murmurent config repos-root [FOLDER]` | Show, or set, the folder where this computer keeps its git repositories (default `~/repos`). Setting it moves nothing |
| `murmurent config project-layout [nested\|flat]` | Show, or set, where new projects go: `nested` (one project folder holding its code, manuscript and seminar repositories; the default) or `flat` (each repository directly in the repositories folder). Existing projects are not moved |

## Command reference

### Agents

| Command | Effect | Notes |
|---|---|---|
| `murmurent agent which [--repo <path>]` | Show which version of each agent Claude Code will use, and where it comes from | One row per agent: **centre version**, **your version** or **your agent** (from your vault), **project version** (committed in the repo), **local file** (this machine only), **broken link**, or **not installed**. `--repo` describes a session started in that repo, whose own `.claude/agents/` wins |
| `murmurent agent list` | List installed agents in `~/.claude/agents/` | Each shown as **linked** (commons symlink), **forked** (personal copy), or **user-file**; forks also show upstream/local drift status |
| `murmurent agent fork <name> [--force]` | Replace a commons agent's symlink with an editable personal copy | Preserved across commons upgrades; canonical copy in the vault's `agent_forks/` (rides `murmurent vault sync` to your other machines; legacy `~/.murmurent/agent_forks/` when no vault), hardlinked into `~/.claude/agents/`. `--force` re-snapshots from the current commons |
| `murmurent agent drift [<name>]` | Merge indicator for forks | Per fork: `UP-TO-DATE` / `LOCAL-ONLY` / `UPSTREAM` / `DIVERGED` / `ORPHANED`, plus a summary of forks needing review |
| `murmurent agent unfork <name> [--force]` | Restore the commons symlink, dropping the personal copy | Prompts if local edits would be lost, unless `--force` |
| `murmurent agent relink` | Re-link the vault's personal agents (symlinks) + forks (hardlinks) into `~/.claude/agents/` | Run after a vault pull on another machine (`scripts/setup.sh` also runs it). Migrates a legacy `~/.murmurent/agent_forks/` into the vault once; idempotent and non-destructive |

### Preferences

Personal preferences profile lives at `~/.claude/murmurent-preferences.yaml` (local; never committed to group repos). Sets standardised cross-cutting fields once across all installed `personal` agents. See [Tool preferences](group_level.md#tool-preferences-defaults-overrides) for the controlled vocabulary.

| Command | Effect |
|---|---|
| `murmurent preference show` | Print the effective preferences profile |
| `murmurent preference set <field> <value>` | Set a standardised field; warns if `<field>` is not in the centre + guild vocabulary |
| `murmurent preference unset <field>` | Remove a field (agents fall back to registry default) |
| `murmurent preference validate` | Check the profile + every installed agent's `defaults` against the controlled vocabulary; prints warnings (typos, unknown enum values, missing-but-expected fields) |

### Groups

| Command | Effect |
|---|---|
| `murmurent group list` | List groups visible from your identity |
| `murmurent group join <group>` | Request membership; PI approves |
| `murmurent group leave <group>` | Remove yourself from a group |
| `murmurent group-setup <group> --set <key>=<value>` *PI* | Fill in a group's post-creation details, written to its `lab.md` (repeatable `--set`; interactive without `--set`). Keys: `github`, `github_org`, `notebook_host`, `notebook_path`, `slack_workspace`, `slack_invite_url`, `data_host`, `data_raw`, `data_refined`. Setting `github=<org>/<repo>` also fills `github_org` when unset, clearing the "no GitHub org configured" warning |

### Roles (PI-only commands marked)

| Command | Effect |
|---|---|
| `murmurent role list [--group <g>]` | List roles and current operators |
| `murmurent role describe <role>` | Print charter, cardinality, current operators |
| `murmurent role assign <role> <member>` *PI* | Open a role-transition issue |
| `murmurent role revoke <role> <member>` *PI* | Open a revoke issue |
| `murmurent role transfer <role> <from> <to>` *PI* | Open a transfer issue |
| `murmurent role ack <issue>` | Acknowledge a proposed assignment (proposed operator) |

### Identity & project certificates (current model)

| Command | Who | Effect |
|---|---|---|
| `murmurent init` | everyone | One-time identity setup (handle, official/institutional handle, email, GitHub, Slack) |
| `murmurent enroll [--group <g>] [--project <p>]` | member | Proof-of-possession request to send to the PI / project lead |
| `murmurent pi-init <lab>` | PI | Self-issue your PI ID; become your lab's trust root |
| `murmurent issue-member-card <enroll.json> --group <g>` | PI | Sign a member card (DM'd on Slack by default) |
| `murmurent import-card <bundle.json> [--trust-root <r>]` | anyone | Verify + store a card you were issued (PI / member / lead / project) |
| `murmurent whoami` | anyone | Your verified identity + trust root |
| `murmurent issue-project-lead-card <handle> --project <p>` | PI | Delegate a project to its creator (the lead) |
| `murmurent project-add-member <handle> --project <p> [--enrollment <f>]` | lead | Sign a member into a project (cert + DM + channel invite) |
| `murmurent project-remove-member <handle> --project <p>` | PI | Revoke a member's project card + kick from the channel |
| `murmurent project-whoami` | anyone | Prove which projects this machine's cards certify you for |
| `murmurent project-unarchive --project <p>` | PI | Bring a deleted project back (certs stay revoked; re-issue) |
| `murmurent revoke-project --project <p>` | PI | Revoke every card issued for a project |
| `murmurent member-audit` | PI | Check every roster member holds a valid certificate |
| `murmurent crl` / `murmurent revoke` | PI/mayor | Inspect / extend the revocation list |

### Projects

| Command | Effect |
|---|---|
| `murmurent project list` | List projects you are a member of |
| `murmurent project describe <name>` | Charter, MEMBERS, status |
| `murmurent project status [<name>]` | One project as a whole: its repositories, data folders, what it reads without owning, its keep-until date, when it was last used, and whether it is active, quiet or dormant. With no name, the project of the repository you are in. See [Every repository is in a project](ready_vs_projects.md#every-repository-is-in-a-project) |
| `murmurent project migrate [--apply] [--yes]` | List every repository and every folder directly under `immutable/` and `append_only/` that no project claims, and propose project records for them (`x`, `x_manuscript` and `x_seminar` become one project `x`). Writes nothing without `--apply`, and asks before writing (`--yes` skips the question). Never moves, renames or deletes anything |
| `murmurent project new <name> --charter <file> --members <list>` *PI/proposer* | Create a new project |
| `murmurent project members <name>` | Print MEMBERS |
| `murmurent project admit <name> <member>` *PI* | Add a member |
| `murmurent project release <name> <member>` *PI* | Remove a member |
| `murmurent project pause <name>` *PI* | Mark inactive |
| `murmurent project resume <name>` *PI* | Mark active |
| `murmurent project end <name> --reason <r>` *PI* | Terminal event |
| `murmurent project archive <name>` *PI* | Archive repo + data |
| `murmurent project gather <name> [--yes]` | Move a project's repositories on this computer into one project folder. Shows the plan and moves nothing without `--yes`; never overwrites; lists anything to fix by hand |
| `murmurent project provision-slack <name>` *PI* | Create the project's private Slack channel, named `proj-<name>`, and invite its certified members. Idempotent |
| `murmurent project rename-slack <name> [--to <channel>]` *PI* | Rename the project's Slack channel to `proj-<name>`, or to the name given. For channels made before 2026.10.0 without the `proj-` prefix (#157) |

### Project-wide push + managed mirrors

Back up **every** repo a project owns in one go, with the same per-repo safety
pre-flight as `/murmurent-push` (secret scan, secret-shaped names, governed-data
+ large-file guards). A repo that fails is blocked; the rest proceed. Exit codes:
**0** all clean · **1** partial · **2** nothing pushable / project not found.

| Command | Effect |
|---|---|
| `murmurent project push [--project <name>] [-m <msg>] [--detail]` | Commit + push every repo of a project; one plain-language summary + one Slack note to the project channel |
| `murmurent project mirror add <repo> <dest> [--project <name>]` | Record a GitHub mirror for a repo — an `org/name` shorthand (→ GitHub HTTPS) or a full git URL (e.g. `git@…`). Idempotent |
| `murmurent project mirror remove <repo> <dest> [--project <name>]` | Drop a recorded mirror (the working clone's git remotes are left as-is) |
| `murmurent project mirror list <repo> [--project <name>]` | List a repo's recorded mirrors |

**Mirrors** are extra push destinations beyond the primary `origin` — the
inter-group case where each lab's org wants its own copy. Each is managed as an
explicit `mm-mirror-<slug>` git remote, created/synced idempotently at push time;
`origin` is **never** touched, and no silent multiple-push-URLs are used, so each
destination's success/failure is reported **separately** ("also backed up to
labB: ✔ / ⚠ could not reach — tell your PI"). A mirror failure never rolls back
or blocks the primary push; it only downgrades the exit code to **1**.
Authentication is whatever your `git`/`gh` already has for that org.

### Repos (cross-machine inventory + adopt)

Terminal twin of the dashboard's **Repos** panel. All three commands
use the same core modules as the panel (`core.repo_inventory`,
`core.adopt`), so the two surfaces can't drift. **"Murmurent-ready" and
"a project" are two different things**: see
[`ready_vs_projects.md`](ready_vs_projects.md) for that distinction.

| Command | Effect |
|---|---|
| `murmurent repo list [--host <name>]` | Every git clone on **this** machine, each with its readiness verdict (`✓ ready` when it has a `.murmurent.yaml` marker, otherwise `• not set up yet`). Issue #94: this machine only, so remote hosts are skipped; view another machine's repos on its own dashboard ([Remote dashboard access](remote_dashboard.md)) |
| `murmurent repo status <path-or-name> [--host <name>]` | Is this repo murmurent-ready? A path is checked directly (local, or on `--host` over SSH); a bare name is searched on every registered machine. Ready means the `.murmurent.yaml` marker is present; `.claude/agents/` plays no part. `partial` means only a legacy `CHARTER.md` setup (run `repo upgrade`). Also lists agent links that git tracks, with the repair (#150). Exit 0 = ready, 1 = not ready, 2 = not found (scriptable) |
| `murmurent repo adopt <path> [--lab <slug>] [--agents a,b] [--host <name>]` | Make an existing clone **murmurent-ready**: writes the `.murmurent.yaml` readiness marker. `--agents` pins named agents to this repo as links (rarely needed: every agent works in every folder); those links are listed in the repo's `.gitignore` so they are never committed. Every repository belongs to a project, so when no project lists this one, adopt also records a one-repository project for it, with you as lead; an existing project is never changed. Adopting again changes nothing. See [Every repository is in a project](ready_vs_projects.md#every-repository-is-in-a-project) |
| `murmurent repo upgrade [<path> \| --all] [--add-agents a,b] [--all-agents]` | Bring ready repos up to the current Murmurent release: converts legacy `CHARTER.md` bootstraps to the marker, migrates the marker schema, re-links commons agents, re-stamps `bootstrap_version`. Agent *content* updates never need this: symlinks track the commons clone automatically |

### Experiments

Experiments follow the lab project structure: `exp/<integer>_<slug>/` in the project repo, with immutable and append-only data on the lab VM.

| Command | Effect |
|---|---|
| `murmurent experiment new --project <project> --name <slug>` | Scaffold `exp/<next-int>_<slug>/` with `README.md`, `run_all.py` skeleton, `notebook.md` template; create `$MURMURENT_DATA_ROOT/immutable/<project>/<exp>/` and `$MURMURENT_DATA_ROOT/append_only/<project>/<exp>/`; open `notebook.md` in Obsidian |
| `murmurent experiment list [--project <project>]` | List experiments and their `status` |
| `murmurent experiment status <project> <slug> --set <state>` | Update the `status` field on a notebook entry |
| `murmurent experiment ingest <project> <slug> <source> [--instrument <t>] [--accept] [--dry-run]` | Classify files in `<source>` as raw vs derived (instrument profile + generic patterns), present for mandatory review, then copy: raw → `$MURMURENT_DATA_ROOT/immutable/<project>/<slug>/` (chmod a-w), derived → `.../append_only/<project>/<slug>/instrument_outputs/`. Compute SHA-256; update `immutable_data:`, `instrument_outputs:`, `checksums:` in `notebook.md`. |
| `murmurent experiment attach <project> <slug> <file>` | Place a documentation file (photo of paper notebook page, sketch) into the appropriate subfolder; downsamples camera photos; never used for data files |

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
| `murmurent squad form --scope <project\|experiment\|sea> --target <name> --lead @<handle> --members <list>` | Create a squad with a lead and members | PI for project; project lead for sub-squads |
| `murmurent squad list [--scope <s>] [--member @<h>]` | Browse squads | Anyone |
| `murmurent squad describe <name>` | Print charter, lead, members, audit | Anyone |
| `murmurent squad invite <name> @<handle>` | Propose adding a member | Lead |
| `murmurent squad release <name> @<handle>` | Remove a member | Lead |
| `murmurent squad transfer-lead <name> @<new>` | Open a lead-transfer issue | PI for project; project lead for sub |
| `murmurent squad dissolve <name>` | End the squad | Lead, with PI sign-off for project-level |
| `murmurent squad promote <name> --to <scope>` | Upgrade scope (e.g. experiment → project) | PI |

### SEAs

Operational verbs (request → claim → complete; see also Finalisation below):

| Command | Effect |
|---|---|
| `murmurent sea request --to <member-or-squad> --kind <skill\|experiment\|analysis> --description <...>` | File an SEA request |
| `murmurent sea list [--mine] [--incoming] [--outgoing]` | Browse SEAs |
| `murmurent sea claim <id>` | Declare you'll perform an offered SEA |
| `murmurent sea complete <id> --delivery <path>` | Mark operational completion with a delivery artefact |
| `murmurent sea decline <id> --reason <r>` | Refuse with reason |

### Finalisation (analysis stages)

The finalisation choreography runs at SEA / experiment / project scope. `<scope>` ∈ `sea`, `experiment`, `projects`.

| Command | Effect | Authority |
|---|---|---|
| `murmurent <scope> examine <id>` | Trigger common agents to write their sections of the deliberation document | Squad lead |
| `murmurent <scope> conclude <id> [--statement <path>]` | Close the deliberation; optionally promote a statement to a finding | Squad lead with squad approvals |
| `murmurent finalize <scope> <id>` | Umbrella: runs `examine` then `conclude` end-to-end | Squad lead |
| `murmurent <scope> reopen <id>` | Re-open a concluded deliberation (e.g. when new evidence arrives) | Squad lead; PI sign-off for project scope |

### Discussions

| Command | Effect | Authority |
|---|---|---|
| `murmurent discuss new --project <p> --topic <t> [--participants <list>]` | Scaffold `discussions/<date>_<topic>.md`, open in editor | Any project member |
| `murmurent discuss list [--project <p>] [--open]` | Browse discussions; `--open` filters to non-decided | Anyone |
| `murmurent discuss close <id> --outcome <decided\|open\|blocked\|tabled> [--decision <text>]` | Set the outcome on a discussion | Project lead (for `decided`) |

### Teach (protocols and skills)

| Command | Effect | Authority |
|---|---|---|
| `murmurent teach protocol --name <n> [--scope project\|group\|center] [--from-experiment <p> <e>]` | Scaffold a protocol; `--from-experiment` extracts a draft from a notebook entry | Author at project scope; group lead promotes to group; PI to centre |
| `murmurent teach skill --name <n> [--scope group\|center]` | Scaffold a Claude Code skill | Group lead at group scope; PI at centre |
| `murmurent teach promote <name> --to <wider-scope>` | Move a protocol or skill to a wider scope | Group lead / PI |

### Freeze

| Command | Effect | Authority |
|---|---|---|
| `murmurent freeze <project> --purpose <text> [--include-raw]` | Compute manifest, create tag, encrypt bundle. Tag created only after PI approves the manifest PR. | Project lead initiates; PI approves |
| `murmurent freeze list <project>` | List past freezes with their purposes and dates | Anyone with project access |
| `murmurent freeze restore <project> <tag> [--to <path>]` | Extract a freeze into a temp location for inspection (read-only; never modifies the live project) | Anyone with project access |

### Sensitivity and compliance

| Command | Effect | Authority |
|---|---|---|
| `murmurent project sensitivity <project> [--set <standard\|restricted\|clinical>]` | Read or change a project's sensitivity tier | PI; raising allowed; lowering requires PR + audit |
| `murmurent compliance status [--project <p>]` | Show your compliance state per project (required + elected controls; missing items in red) | Member |
| `murmurent compliance certify <cert-name> --expires <date>` | Record a certification (e.g. TCPS 2) on your member profile | Member; PI verifies |
| `murmurent audit verify <repo>` | Walk the audit chain, verify signatures and tamper-evident hash chain | Anyone with repo access |
| `murmurent secret rotate <scope> <name>` | Rotate and re-encrypt a secret (`personal`, `group`, or `project` scope) | Scope-appropriate authority |
| `murmurent breach <project> --description <text>` | Open a breach incident in the lab-management repo; notify PI; start the PHIPA 24-hour clock; draft the IPC notification | Any project member |

### Choreographies

| Command | Effect |
|---|---|
| `murmurent choreography init <name>` | Start a choreography from nothing: create its repository, make it ready, declare it, pose its question, commit, and ask the PI to make it a project. Asks for anything left out; `--yes` asks nothing. See [Starting a choreography](starting_a_choreography.md) |
| `murmurent choreography list` | List choreographies published in the public hub |
| `murmurent choreography install <name-or-git-url>` | Clone a choreography and make it murmurent-ready |
| `murmurent choreography new --question … --poser … --title … --candidate-key … --criteria …` | Pose a question on its own |
| `murmurent choreography offer <question.md> --contribution <slug>` | Attach a contribution to a question |
| `murmurent choreography validate <question.md>` | Check every attached contribution reports on the question's candidate key |
| `murmurent choreography show <question.md>` | Print the question, its criteria and its contributions |
| `murmurent choreography prepare-run <question.md>` | Gather everything the judge needs into one run package |
| `murmurent choreography freeze-run <question.md> --result <file>` | Keep a permanent record of a run and the judge's result |

The full workflow is in [Assembling a choreography](assembling_choreographies.md).

### Long jobs

| Command | Effect |
|---|---|
| `murmurent run [options] -- <command>` | Start a long job inside tmux (so a dropped connection does not stop it) at priority `nice 19`, with thread limits set and cores and GPUs chosen from the lab's rules and the server's load. Writes a job card under `~/.murmurent/runs/` and posts one line to the project's Slack channel when the job finishes, fails or stalls (never the command or a file path) |
| `murmurent run --cores N --gpus N --memory 64G` | Ask for cores, GPUs and memory. Requests above the lab's allowance are capped or refused, and the reply says why |
| `murmurent run --out <folder> --expect-disk 500G` | Check the output folder's free space, and refuse a job whose stated output would not fit |
| `murmurent run --input <path> [--input <path> ...]` | Record what the job reads, so the space scan can tell later whether its output could be made again |
| `murmurent run --at 22:00` / `--when-load-below 150` / `--wait` | Start later: at a time, once the server is quieter, or as soon as there is room |
| `murmurent run --exception "<reason>" --until <time>` | Go above your allowance after asking in the server channel; recorded on the card |
| `murmurent run --session <name>` | Put the job in a new window of an existing tmux session |
| `murmurent run --no-notify` / `--dry-run` | No Slack line / show what would be chosen and start nothing |
| `murmurent jobs [--all]` | What is running, waiting and recently ended, with estimates |
| `murmurent jobs show <id or name>` | Everything recorded about one job |
| `murmurent jobs stop <id or name>` | Stop a job: asked to end cleanly, then by force 30 seconds later |
| `murmurent jobs restart <id or name> [--wait]` | Run a job again from its card |
| `murmurent jobs policy` | The lab's rules in force (from `<lab-mgmt>/policy/millwright.yaml`) and where they came from |

The full guide is [Running long jobs](run_launcher.md).

### Space

| Command | Effect |
|---|---|
| `murmurent space scan [project] [--no-checksums]` | Look through one project's repositories and data folders and list what could be deleted, compressed, moved or asked about, most pressing first. Reads sizes, dates, owners and names; changes nothing. The table is kept in `~/.murmurent/space/`, readable by you only |
| `murmurent space show [project] [--category C] [--owner O] [--min-size 10G] [--all]` | The table from the last scan: emergencies, the top three, then every row waiting for a decision |
| `murmurent space decide <row> keep\|delete\|mothball\|compress\|move\|undo [--note …]` | Record your decision on one row. Nothing is carried out |
| `murmurent space gaps [project]` | Cases the lab's procedures do not cover, each with an example |
| `murmurent space scan-lab [--notify]` | (PI, on the server) Scan every project's data folders and the folders no project claims; write the lab report; with `--notify`, send the PI a Slack summary without file names |
| `murmurent space lab [--host <server>] [--json]` | The lab's last report: emergencies, what to look at first, every project. With `--host`, fetch it from the server over SSH |
| `murmurent space schedule [--install\|--remove] [--day sun --at 02:00]` | Show, set up or remove the weekly lab scan (a systemd user timer); recorded in the lab records repository |

The full guide is [Tidying a project's space](space_table.md).

### Dashboard

| Command | Effect |
|---|---|
| `murmurent dashboard --hifi` | Open the local dashboard (the FastAPI web UI) in your browser |
| `murmurent dashboard --stop [--port N]` | Stop the dashboard running on this machine | For one started in the background by the dashboard icon; closing the browser window does not stop it. The top bar's **⏻ stop dashboard** button does the same |
| `murmurent dashboard --pi` | Open the PI view (rejected if you're not a PI); adds escalated-from-members nags |
| `murmurent dashboard --snapshot` | Print the latest markdown snapshot from the lab-management repo |
| `murmurent dashboard --outstanding` | Print only the Outstanding analysis panel (terminal-friendly summary) |
| `murmurent dashboard --tunnel you@host` | Open an SSH tunnel to `you@host` and forward its dashboard to `http://localhost:8770` on this machine. A literal `you@host` or `~/.ssh/config` alias works directly — no registration needed (a name in `hosts.yaml` is honoured as an optional fallback). See [Remote dashboard access](remote_dashboard.md) |
| `murmurent dashboard --tunnel you@host --tunnel-port 8771` | Same, but forward to local port 8771, so a second tunnelled dashboard can run alongside the first |

### Onboarding

| Command | Effect |
|---|---|
| `murmurent onboard <group> --profile <profile>` | One-shot setup for a new member: clone Murmurent, install agents per profile, configure MCP, generate age key, push key + member profile via PR |
| `murmurent doctor` | Check the local install and print the one command that fixes each problem: Python version, whether `pip`/`python` on PATH match the interpreter murmurent runs under, agent/rule/skill links into the commons (including dangling ones), registered hooks and their interpreter, whether a clone's `origin` can still `git pull`, and whether the Murmurent Dashboard icon exists. Exit 0 = healthy (warnings allowed), 1 = something failed |
| `murmurent offboard --member @<handle>` *PI* | Mirror of onboard: revoke roles, release from projects, archive age key, mark profile alumni |

### Verbs (day-to-day)

Note: `provision` is no longer a CLI command; it is a tool on the `inventory` MCP and is called from inside CC by any agent.

| Command | Effect |
|---|---|
| `murmurent push <project> [--message <m>]` | Push current branch as `member/<handle>/<topic>` (direct, no review) |
| `murmurent push <project> --finalize` | Open a PR from the personal branch to `main`; trigger bot + human reviews per path rules |
| `murmurent push <project> --refined <exp>` | Recompute checksums in `$MURMURENT_DATA_ROOT/append_only/<project>/<exp>/`, update notebook `append_only_data` + `checksums`, push to personal branch |
| `murmurent pull <project>` | Fetch latest |
| `murmurent cite <reference>` | Resolve and insert a citation; checks group oracle |
| `murmurent audit <target>` | Invoke `adversary` on a path or PR |
| `murmurent publish <artefact> --to <oracle>` | Promote a finding to the group oracle |
| `murmurent request-sea --to <member> --kind <skill\|experiment\|analysis> --description <...>` | File an SEA request on the group request board |
| `murmurent review <PR-url>` | Open a review session |
| `murmurent capture` | Open `inbox/YYYY-MM-DD_HHMM.md` for a quick note |
| `murmurent triage` | Run `/process-inbox`-equivalent flow on `inbox/` |

## Examples

### First-time setup

```
$ murmurent onboard newmember --profile student
Cloning murmurent... done.
Installing agents (profile: student): bookworm, adversary, blacksmith, artist
  bookworm:    personal (copied)
  adversary:   frozen   (symlink)
  blacksmith:  personal (copied)
  artist:      personal (copied)
Configuring MCP servers: inventory, oracle, request_board
Generated age key. Public key: age1...
Opened PR #87 in lab_mgmt: "Onboard @newuser"

# (PI approves PR and runs `murmurent project admit` for each project in onboarding issue)

$ murmurent doctor
All checks passed.
```

### Daily flow on a project

```
$ murmurent pull brca_imaging
# work in Claude Code on member/the_pi/qc-batch-3 ...
$ murmurent audit src/qc.py
$ murmurent push brca_imaging --message "add QC for batch 3"
Pushed to member/the_pi/qc-batch-3 (direct; no review).

# later, when ready to merge:
$ murmurent push brca_imaging --finalize
Opened PR #14: member/the_pi/qc-batch-3 → main
Triggered: adversary (src/**), security_guard (always)
```

### Updating append-only data after a run

```
$ murmurent push brca_imaging --refined 3_titration
Recomputed SHA-256 for 5 files in $MURMURENT_DATA_ROOT/append_only/brca_imaging/3_titration/
Updated exp/3_titration/notebook.md (append_only_data, checksums).
Pushed to member/the_pi/3_titration-analysis (direct).
```

### Scaffolding a new experiment

```
$ murmurent experiment new --project brca_imaging --name titration
Created exp/3_titration/
  README.md, run_all.py, notebook.md
  pages/, sketches/, data/
  notebook.md frontmatter pre-filled: experiment=3_titration, date=2026-05-06, performer=@the_pi
Created $MURMURENT_DATA_ROOT/immutable/brca_imaging/3_titration/
Created $MURMURENT_DATA_ROOT/append_only/brca_imaging/3_titration/
Opening notebook.md in Obsidian.
```

### Ingesting raw instrument data

```
$ murmurent experiment ingest brca_imaging 3_titration ~/Downloads/scope_export
Copied 12 files to $MURMURENT_DATA_ROOT/immutable/brca_imaging/3_titration/
Computed SHA-256 checksums.
Set $MURMURENT_DATA_ROOT/immutable/brca_imaging/3_titration/ to chmod a-w (read-only).
Updated immutable_data and checksums in exp/3_titration/notebook.md.
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
$ murmurent publish notes/abcb1_finding.md --to group
Published to lab group oracle as findings/2026-05-05_abcb1.md
Audit entry written to lab_mgmt/oracle-publish.log
```

### PI assigns a role

```
$ murmurent role assign lab_manager @member_b
Opened transition issue #42 in lab_mgmt
Awaiting acknowledgement from @member_b and handoff from @prev_admin.
```

### Proposed operator acknowledges

```
$ murmurent role ack 42
Acknowledged role-transition #42 (lab_manager → @member_b)
```

### Birth of a project

```
$ murmurent project new brca_imaging \
    --charter charter.md \
    --members @member_a,@the_pi,@member_b
Created repo hallettmiket/brca_imaging
MEMBERS:    3
Lab VM ACL synced.
Registered in lab_mgmt/projects/brca_imaging.md
```

## Open

- Authentication / who-am-I (GitHub auth + lab VM SSH; SSO?).
- MCP server configuration (Slack, inventory, Zotero): should `install` configure these or a separate `murmurent mcp` subcommand?
- Offline mode (lab VM unreachable): which commands degrade gracefully, which fail closed?
- How `murmurent` interacts with Claude Code's own `/install`-style flows.
