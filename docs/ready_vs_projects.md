# "Murmurent-ready" vs. a project

Murmurent has two distinct levels of structure: a repo-level property
called "murmurent-ready," and a governance-level object called a
"project." This page explains each in turn, then how they relate.

## Making a repo Murmurent-ready

A git clone under `~/repos/<name>` is **murmurent-ready** when it carries:

1. a `.murmurent.yaml` marker at its root (schema version, owning lab,
   the agents picked, and the Murmurent version that last bootstrapped it), and
2. a `.claude/agents/` directory: symlinks into the Murmurent commons.

Readiness means Claude Code sessions opened in that repo have the commons
agents and rules wired in.

### Adopting a repo

You make a repo ready with:

```bash
murmurent repo adopt <path> [--lab <slug>] [--agents a,b] [--host <name>]
```

This is the same action as the dashboard Repos panel's **↑ adopt** button.
Parameters, for a naive reader:

- `<path>`: the local path to the git clone (e.g. `~/repos/brca_wgs`).
- `--lab <slug>`: the owning lab's short registry name (its "slug," e.g.
  e.g. `mh`). Defaults to this machine's lab.
- `--agents a,b`: a comma-separated list of which commons agents to wire
  in (e.g. `bookworm,blacksmith`). Defaults to the standard set if
  omitted.
- `--host <name>`: which machine to act on. `local` (default) is this
  laptop; any other value is a registered remote machine (see `murmurent
  host list`), acted on over SSH.

### Checking readiness

Check readiness without changing anything:

```bash
murmurent repo status <path-or-name> [--host <name>]   # check one repo
murmurent repo list [--host <name>]                    # list every clone + its verdict
```

Example `repo list` output:

```
NAME       PATH                    VERDICT
brca_wgs   ~/repos/brca_wgs        ready
brca_sc    ~/repos/brca_sc         partial
scratch    ~/repos/scratch         plain clone
old_proj   ~/repos/old_proj        missing
```

Verdicts, defined for a naive reader:

- **ready**: has both the `.murmurent.yaml` marker and `.claude/agents/`.
  Good to go.
- **partial**: has one but not the other (for example agents linked but
  no marker yet). Run `murmurent repo adopt` (or the Upgrade button) to
  finish.
- **plain clone**: an ordinary git repo with neither. Not wired into
  Murmurent.
- **not a git repo** / **missing**: the path is not a git checkout, or
  does not exist.

### Upgrading after a new Murmurent release

This applies to any ready repo, not just repos attached to a project.

Agent *content* edits (an agent's prompt gets changed) reach every ready
repo automatically: `.claude/agents/<name>.md` is a symlink into the
commons clone, so a `git pull` on `~/repos/murmurent` updates every repo
that links it, with nothing further to run.

*Structural* changes don't flow through the symlink: a brand-new commons
agent that didn't exist when a repo was adopted, or a bump to the
`.murmurent.yaml` schema. Those need an explicit:

```bash
murmurent repo upgrade <path> [--add-agents a,b] [--all-agents]
murmurent repo upgrade --all [--add-agents a,b] [--all-agents]
```

`--add-agents` links specific new agents into an already-ready repo
without touching the ones already linked; `--all-agents` links every
commons agent (new releases included). `--all` applies the upgrade to
every ready repo under `~/repos` instead of a single path. Neither flag
is needed just to pick up prompt edits to agents already linked; that
part is automatic.

## Projects

A Murmurent **project** is a named, governed collaboration. It consists
of:

- a set of Murmurent-ready repos,
- a set of cryptographically certified members,
- a project lead,
- a sensitivity tier (`standard` / `restricted` / `clinical`), and
- once provisioned, a private Slack channel.

**Lead**: the project lead is the member who holds the project-lead
certificate; the lead signs other members into the project. It defaults
to the first member at creation.

**Repos**: the repos a project lists are existing, already-Murmurent-ready
clones. Creating a project attaches existing repos, and can also create
and clone one fresh repo for the project. Every repo a project lists is,
or becomes, Murmurent-ready. Creating a project never turns a random
directory into a repo.

**Where projects are recorded**: the authoritative registry is
`cert_projects/<name>.md` in the lab's governance repo,
`murmurent_lab_mgmt_<lab>`. That registry is what the dashboard reads to
know which projects exist.

**How a project is created**: from the dashboard's **New Project** flow,
which attaches existing ready repos and can create and clone a new one on
approval. (A `murmurent project new` CLI exists but predates the current
certificate-based model; the dashboard is the current path.) See
[`project_creation.md`](project_creation.md) for the full walkthrough
(intra- and inter-group vignettes, the certificate chain, the Slack
channel).

## The relationship, in one picture

```
repo (git clone under ~/repos)
  │
  ├─ murmurent-ready?  .murmurent.yaml + .claude/agents/
  │     "can I run murmurent agents here"        ← murmurent repo adopt / upgrade
  │
  └─ attached to a project?  cert_projects/<name>.md in lab_mgmt
        "is this repo part of a named, governed collaboration"
              ← dashboard New Project flow
```

- A repo can be ready and attached to zero projects (adopt it and stop
  there; that's a normal, common state).
- A project's repos are all ready: readiness is the foundation a project
  is built on.

## See also

- [`setup.md`](setup.md): per-machine + per-project install steps.
- [`project_creation.md`](project_creation.md): how a project actually
  gets created (the two vignettes, the certificate chain).
- [`cli_manual.md`](cli_manual.md): full `murmurent repo …` command
  reference.
- [`reconcile.md`](reconcile.md): the readiness/adoption drift checks
  that watch repos on a schedule.
