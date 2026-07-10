---
date: 2026-05-06
tags: [murmurent, prompt]
---

# Phase 5 prompt: Dashboard + tutorial

> Phase 5 of 5 — the final phase. Phases 1–4 shipped: full CLI, MCP, hooks, finalisation.
>
> Read first: `docs/implementation_prompt.md`, `docs/group_level.md`, `docs/cli_manual.md`, prior phase prompts.

## Goal

Dashboard renders the textured fake state; tutorial document walks two students through the smoke test end-to-end; final smoke run is performed and any breakage fixed.

## Preconditions

- All prior phases merged
- All seed data + hooks + MCP in place
- `streamlit` installable

## Deliverables

1. **Dashboard snapshot generator** at `scripts/generate_dashboard.py`
   - Walks `lab-mgmt` repo + both project repos + lab VM
   - Computes per-member dashboard contents: identity, agents, projects, SEAs (incoming / outgoing), outstanding analysis (items where user is squad member or lead and `analysis_status != concluded`, sorted by age since `complete`), security and compliance (per-project tier badge, certifications, missing items in red), PI-only sections if user is `@mike`
   - Writes `<lab-mgmt>/dashboards/<handle>.md` per member
   - Idempotent
   - GitHub Action `.github/workflows/dashboard.yml` triggers on PR merge to `main` of any project repo

2. **Streamlit viewer** at `src/wigamig/dashboard/app.py`
   - Reads the snapshot for static state; queries inventory MCP live for current inventory
   - Outstanding analysis: subtle yellow at >2 weeks since `complete` and not `examined`; red and "escalated" at >2 months
   - Security and compliance: red for missing required (e.g. Cassie's TCPS 2)
   - Member view by default; PI view auto-enabled if `WIGAMIG_USER=mike`
   - `murmurent dashboard` opens streamlit on localhost
   - `murmurent dashboard --snapshot` prints the markdown
   - `murmurent dashboard --outstanding` prints the Outstanding analysis as a terminal summary

3. **Compliance state seeded** in member files (extend seed script to v5):
   - `@allie`: TCPS 2 ✓, TOTP ✓, signing key ✓ — green
   - `@bob`: TCPS 2 expires in 30 days — yellow
   - `@cassie`: TCPS 2 missing — red (would block `dcis_sc_tutorial` access in production; v1 just flags visually)
   - `@mike`: all green; PI dashboard surfaces Cassie's red status

4. **Tutorial document** at `TUTORIAL.md`
   - **Day 1 (each student solo)**: `murmurent install`; explore the dashboard; locate both project repos; understand `MEMBERS` files
   - **Day 2 (each student solo)**: claim a pre-seeded SEA; do (synthetic) work; `murmurent push` to personal branch; `murmurent push --finalize` opens a PR
   - **Day 3 (collaborative, all three online)**: finalise SEA #3 (Allie's methodology review with Mike). Each squad member invokes the relevant CC agents to fill the deliberation document. Squad approves. Statement promoted to a finding.
   - **Day 4 (deliberate breakage)**: try to paste fake OHIP `1234-567-890-AB` into a `dcis_sc_tutorial` prompt; try to write to a raw-data path; try to read another project's repo as a non-member
   - **Day 5 (debrief)**: file smoke-test issues using the issue template
   - Concrete commands at each step with expected output
   - "What to check" punch list per step

5. **Troubleshooting** at `TROUBLESHOOTING.md`
   - Common failure modes (hook not firing, MCP not registered, gh auth issues, branch protection blocking, etc.)
   - How to recover

6. **Issue template** at `.github/ISSUE_TEMPLATE/smoke_test.md`
   - Sections: what was confusing, what was broken, what was missing, what was surprising in a good way, suggested fix

7. **Final smoke run** — walk through `TUTORIAL.md` yourself end-to-end; fix anything that breaks. Don't add new features; only fix the existing ones. Anything that surfaces beyond a fix gets logged as a v2 issue.

## Acceptance criteria (the final v1 acceptance gate)

All eight from `docs/implementation_prompt.md`:

1. Each persona's CC instance can run `murmurent install`, then `murmurent dashboard` and see their populated dashboard
2. As @bob, claim SEA #1, work in `exp/2_alignment_count_matrix/`, run a fake analysis script, push to a personal branch
3. As @allie, run `murmurent sea examine 3`; the deliberation document is scaffolded; manually invoke bookworm and adversary in CC to fill in their sections; commit; run `murmurent sea conclude 3` and gather approvals
4. As any persona inside `dcis_sc_tutorial`, paste `1234-567-890-AB` into a prompt — PHI hook refuses with a clear message
5. As any persona, attempt to write to a file under `$WIGAMIG_LAB_VM_ROOT/raw/dcis_sc_tutorial/` — raw-data guard refuses
6. Inside CC in any persona's session, ask about reagents — CC calls `inventory_list` via the MCP and reports correctly
7. As @mike, run `murmurent dashboard` and see the PI compliance grid surface @cassie's missing TCPS 2 in red
8. All four repos visible at `https://github.com/hallettmiket/{murmurent, lab_mgmt, dcis_sc_tutorial, bbb_drug_screen}` with seed content committed

Plus:
- [ ] `TUTORIAL.md` walkthrough runs end-to-end without manual workarounds
- [ ] PR opened on `hallettmiket/murmurent` from `feat/phase-5-dashboard-tutorial`
- [ ] All five phase PRs merged to `main` of `hallettmiket/murmurent`

## After phase 5

The smoke test is ready to run with two real students. Use the issue template to log everything that comes up. Open issues label-tag with `smoke-test`. Anything that requires more than a one-line fix becomes a v2 design item.
