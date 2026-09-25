# Making a repo Murmurent-ready

A **repo** (repository) is a folder of code and files tracked by git,
living under `~/repos/` on your machine. Your day-to-day research work
happens inside repositories.

A **Murmurent-ready** repo is a git clone Murmurent has registered, by
writing a `.murmurent.yaml` marker at its root. This page covers how to make
a repo ready, check its status, and upgrade it after a release. A project is a
separate, higher-level thing built on top of ready repos; see
[`project_intra.md`](project_intra.md).

## What readiness does and does not do

**It does not give you the agents.** `murmurent setup` (run by `murmurent
install`) links the whole commons into `~/.claude/agents/`, and Claude Code
loads those in *every* directory on the machine. Every agent is therefore
available in every folder, ready or not. Documentation that said otherwise was
wrong, and this section exists because that error survived several rewrites.

What readiness does buy, all of it keyed on that marker file:

1. **The PHI check runs.** `hooks/phi_check.py` inspects outbound tool calls
   (`WebFetch`, `WebSearch`, `Bash`) for patient identifiers — health-card and
   medical-record numbers, SINs, a name adjacent to a date of birth — and
   redacts them. It resolves the project by walking up for the marker
   (`core.repo.find_project_repo`) and returns early when there is none: *"not
   inside a project repo → no PHI context to guard"*. In a folder that is not
   ready, **the check does nothing**. This is the reason to make a folder
   ready, and the only one that can cost you something real.
2. **The audit log attributes activity to a project.** `hooks/audit.py` names
   the project the same way; without a marker the entry is recorded without it.
3. **The repo can be attached to a project.** `core.cert_projects` finds a
   project's code repo through the marker, and stamps one if a legacy
   `CHARTER.md` repo is being migrated, precisely so the repo stays
   discoverable.
4. **The repo can declare itself clinical.** `sensitivity: clinical` in the
   marker makes `core.personal_audit` treat it as holding patient data
   regardless of what the project registry says.
5. **It appears as ready** in `murmurent repo list` and the dashboard's Repos
   panel.

Note what is *not* on that list: the read-only guarantees on the governed data
directories (`hooks/raw_guard.py`, `hooks/protected_paths.py`) are keyed on
paths, not on readiness, so they apply everywhere.

## The per-repo `.claude/agents/` directory

`adopt` creates this directory, and populates it only if you name agents with
`--agents`, or all of them with `--all-agents`. Since access comes from
`~/.claude/agents/` regardless, a repo's own copies do exactly one thing:
**Claude Code prefers a directory's own agent file over the machine-wide one**,
so a link here pins that agent, for this repo, to whatever it points at.

That is occasionally useful — pinning one project to a particular version of an
agent — and twice a liability:

- **The links are absolute paths to one machine.** Git stores
  `.claude/agents/oracle.md` as a symlink whose content is, for example,
  `/home/mike/repos/murmurent_dev/agents/oracle.md`. Commit it, and on a
  colleague's machine — different home directory, or Murmurent installed from
  PyPI with no clone at all — every one of those links dangles. The portable
  record is the marker's own `agents:` list, which `repo adopt`/`repo upgrade`
  read to recreate the links locally.
- **A wrong link is silent.** A repo whose links point into a second Murmurent
  clone runs a different version of those agents from the rest of the machine,
  with no error. `murmurent repo status` reports this as a `follows commons`
  line, and the `UserPromptSubmit` hook warns in-session.

If you have no reason to pin an agent to a single repo, run `adopt` with
neither option and leave the directory empty.

## Start here: any directory

The same procedure covers a brand-new folder, a repository you have worked in
for years, and one that an older Murmurent release set up. Ask first, because
the verdict decides the step:

```bash
murmurent repo status ~/repos/<directory>
```

| Verdict | What it means | Do this |
|---|---|---|
| `✗ no such folder` | the path is wrong | check the path |
| `✗ not tracked by git` | a plain folder | `git -C ~/repos/<directory> init`, then the next row |
| `• not set up yet` | git, and Murmurent has never set it up | `murmurent repo adopt ~/repos/<directory>` |
| `± half set up` | a marker without agent links, or the reverse | the same `adopt` — it completes the setup |
| `✓ ready`, bootstrapped by an older version | ready, set up by an earlier release | `murmurent repo upgrade ~/repos/<directory>` |
| `✓ ready`, current version | finished | open Claude Code in it |

Murmurent tracks a directory through git, so the plain-folder row comes first:
`repo adopt` on a folder without a `.git/` directory stops and says so. The
directory has to live under `~/repos/` (or the folder named by
`MURMURENT_REPOS_ROOT`), which is where the inventory looks.

Adopting writes the two things readiness consists of, the `.murmurent.yaml`
marker and the `.claude/agents/` symlinks, and leaves every other file as it
was. Commit both, so each clone of the repository is ready as well.

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
