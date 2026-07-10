---
name: murmurent-admin
description: Prime context before admin-level (centre / mayor / registrar) work on murmurent. Reloads murmurent's purpose from the manuscript and code, pins the Obsidian maps/legends and Claude-Code guidance to the top of context, and enforces the manuscript pull-first rule. Use before designing or changing the administrative layer, the mayor/centre bootstrap, the join flow, or provisioning.
user_invocable: true
---

Murmurent is a large, multi-repo system whose *purpose* and *administrative
architecture* live as much in the manuscript as in the code. Before doing
admin-level work — the centre/mayor bootstrap, the registrar, the join
flow, provisioning, or the install story for a new institution — reload
that context so you act from murmurent's actual design, not a half-remembered
version of it. Do this **first**, before proposing or writing changes.

## 0. Load orientation to the top of context

Read these first so they anchor the rest of the session:

1. **Obsidian maps/legends** — the vault's `maps-legends/` and the vault's
   own `CLAUDE.md` (see `docs/obsidian-layout.md` for where the registered
   vault is). These are the human index into the project's knowledge.
2. **How to use Claude Code here** — the top-level `CLAUDE.md` of this repo
   (agents, hard rules, skills) and `docs/vscode-workflow.md`.

## 1. Reload murmurent's purpose from the manuscript

The manuscript is the authoritative description of what murmurent is and how
the administrative layer is meant to work (it uses **registrar /
receptionist / accountant / centre-level security guard**; note there is
**no "mayor" agent** — "mayor" is a *human bootstrap role* only).

- Repo: `~/repos/murmurent_manuscript`, remote
  `git@github.com:hallettmiket/murmurent_manuscript.git`, single source
  `main-article.tex`. Read the "Beyond the individual" / Results section on
  the centre, cores, labs, commons, and the twelve reference agents.
- **If your task will modify the manuscript, `git -C
  ~/repos/murmurent_manuscript pull` FIRST** (it's synced with Overleaf via
  GitHub — see `rules/manuscript.md`). Overleaf edits are authoritative on
  conflict; no feature branches; do not compile locally.

## 2. Read the code before proposing changes

Skim the centre/admin layer so you reuse what exists instead of
re-implementing it:

- `src/wigamig/core/centre_init.py` — centre profile / mayor bootstrap.
- `src/wigamig/core/join_requests.py` — the join queue + approve dispatch.
- `src/wigamig/core/centre_provision.py` — Slack/GitHub/FS provisioning.
- `src/wigamig/core/registrar.py` — the registry + `is_registrar`.
- `agents/registrar.md`, `agents/security_guard.md`, `agents/cable_guy.md`,
  `agents/centre_cable_guy.md` — the admin-layer agents.

## 3. The three repos + the public hub

Murmurent spans three repos plus a global onboarding hub. Name them
precisely when you reference them:

| Repo | Purpose |
|---|---|
| `github.com/hallettmiket/wigamig` | reference implementation (**public**): agents, rules, hooks, MCP servers, CLI, dashboard. This is what a new mayor clones to bootstrap a centre. |
| `github.com/hallettmiket/murmurent_manuscript` | the paper (private; Overleaf-synced) |
| `github.com/hallettmiket/lab_mgmt` | per-group governance repo (private; registry + lab Oracle publish gateway) |
| `github.com/hallettmiket/murmurent_public` *(planned — Phase 2)* | global onboarding hub for self-service join. **Not yet created**; onboarding is the phase after the admin level. |

## 4. Then act

Only after 0–3 are loaded, proceed with the admin-level task. Prefer
extending the existing centre modules over adding parallel machinery, and
keep every deployment **institution-agnostic** (drive names off the
centre's `unique_name`, never a hardcoded university).
