# Creating a project (intra-group)

> Diagram: [project lifecycle](diagrams.md#4-project-lifecycle) shows a project's states from creation to archive.

A Murmurent **project** is two coordinated sets:

- a set of **repos**: existing repos, picked from your repositories folder
  (`~/repos` unless you chose another; `murmurent config repos-root` shows
  it) or from the lab's GitHub organisation. A repo picked from GitHub is
  copied to this machine when the project is created, and every repo is made
  murmurent-ready for you. Approval creates one thing on GitHub: a private
  `<org>/<project>` remote for the project's primary repository when it has
  none yet (`<org>` is the lab's `github_org`). Any other repository is added
  later with `murmurent project add-repo`, and a repository may belong to
  several projects;
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
The channel is named `proj-<project>`. To rename it, run
`murmurent project rename-slack <project>` (add `--to <name>` for a name of
your own).

A project is a higher-level construct than a repo being
**murmurent-ready** (having the commons agents wired in via `murmurent repo
adopt`): readiness is the configuration a repo needs before it can be used
in a project. Every repository is in a project: adopting one that no project
lists records a one-repository project for it. When a project like the one
below takes in that repository, the one-repository project is archived (kept,
not deleted), so the repository still has a single owning project. See
[`ready_vs_projects.md`](ready_vs_projects.md) for the distinction between the
two.

---

## An intra-group project (everyone is in your lab)

Allie (a member of the Rao lab) wants to start `brca_17` with Bob. She
already has the two repos that make up the work (`brca_code` and
`brca_manuscript`) cloned in her repositories folder on her laptop.

**1. Create.** On her dashboard, Allie clicks **＋ new project**
(**Create new project**) and fills in:

- *name*: `brca_17`, and a short *description* of what it is about
- *members*: `@allie`, `@bob` (from the lab roster dropdown)
- *repos*: `brca_code` + `brca_manuscript`, picked from the repos on her
  laptop and in the lab's GitHub organisation: code and paper grouped into
  one project.

She clicks **create**. Because she is a member, not the PI, the request goes
to the PI to confirm. (When the PI creates a project, it is created at once.)

**2. PI approves.** The PI approves the request from the dashboard.
Murmurent registers the project over the selected repos, creates the
**private** Slack channel (`#proj-brca_17`), gives the primary repository a
GitHub remote if it has none, and (because Allie is the creator) issues her
the **project-lead card** and DMs it to her:

> **Slack DM to @allie:** Your murmurent project LEAD card for project
> 'brca_17' is ready. Your signed bundle.json is attached to this message.
> Download it, then run: `murmurent import-card bundle.json --trust-root
> ed25519:...` (the `--trust-root` part is needed once; it pins the key of
> the PI who signed the card)

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
| Add an outside member | project → Members → type their `@handle`, or their email address, and press Enter. An email murmurent knows (this lab's roster, or another lab's records on this machine) becomes the handle; any other records an invitation and drafts the email for you to send, with the enroll command and the trust root to expect; the handle fills in when their enrollment arrives. A handle: they join the list at once, marked *no cert*. They run `murmurent enroll --project <p>` and send you the file (those steps are also sent to them by direct message when the workspace is connected); paste it in the window, or later via **issue** next to their name (CLI: `--enrollment`). Their card then needs `--trust-root <your root>` the first time, which the message with the bundle gives them; see [inter-group projects](project_inter.md) | Dashboard or CLI |
| Remove a member | project → Members → **×**, or `murmurent project-remove-member`. Revokes their card, removes them from the channel and from every GitHub repository the project lists, and tells them. A lead's removal leaves the card for the PI's `project reconcile --apply` to revoke | Dashboard or CLI |
| What membership gives | Access follows membership: adding someone grants collaborator access on every GitHub repository the project lists (`murmurent project add-repo`) and a seat in the channel; removing them takes all of it away. `murmurent project reconcile` shows any drift | |
| Prove your membership | `murmurent project-whoami` | CLI |

Deeper background: the certificate chain and trust model are in
[`identity.md`](identity.md); the full command reference is in
[`cli_manual.md`](cli_manual.md).

## Posting a status update

Type `/murmurent-update-me` in a Claude Code session opened in one of the
project's repositories. It gathers the facts (what is running on every lab
account, what finished since the last update, quality-gate results, git, and the
project's open progress issues on GitHub), writes a short plain-English summary
naming what is blocked and on whom, and posts it to the project's Slack channel.
Type `/murmurent-update-me dry-run` to see the text without posting.

It never posts a credential, a path inside a `publication/` folder, or a count
under six of people or events. Most projects need no settings. To change where
it looks (another outputs folder, a manuscript repository, quality gates to
report, the channel for a project without its own), add an `update_me:` block to
the repository's `.murmurent.yaml`; the keys are listed in the skill's
[`SKILL.md`](https://github.com/hallettmiket/murmurent/blob/main/skills/murmurent-update-me/SKILL.md).

