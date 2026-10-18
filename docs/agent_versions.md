# Choosing an agent's version

Murmurent ships one definition of each agent, the **centre version**. A lab, a
project, or a person can use a different one, and a person can switch an agent
off in one project. This page explains how Claude Code ends up using one
version and how to change which.

## The five levels

When two levels have a version of the same agent, the more specific one wins:

| Level | Who sets it | Where it is kept | Who it applies to |
|---|---|---|---|
| **Your version for one project** | you | your vault: `projects/<project>/agents/` | you, in that project |
| **Project version** | the project lead | the repo: `.murmurent/agents/`, committed | everyone in the project |
| **Your version** | you | your vault: `agent_forks/` or `agents/` | you, in all your projects |
| **Lab version** | the PI | the lab management repo: `agents/` | everyone in the lab |
| **Centre version** | murmurent | murmurent's `agents/` | everyone |

A student's own version beats the lab's. The security and audit agents
(Security Guard, Adversary, Conscience) and any centre agent marked frozen
always use the centre version, and the guardians cannot be switched off.

Everything kept in your vault follows you to your other machines.

## On the dashboard

Each agent card says "in use:" and the level. Its **versions** button opens a
window where you pick a project and see which version you use there, then
make your own version for that project, switch the agent off or on there, or,
as PI, make the version you use the lab's. The sections below give the
terminal commands for the same things.

## Which version am I using?

In a terminal:

```bash
murmurent agent which                    # outside any repo
murmurent agent which --repo ~/repos/x   # in a session started in repo x
```

## Making your own version

```bash
murmurent agent fork blacksmith                     # for all your projects
murmurent agent fork blacksmith --project dcis      # for the dcis project only
```

Both copy the version you use now into your vault for you to edit. Run
`murmurent vault sync` afterwards so your other machines have it.

## Sharing a version

```bash
murmurent agent share blacksmith --lab                  # PI: the lab's version
murmurent agent share blacksmith --repo ~/repos/dcis    # the project's version
```

`--lab` commits and pushes it to the lab management repo. `--repo` copies it
into the repo's `.murmurent/agents/`; commit and push it so the team gets it.

## Switching an agent off in one project

```bash
murmurent agent off artist --project dcis    # off for you in dcis
murmurent agent on artist --project dcis     # back on
```

To switch an agent off for everyone in a project, list it under `agents_off:`
in the repo's `.murmurent.yaml` and commit it. Murmurent turns a switch-off
into Claude Code's rule `Agent(<name>)` in the repo's
`.claude/settings.local.json`, which stays on your machine. Rules you added
there yourself are kept.

## When changes apply

Murmurent installs the winning versions when the dashboard's **▶ Claude Code**
button opens a session in a repo, when you run `murmurent agent relink` (after
a vault pull), and when you run:

```bash
murmurent agent sync            # the repo in the current folder
murmurent agent sync --all      # every project repo on this machine
```

Claude Code reads agents when a session starts, so open a new session after a
change. Links murmurent puts in a repo's `.claude/agents/` are listed in its
`.gitignore` and never committed. A file you or your project committed there is
never replaced.
