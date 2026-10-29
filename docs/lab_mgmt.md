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
repo and the local clone directory use this exact name. The local clone sits
directly in your repositories folder (`~/repos` unless you chose another;
`murmurent config repos-root` shows it), not inside a project folder:

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

This path is the only one murmurent looks at. A clone under any other
name or folder is not used: the dashboard and `murmurent import-card`
tell you the exact `mv` command that puts it in the right place.

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
├── pi_card.json              The PI's current signed identity card,
│                             written by `murmurent pi-init` (and when
│                             a centre-issued PI card is imported).
│                             Members' sign-in reads it, so renewing
│                             the PI card does not lock members out.
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
│                             dashboard's Projects and repos panel
│                             reads; it no longer scans ~/repos for
│                             CHARTER.md files.
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
│                             postdoc, pi-collab) the millwright
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
| Lab member (postdoc, student) | accept the GitHub invitation, then clone, read-only | `gh repo clone <owner>/murmurent_lab_mgmt_<lab> ~/repos/murmurent_lab_mgmt_<lab>` (the exact command is in the message that brought your card, and on the dashboard until you have cloned; `murmurent doctor` says why a clone is refused) |
| Core leader | clone OF THEIR CORE'S `lab_mgmt` (cores have their own) | same |
| Registrar | reads multiple `lab_mgmt` repos via the centre registry | each lab's path is recorded in `~/.murmurent/lab_info/_registry.yaml` |
| Mayor (bootstrap) | no | uses `~/.murmurent/lab_info/` instead |
| External customer | no | only sees the dashboard surfaces, not the underlying repo |

If you're a new lab member, the millwright agent's `PROVISION_MEMBER`
flow will tell you to clone it during onboarding. If you're a brand-
new PI joining a centre, the registrar will tell you to create one,
populate `lab.md`, and push it to your lab's GitHub org during the
join-request approval flow.

## How `lab_mgmt` is resolved at runtime

Your identity card (`~/.murmurent/identity.yaml`, written by
`murmurent import-card` or `murmurent pi-init`) lists the groups you
belong to. For each one, the records repo is at
`<your repositories folder>/murmurent_lab_mgmt_<group>`. That is the
whole lookup, and it is the same lookup for the dashboard and for every
terminal command, so they can never follow different labs.

`core.repo.lab_mgmt_repo_root()` returns the repo of your primary group
(the one you lead if you lead one, else the first on your card) in this
order:

1. **Per-request override**: the dashboard points each request at the
   viewer's own group, so a shared dashboard scopes each person correctly.
2. **`$MURMURENT_LAB_MGMT_REPO`**: an explicit pin to one repo, for tests
   and unusual deployments. When set, it wins everywhere.
3. **Your identity card**: the canonical path of your primary group,
   whether or not the clone is on disk yet. If it is not, the dashboard
   shows the clone command and panels stay empty until you run it.
