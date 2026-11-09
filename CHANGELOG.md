# Changelog

All notable, release-worthy changes to murmurent are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/); the version scheme is
**CalVer `YYYY.M.MICRO`** (see [`docs/versioning.md`](docs/versioning.md)).

**When to add an entry:** bump the version and add a section only for a
*structural* release — a new commons agent, a marker/schema change, or anything
that should make existing murmurent-ready repos want `murmurent repo upgrade`.
Agent-content edits (prompt tweaks, rule wording, docs) propagate automatically
via the `.claude/agents` symlinks and need **no** version bump — don't add a
changelog entry or a tag for those. Developers append to `[Unreleased]` as
structural changes land; it's cut to a dated version at release time.

The version lives in exactly one place: `src/murmurent/__init__.py`
(`__version__`). `pyproject.toml` reads it from there.

## [Unreleased]

### Changed
- The agent movies: each agent now speaks for itself, in the first person and in a voice of its own (`AGENT_VOICES` in `training/lib/agent_movie.py`; the skill movies keep the narrator), and no movie restates what the other agents do, only how they hand work to each other. The bookworm says it covers the databases (UniProt, ChEMBL, trial registries) as well as the literature, and the forms it returns; the adversary reproduces ordinary statistics (t-tests, ANOVA, regression, survival curves), not only classifiers; the scribe writes in whatever form is asked for; the teacher draws the permutation test (a scene of the movie's own, through the new `Extra` scene type), writes a quiz with each page, and explains Feynman's rule against jargon; the conscience names SGBA+, decolonization and the kinds of document it reviews (a grant, a course outline, a paper); the lawyer names the Ontario IP Foundations course; the millwright is introduced in plain words; the security guard marks the social insurance number as Canada-specific; the clerk says its cases are examples and flags the quiz that breaks a university rule. The example projects are now Candida albicans studies.
- `agents/lawyer.md`: a section on the IP Foundations course (University of Toronto Entrepreneurship, endorsed by the Ontario Ministry of Colleges and Universities): the lawyer uses its distinctions between the forms of intellectual property, names which one applies, and points a researcher to the course rather than replacing it.

## [2026.11.2] - 2026-11-09

### Added
- `murmurent prompt send --quiet`: with the Obsidian hotkey's output set to replace the selection, a prompt leaves the day's entry the moment it is sent and lives on in the sessions record. The lab notebook page says how to set it up, and the notebook movie's first step is the experimental design, if you like, rather than a plan you must write.
- The clerk's course review opens with the term day by day: every date from the first day of classes to the end of the examination period, with the outline's own events and their weights, the pack's holidays, reading weeks and study days, the pack's deadlines (add, drop, withdraw), and the cutoffs the institution's rules imply, counted back from the last day of classes (the last day a test may be scheduled, a new assignment announced, work accepted), each with its source. The report says what it could not place: a pack without deadlines, an assessment with no date.

## [2026.11.1] - 2026-11-09

### Fixed
- **Spoken verdicts no longer talk over each other or repeat.** The lock
  that makes verdicts wait their turn recorded the hook's pid instead of the
  speaking subshell's, so every waiter took the lock while the previous voice
  was still talking; it now records the right pid. A verdict queued for more
  than two minutes is dropped rather than read as a backlog. The same event
  delivered twice (the hook registered in a project's `.claude/settings.json`
  as well as the user's, a leftover from before 2026-05-17) is logged and
  spoken once; `murmurent doctor` warns about the stale project registration.

### Changed (training movies, #302, #303)
- Every agent and skill movie rewritten through the scribe in plain language: cards are short statements rather than quotations from the agent files, scope is stated positively, no file paths or commands on screen, and each movie says what a lab can tailor. The oracle movie tells the cross-project story the PI asked for: a marker of early liver cancer (GPC3, separating early hepatocellular carcinoma from a dysplastic nodule), recalled eight months later from a screening gene list. The adversary checked each movie against its agent's file and the artist reviewed the frames.

### Added (documentation)
- A figure of which agent hands work to which, drawn from the hand-off lines in the agents' own files, on the reference-agents page (`docs/diagrams/agent_handoffs.dot`).

### Fixed (agent files)
- The millwright and registrar open with their own verdict words rather than a paragraph copied from the security guard; the registrar's file no longer calls itself read-only, since the code creates, archives and updates labs and cores; the security guard no longer claims the conscience is told automatically when it blocks on patient data (nothing tells one agent about another's verdict; it names the hand-off in its reply).

### Added (course review, the scribe)
- `murmurent institution review`: the clerk reviews a whole course outline, every rule for its level (`applies_to` on a policy), each dated lecture, lab and assessment against the holidays and non-instructional days, the grade weights, and what the outline leaves unclear, as an HTML report. The conscience reviews the same outline separately; the scribe redoes it on request (#300).
- The scribe may edit a manuscript in place when asked, writes in whatever format the manuscript uses, uses the house style by default, and a lab tailors it with its own papers in `docs/scientific_writing_examples.md` (#301).

### Added
- **The clerk reviews a syllabus against the institution's rules.** Rules live
  in the pack under `policies/<name>.yaml`, each quoted as the institution's
  page words it with the page and the date read (`murmurent institution
  learn-rule`, which fetches the page and refuses a quote it does not find);
  `murmurent institution check <file> --policy course_outlines` finds the
  assessments in a course outline and reports each rule as Fix, Correct or
  Unknown: a test in the last weeks of classes, a new assignment introduced
  too late, a final examination too early. The Western pack holds the
  Academic Calendar's rules on scheduling tests, assignments and examinations.
- **Prompts written in Obsidian, sent with one keystroke, and kept.**
  `murmurent prompt new` opens today's `prompts/<date>.md` in the vault;
  `murmurent prompt send` copies the selected prompt or the latest block,
  pastes it into Claude Code (an app on macOS, or a tmux pane) and records it
  under `sessions/<date>/sent.md`, so prompts no longer vanish with the
  session. Bound to a hotkey through Obsidian's Shell commands plugin
  (`docs/lab_notebook.md`). The notebook movie is re-made as a bench
  scientist's day in natural language, with the commands as footnotes.
- **Two more training movies**: the lab notebook (adding text, photos and
  voice notes from Claude Code, the entry as Obsidian shows it, prompts moved
  out of old notes, a report for a supervisor from entries marked for them)
  and the data root (tier-3 memory: what immutable, append_only, modifiable,
  mothballed, release, cottage, tools and db are for, how a project's folders
  mirror its repository, what the hooks refuse, the layout check). The
  bookworm, blacksmith, artist, scribe and adversary movies gain a "how to
  direct it" scene: example requests that name the format, the destination
  (Zotero, a Streamlit app, a slide deck in Western's colours) and the method.
- **Five more training movies** (#290): working through Claude Code (the one
  every other movie assumes), the two push skills, the status update, a
  course across sessions, and the mayor's and PI's tools, under
  `training/skills/`, on a generic scene module (`training/lib/movie.py`)
  that quotes a skill's own `SKILL.md`. The getting-started video was
  re-checked against this release and ends with a coda pointing at the
  Claude Code movie.
- **One place for the videos and the news** (#289). `training/index.yaml`
  lists every training video (the standalone ones, the agent movies) and one
  line per release or new capability; `training/front_page.py` writes from it
  the "Videos and news" section of the README and the page at
  mikehallett.science/assets/videos/, so the two cannot drift apart. The
  agent movies carry their own emoji badge, as the seminar slides mark them.
- **The lab notebook: two streams** (#292). A new `UserPromptSubmit` hook,
  `murmurent.hooks.session_log`, records every prompt given to Claude Code in
  the personal vault under `sessions/<date>/<session>.md` with the time,
  project, repository and commit, so the day's notes in `lab-notebook/` hold
  only notes. A prompt matching a PHI or secret pattern is withheld and the
  hook says so; the stream is never published to the lab. The oracle MCP gains
  `kind=sessions`, and `kind=all` lists the notes before the sessions.
  `murmurent notebook split` moves prompt-shaped blocks out of existing
  entries into `sessions/<date>/pasted.md`, keeps each original under
  `obsolete/`, prints what it moved and deletes nothing.
- **The lab notebook: capture** (#293). `murmurent notebook add` puts text,
  an image, a handwritten page, a sound note, a video or a result file into
  today's entry. Small result files stay in the vault's `attachments/`;
  images, sound, video and large files go to
  `append_only/<project>/notebook/<date>/` on the project's data host (the
  lab's `data_host`, else the main repository's host; local or over SSH),
  never overwriting. The entry keeps the link, a thumbnail or poster frame
  (none for a protected project), and machine-made text marked as such: an
  ElevenLabs transcription when the Keychain holds `elevenlabs-api-key`,
  checked for PHI patterns first, or a marked placeholder for the session to
  fill. `murmurent notebook open <host>:<path>` fetches a copy to look at.
  `core.remote.Remote` gains `copy_to` and `copy_from`.
- **The lab notebook: audience and reports** (#294). An entry's `audience`
  (`me` by default, `supervisor`, `lab`, `project:<name>`) says who may read
  it. `murmurent notebook report --for <audience> --since <date>` collects
  the whole entries marked for that reader, refuses restricted and protected
  ones as `oracle publish` does, writes `material.md` and `sources.md` for
  the scribe and the artist, renders one self-contained `report.html` with a
  marked slot for the scribe's `narrative.md`, prints every entry and file it
  drew on, and sends nothing. Documented in `docs/lab_notebook.md`.
- **The clerk and the institution pack** (#291). A new commons agent, the
  `clerk`: ask it anything about your institution and it reads the answer off
  the institution's own web pages (a web search limited to the institution's
  domains, then the page), names the page and the date it read it, and
  remembers the fact in the **institution pack**, `institution/<unique_name>/`
  (`facts.yaml` for what it looked up, `directory.yaml` for office holders it
  confirmed, plus what the centre keeps on purpose: procedures, holidays, the
  letterhead). `Unknown` when the institution's pages do not say; never from
  memory. A remembered fact older than `verify_after_days` is re-read before
  it is relied on; `murmurent institution refresh` re-reads every fact on a
  schedule. Three jobs on top: check a document's office holders and
  addresses, compute a date in working days that never lands on a holiday,
  walk a procedure to its next steps. `murmurent institution
  recall|lookup|learn|verify|check|date|walk|refresh|fetch-course|init|validate`.
  The Western pack is withheld from the release; an example pack ships. The
  thesis paperwork reads the pack's procedure, and the docent asks the clerk
  for it.
- **One short training movie per commons agent** (#288): sixteen movies under
  `training/agents/<agent>/`, each 90 seconds to 3 minutes, rendered from a
  scene file by the shared renderer in `training/lib/` (lifted from the
  thesis-package video), quoting the agent's own `.md`, showing one real run,
  and narrated with ElevenLabs. `training/index.yaml` stamps each movie with
  the version and the hash of the agent file it was checked against. A new
  `PostToolUse` hook, `murmurent.hooks.agent_movie`, prompts once per session
  to re-render a movie when its `agents/<x>.md` is edited; the release
  checklist in `docs/versioning.md` repeats the step.
- **Paper packages, thesis packages and the `docent`.** A paper becomes a
  queryable package: `paper.yaml` maps each central claim to the code and
  data behind it; `murmurent paper init|check|build` scaffold, validate and
  render `build/claim_map.md`. A thesis is composed of paper packages or of
  chapters with their own claims: `murmurent thesis init|check|build` assemble
  `build/main.tex` in Western's SGPS order, `thesis talk` drafts a timed
  defence talk (one slide per claim, Beamer), and `thesis paperwork` writes
  the SGPS submission checklist from the manifest. The new `docent` agent
  answers an examiner's or reader's questions with a location, logs them
  append-only, and walks the candidate through the commands. Examples under
  `examples/`. Design, limits and sources: `docs/paper_package.md` (issue #284).
- **Windows on ARM installs without a compiler** (#281). `cryptography`
  stopped shipping Windows ARM wheels after 46.0.3, so `uv tool install`
  on a Surface or a Parallels VM tried to build it with Rust and failed.
  That platform is now held at 46.0.3 in `pyproject.toml`; every other
  platform keeps the current release.
- **Windows: supported through WSL, and `murmurent` now starts on a native
  Windows Python** (#281). Every command used to stop with "No module named
  'pwd'" before printing anything, and the vault-sync hook failed the same way
  on `fcntl`; those imports are now made only where Unix has them. `murmurent
  doctor` gains an "operating system" check that names WSL on Windows, and
  `docs/setup.md` says how to install it. A Windows console with a legacy
  code page no longer kills a command at the first ✓: the character is
  replaced instead. The run supervisor and the update-me script import
  there too. Nothing else is ported: the bash hooks, the symlinked commons
  and spoken verdicts still need Unix.
- **Agents can speak their verdicts in another language** (#279).
  `murmurent config speak-language fr_FR` (or any of the languages
  `--list` shows) records the choice in `~/.murmurent/speak` and fetches that
  language's Piper voice. A new `SubagentStart` hook (installed by
  `murmurent install --hooks`) tells each agent, before its first prompt, to
  write its `Aloud:` line in that language; the hook then reads it with a
  voice for the language (one Piper voice per language, or the Mac's own).
  Headline and detail stay in English. English stays the default; a machine
  that picks no language is unchanged. `docs/vscode-workflow.md`, "Spoken
  verdicts".
- **Members can post project notes from their own machines.** The lab's Slack
  bot token used to exist only on the PI's machine, so `murmurent project note`
  from a member's machine stopped at "no Slack bot token on this machine". New
  `murmurent group-slack-share <lab>` (PI) seals the token to the card key each
  active member attested at issuance and commits the box to the lab records
  (`security/slack_bot_token.sealed.json`); new `murmurent group-slack-unlock
  <lab>` (member) opens it with the machine's own key and stores the token at
  the usual per-machine path. `murmurent project note` tries the unlock itself
  when a machine has no token, and otherwise prints the exact command for that
  machine. Design and the relay alternative: `docs/slack_routing.md`.

## [2026.11.0] - 2026-11-02

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install --hooks`,
then restart Claude Code and the dashboard (**⏻ Stop dashboard**, then start
it again). From a copy of the repository: `git checkout main && git pull`
first, then the same two steps. The install re-links every ready repository
itself; nothing else to run.

This release is the outcome of a review of how repositories, projects and
membership work (`docs/repos_and_projects_plan.md`, issues 252 to 260, 269).
The rules it settles: a repository may belong to several projects; membership
of a project means access to every repository it lists, granted and revoked
together; readiness travels with the clone; each person sees exactly their
projects; a collaborator from another lab can finish joining from the message
they receive.

### Added
- **A repository may belong to several projects** (#253). A note about it
  goes to every project's channel; its data stays with its home project, the
  first that listed it, and the other projects read that folder. New
  `murmurent project add-repo <project> <folder> [--role] [--home]`; it and
  `release-repo` are for the PI or the project lead.
- **`add-repo --create-remote`** (#269) creates a private `<org>/<repo>` on
  GitHub for a clone that has none, pushes it, records the remote and grants
  every member access in one step. `project status` shows each repository's
  remote.
- **Membership grants and revokes access on every repository** (#255).
  Adding a member grants collaborator access on every GitHub repository the
  project lists; removing one revokes it everywhere, removes them from the
  channel and tells them by direct message. A lead who is not the PI can
  remove members; the PI's `project reconcile --apply` signs the revocation.
  Leaving the lab (`group-remove-member`, or deactivation on the dashboard)
  removes the person from every project they do not lead.
- **Invite a project member by email** (#258). An address murmurent knows
  becomes the handle; any other records an invitation and drafts the email,
  with the enroll command and the trust root to expect; the handle fills in
  when the enrollment arrives.
- **Collaborators from another lab can finish joining** (#252). The message
  that brings a project card names the lab's trust root and the exact
  `import-card --trust-root` command; a pending member is sent the
  enrollment steps; the import error names the key and where it is.
- **Server timers under a lab service account** (#249): the weekly space
  scan and the weekday etiquette check can run under a service account, with
  a shared `space_dir` so the PI keeps reading the table. See
  `docs/service_account.md`.
- **Outside members by handle** (#248): type a handle from another group
  into a project's member box and they join the list at once, awaiting a
  certificate.
- **Spoken verdicts with Piper voices** (#272). `bash
  scripts/install_piper_voices.sh` installs Piper, a free neural
  text-to-speech engine that runs on the machine itself, and fetches one
  natural English voice per agent. The agent-event hook uses Piper when it
  is present, on a Mac or on Linux, and otherwise the Mac's `say` or
  Linux's `spd-say` as before. `engine say` in `~/.murmurent/speak` forces
  the old engine; `audition` plays every voice.
- **Agents say their verdict in plain English.** Every agent now writes a
  second line beginning `Aloud:` under its headline, a summary of at most 100
  words written to be heard, and the hook speaks that line instead of the
  headline's shorthand. Piper voices were re-chosen by listening (the `high`
  voices for the agents heard most often) and are read a little slower with
  less noise; `speed` and `noise` lines in `~/.murmurent/speak` tune that.

### Changed
- **Readiness travels with the clone** (#257). Make ready commits the marker,
  the CLAUDE.md stub and the `.gitignore` lines for agent links, so every
  clone is ready; a clone carrying the marker is registered when `install` or
  `reconcile` sees it. The release that linked a repository is recorded per
  machine, no longer written into the committed marker. `repo adopt` links
  every commons agent for a fresh repository, as the dashboard does
  (`--agents none` links nothing).
- **The dashboard shows each person exactly their projects** (#259): the
  ones that list them, from any lab, plus any they hold a card for; the PI
  sees every project of the lab. A project hosted in another lab shows its
  team and repositories from the card bundle or the host lab's records, and
  its Slack link points into the right workspace.
- **No GitHub repository per project.** `provision-github` grants access on
  the repositories a project lists and creates nothing unless `--create`.
- The millwright's scaffold, the readiness and project guides, the push skill
  and the routing page say what the code does (#260).

### Fixed
- A note sent from a git worktree is routed like one from the main copy
  (#250); `murmurent project release-repo` takes a repository off a record.
- `murmurent inventory show` works on a machine with GitHub only (#264);
  the documentation site build link (#266).

## [2026.10.8] - 2026-10-30

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install --hooks`,
then restart Claude Code and the dashboard (**⏻ Stop dashboard**, then start
it again). From a copy of the repository: `git checkout main && git pull`
first, then the same two steps.

### Added
- **One resolver for where a repository's Slack notes go** (#243). Every
  release note, job notice and status update now follows the same route: a
  `slack_channel:` override in the repository's `.murmurent.yaml`, else the
  one active project whose record lists the repository, else the lab's
  channel, else nowhere. A note with no destination is not sent, and the
  sender says why. `murmurent project note "<text>"` posts through it;
  `murmurent project channels` audits every project's channel, bot
  membership and repositories claimed by two projects. See
  `docs/slack_routing.md`.
- **`murmurent project reconcile <name>`** compares a project channel's
  members with its certified members and reports the drift; `--apply`
  invites the missing and removes the extras. Members are matched by the
  roster's `slack:` id first, nobody is removed while a member is
  unresolved, and the bot is never removed.

### Fixed
- **A Slack invite counts only when the member arrives** (#246). Slack
  answers `ok` for a single-channel guest and adds nobody, so the reconcile
  and `provision-slack` now re-read the channel and name each member who
  did not arrive, with the reason.
- The push skill and the push command no longer resolve the channel each
  their own way, which had sent a dozen projects' notes to one channel.

## [2026.10.7] - 2026-10-29

**To upgrade:** as for 2026.10.6 below; this release only repairs the
documentation site.

### Fixed
- **The documentation site builds again.** A link in the writing guide
  pointed outside the docs folder, and the strict build had refused every
  release since 2026.10.3, so the site had not followed the releases.

## [2026.10.6] - 2026-10-29

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install --hooks`,
then restart Claude Code and the dashboard (**⏻ Stop dashboard**, then start
it again). From a copy of the repository: `git checkout main && git pull`
first, then the same two steps.

### Added
- **`murmurent cite check <file>`** (#225) looks up every DOI, PMID and arXiv
  identifier in a `.bib`, `.tex` or `.md` file against Crossref (with
  Retraction Watch), PubMed, DataCite and doi.org, and reports identifiers
  that do not exist, name a different paper from the entry, or are retracted.
  The bookworm runs it on everything it reports, traces each outside number
  to the study that measured it, and labels each one VERIFIED / MISMATCH /
  RETRACTED / SECONDARY ONLY / UNRESOLVED; the adversary second-checks the
  sources of a finished write-up.
- **Lab records access is tracked** (#232). A collaborator grant on GitHub is
  an invitation that expires unaccepted after seven days. `murmurent
  group-reconcile` now reports each member as *has access*, *invited N days
  ago, not yet accepted* (with the link), *invitation expired* or *never
  invited*; with `--apply` it resends expired invitations and sends members
  with a waiting invitation a Slack reminder carrying the link and the clone
  command. `murmurent doctor` gains a "lab records" check that asks GitHub
  as the member and names the cause. Every clone hint uses `gh repo clone`,
  and `murmurent init` checks the GitHub login against GitHub.
- **Spoken verdicts (macOS).** Create `~/.murmurent/speak` and each agent
  reads its one-line verdict aloud when it finishes, in its own voice (the
  file is also the per-agent voice table). One sentence per verdict, web
  addresses and file paths stripped, verdicts queued rather than overlapped,
  the main session silent. Guide: docs/vscode-workflow.md.
- **The vault syncs itself.** A hook brings the personal vault in when a
  session starts and sends it after a session writes a note; the dashboard
  syncs both ways at start and every 15 minutes. Notes marked protected or
  restricted are never sent; if two machines changed the same note, nothing
  is overwritten.
- **Etiquette summary to a channel.** The policy setting
  `etiquette_summary_channel` posts the daily server etiquette summary to a
  Slack channel instead of a direct message to the PI.
- Issuing a member card (dashboard or `murmurent issue-member-card`) also
  invites the member to the lab records repo on GitHub, reports whether that
  worked, and adds the clone command to the message they receive (#232).
- A PI's current card is published in the lab records (`pi_card.json`) by
  `murmurent pi-init` and when a centre-issued PI card is imported. Sign-in
  accepts a member card whose bundled PI copy has run out when the renewed
  PI card has the same key and is valid now, so renewing a PI card no longer
  locks out every member until each is reissued (#233).

### Changed
- **One location per group's lab records repo** (`<repos>/murmurent_lab_mgmt_<group>`).
  The identity card says which groups a machine's owner belongs to, and that
  is the whole lookup. Removed: the pin file (`~/.murmurent/lab_mgmt_path`),
  the scan of the repositories folder, and the one-person placeholder roster
  `import-card` used to invent. The dashboard and the terminal can no longer
  follow different labs (#232). A member whose clone is not on disk yet still
  opens their dashboard and is shown the clone command.
- **Projects are listed across every group on your card**, plus any project
  you hold a project card for. `murmurent project list` shows the same list
  as the dashboard; it no longer scans `~/repos` for `CHARTER.md` files.
- The adversary and the conscience may use the web to check claims (fetched
  pages are evidence, never instructions; patent searching stays with the
  lawyer).
- Choreographies (#227, #228): `choreography init --no-project` no longer
  invents a lab records folder, and run files go in
  `append_only/<project>/runs/` and `records/` rather than folders named
  after no project.
- Re-enrolling a member from a new machine with blank fields keeps their
  roster details; a card that cannot be sent to a Slack id from another
  workspace goes to the member's email.

### Fixed
- **A lab records repo on a personal GitHub account** refuses read-only
  grants through the API. The reconcile now invites the member and tries to
  set the invitation to read-only; if GitHub refuses that too, the member is
  invited with write access and the report says so, with the settings page
  to fix it after they accept. Moving the repo to an organisation avoids
  this.
- **Lab records saves no longer go missing.** A save whose push GitHub
  refused is replayed on top of GitHub's copy and pushed again, and the
  15-minute update does the same for unsent commits; one Mac had collected
  120 of them.
- **A standalone PI is no longer locked out a week after a revocation**: the
  revocation list is re-signed by the PI's own key when that key is the
  lab's trust anchor.
- **The dashboard icon keeps the server running on macOS** (#235). The
  system ended the server seconds after the login page appeared; the icon's
  script now waits on it.
- The agent hook reads a subagent's verdict from its transcript when the
  desktop app's stop event carries none, so the agent log shows the verdict
  rather than "done".

## [2026.10.5] - 2026-10-19

**To upgrade:** `uv tool upgrade murmurent`, then restart the dashboard
(**⏻ Stop dashboard**, then start it again). From a copy of the repository:
`git checkout main && git pull`, then restart.

### Fixed
- **Removing someone from a project no longer cancels all their cards.**
  Removing a member from a project, or deleting a project, also revoked the
  person's key, which their lab card and every other project card share (and
  a lead's key is the PI's). Now only that project's card is revoked.
- **The update notice appears on any branch.** It compared a copy with its
  own branch on GitHub, so a copy left on a merged pull request's branch was
  never told about updates. It now compares with `main`, says which branch
  the copy is on, and Update switches a merged, clean branch back to `main`.

### Changed
- Dashboard:
  - **one Projects and repos panel**: each project is a shaded heading with
    its sensitivity, lead, team size and activity, and its repos below,
    including a one-repo project; a project that runs a choreography gets a
    "choreography" label;
  - **Upgrade all repos**: one button replaces the Upgrade button on every
    row;
  - **Claude Code windows are named after their folder** ("Claude Code ·
    survival"), and the button brings an already-open session's window to
    the front;
  - the docs link in the top bar has "docs" under the book, and it and the
    version label are readable on the purple bar;
  - the This machine panel is at the bottom of the page.
- A repo counts as murmurent-ready when it has its `.murmurent.yaml` (#169).

## [2026.10.4] - 2026-10-19

**To upgrade:** `uv tool upgrade murmurent`, then restart the dashboard
(**⏻ Stop dashboard**, then start it again).

### Changed
- Dashboard: the Stop dashboard button is solid red with white text; the
  Projects table's columns fit their contents, with no wide gap before the
  sensitivity column.
- The README has badges: PyPI version, downloads, Python, licence,
  documentation.

## [2026.10.3] - 2026-10-19

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install`, then
restart Claude Code and the dashboard (**⏻ Stop dashboard**, then start it
again). If you installed from a copy of the repository, `git pull` there
instead of the first command.

### Added
- **The lab folder protocol** (#206). murmurent knows what each folder at the
  top of a lab's data root is for: `immutable/`, `append_only/`,
  `modifiable/`, `mothballed/` and `release/` (one subfolder per project),
  `cottage/` (one per person), and the shared `tools/` and `db/`.
  `murmurent space layout` lists anything that does not follow it, and moves
  nothing. Every agent's rules and the millwright describe it; agents tell
  the PI rather than tidy. Guide: [The lab folder
  protocol](https://mikehallett.science/murmurent/lab_folders/).
- **Carrying out space decisions** (#151, step 6). `murmurent space
  carry-out` copies each mothball, compress or move decision, checks the copy
  against fingerprints of the original, and logs it. `murmurent space
  removable` lists the originals a person may then remove. murmurent never
  removes files. Mothballing needs `mothball_target` in the lab's policy file.
- **Decide from the dashboard.** The Space page has a Decide column for the
  PI.
- **The Scribe** (#153, #173), an agent that revises and drafts manuscript
  text in the house style, and its writing guide, [Writing a scientific
  manuscript](https://mikehallett.science/murmurent/scientific_writing/).

### Changed
- **The sensitivity tiers are standard, restricted and protected** (#205),
  matching the manuscript. `clinical`, the former name of `protected`, is
  still read everywhere, so existing records need no edit.
- The weekly space scan counts a project's `modifiable/`, `release/` and
  `mothballed/` folders as its own, never suggests changes in `mothballed/`,
  and reports cottages and shared folders on their own line.
- Dashboard:
  - the This machine window lists each lab folder and what it is for;
  - the Repos panel shows every project's repos, including murmurent's own,
    under shaded project headings, and a listed repo it cannot find as "not
    found";
  - project actions (provision, reconcile, delete) sit on a "Manage this
    project" line in the project's details; the Projects panel is above
    Repos; published choreographies are listed without a button;
  - a project's member list takes an @handle from another group;
  - the lab notebook window shows about the last 25 lines of the day;
  - the Stop dashboard button is red and easy to see;
  - the agent versions window no longer says "most specific wins".

## [2026.10.2] - 2026-10-18

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install`, then
restart Claude Code and the dashboard (**⏻ stop dashboard**, then start it
again). If you installed from a copy of the repository, `git pull` there
instead of the first command. PIs: if your lab has no `policy/millwright.yaml`
yet, run `murmurent jobs policy --init` and commit it.

### Added
- **Your profile follows you, and reaches the lab roster** (#187). A member's
  profile edits are saved in their personal vault, so their other machines see
  them, and sent to the PI as an issue on the lab management repo. The PI's
  `murmurent reconcile --apply` adds them to the roster, only when the issue
  was opened from that member's own GitHub account. The dashboard updates the
  roster and the vault when it starts and every 15 minutes. Each settings
  window says whether its settings apply to this machine, to you everywhere,
  or to the whole lab.
- **Agent versions at five levels** (#186): your version for one project, the
  project's, yours for all projects, the lab's, the centre's. A person's own
  version beats the lab's; the guardians always use the centre's. Switch an
  agent off in one project. On the dashboard, each agent card's **versions**
  button does all of this; in a terminal, `murmurent agent fork --project`,
  `agent off` / `on`, `agent share --lab` and `agent sync`. Guide: [Choosing
  an agent's version](https://mikehallett.science/murmurent/agent_versions/).
- **Server etiquette check** (#151): `murmurent etiquette check` reports lab
  members running above nice 19, over their cores, or over the GPU allowance
  for the time of day, and with `--notify` messages them politely (the person,
  then the lab channel, then the PI). It never reads command lines or changes
  anyone's jobs. `murmurent etiquette schedule --install` runs it every
  weekday.
- **Browse and install published choreographies** from the dashboard's
  Choreographies panel.
- **Create a project from repos on GitHub** as well as on this machine; they
  are copied here when the project is created.
- **`murmurent project set`** sets a project's data folders, what it reads
  without owning, and its keep-until date.
- **`murmurent jobs policy --init`**, and `murmurent pi-init`, create the lab's
  policy file from the template.

### Changed
- The Projects panel marks a project **quiet** or **dormant**.
- A running job sends one Slack line, without any path, when it would fill its
  disk within a day.
- The project access check uses a project's own data folders when its record
  names any.

### Fixed
- **Lab settings sends only the fields you changed.** Before, a save could
  rewrite untouched values in `lab.md`, such as filling the lab's GitHub
  organisation from the PI's own login.
- A cleared field in a member's profile stays cleared.

## [2026.10.1] - 2026-10-18

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install`, then
restart Claude Code and the dashboard (the new **⏻ stop dashboard** button in
its top bar, then start it again). Run `murmurent repo upgrade --all` once. If
you installed from a copy of the repository, `git pull` there instead of the
first command. On a lab server that uses the security snapshot, run
`sudo bash scripts/install_security_snapshot.sh` once from that copy: it also
replaces an install made under the old name, wigamig. PIs: choose **on** or
**off** for the space audit under **⚙ Lab settings** (it is hidden until you
choose).

### Added
- **The dashboard says which version of each agent is in use** (#186). Each
  agent card shows "in use:" with the centre version, your own version, the
  project's version, a file on this machine only, a broken link, or "not
  installed", and hovering gives the reason. `murmurent agent which [--repo
  <folder>]` shows the same in a terminal.
- **Each lab and core gets a `#lab-<name>` Slack channel** (#188), whether it
  joins through a join request or the registrar creates it, and members are
  added and removed as they join, leave, are deactivated or reactivated.
  Existing channels are kept.
- **A stop button for the dashboard**, and `murmurent dashboard --stop`.
  Closing the browser window does not stop the dashboard.
- **The top bar says which murmurent is running**, for example
  `running murmurent_dev · main @ 787faca` or `running release v2026.10.1`.
- **`scripts/install_security_snapshot.sh`** installs the security snapshot on
  a lab server in one step and retires an old wigamig install.
- **Every repository is now part of a project** (#151). `murmurent repo adopt`
  records a one-repository project for a repository that no project lists,
  with you as lead; adopting again changes nothing, and an existing project is
  never changed by adopting. When such a repository later joins a bigger
  project, its one-repository project is archived, so each repository has one
  owning project. `murmurent project migrate` lists every repository and data
  folder that no project claims and proposes project records for them,
  grouping `x`, `x_manuscript` and `x_seminar` into one project. It writes
  nothing unless you add `--apply` and confirm, and it never moves, renames or
  deletes anything. Run it once on each machine.
- **`murmurent project status`** shows one project as a whole: its
  repositories, its data folders, what it reads without owning, its keep-until
  date, when it was last used, and whether it is active, quiet (no use for 12
  months) or dormant (24 months). Activity is worked out from commits,
  `murmurent run` job records and the data scan's record, never typed, and it
  does not change who can reach a project.
- **Three optional settings in a project record**: `data_folders` (the folders
  it owns; by default `immutable/<project>/` and `append_only/<project>/`),
  `reads_from` (folders and repositories it reads but does not own, which are
  never offered to it for clean-up) and `retain_until` (a date before which
  nothing in it may be suggested for deletion). Records without them read as
  before.
- **`murmurent run` starts a long job so that a dropped connection does not
  stop it, and `murmurent jobs` says how it is going** (#151). The job runs
  inside tmux (a program that keeps a command running after you disconnect),
  at the lowest priority, with the thread settings numerical libraries read set
  to the number of cores it was given. Cores and GPUs are chosen from the lab's
  rules and how busy the server is; memory and disk space are checked before it
  starts; it can start at a set time or once the server is quieter. When the job
  finishes, fails or stops producing output, one line goes to the project's
  Slack channel, giving the job's name, what happened, how long it ran and its
  exit code, never the command or a file path. `murmurent jobs` lists what is
  running and how earlier jobs ended, with time and disk estimates where there
  is something to base them on. The lab's rules live in one file in its
  management repository, `policy/millwright.yaml`; a commented example is in
  `templates/millwright_policy.yaml`. Guide: [Running long
  jobs](https://hallettmiket.github.io/murmurent/run_launcher/).
- **`murmurent space scan` lists what in a project could be deleted, compressed,
  moved or asked about** (#151). It looks through one project's repositories
  and data folders, reading sizes, dates, owners and names, and suggests:
  temporary files, job output that could be made again, uncompressed text data,
  duplicates, files out of place, files owned by non-members, and files already
  listed in `src/ready_to_delete.md`. Each row gives a reason and its evidence.
  `murmurent space show` lists the three most pressing first, and
  `murmurent space decide` records what you decide. Nothing is changed, moved or
  deleted, nothing in `immutable/` is ever suggested for deletion, and a
  project's keep-until date turns every "delete" into "keep". The table is kept
  in your own `~/.murmurent/space/`, readable by you only. The thresholds are in
  `policy/millwright.yaml`. Guide: [Tidying a project's
  space](https://hallettmiket.github.io/murmurent/space_table/).
- **A weekly lab-wide space scan, and the report on your laptop** (#151). On
  the server, `murmurent space schedule --install` runs `murmurent space
  scan-lab` every Sunday at 02:00: it scans every project's data folders and
  every folder under the data root that no project claims, suggests mothballing
  for projects unused for 24 months, and sends the PI a Slack summary with no
  file names. Other labs' folders are never scanned. On a laptop, `murmurent
  space lab --host <server>`, or the new Space page of the PI's dashboard,
  fetches the report over SSH. A full scan takes about 10 minutes per million
  files on the lab's network drive.
- **`murmurent run --input`** records what a job reads, so the space scan can
  tell later whether its output could be made again.

### Changed
- **The space audit is optional for each lab.** The PI chooses on or off in
  Lab settings; until then the dashboard does not show it. Off also makes the
  weekly scan do nothing. When it is not set up, it explains what is missing
  instead of showing raw errors.
- **The security scans check `immutable/`, `append_only/` and `modifiable/`**,
  as well as the old `raw/` and `refined/`. Files in `immutable/` must be
  read-only on disk.
- **Dashboard tidied** (#185): the live agent feed, My contributions,
  Inventory, the compliance panels and Installations are gone. "Create new
  project" is simpler: a description instead of a justification, no machines
  or git provider fields, the PI's own project is created at once, the chosen
  repos are made murmurent-ready automatically, and the repo list is
  rescanned. Repos are grouped by project. "space" and "security" are now
  "space audit" and "security audit".
- **The update banner speaks in words**: "Murmurent 2026.10.2 is available", or
  "murmurent_dev has 3 new changes on GitHub", with the change titles, instead
  of commit codes.
- **Both READMEs link to the documentation** at
  <https://mikehallett.science/murmurent/> near the top.

### Fixed
- **The released murmurent's dashboard showed only an error** ("static dir
  not found"). Its pages were left out of the release and of the installed
  package; both now include them.
- **The update button updated the wrong copy** when the dashboard ran from
  murmurent_dev, and could report success without restarting.
- **The agent card's disable switch and model menu edited the shared agent
  file**, changing the agent for everyone linked to it. They now make your own
  copy, as the Modify window does, and never overwrite a hand-written one.
- **Approving a project built from existing repos reported a failed
  git-remote step.** Each repo now keeps its own remote.
- **Profile and lab settings saves** go to the person whose page is open, and
  say when an edit is saved on this computer only or did not reach the lab's
  repository.
- **Files anyone can write in a data folder are marked as blocking** by the
  security scan; the check never matched before.
- **The dashboard now says when your identity card has expired.** Before, the
  sign-in page accepted you, the dashboard was then refused, and you landed back
  on the sign-in page with no reason given. Now the sign-in page checks your
  card first and, if it has expired, says on which date and gives the command
  that renews it: `murmurent pi-init <lab>` for a PI, or a new card from the PI
  for a member. A member whose own card is fine but whose PI's card (which their
  card carries) has expired is told so. In the two weeks before a card expires,
  the sign-in page shows a warning with the same command.

## [2026.10.0] - 2026-10-14

**To upgrade:** `uv tool upgrade murmurent`, then `murmurent install`, then
restart Claude Code. Then run `murmurent repo upgrade --all` once, which keeps
your folders' agent links out of git (#150). If you installed from a copy of
the repository, `git pull` there instead of the first command.

### Fixed
- **Agent links in a project folder are no longer committed** (#150). The
  links `murmurent repo adopt` makes in `.claude/agents/` point into your own
  home folder, so a committed link broke those agents for everyone else in the
  project. `adopt` now lists each link in `.gitignore`, both push commands leave
  them out, and `murmurent repo status` names any already committed and how to
  repair them. Run `murmurent repo upgrade <folder>` in each folder you have set
  up to add the `.gitignore` lines. Also fixed: adopting a folder replaced a
  group's own agent file with a link when the two had the same name.
- **A fresh install from PyPI now works fully** (#159). Three problems are
  fixed. The four murmurent data services (Oracle, data, core data and
  inventory) failed to start because a fresh install picked up version 2 of
  the `mcp` library, which they do not support yet; murmurent now asks for
  version 1. The agent activity log looked for a script in
  `~/repos/murmurent`, which only exists if you copied the repository; the
  script now ships inside the package. And the plain-English writing style
  was not installed; `murmurent setup` now links it. If you installed with
  `uv`, run `uv tool upgrade murmurent`, then `murmurent install`, then
  restart Claude Code.

### Added
- **`/murmurent-update-me` posts a status update for any project** (#152). It
  reports what is running, what finished since the last update, what is blocked
  and on whom, and the next steps, to the project's Slack channel. Built and used
  in the survival project first; most projects need no settings, and an
  optional `update_me:` block in `.murmurent.yaml` changes the defaults.
- **The adversary checks written-up prediction models and marker studies
  against TRIPOD+AI, PROBAST+AI and REMARK** (#155). Missing reporting items
  get their own section and never on their own fail a method; a high risk of
  bias does count. Work that predicts nothing about a person is left alone.
  The checklists ship as a reference page, [Reporting
  checklists](https://hallettmiket.github.io/murmurent/reporting_guidelines/).
- **Every install now gets a Murmurent Dashboard icon** (#156). `murmurent
  install` creates it: in Applications on a Mac, in the applications menu on
  Linux. Until now only installs from a copy of the repository got one, and
  nobody was told. A new command, `murmurent launcher`, re-creates it, and
  `murmurent launcher --remove` deletes it. `murmurent doctor` says whether it
  is there. Windows has no icon yet. `Open Dashboard.command` is retired; use
  the icon.

### Changed
- **You choose where your repositories live** (#166). Murmurent no longer
  assumes `~/repos`: `murmurent init` asks, `murmurent config repos-root`
  shows or changes it, the dashboard's "this machine" settings have a field
  for it, and `murmurent doctor` reports it. Nothing changes for anyone
  already using `~/repos`.
- **A project's repositories can sit in one folder** (#166). New projects go in
  a project folder, `<repositories>/<project>/<project>`, with the manuscript
  and seminar repositories beside the code; `seminar` is a new repository
  role. The flat layout stays fully supported and nobody has to move.
  `murmurent config project-layout flat` keeps new projects flat;
  `murmurent project gather <project>` moves an existing project into a folder
  (it shows its plan first and moves nothing without `--yes`).
- **Project records no longer hold one member's folder paths** (#166). Each
  computer finds its own copy of a project's repositories, so a path recorded
  by one member no longer sends everyone else's tools into that member's home
  folder.
- **"Ready" now means the folder has a `.murmurent.yaml` file, and nothing
  else** (from PR #167, found by emucaki). The check also required a
  `.claude/agents/` folder, which `adopt` always creates, so it could never
  fail. Agents in that folder make no difference: every agent already works in
  every folder. "Half set up" now means only a folder set up by a very old
  Murmurent; `murmurent repo upgrade` finishes it. The help for `--agents` and
  `--all-agents` now says they pin agents to one folder and are rarely needed.
- **Project Slack channels are named `proj-<project>`** (#157). Projects made
  with certificates were getting a channel named after the project alone. A
  new command, `murmurent project rename-slack <project>`, renames an existing
  channel to the `proj-` name, or to any name with `--to`.
- **`murmurent install` turns off Claude Code's feedback survey** (#154), which
  interrupted sessions to ask for a rating. A member who has set
  `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` themselves keeps their own setting.

## [2026.9.9] - 2026-09-25

### Changed
- **Two agents have new names.** `cable_guy` is now `millwright`, and
  `centre_cable_guy` is now `centre_millwright`, matching the gender-neutral
  names in the manuscript. Address them as the Millwright and the Centre
  Millwright. Their work is unchanged. `murmurent install` removes the old
  entries from `~/.claude/agents/`; if you work from a clone, re-run
  `bash scripts/setup.sh`, which now does the same. Restart Claude Code
  afterwards so it lists the new names.

### Added
- **A voice rule, `rules/voice.md`, loaded in every session.** It says to read
  the Plain English guidelines before writing anything a person will read,
  because the output style applies only when a member has selected it, and
  never to agents working on their own.
- **Research-ethics sources for the conscience.** TCPS 2 Chapter 9, OCAP,
  SAGER and the CIHR sex-and-gender requirement are now in
  `docs/edid_resources.md`, with further sources on accessibility, medical
  eponyms, and cancer data for First Nations, Inuit and Métis peoples.

### Added
- **`murmurent choreography init <name>`, and ＋ new choreography on the
  dashboard, start a choreography from nothing.** One action creates the
  repository with the lab's folder layout, starts git, makes it murmurent-ready,
  declares `kind: choreography` in `.murmurent.yaml`, poses the question, creates
  the data folders, makes the first commit, and files a project request naming
  the repository. Approving the request creates the GitHub repository, the Slack
  channel and the lead card, as for any project. The command asks for anything
  left out and shows the plan before acting; both finish with a list of what is
  left. See `docs/starting_a_choreography.md`.
- A question file may now name its repository (`repo:`), and the dashboard card
  shows it.

### Fixed
- **`repo upgrade` erased a choreography's declaration.** It, and
  `repo adopt --agents`/`--all-agents` on a ready repo, rewrote
  `.murmurent.yaml` with the readiness fields only, so `kind: choreography`
  and everything after it were lost and `choreography install` then refused the
  repo. The marker now keeps every field readiness does not own.

### Changed
- **The user-facing README is rewritten and reorganised**, from 428 lines to
  201. It now follows the Plain English output style, so it has no em dashes
  and defines each term where it first appears. The structure is six numbered
  steps with a table of contents at the top: install, say who you are, set up
  a folder, keep it up to date, what to do next, getting help. The role
  sections that made every reader scroll past the other roles are replaced by
  one routing table, "what you are doing" against "where to go".
  It also now describes what setting up a folder actually does, which is to
  turn on the check on sensitive data, rather than repeating the claim that it
  gives access to the agents.
- Two procedures moved out of the README rather than being dropped, since
  neither was documented anywhere else:
  - `murmurent centre-init`, its fifteen options and the four steps that make a
    centre joinable, are now in `docs/centre_overview.md` under "Starting a new
    centre".
  - How a PI finds their centre in the public directory and sends an encrypted
    join request is now in `docs/identity.md`, which already covered the rest
    of that exchange but not the discovery step.

### Fixed
- **Corrected what "murmurent-ready" is documented to do.** Both READMEs and
  `docs/ready_vs_projects.md` said readiness "wires the commons agents into the
  repo so Claude Code sessions opened there can use them" — the one thing it
  does not do. `murmurent setup` links the whole commons into
  `~/.claude/agents/`, which Claude Code loads in *every* directory, so every
  agent is available everywhere regardless. Verified: `murmurent_dev` has no
  `.claude/agents/` directory at all and every agent is available in a session
  there.
  What readiness actually turns on, now documented in that order: **the PHI
  check** (`hooks/phi_check.py` redacts patient identifiers from outbound tool
  calls, and returns early — doing nothing — when there is no marker to
  resolve a project from), project attribution in the audit log, attaching the
  repo to a project, and `sensitivity: clinical`. The first of those is the
  reason to make a folder ready and had been omitted entirely.
- **The in-session readiness notice no longer reports agents "not linked into
  this repo".** They are usable there anyway, so the notice implied a problem
  that did not exist and sent the reader to run a command with no observable
  effect. It now reports only a repo whose agent files point into a *different*
  murmurent than the one installed — which does change behaviour, silently,
  because Claude Code prefers a directory's own agent file.
- Both READMEs now give the simplest form of each step: `murmurent repo adopt
  ~/repos/<folder>` with no options, and no per-directory command after an
  upgrade. Agent-pinning, `--agents`/`--all-agents`, and the fact that per-repo
  agent symlinks are absolute paths that break on another machine moved to
  `docs/ready_vs_projects.md`.

### Changed
- **`murmurent repo status` verdicts say what they mean.** `• clone` named
  git's concept rather than the reader's situation and gave no hint what to do
  next; it is now `• not set up yet`. Likewise `± partial` → `± half set up`,
  `✗ not a git repo` → `✗ not tracked by git`, `✗ missing` → `✗ no such
  folder`. Internal verdict names are unchanged, so the dashboard and
  `core/adopt.py` are unaffected.
- The ready-a-directory section of both READMEs is a case-by-case table —
  every verdict, what it means, the one command to run — instead of two
  paragraphs of preamble before the table.

### Added
- **`murmurent repo adopt --all-agents`**, so setting a directory up with the
  agents is one command. Previously `adopt` took `--agents a,b,c` or linked
  nothing, which meant the documentation had to tell a newcomer to type a
  specific pair of agent names for no stated reason, and a bare `adopt` left an
  empty `.claude/agents/` that only surfaced later as a missing agent. It fails
  loudly if no commons is found rather than making the repo ready with nothing.

### Changed
- **The development README is rewritten for its actual readers** — biomedical
  scientists, not software engineers. The previous version stated true things
  with no context and no gloss ("`setup.sh` symlinks rather than copies…", "how
  to confirm you are reading this clone's commons and not a packaged copy"), and
  used headings that were engineer shorthand ("How a change gets in", "Before
  you push", "Cutting a release"). Sections are now named as the reader's own
  question and explain why before what: *I changed something. How do I make it
  part of Murmurent?*, *Publishing a new version for everyone to download*,
  *Which README to edit*. Every Murmurent-specific term — the commons, the
  publishable-files list, a branch, a pull request, a test — gets a
  one-sentence definition where it first appears.
  Removed: *Exercising Murmurent without real people*, which answered a question
  nobody asked, and the test-suite pass/fail statistics from one machine, which
  no reader could act on.

### Fixed
- **`repo adopt` and `repo upgrade` now resolve the commons the way the rest of
  the CLI does** (`core.commons.commons_root()` instead of the hardcoded
  `~/repos/murmurent` in `core.repo.murmurent_repo_root()`). On a machine
  holding both a release clone and a development one the two disagreed, so
  `murmurent doctor` truthfully reported reading the commons from
  `murmurent_dev` while a repo adopted seconds earlier was linked into
  `~/repos/murmurent`: an agent edited in the clone under development was live
  in `~/.claude/agents/` and silently absent from the repo. The rule is now one
  rule everywhere — *the clone you installed is the clone your repos follow* —
  and the `$MURMURENT_REPO_ROOT` workaround is no longer needed.
- **`murmurent repo status` prints which commons a repo follows**, and flags a
  repo following a different one. Previously discoverable only by running
  `readlink` on a symlink by hand.

### Added
- **A murmurent-ready repo now says when its wiring has fallen behind**, through
  the existing `UserPromptSubmit` hook (`hooks/context_inject.py`), so it
  appears the moment you start working rather than requiring you to go and ask.
  It reports the two states that are both actionable and otherwise silent:
  commons agents this repo has no link to (the shape a newly added agent takes,
  since nothing retro-fits links), and links resolving into a different commons.
  Keyed on the `.murmurent.yaml` marker rather than on a CHARTER, so it covers
  every ready repo and not only project repos.
  **Deliberately not reported:** a `bootstrap_version` that merely differs from
  the running version. `repo_ready.needs_upgrade` is true after every release,
  including one that changed nothing for the repo, so notifying on it would put
  a line in front of the user on every prompt after every upgrade and teach them
  to ignore the notice.
- **Bare `murmurent install` now finishes by re-linking every murmurent-ready
  repo on the machine**, so an upgrade reaches the repos people work in instead
  of stopping at `~/.claude/`. `--hooks` is unchanged (hooks only). It re-links
  the roster each repo already chose and does **not** add agents new in the
  release: that changes what a repo is, and the readiness notice above plus
  `repo upgrade --all-agents` makes it an opt-in.
  The automatic pass is restricted to repos that already carry a marker. The
  first run of it on a real machine stamped a marker and a `.vscode/` onto a
  years-old repo whose only bootstrap was a legacy `CHARTER.md` — turning an
  upgrade into an adoption and leaving untracked files in a repo whose owner had
  asked for nothing. A hand-typed `repo upgrade --all` still migrates those.

### Added
- **Both READMEs now cover making a directory Murmurent-ready and keeping it
  current**, which neither said completely. The ready-a-directory section states
  the three starting points (plain folder, long-lived repo, repo set up by an
  older release) as one procedure keyed on `murmurent repo status`, and names
  two things the verdict does not: `adopt` refuses a path outside `~/repos/`,
  and a bare `adopt` leaves `.claude/agents/` **empty** unless you pass
  `--agents` (the README previously described it as writing "a `.claude/agents/`
  folder of symlinks", which is only true when you ask for agents).
- **An upgrade is two halves** — the install, then the repos wired to it — and
  the READMEs now say which changes need no command at all. Agent, rule and
  skill *text* is live immediately because everything is symlinks; only
  structural change (a new agent file, a marker-schema bump, a version bump)
  needs `setup` / `install` / `repo upgrade`. Each README carries the table.
- `DEVELOPING.md` records a defect found while verifying the above: `repo adopt`
  and `repo upgrade` resolve the commons through
  `core.repo.murmurent_repo_root()` (hardcoded `~/repos/murmurent`, overridable
  with `$MURMURENT_REPO_ROOT`), while `setup` / `install` / `doctor` use
  `core.commons.commons_root()` (the clone you are running from). On a machine
  holding both clones they disagree silently: an agent edited in the dev clone
  is live in `~/.claude/agents/` and absent from an adopted repo. Documented
  with the `MURMURENT_REPO_ROOT` workaround rather than fixed in passing —
  changing the fallback moves where every adopted repo's links point.

### Changed
- **The two repositories no longer share one README.** `README.md` here is now
  the development repository's landing page — what the repo is, where everything
  lives, how a change becomes a pull request, how the suite is run, and how a
  release is cut. The user-facing README moved to `release/README_public.md`,
  which `release/make_release.sh` copies into the release tree as `README.md`
  (and which PyPI therefore renders as the project page). One README could not
  be both: the development repo's front page opened with install instructions
  for software nobody installs from it, and the member / PI / mayor onboarding
  flows were the first thing a would-be contributor read.
- `tests/test_release_hygiene.py` scans the release README even though its path
  is withheld, because its *content* ships. Without that, the one file every
  visitor reads was the only shipping text nothing checked for private repos,
  grant documents or Slack IDs. A second test asserts the file exists and that
  the development README is not in the shipping set.
- `DEVELOPING.md` and `README.md` now run pytest and the commons check through
  `uv run --python 3.12`. A bare `python3` is frequently a conda `base` — below
  the 3.12 floor and without fastapi, slack-sdk or mcp — where the suite
  reported 41 collection errors and the commons check reported
  `ModuleNotFoundError`, both of which read as real breakage and are not.

## [2026.9.8] — 2026-09-04

### Changed
- README (shared by the release and development repositories) and the
  documentation home page now point at `murmurent_public` as the directory that
  holds the **index of all published choreographies** (`choreographies.tsv`),
  alongside the institution list, and name the two commands that read it.

## [2026.9.7] — 2026-09-04

### Fixed
- **The author email in README was still the placeholder on the release
  repository.** The development repository had it right since 2026.9.6, and no
  release had gone out since, so the public page never changed. This release
  carries it, and the test fixture that used a real name with the placeholder
  domain now uses `@the_pi`.
- **README links go to the documentation website**
  (<https://hallettmiket.github.io/murmurent/>) instead of to the raw
  Markdown under `docs/` on GitHub. The public site itself had never built: its
  strict MkDocs build failed on 2026-09-01 over relative `agents/` links that
  were fixed in development on 2026-09-02 and ship here for the first time.
  `release/make_release.sh` now asks the public repository to rebuild the docs
  after every push, since a squashed release commit does not reliably trigger
  the path-filtered workflow on its own.

### Added
- **`murmurent doctor` is real.** It checks the Python version, whether the
  `pip` and `python` on PATH belong to the interpreter murmurent runs under,
  the agent/rule/skill links in `~/.claude/` (dangling ones included), the
  registered hooks and the interpreter they call, and whether a clone's
  `origin` can still `git pull`. Each failure prints the one command that
  fixes it. Every check corresponds to a way a real install went wrong
  silently: a `pip install -e .` from a conda `base` shell refused with
  "requires a different Python"; a development clone left pointing at the
  release repository after the split; a symlink to an agent that had left the
  commons.
- **Initializing a directory is documented from the status check down.**
  README, `docs/setup.md` and `docs/ready_vs_projects.md` now open with
  `murmurent repo status` and a verdict table (plain folder, plain clone,
  ready-but-old, ready), so nothing assumes the directory is or is not already
  ready. README and `docs/setup.md` gain an **Upgrading** section;
  `DEVELOPING.md` gains one for a development clone.

### Changed
- `murmurent setup` and `scripts/setup.sh` remove symlinks in `~/.claude/`
  that point into the commons at a file that no longer exists (an agent
  retired from the commons). Links into a personal vault or anywhere else are
  left as they are.
- `murmurent repo adopt` on a folder without `.git/` now says to run
  `git init` first, instead of only reporting that it is not a working tree.

## [2026.9.6] — 2026-09-04

### Added
- **The public choreography index is published**, which was the third piece of
  #136 and was waiting on a choreography having a public release. It lives at
  `choreographies.tsv` in `murmurent_public` and carries **locations only**:
  one `name<TAB>git_url` row, no titles or summaries, because everything a
  reader is shown is read from the choreography's own `.murmurent.yaml` and a
  second copy would drift. First entry: `inhibition`
  ([tt8804/inhibition_public](https://github.com/tt8804/inhibition_public)).
- **`murmurent choreography install <name>`** now resolves a published
  choreography's name through that index. A bare name used to be refused
  outright, which left `list` showing things that could not then be installed
  the way they were named.

### Changed
- Every failure to read the index now names the URL route, not only the 404
  case. Offline, or inside one lab with a choreography that was never
  published, the index is not needed and should not be in the way.
- An index row with a name but no URL is dropped rather than listed, so a
  half-filled row can never be offered as something to install.

## [2026.9.5] — 2026-09-02

### Added
- **`murmurent choreography install <git-url>`** — clone a choreography, read
  what it says about itself, report any agent it needs that this machine has
  not got, and make it murmurent-ready. Thin by design: it hands the clone to
  the existing `repo adopt` path rather than re-implementing readiness.
- **`murmurent choreography list`** — read the public index. The index is not
  published yet, so it says so and points at the URL route instead of failing.
- **A choreography declares itself** in `.murmurent.yaml` with
  `kind: choreography`. A repository that does not is refused, with a pointer
  to `murmurent repo adopt`: treating any cloned repository as a choreography
  would install arbitrary code as one.
- `docs/choreography.md` documents discovery and installation, which it did not
  mention at all.

## [2026.9.4] — 2026-09-01

### Fixed
- **An editable clone at any path is now found.** `commons_root()` only
  consulted `~/repos/murmurent`, so a developer who cloned to
  `~/repos/murmurent_dev` — which `DEVELOPING.md` tells them to do — silently
  read the packaged commons instead of their own clone, edited an agent and saw
  no effect, with no error anywhere.
- `murmurent install` no longer prints "Next: murmurent install --hooks" and
  then immediately runs the hooks itself.

### Changed
- README: the PyPI route now says to install `uv` first (the one-command route
  does that for you; the PyPI route did not, and `uv: command not found` was
  the first thing a new user would hit).
- README: the two-repository section now reads correctly from **either** repo,
  since both share this file, and says where to file issues.

## [2026.9.3] — 2026-09-01

### Added
- **`uv tool install murmurent` is now a complete install.** The wheel
  force-includes the commons (`agents/`, `rules/`, `skills/`, `templates/`,
  `CLAUDE.md`) under `murmurent/commons/`; `core/commons.py` resolves them, and
  a new `murmurent setup` wires them into `~/.claude/`. No clone and no
  `curl | bash` required. A clone still wins over the packaged copy, decided by
  content rather than by name, so editing an agent in a clone takes effect at
  once and an empty directory from a failed clone cannot win.

### Changed
- **`murmurent install` with no flags now performs the whole install** (wire
  the commons, then register hooks) instead of printing "not yet implemented in
  v1". `--hooks` still means hooks only, so `scripts/bootstrap.sh` and existing
  callers are unaffected.
- Licence metadata is Apache-2.0 throughout, with a matching PyPI classifier.

## [2026.9.2] — 2026-09-01

### Added
- **PyPI publishing** via `.github/workflows/publish.yml`, using trusted
  publishing (no stored token). The build job runs on every release; the
  upload job is gated on the `PYPI_ENABLED` repository variable so it is
  visibly skipped rather than silently absent until PyPI is configured.
- **`DEVELOPING.md`** (development repository only): the dev setup, what
  `rules/local/` is for, the pre-push checks, and how a release is cut.

### Changed
- `README.md` now says plainly that this repository carries released versions
  only, and points bug reports at the development repository's issues.

## [2026.9.1] — 2026-09-01

### Fixed
- **Author email in the package metadata was wrong** (`hallett.mike.t@gmail.com`);
  it is `michael.hallett@uwo.ca`. This shipped in 2026.9.0 and would have been
  the contact address on PyPI.
- **Licence metadata contradicted the licence.** `pyproject.toml` declared MIT
  while `LICENSE` is, and has always been, Apache-2.0. The metadata now matches
  the file. No licence has changed; the declaration was wrong.

## [2026.9.0] — 2026-09-01

**First public release.** Development moves to `murmurent_dev`; this repo now
carries released versions only, one commit per release.

### Added
- **`murmurent keyring`** — distribute a centre's shared secrets (the Slack token,
  and later the onboarding age key) across a principal's machines via per-machine
  `age` identities and multi-recipient `age` boxes committed to the `lab_info`
  repo, locked **per role** so a `server` machine cannot open a `mayor`-only box
  (e.g. the root CA). Commands: `init`, `authorize`, `set-secret`,
  `rotate-secret`, `revoke`, `sync`, `status`, `check`, `verify`. Self-heals via
  `murmurent reconcile`. Introduces a `.keyring/` store under `lab_info`. Design
  and runbooks in [`docs/keyring.md`](docs/keyring.md) /
  [`docs/keyring_deploy.md`](docs/keyring_deploy.md).
- **`rules/local/`** — a deployment layer for facts true of one centre only
  (its own private repos, Slack IDs, local conventions). `scripts/setup.sh`
  symlinks these alongside the shared rules when the directory exists; a clone
  without one simply skips it.

### Changed
- `CLAUDE.md` is institution-agnostic: no hardcoded university, GitHub owner
  written as `<owner>`, and no reference to any one centre's private repos.
- `rules/slack.md` carries the posting protocol only. The channel, workspace
  and bot are deployment facts and belong in `rules/local/`.

### Fixed
- **Slack notifications no longer default to one lab's channel.**
  `dashboard/slack_notify.py` and `commands/reconcile_cmd.py` each hardcoded a
  channel ID as the last-resort destination for every notification, so any
  installation would have posted there. Both now resolve from
  `MURMURENT_SLACK_DEFAULT_CHANNEL` / `MURMURENT_SLACK_INFRA_CHANNEL` or
  `~/.config/murmurent/`, and decline to post when unset.

## [2026.7.0] — 2026-07-16

First numbered release. Establishes version tracking itself (issue #24):

### Changed
- **Single source of truth for the version.** `pyproject.toml` now reads
  `__version__` from `src/murmurent/__init__.py` via Hatchling's
  `[tool.hatch.version]`, so the package metadata, `murmurent --version`, and
  the `bootstrap_version` stamped into every repo's `.murmurent.yaml` can no
  longer disagree. Previously `pyproject.toml` said `1.0.0` while the runtime
  reported `0.1.0`.
- **Adopted CalVer** (`YYYY.M.MICRO`), bumped only on structural releases and
  tied to the `murmurent repo upgrade` mechanism: if the version changed, run
  `murmurent repo upgrade --all`; if it didn't, you're current.

### Notes
- Because `Readiness.needs_upgrade` compares the stamped `bootstrap_version`
  against the current version by string inequality, existing murmurent-ready
  repos (stamped `0.1.0`) will show `needs_upgrade = True` once. That's the
  intended "a new release shipped" signal — run `murmurent repo upgrade --all`
  to re-stamp them. Harmless if you don't; agent content is already current via
  the symlinks.
- The on-disk/on-wire schema versions (`MARKER_SCHEMA`, `CARD_VERSION`,
  `SIGNED_CARD_VERSION`) are versioned independently of this release number and
  bump only when their own format changes.
