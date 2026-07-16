# The lab_mgmt repository (`murmurent_lab_mgmt_<lab>`)

The single most-confusing piece of Murmurent's filesystem layout is what
`lab_mgmt` is, who needs it, and how it differs from
`~/.murmurent/lab_info/`. This document is the short answer.

## TL;DR

`lab_mgmt` is the **per-group governance repo** — one per PI. It is
NOT a Murmurent commons artifact; it belongs to the lab. It holds the
canonical roster, project registry, inventory, training records,
audit log, and other day-to-day filing-cabinet contents for ONE
research group.

Different labs each have their own lab_mgmt repo under their own
GitHub account/org. **The canonical name is `murmurent_lab_mgmt_<lab>`**
(see "Naming — read this before creating the repo" below): the Hallett
lab's lives at `hallettmiket/murmurent_lab_mgmt_mh`; a bioinformatics
core's would be `<owner>/murmurent_lab_mgmt_bioinformatics`.

The centre-wide registry (labs, cores, common SEAs, join requests)
lives in a separate, distinct tree at `~/.murmurent/lab_info/`. That
one is owned by the registrar, not by any single lab.

## Naming — read this before creating the repo

**The repo is named `murmurent_lab_mgmt_<lab>`, where `<lab>` is your
group's registry slug** (e.g. `mh`, `bioinformatics`). Both the GitHub
repo and the local clone directory use this exact name:

```
GitHub:      <your-account-or-org>/murmurent_lab_mgmt_<lab>   (private)
local clone: ~/repos/murmurent_lab_mgmt_<lab>
```

You normally never create it by hand — **`murmurent pi-init <lab>`
scaffolds it at exactly this path** (`core.repo.lab_repo_path`), and
pins the machine's lab_mgmt pointer to it. If you do create the GitHub
repo manually (e.g. to push an existing local scaffold), use the same
name:

```bash
gh repo create <you>/murmurent_lab_mgmt_<lab> --private \
  --source ~/repos/murmurent_lab_mgmt_<lab> --remote origin --push
```

Why this shape and not a bare `lab_mgmt`? Field experience: two groups
independently created repos called `lab_mgmt` and they were
indistinguishable in clones, invitations, and conversation. The
`murmurent_` prefix announces what kind of repo it is; the `_<lab>`
suffix says whose. Machines that host several labs' clones (a
registrar's laptop, a shared server) get collision-free directories
for free.

Deviant names still *work* — member-side resolution auto-discovers any
clone under `~/repos` that has the lab_mgmt shape (`lab.md` +
`members/`) and pins it — but stick to the canonical name; discovery
refuses to guess when two candidate clones both match.

The clean conceptual boundary is:

```
~/repos/murmurent/                  ← Commons: agents, rules, skills, CLI
                                      source. Shared across the centre.
                                      Symlinked into ~/.claude/.
~/repos/murmurent_lab_mgmt_<lab>/   ← One lab's filing cabinet. PI-owned.
                                      Members read; PI + delegates write.
~/.murmurent/lab_info/              ← Centre registry. Registrar-owned.
                                      Lists every lab + core + common SEA.
```

## What lives in `lab_mgmt`?

Canonical location is `~/repos/murmurent_lab_mgmt_<lab>/`. The directory layout:

