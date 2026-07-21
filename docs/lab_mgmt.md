# The lab_mgmt repository (`murmurent_lab_mgmt_<lab>`)

The single most-confusing piece of Murmurent's filesystem layout is what
`lab_mgmt` is, who needs it, and how it differs from
`~/.murmurent/lab_info/`. This document is the short answer.

## TL;DR

`lab_mgmt` is the **per-group governance repo**, one per PI. It is owned
by the lab and is not a Murmurent commons artifact. It holds the
canonical roster, project registry, inventory, training records,
audit log, and other governance records for a single research group.

Different labs each have their own lab_mgmt repo under their own
GitHub account/org. **The canonical name is `murmurent_lab_mgmt_<lab>`**
(see "Naming: read this before creating the repo" below): a given
lab's lives at `<owner>/murmurent_lab_mgmt_<lab>`; a bioinformatics
core's would be `<owner>/murmurent_lab_mgmt_bioinformatics`.

The centre-wide registry (labs, cores, common SEAs, join requests)
lives in a separate, distinct tree at `~/.murmurent/lab_info/`. That
tree is owned by the registrar; it is not the property of any single lab.

## Naming: read this before creating the repo

**The repo is named `murmurent_lab_mgmt_<lab>`, where `<lab>` is your
group's registry slug** (e.g. `mh`, `bioinformatics`). Both the GitHub
repo and the local clone directory use this exact name:

```
GitHub:      <your-account-or-org>/murmurent_lab_mgmt_<lab>   (private)
local clone: ~/repos/murmurent_lab_mgmt_<lab>
```

You normally never create it by hand: **`murmurent pi-init <lab>`
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

Deviant names still work (member-side resolution auto-discovers any
clone under `~/repos` that has the lab_mgmt shape (`lab.md` +
`members/`) and pins it), but stick to the canonical name; discovery
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

1. **Thread-local override**: the dashboard sets this per-request so a
   shared, multi-lab dashboard scopes each request to the acting viewer's
   own lab (via `use_lab_mgmt_root(resolve_viewer_lab_mgmt(actor))`).
2. **`$MURMURENT_LAB_MGMT_REPO` env var**: an explicit operator pin to
   one lab (single-lab installs, tests, scripted use). When set, it wins
   over the registry net below — and the dashboard's per-viewer scoping
   stands down, since a machine pinned to one lab is not multi-lab.
3. **This machine's pinned pointer** (`~/.murmurent/lab_mgmt_path`):
   written by `murmurent pi-init <lab>`, and by discovery (step 5).
