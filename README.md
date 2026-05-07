# wigamig

Group-level agentic infrastructure for the Hallett bioconvergence center.

A multi-tier configuration hub that lets multiple research groups share a common
agent registry, role registry, and choreography catalog while running their own
projects. See `CLAUDE.md` for the architectural overview and `docs/group_level.md`
for the full design.

## Status

Phase 1 of the v1 smoke-test build. See `docs/implementation_prompt_phase_1_foundation.md`.

## Install (developer)

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and `gh` CLI.

```bash
uv sync --extra dev
uv run wigamig --help
```

## Running tests

```bash
uv run pytest
```

## Authors

Mike Hallett &mdash; hallett.mike.t@gmail.com
