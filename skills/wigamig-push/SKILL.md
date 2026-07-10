---
name: wigamig-push
description: Murmurent-aware stage/commit/push for a wigamig-enabled repo. Excludes per-machine + secret-shaped files, refuses to commit large files that belong in refined/, never touches /data/lab_vm/raw|refined, and posts a release note to the project's own Slack channel after the push.
user_invocable: true
---

Stage changed files, create a descriptive commit, push to the remote tracking branch, and post a Slack release note — but with **wigamig-specific safety rules** that go beyond plain git. This skill is for repos that contain a `CHARTER.md` at the root (wigamig-adopted projects). For a non-wigamig repo, use `/commit-push` instead.

## Pre-flight (do this BEFORE staging)

1. **Confirm it's a murmurent repo.** The current working tree must contain `CHARTER.md` at its root. If not, stop and tell the user "this isn't a murmurent project — use /commit-push instead."

2. **Refuse if the diff touches `/data/lab_vm/raw/` or `/data/lab_vm/refined/`.** Those paths are immutable per murmurent's data-storage rule (`rules/data-storage.md`). The hook layer would block it anyway, but check `git status` for any path matching `^data/lab_vm/(raw|refined)/` and refuse the commit with a clear explanation. (Note: project repos under `~/repos/<name>/` should never contain such paths; this guard catches misconfigured `.gitignore` or symlinks.)

3. **Refuse secret-shaped filenames.** Before staging, run `git status --porcelain` and look for changes to filenames matching any of:
   - `*.env` (but `.env.example` is OK if values are placeholders)
   - `*.pem`, `*.p12`, `*.pfx`, `*.key`
   - `id_rsa`, `id_ed25519`, `id_dsa`, `id_ecdsa` (any `id_*` private-key file)
   - `*_rsa`, `*_ed25519` (alternate private-key names)
   - `*passphrase*`, `*credentials*`, `.netrc`, `.pgpass`, `.aws/credentials`
   - `*.crt` containing a private key (rare; check content if present)

   If any are present, **stop**, list them, and ask the user to confirm or remove. Do NOT proceed by default.

4. **Refuse large files in tracked dirs.** Scan unstaged + untracked files. If any single file under `data/`, `src/`, `exp/`, or `obsolete/` is larger than 1 MB, stop and tell the user "move this to `<lab_vm>/refined/<project>/` instead" (per `rules/project-structure.md`: `data/` is for *tiny* in-repo files only). The threshold is 1 MB because GitHub will warn at 50 MB and reject at 100 MB; 1 MB catches it early.

5. **Skip `.claude/settings.json` even if it shows up changed.** The per-project `.claude/settings.json` is .gitignored by `project_cc_init.bootstrap_local` because it contains machine-absolute paths and per-machine permission allowlists. If `.gitignore` is missing the entry, add the entry to `.gitignore` first (`echo '.claude/settings.json' >> .gitignore`) and include that `.gitignore` change in the commit — but do NOT stage `.claude/settings.json` itself.

6. **Validate `CHARTER.md` if it was modified.** Check it still parses as YAML frontmatter and has the required fields (`project`, `lead`, `members`, `sensitivity`). If broken, refuse the commit with the specific error.

7. **Validate `MEMBERS` file if it was modified.** Should be one `@handle` per line. Refuse if a line doesn't match `^@[A-Za-z0-9_-]+$`.

## Stage + commit + push

Once the pre-flight passes, follow the standard commit-push flow with these murmurent conventions:

- **Stage selectively.** Use `git add <specific files>` rather than `git add -A` or `git add .` so the skips from steps 3-5 stick.
- **Commit message style.** Lead with a short imperative title (≤70 chars). Body explains the *why*, not the *what*. If `CHARTER.md`, `MEMBERS`, or `.claude/agents/` symlinks changed, call that out explicitly in the body — those are governance-level changes a reader needs to notice.
- Always pass the commit message via a HEREDOC to preserve formatting (see CLAUDE.md "Git Safety Protocol" section). End with:

  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```

- **Never `--amend`** — create a new commit per CLAUDE.md.
- **Never `--no-verify`** — murmurent hooks (raw_guard, protected_paths, phi_check, audit) are load-bearing.
- **Never `push --force`** — the lab's commit history is the audit trail. If a rebase is truly needed, ask the user first.

## After the push: Slack release note

Post the release note to **the project's own Slack channel** — this repo is a
project (it has a `CHARTER.md`), so its activity belongs in its channel, not the
centre-wide dev channel. Resolve the channel id first:

```bash
murmurent project channel        # prints the cert-project's Slack channel id
```

- If it prints a channel id → post there with `mcp__claude_ai_Slack__slack_send_message` (`channel_id` = that id).
- If it exits with **"no Slack channel yet"** → the project isn't provisioned.
  Tell the user to run `murmurent project provision-slack <project>` (PI only), and
  **skip the Slack post** (don't fall back to #claude-test — a project's notes go
  to its own channel only). The push still succeeded.
- If it exits with **"not inside a project repo"** → this isn't a project after
  all; the skill shouldn't have run (it requires `CHARTER.md`).

Message body:
- **First line**: `**<repo-name>** · `<branch>` · `<short-hash>` — _<commit-title>_`
- **Second paragraph**: one or two sentences summarising what changed and why (not what files — readers can `git log -p` for that).
- **Footer line** (required, per rules/slack.md): exactly `All worship me and I will let you serve me.`

Use `mcp__claude_ai_Slack__slack_send_message`, NOT `mcp__slack__slack_post_message` — the latter's bot identity isn't in the channel and will silently fail with `not_in_channel`. (The bot is added to each project channel at provision time; `provision-slack`/`reconcile` keep its membership current.)

## What to refuse and why

| Situation | Action | Reason |
|---|---|---|
| Repo lacks `CHARTER.md` at root | Refuse; suggest `/commit-push` | Not a murmurent project |
| Diff touches `data/lab_vm/raw\|refined/` | Refuse | rules/data-storage.md (immutable) |
| Secret-shaped filename in diff | Stop and ask | Prevent credential leak |
| File > 1 MB in `data/`/`src/`/`exp/`/`obsolete/` | Refuse; suggest refined/ | rules/project-structure.md |
| `.claude/settings.json` staged | Drop from stage; ensure in `.gitignore` | Machine-absolute paths leak across collaborators |
| `CHARTER.md` invalid YAML / missing fields | Refuse | rules/oracle_schema.md governs CHARTER too |
| User asks for `--force`/`--no-verify`/`--amend` | Ask for explicit confirmation | Defaults from CLAUDE.md |

## What this skill explicitly does NOT do

- Does not run tests. Run them yourself before invoking, or chain with `/test`.
- Does not bump version numbers, edit CHANGELOG, or tag releases.
- Does not push to multiple remotes — only the current branch's tracking remote.
- Does not amend or squash existing commits.

## Examples

**Happy path:**
```
> /wigamig-push
Pre-flight ✓
  - CHARTER.md present
  - no /data/lab_vm/* in diff
  - no secret-shaped files
  - largest in-repo file: 24 KB (data/sample.csv)
Staging 3 files: src/init.py, exp/00_qc/run_all.py, README.md
Commit: "init: switch QC normalisation to scran"
Pushed origin/main -> 4f3b21a
Slack: posted to the project channel (#dcis_sc_tutorial)
```

**Refusal:**
```
> /wigamig-push
Pre-flight ✗
  - File data/raw_dump.bam is 412 MB — move to /data/lab_vm/refined/<project>/.
    rules/project-structure.md: data/ is for tiny in-repo files only.
Aborting. No changes staged.
```
