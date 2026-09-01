# Reconciliation routine

`murmurent reconcile` compares Murmurent's recorded state to on-disk
reality across every registered host and reports drift. Default is
dry-run; `--apply` repairs the actionable subset.

Before the detectors run, reconcile fast-forwards the local **lab_mgmt
clone** (`git pull --ff-only`) so the roster and cert-project registry
reflect what the PI last pushed: this is what keeps a member's Lab
Members panel current without clicking its update button. Offline,
diverged, or not-a-git-clone lab_mgmt is a note in the report, never
a failure.

## What counts as drift

| Kind | Severity | Auto-repair? | Repair action |
|---|---|---|---|
| `orphan_installation` | actionable | ✓ | Move `~/.murmurent/installations/<name>.yaml` into `installations/.archive/<name>_<date>.yaml` |
| `orphan_registry` | actionable | ✓ | Set `status: archived` + `archived_at: <date>` in the lab_mgmt registry frontmatter (file preserved, lab history is shared) |
| `missing_charter` | warn | ✗ | User decides: re-adopt the clone, or remove from Murmurent |
| `unadopted_clone` | info | ✗ | Click ↑ adopt in the Repos panel |
| `lab_mgmt_uncommitted` | warn | ✗ | Review + commit + push lab_mgmt: local-only edits are invisible to the lab (roster writers auto-commit, so this usually means a hand-edit) |
| `lab_mgmt_unpushed` | warn | ✗ | `git -C <lab-mgmt> push`: commits exist locally that members can't pull yet |

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
- `0`: clean OR everything actionable was applied.
- `1`: actionable drift exists and `--apply` wasn't passed (so
  cron / CI can branch on it).

## Daily schedule via CC `/routine`

Set up once:

```
/routine create murmurent-reconcile
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
that auto-archives an active installation manifest is disruptive and
easily missed. The routine surfaces drift in Slack; you decide whether to run
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

- [`src/murmurent/core/reconcile.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/core/reconcile.py): detection + repair logic.
- [`src/murmurent/commands/reconcile_cmd.py`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/commands/reconcile_cmd.py): CLI wrapper + Slack body formatter.
- [`tests/test_reconcile.py`](https://github.com/hallettmiket/murmurent/blob/main/tests/test_reconcile.py): drift-detection contract pins.
