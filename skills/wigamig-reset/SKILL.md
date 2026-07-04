---
name: wigamig-reset
description: Back up, then reset wigamig machine state to a fresh start so `wigamig centre-init` runs first-run again. Tiered (centre / install / full) with a mandatory backup, a dry-run preview, and credentials + other-project installs protected behind explicit --nuke flags. Use when the user wants a clean slate / fresh copy from the repo.
user_invocable: true
---

Reset this machine's wigamig state to a clean starting point — safely. The
default is the **least** destructive thing (`centre`), a backup is **always**
taken first, and the genuinely dangerous deletions (credentials, other
projects' installs) never happen without an explicit flag.

The heavy lifting is in `reset.sh` (next to this file). Your job is to pick the
level from what the user asked, **preview with `--dry-run`, get confirmation,
then run for real**.

## Levels

| Level | Removes | Keeps |
|---|---|---|
| `centre` (default) | `~/.wigamig/lab_info/` only → centre-init is first-run again | everything else |
| `install` | centre + reinstall the tool from `~/repos/wigamig` (`uv tool install --force --python 3.12 -e '.[dashboard,slack,mcp]'`) + `scripts/setup.sh` + `wigamig install --hooks` | credentials, installations, audit |
| `full` | install + machine-local **caches** (`workspaces/`, `*.log`, `dashboard.pid`, `security/agent_cache`, stale `RESUME.md`) | credentials, `installations/`, `decommissions/`, audit logs, `hosts.yaml`/`machine.yaml` |

Opt-in extras (only with the flag): `--nuke-installations` (also wipes
`~/.wigamig/installations/` — **other projects' manifests**),
`--nuke-credentials` (also wipes `~/.config/wigamig/` — the **slack-token +
keys**).

## How to run it

1. **Pick the level.** No level / "reset the centre" / "start centre-init
   fresh" → `centre`. "reinstall / fresh copy from the repo" → `install`.
   "full machine reset / everything clean" → `full`. If the user's words imply
   removing credentials or other projects, ask before adding a `--nuke` flag —
   never infer those.

2. **Dry-run first, always.** Run:
   `bash ~/.claude/skills/wigamig-reset/reset.sh --level <lvl> --dry-run [nukes]`
   (or the repo path `skills/wigamig-reset/reset.sh`). Show the user the exact
   list of what it would remove and the backup path.

3. **Confirm, then execute.** Only after the user is happy, re-run with `--yes`
   instead of `--dry-run`. The script refuses to do anything destructive
   without `--yes`, so this two-step is enforced, not just convention.

4. **Report.** Show the backup tarball path (`~/.wigamig_backups/reset_*.tgz`)
   and the restore one-liner, then confirm `wigamig centre-status` reports
   "no centre initialised". If the level was `install`/`full`, confirm
   `wigamig dashboard --hifi` still launches.

## Guardrails (the script enforces these — don't work around them)

- **Backup is mandatory and lands OUTSIDE `~/.wigamig`** (`~/.wigamig_backups/`)
  so even a full wipe can't delete it. Never pass a flag to skip it; there
  isn't one.
- **Never** touches `~/repos/*` working clones, `~/.claude/CLAUDE.md`,
  `~/.claude/memory/`, or `~/.claude/projects/`.
- **Credentials and other-project installs are preserved by default.** On this
  machine `~/.config/wigamig/slack-token` + `keys/` are real, and
  `~/.wigamig/installations/` holds manifests for the user's *other* projects
  (manuscript, mp3/mp4, …). Removing either needs the explicit `--nuke-*` flag
  AND a clear go-ahead from the user.
- If the user says "wipe everything / pristine machine", read that back as
  "this includes your slack-token, keys, and every other project's install —
  confirm?" before adding both `--nuke` flags.
