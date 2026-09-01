---
name: murmurent-admin
description: Prime context before admin-level (centre / mayor / registrar) work on murmurent. Reloads murmurent's purpose from the code and docs, pins the Obsidian maps/legends and Claude-Code guidance to the top of context, and honours any further reference documents the centre names in rules/local/. Use before designing or changing the administrative layer, the mayor/centre bootstrap, the join flow, or provisioning.
user_invocable: true
---

Murmurent is a large, multi-repo system whose *purpose* and *administrative
architecture* live as much in the design docs as in the code. Before doing
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

## 1. Reload murmurent's purpose from the docs

The administrative layer uses **registrar / receptionist / accountant /
centre-level security guard**; note there is **no "mayor" agent** — "mayor"
is a *human bootstrap role* only.

- Start from [`docs/centre_overview.md`](../../docs/centre_overview.md),
  [`docs/overview.md`](../../docs/overview.md) and
  [`docs/group_level.md`](../../docs/group_level.md): the centre, cores, labs,
  the commons and the reference agents.
- **A centre may hold further authoritative documents of its own** (a paper, a
  grant, internal design notes). Those are deployment facts, so they are named
  in `rules/local/` rather than here. If `rules/local/` exists, read what it
  names first, and follow any pull-first or write rules it states.

## 2. Read the code before proposing changes

Skim the centre/admin layer so you reuse what exists instead of
re-implementing it:

- `src/murmurent/core/centre_init.py` — centre profile / mayor bootstrap.
- `src/murmurent/core/join_requests.py` — the join queue + approve dispatch.
- `src/murmurent/core/centre_provision.py` — Slack/GitHub/FS provisioning.
- `src/murmurent/core/registrar.py` — the registry + `is_registrar`.
- `agents/registrar.md`, `agents/security_guard.md`, `agents/cable_guy.md`,
  `agents/centre_cable_guy.md` — the admin-layer agents.

## 3. The three repos + the public hub

Murmurent spans three repos plus a global onboarding hub. Name them
precisely when you reference them:

| Repo | Purpose |
|---|---|
| `github.com/hallettmiket/murmurent` | reference implementation (**public**): agents, rules, hooks, MCP servers, CLI, dashboard. This is what a new mayor clones to bootstrap a centre. |
| `<owner>/murmurent_lab_mgmt_<lab>` | per-group governance repo (private; registry + lab Oracle publish gateway) |
| `github.com/hallettmiket/murmurent_public` | global onboarding hub for self-service join |
| anything else the centre owns | named in `rules/local/`, not here |

## 4. Then act

Only after 0–3 are loaded, proceed with the admin-level task. Prefer
extending the existing centre modules over adding parallel machinery, and
keep every deployment **institution-agnostic** (drive names off the
centre's `unique_name`, never a hardcoded university).
