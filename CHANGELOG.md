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
