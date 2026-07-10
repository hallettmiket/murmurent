# murmurent — hi-fi dashboard handoff

This package contains the design spec for the redesigned murmurent dashboard. It is intentionally framework-agnostic — your job is to wire it into the existing Streamlit (or successor) app. Tokens, components, and data shape are all explicit so a port to React/HTMX/Streamlit-with-custom-components is a 1-to-1 mapping.

## Files in this handoff
| file | role |
|---|---|
| `Murmurent Dashboard Hi-Fi.html` | the source of truth — open in a browser to see the live design |
| `Murmurent Dashboard Wireframes.html` | exploration phase — 4 layout directions; "Command Bridge" was selected |
| `hifi-data.jsx` | mock data shape — mirror this in `murmurent.core.dashboard.DashboardSnapshot` |
| `hifi-app.jsx` | top-level layout + all section panels |
| `hifi-notebook.jsx` | the lab-notebook entry view (Obsidian-style daily notes) |
| `HANDOFF.md` | this file |

## Direction picked: **Command Bridge**
Dense, single-page, Bloomberg-style. No drilling required for the most-used signals. Persona toggle (`member` ↔ `PI`) reshapes the attention queue and compliance scope without changing layout.

## Design tokens
Locked to Western University brand. Do not invent new colors.

```css
--purple:        #4F2683;   /* Western purple — primary brand */
--purple-deep:   #201436;   /* deep header / footer */
--purple-soft:   #6F4DA8;
--tiger:         #F0A757;   /* Tiger orange — single accent */
--tiger-deep:    #C97F2A;
--paper:         #FAF8F5;   /* page bg */
--paper-2:       #F1ECE3;   /* card hover / fill */
--card:          #FFFFFF;
--rule:          #E0DAD0;
--rule-strong:   #C7BFB1;
--ink:           #1A1A1A;
--muted:         #5B5B5B;
--green:         #4F6B3A;   /* success / compliant */
--red:           #B23A2B;   /* expired / overdue */

--serif: "EB Garamond", Georgia, serif;   /* keep — lab's existing font */
--mono:  "Courier Prime", "IBM Plex Mono", Menlo, monospace;
```

## Layout regions (top → bottom)
1. **Brand bar** — purple band, tiger underline, "Hallett Lab · Schulich · Western University". Right side: signed-in handle + lab.
2. **Command bar** — `murmurent` wordmark, global search (`⌘K` / `/`), persona toggle (`V`).
3. **Stat strip** — 5 KPI cards: attention, SEAs/week, compliance, inventory, notebook cadence.
4. **Row 1**: Attention queue (5/12) + SEAs in/out tabs (7/12).
5. **Row 2**: Compliance heatmap (7/12) + Projects table (5/12).
6. **Row 3**: Group · Inventory · Activity sparkline · Daily notes rail (3/12 each).
7. **Row 4**: Notebook entry (full bleed).
8. **Footer** — purple, includes the existing land acknowledgement.

## Persona behavior
- **member** view: attention queue is *my* overdue SEAs / expiring certs; compliance heatmap shows projects I'm in.
- **PI** view: attention queue surfaces lab-wide blockers (peer cert lapses, project backlogs, new joiners needing access); compliance heatmap shows the full lab.
- Toggle is in the command bar AND the `V` keyboard shortcut.

## Keyboard shortcuts (implement)
| key | action |
|---|---|
| `/` or `⌘K` | focus search |
| `V` | swap persona (member ↔ PI) |
| `?` | shortcut help (future) |
| `g p` / `g s` / `g c` | jump to projects / SEAs / compliance (future) |

