# Reconciliation routine

`murmurent reconcile` compares murmurent's recorded state to on-disk
reality across every registered host and reports drift. Default is
dry-run; `--apply` repairs the actionable subset.

## What counts as drift

| Kind | Severity | Auto-repair? | Repair action |
|---|---|---|---|
| `orphan_installation` | actionable | ✓ | Move `~/.murmurent/installations/<name>.yaml` into `installations/.archive/<name>_<date>.yaml` |
| `orphan_registry` | actionable | ✓ | Set `status: archived` + `archived_at: <date>` in the lab_mgmt registry frontmatter (file preserved — lab history is shared) |
| `missing_charter` | warn | ✗ | User decides: re-adopt the clone, or remove from murmurent |
| `unadopted_clone` | info | ✗ | Click ↑ adopt in the Repos panel |

Remote (SSH) hosts are probed in a single batched bash call per
host. A transient SSH failure (host unreachable) is conservative:
no installations on that host are reported as orphaned. That way
lab-server being down for a reboot won't auto-deactivate everything.

## Manual run

```bash
murmurent reconcile                  # dry-run; exit 1 if actionable drift
murmurent reconcile --apply          # repair actionable findings
murmurent reconcile --slack-body     # also print a Slack-formatted summary
```

Exit codes:
- `0` — clean OR everything actionable was applied.
- `1` — actionable drift exists and `--apply` wasn't passed (so
  cron / CI can branch on it).

## Daily schedule via CC `/routine`

Set up once:

```
/routine create wigamig-reconcile
  prompt: |
    Run `murmurent reconcile --slack-body` in the shell and capture the
    output. If exit code is 1 (actionable drift was found in dry-run
    mode), post the slack-body block to #claude-test via
    mcp__claude_ai_Slack__slack_send_message and STOP — do not
    --apply automatically. If exit code is 0 and the report shows
    info-only findings (unadopted clones), post a short summary and
    stop. Never run --apply without my confirmation.
  schedule: daily at 09:00 America/Toronto
```

Why dry-run on the cron and `--apply` is manual: a false positive
auto-archiving an installation manifest is a bad surprise. The
routine surfaces drift in Slack; you decide whether to run
`murmurent reconcile --apply` from a terminal.

## Recovery from auto-archive

Archived manifests live in `~/.murmurent/installations/.archive/`
with a date suffix. To restore: copy the file back to
`~/.murmurent/installations/<name>.yaml`.

Archived registry entries keep `status: archived` in the
frontmatter. To restore: remove the `status:` and `archived_at:`
lines from the lab_mgmt registry .md file. Commit + push the
lab_mgmt repo so other group members see the restoration.

## See also

- [`src/murmurent/core/reconcile.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/core/reconcile.py) — detection + repair logic.
- [`src/murmurent/commands/reconcile_cmd.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/commands/reconcile_cmd.py) — CLI wrapper + Slack body formatter.
- [`tests/test_reconcile.py`](https://github.com/hallettmiket/murmurent/blob/main/tests/test_reconcile.py) — drift-detection contract pins.
