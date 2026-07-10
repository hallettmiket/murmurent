# The `lab_mgmt` repository

The single most-confusing piece of murmurent's filesystem layout is what
`lab_mgmt` is, who needs it, and how it differs from
`~/.wigamig/lab_info/`. This document is the short answer.

## TL;DR

`lab_mgmt` is the **per-group governance repo** — one per PI. It is
NOT a murmurent commons artifact; it belongs to the lab. It holds the
canonical roster, project registry, inventory, training records,
audit log, and other day-to-day filing-cabinet contents for ONE
research group.

Different labs each have their own `lab_mgmt` repo under their own
GitHub org. The Hallett lab's lives at
`hallettmiket/lab_mgmt`; the Castellani lab's would live at
`castellani-lab/lab_mgmt` (or wherever the Castellani PI hosts it).

The centre-wide registry (labs, cores, common SEAs, join requests)
lives in a separate, distinct tree at `~/.wigamig/lab_info/`. That
one is owned by the registrar, not by any single lab.

## Why not rename it `wigamig-mgmt`?

Tempting — but no. The name `lab_mgmt` correctly signals "the lab's
own management data," analogous to how a paper folder labelled "Lab
Filing Cabinet" sits on the PI's bookshelf. Renaming to
`wigamig-mgmt` would imply this is a wigamig-owned artifact you can
update from the commons. It isn't: every murmurent install reads
multiple `lab_mgmt` repos (one per lab in the centre) and never
writes across labs.

The clean conceptual boundary is:

```
~/repos/wigamig/         ← Commons: agents, rules, skills, CLI source.
                           Shared across the centre. Symlinked into
                           ~/.claude/. Anyone can clone.
~/repos/lab_mgmt/        ← One lab's filing cabinet. PI-owned.
                           Members read; PI + delegates write.
~/.wigamig/lab_info/     ← Centre registry. Registrar-owned.
                           Lists every lab + core + common SEA in
                           the centre.
```

Different roles read different trees. Renaming `lab_mgmt` would
break the visual symmetry — the prefix would no longer announce who
owns it.

## What lives in `lab_mgmt`?

Default location is `~/repos/lab_mgmt/`. The directory layout:

```
lab_mgmt/
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
├── projects/                 Per-project registry entries. Each
│                             holds the project's charter, members
│                             subset, status.
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
| Lab PI | clone, write, push | `git clone git@github.com:<lab-org>/lab_mgmt ~/repos/lab_mgmt` |
| Lab member (postdoc, student) | clone, read-only | same |
| Core leader | clone OF THEIR CORE'S `lab_mgmt` (cores have their own) | same |
| Registrar | reads multiple `lab_mgmt` repos via the centre registry | each lab's path is recorded in `~/.wigamig/lab_info/_registry.yaml` |
| Mayor (bootstrap) | no | uses `~/.wigamig/lab_info/` instead |
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
2. **`$WIGAMIG_LAB_MGMT_REPO` env var** — for tests + scripted use.
3. **`~/repos/lab_mgmt`** — the default if it exists.
4. **`~/repos/hallett-lab-mgmt`** — legacy fallback from before the
   2026-05-14 rename. Will be removed in a future cleanup.
5. **`~/repos/lab_mgmt`** — used unconditionally if none of the
   above exists (so first-clone instructions can write to a known
   location).

The `WIGAMIG_LAB_MGMT_REPO` env var is the right knob for tests and
unusual deployments (e.g. multi-lab dev workstations). For a normal
lab member, the default path just works.

## Reading + writing — who's allowed?

| Path under `lab_mgmt/` | Read | Write |
|---|---|---|
| `lab.md` | everyone | PI |
| `members/*.md` | everyone | PI (or `cable_guy` via PI delegation) |
| `inventory/*.md` | everyone | `lab_manager` role via the inventory MCP |
| `oracle/*.md` | everyone | `oracle_curator` role via the oracle publish flow |
| `projects/*.md` | everyone | project lead + PI |
| `roles/*.md`, `audit/*.md` | everyone | PI |
| `compliance.md` | everyone | PI |

In practice the granular write permissions are enforced by the
**MCP layer**, not by git. Members CAN locally edit `inventory/*.md`,
but the inventory MCP refuses to commit-publish their changes unless
they hold the `lab_manager` role. The PI's review on incoming PRs is
the final gate.

## `lab_mgmt` vs `~/.wigamig/lab_info/` — the comparison

| Aspect | `~/repos/lab_mgmt` | `~/.wigamig/lab_info/` |
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

- [`docs/setup.md`](setup.md) — first-time murmurent install on a new
  machine, including the recommended `~/repos/lab_mgmt` clone.
- [`docs/group_level.md`](group_level.md) — the broader design
  document for group-scope murmurent operations.
- [`docs/cores_plan.md`](cores_plan.md) §4 — how a core's own
  `lab_mgmt` (yes, cores have one too, parallel to labs) mounts
  inside `~/.wigamig/lab_info/cores/<core>/lab-mgmt/`.
- [`agents/cable_guy.md`](../agents/cable_guy.md) — the per-lab
  cable_guy that owns most of the read/write surface on this repo.
