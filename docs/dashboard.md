# The dashboard

Everything Murmurent does is available from the command line and from
plain-English requests to an agent. Murmurent also ships a local dashboard
that presents the same information and lets you act on it through the
interface rather than by typing a command.

Launch it with:

```bash
murmurent dashboard --hifi
```

It opens in your browser at `http://127.0.0.1:8770/`. The dashboard is a
local, read-mostly control surface for your Murmurent state: it shows what
the CLI can show, and lets you act on it. (The mac and Linux desktop
launchers and the server systemd unit all start it with this same
command.)

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
