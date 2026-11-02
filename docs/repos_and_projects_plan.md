# Repositories and projects: how it works, what is wrong, and the plan

**Date:** 2 November 2026. **Author:** Mike Hallett with Claude Code.
**Status:** approved by the PI on 2 November 2026 and built the same day. The
seven stages below are merged in `murmurent_dev`:

| Stage | Issue | Pull request |
|---|---|---|
| 1. Collaborators from another group can finish joining | 252 | 262 |
| 2. A repository may belong to several projects | 253 | 263 |
| 3. Membership grants and revokes access on every repository | 255 | 265 |
| 4. Readiness travels with the clone | 257 | 267 |
| 5. Invite by email | 258 | 268 |
| 6. The dashboard shows each person exactly their projects | 259 | 270 |
| 7. The documents and the millwright agree with the code | 260 | this one |

Open after the plan: issue 269 (`add-repo --create-remote`, so a new
repository is created on GitHub and access granted in one step). Deferred by
decision: issues 254 and 256 (see the end of Part 3). Part 1 below describes
the code as it was before the stages; the file references point at commit
`55a6d6e`.

This document answers a request to look closely at how murmurent handles
repositories, projects and membership. It has three parts: what the code does
today, point by point against what was asked for; where the request itself
should change; and a plan in stages, each with the GitHub issue that tracks it.

Every claim about the code was checked against `murmurent_dev` at commit
`55a6d6e` (2 November 2026). File references are to `src/murmurent/`.

## The one-paragraph answer

The model is right and the code mostly follows it: a repository is made ready
with a marker file, a project is a record in the lab's records repository that
lists repositories and members, and membership is a signed card plus Slack and
GitHub access. Three things make it confusing in practice. First, the code
still treats a repository as owned by exactly one project, so sharing a
repository between projects fails in several places, and the "one repository
is its own project" rule produces placeholder projects nobody asked for.
Second, joining and leaving a project do far less than people expect: a new
member gets a card and a Slack invite, but GitHub access is granted only on
one repository named after the project, which is often not one of the
project's repositories at all, and leaving revokes almost nothing. Third, a
collaborator from another group cannot finish joining without a step nobody
tells them about (the trust root), which is exactly what happened to a collaborator from
another lab on 2 November. The plan fixes these in order: the collaborator path
first, because it is small and blocks people today; then "a repository can
belong to several projects"; then "membership means access to every
repository of the project, granted and revoked together".

## Part 1. What happens today, against each point raised

The numbering follows the request.

### 1 and 2. How repositories and projects are handled

A **repository** becomes murmurent-ready when `.murmurent.yaml` is written in
it (`core/repo_ready.py`). The marker holds the lab, the date, the bootstrap
version and the agents to link. "Make ready" also links the agents, writes a
`CLAUDE.md` stub and the editor settings, and records the path on this
machine. It does not run `git init` (it refuses a folder with no `.git`), does
not create a GitHub repository, does not create a Slack channel, and does not
commit the marker.

A **project** is a file `cert_projects/<name>.md` in the lab's records
repository (`core/cert_projects.py`). It lists repositories (name, role such as
code or manuscript, where they are), members, the certificates issued to them,
its Slack channel, its data folders, and what it reads without owning. When a
repository is made ready and no project lists it, a one-repository project of
the same name is written automatically (`core/project_unit.py`,
`ensure_repo_project`), so point 5 below already holds.

Where the two meet: `owning_projects` finds every project that lists a
repository, and most code assumes there is exactly one.

### 3. Making a repository ready should open a Slack channel and a GitHub repository

Not today. Make ready creates neither. A GitHub repository is created only by
`murmurent project new`, by project request approval when no repositories are
attached, and by `project provision-github`, which creates a repository named
after the *project* and ignores the project's repository list
(`core/cert_provision.py:310-376`). A Slack channel is created only per
project, named `proj-<project>` (`cert_provision.py:237-302`). Nothing creates
a channel per repository; the only way a repository gets its own channel is a
hand-written `slack_channel:` line in its marker.

See Part 2 on whether a channel per repository is the right goal.

### 4. A clone on a second machine should be under murmurent control

Half true. If the marker was committed, the clone is recognised, and
`murmurent install` re-links the agents from the marker. But make ready never
commits the marker, so this depends on the person remembering; the clone is
not registered on the second machine; and `murmurent install` rewrites
`bootstrap_version` in the committed marker, so two machines on different
murmurent versions push that line back and forth. Pushes from the clone post
notes only if the lab's bot token is on that machine; otherwise the note is
silently not posted (`core/slack_routing.py:208-210`).

