# Murmurent — an agentic AI village for a research centre

Murmurent is shared agentic-AI infrastructure that lets research groups
work independently, pool agents and data when collaboration benefits
them, and accumulate institutional knowledge across every project.

An overview is in [`docs/index.md`](docs/index.md) and
[`docs/overview.md`](docs/overview.md). In short:

- **Choreography, not orchestration.** Each group runs its own
  documented workflow using the shared agents and rules, and retains
  authority over its own members and data. Distributing control this
  way limits the scope of any single failure and preserves each
  group's autonomy. ("Choreography" is the term used throughout the
  code for a recurring multi-actor workflow recipe.)
- **Four social units**: individual members; groups (each a lab or a
  core, led by a PI); projects (units of work that bring members
  together, potentially across groups); and the administration
  (centre-level governance and registry).
- **The commons** = centre-wide AI infrastructure every member draws
  on (reference agents + data-governance rules + baseline workflows).
  Group/core toolkits are built on top.

## Reference agents (the commons)

Defined in [`agents/`](agents/), symlinked into `~/.claude/agents/`
by [`scripts/setup.sh`](scripts/setup.sh). Each MUST begin its final
reply with a ≤200-char verdict line (see
[`rules/headline_first.md`](rules/headline_first.md)).

| Agent | Role |
|---|---|
| [`oracle`](agents/oracle.md) | Personal research memory (per-user Obsidian vault) |
| [`lab_oracle`](agents/lab_oracle.md) | Lab-shared institutional memory (read-only; promoted via `murmurent oracle publish`) |
| [`bookworm`](agents/bookworm.md) | Literature + database integration |
| [`blacksmith`](agents/blacksmith.md) | Computation, statistics, feature engineering |
| [`adversary`](agents/adversary.md) | Methodological audit + peer review; auto-refers IP-bearing work to the [`lawyer`](agents/lawyer.md) and folds their verdict into its own |
| [`artist`](agents/artist.md) | Visualization, communication, education |
| [`teacher`](agents/teacher.md) | Three modes, one entry point — `teacher debrief` \| `explain` \| `course` (see below). Debrief is "wait, what?" — fired at the sentence CC just wrote that was jargon, overcomplicated, or handed you an unexplained decision; it re-pitches that in plain words in chat, under 60s, from the tail of the real session transcript. Explain covers any method or paper; course recognises a subject and hands it to the course skill. Only explain renders a self-contained HTML page, on request, annotated in `lavish-axi` — where "wait, what?" gets that same re-pitch. Bullet-led and jargon-light, and it makes things **visual — reusing before drawing**: first a real image it found and may reuse (inlined with its licence, captioned with what to notice), then a video it actually loaded, and only then something hand-drawn (inline SVG, mermaid, a slider) when nothing suitable exists or the reader needs a knob to drag. Figures needing real data still go to the [`artist`](agents/artist.md). It has `WebSearch`/`WebFetch` for exactly this, **scoped: `debrief` is offline entirely**, since a search query is outbound text and session transcripts are not public. It never emits a URL, title, or attribution it did not load; citations it cannot verify escalate to the [`bookworm`](agents/bookworm.md). (persona: Richard Feynman — answers to "Feynman") |
| [`conscience`](agents/conscience.md) | EDID + bias review. **Reviewing is the default and is not a mode** — located, line-by-line findings, every one with a citation, and its rules bind whatever else the agent is doing. One entry point, no mode to select: it is pointed at something and infers from it whether one of two other things is wanted instead, each inferred rather than named: **explain** fires on a flag the author disputed or missed, and re-pitches that one flag — in chat, or on request as an HTML page annotated in `lavish-axi`; it either teaches the concept or names an existing training module. and **design** fires when nothing has been built yet, returning the equitable blueprint — the design itself, not objections to one already built. Never speaks for — or as — a marginalized community; doesn't browse — the [`bookworm`](agents/bookworm.md) curates its resources. **No persona:** it works in a tradition (bell hooks, Freire, Lorde, Baldwin) and cites it rather than impersonating it. |
| [`lawyer`](agents/lawyer.md) | Patent counsel + freedom-to-operate (formerly `saul_goodman`); reached on request **or** by automatic referral from the [`adversary`](agents/adversary.md) mid-audit — triages first, so a referral with no IP surface costs one step, not six database searches |
| [`cable_guy`](agents/cable_guy.md) | Infrastructure provisioner |
| [`centre_cable_guy`](agents/centre_cable_guy.md) | Centre-wide infrastructure reconciler (cross-lab ACLs, drift loop) |
| [`judge`](agents/judge.md) | Combines and presents member contributions in a compositional choreography |
| [`registrar`](agents/registrar.md) | Centre-wide registry of labs/cores/collaborations |
| [`security_guard`](agents/security_guard.md) | Secrets, PHI, world-accessible files audit |

