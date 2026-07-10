---
name: murmurent-reset
description: Back up, then reset murmurent machine state to a fresh start so `murmurent centre-init` runs first-run again. Tiered (centre / install / full) with a mandatory backup, a dry-run preview, and credentials + other-project installs protected behind explicit --nuke flags. Use when the user wants a clean slate / fresh copy from the repo.
user_invocable: true
---

Reset this machine's murmurent state to a clean starting point — safely. The
default is the **least** destructive thing (`centre`), a backup is **always**
taken first, and the genuinely dangerous deletions (credentials, other
projects' installs) never happen without an explicit flag.

The heavy lifting is in `reset.sh` (next to this file). Your job is to pick the
level from what the user asked, **preview with `--dry-run`, get confirmation,
then run for real**.

## Levels

| Level | Removes | Keeps |
|---|---|---|
| `centre` (default) | `~/.murmurent/lab_info/` only → centre-init is first-run again | everything else |
| `install` | centre + reinstall the tool from `~/repos/wigamig` (`uv tool install --force --python 3.12 -e '.[dashboard,slack,mcp]'`) + `scripts/setup.sh` + `murmurent install --hooks` | credentials, installations, audit |
| `full` | install + machine-local **caches** (`workspaces/`, `*.log`, `dashboard.pid`, `security/agent_cache`, stale `RESUME.md`) | credentials, `installations/`, `decommissions/`, audit logs, `hosts.yaml`/`machine.yaml` |
| `data` | **all data you entered** into `~/.murmurent` — `lab_info/`, `profile.yaml`, `hosts`/`machine`/`master_folders` yaml, `inventory/`, `cores/`, `onboarding/`, `decommissions/`, `security/`, identity/cards/trust/revocation, logs — everything *except* key material (allowlist-based, so new files are caught) | `keys/`, `age/`, `installations/` (other projects), and `~/.config/wigamig`. **No reinstall.** |

Use `data` for "wipe everything I've entered and start over, but keep my keys and
credentials." It's the level to reach for when `full` leaves too much behind
(`full` keeps `profile.yaml`, `hosts.yaml`, `inventory/`, etc.).

Opt-in extras (only with the flag): `--nuke-installations` (also wipes
`~/.murmurent/installations/` — **other projects' manifests**),
`--nuke-credentials` (also wipes `~/.config/wigamig/` — the **slack-token +
keys**), `--nuke-keys` (with `--level data`, **also** removes `~/.murmurent/keys/`
+ `age/` for a fully fresh identity; default keeps them), `--nuke-labs` (also
removes this machine's **lab-management repos** `~/repos/wigamig_*` — they hold
the roster; see below), `--uninstall` (first **completely removes** the existing
murmurent install — the uv-tool one *and* stray conda/pipx copies that shadow it —
before any reinstall).

### Lab repos (`~/repos/wigamig_*`) — the roster

A PI's lab-management repo (`~/repos/wigamig_<group>`, created by `pi-init` /
`murmurent init`) holds `members/*.md` — the **roster**, which is the source of
truth for member identity (card fingerprints included). It lives under
`~/repos`, which reset **never** touches by default, so **every** reset just
**lists** these repos and leaves them alone.

`--nuke-labs` removes them, but safely: each is **tar'd into the backup dir
first**, and any repo with **uncommitted or unpushed** work is **refused**
(you'll be told to push/commit it first). A standalone lab with **no git remote**
is always refused — its roster is the only copy. After a successful nuke the
dangling `lab_mgmt_path` pointer is dropped, so `pi-init` is first-run again.
Only reach for `--nuke-labs` when the user explicitly wants the lab's roster gone
from this machine and has confirmed it's pushed somewhere safe.

### Completely removing the old install

When the user asks to "completely remove" / "uninstall" murmurent:

- **Remove it and leave nothing:** `--level centre --uninstall`. This
  uninstalls every murmurent executable and does not reinstall — the machine ends
  up with no `murmurent` on PATH.
- **Remove the old one and put back a clean one** (the usual "fresh copy from
  the repo" intent): `--level install --uninstall` — uninstalls first, then
  reinstalls editable from `~/repos/wigamig`.

`--uninstall` is what handles the stray-duplicate-install problem (e.g. an old
`pip install -e` copy in a conda env shadowing the uv-tool one). It scans conda
base/envs + pipx and removes any murmurent it finds. Working clones under
`~/repos/*` are never touched — only installed executables.

## How to run it

1. **Pick the level.** No level / "reset the centre" / "start centre-init
   fresh" → `centre`. "reinstall / fresh copy from the repo" → `install`.
   "full machine reset / everything clean" → `full`. If the user's words imply
   removing credentials or other projects, ask before adding a `--nuke` flag —
   never infer those.

2. **Dry-run first, always.** Run:
   `bash ~/.claude/skills/murmurent-reset/reset.sh --level <lvl> --dry-run [nukes]`
   (or the repo path `skills/murmurent-reset/reset.sh`). Show the user the exact
   list of what it would remove and the backup path.

3. **Confirm, then execute.** Only after the user is happy, re-run with `--yes`
   instead of `--dry-run`. The script refuses to do anything destructive
   without `--yes`, so this two-step is enforced, not just convention.

4. **Report.** Show the backup tarball path (`~/.wigamig_backups/reset_*.tgz`)
   and the restore one-liner, then confirm `murmurent centre-status` reports
   "no centre initialised". If the level was `install`/`full`, confirm
   `murmurent dashboard --hifi` still launches.

## Guardrails (the script enforces these — don't work around them)

- **Backup is mandatory and lands OUTSIDE `~/.murmurent`** (`~/.wigamig_backups/`)
  so even a full wipe can't delete it. Never pass a flag to skip it; there
  isn't one.
- **Never** touches `~/repos/*` working clones, `~/.claude/CLAUDE.md`,
  `~/.claude/memory/`, or `~/.claude/projects/` — with **one** opt-in exception:
  `--nuke-labs` removes `~/repos/wigamig_*` lab-management repos (backed up first,
  and only when they have no uncommitted/unpushed work). Nothing else under
  `~/repos` is ever touched.
- **Credentials and other-project installs are preserved by default.** On this
  machine `~/.config/wigamig/slack-token` + `keys/` are real, and
  `~/.murmurent/installations/` holds manifests for the user's *other* projects
  (manuscript, mp3/mp4, …). Removing either needs the explicit `--nuke-*` flag
  AND a clear go-ahead from the user.
- If the user says "wipe everything / pristine machine", read that back as
  "this includes your slack-token, keys, and every other project's install —
  confirm?" before adding both `--nuke` flags.
