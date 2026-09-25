<!-- The user-facing README. In the development repository this file is
     release/README_public.md; release/make_release.sh copies it to README.md
     when it builds the release tree. Edit it there, not here: a change made in
     the release repo is overwritten by the next release. -->

# Murmurent

Shared AI infrastructure for researchers, labs, core facilities and research
centres. Murmurent gives a research group a set of AI assistants, called
agents, that know the group's data, its conventions and its accumulated
findings. Each group works independently, and can pool its agents and data with
other groups when collaboration helps.

There are three ways to use it: on your own, as a way of working with the other
members of your lab, or as shared infrastructure across many labs and core
facilities at an institution.

**Documentation: <https://hallettmiket.github.io/murmurent/>**

> **Stuck on any step?** Once [Claude Code](https://claude.com/claude-code) is
> installed, ask it. Murmurent puts its own documentation and commands inside
> Claude Code, so questions such as "walk me through installing Murmurent",
> "did my install work?" or "how do I issue a member card?" are answered
> directly, and it can run many of these steps for you.

## Contents

1. [Install it](#1-install-it)
2. [Say who you are](#2-say-who-you-are)
3. [Set up a folder to work in](#3-set-up-a-folder-to-work-in)
4. [Keep it up to date](#4-keep-it-up-to-date)
5. [What to do next](#5-what-to-do-next), according to what you are doing
6. [Getting help](#6-getting-help)

## 1. Install it

You need Python 3.12 or newer, but you do not have to install it yourself:
[uv](https://docs.astral.sh/uv/) fetches the right version. If you do not have
`uv`, one line installs it.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install Murmurent.

```bash
uv tool install murmurent
murmurent install
murmurent doctor
```

Those three commands download Murmurent, connect it to Claude Code, and check
that it worked. Run `murmurent doctor` whenever something looks wrong: it
reports each problem it finds together with the command that corrects it.

If your shell cannot find `murmurent` afterwards, close the terminal and open a
new one. `uv` puts the command in `~/.local/bin`.

<details>
<summary>Alternative: install with a single command</summary>

This needs only `git`, and it installs `uv` for you if it is missing.

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

To read the installer before running it, clone this repository first and run
`scripts/bootstrap.sh` from inside it.

</details>

## 2. Say who you are

```bash
murmurent init
```

This records your name, your email, your institutional username, and your
GitHub and Slack accounts. Everything else is built on it, whether or not you
ever join a lab.

It also asks which of three roles you hold, so decide before you start.

| Role | Who it is |
|---|---|
| **member** | You use Murmurent for your own work, perhaps as part of a lab |
| **PI** | You lead a lab or a core facility, and issue identities to its members |
| **mayor** | You run a centre, meaning several labs and core facilities together |

`murmurent whoami` shows what was recorded.

## 3. Set up a folder to work in

The agents are available in every folder on your machine as soon as you
install, so setting up a particular folder is not what gives you them. It does
something different: it turns on Murmurent's check on sensitive data, which
removes personal identifiers from anything leaving your machine, such as a web
search or a fetched page. **That check does not run in folders you have not set
up.** Setting up a folder also allows it to join a Murmurent project later.

Do this for any folder holding research data, and for every folder holding
sensitive data.

Murmurent works in folders that git tracks and that live under `~/repos/`. Ask
what state your folder is in.

```bash
murmurent repo status ~/repos/<folder>
```

Then run the command beside the answer you get.

| Answer | What it means | What to run |
|---|---|---|
| `✗ no such folder` | the path is wrong | check the path |
| `✗ not tracked by git` | the folder exists, but git is not tracking it | `git -C ~/repos/<folder> init`, then read the next row |
| `• not set up yet` | git tracks it, and Murmurent has never set it up | `murmurent repo adopt ~/repos/<folder>` |
| `± half set up` | an earlier attempt stopped partway | the same `adopt` command, which completes it |
| `✓ ready`, older version | set up by an earlier version of Murmurent | `murmurent repo upgrade ~/repos/<folder>` |
| `✓ ready`, current | nothing to do | open Claude Code in it |

Neither command needs options, and neither alters anything already in the
folder. Your files, your history and any Claude Code settings of your own are
left as they are. What is added is a `.murmurent.yaml` file recording the
setup, a `CLAUDE.md` template, and VS Code settings. Commit the first two, and
everyone else working in that folder has the same setup.

To mark a folder as holding sensitive data, add one line to `.murmurent.yaml`.

```yaml
sensitivity: clinical
```

`murmurent repo list` shows the state of every folder on your machine at once.

Setting up a folder is separate from creating a Murmurent **project**, which is
a different thing and does not happen automatically. See
[Making a repo Murmurent-ready](https://hallettmiket.github.io/murmurent/ready_vs_projects/).

## 4. Keep it up to date

```bash
uv tool upgrade murmurent
murmurent install
```

Run `murmurent install` with no options. It completes the update everywhere it
is needed, including in the folders you have already set up, and it is safe to
run when nothing has changed.

Changes to the wording of an agent or a rule take effect with no command at
all. A newly added agent arrives with the `murmurent install` above. There is
never anything to run folder by folder.

If you installed from a clone rather than from PyPI, replace the first command
with `git pull` inside that clone, followed by
`uv tool install --python 3.12 --reinstall -e .`. Use `uv` rather than `pip`
here. The `pip` on your path often belongs to a different Python installation,
such as a conda environment, and then the upgrade either lands in the wrong
place or stops with an error about the Python version.

## 5. What to do next

Find the row that describes you.

| What you are doing | Where to go |
|---|---|
| Working on your own, and want to see what Murmurent is for | [Five worked examples](https://hallettmiket.github.io/murmurent/getting_started/) |
| Joining a lab whose head already uses Murmurent | [Membership IDs and the trust chain](https://hallettmiket.github.io/murmurent/identity/) for the identity card your lab head signs for you, then [The lab records repository](https://hallettmiket.github.io/murmurent/lab_mgmt/) for the copy of the lab's records you also need |
| Running a lab or core facility, and adding members to it | [Membership IDs and the trust chain](https://hallettmiket.github.io/murmurent/identity/) for issuing identities, then [Group Slack setup](https://hallettmiket.github.io/murmurent/group_slack_setup/) so that identities can be sent by direct message |
| Joining your lab to a centre that already exists | [Membership IDs and the trust chain](https://hallettmiket.github.io/murmurent/identity/), under "Registering your lab or core with an existing centre". You find your centre in the public directory, then send its mayor an encrypted request. |
| Starting a centre at your institution | [What a centre is](https://hallettmiket.github.io/murmurent/centre_overview/), which includes the full setup procedure |
| Reading about the agents themselves | [The reference agents](https://hallettmiket.github.io/murmurent/agents/) |
| Looking for one particular command | [The command manual](https://hallettmiket.github.io/murmurent/cli_manual/) |

## 6. Getting help

Ask Claude Code first. It has Murmurent's documentation and commands available,
and can usually diagnose and repair an installation problem directly.

Failing that, [TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers the common
installation problems. Bug reports and requests for new features go to
[the development repository](https://github.com/hallettmiket/murmurent_dev/issues),
where the work happens. Issues are turned off here deliberately, so that the
discussion stays in one place.

## The three repositories

| | |
|---|---|
| [**`murmurent`**](https://github.com/hallettmiket/murmurent) | This one. Released versions, one entry per release. It is what you install. |
| [**`murmurent_dev`**](https://github.com/hallettmiket/murmurent_dev) | Where Murmurent is written: issues, proposals, and the full history of every change. Its README is written for people working on Murmurent rather than using it. |
| [**`murmurent_public`**](https://github.com/hallettmiket/murmurent_public) | The public directory: which institutions run Murmurent and how to request to join one, plus an index of shared workflows, called choreographies, that anyone can install. |

## Authors

Mike Hallett &mdash; michael.hallett@uwo.ca

Licensed under Apache-2.0. See [LICENSE](LICENSE).
