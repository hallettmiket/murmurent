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
| `murmurent config speak-language [CODE] [--voice NAME] [--list]` | Show, or set, the language agents speak their verdicts in on this computer (a Piper language code such as `fr_FR`; `en` is English, the default). Writes the `language` line of `~/.murmurent/speak` and fetches that language's voice when Piper is installed; `--list` shows the languages with a voice, `--voice` names a Piper voice for one the table lacks |

## Command reference

### Agents

| Command | Effect | Notes |
|---|---|---|
| `murmurent agent which [--repo <path>]` | Show which version of each agent Claude Code will use, and where it comes from | One row per agent: **centre version**, **your version** or **your agent** (from your vault), **project version** (committed in the repo), **local file** (this machine only), **broken link**, or **not installed**. `--repo` describes a session started in that repo, whose own `.claude/agents/` wins |
| `murmurent agent list` | List installed agents in `~/.claude/agents/` | Each shown as **linked** (commons symlink), **forked** (personal copy), or **user-file**; forks also show upstream/local drift status |
| `murmurent agent fork <name> [--force] [--project P]` | Replace a commons agent's symlink with an editable personal copy | Preserved across commons upgrades; canonical copy in the vault's `agent_forks/` (rides `murmurent vault sync` to your other machines; legacy `~/.murmurent/agent_forks/` when no vault), hardlinked into `~/.claude/agents/`. `--force` re-snapshots from the current commons. `--project P` keeps the copy in your vault's `projects/P/agents/`, for that project only |
| `murmurent agent sync [--repo PATH] [--all]` | Install the version of each agent that should win | The lab's into `~/.claude/agents` unless you have your own; project and per-project versions into a repo; agents switched off there. See [Choosing an agent's version](agent_versions.md) |
| `murmurent agent off <name> --project P` / `on` | Switch an agent off (or back on) for you in one project | Becomes Claude Code's `Agent(<name>)` deny rule in the repo's `.claude/settings.local.json`. Guardians cannot be switched off |
| `murmurent agent share <name> --lab` / `--repo PATH` | Make the version you use the lab's (PI only) or a project's | `--lab` commits it to the lab-management repo's `agents/`; `--repo` copies it into `.murmurent/agents/` for you to commit |
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
| `murmurent group-slack-share <group>` *PI* | Seal the lab's Slack bot token to each active member's attested card key and commit it to the lab records (`security/slack_bot_token.sealed.json`), so members can post notes from their own machines. Re-run after adding a member or rotating the token |
| `murmurent group-slack-unlock <group>` | Member: open the token the PI shared, with this machine's key, and store it at `~/.config/murmurent/groups/<group>/slack-token`. `murmurent project note` tries this itself when the machine has no token; `--check` only reports |
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
| `murmurent project-add-member <handle-or-email> --project <p> [--enrollment <f>] [--no-open-mail]` | lead | Sign a member into a project (cert + DM + channel invite + access on every repository). A handle with no key on file (someone from another group) is put on the member list at once, awaiting a certificate, and is sent the enrollment steps; `--no-pending` refuses instead. An email address murmurent does not know records an invitation and drafts the email to send (opened in your mail client unless `--no-open-mail`); the handle fills in when the enrollment arrives |
| `murmurent project-remove-member <handle> --project <p> [--no-dm]` | PI or lead | Remove a member: revoke their project card (a lead's removal waits for the PI's `project reconcile --apply`), remove them from the channel and from every GitHub repository the project lists, and tell them by direct message. Lists what it could not do |
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
| `murmurent project set <name> [--data-folder F]... [--reads-from F]... [--retain-until DATE] [--clear data-folders\|reads-from]` | Set a project's data folders, what it reads without owning, and its keep-until date | Commits and pushes the project record |
| `murmurent project add-repo <name> <folder-or-repo> [--role R] [--home] [--create-remote]` *PI or lead* | List one more repository on a project's record. A repository may be in several projects: a note about it goes to each project's channel, and its data stays with the project that listed it first (the others read its folders) unless `--home` moves it here (#253). `--create-remote` creates a private `<org>/<repo>` on GitHub for a clone with no remote (`<org>` from `lab.md`), pushes, records the remote and grants every member access; without it, a clone with no remote is named with that hint (#269) | Commits and pushes the project record; `--create-remote` creates a GitHub repository |
| `murmurent project release-repo <name> <repo>` *PI or lead* | Take a repository off a project's record, so the project no longer claims it; the clone on disk is untouched (#250) | Commits and pushes the project record |
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
| `murmurent project note "<text>" [--project <name>] [--dry-run]` | Post a short note (a release note after a push) to the channel this repository's notes belong in: its project's channel, else the lab's; never a shared channel. Prints where it went or why it was not posted. `--dry-run` shows the destination only |
| `murmurent project channels` | Audit every project's Slack channel: id, name, archived or not, whether the bot is in it; lists repositories in more than one project (a note about one goes to each project's channel) and projects with no channel. Read-only |
| `murmurent project channel [--project <name>]` | Print the project's Slack channel id, one per line when the repository is in several projects, or fail with the reason (no channel yet) |
| `murmurent project provision-slack <name>` *PI* | Create the project's private Slack channel, named `proj-<name>`, and invite its certified members. Idempotent |
| `murmurent project rename-slack <name> [--to <channel>]` *PI* | Rename the project's Slack channel to `proj-<name>`, or to the name given. For channels made before 2026.10.0 without the `proj-` prefix (#157) |
| `murmurent project provision-github <name> [--create] [--org <org>]` *PI* | Give the project's certified members collaborator access on every GitHub repository it lists. Creates nothing unless `--create`, which makes a private `<org>/<name>` repository for a project with no repository yet |
| `murmurent project reconcile <name> [--apply]` *PI* | Compare the project's Slack channel and the collaborators of every GitHub repository it lists with its certified members. Reports drift and what it could not do (members with no GitHub login, refused calls); `--apply` invites the missing, removes the extras, and revokes the cards of members a lead removed. Nobody is swept from the channel while any member's Slack account is unresolved |

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
| `murmurent repo status <path-or-name> [--host <name>]` | Is this repo murmurent-ready? A path is checked directly (local, or on `--host` over SSH); a bare name is searched on this machine only (another machine's repos are seen on its own dashboard). Ready means the `.murmurent.yaml` marker is present; `.claude/agents/` plays no part. `partial` means only a legacy `CHARTER.md` setup (run `repo upgrade`). Also lists agent links that git tracks, with the repair (#150). Exit 0 = ready, 1 = not ready, 2 = not found (scriptable) |
| `murmurent repo adopt <path> [--lab <slug>] [--agents a,b] [--all-agents] [--host <name>] [--no-commit]` | Make an existing clone **murmurent-ready**: writes the `.murmurent.yaml` readiness marker and a `CLAUDE.md` stub, links the agents (every commons agent for a repository with no marker yet, as the dashboard does; `--agents` names fewer), lists the links in `.gitignore` so they stay on this machine, and commits the marker, stub and `.gitignore` so every clone is ready (`--no-commit` leaves that to you). Every repository belongs to a project, so when no project lists this one, adopt also records a one-repository project for it, with you as lead; an existing project is never changed. Adopting again changes nothing. See [Every repository is in a project](ready_vs_projects.md#every-repository-is-in-a-project) |
| `murmurent repo upgrade [<path> \| --all] [--add-agents a,b] [--all-agents]` | Bring ready repos up to the current Murmurent release: converts legacy `CHARTER.md` bootstraps to the marker, migrates the marker schema, re-links commons agents, and records on this machine which release linked each repo (`~/.murmurent/repo_bootstrap.yaml`, no longer written into the committed marker). `--all` also registers any clone that arrived with its marker. Agent *content* updates never need this: symlinks track the commons clone automatically |

### Experiments

Experiments follow the lab project structure: `exp/<integer>_<slug>/` in the project repo, with immutable and append-only data on the lab VM.

| Command | Effect |
|---|---|
| `murmurent experiment new --project <project> --name <slug>` | Scaffold `exp/<next-int>_<slug>/` with `README.md`, `run_all.py` skeleton, `notebook.md` template; create `$MURMURENT_DATA_ROOT/immutable/<project>/<exp>/` and `$MURMURENT_DATA_ROOT/append_only/<project>/<exp>/`; open `notebook.md` in Obsidian |
| `murmurent experiment list [--project <project>]` | List experiments and their `status` |
| `murmurent experiment status <project> <slug> --set <state>` | Update the `status` field on a notebook entry |
| `murmurent experiment ingest <project> <slug> <source> [--instrument <t>] [--accept] [--dry-run]` | Classify files in `<source>` as raw vs derived (instrument profile + generic patterns), present for mandatory review, then copy: raw → `$MURMURENT_DATA_ROOT/immutable/<project>/<slug>/` (chmod a-w), derived → `.../append_only/<project>/<slug>/instrument_outputs/`. Compute SHA-256; update `immutable_data:`, `instrument_outputs:`, `checksums:` in `notebook.md`. |
| `murmurent experiment attach <project> <slug> <file>` | Place a documentation file (photo of paper notebook page, sketch) into the appropriate subfolder; downsamples camera photos; never used for data files |

### Lab notebook

The daily notebook in your vault: notes in `lab-notebook/<date>.md`, the
prompts you gave Claude Code recorded by a hook in `sessions/<date>/`. Full
page: [The lab notebook](lab_notebook.md).

| Command | Effect |
|---|---|
| `murmurent notebook add <text or file> [--project P] [--host H] [--handwritten] [--kind K] [--note T] [--sensitivity S] [--date D] [--dry-run]` | Put a line of text, a photo, a handwritten page, a sound note, a video or a result file into today's entry. Small result files stay in the vault's `attachments/`; images, sound, video and large files go to `append_only/<P>/notebook/<date>/` on the project's data host, never overwritten; the entry keeps the link, a thumbnail or poster frame (none for a protected project), and any transcription or description marked as machine-made |
| `murmurent notebook open <host>:<path> [--no-open]` | Fetch a copy of a file the notebook links to into `~/.murmurent/notebook_cache/` and open it |
| `murmurent notebook split [--dry-run]` | Move pasted prompts (long second-person paragraphs) out of existing entries into `sessions/<date>/pasted.md`; each original kept under `obsolete/`; prints every move; deletes nothing |
| `murmurent notebook report --for <supervisor\|lab\|project:<name>> --since <date> [--until <date>] [--out DIR] [--title T]` | Collect the whole entries whose `audience` admits the reader, refuse restricted and protected ones, write `material.md` + `sources.md` for the scribe and artist, render one self-contained `report.html`, list every entry and file drawn on; sends nothing |

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
| `murmurent project sensitivity <project> [--set <standard\|restricted\|protected>]` | Read or change a project's sensitivity tier | PI; raising allowed; lowering requires PR + audit |
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
| `murmurent jobs policy [--init]` | The lab's rules in force; `--init` creates `policy/millwright.yaml` from the template if the lab has none |
| `murmurent etiquette check [--notify]` | Lab members running above nice 19, over their cores or GPUs | Reports only unless `--notify`: a direct message, then the lab channel, then the PI. Never reads command lines or changes jobs |
| `murmurent etiquette schedule --install [--notify] [--at 11:00]` / `--remove` | Run the check every weekday under your account | Recorded in `policy/scheduled_jobs.md` |
| `murmurent jobs restart <id or name> [--wait]` | Run a job again from its card |
| `murmurent jobs policy` | The lab's rules in force (from `<lab-mgmt>/policy/millwright.yaml`) and where they came from |

The full guide is [Running long jobs](run_launcher.md).

### Papers and theses

A paper as a queryable package, and a thesis composed of them; see
[`paper_package.md`](paper_package.md).

| Command | What it does |
|---|---|
| `murmurent paper init <dir> --title ... [--author ...] [--lab ...]` | Scaffold a paper package: `paper.yaml`, `main.tex`, `CLAUDE.md`, `queries/`, marker. Never overwrites. |
| `murmurent paper check [<dir>] [--strict]` | Every claim has its code, data and figure; exits 1 on an error (or a warning with `--strict`). |
| `murmurent paper build [<dir>] [--pdf]` | Write `build/claim_map.md`; with `--pdf`, run latexmk on the source. |
| `murmurent thesis init <dir> --title ... [--candidate ...]` | Scaffold a thesis package with SGPS front matter and chapter stubs. |
| `murmurent thesis adopt <thesis.tex> <dir> [--title ...] [--candidate ...]` | Turn one monolithic thesis `.tex` into a package: preamble kept, SGPS front matter and chapters split, a draft claim per figure, figures and `.bib` files copied. The source folder is not changed. |
| `murmurent thesis check [<dir>] [--strict]` | Check the thesis and every paper package in it: front matter and its word limits, chapter order, permissions, sensitivity. |
| `murmurent thesis build [<dir>] [--pdf]` | Assemble `build/main.tex` in the SGPS order and `build/claim_map.md` for every chapter. |
| `murmurent thesis talk [<dir>] [--minutes 20] [--pdf]` | Draft the defence talk: `build/talk_plan.md` (timed, one slide per claim) and `build/talk.tex` (Beamer). |
| `murmurent thesis paperwork [<dir>]` | Write `build/paperwork.md`: the submission checklist from the institution pack's `thesis_examination` procedure (the built-in SGPS seed when no pack is found), deadlines from the defence date, board, forms, Veritas and final-submission steps. |

### The institution pack

Dated, sourced facts about the institution that the clerk answers from; see
[`institution_pack.md`](institution_pack.md). The pack is chosen by `--pack`,
else `$MURMURENT_INSTITUTION_PACK`, else the centre's `unique_name` under
`institution/`.

| Command | What it does |
|---|---|
| `murmurent institution init <unique_name> --name ... --domain ... [--seed-thesis]` | Scaffold a pack; `--seed-thesis` writes `procedures/thesis_examination.yaml` from the seed built into murmurent. Never overwrites. |
| `murmurent institution validate [--pack P]` | Every fact has `source` and `date_read`, every source is inside the pack's domains, dates parse; lists stale facts. Exits 1 on an error. |
| `murmurent institution show <office\|procedure\|holiday\|term\|deadline\|course\|letterhead\|packs> [key]` | One thing from the pack with its source, date and age note; `Unknown` with the nearest facts when absent. |
| `murmurent institution review <file> [--level undergraduate\|graduate] [--term T] [--html OUT] [--markdown]` | A whole course outline: the term day by day (every date with the outline's events, the pack's holidays and deadlines, and the cutoffs the rules imply), then every policy for the level, the schedule against the pack's holidays and non-instructional days, the grade weights, what is unclear. Writes an HTML report (default `outputs/clerk/<name>_review.html`); exits 1 on a `Fix`. |
| `murmurent institution check <file> [--pack P]` | Office holders, emails, postal codes, colours and fonts in a document against the pack. `Correct / Fix / Unknown` per finding; exits 1 on a `Fix`. |
| `murmurent institution date <YYYY-MM-DD> --days N [--pack P]` | N working days before (negative) or after the date, skipping weekends and the pack's holidays; says which holidays it skipped. `--days 0` moves a holiday to the next working day. |
| `murmurent institution walk <procedure> [--anchor DATE] [--variant doctoral] [--done 1,2] [--next]` | The steps with their forms and deadlines counted from the anchor date. |
| `murmurent institution fetch-course <SUBJECT> <number> [--apply]` | Run the pack's course fetch rule for one course; `--apply` caches it in `courses.yaml`. |
| `murmurent institution refresh [--apply] [--kind office ...]` | Re-read every fact from its source, inside the pack's domains only, and report confirmed, changed and unreachable facts with their dates. Dry run; `--apply` stamps today's date on confirmed facts and refreshes the course cache. A changed fact is reported, not rewritten. |

### Space

| Command | Effect |
|---|---|
| `murmurent space scan [project] [--no-checksums]` | Look through one project's repositories and data folders and list what could be deleted, compressed, moved or asked about, most pressing first. Reads sizes, dates, owners and names; changes nothing. The table is kept in `~/.murmurent/space/`, readable by you only |
| `murmurent space show [project] [--category C] [--owner O] [--min-size 10G] [--all]` | The table from the last scan: emergencies, the top three, then every row waiting for a decision |
| `murmurent space decide <row> keep\|delete\|mothball\|compress\|move\|undo [--note …]` | Record your decision on one row. Nothing is carried out; see `carry-out` |
| `murmurent space carry-out [project] [--row N] [--to <place>] [--apply]` | Carry out mothball, compress and move decisions: copy, check the copy against fingerprints of the original, and log it. Shows the plan unless `--apply` is given. Never removes an original |
| `murmurent space removable [project]` | Originals a person may now remove: those whose copy was checked, and rows decided `delete`. Projects with a keep-until date in the future are listed as held. Removes nothing |
| `murmurent space gaps [project]` | Cases the lab's procedures do not cover, each with an example |
| `murmurent space scan-lab [--notify]` | (PI, on the server) Scan every project's data folders and the folders no project claims; write the lab report; with `--notify`, send the PI a Slack summary without file names |
| `murmurent space lab [--host <server>] [--json]` | The lab's last report: emergencies, what to look at first, every project. With `--host`, fetch it from the server over SSH |
| `murmurent space layout [--json]` | Compare the lab's data root with the lab folder protocol and list what does not follow it: folders not in the protocol, folders being phased out, loose files, and subfolders named after no project or person. Reads folder names only and moves nothing; see [The lab folder protocol](lab_folders.md) |
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
| `murmurent doctor` | Check the local install and print the one command that fixes each problem: Python version, whether `pip`/`python` on PATH match the interpreter murmurent runs under, agent/rule/skill links into the commons (including dangling ones), registered hooks and their interpreter, whether a clone's `origin` can still `git pull`, whether the Murmurent Dashboard icon exists, and whether this machine has the lab's records repository or, if not, whether your GitHub account can get it (invitation waiting, expired, never sent, or `gh` signed in as another account). Exit 0 = healthy (warnings allowed), 1 = something failed |
| `murmurent offboard --member @<handle>` *PI* | Mirror of onboard: revoke roles, release from projects, archive age key, mark profile alumni |

### Verbs (day-to-day)

Note: `provision` is no longer a CLI command; it is a tool on the `inventory` MCP and is called from inside CC by any agent.

| Command | Effect |
|---|---|
| `murmurent push <project> [--message <m>]` | Push current branch as `member/<handle>/<topic>` (direct, no review) |
| `murmurent push <project> --finalize` | Open a PR from the personal branch to `main`; trigger bot + human reviews per path rules |
| `murmurent push <project> --refined <exp>` | Recompute checksums in `$MURMURENT_DATA_ROOT/append_only/<project>/<exp>/`, update notebook `append_only_data` + `checksums`, push to personal branch |
| `murmurent pull <project>` | Fetch latest |
| `murmurent cite check <file>` | Look up every DOI, PMID and arXiv ID in a `.bib`, `.tex` or `.md` file. Reports any that do not exist, name a different paper from the one the bibliography claims, or have been retracted, and exits 1 if there are any. `--json` for agents |
| `murmurent audit <target>` | Invoke `adversary` on a path or PR |
| `murmurent publish <artefact> --to <oracle>` | Promote a finding to the group oracle |
| `murmurent request-sea --to <member> --kind <skill\|experiment\|analysis> --description <...>` | File an SEA request on the group request board |
| `murmurent review <PR-url>` | Open a review session |
| `murmurent capture` | Open `inbox/YYYY-MM-DD_HHMM.md` for a quick note |
| `murmurent triage` | Run `/process-inbox`-equivalent flow on `inbox/` |

### `murmurent prompt`

Prompts written in Obsidian, sent to Claude Code, and kept
([`docs/lab_notebook.md`](lab_notebook.md)).

| Command | What it does |
|---|---|
| `murmurent prompt new` | Open today's `prompts/<date>.md` in the vault, created with a heading when missing. |
| `murmurent prompt send [--text T] [--file F] [--to APP] [--tmux PANE] [--no-paste] [--project P]` | Copy a prompt to the clipboard, paste it into Claude Code (an app on macOS, or a tmux pane) and record it under `sessions/<date>/sent.md`. With no `--text` or `--file`, the latest block of today's prompts file. |

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