4. **The centre registry**, for a machine with no card (a lab the
   registrar created on the mayor's machine lives under `lab_info/`).
5. A group-less default that never exists, so a machine with nothing
   configured misses cleanly.

Things that no longer exist, in case you meet them in old notes: the pin
file `~/.murmurent/lab_mgmt_path`, the scan of your repositories folder
for anything shaped like a records repo, and the one-person placeholder
roster that `import-card` used to invent when no clone was found. Each
of them could point a machine at the wrong lab, or at a roster of one,
with nothing on screen to say so.

### Projects you can see

The dashboard's Projects panel and `murmurent project list` show the
same list: the projects of every group on your card (read from each
group's `cert_projects/`), any project that lists you, and any project
you hold a project card for. A cross-lab project is recorded in the host
lab's records; if you are not in that lab, your card is what names it,
and the row says "hosted by" that lab without a team or repo list.

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

**A repo owned by a personal account cannot grant read-only through the
API.** GitHub answers `Cannot assign <login> permission of read` to every
such request, even for a member who already has read-only access (set from
the web page, which does allow it). This is why every grant to a repo under
a personal account such as `hallettmiket/...` failed until 2026-10-29, while
grants to an organisation-owned repo worked. The reconcile now falls back:
it invites the member with GitHub's default (write) permission and then
sets the pending invitation to read-only through the invitations endpoint,
which does accept it. If that second step is refused too, the member is
invited with write access and the line says so, with the settings page
where you can set them to Read after they accept. Members who already hold
write access are listed with the same link. Moving the records repo into a
GitHub organisation removes the limitation.

**A grant is only an invitation.** GitHub sends the member an email, and
if nobody accepts it within seven days it expires, silently. So the
reconcile reads the repo's collaborators *and* its pending invitations and
reports each member as one of:

| Line | Meaning | What `--apply` does |
|---|---|---|
| `read access ✓` | accepted; their machine can clone and pull | nothing |
| `invitation sent N days ago, expires in M days, not yet accepted: <link>` | waiting on the member | DMs them the link and the clone command |
| `invitation ... has expired` | never accepted | deletes the dead invitation, sends a new one, DMs them |
| `would grant read-only access` | never invited | invites them, DMs them |
| `no GitHub login on file` | nothing to invite | nothing; collect the login |

The DM goes through the group's own Slack bot, so it needs the group
Slack token on the PI's machine; without it the line says `reminder DM not
sent`. Reading invitations needs `gh` signed in as the repo owner; if it is
not, the reconcile says so and falls back to sending grants blind.

Each member then completes their side once: accept the invitation, and
clone the repo under its own name
(`gh repo clone <owner>/murmurent_lab_mgmt_<lab>
~/repos/murmurent_lab_mgmt_<lab>`). `gh repo clone` uses whichever
protocol they signed in to `gh` with; a bare `git clone git@github.com:...`
also needs an SSH key, and its "Permission denied (publickey)" is easily
mistaken for a missing invitation. From then on their Lab Members panel
and daily reconcile track what the PI pushes. Issuing a member card
sends this invitation and the clone command automatically; the reconcile
above is for members carded before that, or whose invitation failed or
lapsed.

**On the member's side, `murmurent doctor` names the cause** when the
clone is refused. Its "lab records" check asks GitHub, signed in as the
member, and reports one of: has access but not cloned yet (with the
command), no access (invitation waiting, expired, or never sent, with the
link to check and the reconcile to ask the PI for), signed in as a
different GitHub account from the one on the roster (the common case
when someone has two accounts), `gh` not signed in, or `gh` not installed.
`murmurent init` now checks the GitHub username it is given against
GitHub, defaults it to the account `gh` is signed in as, and warns before
accepting a blank one, since a blank or misspelled login is how a member
ends up never invited.

## Reading + writing: who's allowed?

| Path under `lab_mgmt/` | Read | Write |
|---|---|---|
| `lab.md` | everyone | PI |
| `members/*.md` | everyone | PI (or `millwright` via PI delegation) |
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

### How a member's profile edit reaches the roster (#34, #187)

Members hold the roster clone **read-only** by design: the PI is the only
writer, so a member's `git pull --ff-only` on the roster can never conflict.
So a member editing their own profile in the dashboard does **not** write to
`members/<handle>.md`. Instead:

1. **The edit is saved in the member's personal vault**
   (`profile/roster_profile.yaml`) and pushed, so their other machines get it.
   Their dashboard shows it straight away on every machine with that vault.
2. **The PI is sent the change** as an issue on the lab management repo,
   titled `Profile update: @<handle>`. Members can open issues with read
   access. A later edit updates the same issue.
3. **The PI applies it** with `murmurent reconcile --apply` on their own
   machine. The change is applied only if the GitHub account that opened the
   issue is the GitHub login already on that member's roster entry, so nobody
   can change someone else's details. A member's GitHub login is never changed
   from an issue. Each applied change is committed and pushed, and its issue
   closed. Without `--apply`, reconcile lists what is waiting.

If the member's machine has no personal vault, the change stays on that
machine (step 1) but is still sent to the PI (step 2). If the lab management
repo has no GitHub copy, the dashboard says the PI was not sent the change.

The PI's own profile edits go straight to `members/<pi>.md`, committed and
pushed. Every dashboard updates the roster and the vault when it starts and
every 15 minutes, so a change made elsewhere appears without pressing
"update".

Which settings follow you between machines and which stay on one machine is
recorded in `src/murmurent/core/settings_scope.py`; each settings window says
which at the top.

## `lab_mgmt` vs `~/.murmurent/lab_info/`: the comparison

| Aspect | `~/repos/lab_mgmt` | `~/.murmurent/lab_info/` |
|---|---|---|
| **Scope** | one lab | the whole centre |
| **Owner** | the PI | the registrar |
| **Members** | one PI + lab members | one or more registrars (mayors become first registrar) |
| **GitHub home** | the lab's own org | a private centre org (or none, can stay local + git-push to a private remote) |
| **First clone** | each lab member runs `git clone` once during onboarding | the mayor's machine creates it on `murmurent centre-init` |
| **Cross-lab visibility** | no: one lab's repo, period | yes: the registry lists every lab and core in the centre |
| **What writes here** | `millwright` (per-member onboarding), inventory MCP, oracle MCP, PI's hand-edits | `centre_millwright` (lab/core onboarding), `registrar.create_lab` / `create_core`, join-request approvals, common-SEA submissions |

To decide where something belongs, ask whether it concerns one lab
specifically or how labs relate to each other. One-lab specifics
belong in `lab_mgmt`. Inter-lab relations belong in `lab_info`.

## See also

- [`docs/setup.md`](setup.md): first-time Murmurent install on a new
  machine, including the `~/repos/murmurent_lab_mgmt_<lab>` clone.
- [`docs/group_level.md`](group_level.md): the broader design
  document for group-scope Murmurent operations.
- A core's own `lab_mgmt` (yes, cores have one too, parallel to labs)
  mounts inside `~/.murmurent/lab_info/cores/<core>/lab-mgmt/`.
- [`agents/millwright.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/millwright.md): the per-lab
  millwright that owns most of the read/write surface on this repo.