Group/core toolkits build on top of the commons — discipline-specific
agents (medchem, segmenter, cohort, …) live in the owning group's
own repo and compose against this reference set.

## Hard rules (always loaded)

Auto-loaded into every CC session via `~/.claude/rules/`:

- [`rules/data-storage.md`](rules/data-storage.md) — the `immutable/`
  directory is read-only and `append_only/` is append-only (data lives under
  `$MURMURENT_DATA_ROOT`; legacy `raw/`/`refined/` and `MURMURENT_LAB_VM_ROOT`
  stay recognized during the transition). Upheld for agents by the
  [`raw_guard`](src/murmurent/hooks/raw_guard.py) +
  [`protected_paths`](src/murmurent/hooks/protected_paths.py) hooks, which
  refuse deletes and overwrites under immutable/append_only **from inside a
  Claude Code session**. This is a guardrail, not a security perimeter: the
  hooks are per-user and inert in a plain shell, in a script run outside a
  session, and for any member who has not installed them. The trees themselves
  are group-writable on disk.
- [`rules/project-structure.md`](rules/project-structure.md) —
  `~/repos/<project>/{exp,src,obsolete,data}`, snake_case, integer-versioned files.
- [`rules/oracle_schema.md`](rules/oracle_schema.md) — every Oracle
  entry needs `title`, `date`, `project`, `sensitivity`, `tags`, `sources`.
- [`rules/headline_first.md`](rules/headline_first.md) — every agent's
  final reply leads with a ≤200-char verdict.
