# What a centre is

A **centre** is a collection of labs and cores, together with the projects
that run across them and the administration that governs them. In an
academic setting a centre corresponds to a research centre, a department,
or another federation of labs and units with shared scientific goals. An
institution can run more than one centre. Each centre is independent and
drives its deployment from its own `unique_name`.

The purpose of the centre layer is to let independent groups share a common
set of agents, rules, and infrastructure (the commons) while each group
keeps authority over its own members and data. The centre provides the
parts that must be shared: a registry of who exists, and a chain of
identity certificates that lets any member verify any other member's
affiliation.

## Roles at the centre level

- **The administration.** The governance layer of a centre. It maintains
  the centre registry and the trust chain, and it decides which groups may
  join.
- **Mayor.** The person who bootstraps and runs a centre. The Mayor
  initializes the centre (`murmurent centre-init`), holds the **centre root
  key** (the root of the identity trust chain), sets up the centre's Slack
  workspace, approves or declines group join requests, and publishes the
  centre's entry in the public directory.
- **Registrar.** The agent that maintains the centre registry: the
  authoritative record of every lab, core, and collaboration at the
  institution, held in `_registry.yaml` plus a per-entity directory for
  each. It creates, archives, and updates lab and core entries, enforces
  registry invariants such as one PI leading at most one active lab or
  core, reviews incoming join requests, and keeps the roster current. It
  also renders a read-only, institution-level dashboard covering
  membership, cross-group certification status, and pointer integrity,
  and it acts as the centre's certificate authority, issuing PI identity
  cards signed with the centre root key and publishing the revocation
  list. A lab's own projects, notebooks, SEAs, and personal Oracles stay
  outside the registrar's view; from its vantage point, labs are opaque
  units.

  The registrar is, at least initially, an agent controlled by the
  Mayor: the person who bootstraps a centre becomes its first registrar,
  operating the registrar agent from their own machine until the role is
  formally handed to a separate administrator.

For how members, groups, and projects relate to the centre, see
[Overview: members, groups, projects](overview.md).

## What this section covers

- [Membership IDs & the trust chain](identity.md): how identity
  certificates chain from the centre root to PIs to members.
- [The centre root key](centre_root_key.md): the certificate-authority
  root, and how it is generated, backed up, and rotated.
- [The public directory](hub_setup.md): the global registry where each
  centre lists itself so prospective members can find and join it.
- [Drift detection (reconcile)](reconcile.md) and the
  [security dashboard](security-dashboard.md): keeping the centre's
  registry, permissions, and shared state consistent.

## Starting a new centre

This moved here from the README, which is now limited to what every user
needs. It is for a mayor setting up a centre for the first time.

You need [Claude Code](https://claude.com/claude-code), installed and logged
in once; the [GitHub CLI `gh`](https://cli.github.com/), authenticated with
`gh auth login`, for the centre's repositories; and
[uv](https://docs.astral.sh/uv/), which the installer adds if it is missing.

One command creates the centre and makes you its founding registrar:

```bash
murmurent centre-init
```

Only `--name` and `--institution` are required. Everything else can be
supplied later, from the dashboard or with `murmurent centre-set`. A complete
example:

```bash
murmurent centre-init \
  --name "Example Bioconvergence Centre" \
  --institution "Example University" \
  --mayor @the_mayor \
  --unique-name example \
  --join-email murmurent-join@example.edu \
  --slack-workspace T0EXAMPLE \
  --github-org centre-example \
  --public-hub github.com/hallettmiket/murmurent_public#example \
  --server-host lab-server.example.edu \
  --server-account murmurent \
  --cc-install-path /opt/claude \
  --mayor-root /mayor/example \
  --obsidian-vault /mayor/obsidian \
  --raw-root /data/example/raw \
  --refined-root /data/example/refined
murmurent centre-status      # confirms you are the founding registrar
```

| Flag | What it is | Example |
|---|---|---|
| `--name` *(required)* | Display name of the centre | `"Example Bioconvergence Centre"` |
| `--institution` *(required)* | Hosting institution | `"Example University"` |
| `--mayor` | Your `@handle`. Defaults to `$MURMURENT_USER`, then the operating system user | `@the_mayor` |
| `--unique-name` | Short identifier, not tied to an institution name. Used to name repositories, Slack channels and groups | `example` |
| `--join-email` | Public address that PIs send join requests to. Listed in the public directory | `murmurent-join@example.edu` |
| `--slack-workspace` | Your Slack workspace identifier, the one beginning with `T` | `T0EXAMPLE` |
| `--github-org` | The centre's GitHub organisation or dedicated account | `centre-example` |
| `--public-hub` | The public directory, plus this centre's label in it | `github.com/hallettmiket/murmurent_public#example` |
| `--server-host` | The always-online server, reachable over SSH | `lab-server.example.edu` |
| `--server-account` | SSH login account on that server | `murmurent` |
| `--cc-install-path` | Where Claude Code is installed on that server | `/opt/claude` |
| `--mayor-root` | Top-level mayor directory, which can be mirrored to GitHub | `/mayor/example` |
| `--obsidian-vault` | Centre-level Obsidian vault | `/mayor/obsidian` |
| `--raw-root` | Root of the centre's raw data on the data server | `/data/example/raw` |
| `--refined-root` | Root of the centre's refined data | `/data/example/refined` |

`--data-server` is an older name for `--server-host` and still works. Add
`--no-prompt` for scripted runs on a server, and `--no-sentinel` when running
under `sudo` or in continuous integration.

### Making the centre joinable

A prospective member cannot be assumed to belong to the centre's Slack
workspace already, so four further steps make the centre reachable from
outside.

1. **The encryption key for join requests.** `centre-init` generates an `age`
   keypair automatically, which PIs encrypt their join requests to. Recreate
   it with `murmurent centre-age-keygen`.
2. **The root signing key**, which is the centre's certificate authority. Run
   `murmurent centre-root-keygen`. It signs PI identity cards and the list of
   revoked ones. Back it up offline; see
   [The centre root key](centre_root_key.md).
3. **List the centre publicly.** `murmurent centre-hub-publish` writes your
   entry in the public directory and publishes your signing key and revocation
   list, so members elsewhere can verify identity cards. It prints a `git push`
   command for you to run.
4. **Set up Slack.** Create a `murmurent-<unique-name>` workspace and a bot
   token, then test it with `murmurent centre-slack-smoke`. See
   [Centre Slack setup](slack_setup.md).


## The centre vault (work in progress)

!!! warning "Work in progress"
    The centre vault is a planned capability, not yet implemented.

Just as an individual member keeps a personal vault of findings, and a
lab keeps a shared vault of institutional memory (see
[How Murmurent remembers](memory.md)), the centre could maintain a
vault of its own: institutional memory that spans labs, PIs, and time.
Such a vault would hold information whose value crosses the whole
centre. Examples include a dataset of broad interest derived from a
local hospital, or administrative records worth preserving independent
of who currently holds the registrar role. This extends the
tiered-memory model described in [How Murmurent remembers](memory.md)
up one level, from the member and the lab to the centre. Institutional
memory at centre scope is an important concept, and Murmurent's
architecture offers a path toward implementing it, though the centre
vault itself remains a work in progress.
