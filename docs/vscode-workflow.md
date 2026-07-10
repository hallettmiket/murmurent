# VSCode workflow

The murmurent repo ships a launcher + workspace config so VSCode opens
in a consistent 4-quadrant layout with live agent reporting.

## Opening a project

```bash
scripts/open_wigamig.sh                   # opens murmurent itself
scripts/open_wigamig.sh ~/repos/<other>   # opens another repo
```

The launcher (macOS only) enumerates displays via
`AppKit.NSScreen`. If a second monitor is attached, VSCode opens
there; otherwise on the laptop screen. Either way the window is
sized to 80% of the chosen display, centred. Subsequent opens
restore VSCode's persisted layout — **arrange the quadrants once
and they stick**.

The dashboard's *open workspace* button calls the same launcher
(see [`src/wigamig/dashboard/server.py`](../src/wigamig/dashboard/server.py)
`workspace_launch` local branch).

## Quadrant layout

| Pane | Contents |
|------|----------|
| TL | Claude Code (VSCode extension) |
| TR | Editor area |
| BL | tmux shell |
| BR | `tail -F ~/.wigamig/agents.log` — live subagent reporter |

One-time setup per project:

1. Open four terminals (Cmd+Shift+`); they open in the editor area
   thanks to `terminal.integrated.defaultLocation: editor`.
2. Drag them into a 2×2 split.
3. In BL: any tmux shell.
4. In BR: `tail -F ~/.wigamig/agents.log`.
5. VSCode persists this editor-group state per folder.

## Title bar + chrome

Each project's `.vscode/settings.json` (written by
`bootstrap_local`) wires:

- `window.title` → `Murmurent — <repo>  ·  <active editor>  ·  <dirty>`
- `workbench.activityBar.location` → `end` (right side)
- `workbench.sideBar.location` → `right`
- `terminal.integrated.defaultLocation` → `editor`

VSCode has no native bold/large title font (that's OS chrome); the
text is what we can control.

## Live agent reporter (BR pane)

User-global hooks in `~/.claude/settings.json` invoke
[`scripts/wigamig_log_agent_event.sh`](../scripts/wigamig_log_agent_event.sh)
on:

- `PreToolUse(Agent)` → writes `<agent>: starting — <description>`
  in a deterministic colour per agent.
- `SubagentStop` → writes `<agent>: <verdict>` (first line of the
  agent's reply, ≤200 chars).

BR pane runs `tail -F ~/.wigamig/agents.log`. Same log across every
project on this machine, so you see all subagent activity in one
place.

**Known limit**: CC subagents return *one final message*, not a
live stream of their thinking. The reporter shows agent start/end
boundaries with the verdict line, not granular progress. That's a
CC architecture constraint, not a missing feature.

## Tmux copy-paste

`~/.tmux.conf` includes:

```tmux
set -g mouse on
set -g set-clipboard on
bind -T copy-mode    MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy"
bind -T copy-mode-vi MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy"
bind -T copy-mode    y                 send -X copy-pipe-and-cancel "pbcopy"
bind -T copy-mode-vi y                 send -X copy-pipe-and-cancel "pbcopy"
```

Drag-to-select inside a tmux pane copies to the system clipboard.
Cmd+V pastes anywhere.
