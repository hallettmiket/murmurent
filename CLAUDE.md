# Murmurent — agentic AI village for Western's Bioconvergence Centre

Murmurent is shared agentic-AI infrastructure that lets research groups
work independently, pool agents and data when collaboration benefits
them, and accumulate institutional knowledge across every project.

Full vision: [`assets/chair_renewal_1.3.pdf`](assets/chair_renewal_1.3.pdf)
(§ "Proposed Research Program"). TL;DR:

- **Choreography, not orchestration.** Each group runs its own
  documented pattern using shared agents + rules; no central
  controller decides every move. Limits the blast radius of any
  failure and preserves each group's autonomy.
- **Five social units**: individuals, groups (PI + HQP),
  collaborations (sets of groups with projects), cores (e.g.
  proteomics facility), administration (governance).
- **The commons** = centre-wide AI infrastructure every member draws
  on (reference agents + data-governance rules + baseline workflows).
  Group/core *toolkits* are built on top.

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
| [`adversary`](agents/adversary.md) | Methodological audit + peer review |
| [`artist`](agents/artist.md) | Visualization, communication, education |
| [`conscience`](agents/conscience.md) | EDID + bias review |
| [`lawyer`](agents/lawyer.md) | Patent counsel + freedom-to-operate (formerly `saul_goodman`) |
| [`cable_guy`](agents/cable_guy.md) | Infrastructure provisioner |
| [`receptionist`](agents/receptionist.md) | Routes inbound cross-group SEA requests |
| [`registrar`](agents/registrar.md) | Centre-wide registry of labs/cores/collaborations |
| [`security_guard`](agents/security_guard.md) | Secrets, PHI, world-accessible files audit |

Group/core toolkits build on top of the commons — discipline-specific
agents (medchem, segmenter, cohort, …) live in the owning group's
own repo and compose against this reference set.

## Hard rules (always loaded)

Auto-loaded into every CC session via `~/.claude/rules/`:

- [`rules/data-storage.md`](rules/data-storage.md) — raw is immutable,
  refined is append-only. Enforced by [`raw_guard`](src/murmurent/hooks/raw_guard.py)
  + [`protected_paths`](src/murmurent/hooks/protected_paths.py) hooks (delete +
  overwrite under raw or refined are blocked at the hook layer, not just
  by convention).
- [`rules/project-structure.md`](rules/project-structure.md) —
  `~/repos/<project>/{exp,src,obsolete,data}`, snake_case, integer-versioned files.
- [`rules/oracle_schema.md`](rules/oracle_schema.md) — every Oracle
  entry needs `title`, `date`, `project`, `sensitivity`, `tags`, `sources`.
- [`rules/headline_first.md`](rules/headline_first.md) — every agent's
  final reply leads with a ≤200-char verdict.
- [`rules/slack.md`](rules/slack.md) — Slack-posting protocol (after
  every `git push`, post to `#claude-test`).
- [`rules/manuscript.md`](rules/manuscript.md) — the manuscript is
  Overleaf-synced; **`git pull` `~/repos/murmurent_manuscript` before
  editing it**, no feature branches, don't compile locally.

## User-invocable skills (the commons)

Defined in [`skills/`](skills/), symlinked into `~/.claude/skills/` by
[`scripts/setup.sh`](scripts/setup.sh). Each is a single-purpose slash
command available in any murmurent-bootstrapped CC session.

| Skill | Role |
|---|---|
| [`/murmurent-push`](skills/murmurent-push/SKILL.md) | Murmurent-aware stage/commit/push: skips per-machine + secret-shaped files, refuses large files that belong in `refined/`, never touches `/data/lab_vm/raw\|refined/`, posts a Slack release note. Use instead of generic `/commit-push` for any **murmurent-ready** repo (`.murmurent.yaml`, or a legacy `CHARTER.md` bootstrap). |
| [`/murmurent-admin`](skills/murmurent-admin/SKILL.md) | Prime context before admin-level (centre / mayor / registrar / join / provisioning) work: reloads murmurent's purpose from the manuscript + code, pins Obsidian maps-legends and CC guidance to the top, enforces the manuscript pull-first rule. |
| [`/murmurent-reset`](skills/murmurent-reset/SKILL.md) | Back up, then reset this machine's murmurent state to a fresh start (so `centre-init` is first-run again). Tiered `centre`/`install`/`full`; always tarballs `~/.murmurent` first; credentials + other-project installs are protected behind explicit `--nuke` flags; `--dry-run` previews. Use for a clean slate / fresh copy from the repo. |
| [`/murmurent-onboard`](skills/murmurent-onboard/SKILL.md) | Mayor/registrar helper: process an incoming **encrypted** join-request email end to end — decrypt + file it, show who's asking, then (on explicit OK) approve + provision (lab/core Slack channel, GitHub repo, FS ACLs) or decline. Approval reads the Slack token from env **or** the `~/.config` file so the channel is created without exporting anything. |

## Linked references (loaded on-demand)

- [`docs/oracle-workflow.md`](docs/oracle-workflow.md) — personal vs lab Oracle, publish flow, MCP search.
- [`docs/obsidian-layout.md`](docs/obsidian-layout.md) — vault-side conventions + cross-reference to vault's own `CLAUDE.md` and `maps-legends/`.
- [`docs/vscode-workflow.md`](docs/vscode-workflow.md) — launcher, 4-quadrant layout, agent reporter, tmux copy-paste.
- [`docs/setup.md`](docs/setup.md) — per-machine + per-project install steps.
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
- [`docs/project_creation.md`](docs/project_creation.md) — vignettes: creating
  intra- and inter-group projects (lead-signed certificates, private channel,
  shared-workspace gate).
- [`docs/slack_setup.md`](docs/slack_setup.md) — mayor's one-time Slack setup:
  workspace + bot token + scopes, `centre-slack-smoke` / `centre-slack-setup`,
  and how lab/core/mayor channels + broadcasts get created.

## Related repos + the public hub

Murmurent spans three repos plus a global onboarding hub. Name them
precisely; keep every deployment institution-agnostic (drive names off a
centre's `unique_name`, never a hardcoded university).

| Repo | Purpose |
|---|---|
| [`hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent) | this repo (**public**) — agents, rules, hooks, MCP servers, CLI, dashboard. Clone this to install murmurent / bootstrap a centre. |
| `hallettmiket/murmurent_manuscript` | the paper (private; Overleaf-synced — see [`rules/manuscript.md`](rules/manuscript.md)) |
| `hallettmiket/murmurent_lab_mgmt_<lab>` | per-group governance repo (private), one per lab/core — canonical name, see [`docs/lab_mgmt.md`](docs/lab_mgmt.md) |
| [`hallettmiket/murmurent_public`](https://github.com/hallettmiket/murmurent_public) | global onboarding hub: institution directory + GitHub-issue join intake (no netnames / server paths). Novice-facing README kept trivial; maintainer/mayor setup lives in [`docs/hub_setup.md`](docs/hub_setup.md). |

## Quick setup

```bash
bash scripts/setup.sh              # symlinks agents/ + rules/ + skills/ into ~/.claude/
murmurent install --hooks            # registers hooks + MCP servers
```

Full setup notes including remote-host wiring: [`docs/setup.md`](docs/setup.md).