```
murmurent_lab_mgmt_<lab>/
├── lab.md                    PI handle, lab name, institution,
│                             Slack workspace, GitHub org, lab-VM
│                             base path. Single source of truth
│                             for the lab's configuration.
├── compliance.md             Group-level required training
│                             (TCPS_2, WHMIS, etc.) — applied to
│                             every member.
├── members/                  One .md per member (active or inactive).
│   ├── the_pi.md            Each carries handle, role, status,
│   ├── gary.md               certifications, lab affiliation.
│   └── ...
├── inventory/                Reagents + equipment. Managed by the
│                             inventory MCP. Lab-manager writes only.
├── oracle/                   Curated group findings (promoted from
│                             personal-vault drafts via the publish
│                             flow). Read by every member; written by
│                             the oracle MCP after PI review.
├── cert_projects/            THE authoritative project registry — one
│                             .md per project (name, lab, lead,
│                             sensitivity, certified members, repos,
│                             Slack channel). This is what the
│                             dashboard's Projects panel reads; it no
│                             longer scans ~/repos for CHARTER.md files.
├── projects/                 Legacy CHARTER-mirror registry that
│                             cert_projects/ replaced (2026-07-15
│                             split). Old entries may still be present
│                             for history; new projects are recorded
│                             in cert_projects/ only.
├── roles/                    Role assignments (lab_manager,
│                             oracle_curator, sysadmin, …) with
│                             audit history.
├── keys/                     Public age keys per member, for
│                             encrypted artifacts.
├── audit/                    Compliance + decommission records;
│                             never deleted, only appended.
├── onboarding/               Reusable member profiles (student,
│                             postdoc, pi-collab) the cable_guy
│                             clones into a new member.md.
├── dashboards/               Auto-generated per-member dashboard
│                             snapshots (markdown).
├── external_customers/       Industry / academic-external clients
│                             that core facilities bill.
└── requests/                 SEA request board (project↔project).
```

## Who needs it?

| Person | Action | Where they get it |
|---|---|---|
| Lab PI | scaffolded by `murmurent pi-init <lab>` at `~/repos/murmurent_lab_mgmt_<lab>`; push it to GitHub under the same name | see "Naming" above |
| Lab member (postdoc, student) | clone, read-only | `git clone git@github.com:<owner>/murmurent_lab_mgmt_<lab>.git ~/repos/murmurent_lab_mgmt_<lab>` (auto-discovered + pinned on first dashboard load) |
| Core leader | clone OF THEIR CORE'S `lab_mgmt` (cores have their own) | same |
| Registrar | reads multiple `lab_mgmt` repos via the centre registry | each lab's path is recorded in `~/.murmurent/lab_info/_registry.yaml` |
| Mayor (bootstrap) | no | uses `~/.murmurent/lab_info/` instead |
| External customer | no | only sees the dashboard surfaces, not the underlying repo |

If you're a new lab member, the cable_guy agent's `PROVISION_MEMBER`
flow will tell you to clone it during onboarding. If you're a brand-
new PI joining a centre, the registrar will tell you to create one,
populate `lab.md`, and push it to your lab's GitHub org during the
join-request approval flow.

## How `lab_mgmt` is resolved at runtime

`core.repo.lab_mgmt_repo_root()` returns the active lab's repo path
using this order:

1. **Thread-local override** — the dashboard sets this per-request
   so the registrar can switch between viewing different labs.
2. **`$MURMURENT_LAB_MGMT_REPO` env var** — for tests + scripted use.
3. **This machine's pinned pointer** (`~/.murmurent/lab_mgmt_path`) —
   written by `murmurent pi-init <lab>`, and by discovery (step 5).
4. **`~/repos/lab_mgmt`, then `~/repos/hallett-lab-mgmt`** — if either
   exists. Pre-convention names, kept working for clones made before
   `murmurent_lab_mgmt_<lab>` was settled; not what you should create.
5. **Discovery** — scans `~/repos` for a directory with the lab_mgmt
   shape (`lab.md` + `members/`), preferring one whose roster contains
   your handle, and **pins** an unambiguous hit so this runs once. This
   is what finds `~/repos/murmurent_lab_mgmt_<lab>` on a member machine
   (they never run `pi-init`, so nothing pinned it). Two matching clones
   → it refuses to guess and the panels stay empty; set
   `MURMURENT_LAB_MGMT_REPO` to break the tie.
6. **`~/repos/lab_mgmt`** — last-resort default if nothing above hit.

So the canonical clone path needs no configuration: `pi-init` pins it
for the PI, discovery pins it for members. The `MURMURENT_LAB_MGMT_REPO`
env var is the knob for tests and unusual deployments (e.g. a multi-lab
dev workstation where discovery is ambiguous by design).

