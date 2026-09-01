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
