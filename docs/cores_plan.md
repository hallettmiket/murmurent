# Cores in murmurent — comprehensive design plan

**Status:** draft for discussion. **Nothing implemented yet.** This document is the proposed strategy for adding cores (e.g. bioCore) to murmurent as first-class entities alongside labs. It answers items 0–8 from the user request, proposes architectural decisions, and ends with the open questions we need to resolve before any code lands.

Worked example throughout: **bioCore** (Western, Schulich, Department of Biochemistry — https://www.schulich.uwo.ca/biocore/). Three service modes (consultation / independent data collection / fee-for-service) — we focus on **independent data collection**. Three capability families (protein production & synthetic biology / structure-function-interaction / high-throughput molecular analysis) — we focus on **structure, function, and interaction**.

---

## 1. Executive summary

A **core** in murmurent is a peer of a lab. It has a leader (PI-equivalent), members (staff who run services), and lives under the centre's registrar. Where a lab does *open-ended research*, a core does *discrete repeatable services* with defined SLAs, fee schedules, training prerequisites, and equipment scheduling.

Architecturally, **a core is a lab whose "projects" are durable service offerings rather than time-bounded research investigations.** Most murmurent plumbing — agents, security guard, lab_mgmt registry, MEMBERS files, certification tracking, Slack notifications, Tier 2 sudo dump, reconcile — applies to cores with minor schema additions.

The genuinely new concepts are:

| Concept | What it is | Existing analogue |
|---|---|---|
| **Service catalog** | The menu of bookable offerings | `projects/` (one entry per service) |
| **Booking** | A user reserves a time slot on a piece of equipment | (none — new) |
| **Training prerequisites** | A user must complete training before booking certain services | TCPS_2 cert pattern from membership |
| **Pricing schedule** | Per-service fee tiers by time, user-class, and access | (none — new) |
| **Cross-lab user pool** | Anyone with a Schulich identity can use a core service, not just core staff | Currently lab-scoped; needs expanding |
| **Job → data deliverable** | Each booking produces files the requester needs to retrieve | Existing `raw/`/`refined/` model, scoped per-job |
| **Invoicing** | Periodic per-lab statement of charges | (none — new) |

We **recommend phasing** so we can land value quickly and learn before committing to the harder parts (scheduling UX, billing integration, cross-org identity). A 5-phase plan is in §11. Per-phase UI work for the Core Dashboard (added in §10) is folded into each phase rather than being separate.

---

## 2. Why cores are a peer of labs, not a special case

A core's leader is a PI. A core's members are HQP/staff. A core needs the same audit, the same security posture, the same identity model, the same agents (oracle, blacksmith, bookworm, security_guard, conscience, etc.). What differs is the *outward face*: a lab publishes papers, a core publishes services.

This shapes the implementation: we extend the existing entities rather than creating parallel ones.

```
                                ┌──────────────────┐
                                │   Centre         │
                                │   (registrar)    │
                                └────────┬─────────┘
                                         │ governs
                       ┌─────────────────┴─────────────────┐
                       │                                   │
              ┌────────▼────────┐                 ┌────────▼────────┐
              │   Lab           │                 │   Core          │
              │   PI + members  │                 │   Leader +      │
              │   Projects      │                 │   members       │
              │   SEAs          │                 │   Service       │
              │                 │                 │   catalog       │
              └────────┬────────┘                 │   (= projects)  │
                       │ research uses ──────────▶│   Service       │
                       │ core services            │   requests      │
                       └──────────────────────────│   (= SEAs)      │
                                                  │   Bookings      │
                                                  │   Invoices      │
                                                  └─────────────────┘
```

A lab member of lab `hallett` who needs to use a bioCore centrifuge becomes a **service requester** at bioCore — murmurent should know they're affiliated with lab `hallett` (for billing + data delivery) without making them a *member* of bioCore.

---

## 3. Item 0: Rename "users" → "members" everywhere

### Scope analysis

Run a quick grep to size the change:

```bash
grep -rn "\busers\b\|\buser\b" src/ docs/ tests/ agents/ rules/ skills/ --include="*.py" --include="*.md" --include="*.html" --include="*.jsx"
```

Expected hits: many. Most fall into three categories:

1. **Code variable names** (`user`, `user_id`, `actor=user`) — these are wired into the request/auth model. Pydantic field `user: str` is in the IdentityBlock and dozens of endpoints. Renaming everywhere would touch ~50 files.
2. **Documentation prose** — "users", "user-invocable", "user's vault", etc. — half-cosmetic, half-load-bearing.
3. **HTTP query string convention** — `?user=mhallet` is hardcoded in dozens of dashboard JS calls. Renaming to `?member=mhallet` breaks every saved bookmark.

### Proposal: tiered rename

| Layer | Rename? | Why |
|---|---|---|
| **User-facing copy** (UI labels, docs, headings) | **Yes** — "Members" not "Users" | This is what the user actually sees and what HQP terminology refers to. Easy + correct. |
| **lab.md / member frontmatter** | Already uses `members:` and `member` — no change needed | The data model is already correct. |
| **PeerRow / IdentityBlock field names** (`member`, `handle`) | Already uses `member` (snapshot.member, identity.member) — no change needed | The Python types already match. |
| **HTTP query string `?user=<h>`** | Add `?member=<h>` as the canonical name, **keep `?user=<h>` as a back-compat alias** for one release cycle, then drop it | Breaking every dashboard URL has zero benefit; aliasing is one line per endpoint. |
| **Python `actor=user` parameter names** (function args) | Rename to `actor` (which the endpoints already do internally) | Already done in most places; mop up the stragglers. |
| **`MemberRecord`, `members_dir()` etc.** | Already named correctly | No change. |

### "HQP" vs "member"

- **HQP** (Highly Qualified Personnel) is the term Canadian funding agencies (CIHR, NSERC, CFI) use in grant reporting and is what your TCPS_2 / chair-renewal materials use.
- **Member** is the broader, friendlier term that works across academic / industry / government contexts and is what murmurent already uses internally.

**Recommendation:** use **"member"** as murmurent's canonical word, and surface **"HQP"** only where it aligns with grant-reporting context (e.g., the training-compliance panel, certification reports). The two are not synonyms but the overlap is ~90%; collapsing them simplifies UX.

### PI vs Leader

Labs have PIs, cores have leaders. Same role, different vocabulary.

**Recommendation:** Add a `kind: lab | core` field to `lab_mgmt/lab.md` (and per-core: `core_mgmt/<core>.md` if we go that route — see §4). The dashboard chooses the right label based on `kind`. Internally, the field on the entity stays `pi:` (Pydantic name) but renders as "Leader" when `kind=core`. One label-map dict in the React component; zero schema migration.

### Estimated effort

Half a day of focused rename + grep verification + one back-compat shim per query-string endpoint. Land as a separate PR before any core work.

---

## 4. Items 1–4: Cores as first-class entities in the centre registrar

### 4a. Where the core registry lives — **STATUS UPDATE 2026-05-21**

**Correction from the original v1 of this plan.** I initially proposed extending `~/repos/lab_mgmt/` (the Hallett lab's per-lab repo) with a `cores/` subdir. **That was wrong**: `lab_mgmt` is one *lab's* repo. Cores aren't part of any lab — they're centre-wide. Putting them under `lab_mgmt/cores/` is a category error (a core isn't a member of the Hallett lab).

The right place was already wired up in murmurent:

- The **centre registrar** ([src/murmurent/core/registrar.py](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/core/registrar.py)) maintains `~/.murmurent/lab_info/` as the centre-wide registry. Index file `_registry.yaml` + per-entity directories under `labs/`, `cores/`, `collaborations/`.
- Each core gets a **self-contained per-core mini-repo** at `~/.murmurent/lab_info/cores/<name>/lab-mgmt/` — a directory tree that mirrors the per-lab `lab_mgmt/` layout (members/, projects/, requests/, audit/) but owned by the centre's registrar, not by any one lab's PI.
- Full CRUD already exists: `create_core`, `archive_core`, `unarchive_core`, edit endpoints, and a Cores panel on `/registrar` that calls into them.

**Why this is the right architecture (now, with hindsight):**

- Cores are governance-level entities (the registrar adds/removes them, not any single PI). Their natural home is the centre registry, not any one lab's repo.
- "A core is a self-contained mini-lab-mgmt" — beautifully captures the shape: a core has the same internal structure as a lab (members, projects, audit, requests) but its lifecycle is centre-managed. The existing `~/.murmurent/lab_info/cores/<name>/lab-mgmt/` directly expresses this.
- Cross-membership (a core staff member also in a lab) works via shared handles: both registries reference the same member handle string; the member's identity record lives in whichever lab they primarily belong to.
- All Phase 1+ work — registrar CRUD, security audit, slack-notify, training-compliance — already runs over `~/.murmurent/lab_info/` because the registrar dashboard's snapshot pulls from there. Zero migration needed.

**Practical consequence**: Phase 0c (originally "extend lab_mgmt") was reverted (murmurent `3da0aa8`, lab_mgmt `b0b3a5e`) and redone by calling the existing `core.registrar.create_core("biocore", ...)` API, which scaffolds at `~/.murmurent/lab_info/cores/biocore/`. The existing registrar dashboard renders bioCORE without code changes — Phase 0d collapses from "build a Cores panel" to "verify the existing Cores panel + add coverage tests."

The §4b schema below describes the **per-core lab-mgmt** that the registrar scaffolds; the storage path is `~/.murmurent/lab_info/cores/<core>/lab-mgmt/` not `~/repos/lab_mgmt/cores/<core>/`. The rest of the plan stands.

### 4b. Schema for `~/.murmurent/lab_info/cores/<core>/lab-mgmt/`

```
lab_mgmt/
├── lab.md                          # the host lab (Hallett)
├── members/                        # all centre members; lab + core overlap
│   └── mhallet.md
├── projects/                       # lab research projects
│   └── dcis_sc_tutorial.md
└── cores/                          # NEW
    └── biocore/
        ├── core.md                 # leader, members, kind, capabilities, contact
        ├── services/               # one .md per service offering
        │   ├── centrifuge_avanti_jxn_30.md
        │   ├── itc_microcal_peaq.md
        │   ├── circular_dichroism.md
        │   └── ...
        └── data/                   # pointers to /data/lab_vm/wigamig/core/<core>/
            └── DATA_LAYOUT.md      # describes how the core's data tree is organised
```

**`cores/biocore/core.md`** frontmatter (mirrors `lab.md` shape):

```yaml
---
core: biocore                       # short id; matches dir name
name: "BioCORE"                     # display name
kind: core                          # vs lab
leader: '@vdumeaux'                 # (placeholder — actual leader handle TBD)
members:                            # core staff; each has a member file too
  - '@vdumeaux'
  - '@<staff_1>'
description: |
  Western's biochemistry research core facility, offering protein
  production, structure/function/interaction analysis, and
  high-throughput molecular methods to investigators across the
  Schulich school.
website: https://www.schulich.uwo.ca/biocore/
contact:
  email: BioCORE@uwo.ca
  phone: "519-661-2111 ext 86945"
  location: "MSB 323, 1151 Richmond Street, London, ON"
capabilities:                       # broad capability families (matches website)
  - protein_production_synthetic_biology
  - structure_function_interaction
  - high_throughput_molecular_analysis
service_modes:                      # which modes murmurent wires up (for now: independent_data_collection only)
  - consultation                    # advisory; not bookable
  - independent_data_collection     # bookable; user runs the equipment
  - fee_for_service_data_collection # bookable; core staff runs the equipment
data_root: /data/lab_vm/wigamig/core/biocore  # where job data lives
billing:
  cost_centre: "C2-12345"           # Western fund code; placeholder
  invoice_period: monthly
  rate_tiers:                       # see §7
    - academic_internal
    - academic_external
    - industry
---

# BioCORE

Body: longer description, governance, calendar of upcoming training,
links to the lab_mgmt/cores/biocore/services/ subdir.
```

**`cores/biocore/services/<service>.md`** schema in §6.

### 4c. Registrar workflows (CRUD)

Mirror the existing labs/members CRUD endpoints. New endpoints:

| Method | Path | Body | Effect |
|---|---|---|---|
| `POST` | `/api/registrar/core` | `{core, name, leader, ...}` | Create `lab_mgmt/cores/<core>/core.md` |
| `PATCH` | `/api/registrar/core/{core}` | partial | Merge into frontmatter (preserves unknown fields) |
| `POST` | `/api/registrar/core/{core}/members/{handle}` | `{action: add|remove|set_role}` | Add/remove from `core.members` list |
| `POST` | `/api/registrar/core/{core}/leader` | `{handle}` | Rotate leader; logs to audit |
| `DELETE` | `/api/registrar/core/{core}` | — | Soft delete (sets `status: archived` in frontmatter; preserves file) |

The registrar dashboard at `/registrar` gains a **Cores panel** with the same UX shape as the existing **Labs panel**: table of cores, expandable per-core row showing members + service count + last activity. Editing happens via per-row inline edit (no separate modal — keep parity with labs).

### 4d. Registrar's cross-cutting view (item 3 in your spec)

The registrar dashboard already shows lab members + their certifications. Extend to include core members in the same training-compliance table, with one extra column **affiliation** (lab name or core name). For a member who's in both, two rows.

The `TrainingCompliancePanel` data builder already iterates `iter_members()` from `core.membership`. Change: iterate over both `lab_mgmt/members/*.md` (labs) and `lab_mgmt/cores/*/members/*.md` (cores). The certification UX is unchanged.

### 4e. Security guard scope (item 4 in your spec)

The security guard's Tier 1 + Tier 2 audit currently scopes to `/data/lab_vm/wigamig/{raw,refined,...}`. Extend the snapshot script's path list to include `/data/lab_vm/wigamig/core/<core>/{raw,refined,jobs}/` for every registered core.

Concretely:

- `scripts/lab_sec_dump.sh` enumerates `/data/lab_vm/wigamig/core/*/` and `nfs4_getfacl -R` each. Per-core budget (mirror the per-project budget we added in v6 for refined).
- The Tier 2 ACL template (the Dumeaux reference in `docs/security-dashboard.md`) gets a parallel **CORE-RAW-IMMUTABLE-01**, **CORE-REFINED-LAB-WRITE-01**, **CORE-JOB-DELIVERY-01** rule family. Same patterns as raw/refined, just scoped to core paths.
- A new finding category **CORE-OVER-EXPOSED-DATA-01** (warn): job data dirs at `core/<core>/jobs/<job_id>/` should be readable by exactly the requesting lab's group + the core's group, nothing more.

The security dashboard's per-host view stays the same UX; the rule catalog grows.

---

## 5. Item 5: SEAs adapted for service catalog + service requests

### Today's SEA model

A SEA (Service, Experiment, Assay) is filed in a lab project, has a from/to handle, a state machine (`open → assigned → in_progress → concluded`), and lives in `<project>/SEAs/<id>.md`.

### Adapted for cores

Two related but distinct entities:

#### 5a. Service catalog entry — `cores/<core>/services/<service>.md`

This is the **menu item** description. Static; doesn't change per booking.

```yaml
---
service: itc_microcal_peaq
name: "Isothermal Titration Calorimetry (MicroCal PEAQ-ITC)"
core: biocore
capability: structure_function_interaction
mode: independent_data_collection   # user runs it themselves
description: |
  Measures thermodynamic parameters of biomolecular binding
  interactions (Kd, ΔH, ΔS, stoichiometry).
equipment:
  manufacturer: Malvern Panalytical
  model: MicroCal PEAQ-ITC
  serial: "12345"
  location: "MSB 323, room A"
training_required: itc_basic_training   # references training catalog entry
prerequisites:
  - "Sample concentration ≥ 10 µM, volume ≥ 400 µL"
  - "Buffer matched between cell and syringe"
duration_default_min: 90              # for the calendar
duration_max_min: 240
fee:
  unit: per_run
  tiers:
    academic_internal: 80.00          # CAD; bioCore example
    academic_external: 130.00
    industry: 260.00
  modifiers:
    weekend: 1.25
    after_hours: 1.5
    overtime: 1.5                     # > duration_default
data_deliverable:
  format: "MicroCal .itc files + auto-generated PNG fit"
  delivery: per_job_acl              # murmurent grants requesting-lab read on job dir
contact:
  email: BioCORE@uwo.ca
status: active                        # active | maintenance | retired
---
```

#### 5b. Service request — `cores/<core>/requests/<request_id>.md` (the SEA analogue)

Filed when a user books a service. Same state machine as a SEA but with extra fields for the calendar + billing.

```yaml
---
request_id: 2026-05-21-001
service: itc_microcal_peaq
core: biocore
requester: '@knabavil'                 # the user's handle (cross-lab — see §4)
requester_lab: hallett                 # for billing + data delivery
state: scheduled                       # requested | scheduled | in_progress | completed | cancelled
booked_slot:
  start: 2026-05-23T10:00-04:00
  end:   2026-05-23T12:00-04:00
  calendar_event_id: <opaque>          # links to the Google Calendar event
training_verified:
  itc_basic_training: 2025-11-15       # date the user completed training
  by: '@vdumeaux'
prerequisites_attested:
  - "Sample concentration ≥ 10 µM": true
  - "Volume ≥ 400 µL": true
fee_at_booking:                        # snapshot of pricing at request time
  base: 80.00
  modifiers_applied: []
  total: 80.00
  tier: academic_internal
job_id: 2026-05-23-knabavil-itc-001    # used as the data-delivery dir name
notes: |
  Free-form notes from requester or core staff. Default empty.
---
```

The state machine matches existing SEAs so the dashboard UX is reusable: a panel listing pending/scheduled/completed requests, per-row actions to advance state.

### 5c. Integration with the existing murmurent dashboard

- **Member dashboard**: new **Service requests (mine)** panel showing requests the logged-in user has filed across all cores, with state + links.
- **Lab PI dashboard**: new **Lab service spend** panel showing requests filed by anyone in the PI's lab + monthly $ total.
- **Core leader dashboard** (new persona — see §10): inbox of incoming requests, calendar widget, fee schedule editor, member admin.

---

## 6. Item 6: Scheduling & booking

This is the biggest decision. We don't want to build a calendar app from scratch. Three options:

### Option A — Google Calendar via the existing Anthropic MCP

`mcp__claude_ai_Google_Calendar__*` tools are already loaded in this environment. Each service gets its own dedicated Google Calendar (e.g. `biocore-itc-peaq@western.calendar`); the core leader owns it and grants the bioCore service account write access. Bookings are calendar events with a custom property bag (request_id, fee, prereqs).

**Pros:**
- Zero new infrastructure. Users already use Google Calendar at Western.
- Native iCal subscription means a user can see their bookings in their phone calendar without us doing anything.
- Conflict detection is free (Google checks).
- Cancellation, reschedule, reminder emails — all built in.
- Murmurent MCP already wired in this environment.

**Cons:**
- No native pricing/tier logic — we layer it in murmurent.
- No native training-prerequisite enforcement — murmurent must check before creating the calendar event.
- Cross-org calendar sharing (a Hallett-lab member booking a bioCore calendar) needs the core to grant guest-write — once per calendar, manageable.
- Privacy concern: booking metadata sits on Google.

### Option B — Self-hosted booking system

Two open-source candidates:

**Booked Scheduler** (https://www.bookedscheduler.com/) — open-source, designed specifically for university shared-resource booking (centrifuges, microscopes, etc.). Has training-prerequisite enforcement built in. Supports per-resource rate schedules. PHP stack; runs on the lab server.

**Cal.com** (https://cal.com/) — modern, polished, well-maintained. Less "shared-equipment" focused (more individual scheduling) but has resource booking and webhooks. TypeScript stack.

**Pros:**
- Full control of the data; no Google dependency.
- Booked Scheduler in particular has the right shape for this domain (it's *literally* the use case it was built for).
- Self-hosting is one VM.

**Cons:**
- One more thing to run, secure, back up, update.
- Webhook integration with murmurent is bespoke.
- Authentication — needs to talk to Western SSO somehow, otherwise users juggle yet another login.

### Option C — Roll our own minimal booking layer

A `core/scheduling.py` module + a sqlite-backed table (or files in `lab_mgmt/cores/<core>/calendar/`). Just enough to record `(service, slot, requester)` with conflict detection and a per-service availability config (weekdays X to Y, max one booking per slot, etc.).

**Pros:**
- Total integration with murmurent identity, training, billing.
- No third party.

**Cons:**
- We're now in the calendar business. Reminder emails. Reschedule. Cancellation. iCal export. Mobile sync. None of that is trivial.

### Recommendation

**Phase A: Option A (Google Calendar MCP).** Fast to ship, leverages infra already in this CC environment, lets users see bookings in their existing tools. Murmurent owns the *policy* layer (training enforcement, fee snapshotting, lab-affiliation tracking) and Google owns the *calendar* layer.

**Phase B (if Phase A reveals friction):** evaluate Booked Scheduler as a self-hosted alternative. Migration is straightforward because all the wigamig-side state (request_id, fee_at_booking, training_verified, job_id) is independent of the calendar backend.

Concretely for Phase A:

1. Per-service `calendar_id` field added to the service catalog frontmatter.
2. New `core/booking.py` module:
   - `check_prereqs(request)` — returns list of missing items
   - `quote_fee(service, slot, tier)` — returns the fee using the service's rate_tiers + modifiers
   - `create_booking(request)` — checks prereqs, quotes fee, uses MCP `Google_Calendar.create_event` to create the calendar event, persists `requests/<request_id>.md`
   - `cancel_booking(request_id)` — uses MCP to delete the event, sets state to `cancelled`
3. New `/api/core/<core>/services` (GET = catalog), `/api/core/<core>/requests` (GET/POST), `/api/core/<core>/requests/<id>` (GET/PATCH).
4. New dashboard panel (member-facing): browse a core's services, book a slot, see your bookings.

### Training prerequisites

Add `lab_mgmt/cores/<core>/training/` directory:

```
training/
├── itc_basic_training.md          # describes the training, who teaches it, duration, refresher interval
└── centrifuge_basic_training.md
```

Per-member training records live in their existing `lab_mgmt/members/<handle>.md` frontmatter under a `training:` list (same shape as the existing `certifications:` list — just a different namespace):

```yaml
---
handle: '@knabavil'
training:
  - name: itc_basic_training
    completed: 2025-11-15
    by: '@vdumeaux'
    valid_until: 2027-11-15           # auto: 2-year refresher
  - name: centrifuge_basic_training
    completed: 2024-06-02
    by: '@<staff>'
---
```

This piggybacks on the existing certification UI; no new schema work in the dashboard's compliance panel.

---

## 7. Item 7: Billing

### Murmurent's role

**Murmurent is not a billing system.** Murmurent is a *billing-data producer*. It captures every billable event (a completed service request, the tier, the time-of-day modifiers, the requester's lab + Western ID) and emits structured invoice artifacts. A human then routes those artifacts through Western's actual finance system.

### Data model

Each completed service request has `fee_at_booking` snapshotted (so retroactive fee schedule changes don't rewrite history). On state transition `in_progress → completed`, the request gains an `actual_charge` field that may differ from `fee_at_booking` (e.g., the run went 30 min over → overtime modifier kicks in). The core leader confirms the actual charge before invoicing.

### Monthly invoice generation

End-of-month CLI command (and scheduled via CC `/routine`):

```bash
murmurent core invoice --core biocore --month 2026-05
```

Produces, per requesting-lab, a CSV + PDF at:

```
lab_mgmt/cores/biocore/invoices/2026-05/
├── hallett.csv
├── hallett.pdf
├── castellani.csv
├── castellani.pdf
└── summary.md
```

The PDF format mirrors what Western accounting expects (line items, tax breakdowns, cost-centre reference). The CSV is for the lab PI's records + machine-readable forwarding.

### Western finance integration — three realistic paths

| Path | Effort | Probability of success |
|---|---|---|
| **1. Manual** (lab admin emails PDF to Western finance, mirrors current bioCore process) | None | 100% |
| **2. Semi-automated** (lab admin uploads CSVs into Western's expense-report tool) | Low | Likely Western has a CSV upload format; can match it |
| **3. API integration** (murmurent POSTs invoices to Western finance) | High; needs Western IT engagement, contracts | Low — Western IT is risk-averse with research-side automation |

**Recommendation for v1:** ship Path 1, design the CSV/PDF to make Path 2 easy when the lab admin is ready. Defer Path 3 until there's a clear business case (e.g., bioCore wants real-time charge-back to lab fund balances).

### Direct payment for industry / external collaborators

The "industry" tier in the fee schedule covers customers who aren't on a Western lab fund. Two sub-paths:

- **Western invoice → external customer** (existing bioCore flow) — murmurent generates the invoice, Western's existing Accounts Receivable system bills the customer. No new integration.
- **Direct Stripe/Square payment at booking** — murmurent generates a payment link, user pays before the slot is confirmed. Useful for one-off industry users who don't want to deal with Western AR. Stripe has a Python SDK; integration is ~half a day. Requires the core to have a merchant account.

**Recommendation:** ship the Western-invoice path for v1; flag Stripe as a Phase 5 add-on if bioCore actually has external customers who want it.

### Per-lab budget alerts (nice-to-have)

A lab PI can set a monthly budget cap. When their lab's accumulated charges in a month hit 75% of cap, murmurent posts to the lab's Slack channel. At 100%, optionally block further bookings (configurable per lab — some PIs prefer the alert without the block).

---

## 8. Item 8: Data delivery

The use case: a Hallett-lab member books bioCore's ITC service. ITC produces ~10 MB of `.itc` files + a fit PNG. Those files need to land somewhere the Hallett lab can read, without bioCore's *other* customers being able to see them.

### Storage layout

```
/data/lab_vm/wigamig/core/biocore/
├── jobs/
│   ├── 2026-05-23-knabavil-itc-001/
│   │   ├── manifest.json                    # request_id, service, requester, lab, fee
│   │   ├── raw/
│   │   │   ├── sample1.itc
│   │   │   └── sample2.itc
│   │   └── refined/
│   │       └── fit.png
│   └── 2026-05-23-jdeloss4-cd-002/
│       └── ...
├── raw/                                     # core's own staging area (not per-job)
└── refined/                                 # core's own derived data (not per-job)
```

The per-job dir has its own ACL: read-only for the requesting lab's group + read-write for the core's group. Other labs can't see in.

### Three options for actually giving the lab access

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **1. Per-job NFSv4 ACL grants** | At job completion, `lab_sec_dump`-like script (running as root) sets an inheriting ACE granting `ssmd-u-<labgroup>:rxtTcy` on the job dir | Native, no daemon, files visible in the lab's normal mount | Requires root ACL changes on every job — that's a lot of `nfs4_setfacl` calls. Auditing later is harder. |
| **2. Murmurent MCP (`murmurent-core-data`)** | New MCP server that exposes `list_jobs(lab=)`, `get_job_status(job_id)`, `read_file(job_id, path)`, `bundle_job(job_id)`. The MCP runs as a service account, walks the job dir, returns content. Murmurent identity check at the request layer. | Clean access-control story (one place to enforce policy); easy auditing (MCP logs each access); works the same on every machine | Users get data via tooling (`claude` / dashboard download button), not as files in their lab's normal mount. They have to copy/move if they want files on disk. |
| **3. Per-job signed URLs** | Murmurent HTTP server signs a short-lived (e.g. 72h) URL per file; user downloads via browser/curl | Familiar UX (one-click download); easy to email the link to a non-CC user | Files leave the lab_vm tree onto the murmurent host's disk during download; needs HTTPS + cert; sharing the link is a security hole if it leaks |

**Recommendation: Option 2 (MCP)** as the primary mechanism, with Option 1 as a *fallback* for users who absolutely need the files on the lab's NFS mount.

Why Option 2:
- It mirrors how `murmurent-oracle` already works (server-side filter + identity check, client gets only what's allowed). Murmurent has the pattern.
- The audit trail is built-in: every read is one MCP-call log line, telling us who pulled what when. Compare to the NFS-ACL path where reads are not logged at the filesystem layer.
- It's the right ergonomics for a research lab: the requester opens Claude Code, asks "show me my most recent ITC fits," the MCP returns them, the agent analyses them. The data never has to land on the lab's working tree.

Sketch of the MCP server:

```
murmurent-core-data  (new MCP server in src/murmurent/mcp/core_data_server.py)

Tools:
  list_my_jobs(state="completed", limit=20)
      → returns jobs where requester_lab matches the caller's lab
  get_job_manifest(job_id)
      → returns the manifest.json; refuses if caller's lab != job.requester_lab
  list_job_files(job_id)
      → directory listing inside the job dir
  read_job_file(job_id, relpath, max_bytes=10_485_760)
      → file contents; refuses outside the job dir; size-capped
  bundle_job(job_id, format="tar.gz")
      → returns a single archive blob (for offline analysis)

Identity:
  Honours MURMURENT_USER env (set by the murmurent shell wrapper); falls back
  to the user's claim in the MCP call. Refuses if the caller's lab
  doesn't match the job's requester_lab field UNLESS the caller is a
  member of the core itself (core staff see all jobs in their core).

Audit:
  Every call logged to /var/log/wigamig/core_data_access.log on the
  host where the MCP server runs (lab server, near the data).
```

### Where the MCP runs

On the lab server (biodatsci) close to the data. The user's local CC session connects via stdio over SSH (same pattern as the existing murmurent-oracle MCP).

### What's MCP-applicable beyond data delivery?

The user asked. Other MCP candidates for cores:

- **`wigamig-core-services`** — list services, check availability, quote a fee, book a slot, cancel. Lets a researcher say "claude, find me an ITC slot tomorrow morning" and the agent does the conversation with bioCore via MCP. This is *exactly* what MCP is for.
- **`wigamig-core-billing`** — read-only access to a lab's spend in a period, for PI's monthly review.
- **`wigamig-core-training`** — what training do I have, when does it expire, when's the next session.

The agent-side wins are clear: a member of the Hallett lab can now have a conversation like "I have a sample at 8 µM, can I run ITC this week?" and the agent checks training, books the slot, and confirms — all via MCPs. That's a step change in UX.

### Cores with existing data infrastructure

Many established cores (genomics core with sequencers writing to BaseSpace, proteomics core with mass-spec data on a vendor server) will not migrate their data to `/data/lab_vm/wigamig/core/<core>/`. Murmurent needs to handle the "core stores its data elsewhere; murmurent is just the access layer" case:

- The core's `data_root` field can be a URL (s3://, https://, sftp://) or a mount path on the lab server.
- The `murmurent-core-data` MCP's `read_job_file` implementation per-core handles the backend (filesystem, s3, http GET, vendor API).
- For BaseSpace (Illumina): there's an existing API + Python SDK. The MCP wraps it.
- For mass-spec instruments writing to an Exchange-share-style NAS: the MCP mounts read-only and proxies.

This keeps the abstraction stable while letting each core wire in whatever its existing infrastructure is.

---

## 9. Cross-lab user identity (a thing item 6 implies but isn't called out)

bioCore's customers are Hallett-lab members, Castellani-lab members, industry collaborators — anyone with a Schulich identity. Murmurent today scopes users to one lab via `lab_mgmt/members/<handle>.md` + a `lab:` field. We need to handle "this user is *primarily* in lab X but is *currently requesting a service from* core Y."

Proposed model:

- Every Schulich identity gets a `lab_mgmt/members/<handle>.md` whether or not they're affiliated with a lab. (For external industry customers, the `lab:` field becomes `external` or holds the company name.)
- A service request carries `requester` (the handle) and `requester_lab` (resolved at booking time from the member file).
- Billing flows through `requester_lab` (the lab pays). Data delivery flows through `requester_lab` (the lab gets access).

For non-Schulich industry users:
- A `lab_mgmt/external_customers/<id>.md` file with billing contact, PO number, etc.
- The MCP / dashboard treats them as a special-case lab for the purposes of request routing.

---

## 10. The Core Dashboard (added 2026-05-21)

Each core's leader needs a dashboard that mirrors the lab PI dashboard's shape, with core-specific extensions. Login: a new persona option `core_leader` (alongside `member`/`pi`/`registrar`), routed to a new top-level URL `/core?core=<id>&user=<handle>`.

### Why a separate route

Three reasons:

1. **Cognitive scope**: the lab PI cares about projects, SEAs, experiments. The core leader cares about service catalog, incoming requests, equipment calendar, monthly invoice run. The data on screen at any given moment shouldn't mix.
2. **Permission model**: the core leader has admin rights inside the core (add/remove core members, edit service catalog, set fees, approve/cancel requests) but is just an ordinary lab member elsewhere. A separate route lets us gate one without polluting the other.
3. **Multi-affiliation**: a person can lead bioCore AND be a member of the Hallett lab. They'd switch between `/core?core=biocore` and `/dashboard` via the cmd-bar `↺ switch` link, the same way registrar already does.

### Panel inventory

The Core Dashboard reuses ~70% of the lab PI dashboard's panels. New panels for the core-specific concerns. Phasing notes which panels arrive in which phase.

| Panel | Source | New / Reused | Phase |
|---|---|---|---|
| Topbar (lab logo → "BioCORE", member chip, ↺ switch, ⚿ security if granted) | hifi-app.jsx topbar | Reused + relabelled | 1 |
| Cmd-bar (search) | hifi-app.jsx CmdBar | Reused; scope changes to search services + requests + member roster | 1 |
| Identity block (leader + core contact info + capabilities list) | new | New (parallels lab identity block) | 1 |
| **Core members panel** (analogue of LabMembersPanel — list staff, status, certifications, deactivate/reactivate) | LabMembersPanel | Reused as-is, scoped to core members | 1 |
| **Service catalog panel** (list services, per-row status: active / maintenance / retired) | new | New (analogous to ProjectsPanel for labs) | 2 |
| **Incoming requests inbox** (state machine: requested → scheduled → in_progress → completed) | new (analogous to SEAs) | New | 3 |
| **Calendar widget** (next 30 days of bookings across all services) | new | New, embeds Google Calendar iframe per-service | 3 |
| **Training catalogue + roster** (who has done which training, expiring soon) | extends TrainingCompliancePanel | Reused + extended | 2-3 |
| **Fee schedule editor** (per-service rate tiers + modifiers) | new | New | 2 |
| **Pending invoices** (current month's accumulated charges per requesting-lab) | new | New | 5 |
| **Data deliverables overview** (recent jobs + their delivery status: pending / delivered / archived) | new | New (consumes murmurent-core-data MCP) | 4 |
| **Repos panel** (this core's tooling repos, e.g. analysis scripts) | RepoInventoryPanel | Reused as-is | 1 |
| **Security access (lab_sudo for core)** (which core staff can see /security) | SecurityAccessPanel | Reused, gates on core_leader instead of lab PI | 1 |
| **Lab Oracle / personal Oracle** | OraclePanel | Reused | 1 |
| **Audit log slice** (recent state-changing actions inside this core) | new (filtered audit) | New view of existing audit data | 1-3 |

### What's NOT on the Core Dashboard

To keep the leader's screen focused, deliberately excluded:
- Lab research projects (those live on the PI dashboard).
- Lab SEAs (research-side; the core's analogue is "incoming requests").
- Cross-centre registrar view (that's the registrar route).
- Per-project experiment notebooks (cores don't have lab-research experiments).

### Persona + login routing

`POST /api/login/select` body gains `role: "core_leader"` as a valid option. The resolve endpoint (`/api/login/resolve`) returns `is_core_leader: bool` after a frontmatter check: walks `lab_mgmt/cores/*/core.md`, sets True if any `leader: '@<handle>'` matches the requested handle. The login page surfaces "Core leader view" as an additional role-pill (greyed out unless `is_core_leader: true`); on submit the redirect is `/core?core=<found>&user=<handle>`.

A leader of multiple cores (rare but possible) gets a core-picker on the login page; selecting one becomes the `?core=` query parameter.

### Why we didn't reuse `/dashboard?persona=pi&kind=core`

Considered. The risk is that "PI lens" baked the lab-research mental model into every panel (projects, SEAs, lab inventory). Trying to overlay `kind=core` onto that lens would require dozens of conditionals per panel ("if core, hide projects; if core, rename SEAs to requests; if core, show calendar instead of experiments"). A dedicated route makes the panel set explicit and keeps both dashboards readable.

### Effort

Phase 1 lands the Core Dashboard shell (topbar + identity + members panel + repos + security-access). Phase 2 adds the service catalog + fee editor. Phase 3 adds the inbox + calendar. Phase 4 adds the data deliverables overview. Phase 5 adds pending invoices. The dashboard grows feature-by-feature alongside the underlying functionality; nothing renders until its backing data is real.

Estimate: roughly +1 week distributed across Phases 1-5 (each phase's UI is +1-2 days on top of its backend work). Already absorbed into the existing per-phase estimates rather than appearing as a separate phase.

---

## 11. Phasing

**Hard rule: each phase ships independently and produces user value before the next starts.**

### Phase 0 — Terminology + scaffolding (≈ 2-3 days)

- Rename "users" → "members" in user-facing copy (per §3).
- Add `kind: lab | core` to `lab_mgmt/lab.md`; dashboard renders "Leader" vs "PI".
- Add empty `lab_mgmt/cores/` directory + the `cores/biocore/core.md` example file (just the leader + members, no services yet).
- Registrar dashboard shows a "Cores" panel that lists registered cores. Empty until later phases.

**Deliverable:** Registrar can see "BioCORE" as a registered entity. No services yet.

### Phase 1 — Core CRUD + security audit (≈ 1 week)

- Registrar can add/delete/rename cores; add/remove core members; rotate leader.
- Security guard's snapshot script extends to walk `/data/lab_vm/wigamig/core/<core>/`.
- Tier 2 ACL templates for core dirs.
- Slack notifications when core membership changes.

**Deliverable:** Cores are first-class entities; full lifecycle managed by the registrar; security audit covers them.

### Phase 2 — Service catalog (≈ 1 week)

- Schema for `cores/<core>/services/<service>.md`.
- Dashboard panel: "Browse services" for any user; "Manage services" for the core leader.
- Training prerequisites schema + per-member training records.
- Fee schedule editor.

**Deliverable:** bioCore staff can curate a service catalog visible to all centre members; no bookings yet.

### Phase 3 — Booking (≈ 2 weeks; the largest phase)

- Google Calendar MCP integration: per-service calendar, event creation on booking.
- Request lifecycle (requested → scheduled → in_progress → completed → cancelled).
- Pre-booking checks (training, prereq attestation, fee quote).
- Member dashboard: "My bookings"; core leader dashboard: "Incoming requests."
- Reminder Slack DMs to requester 24h before, 1h before.

**Deliverable:** A Hallett-lab member can book ITC time; bioCore staff see the booking on their calendar; reminder sent.

### Phase 4 — Data delivery MCP (≈ 1 week)

- `murmurent-core-data` MCP server.
- Job manifest schema; `bundle_job` for archive download.
- Per-job ACL grant fallback (Option 1 above) for users who need files on the NFS mount.
- Audit log of every data-access call.

**Deliverable:** Completed bookings produce data; the requesting lab can pull it via MCP or NFS.

### Phase 5 — Billing (≈ 1-2 weeks)

- `murmurent core invoice --core <core> --month YYYY-MM` CLI.
- Per-lab CSV + PDF invoices.
- Monthly Slack summary to each PI.
- Budget cap + alerts (optional).
- *Defer* Western-finance API integration unless explicitly requested.

**Deliverable:** End-of-month invoices generated automatically; lab admin can route to Western finance manually.

### Phase 6 (optional / nice-to-have)

- `wigamig-core-services` MCP for conversational booking.
- `wigamig-core-billing` MCP for read-only spend queries.
- Stripe direct-pay for external customers.
- Migration tools for cores with existing booking systems (Booked Scheduler export, etc.).

---

## 12. Risks and open questions

These need a decision from you before the plan goes further:

### Architecture

1. **Confirm: extend `lab_mgmt` rather than create `core_mgmt`.** §4a recommends extending; do you agree, or do you want strict isolation between lab and core registries?
2. **Schema for `requester_lab` on cross-lab requests** — proposed in §9. Do external (industry) customers need to model as a `lab_mgmt/external_customers/` directory, or is your initial scope all-internal?

### Scheduling

3. **Google Calendar vs Booked Scheduler.** §6 recommends Google Calendar via existing MCP for v1. Comfortable with Google holding bioCore booking metadata, or do you want a self-hosted booking layer from day one (longer build but full control)?
4. **Conflict semantics**: one ITC machine = one booking at a time, obvious. But the centrifuge in your spec has *multiple users running in parallel* (it's a shared piece of equipment with multiple rotors). Does each rotor become its own service? Or does the service have an `instances: N` field allowing N concurrent bookings?
5. **Training requirements**: per-service or per-equipment family? E.g., does "centrifuge training" cover all rotors, or do users train per-model?

### Billing

6. **Tier vocabulary**. §5a proposes `academic_internal / academic_external / industry`. Is that bioCore's actual structure, or do they have e.g. a "graduate trainee discount" tier?
7. **Time-of-day modifiers**. §5a sketches `weekend / after_hours / overtime` modifiers. Is that bioCore's actual structure, or do they have a flat schedule?
8. **Cost-centre / Western fund-code field**. Is the right level to attach this on the *request* (per-booking, member specifies their lab fund), on the *member profile* (their default fund), or on the *lab* (the lab's default fund)? Probably hierarchical: lab default → member override → request-time override.

### Data delivery

9. **Confirm MCP-first vs ACL-first.** §8 recommends MCP-first with ACL as fallback. The opposite (ACL-first) would mean writing per-job ACEs at job completion; less novel to users but the audit trail is weaker.
10. **Retention policy**. How long does a completed-job's data sit at `core/<core>/jobs/<job_id>/` before it's archived or deleted? Does the requesting lab "own" the data forever (storage costs), or does the core hold it for N months then make the lab pay to keep it?

### Cross-core concerns

11. **Multiple cores at the centre.** Plan structures for "any number of cores." Once bioCore is wired, adding the next core (genomics, proteomics, …) is mostly schema + service catalog. Confirm: that's the intended scaling shape.
12. **Cores using existing data infrastructure** (genomics on BaseSpace, proteomics on vendor NAS). The MCP-per-backend approach in §8 handles this; but adopting an existing core means writing a per-backend adapter. Are there cores you want to onboard whose backends I should research now (e.g., would knowing the genomics-core's actual data system shape the MCP design)?

### Process

13. **Who signs off on the leader for each core?** The registrar can set it; but is there a centre-level approval step before a person becomes a core's leader (e.g., a director's review)?
14. **Audit trail of fee schedule changes**. If bioCore raises the ITC fee from $80 to $100, requests booked before the change must keep the old fee. The `fee_at_booking` snapshot in §5b handles this — confirm that satisfies your audit requirements.

---

## 13. What this plan does NOT cover

To set expectations on what's out of scope and would be future work:

- **Multi-centre federation** — murmurent assumes one centre. If Schulich grows into a multi-centre group (e.g., adding Robarts), we'd need a layer above the registrar.
- **Public marketplace**. The plan assumes services are offered to centre-affiliated users only. A public-facing "bioCore is open to anyone with a credit card" mode is a separate effort.
- **Time-and-motion analytics**. Tracking actual-vs-quoted duration over time is doable from the booking data, but I haven't sketched the dashboards for it.
- **Equipment health / maintenance scheduling**. A core has a centrifuge that needs calibration every 6 months. Murmurent could track maintenance windows, but that's a separate scope (equipment registry, not service catalog).
- **Sample tracking**. A user dropping off a tube for bioCore staff to run later (the fee_for_service mode) implies sample-tracking that we're explicitly out-of-scope for the focus on independent_data_collection.

---

## 14. Why bioCore first

bioCore is the right pilot because:

- It's already established (real customers, real fee schedule, real workflows we can learn from).
- The leader is in the existing murmurent ecosystem (Vanessa is already in `lab_mgmt/members/`).
- The capability range (centrifuge, ITC, CD, mass spec) spans the simple-to-complex spectrum, so we'll surface design issues early.
- It's small enough to onboard end-to-end before we generalise to other cores.
- The data is already on biodatsci, where murmurent already runs.

Once Phase 0-4 are live for bioCore, **the second core** (genomics, proteomics, microscopy — your call) is mostly schema + service catalog + per-backend MCP adapter. The platform is built once.

---

## 15. Effort summary

| Phase | Effort | Cumulative |
|---|---|---|
| 0. Terminology + scaffolding | 2-3 days | 3 days |
| 1. Core CRUD + security audit | 1 week | 1.5 weeks |
| 2. Service catalog | 1 week | 2.5 weeks |
| 3. Booking | 2 weeks | 4.5 weeks |
| 4. Data delivery MCP | 1 week | 5.5 weeks |
| 5. Billing | 1-2 weeks | 7 weeks |
| 6. Optional add-ons | as-needed | — |

Total to a workable bioCore in murmurent: **~7 weeks** of focused work, with usable deliverables at each phase boundary. Phase 0+1 alone gives the registrar what they need to track cores; Phase 2 gives bioCore's leader the catalog editor; Phase 3 is where end-users see real value.

---

## 16. Next decisions for you

Before this plan turns into code, I need answers to the **open questions in §11**, especially:

1. lab_mgmt-extension vs core_mgmt-sibling (§11.1)
2. Google Calendar vs Booked Scheduler (§11.3)
3. MCP-first vs ACL-first data delivery (§11.9)
4. Confirm the phasing in §10 — start with Phase 0 (terminology + scaffolding) and iterate?

Plus a request: if you can grab from bioCore's actual fee schedule page, the **tier names and modifier structure** they actually use, that'll let me skip §11.6 and §11.7 with real data instead of placeholders.

---

*Drafted 2026-05-21. Author: Mike Hallett with Claude. Comments / pushback welcome — this is meant to be marked up before any code lands.*
