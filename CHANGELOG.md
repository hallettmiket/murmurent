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
