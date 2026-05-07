---
date: 2026-05-06
tags: [wigamig, prompt]
---

# Phase 3 prompt: Push and SEA

> Phase 3 of 5. Phases 1–2 shipped: Python package, CLI, agents, repos, projects, experiments, ingest, raw-data guard.
>
> Read first: `docs/implementation_prompt.md`, `docs/group_level.md`, `docs/cli_manual.md`, prior phase prompts.

## Goal

Push to personal branches, open PRs for finalisation, run the SEA lifecycle, and complete a deliberation through the finalisation choreography.

## Preconditions

- Phase 2 PR merged
- Both project repos exist with seeded experiments
- Raw-data guard registered (manually or via test harness)

## Deliverables

1. **Push mechanics**
   - `wigamig push <project>` — commit current changes, push to `member/<handle>/<topic>` branch (direct, no review)
   - `wigamig push <project> --finalize` — open PR via `gh pr create` from personal branch to `main`
   - `wigamig push <project> --refined <exp>` — recompute SHA-256 for files in `$WIGAMIG_LAB_VM_ROOT/refined/<project>/<exp>/`, update notebook frontmatter (`refined_data`, `checksums`), push to personal branch
   - `wigamig pull <project>`

2. **SEA registry and operational verbs**
   - SEA registry at `<project>/seas/<id>.md` with frontmatter (id, from, to, kind, description, status, claimed_at, completed_at, delivery)
   - `wigamig sea request --to <m> --kind <k> --description <d>` — file an SEA, push to project
   - `wigamig sea list [--mine | --incoming | --outgoing]`
   - `wigamig sea claim <id>`, `wigamig sea complete <id> --delivery <path>`, `wigamig sea decline <id> --reason <r>`

3. **Finalisation choreography**
   - Deliberation document templates at `<project>/deliberations/sea/<id>.md`, `<project>/deliberations/exp/<experiment>.md`, `<project>/deliberations/project.md`
   - Template structure per design: agent contributions section (one per common agent in the squad's roster — for v1 use the eight registered agents), member reflections, group oracle context, attempted statement (flexible), caveats and dissent, approval log
   - `wigamig sea examine <id>` — scaffolds the deliberation doc with empty agent-contribution sections; sets `analysis_status: examined` after the squad fills sections (does NOT auto-invoke agents — students invoke them manually in their CC sessions)
   - `wigamig sea conclude <id> [--statement <path>]` — validates required sections present, prompts lead for the attempted statement, opens PR for squad approvals; sets `analysis_status: concluded` on merge
   - `wigamig finalize <scope> <id>` — umbrella that runs examine then prompts conclude; `<scope>` ∈ `sea`, `experiment`, `project`
   - `wigamig sea reopen <id>` — re-opens a concluded deliberation

4. **Bot review action** (simulated)
   - GitHub Action workflow file in each project repo (`.github/workflows/adversary_stub.yml`) that on PR open posts a fixed comment representing a stub adversary review
   - Real adversary integration is v2

5. **Seed script v3** extends v2
   - Pre-populate the six SEAs per umbrella prompt (states: claimed/in-progress, requested/unclaimed, complete/awaiting examine, declined, complete/finalised)
   - Write deliberation docs for SEAs in `awaiting examine` (partial) or `finalised` (complete) state

## Acceptance criteria

- [ ] `WIGAMIG_USER=bob wigamig sea list --incoming` shows SEAs assigned to bob
- [ ] `WIGAMIG_USER=allie wigamig sea list --outgoing` shows SEAs filed by allie
- [ ] `wigamig sea examine 3` (as @mike) scaffolds the deliberation doc with empty agent sections
- [ ] `wigamig sea conclude 3 --statement <path>` opens PR for approvals
- [ ] `wigamig push dcis_sc_tutorial --finalize` opens a real PR on GitHub
- [ ] PR triggers the simulated bot review comment
- [ ] PR opened on `hallettmiket/wigamig` from `feat/phase-3-push-sea`

## Deferred to phase 4

- Inventory MCP server
- PHI / context / audit hooks
- `wigamig install --hooks` deployer
