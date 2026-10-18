# Making a repo Murmurent-ready

A **repo** (repository) is a folder of code and files tracked by git,
living in your repositories folder (`~/repos` unless you chose another;
`murmurent config repos-root` shows it). Your day-to-day research work
happens inside repositories.

A **Murmurent-ready** repo is a git clone Murmurent has registered, by
writing a `.murmurent.yaml` marker at its root. This page covers how to make
a repo ready, check its status, and upgrade it after a release.

**Every repository is part of a project.** A project is the unit Murmurent
works with: its record lists its repositories, its data folders, its members
and its state. Making a repository ready also puts it in a project when it is
in none; see [Every repository is in a project](#every-repository-is-in-a-project)
below. How a project with several members is set up is in
[`project_intra.md`](project_intra.md).

A project often owns several repos, each with a role: `code`, `manuscript`,
`seminar` (talks and slides), `data` or `infra`. On your machine they can sit
together in one project folder, for example `~/repos/brca/brca`,
`~/repos/brca/brca_manuscript` and `~/repos/brca/brca_seminar`, or each
directly in your repositories folder. Murmurent finds them either way; see
[Projects with several repositories](setup.md#projects-with-several-repositories).

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
3. **The repo is found as part of its project.** `core.cert_projects` finds a
   project's code repo through the marker, and stamps one if a legacy
   `CHARTER.md` repo is being migrated, so the repo stays discoverable.
   Commands run inside the repo, such as `murmurent project status`, use it to
   work out which project you are in.
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
  read to recreate the links locally. To stop the links being committed, `adopt`
  names each one in a block at the end of the repo's `.gitignore`, and both push
  commands leave them out. A file you wrote yourself in `.claude/agents/` is not
  a link: it is never replaced, and you commit it as usual.

  If links were committed before this, `murmurent repo status` lists them and
  prints the repair: stop tracking them with `git rm --cached`, commit and
  push, then everyone else runs `murmurent repo upgrade <repo>` straight after
  their next pull to re-create their own links.
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
| `± half set up` | set up by a very old Murmurent (a `CHARTER.md` but no `.murmurent.yaml`) | `murmurent repo upgrade ~/repos/<directory>` |
| `✓ ready`, bootstrapped by an older version | ready, set up by an earlier release | `murmurent repo upgrade ~/repos/<directory>` |
| `✓ ready`, current version | finished | open Claude Code in it |

Murmurent tracks a directory through git, so the plain-folder row comes first:
`repo adopt` on a folder without a `.git/` directory stops and says so. The
directory has to live in your repositories folder, directly or inside a
project folder, which is where the inventory looks.

Adopting writes the two things readiness consists of, the `.murmurent.yaml`
marker and the `.claude/agents/` symlinks, and leaves every other file as it
was. Commit both, so each clone of the repository is ready as well. If no
project lists the repository, adopting also writes a project record for it in
the lab records repository; see the next section.

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

## Every repository is in a project

Each repository belongs to exactly one project, its **owning** project. When
you adopt a repository that no project lists, Murmurent writes a project record
for it, with you as lead and only member, in the lab records repository (the
lab's shared management repository). Adopting it again changes nothing. If the
repository later joins a bigger project, for example through the dashboard's
New Project, its one-repository project is archived (kept, not deleted), so it
still has one owning project.

The project's name comes from the repository's name and place:

| Repository | Project | Role |
|---|---|---|
| `~/repos/brca` | `brca` | `code` |
| `~/repos/brca_manuscript`, when a project or repository `brca` exists | `brca` | `manuscript` |
| `~/repos/brca/brca_seminar` (inside a project folder) | `brca` | `seminar` |
| `~/repos/cell_data`, when nothing called `cell` exists | `cell_data` | `code` |

Adopting never changes a project that already exists. If the repository
belongs by its name to an existing project that does not list it yet, adopt
says so and writes nothing. Add it with `murmurent project migrate`, which
shows the change and asks first.

### Finding repositories and data that are in no project

```bash
murmurent project migrate            # list them and what would be written; writes nothing
murmurent project migrate --apply    # write those records, after you confirm
```

`migrate` lists every repository in your repositories folder, and every folder
directly under `immutable/` and `append_only/` in the data root, that no
project claims. It proposes project records for the repositories, grouping
`x`, `x_manuscript` and `x_seminar` into one project `x`. A data folder named
after a project is claimed by that project. Any other folder stays listed as
unclaimed, for you to decide about. `migrate` never moves, renames or deletes
anything, and `--yes` skips the question for scripts. Murmurent's own
repositories, the lab records repository, and repositories you have marked
private (`murmurent repo private add`) are left out.

### What a project record holds

Besides its repositories and members, a project record has three settings,
all optional:

| Setting | What it holds |
|---|---|
| `data_folders` | The folders the project owns. Left empty, these are `immutable/<project>/` and `append_only/<project>/` under the data root, which is right for most projects. Write a folder in full, or relative to the data root (`append_only/brca`) so it is right on every machine. |
| `reads_from` | What the project reads but does not own: a folder, written as a path (`append_only/shared_cohort`), or another project's repository, by its name. These are never offered to this project for clean-up. |
| `retain_until` | A date, `YYYY-MM-DD`, before which nothing in the project may be suggested for deletion, for example the end of an ethics approval or a data-sharing agreement. |

Set them with one command, which commits and pushes the record:

```bash
murmurent project set brca --data-folder append_only/brca --data-folder immutable/brca_raw
murmurent project set brca --reads-from append_only/shared_cohort --retain-until 2031-06-30
murmurent project set brca --clear data-folders     # back to the default pair
```

The Projects panel on the dashboard marks a project **quiet** or **dormant**
when it has not been used for the lab's quiet or dormant period.

### Whether a project is in use

```bash
murmurent project status brca        # or, inside one of its repositories: murmurent project status
```

This shows the project's repositories, data folders, what it reads, its
keep-until date, when it was last used, and its **activity**:

- **active**: used in the last 12 months;
- **quiet**: not used for 12 months;
- **dormant**: not used for 24 months;
- **unknown**: nothing on this computer shows it being used.

A lab can set its own numbers of months in its policy file,
`policy/millwright.yaml` in the lab records repository
(`project_quiet_months:` and `project_dormant_months:`). The same file holds the
lab's other numbers; a commented example is in `templates/millwright_policy.yaml`.

"Used" means the newest of: a commit in any of the project's repositories on
this computer, a job started with `murmurent run`, and a file changed in its
data folders, as recorded by the lab's data scan where one runs. Reading data
does not count unless it ran through `murmurent run`, because the shared data
drive does not record when a file was read.

Activity is separate from a project's status (`active` or `archived`), which
decides who can reach it. A dormant project keeps its members.

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
scratch    ~/repos/scratch         plain clone
old_proj   ~/repos/old_proj        missing
```

Verdicts:

- **ready**: has the `.murmurent.yaml` marker. Whether `.claude/agents/`
  holds anything makes no difference: every agent works in every folder.
- **partial**: set up by a very old Murmurent, with a `CHARTER.md` but no
  `.murmurent.yaml`. Run `murmurent repo upgrade` (or the Upgrade button).
- **plain clone**: an ordinary git repo with no marker, outside
  Murmurent's configuration. A `.claude/agents/` folder on its own does not
  change this: that is Claude Code's feature, not Murmurent's.
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
every ready repo in your repositories folder instead of a single path. Neither flag
is needed just to pick up prompt edits to agents already linked; that
part is automatic.

## See also

- [`setup.md`](setup.md): per-machine + per-project install steps.
- [`project_intra.md`](project_intra.md): how a project with several members
  is set up.
- [`cli_manual.md`](cli_manual.md): full `murmurent repo …` command
  reference.
- [`reconcile.md`](reconcile.md): the readiness/adoption drift checks
  that watch repos on a schedule.