## Backfilling access for pre-existing members

Members added **before** the automatic lab_mgmt grant existed (or via
any path that skipped it) can be granted access a posteriori — the
grant pass works from the whole roster, not just new additions:

```bash
murmurent group-reconcile <group> --apply
```

For every active roster member with a `github:` login this ensures
**read-only** collaborator access on the lab_mgmt repo (idempotent;
already-granted members and the repo owner are no-ops). Members whose
profile lacks a GitHub login are listed so the PI can collect them.
Prerequisite: the lab_mgmt repo must be on GitHub (`git remote -v`
shows an origin) — the reconcile output says so if it isn't.

Each member then completes their side once: accept the GitHub
invitation e-mail, and clone the repo under its own name
(`git clone git@github.com:<owner>/murmurent_lab_mgmt_<lab>.git
~/repos/murmurent_lab_mgmt_<lab>`). Resolution auto-discovers the
clone and pins it on the next dashboard load; `MURMURENT_LAB_MGMT_REPO`
remains the explicit override. From then on their Lab Members panel
and daily reconcile track what the PI pushes.

## Reading + writing — who's allowed?

| Path under `lab_mgmt/` | Read | Write |
|---|---|---|
| `lab.md` | everyone | PI |
| `members/*.md` | everyone | PI (or `cable_guy` via PI delegation) |
| `inventory/*.md` | everyone | `lab_manager` role via the inventory MCP |
| `oracle/*.md` | everyone | `oracle_curator` role via the oracle publish flow |
| `cert_projects/*.md` | everyone | project lead + PI (written by the dashboard's New Project flow / `core.cert_projects`) |
| `projects/*.md` (legacy) | everyone | project lead + PI |
| `roles/*.md`, `audit/*.md` | everyone | PI |
| `compliance.md` | everyone | PI |

In practice the granular write permissions are enforced by the
**MCP layer**, not by git. Members CAN locally edit `inventory/*.md`,
but the inventory MCP refuses to commit-publish their changes unless
they hold the `lab_manager` role. The PI's review on incoming PRs is
the final gate.

## `lab_mgmt` vs `~/.murmurent/lab_info/` — the comparison

| Aspect | `~/repos/lab_mgmt` | `~/.murmurent/lab_info/` |
|---|---|---|
| **Scope** | one lab | the whole centre |
| **Owner** | the PI | the registrar |
| **Members** | one PI + lab members | one or more registrars (mayors become first registrar) |
| **GitHub home** | the lab's own org | a private centre org (or none — can stay local + git-push to a private remote) |
| **First clone** | each lab member runs `git clone` once during onboarding | the mayor's machine creates it on `murmurent centre-init` |
| **Cross-lab visibility** | no — one lab's repo, period | yes — the registry lists every lab and core in the centre |
| **What writes here** | `cable_guy` (per-member onboarding), inventory MCP, oracle MCP, PI's hand-edits | `centre_cable_guy` (lab/core onboarding), `registrar.create_lab` / `create_core`, join-request approvals, common-SEA submissions |

If you find yourself wondering "where does X go?" — ask "is X about
one lab specifically, or about how labs relate to each other?" One-
lab specifics belong in `lab_mgmt`. Inter-lab relations belong in
`lab_info`.

## See also

- [`docs/setup.md`](setup.md) — first-time Murmurent install on a new
  machine, including the `~/repos/murmurent_lab_mgmt_<lab>` clone.
- [`docs/group_level.md`](group_level.md) — the broader design
  document for group-scope Murmurent operations.
- [`docs/cores_plan.md`](https://github.com/hallettmiket/murmurent/blob/main/docs/cores_plan.md) §4 — how a core's own
  `lab_mgmt` (yes, cores have one too, parallel to labs) mounts
  inside `~/.murmurent/lab_info/cores/<core>/lab-mgmt/`.
- [`agents/cable_guy.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/cable_guy.md) — the per-lab
  cable_guy that owns most of the read/write surface on this repo.
