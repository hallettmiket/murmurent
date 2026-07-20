# Making a repo Murmurent-ready

A **Murmurent-ready** repo is a git clone that has the commons agents and
rules wired in, so Claude Code sessions opened in it can use Murmurent.
This page covers how to make a repo ready, check its status, and upgrade
it after a release. A project is a separate, higher-level thing built on
top of ready repos; see [`project_intra.md`](project_intra.md).

A git clone under `~/repos/<name>` is **murmurent-ready** when it carries:

1. a `.murmurent.yaml` marker at its root (schema version, owning lab,
   the agents picked, and the Murmurent version that last bootstrapped it), and
2. a `.claude/agents/` directory: symlinks into the Murmurent commons.

Readiness means Claude Code sessions opened in that repo have the commons
agents and rules wired in.

## Adopting a repo

You make a repo ready with:

```bash
murmurent repo adopt <path> [--lab <slug>] [--agents a,b] [--host <name>]
```

This is the same action as the dashboard Repos panel's **↑ adopt** button.
Parameters:

- `<path>`: the local path to the git clone (e.g. `~/repos/brca_wgs`).
- `--lab <slug>`: the owning lab's short registry name (its "slug,"
  e.g. `example_lab`). Defaults to this machine's lab.
- `--agents a,b`: a comma-separated list of which commons agents to wire
  in (e.g. `bookworm,blacksmith`). Defaults to the standard set if
  omitted.
- `--host <name>`: which machine to act on. `local` (default) is this
  laptop; any other value is a registered remote machine (see `murmurent
  host list`), acted on over SSH.

## Checking readiness

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

Verdicts:

- **ready**: has both the `.murmurent.yaml` marker and `.claude/agents/`.
- **partial**: has one but not the other (for example agents linked but
  no marker yet). Run `murmurent repo adopt` (or the Upgrade button) to
  finish.
- **plain clone**: an ordinary git repo with neither marker, outside
  Murmurent's configuration.
- **not a git repo** / **missing**: the path is not a git checkout, or
  does not exist.

## Upgrading after a new Murmurent release

This applies to every ready repo, whether or not it's attached to a
project.

Agent content edits (an agent's prompt gets changed) reach every ready
repo automatically: `.claude/agents/<name>.md` is a symlink into the
commons clone, so a `git pull` on `~/repos/murmurent` updates every repo
that links it, with nothing further to run.

Structural changes do not flow through the symlink: a brand-new commons
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

## See also

- [`setup.md`](setup.md): per-machine + per-project install steps.
- [`project_intra.md`](project_intra.md): what a project is and how one
  gets created.
- [`cli_manual.md`](cli_manual.md): full `murmurent repo …` command
  reference.
- [`reconcile.md`](reconcile.md): the readiness/adoption drift checks
  that watch repos on a schedule.
