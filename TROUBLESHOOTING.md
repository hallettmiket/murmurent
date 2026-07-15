# murmurent troubleshooting

> Common smoke-test failure modes and how to recover.

## `murmurent: command not found`

The console-script entry point isn't on your PATH. Either:

```bash
uv run murmurent <args>
# or, for the rest of the session:
uv pip install -e ~/repos/murmurent
```

## Hooks don't fire in Claude Code

1. Did you run `murmurent install --hooks`? Check `~/.claude/settings.json` —
   the `hooks` block must contain murmurent entries (matchers and command
   strings starting with `python -m murmurent.hooks.*`).
2. Did you restart Claude Code after the install? Settings are read at
   startup.
3. Is the python on your PATH the same one that has murmurent installed?
   The install rewrites the hook command using `sys.executable`. If you
   later move to a different Python, re-run `murmurent install --hooks`.

Quick verification without restarting CC:

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":"~/lab_vm/data/raw/x"}}' \
    | python -m murmurent.hooks.raw_guard
# -> {"decision":"deny","reason":"raw data is read-only ..."}
```

## Inventory MCP not visible to CC

1. Confirm `mcpServers.wigamig-inventory` is in `~/.claude/settings.json`.
2. The MCP is invoked as `python -m murmurent.mcp.inventory_server`. The
   path must be the same Python that has `murmurent` and `mcp>=1.0`
   installed. Re-run `uv sync --extra mcp` if needed.
3. `gh auth status` doesn't matter here; the MCP reads markdown files.

To verify the MCP tool layer without CC:

```bash
python -c "from murmurent.mcp.inventory_server import tool_list; \
import json; print(json.dumps(tool_list('low'), indent=2))"
```

## `murmurent push --finalize` fails

Symptom: `gh pr create` errors with `no commits between main and ...`.

Causes:

- You're already on `main` (refused by design).
- The personal branch has no commits ahead of `main`. Make a change, commit, then re-run.
- The project repo doesn't exist on GitHub. Either:
  - Re-run the seed *without* `--skip-github`, **or**
  - `gh repo create hallettmiket/<project> --private --source=. --push`.

## PHI hook fires when it shouldn't

Likely false positive on the OHIP pattern (any 4-3-3 digit sequence). The
hook is intentionally conservative — favours false-positives over silent
leakage. If the string is genuinely not PHI, replace it before the prompt
or invoke a non-outbound tool.

## PHI hook *doesn't* fire when it should

The hook checks `cwd` for an active project. Run from inside the project
repo. If you're outside, no project context is resolved and the hook is
permissive.

## Raw-data guard denies a legitimate copy

By design — *any* mutation of `$MURMURENT_LAB_VM_ROOT/raw/` is refused. Use
`murmurent experiment ingest` for the controlled copy path. If you really
need to drop a raw file ad-hoc, do it via shell with the hook disabled
(comment it out in `~/.claude/settings.json` for that session) and *then*
re-enable. The design refuses to bypass this from CC.

## Dashboard shows nothing

```bash
python scripts/generate_dashboard.py
ls ~/repos/murmurent_lab_mgmt_<lab>/dashboards/
```

The Streamlit app reads from these files. If you haven't seeded yet:

```bash
python scripts/seed_tutorial.py --skip-github
```

Re-seed is safe — it's idempotent.

## Streamlit not installed

```bash
uv sync --extra dashboard
# or
uv pip install streamlit
```

`murmurent dashboard --snapshot` works without streamlit; only the live view
needs it.

## SEA id ambiguity

SEA IDs are *per-project*. If `murmurent sea claim 3` errors with
"ambiguous", pass `--project <name>` explicitly.

## Audit log isn't being written

Check `~/.claude/murmurent-audit/`. If the hook isn't firing, see "Hooks
don't fire in Claude Code" above. The audit hook silently swallows
internal failures (it must never block tool calls), so a mis-configured
audit dir won't surface as an error message.

## Onboarding a fresh machine

```bash
git clone git@github.com:hallettmiket/murmurent
cd murmurent
uv sync --extra dev --extra mcp --extra dashboard
uv pip install -e .
git clone git@github.com:hallettmiket/murmurent_lab_mgmt_mh ~/repos/murmurent_lab_mgmt_mh
git clone git@github.com:hallettmiket/dcis_sc_tutorial ~/repos/
git clone git@github.com:hallettmiket/bbb_drug_screen ~/repos/
murmurent install --hooks
```

If you don't have access to the private repos, run
`python scripts/seed_tutorial.py --skip-github` to recreate them locally.

## Still stuck?

File a smoke-test issue with the template at
[.github/ISSUE_TEMPLATE/smoke_test.md](.github/ISSUE_TEMPLATE/smoke_test.md).
Include the exact command, the error output, and what you expected.
