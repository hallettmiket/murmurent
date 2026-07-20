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

It opens in your browser at `http://127.0.0.1:8770/`. The dashboard is a
local, read-mostly control surface for your Murmurent state: it shows what
the CLI can show, and lets you act on it.

## Installing a desktop launcher (menu icon)

Rather than typing the command each time, you can install a desktop icon
that starts the dashboard and opens it in your browser with one click. Run
the script for your platform once, after cloning or reinstalling Murmurent.

**macOS:**

```bash
bash scripts/create_mac_app.sh
```

This creates `~/Applications/Murmurent Dashboard.app`, which appears in
Launchpad and Spotlight. Pass `--dest <dir>` to write the bundle
elsewhere.

**Linux:**

```bash
bash scripts/create_linux_launcher.sh
```

This writes a freedesktop `.desktop` entry to
`~/.local/share/applications/murmurent-dashboard.desktop`, so "Murmurent
Dashboard" appears in the applications menu. The entry follows the XDG
specification and shows up on Cinnamon, GNOME, KDE, XFCE, and MATE.

Both launchers start the dashboard on port 8770 (starting it only if it is
not already running) and then open `http://127.0.0.1:8770/`. They run the
same `murmurent dashboard --hifi` command shown above.

## What the dashboard shows

At a high level, it shows:

- your **repos** and their readiness (Repos panel),
- your **projects** (Projects panel),
- your **machines/hosts** (Machines panel),
- your lab's **members**, and
- your **Oracle** and daily **lab-notebook** panels.

Most dashboard actions have a `murmurent ...` CLI twin, and vice versa, so
you can work from whichever you prefer. A few concrete pairs:

| Dashboard action | CLI equivalent |
|---|---|
| Repos panel, **↑ adopt** button | `murmurent repo adopt` |
| Machines panel, add a machine | `murmurent host add` |
| **New Project** flow | how projects get created (created here; see [`ready_vs_projects.md`](ready_vs_projects.md) and [`project_intra.md`](project_intra.md)) |

See [`ready_vs_projects.md`](ready_vs_projects.md) for what "repo readiness"
means, and [`project_intra.md`](project_intra.md) for how a project is
created.
