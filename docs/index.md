# Murmurent

Murmurent is an agentic AI operating system that provides:

- **Reference agents**: a set of specialized agents (literature search,
  computation, adversarial review, security audit, …) you
  delegate to by name.
- **An Obsidian-based vault**: your private, git-backed knowledge base that
  survives across sessions and projects. It holds your **Oracle** (personal
  and lab-shared structured memory), your daily lab notebook, and your own
  notes and maps.
- **Hard rules + hooks**: data-governance guardrails enforced in software:
  raw data is immutable, refined data is append-only, secrets never reach a
  commit.
- **Cryptographic membership**: labs, cores, and projects are held together
  by signed identity certificates (centre root → PI → lead → member).
- **The commons**: independent groups sharing a common set of agents,
  rules, and infrastructure, so institutional knowledge accumulates across
  projects and personnel instead of being trapped on one machine.

Murmurent is built on [Claude Code](https://claude.com/claude-code) today,
although nothing in its design is tied to it: the same tiers, agents, and
governance rules could run on another agentic AI system.

## Where to start

| You are… | Start here |
|---|---|
| New: what does this add over plain Claude Code? | [Getting started](getting_started.md) |
| Installing on your machine | [Install & setup](setup.md) |
| Starting a project (in your lab, or across labs) | [Creating a project](project_intra.md) |
| A PI setting up your lab | [Group Slack setup](group_slack_setup.md) · [The lab-mgmt repo](lab_mgmt.md) |
| A mayor bootstrapping a centre | [Centre Slack setup](slack_setup.md) · [Public directory setup](hub_setup.md) |
| Wondering how the trust model works | [Membership IDs & the trust chain](identity.md) |
| Looking for a command | [CLI manual](cli_manual.md) |

## How a centre is organized

Murmurent models a research centre as four kinds of participant:

- **Individual members**: each person has their own membership identity,
  their own agents, and their own personal vault.
- **Groups**: a group is either a **lab** (a research group) or a **core**
  (a shared facility such as a proteomics or imaging centre). Every group is
  led by a **PI** and owns its own members, data, and workflows.
- **Projects**: a project is a unit of work that brings individual members
  together around shared repositories and data. Its members can come from a
  single group or from several groups at once.
- **The administration**: the centre-level layer that maintains the
  registry of groups and projects and issues the identity certificates that
  bind members, groups, and projects together.

Each group documents and runs its own workflows on top of the shared agents
and rules, keeping authority over its own people and data, while the
administration maintains the shared registry and trust chain.

## Repositories

| Repo | Purpose |
|---|---|
| [`hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent) | the commons codebase: agents, rules, hooks, MCP servers, CLI, dashboard |
| `<your-org>/murmurent_lab_mgmt_<lab>` | your lab's governance repo: roster, project registry, and the **lab oracle** |
| `<you>/murmurent_vault` | your private personal vault repo: your **personal oracle**, lab notebook, and maps-legends |
| [`hallettmiket/murmurent_public`](https://github.com/hallettmiket/murmurent_public) | the global public directory: the institution registry + join intake |
| `hallettmiket/murmurent_manuscript` (private) | the paper describing Murmurent's design |