- [`rules/slack.md`](rules/slack.md) — Slack-posting protocol (after
  every `git push`, post to the group's own channel). Which channel,
  workspace and bot is a deployment fact and lives in `rules/local/`.

**Deployment-specific rules.** A centre may add its own rules under
`rules/local/`, which `scripts/setup.sh` symlinks alongside the shared
ones when the directory exists. That is where private repos, Slack IDs
and local conventions belong, so that nothing tied to one centre reaches
another. A fresh clone has no `rules/local/` and simply skips it.

## User-invocable skills (the commons)

Defined in [`skills/`](skills/), symlinked into `~/.claude/skills/` by
[`scripts/setup.sh`](scripts/setup.sh). Each is a single-purpose slash
command available in any murmurent-bootstrapped CC session.

| Skill | Role |
|---|---|
| [`/murmurent-push`](skills/murmurent-push/SKILL.md) | Murmurent-aware stage/commit/push: skips per-machine + secret-shaped files, refuses large files that belong in `append_only/`, never touches the data root's `immutable/`\|`append_only/` (or legacy `raw/`\|`refined/`), posts a Slack release note. Use instead of generic `/commit-push` for any **murmurent-ready** repo (`.murmurent.yaml`, or a legacy `CHARTER.md` bootstrap). |
| [`/murmurent-project-push`](skills/murmurent-project-push/SKILL.md) | Project-WIDE commit/push: backs up **every** repo a project owns (via `murmurent project push`), running the `/murmurent-push` pre-flight per repo (secret scan, secret-shaped names, governed-data + large-file guards). A repo that fails is blocked, the rest proceed; one plain-language summary + one Slack note to the project channel. Use to "back up my whole project". |
| [`/murmurent-admin`](skills/murmurent-admin/SKILL.md) | Prime context before admin-level (centre / mayor / registrar / join / provisioning) work: reloads murmurent's purpose from the code and docs, and pins Obsidian maps-legends and CC guidance to the top. A centre with its own reference documents adds them via `rules/local/`. |
| [`/murmurent-reset`](skills/murmurent-reset/SKILL.md) | Back up, then reset this machine's murmurent state to a fresh start (so `centre-init` is first-run again). Tiered `centre`/`install`/`full`; always tarballs `~/.murmurent` first; credentials + other-project installs are protected behind explicit `--nuke` flags; `--dry-run` previews. Use for a clean slate / fresh copy from the repo. |
| [`/murmurent-onboard`](skills/murmurent-onboard/SKILL.md) | Mayor/registrar helper: process an incoming **encrypted** join-request email end to end — decrypt + file it, show who's asking, then (on explicit OK) approve + provision (lab/core Slack channel, GitHub repo, FS ACLs) or decline. Approval reads the Slack token from env **or** the `~/.config` file so the channel is created without exporting anything. |
| [`/murmurent-course`](skills/murmurent-course/SKILL.md) | **COURSE mode of the [`teacher`](agents/teacher.md)** — reached by typing `teacher course <subject>`, not by the slash command. Teaches a subject across **multiple sessions** using a course directory as stateful memory: interviews for the mission, sources it through the [`bookworm`](agents/bookworm.md), writes self-contained HTML lessons the learner annotates in `lavish-axi`, and keeps learning records so it never re-teaches what they've demonstrated. Sources **watching as well as reading** — every lesson carries a drawn figure, and where a public explainer beats the page, it assigns the video and writes the bridge instead of competing. Runs in the main session — a subagent can neither interview nor persist. |

## The `teacher <mode>` convention

The [`teacher`](agents/teacher.md) has **three modes**, and one entry point. Type the verb;
never the slash command:

| You type | What runs | Why |
|---|---|---|
| `teacher debrief` (at the sentence that lost you) | the **subagent**, DEBRIEF mode | isolated context is the point — it reads the transcript under rails the main session doesn't have |
| `teacher explain <thing>` | the **subagent**, EXPLAIN mode | one artifact, one sitting; keeps the reading out of your context |
| `teacher course <subject>` | the **[`murmurent-course`](skills/murmurent-course/SKILL.md) skill**, in the main session | a course must interview you and persist; a subagent can do neither |

If the main session mis-routes a course request to the subagent, **mode 3 catches it** — teacher
returns `Gap — this is a course, not an explanation` and names the skill, and the session
invokes it on the rebound. Primary and fallback, not redundancy.

**A debrief is "wait, what?", not a catch-up.** Fire it at the sentence CC just wrote that
was jargon, that made a small mechanism it just built sound intricate, or that asked you to
decide something it never explained. It re-pitches *that* in plain words and says what
follows. It is not for narrating a session you looked away from.

**It answers in chat, in under 60 seconds, and stops.** No file, one dispatch, reading the
tail of the transcript rather than its history — it is read mid-task by someone who wants to
keep working, and a debrief that arrives after you've moved on has failed however good it is.
Want an annotatable artifact? That's `teacher explain <the thing>`, which is allowed to cost
minutes and tens of thousands of tokens. A debrief isn't.

**A debrief does not ask you planning questions.** Deciding what to do next is a back-and-forth,
and a subagent replies once and never hears your answer. Use the **`grilling`** skill for that —
not part of the commons; install it with `npx skills add mattpocock/skills`. It runs in your
session, so it can actually follow up.

**Nothing now forces that step, and that is a real trade.** The design it replaced made the
challenge unskippable. If a plan being explained and then executed without ever being
questioned turns out to matter, the fix belongs in how you dispatch — not inside teacher, which
replies once and cannot hold a back-and-forth.

## Linked references (loaded on-demand)

- [`docs/edid_resources.md`](docs/edid_resources.md) — the EDID resource pool the
  [`conscience`](agents/conscience.md) cites from: five domains, each with its own
  *flag this / suggest that* directive, plus an ingestion backlog the bookworm owns.
- [`docs/oracle-workflow.md`](docs/oracle-workflow.md) — personal vs lab Oracle, publish flow, MCP search.
- [`docs/obsidian-layout.md`](docs/obsidian-layout.md) — vault-side conventions + cross-reference to vault's own `CLAUDE.md` and `maps-legends/`.
- [`docs/vscode-workflow.md`](docs/vscode-workflow.md) — launcher, 4-quadrant layout, agent reporter, tmux copy-paste.
- [`docs/setup.md`](docs/setup.md) — per-machine + per-project install steps.
- [`docs/vault-setup.md`](docs/vault-setup.md) — members: create/adopt your
  personal vault (`murmurent vault init [--adopt]`); the symlinked-folder gotcha.
- [`docs/ready_vs_projects.md`](docs/ready_vs_projects.md) — "murmurent-ready"
  (repo-level: `.murmurent.yaml` + commons agents) vs. a project
  (governance-level: repos + certified members, in `cert_projects/`) — the
  split that replaced adopt-also-minting-a-project.
- [`docs/reconcile.md`](docs/reconcile.md) — `murmurent reconcile` drift-detection routine + daily `/routine` schedule.
- [`docs/versioning.md`](docs/versioning.md) — CalVer scheme (`YYYY.M.MICRO`),
  single-source version in `__init__.py`, when to bump vs not, releases; schema
  versions are independent.
- [`docs/style/code-style.md`](docs/style/code-style.md) — Python/R style
  preferences (CC follows the same defaults; this is for human reference,
  not always-loaded).
- [`docs/style/documentation.md`](docs/style/documentation.md) — script-header + README conventions.
- [`docs/group_level.md`](docs/group_level.md) — group-level architecture notes.
- [`docs/cli_manual.md`](docs/cli_manual.md) — CLI command reference.
- [`docs/keyring.md`](docs/keyring.md) — the `murmurent keyring`: sync a centre's
  shared secrets across a principal's machines (per-machine `age` identities +
  multi-recipient boxes in `lab_info`, locked per role); deploy + test runbooks
  in [`docs/keyring_deploy.md`](docs/keyring_deploy.md).
