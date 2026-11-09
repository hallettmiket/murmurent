# Versioning

Murmurent uses **CalVer**: `YYYY.M.MICRO` (e.g. `2026.7.0`). This page is the
policy; the running record of releases is [`CHANGELOG.md`](https://github.com/hallettmiket/murmurent/blob/main/CHANGELOG.md).

## One number, one place

The version lives in exactly one place: the `__version__` string in
[`src/murmurent/__init__.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/__init__.py). Everything else
reads from there:

- `pyproject.toml` declares `dynamic = ["version"]` and points
  `[tool.hatch.version]` at `__init__.py`, so the package metadata is never a
  second hand-maintained copy (it used to be maintained separately and
  drifted, with `pyproject.toml` and `murmurent --version` reporting
  different versions).
- `murmurent --version` prints `__version__` (via `cli.py`).
- `core.repo_ready` records `__version__` per machine
  (`~/.murmurent/repo_bootstrap.yaml`) as the release that last linked each
  murmurent-ready repo; it is no longer written into the committed
  `.murmurent.yaml` (#257).
- `Remote.murmurent_version()` reads `murmurent --version` over SSH to detect
  cross-machine drift (`host doctor`, the dashboard host health check).

**To cut a release, edit that one string.** Nothing else.

## Why CalVer, and when to bump

Murmurent isn't a library other packages pin against: it's installed by
`git clone` + `uv tool install -e .`, and lab members track `main`. What they
care about is "how stale is my install" and "do I need to run `repo upgrade`",
not SemVer's API-compatibility promise. CalVer answers the first directly.

The bump policy is tied to the upgrade mechanism:

- **Bump on a *structural* release**: a new commons agent, a marker/schema
  change, a changed CLAUDE.md bootstrap stub: anything that should make existing
  murmurent-ready repos want `murmurent repo upgrade`. Add a `CHANGELOG.md`
  entry and tag it.
- **Do NOT bump for agent-content edits**: a tweak to an agent prompt, a rule's
  wording, docs. Those reach every ready repo automatically through the
  `.claude/agents` symlinks into the commons clone; forcing a `repo upgrade`
  would be pure operator noise.

So the version bump carries real meaning: **if the version changed, run
`murmurent repo upgrade --all`; if it didn't, you're already current.**

`MICRO` starts at `0` and increments for a second structural release in the same
month (`2026.7.0` → `2026.7.1`); the next month resets (`2026.8.0`).

> Note: `Readiness.needs_upgrade` compares the release recorded for a repo on
> this machine against the current version by **string inequality**, not "is
> older than". So any version change flips every already-bootstrapped repo to
> `needs_upgrade = True` once: the intended "a release shipped" signal.
> `murmurent install` re-links every ready repo and records the new release;
> `murmurent repo upgrade --all` does the same by hand.

## Releasing

Lightweight: there's no PyPI publish, so a "release" is a pointer for humans and
for the `repo upgrade` signal:

1. Edit `__version__` in `src/murmurent/__init__.py`.
2. Move the `[Unreleased]` notes in `CHANGELOG.md` into a dated
   `[YYYY.M.MICRO]` section.
3. Commit, then annotate + push a tag: `git tag -a v2026.7.0 -m "…"` &&
   `git push --tags`.
4. Cut a GitHub Release from the tag (its notes can be the CHANGELOG section).
5. Add a line to `news:` in `training/index.yaml` for the release, then run
   `python3 training/front_page.py`, which rewrites the "Videos and news"
   section of both READMEs and the videos page on the site (commit the page in
   the website repository). A test fails if the section is stale.
6. Re-render every training movie whose agent changed since it was made:
   `training/index.yaml` stamps each movie with the hash of its `agents/<x>.md`;
   `python3 training/agents/<x>/make.py` re-renders and re-voices one, and
   `training/README.md` says how to publish it. A movie that shows an older
   agent is worse than no movie.

## Schema versions are NOT the release version

Three integers version on-disk / on-wire artifact **formats**, and bump only
when their own shape changes, never to match a release:

- `MARKER_SCHEMA` (`core/repo_ready.py`): the `.murmurent.yaml` marker shape.
- `CARD_VERSION` (`core/identity_card.py`): the identity-card shape.
- `SIGNED_CARD_VERSION` (`core/idcert.py`): the signed-card shape.

Keep them independent of `__version__`.
