# The dashboard

The dashboard is Murmurent's local visual control surface. It provides a
single overview at three levels: your **session on this machine** (your
repositories and their readiness, your registered machines, and your
outstanding work), your **lab** (its members, its projects, the Oracle,
and the daily lab notebook), and, for a registrar, your **centre** (its
registered labs and cores and any pending join requests). Everything the
dashboard shows is also available from the command line and from
plain-English requests to an agent; the dashboard presents it together and
lets you act on it through the interface rather than by typing a command.

Launch it with:

```bash
murmurent dashboard --hifi
```

It opens in your browser at `http://127.0.0.1:8770/`. The dashboard is
read-mostly: most panels display state, and a few offer buttons for common
actions (such as adopting a repository or adding a machine), each of which
has an equivalent `murmurent` command.

The dashboard binds to loopback, so each machine's dashboard is visible
on that machine alone. To view a remote server's dashboard from your
laptop, use an SSH port-forward, either by hand or via
`murmurent dashboard --tunnel you@host`; see
[Remote dashboard access](remote_dashboard.md) for the full recipe
(including first-time server setup and the VS Code Remote-SSH
auto-forward route).

## The dashboard icon

You probably have it already. `murmurent install` creates a **Murmurent
Dashboard** icon that starts the dashboard and opens it in your browser:

- **Mac:** in your Applications folder. Drag it to your Dock for one-click
  access.
- **Linux:** in your applications menu. Search for "murmurent".
- **Windows:** not available yet. Start the dashboard with the command above.

To make the icon again (after moving or reinstalling murmurent), or to remove it:

```bash
murmurent launcher            # create it, replacing any earlier one
murmurent launcher --remove   # delete it
```

`murmurent doctor` says whether the icon is there. The icon opens
`http://127.0.0.1:8770/`, starting the dashboard first if it is not already
running.

## What the dashboard shows

At a high level, it shows:

- your **repos** and their readiness (Repos panel),
- your **projects** (Projects panel),
- your **machines/hosts** (Machines panel),
- your lab's **members**, and
- your **Oracle** and daily **lab-notebook** panels.

**Which murmurent is running.** The top bar says which code the dashboard
runs, for example `running murmurent_dev · main @ 787faca` for the
development copy, or `running release v2026.10.0` for an installed release.
Hover over it for the folder. If it names a different copy than the one you
just updated, restart the dashboard from that copy.

**Stopping the dashboard.** Closing the browser window does not stop the
dashboard: it keeps running in the background, especially when the dashboard
icon started it. To stop it, press **⏻ stop dashboard** in the top bar, or run
`murmurent dashboard --stop`. Start it again with the icon or
`murmurent dashboard --hifi`. On a lab server where the system runs the
dashboard as a service, the button is hidden, because the service would start
it again.

Most dashboard actions have a `murmurent ...` CLI twin, and vice versa, so
you can work from whichever you prefer. A few concrete pairs:

| Dashboard action | CLI equivalent |
|---|---|
| Repos panel, **↑ adopt** button | `murmurent repo adopt` |
| Machines panel, **edit this machine** | edit `~/.murmurent/machine.yaml` |
| **New Project** flow | how projects get created (created here; see [`ready_vs_projects.md`](ready_vs_projects.md) and [`project_intra.md`](project_intra.md)) |

The Machines panel is **this-machine-only** (issue #94): it edits the current
machine and shows your other machines read-only (mirrored through the personal
vault). There is no "add machine / scan an SSH host" button — to view another
machine, open **its own** dashboard over a tunnel (see
[`remote_dashboard.md`](remote_dashboard.md)). `murmurent host add` still exists
as a CLI-only way to register a `--tunnel` alias.

See [`ready_vs_projects.md`](ready_vs_projects.md) for what "repo readiness"
means, and [`project_intra.md`](project_intra.md) for how a project is
created.