### 5. A repository can belong to several projects; a repository alone is a project

The second half holds (see 1 and 2). The first half does not: the code and
docs say one owning project per repository (`core/project_unit.py:18-20`,
`docs/ready_vs_projects.md:147`); Slack routing refuses to post when two
active projects list one repository (issue 243); and the dashboard lets a PI
create exactly that double listing, because `add_repo` does not check. The
placeholder project made at make-ready time is retired only when the real
project lists a repository of the same name, so a placeholder named `x` that
holds only `x_manuscript` is never retired.

### 6. Membership of a project should perhaps not mean access to every repository

Today membership does not reliably mean access to *any* repository (see 7),
so the finer question has not arisen yet. Part 2 argues it need not arise at
all: once a repository can belong to several projects, the case described (a
collaborator who should see the paper but not the data) is served by a second
project that lists only the manuscript repository. No per-repository access
inside a project is needed. Tracked in issue 254 so the decision is recorded.

### 7. Leaving a project should revoke Slack and GitHub access everywhere

Not today. `remove_member` (`core/project_members.py:139-184`) revokes the
card in this machine's ledger, drops the handle from the record, kicks them
from the one project channel, and reconciles collaborators on the one
repository named `org/<project>`. The repositories actually listed on the
project are untouched. Four further faults:

- a non-PI project lead cannot remove anyone, because the check demands a PI
  role on the local machine, although the dashboard and the docs say the lead
  can;
- a PI removing a member of a project led by someone else revokes no card,
  because the card id is in the lead's machine-local ledger;
- the Slack kick is blocked outright while any member of the project cannot
  be resolved in the workspace;
- nothing tells the person they were removed.

`group-remove-member`, the dashboard's deactivate, and the millwright's
deprovisioning checklist do not touch project memberships either.

### 8. A member must hold what proves their membership locally

They do: after `murmurent import-card`, the signed bundle sits in
`~/.murmurent/cards/`. Two things to know. The card proves identity and
membership to anyone who checks it, but nothing checks it for access: Slack
and GitHub key off the project record's member list, and the card feeds only
`project-whoami` and the dashboard's chip. And the proof chain ends at a
**trust root**, the PI's or the centre's public key, which the member's
machine must already hold. That is the step that failed for Tyler (see 14).

### 9. A repository in several projects needs its own GitHub repository and channel

GitHub: every repository already is its own GitHub repository (that is what a
repository is); what is missing is that the project's repository list is not
what collaborator access is granted on. Slack: see Part 2; a channel per
repository is not the right unit.

### 10. Does a project need a GitHub repository or Slack channel of its own?

A project needs a **channel**: it is where the people of the project talk and
where the notes of its repositories land. It does not need a **GitHub
repository**, and today the one `provision-github` creates is a mistake: it is
named after the project, is not in the project's repository list, and is the
only place collaborator access is managed. The project's records (members,
certificates, repositories) live in the lead lab's records repository, which
is right for the lab. The real gap is that a member from another lab cannot
read that record, so their dashboard shows the project as "hosted elsewhere"
with no team and no repositories. Part 2 recommends against a per-project
repository and says what to do instead. Tracked in issue 256.

### 11. Data folders under immutable/ and append_only/

In place, with one wrinkle. Data folders are per **project**, not per
repository: `immutable/<project>` and `append_only/<project>`, with
`append_only/<project>/<experiment>` mirroring the code repository's `exp/`
(`core/project_unit.py:147-181`). The guards on those folders work regardless.
The wrinkle appears only once a repository belongs to several projects: its
data stays with one of them. Part 2 proposes the rule.

### 12. All of this on the dashboard; every member sees all their projects

Most actions exist on the dashboard (make ready, add and remove members, issue
certificates, provision Slack, add and remove repositories). Visibility is off
in two directions. A member sees **every** project of their own lab, not only
the ones they belong to (`core/project_lens.py:128-129`). A project hosted by
another lab is visible only if the member holds its card, and then with no
team and no repositories; and the project's Slack link shown is derived from
the viewer's own lab, which is wrong for such a project.

### 13. Tell people on Slack when they are added

Done when a card is issued (a direct message with the card attached). Not done
when a person is recorded as pending (no key on record yet), and not done on
removal.

### 14. Adding someone from another group is awkward; could it be an email address?

There is no directory of people across groups; the public hub lists centres
only, and nothing maps an email address to a handle. So today the only way is
to ask the person for their handle, which is what happened with Tyler. And
even with the handle, the path broke at the last step. What he saw:

