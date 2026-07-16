# "Murmurent-ready" vs. a project

These two ideas used to be fused — adopting a repo used to *also* mint a
project — and that fusion caused real confusion (five trial adoptions once
masqueraded as projects on the dashboard). Since the 2026-07-15 split
they're deliberately separate, and most of the rest of the docs assume you
know the difference. This page is that explanation, in one place.

## Murmurent-ready — a repo-level property

A git clone under `~/repos/<name>` is **murmurent-ready** when it carries:

1. a `.murmurent.yaml` marker at its root (schema version, owning lab,
   the agents picked, and the Murmurent version that last bootstrapped it), and
2. a `.claude/agents/` directory — symlinks into the Murmurent commons.

That's it. Readiness means "Claude Code sessions opened in this repo have
the Murmurent agents + rules wired in." It does **not** create a project, a
roster, a Slack channel, or a registry entry anywhere. A repo can be
murmurent-ready and belong to zero projects — that's the normal state for,
say, a personal scratch repo you just want the commons agents in.

You make a repo ready with:

```bash
murmurent repo adopt <path> [--lab <slug>] [--agents a,b] [--host <name>]
```

— the CLI twin of the dashboard's Repos panel **↑ adopt** button. Check
readiness without changing anything with:

```bash
murmurent repo status <path-or-name> [--host <name>]
murmurent repo list [--host <name>]
```

`repo list` / `repo status` report one of these verdicts (the same glyphs
the Repos panel uses): `✓ ready`, `✓ ready (legacy)`, `± partial`,
`• clone`, `✗ not a git repo`, `✗ missing`.

### Legacy CHARTER.md-only bootstraps

Before the split, "ready" meant a `CHARTER.md` at the repo root (adopting a
repo *wrote* one, as a project charter). Repos bootstrapped that way still
count as ready — the verdict is **"ready (legacy)"** — but the marker shape
is old. Convert with:

```bash
murmurent repo upgrade <path>          # one repo
murmurent repo upgrade --all           # every ready repo under ~/repos
```

This replaces the `CHARTER.md` bootstrap with `.murmurent.yaml` (lifting
`lab:` and the existing agent picks out of the charter first), migrates the
marker schema, and re-stamps `bootstrap_version`.

**Caution if the repo is also a project's primary code repo:** a project
created through the dashboard's install/provision flow (below) still gets
a `CHARTER.md`-shaped legacy bootstrap on its primary repo. `repo upgrade`
deletes that `CHARTER.md` once it's converted. The project record itself is
unaffected — it lives in the lab_mgmt registry, not in the file you just
deleted — but a couple of dashboard display fields (the project row's Slack
channel id, `repo_kind`, and remote URL) are read live off `CHARTER.md` and
will go blank until the project is re-synced. Upgrading a project's primary
repo is safe for readiness purposes; just expect to re-check those fields
on its dashboard row afterward.

## A project — a governance-level object

A Murmurent **project** is a very specific, bigger thing: a named set of
**repos** (existing clones — creating a project never creates a repo) plus a
named set of cryptographically **certified members**, plus a lead,
sensitivity tier, and (once provisioned) a private Slack channel. Projects
are recorded in the lab's lab_mgmt repo under `cert_projects/<name>.md` —
that registry is the **only** source of truth the dashboard reads for "what
projects exist." It no longer scans `~/repos` for `CHARTER.md` files; that
old behaviour is exactly what let bare adoptions masquerade as projects.

Projects are created from the dashboard's **New Project** flow, which
*attaches* existing repos (`attach_repos`) and can create + clone a fresh
one for the project on approval — never the other way around: making a
repo ready has never created a project. See
[`project_creation.md`](project_creation.md) for the full walkthrough
(intra- and inter-group vignettes, the certificate chain, the Slack
channel).

## The relationship, in one picture

```
repo (git clone under ~/repos)
  │
  ├─ murmurent-ready?  .murmurent.yaml (or legacy CHARTER.md) + .claude/agents/
  │     "can I run murmurent agents here"        ← murmurent repo adopt / upgrade
  │
  └─ attached to a project?  cert_projects/<name>.md in lab_mgmt
        "is this repo part of a named, governed collaboration"
              ← dashboard New Project flow
```

- A repo can be ready and attached to **zero** projects (adopt it and stop
  there — perfectly normal).
- A project always has at least one repo, and every repo it lists is (or
  becomes, at attach time) murmurent-ready — readiness is necessary
  plumbing underneath a project, not the other way around.
- `CHARTER.md`, where it still appears, is either (a) a legacy readiness
  marker on a repo that predates the split — convert it with
  `murmurent repo upgrade` — or (b) metadata written into a project's
  primary repo at project-creation time. Either way, **the authoritative
  record of which projects exist and who's in them is `cert_projects/` in
  lab_mgmt, never a `CHARTER.md` file.**

## Upgrading after a new Murmurent release

Agent *content* changes (an agent's prompt gets edited) reach every
murmurent-ready repo automatically — `.claude/agents/<name>.md` is a
symlink into the commons clone, so a `git pull` on `~/repos/murmurent`
updates every repo that links it, with nothing further to run.

*Structural* changes don't flow through the symlink — a brand-new commons
agent that didn't exist when a repo was adopted, or a bump to the
`.murmurent.yaml` schema. Those need an explicit:

```bash
murmurent repo upgrade <path> [--add-agents <a,b>] [--all-agents]
murmurent repo upgrade --all [--add-agents <a,b>] [--all-agents]
```

`--add-agents` links specific new agents into an already-ready repo without
touching the ones already linked; `--all-agents` links every commons agent
(new releases included). Neither flag is needed just to pick up prompt
edits to agents already linked — that part is automatic.

## See also

- [`setup.md`](setup.md) — per-machine + per-project install steps.
- [`project_creation.md`](project_creation.md) — how a project actually
  gets created (the two vignettes, the certificate chain).
- [`cli_manual.md`](cli_manual.md) — full `murmurent repo …` command
  reference.
- [`reconcile.md`](reconcile.md) — the `missing_charter` / `unadopted_clone`
  drift checks that watch readiness on a schedule.