- [`docs/project_creation.md`](docs/project_creation.md) — vignettes: creating
  intra- and inter-group projects (lead-signed certificates, private channel,
  shared-workspace gate).
- [`docs/slack_setup.md`](docs/slack_setup.md) — mayor's one-time Slack setup:
  workspace + bot token + scopes, `centre-slack-smoke` / `centre-slack-setup`,
  and how lab/core/mayor channels + broadcasts get created.

## Related repos + the public hub

A murmurent deployment spans this repo plus a global onboarding hub, and
each group adds a governance repo of its own. Name them precisely, and
keep every deployment institution-agnostic: drive names off a centre's
`unique_name`, never a hardcoded university or GitHub owner.

`<owner>` below is whoever hosts the deployment. Only the first two rows
name a fixed location, because they are the repos everyone clones.

| Repo | Purpose |
|---|---|
| [`hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent) | **this repo** (public) — agents, rules, hooks, MCP servers, CLI, dashboard. Clone this to install murmurent or bootstrap a centre. |
| [`hallettmiket/murmurent_public`](https://github.com/hallettmiket/murmurent_public) | global onboarding hub: institution directory + GitHub-issue join intake (no netnames / server paths). Novice-facing README kept trivial; maintainer/mayor setup lives in [`docs/hub_setup.md`](docs/hub_setup.md). |
| `<owner>/murmurent_lab_mgmt_<lab>` | per-group governance repo (private), one per lab/core — canonical name, see [`docs/lab_mgmt.md`](docs/lab_mgmt.md) |
| `<owner>/<choreography>` | a choreography: one recurring multi-actor workflow, with its own repo, decision log and data |

A centre with further repos of its own (a manuscript, a grant, internal
notes) records them in `rules/local/`, not here.

## Quick setup

```bash
bash scripts/setup.sh              # symlinks agents/ + rules/ + skills/ into ~/.claude/
murmurent install --hooks            # registers hooks + MCP servers
```

Full setup notes including remote-host wiring: [`docs/setup.md`](docs/setup.md).
