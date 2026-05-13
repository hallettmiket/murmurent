# Architecture diagrams

Hand-tuned Graphviz sources for the wigamig system. Two diagrams live here:

| File | What it shows |
|---|---|
| [`system_map.dot`](system_map.dot) | One-page system map: identity & launch, the three tiers (Commons / Guilds / Project namespaces), per-project data plane, and external services (GitHub, Slack, MCP). |
| [`install_modes.dot`](install_modes.dot) | Local vs `biodatsci` install side-by-side: where the Obsidian vault, project repo, and `/data/lab_vm/{raw,refined}` live in each mode, plus the SSH boundary. |

## Rendering

```bash
bash scripts/render_diagrams.sh
```

The script renders every `.dot` source in this directory to SVG (for the
web / dashboard) and 180-DPI PNG (slide-ready).

Requires Graphviz:

| Platform | Install |
|---|---|
| macOS | `brew install graphviz` |
| Ubuntu (biodatsci) | `sudo apt install graphviz` |

## Editing

Diagrams use the Hallett-Lab palette:

| Use | Colour |
|---|---|
| Western purple (primary) | `#4F2683` |
| Western purple (deep) | `#201436` |
| Tiger orange (accent) | `#F0A757` |
| Paper / cream | `#FAF8F5` |
| Cream-warm | `#F1ECE3` |
| Ink | `#1A1A1A` |
| Muted text | `#5B5B5B` |

Fonts: `EB Garamond` for labels, `Courier Prime` for code-like edge labels.
Both fonts are referenced by name only — the renderer falls back if they
aren't installed, but the slides look best with both present (`brew install
font-eb-garamond font-courier-prime` via `homebrew/cask-fonts`).
