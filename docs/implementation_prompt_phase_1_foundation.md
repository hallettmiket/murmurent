---
date: 2026-05-06
tags: [murmurent, prompt]
---

# Phase 1 prompt: Foundation

> Phase 1 of 5 in the murmurent smoke-test tutorial v1 build.
>
> Read first: `docs/implementation_prompt.md` (umbrella brief), `docs/group_level.md` (full design), `docs/cli_manual.md` (CLI surface).
>
> If anything below conflicts with the design docs, the docs win — flag the conflict.

## Goal

Stand up the Python package, CLI skeleton, agent registry, frontmatter and repo-discovery utilities, and the foundation of the seed script (lab-management repo with member files).

## Preconditions

- The `~/repos/wigamig/` repo exists with `docs/` populated.
- `gh auth status` is healthy against the `hallettmiket` org. If not, stop and ask the user to run `gh auth login`.

## Deliverables

1. **Python package skeleton**
   - `pyproject.toml` (Python 3.12, uv)
   - `src/murmurent/` package
   - Dev deps: pytest, black, isort
   - `src/murmurent/cli.py` with `click`
   - `murmurent --help` prints the full command tree from `cli_manual.md` (most commands stub: `click.echo("not yet implemented in v1")`)
   - `tests/test_cli_help.py` smokes the help output

2. **Agent registry** at `agents/`
   - Port the seven agents from `~/repos/generic_cc/agents/*.md`
   - Add `security_guard.md` (new — guardian persona that scans diffs for secrets and restricted paths)
   - Each agent's frontmatter must include the new fields: `freeze` (`frozen` | `personal`), `required_tools` (list), `denied_tools` (list), `defaults` (block per design)
   - The `defaults` block uses the controlled vocabulary in `docs/group_level.md` "Tool preferences"

3. **Core utilities** at `src/murmurent/core/`
   - `repo.py` — walk cwd to find active project (marker: `CHARTER.md`); read `MEMBERS`; locate lab-management repo at `~/repos/lab_mgmt`
   - `frontmatter.py` — parse YAML frontmatter; validate required fields per the design
   - `identity.py` — resolve current user (env var `MURMURENT_USER` preferred for testing; fall back to `gh api user`)
   - Tests for each

4. **`murmurent agent list`** working — reads `agents/*.md`, prints name + freeze flag in a table

5. **Seed script v1** at `scripts/seed_tutorial.py` (idempotent)
   - Creates `~/repos/lab_mgmt/` locally
   - Creates `hallettmiket/lab_mgmt` private GitHub repo via `gh repo create --private`
   - Member profile files for `mike`, `allie`, `bob`, `cassie` at `members/<handle>.md` (frontmatter: handle, role, status, certifications)
   - Generates dummy age key pairs per persona; commits public keys to `keys/<handle>.age`; private keys saved locally outside the repo (e.g. `~/.config/wigamig/keys/<handle>.age-private`)
   - Empty `inventory/`, `projects/`, `dashboards/`, `audit/`, `roles/`, `onboarding/` directories with `.gitkeep`
   - Initial commit and push

## Acceptance criteria

- [ ] `murmurent --help` prints the full command tree
- [ ] `pytest` passes
- [ ] `murmurent agent list` lists eight agents with freeze flags
- [ ] `python scripts/seed_tutorial.py` completes without error and creates `lab_mgmt` locally and on GitHub
- [ ] `black` and `isort` clean
- [ ] PR opened on `hallettmiket/murmurent` from a `feat/phase-1-foundation` branch

## Deferred to phase 2

- Project + experiment commands
- The two project repos
- Inventory items
- Hooks
- MCPs
