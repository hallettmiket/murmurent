# Inter-group (cross-lab) projects

A project's basics (the definition, the certificate model, and the full
command reference) live on [`project_intra.md`](project_intra.md). This page
covers what's different when project members span labs.

The simplest way to create a project, whether intra- or inter-group, is the
dashboard's **New Project** flow: it walks through the steps below in a form,
and it enforces the shared-workspace requirement for cross-lab projects for
you. The command-line walkthrough here shows what the dashboard does
underneath. See [Firing up the dashboard](dashboard.md).

## An inter-group project (members span labs)

Allie now wants `spatial_atlas` with Carlos, who is in the **Xia lab**, a
different group, a different Slack workspace.

**1. The prerequisite.** She adds `@carlos` to the member list. His key lives
on the Xia lab's roster instead of hers, so the form requires one additional
field, and if she omits it, creation halts:

> project members span multiple groups: the groups must decide on a shared
> Slack workspace before an inter-group project can be created.

This is deliberate: the shared workspace is where the project channel lives
and where certificates are DM'd, so it must exist before the project does.

**2. The groups decide.** The two PIs agree which of their labs' registered
workspaces hosts the project (say the Rao lab's): what matters is that
the workspace's bot token is on file. (A dedicated stand-alone workspace works
too, once it's registered as a group with the registrar: `group-slack-setup`
refuses unregistered names.)

```bash
# one-time, on the machine that will provision the project:
murmurent group-slack-setup <workspace>
# token lands at ~/.config/murmurent/groups/<workspace>/slack-token
```

Allie enters the workspace id in the form and the proposal goes through.
(The check re-runs at approval, so it fails closed even if rosters changed
in between.)

**3. Certifying an outside member.** Carlos's key lives only on the Xia
lab's roster, so Allie has none for him on record. He runs, on his own
machine:

```bash
murmurent enroll --project spatial_atlas
```

and DMs Allie the JSON it prints. She pastes it into the **issue** dialog
(or runs `murmurent project-add-member @carlos --project spatial_atlas
--enrollment carlos.json`). His card is signed by Allie, chained to *her*
lab's root (anyone in the centre can verify it) and DM'd back through the
shared workspace. Subsequent additions take a single action: his key is now on
record.

**4. Repos in two places.** This is supported. Each repo in the project
carries its own remote, so the code repo can push to `hallettmiket/...` while
the analysis repo pushes to the Xia lab's org. (Automatic collaborator sync
covers the primary repo; extra-org repos are managed manually for now.)
