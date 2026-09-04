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