1. He ran `murmurent enroll --project faraday` and sent the file. The command
   told him to send it to "your PI" for `issue-project-card`, the older
   PI-signed path, not to the project lead for `project-add-member`.
2. The card came back by direct message with the instruction
   `murmurent import-card bundle.json`.
3. `import-card` stopped with "no pinned trust anchor for centre
   'mhallet-mh'". His machine has pinned his own group's root, not this lab's.
   The PI's key is in the bundle, but a key taken from the bundle cannot vouch
   for the bundle, so murmurent wants it by another route. The message for
   **lab** member cards says exactly which key to pass and how; the message
   for **project** cards does not, and neither does the inter-group guide.

Email as the way in is possible and is the right goal; Part 3 says how.

## Part 2. Where the request should change

**A channel per repository: no.** The request asks for a Slack channel per
repository so that a repository can belong to several projects. Channels per
repository multiply what people must read, and the notes of a repository
shared by two projects would still have to reach both. The better rule: the
**project** is the unit of conversation, and a note about a repository goes to
the channel of **every** project that lists it. That replaces the current
refusal with the obvious behaviour, removes the one-owner rule from routing,
and keeps the per-repository `slack_channel:` override for the odd repository
whose traffic should go elsewhere.

**Per-repository access inside a project: not needed.** The driver was a
collaborator who needs the paper but not the data. With repositories allowed
in several projects, that collaborator joins a project that lists only the
manuscript repository (say `dcis_paper`), while the lab's own project
`dcis` lists everything. Access follows the project's repository list, so the
case is covered without a second permission system. Record the decision and
revisit only if a real case cannot be expressed as two projects.

