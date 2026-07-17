# Murmurent

Murmurent turns a forgetful generalist into a research team with a memory
and house rules:

- **Reference agents**: a bench of specialists (literature scout,
  computational workhorse, adversarial reviewer, security auditor, …) you
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
| Starting a project (in your lab, or across labs) | [Creating a project](project_creation.md) |
| A PI setting up your lab | [Group Slack setup](group_slack_setup.md) · [The lab-mgmt repo](lab_mgmt.md) |
| A mayor bootstrapping a centre | [Centre Slack setup](slack_setup.md) · [Hub setup](hub_setup.md) |
| Wondering how the trust model works | [Membership IDs & the trust chain](identity.md) |
| Looking for a command | [CLI manual](cli_manual.md) |

## The five social units

Murmurent models a bioconvergence centre as **individuals**, **groups**
(PI + trainees), **collaborations** (groups working together),
**cores** (shared facilities), and the **administration**. Each group runs
its own documented pattern using shared agents and rules (*choreography,
not orchestration*): no central controller decides every move, which limits
the blast radius of any failure and preserves each group's autonomy.

## Repositories

| Repo | Purpose |
|---|---|
| [`hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent) | the commons codebase: agents, rules, hooks, MCP servers, CLI, dashboard |
| `<your-org>/murmurent_lab_mgmt_<lab>` | your lab's governance repo: roster, project registry, and the **lab oracle** |
| `<you>/murmurent_vault` | your private personal vault repo: your **personal oracle**, lab notebook, and maps-legends |
| [`hallettmiket/murmurent_public`](https://github.com/hallettmiket/murmurent_public) | the global onboarding hub: institution directory + join intake |
| `hallettmiket/murmurent_manuscript` (private) | the paper describing Murmurent's design |
