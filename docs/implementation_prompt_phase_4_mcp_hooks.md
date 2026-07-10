---
date: 2026-05-06
tags: [murmurent, prompt]
---

# Phase 4 prompt: MCP + remaining hooks

> Phase 4 of 5. Phases 1–3 shipped: full project + experiment + SEA + push + finalisation.
>
> Read first: `docs/implementation_prompt.md`, `docs/group_level.md`, `docs/cli_manual.md`, prior phase prompts.

## Goal

Inventory MCP works in CC; PHI pattern detection fires inside clinical projects; project context auto-injects into prompts; tool calls are audit-logged.

## Preconditions

- Phase 3 PR merged
- All seed data + finalisation flow in place
- Anthropic `mcp` Python SDK installable

## Deliverables

1. **Inventory items in lab-mgmt** at `inventory/<name>.md`
   - The six items per umbrella prompt with frontmatter per design (`name`, `lot`, `qty`, `unit`, `expiry`, `location`, `vendor`, `catalog_no`, `last_updated`, `status`, `protocols`)
   - Add as part of the seed script v4 (extends v3)

2. **Inventory MCP server** at `src/wigamig/mcp/inventory_server.py`
   - Uses Anthropic's `mcp` Python SDK
   - Tools: `inventory_list(filter)`, `inventory_show(name)`, `inventory_provision(plan_path)`, `inventory_set(name, fields)`, `inventory_add(...)`, `inventory_order(name)`
   - `inventory_provision` reads frontmatter `reagents:` from a notebook entry, intersects with inventory, returns gaps and expiring-soon
   - Permission check: `lab_manager` is hardcoded as `@mike` for v1 (real token-based auth is v2)
   - Independent test harness (without CC) that validates each tool

3. **PHI pattern detection hook** at `src/wigamig/hooks/phi_check.py`
   - PreToolUse and PostToolUse
   - Active when active project's CHARTER has `sensitivity: clinical`
   - Patterns:
     - OHIP-shaped: `\d{4}[ -]\d{3}[ -]\d{3}[ -]?[A-Z]{0,2}`
     - MRN-shaped: `MRN[-_]\w{4,}`
     - SIN-shaped: `\d{3}[ -]\d{3}[ -]\d{3}`
     - DOB-near-name: a date pattern within 50 chars of a name token
   - Pre: refuse outbound calls (Bash with curl/ssh, WebFetch, mcp__slack__*) when matches found
   - Post: redact matches in returned content
   - Test harness with realistic-looking fake strings

4. **Project-context injection hook** at `src/wigamig/hooks/context_inject.py`
   - UserPromptSubmit
   - Walks cwd to find active project; reads CHARTER (first paragraph), MEMBERS, current member's role, active SEAs (assigned to or from current user)
   - Prepends a `<system-reminder>` block to the user prompt

5. **Audit log hook** at `src/wigamig/hooks/audit.py`
   - PostToolUse
   - Append jsonl to `~/.claude/wigamig-audit/YYYY-MM-DD.log`: `ts`, `member`, `project`, `tool`, `args_summary`, `outcome`, `duration_ms`

6. **Hook + MCP installer**
   - `murmurent install --hooks` deploys all four hooks (raw_guard from phase 2 + the three new ones) to `~/.claude/hooks/` and registers in `~/.claude/settings.json` with the right `match` rules
   - Same command registers the inventory MCP under `mcpServers`
   - Idempotent (rerun safely)

## Acceptance criteria

- [ ] In CC inside `dcis_sc_tutorial`, asking "what reagents are low or expiring?" causes CC to call `inventory_list` via the MCP and report `4_oht` expired, `nebnext_kit` low, `livedead_stain` expiring soon
- [ ] In CC inside `dcis_sc_tutorial`, pasting `1234-567-890-AB` into a prompt is refused by the PHI hook with a message naming the pattern type
- [ ] Same paste in `bbb_drug_screen` (sensitivity: standard) — no refusal
- [ ] Submitting any prompt inside `dcis_sc_tutorial` injects a system reminder showing project name + role + active SEAs
- [ ] Tool calls written to `~/.claude/wigamig-audit/YYYY-MM-DD.log` as jsonl
- [ ] `murmurent install --hooks` succeeds idempotently
- [ ] PR opened on `hallettmiket/wigamig` from `feat/phase-4-mcp-hooks`

## Deferred to phase 5

- Dashboard
- Tutorial documentation
- Final smoke run
