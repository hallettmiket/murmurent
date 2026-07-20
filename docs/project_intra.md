# Creating a project (intra-group)

> Diagram: [project lifecycle](diagrams.md#4-project-lifecycle) shows a project's states from creation to archive.

A Murmurent **project** is three coordinated sets:

- a set of **repos**: *existing* clones picked from your machines' repo
  folders (`~/repos` etc.; the folders themselves are configured on the
  Machines panel under *Repo location*). Creating a project attaches
  existing clones: clone or `git init` the repo first, then group it into
  a project;
- a set of **machines** (your laptop, the lab VM, …),
- a set of **members**, and membership is *cryptographic*: each member holds
  a signed **project certificate**, a credential that cryptographically
  proves their membership and can be verified (offline) against the
  project lead's key.

The person who creates the project is its **lead**. At creation the PI signs
the lead a one-time *delegation card*; from then on the lead (and only the
lead) signs members in and out with their own key. The PI approves that the
project should exist; the lead controls who's in it.

Every project also gets a **private Slack channel**: certificates are DM'd
through Slack, members are invited when they join and removed when they leave.

A project is a higher-level construct than a repo being
**murmurent-ready** (having the commons agents wired in via `murmurent repo
adopt`): readiness is the configuration a repo needs before it can be used
in a project. See [`ready_vs_projects.md`](ready_vs_projects.md) for the
distinction between the two.

---

## An intra-group project (everyone is in your lab)

Allie (a member of the Rao lab) wants to start `brca_17` with Bob. She
already has the two repos that make up the work (`brca_code` and
`brca_manuscript`) cloned under `~/repos` on her laptop.

**1. Propose.** On her dashboard, Allie clicks **＋ new project** and picks:

- *name*: `brca_17`
- *members*: `@allie`, `@bob` (from the lab roster dropdown)
- *machines*: her laptop + `lab-server`
- *repos*: `brca_code` + `brca_manuscript`, selected from the clones Murmurent
  already found in her repo folders: code and paper grouped into one project.
  (Only existing clones are offered in the picker: clone or `git init` a
  repo first and it appears there.)

She submits; the request lands in the PI's approval queue.

**2. PI approves.** The PI approves the request from the dashboard.
Murmurent registers the project over the
selected repos, creates the **private** Slack channel, and (because Allie is
the creator) issues her the **project-lead card** and DMs it to her:

> **Slack DM to @allie:** Your Murmurent project LEAD card for 'brca_17' is
> ready. Save the JSON below as bundle.json, then run:
> `murmurent import-card bundle.json`

**3. Allie certifies her members.** After importing her lead card, her
dashboard shows the project with Bob listed as *no cert* and an **issue**
button. When she uses it, Bob's project card is signed with Allie's key (his
public key is already on the roster from when he joined the lab, so signing is
immediate), DM'd to him, and he's invited to the private channel. Bob imports it
and can prove he belongs:

```bash
murmurent project-whoami
# ✓ rao/brca_17 — member (@bob)
```

(When the PI is the one creating a project, steps 2–3 collapse: approval
self-delegates and cards every member in a single step.)

**Later.** When Allie removes a member, their certificate is revoked (CRL) and
they are removed from the channel. When the PI deletes the project, every
certificate is revoked, the channel is archived, and the project is removed
from the dashboard (recovery is CLI-only: `murmurent project-unarchive`;
revoked certs stay revoked: re-issue).

---

## The commands, in one table

Project **creation and deletion** happen only through the dashboard under
the current certificate-based model. (A legacy `murmurent project new`
CLI command predates certificates; dashboard creation is the current
path.) **Membership and certificate** operations, by contrast, run as CLI
commands, some of which are mirrored by a dashboard button that runs the
same command underneath.

| You want to… | Do | Where |
|---|---|---|
| Create a project | dashboard → **＋ new project** (PI approves) | Dashboard |
| Delete a project (PI) | project row → **delete** | Dashboard |
| Recover a deleted project | `murmurent project-unarchive --project <p>` (then re-issue certs) | CLI |
| Import your lead / member card | `murmurent import-card bundle.json` | CLI |
| Add a member (lead) | project → Members → **＋ add member**, or `murmurent project-add-member` | Dashboard or CLI |
| Add an outside member | they run `murmurent enroll --project <p>`, you issue with `--enrollment` | CLI |
| Remove a member | project → Members → **×**, or `murmurent project-remove-member` | Dashboard or CLI |
| Prove your membership | `murmurent project-whoami` | CLI |

Deeper background: the certificate chain and trust model are in
[`identity.md`](identity.md); the full command reference is in
[`cli_manual.md`](cli_manual.md).