## Data contract (`DashboardSnapshot`)
See `hifi-data.jsx`. Required top-level keys:
```
today           { iso, pretty, weekday, week }
member, pi      { handle, name, role }
attention[]     { sev: red|amber|ok, kind, id, text, project, age, actions[[label,tone]] }
stats           { attention{red,amber,ok}, seas{...}, compliance{...}, inventory{...}, notebook{...} }
spark[]         12 weekly counts, oldest first
projects[]      { name, sens, lead, choreo, members, openSeas, lastActivity }
peers[]         { handle, name, role, tcps: ok|expiring|missing, shared }
seas[]          { id, dir: in|out, state: requested|claimed|complete|examined, kind, who, project, desc, age }
heatmap         { members[handles], rows[{project,sens,cells[ok|exp|amb|mis|na]}] }
inventory       { expired[], low[], expiring[], stock{reagents:[a,b], kits:[a,b]} }
notifs[]        { time, text }
notebook        { folder, days[{iso,weekday,word_count,has_entry,is_today}], today{...}, yesterday_excerpt{...} }
```

The `notebook.today.content` array is a discriminated union (`kind: h4|p|task|list|blockquote|code`). The `[[wikilink]]` syntax in `p` blocks should be parsed and rendered as internal links — same as Obsidian.

## Notebook integration
The dashboard expects an Obsidian-style daily-notes folder at `<repo>/lab-notebook/YYYY-MM-DD.md`. Server-side: parse front-matter for `tags`, `links_seas`, `links_exp`. Block parsing only needs to support: H4, paragraph (with `[[wikilink]]`), task `- [ ]` / `- [x]`, list, blockquote, fenced code. Render path = pure markdown → block tree → existing components. Make the entry editor a separate concern; the dashboard panel is read-only with an "edit" button that opens the markdown file in their preferred editor.

## SEA inline actions
The action button on each SEA row depends on its state and direction:
| state | incoming → action | outgoing → action |
|---|---|---|
| `requested` | **claim** (primary) | wait |
| `claimed` | **complete** (tiger) | track |
| `complete` | **accept** (primary) | track |
| `examined` | **review** | accept |

Each row also exposes `⋯` for: reassign, decline, comment, archive. Hitting an action should optimistically update the row and post to the SEA endpoint.

## Compliance heatmap states
- `ok` (green ✓) — TCPS_2 + project-specific cert valid
- `amb` (amber ~) — expires < 30d
- `exp` (red !) — expired
- `mis` (red ? dashed) — required cert missing entirely
- `na` (muted ·) — not on this project

Clicking a cell should open a side drawer with the member's full cert list and "nudge" / "grant access" actions (PI only).

## Things deliberately NOT in this design
- No emoji status badges (the old prototype had several — kill them)
- No big charts. Sparkline only. Reasoning: throughput trends fit in 36px; everything else is a list.
- No left sidebar nav. The top stat strip + same-page scroll covers all sections; deep links go to `/sea`, `/projects/<name>`, `/notebook/<date>` etc. as full pages.

## Resolved decisions
1. **Notebook storage** — per-user. Read from each user's home dir (`~/lab-notebook/YYYY-MM-DD.md`). No shared vault. The dashboard panel renders the signed-in user's own notes; PI persona does NOT cross-read peers' notebooks.
2. **Compliance `mis` rule** — blocks **clinical projects only**. A missing TCPS_2 does not gate `standard`-sensitivity projects. The heatmap should still surface `mis` cells on standard rows as a warning, but the access enforcement layer only refuses for `sens === "clinical"`.
3. **PI persona** — auto-detect from group membership. If the signed-in user is the PI of any project, expose the persona toggle and default it to whichever was last used (localStorage). Non-PI users never see the toggle. No explicit admin override.

## Implementation notes
- Mobile is **not** in scope. Lab members work on workstations. Min target: 1280×800.
- The mock `hifi-data.jsx` is shaped to drop straight into a `dashboard.json` endpoint. Strongly recommend implementing `GET /api/dashboard` returning this shape and rendering client-side rather than re-doing it in Streamlit's render-on-rerun model.
- `EB Garamond` + `Courier Prime` are both on Google Fonts — preconnect + display=swap is in the head.

## Land acknowledgement
Already in the footer. Keep verbatim — it's not a design element, it's a commitment.
