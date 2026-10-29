# VSCode workflow

The Murmurent repo ships a launcher + workspace config so VSCode opens
in a consistent 4-quadrant layout with live agent reporting.

!!! note "Working on a remote server through VS Code?"
    This page covers the local 4-quadrant editor layout. To view a
    remote server's dashboard, including the VS Code Remote-SSH
    auto-forward route, see
    [Remote dashboard access](remote_dashboard.md).

## Opening a project

```bash
scripts/open_murmurent.sh                 # opens murmurent itself
scripts/open_murmurent.sh ~/repos/<other> # opens another repo
```

The launcher (macOS only) enumerates displays via
`AppKit.NSScreen`. If a second monitor is attached, VSCode opens
there; otherwise on the laptop screen. Either way the window is
sized to 80% of the chosen display, centred. Subsequent opens
restore VSCode's persisted layout: arrange the quadrants once
and they persist across opens.

The dashboard's *open workspace* button calls the same launcher
(see [`src/murmurent/dashboard/server.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/dashboard/server.py)
`workspace_launch` local branch).

## Quadrant layout

| Pane | Contents |
|------|----------|
| TL | Claude Code (VSCode extension) |
| TR | Editor area |
| BL | tmux shell |
| BR | `tail -F ~/.murmurent/agents.log`: live subagent reporter |

One-time setup per project:

1. Open four terminals (Cmd+Shift+`); they open in the editor area
   thanks to `terminal.integrated.defaultLocation: editor`.
2. Drag them into a 2×2 split.
3. In BL: any tmux shell.
4. The BR `tail -F ~/.murmurent/agents.log` starts **automatically**: a
   murmurent-ready repo carries a `.vscode/tasks.json` `agents.log` task with
   `runOn: folderOpen` (and `task.allowAutomaticTasks: on`), so opening the
   folder drops you straight into the live subagent feed — no manual `tail`.
   Drag that terminal into the BR quadrant.
5. VSCode persists this editor-group state per folder.

## Title bar + chrome

Each project's `.vscode/settings.json` (written by
`bootstrap_local`) wires:

- `window.title` → `Murmurent — <repo>  ·  <active editor>  ·  <dirty>`
- `workbench.activityBar.location` → `end` (right side)
- `workbench.sideBar.location` → `right`
- `terminal.integrated.defaultLocation` → `editor`

VSCode has no native bold/large title font (that is controlled by the
operating system's window chrome); only the text can be configured.

## Live agent reporter (BR pane)

User-global hooks in `~/.claude/settings.json` invoke
[`scripts/murmurent_log_agent_event.sh`](https://github.com/hallettmiket/murmurent/blob/main/scripts/murmurent_log_agent_event.sh)
on:

- `PreToolUse(Agent)` → writes `<agent>: starting — <description>`
  in a deterministic colour per agent.
- `SubagentStop` → writes `<agent>: <verdict>` (first line of the
  agent's reply, ≤200 chars).

BR pane runs `tail -F ~/.murmurent/agents.log`. Same log across every
project on this machine, so you see all subagent activity in one
place.

### Spoken verdicts (macOS)

The same hook can read each agent's verdict aloud, one voice per agent,
using the `say` command that ships with macOS. Nothing leaves the machine
and no account is needed. The main session never speaks: only a dispatched
subagent reaches this branch of the hook.

Turn it on by creating the file `~/.murmurent/speak`:

```bash
touch ~/.murmurent/speak
```

An empty file uses the default voices below. To change one, add a line
`<agent> <voice>`; voice names may contain spaces. `say -v '?'` lists every
voice installed on your Mac, and `say -v Moira "hello"` auditions one.

| Agent | Voice | | Agent | Voice |
|---|---|---|---|---|
| adversary | Tessa | | scribe | Reed |
| conscience | Moira | | lawyer | Aman |
| judge | Daniel | | millwright | Eddy |
| bookworm | Karen | | centre_millwright | Rocko |
| oracle | Samantha | | registrar | Sandy |
| lab_oracle | Shelley | | security_guard | Rishi |
| blacksmith | Fred | | artist | Flo |
| teacher | Grandpa | | (any other) | the system voice |

Only the headline is read: the first sentence of the agent's first line,
with web addresses, file paths, DOIs and markdown stripped out, since
those are for reading, not listening. Each verdict is spoken once, and
verdicts queue rather than talk over each other. The hook returns at once,
so speech never holds Claude Code up.

To hear the natural English voices one after another, each introducing
itself:

```bash
for v in Daniel Karen Moira Samantha Tessa Rishi Aman Kathy Fred Albert Ralph Reed Flo Eddy Rocko Sandy Shelley Grandma Grandpa Junior; do say -v "$v" "Hello, I am $v"; done
```

To mute: delete the file, or set `MURMURENT_SPEAK=0` in the shell that
starts Claude Code for one session. `MURMURENT_SPEAK=1` turns it on
without the file. On Linux, where there is no `say`, the setting is
ignored.

**Known limit**: CC subagents return one final message rather than a
live stream of their thinking. The reporter shows agent start/end
boundaries with the verdict line rather than granular progress. This
is a constraint of the CC architecture.

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
