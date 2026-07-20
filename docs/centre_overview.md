# What a centre is

A **centre** is one institution's own Murmurent installation: the set of
labs and cores at that institution, the projects that run across them, and
the administration that governs them. A university department, a research
institute, or a bioconvergence centre each runs its own centre. Centres are
independent of one another; a centre drives every deployment from its own
`unique_name`, with no shared server between institutions.

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
- **Registrar.** The person (or agent) that maintains the centre registry:
  the record of every lab, core, and project at the institution. The
  registrar reviews incoming join requests and keeps the roster current.

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
