# Creating a project — two vignettes

A murmurent **project** is three sets, not a folder:

- a set of **repos** — *existing* clones picked from your machines' repo
  folders (`~/repos` etc.; the folders themselves are configured on the
  Machines panel under *Repo location*). Creating a project never creates a
  repo — clone or `git init` it first, then group it into a project;
- a set of **machines** (your laptop, the lab VM, …),
- a set of **members** — and membership is *cryptographic*: each member holds
  a signed **project certificate** they can prove, not just a name on a list.

The person who creates the project is its **lead**. At creation the PI signs
the lead a one-time *delegation card*; from then on the lead — and only the
lead — signs members in and out with their own key. The PI approves that the
project should exist; the lead controls who's in it.

Every project also gets a **private Slack channel**: certificates are DM'd
through Slack, members are invited when they join and removed when they leave.

A project is a different, bigger thing than a repo simply being
**murmurent-ready** (having the commons agents wired in via `murmurent repo
adopt`) — readiness is plumbing a repo needs before it's useful in a
project, not a project itself. See
[`ready_vs_projects.md`](ready_vs_projects.md) if you're not sure which one
you're looking at.

---

## Vignette 1 — An intra-group project (everyone is in your lab)

Allie (a member of the Hallett lab) wants to start `dcis_17` with Bob. She
already has the two repos that make up the work — `dcis_code` and
`dcis_manuscript` — cloned under `~/repos` on her laptop.

**1. Propose.** On her dashboard, Allie clicks **＋ new project** and picks:

- *name*: `dcis_17`
- *members*: `@allie`, `@bob` (from the lab roster dropdown)
- *machines*: her laptop + `lab-server`
- *repos*: `dcis_code` + `dcis_manuscript`, selected from the clones murmurent
  already found in her repo folders — code and paper grouped into one project.
  (No new repo is created here; if a repo doesn't exist yet, clone or
  `git init` it first and it appears in the picker.)

She submits; the request lands in the PI's approval queue.

**2. PI approves.** One click. Murmurent registers the project over the
selected repos, creates the **private** Slack channel, and — because Allie is
the creator — issues her the **project-lead card** and DMs it to her:

> **Slack DM to @allie:** Your murmurent project LEAD card for 'dcis_17' is
> ready. Save the JSON below as bundle.json, then run:
> `murmurent import-card bundle.json`

**3. Allie certifies her members.** After importing her lead card, her
dashboard shows the project with Bob listed as *no cert* and an **issue**
button. One click: Bob's project card is signed *with Allie's key* (his public
key is already on the roster from when he joined the lab — no ceremony
needed), DM'd to him, and he's invited to the private channel. Bob imports it
and can prove he belongs:

```bash
murmurent project-whoami
# ✓ hallett/dcis_17 — member (@bob)
```

*(When the PI is the one creating a project, steps 2–3 collapse: approval
self-delegates and cards every member in one shot.)*

**Later.** Allie removes a member → their certificate is revoked (CRL) and
they're kicked from the channel. The PI deletes the project → every
certificate is revoked, the channel is archived, and the project vanishes
from the dashboard (recovery is CLI-only: `murmurent project-unarchive`;
revoked certs stay revoked — re-issue).

---

## Vignette 2 — An inter-group project (members span labs)

Allie now wants `spatial_atlas` with Carlos, who is in the **Xia lab** — a
different group, a different Slack workspace.

**1. The gate.** She adds `@carlos` to the member list. He isn't on her lab's
roster, so the form demands one more thing — and if she skips it, creation
**halts**:

> project members span multiple groups — the groups must decide on a shared
> Slack workspace before an inter-group project can be created.

This is deliberate: the shared workspace is where the project channel lives
and where certificates are DM'd, so it must exist *before* the project does.

**2. The groups decide.** The two PIs agree which of their labs' registered
workspaces hosts the project (say the Hallett lab's) — what matters is that
the workspace's bot token is on file. (A dedicated stand-alone workspace works
too, once it's registered as a group with the registrar — `group-slack-setup`
refuses unregistered names.)

```bash
# one-time, on the machine that will provision the project:
murmurent group-slack-setup <workspace>
# token lands at ~/.config/murmurent/groups/<workspace>/slack-token
```

Allie enters the workspace id in the form and the proposal goes through.
(The check re-runs at approval, so it fails closed even if rosters changed
in between.)

**3. Certifying an outside member.** Carlos isn't on Allie's roster, so there
is no recorded key for him. He runs, on his own machine:

```bash
murmurent enroll --project spatial_atlas
```

and DMs Allie the JSON it prints. She pastes it into the **issue** dialog
(or runs `murmurent project-add-member @carlos --project spatial_atlas
--enrollment carlos.json`). His card is signed by Allie, chained to *her*
lab's root — anyone in the centre can verify it — and DM'd back through the
shared workspace. Next time is one click: his key is now on record.

**4. Repos in two places?** Fine. Each repo in the project carries its own
remote, so the code repo can push to `hallettmiket/...` while the analysis
repo pushes to the Xia lab's org. (Automatic collaborator sync covers the
primary repo; extra-org repos are managed by hand for now.)

---

## The commands, in one table

| You want to… | Do |
|---|---|
| Create a project | dashboard → **＋ new project** (PI approves) |
| Import your lead / member card | `murmurent import-card bundle.json` |
| Add a member (lead) | project → Members → **＋ add member** or `murmurent project-add-member` |
| Add an outside member | they run `murmurent enroll --project <p>`, you issue with `--enrollment` |
| Remove a member | project → Members → **×** or `murmurent project-remove-member` |
| Prove your membership | `murmurent project-whoami` |
| Delete a project (PI) | project row → **delete** |
| Recover a deleted project | `murmurent project-unarchive --project <p>` (then re-issue certs) |

Deeper background: the certificate chain and trust model are in
[`identity.md`](identity.md); the full command reference is in
[`cli_manual.md`](cli_manual.md).