4. **Registry-authoritative** (`_registry_lab_mgmt_for_owner`): the
   machine owner's own group per the centre registry (`_registry.yaml`).
   A bare call acts for the owner, so their registered group is the
   canonical default — returned **even if the clone isn't on disk yet**
   (the honest answer; panels render empty until it's cloned). This is
   what replaced the old hardcoded `~/repos/lab_mgmt` fallback.
5. **Discovery**: scans `~/repos` for a directory with the lab_mgmt
   shape (`lab.md` + `members/`), preferring one whose roster contains
   your handle, and **pins** an unambiguous hit so this runs once. It
   matches on shape, not name, so a pre-convention `~/repos/lab_mgmt`
   clone is still found here — the name was dropped as a *fallback*, the
   folder still resolves. If two clones match, it refuses to guess and
   the panels stay empty; set `MURMURENT_LAB_MGMT_REPO` to break the tie.
6. **Canonical-convention default** (`~/repos/murmurent_lab_mgmt`, no
   group suffix): the honest last resort when nothing above resolves. It
   never exists on disk, so every lookup misses cleanly and any resulting
   404 names the canonical convention. Murmurent no longer falls back to
   `~/repos/lab_mgmt` by name (that pre-convention path used to outrank
   discovery and was returned even when absent — the root of the
   wrong-roster 404s in issues #31 / #33).

So the canonical clone path needs no configuration: `pi-init` pins it
for the PI; for members the registry net (step 4) resolves it the moment
the PI has pushed their roster record, and discovery (step 5) self-heals
the pre-registry case. The `MURMURENT_LAB_MGMT_REPO` env var remains the
knob for tests and unusual deployments (e.g. a multi-lab dev workstation
where discovery is ambiguous by design).

## Backfilling access for pre-existing members

Members added **before** the automatic lab_mgmt grant existed (or via
any path that skipped it) can be granted access a posteriori. The
grant pass works from the whole roster, not just new additions:

```bash
murmurent group-reconcile <group> --apply
```

For every active roster member with a `github:` login this ensures
**read-only** collaborator access on the lab_mgmt repo (idempotent;
already-granted members and the repo owner are no-ops). Members whose
profile lacks a GitHub login are listed so the PI can collect them.
Prerequisite: the lab_mgmt repo must be on GitHub (`git remote -v`
shows an origin). The reconcile output says so if it isn't.

Each member then completes their side once: accept the GitHub
invitation e-mail, and clone the repo under its own name
(`git clone git@github.com:<owner>/murmurent_lab_mgmt_<lab>.git
~/repos/murmurent_lab_mgmt_<lab>`). Resolution auto-discovers the
clone and pins it on the next dashboard load; `MURMURENT_LAB_MGMT_REPO`
remains the explicit override. From then on their Lab Members panel
and daily reconcile track what the PI pushes.

## Reading + writing: who's allowed?

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

### Member profile edits are staged, not committed (#34)

Members hold the roster clone **read-only** by design: the PI/leader is
the only writer, so a member's `git pull --ff-only` on the roster can
never conflict. That is why a member editing their own profile in the
dashboard does **not** write to `members/<handle>.md` — committing to a
read-only clone leaves an unpushable local commit that diverges it and
breaks the next pull.

Instead, a non-writer's profile edit is **staged** to their own
`~/.murmurent/profile.yaml` under a `roster_profile:` block (shaped like
the roster frontmatter), and their own dashboard overlays it so the edit
shows immediately. The PI applies staged edits to the roster on the next
sync. Only the writer (PI/leader) edits `members/<handle>.md` directly,
with a real commit + push. (The reconcile step that ingests staged member
profiles into the roster is the durable follow-up to this staging store.)

## `lab_mgmt` vs `~/.murmurent/lab_info/`: the comparison

| Aspect | `~/repos/lab_mgmt` | `~/.murmurent/lab_info/` |
|---|---|---|
| **Scope** | one lab | the whole centre |
| **Owner** | the PI | the registrar |
| **Members** | one PI + lab members | one or more registrars (mayors become first registrar) |
| **GitHub home** | the lab's own org | a private centre org (or none, can stay local + git-push to a private remote) |
| **First clone** | each lab member runs `git clone` once during onboarding | the mayor's machine creates it on `murmurent centre-init` |
| **Cross-lab visibility** | no: one lab's repo, period | yes: the registry lists every lab and core in the centre |
| **What writes here** | `cable_guy` (per-member onboarding), inventory MCP, oracle MCP, PI's hand-edits | `centre_cable_guy` (lab/core onboarding), `registrar.create_lab` / `create_core`, join-request approvals, common-SEA submissions |

To decide where something belongs, ask whether it concerns one lab
specifically or how labs relate to each other. One-lab specifics
belong in `lab_mgmt`. Inter-lab relations belong in `lab_info`.

## See also

- [`docs/setup.md`](setup.md): first-time Murmurent install on a new
  machine, including the `~/repos/murmurent_lab_mgmt_<lab>` clone.
- [`docs/group_level.md`](group_level.md): the broader design
  document for group-scope Murmurent operations.
- [`docs/cores_plan.md`](https://github.com/hallettmiket/murmurent/blob/main/docs/cores_plan.md) §4: how a core's own
  `lab_mgmt` (yes, cores have one too, parallel to labs) mounts
  inside `~/.murmurent/lab_info/cores/<core>/lab-mgmt/`.
- [`agents/cable_guy.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/cable_guy.md): the per-lab
  cable_guy that owns most of the read/write surface on this repo.