**A GitHub repository per project: no.** Keep project records in the lead lab's
records repository. For members from other labs, embed the project's team and
repository list in the card bundle at issue time and on each reissue, and let
the dashboard read that for a project it has no record of. A per-project
records repository would be a fourth place to clone, and the lab's records
repository already carries the authority (the PI's signature) that a
cross-lab reader needs. If multi-lab projects become the norm, revisit.

**Cards do not gate access; do not try to make them.** The card is the proof
of identity and membership; Slack and GitHub membership is the enforcement.
Keep it that way, but make the enforcement complete (Part 3, stage 3) and make
the card reachable (stage 1).

**Data folders stay per project.** A repository in two projects keeps its
data under the project that created it (its **home project**, recorded on the
repository entry). The second project lists that folder under `reads_from`,
which already exists for exactly this. `release-repo` and `add-repo` should
move the home when, and only when, the person asks.

**"Make ready" should not create a GitHub repository or a channel by itself.**
Making a folder ready is a local, reversible step a student does on a clone.
Creating a GitHub repository is a decision about where code lives, and
creating a channel is a decision about who talks where; both belong to the
project step, where the PI or lead is acting. What make ready should do is
commit the marker, so the readiness travels with the clone (point 4).

**Membership by email is right, but it is an invitation, not a lookup.**
Nothing can turn an email into a murmurent handle for a person murmurent has
never met. So the flow is: the lead types an email; murmurent records a
pending member keyed by email, drafts the invitation (the `enroll` command,
what to send back, and the trust root to expect) for the lead to send; when
the enrollment arrives, the handle fills in and the card is issued. For a
person murmurent *has* met (on this lab's roster, or on another lab's records
this machine holds), the email resolves to the handle at once.

## Part 3. The plan, in stages

Each stage is one or two pull requests and has an issue. Earlier stages do not
depend on later ones.

### Stage 1. Collaborators from another group can finish joining (issue 252)

Small, and it unblocks people now.

- The project-card direct message names the trust root and gives the exact
  command, as the lab member-card path already does:
  `murmurent import-card bundle.json --trust-root ed25519:...`, with one line
  on confirming the key with the lead by another route.
- `import-card`'s error names the key to pass and where it is in the bundle,
  and says "lab" rather than "centre" for a self-rooted lab.
- `murmurent enroll --project` points at `project-add-member --enrollment`,
  not at the older PI path.
- `docs/project_inter.md` gets the missing step.
- A pending member (no key yet) gets a direct message with the enrollment
  steps when the lead has their Slack handle or email; today the lead sends
  it by hand.

### Stage 2. A repository may belong to several projects (issue 253)

- Routing posts a repository's note to every active project that lists it
  (the refusal from issue 243 goes away; the marker override stays).
- `project add-repo` on the CLI, and both `add-repo` and `release-repo` check
  that the caller is the PI or the lead, as the dashboard does.
- The placeholder project made at make-ready time is retired whenever a real
  project lists that repository, whatever its name.
- A repository entry records its home project for data folders; the other
  projects list that folder under `reads_from` automatically.
- Docs: `ready_vs_projects.md` and `slack_routing.md` state the new rule.

### Stage 3. Membership means access to every repository, granted and revoked together (issue 255)

- Adding a member grants collaborator access on every repository of the
  project that has a GitHub remote, invites them to the project channel, and
  runs the guest invite for outside members where the workspace allows it.
- Removing a member revokes all of that, on every repository, and tells them
  by direct message. The Slack kick is no longer blocked by an unresolved
  third party.
- A project lead who is not the PI can remove members; revocation of a card
  issued on another machine is recorded so the lead and the PI can each do it.
- `group-remove-member` and the dashboard's deactivate also remove the person
  from every project of the lab.
- The project-level `github_repo` created by `provision-github` is retired;
  provisioning acts on the repository list.
- Reconciliation reports what it could not do (unresolved people, failed
  invites) instead of a count of invitations.

### Stage 4. Readiness travels with the clone (issue 257)

- Make ready commits the marker (and the `CLAUDE.md` stub) with a clear
  message, or tells the person to.
- `murmurent install` stops rewriting `bootstrap_version` in a committed file;
  the version is recorded per machine instead.
- A clone that carries the marker is registered on the machine when
  `murmurent install` or `reconcile` first sees it.
- A push from a machine without the bot token says so once, with the fix,
  instead of silently not posting.

### Stage 5. Invite by email (issue 258)

- The dashboard's "add member" takes an email address as well as a handle.
- An email already on this lab's roster, or on another lab's records this
  machine holds, resolves to the handle.
- Otherwise a pending member is recorded under the email, and murmurent
  drafts the invitation for the lead to send: the `enroll` command, where to
  send the file, and the trust root the person will need. On macOS and Linux
  it opens the draft in the mail client, as the join flow already does.
- When the enrollment arrives, the handle replaces the email and the card is
  issued as today.

### Stage 6. The dashboard shows each person exactly their projects (issue 259)

- A member sees the projects they belong to, from any lab; the PI sees every
  project of the lab.
- A project hosted by another lab shows its team and repositories from the
  card bundle (Part 2), and its Slack link from the host lab, not the viewer's.
- A lead whose project is hosted in another lab's records can manage it.

### Stage 7. The documents and the millwright agree with the code (issue 260)

The millwright's text still names a hard-coded GitHub organisation, `raw` and
`refined`, `CHARTER.md` as the readiness marker and a channel named
`#<project>`; `ready_vs_projects.md` describes a default agent set the CLI
does not have and a cross-machine search that was retired; `project_intra.md`
says creating a project never creates a repository, which approval does. One
pass to make them say what the code does, after stages 2 and 3 settle it.

### Deferred, by decision

- Per-repository access inside a project (issue 254): not built; two projects
  cover the case.
- A GitHub repository per project (issue 256): not built; the card bundle
  carries what outside members need.
- Filesystem access lists on the server for project membership: the script
  exists (`scripts/murmurent_project_acl.sh`) but is never called on join or
  leave. It belongs with stage 3 once a lab service account exists to run it
  (see `docs/service_account.md`).

## Appendix. Other faults found on the way

Each is a sentence; the issue that owns it is in brackets.

- A proof-of-possession enrollment from an outsider silently adds them to the
  lead's lab roster as staff, which then grants lab-level access on the next
  group reconcile (255).
- The same path writes empty strings over a roster entry's email, GitHub and
  Slack fields when the enrollment lacks them (255).
- Uncertified members are invited to the project channel on the next
  reconcile, although the code and docs say certified members only (255).
- The dashboard lists an uncertified member twice, once with a key icon and
  once as "no cert" (259).
- `revoke-project` still prints "Slack/GitHub teardown is a later phase"
  although teardown now runs (255).
- A standalone lab's revocation list never leaves the PI's machine, so a
  revoked card keeps verifying elsewhere (255).
- The "+ install" path can register a project that lists a repository another
  project already lists (253).
- `make_ready` names the `CLAUDE.md` stub and the path record after the
  worktree folder, the one spot the fix for issue 250 missed (257).
- Remote adopt over SSH leaves an existing marker untouched, so its agent list
  cannot be changed that way (257).
- The CLI and the dashboard disagree on which agents "make ready" links by
  default: none against nearly all (257).
