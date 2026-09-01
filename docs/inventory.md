# Inventory and shared resources (work in progress)

!!! warning "Work in progress"
    The inventory model described here is partially implemented (the
    `inventory` MCP server exists) but is still under active development.
    The schema and mechanisms below describe the intended design.

Inventory is stored as semi-structured markdown in the lab-management
repository. It is **group-scoped**, never project-scoped: every member
needs access regardless of which project they are working on. Markdown with
frontmatter carries catalog photos, vendor notes, and prep procedures, is
versioned in git, and can be queried from Claude Code, in the same
toolchain as everything else.

## Layout

One markdown file per reagent or kit:

```
<lab-mgmt-repo>/
├── inventory/
│   ├── anti_cd31.md
│   ├── 4_oht.md
│   └── ...
└── ...
```

## Schema (frontmatter)

| Field | Type | Notes |
|---|---|---|
| `name` | str | Canonical name |
| `lot` | str | Current lot number |
| `qty` | number | Current quantity |
| `unit` | str | mg, mL, units, vials |
| `expiry` | ISO date | YYYY-MM-DD |
| `location` | str | Freezer / shelf / box |
| `vendor` | str | |
| `catalog_no` | str | |
| `last_updated` | ISO date | Auto-set on edit |
| `status` | enum | `in_stock` / `low` / `out` / `expired` / `on_order` |
| `protocols` | list[wikilink] | Protocols that consume this reagent |

Body holds free-form notes: vendor link, MSDS, prep procedure, photos of
label or catalog page.

## Inventory MCP

The `provision` operation, and inventory access in general, are exposed as
an **MCP server** (the `inventory` MCP). Any agent in any member's Claude
Code instance can call its tools:

- `inventory_list(filter)`: list reagents matching a filter (e.g. `--low`,
  `--expiring 30`).
- `inventory_show(name)`: return frontmatter + body of one reagent.
- `inventory_provision(plan_path)`: compute `plan ∩ inventory`, report gaps
  and expiring lots.
- `inventory_set(name, fields)` (`lab_manager` only): update fields,
  auto-bump `last_updated`.
- `inventory_order(name)` (`lab_manager` only): open an order issue in the
  lab-management repo.

The MCP wraps the markdown files. Permissions are enforced by the MCP
server (read for the whole group, write for the `lab_manager` role); the
lab-management repo's branch protection is the second line of defence for
write paths that bypass the MCP.

## `last_updated` mechanism

`last_updated` is auto-set regardless of how the file was edited, via three
redundant layers:

1. the **inventory MCP** sets it on every write (primary path; covers
   programmatic edits by agents);
2. a **pre-commit hook** in the lab-management repo updates `last_updated`
   for any staged `inventory/*.md` file (covers direct edits via Obsidian,
   vim, or an IDE);
3. a **GitHub Action on push** does the same (a backstop for edits made
   through the GitHub web UI, which does not run pre-commit hooks).

The field is reliable regardless of the editing tool.

## Permissions

- Read: every group member.
- Write: the `lab_manager` role only (enforced by the inventory MCP and by
  branch protection on the lab-management repo).
