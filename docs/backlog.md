# Backlog

Issues to tackle later, captured during the post-item-2 review on
2026-06-16. Order is rough priority; each item is sized + has a
concrete first step.

---

## 1. Cross-lab Slack guest invite logic (deferred from item 0)

**Problem.** When a centre project spans multiple labs, the project
Slack channel currently can only invite members of the primary lab's
workspace. Cross-lab collaborators need single-channel guest invites,
which Slack's API supports but requires the primary lab's workspace
admin to set up a "Slack Connect" or guest-seat plan and the
appropriate bot scopes (`groups:write.invites`, `users:read.email`).

**Scope.** ~2 days. Add a `centre_provision.invite_cross_lab_guest()`
helper that wraps `conversations.invite` with email-based invites,
plus a registrar-side approval gate (guest seats cost money). The
existing `provision_lab_onboarding` is a clean place to extend.

**First step.** Document the centre's Slack workspace plan + which
PI's admin token murmurent should use, then add the helper.

---

## 2. Slack `conversations.create` smoke against a live workspace
✅ **Code shipped 2026-06-16; live smoke still needed.**

**Problem.** The mayor-approval auto-provisioning flow (item 2) calls
`centre_provision._live_slack_create_channel` which posts to
`conversations.create`. The code path is tested with injected fakes
but has never run against a real Slack API token. The first time a
registrar approves a lab join in production, we'll discover whatever's
wrong with the live call (scopes, channel name validation, dup
detection, …).

**Shipped 2026-06-16:**
- `core.centre_provision.slack_create_channel()` returns a
  structured `SlackChannelResult` with actionable hints for every
  Slack error code (`missing_scope`, `name_taken`, `ratelimited`, …).
- `_live_slack_create_channel` is now a thin compat shim around
  it so the join-approve probe signature stays unchanged.
- New CLI: `murmurent centre-slack-smoke` creates a probe channel,
  reports the result, archives the probe on success. Exit 0 = bot
  healthy; exit 1 = registrar needs to fix the token.
- Documented in `docs/setup.md` §4.

**Still needed.** Actually run `murmurent centre-slack-smoke` against
the centre's real Slack workspace once it exists, file any bugs
that fall out. Then approve a real `kind=lab` join request end-to-end
and watch the workspace for the channel.

---

## 3. Hermetic test fixtures (`WIGAMIG_HOME` not pinned)

**Problem.** Several test modules' fixtures set
`WIGAMIG_LAB_INFO_ROOT` and `WIGAMIG_LAB_MGMT_REPO` but NOT
`WIGAMIG_HOME`, so they read the developer's real
`~/.wigamig/cores/*/google_calendar.json`,
`~/.wigamig/cores/*/access.log`, etc. Most of the time this is
harmless; when the developer has done any local smoke testing (e.g.
left an expired OAuth token), 6+ booking tests flake.

**Scope.** ~1 hour. One-line addition to each affected fixture:
`monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))`.

**First step.** `grep -L WIGAMIG_HOME tests/test_*.py` to find all
test files that monkeypatch `WIGAMIG_LAB_INFO_ROOT` but not
`WIGAMIG_HOME`, then add the pin.

---

## 4. Real actual-state fetcher for `centre-project reconcile`

**Problem.** The `centre_provision.reconcile_project()` function is
pure-diff: it compares declared state vs an `actual_state` argument
the caller passes in. Today that caller (the CLI / dashboard) passes
empty actuals because there's no fetcher wired up. Reconcile output
is therefore "everything is drift" — a placeholder.

**Scope.** ~3 days. Three async fetchers:
- `_fetch_slack_members(channel_id)` via Slack `conversations.members`
- `_fetch_github_collaborators(org, repo)` via `gh api`
- `_fetch_fs_acl(machine, project)` via `ssh <machine> sudo
  murmurent_project_acl.sh --inspect <project>` (new sub-command on
  the existing sudo script)

**First step.** Add the `--inspect` sub-command to
`scripts/murmurent_project_acl.sh` and have it emit a JSON snapshot of
the wgm_<project> group members on the host.

---

## 5. `lab_mgmt` repo — purpose docs + (do NOT rename)

**The user's question:** what is `lab_mgmt`? Who needs it? Should
it be renamed to `wigamig-mgmt`?

**Short answer.** `lab_mgmt` is the **per-group governance repo**
(one per PI / lab). It is **distinct from** the centre-wide
`~/.wigamig/lab_info/` tree, which is the registrar's. Contents:

| Path | Purpose |
|---|---|
| `lab.md` | PI handle, lab name, institution, Slack workspace, GitHub org, lab-VM base path |
| `members/<handle>.md` | One file per lab member (active/inactive, certifications) |
| `inventory/` | Reagents, equipment (managed via the inventory MCP) |
| `oracle/` | Curated group-level findings (published from individual project findings) |
| `projects/` | Per-project registry entry (metadata + status) |
| `compliance.md` | Group-level training requirements |
| `audit/`, `roles/`, `keys/`, etc. | Smaller per-group state |

**Who needs it.** Every member of a wigamig-enabled lab reads it;
only the PI writes (with delegation to roles like `lab_manager`).
The default location is `~/repos/lab_mgmt`, overrideable via
`$WIGAMIG_LAB_MGMT_REPO`.

**Rename recommendation.** **Do NOT rename to `wigamig-mgmt` or
`wigamig-lab`.** The current name correctly signals that this is the
*lab's own* repo, not part of the murmurent commons. It belongs to the
PI, lives under the lab's GitHub org (`<labpi>/lab_mgmt`), and is
analogous to a department's filing cabinet — not a murmurent artifact.
Renaming would blur the boundary between centre-wide tooling
(`wigamig/`) and group-scoped governance (`lab_mgmt/`).

**Scope.** ~2 hours of docs work. Add a `docs/lab_mgmt.md` explaining
the above, with a layout diagram + the "what you should and
shouldn't put here" table. Link it from `docs/setup.md`.

**First step.** Write `docs/lab_mgmt.md` using the breakdown above.

---

## 6. `~/repos` should be user-configurable, not defaulted

**Problem.** `core/projects.py` defaults `DEFAULT_PROJECTS_ROOT` to
`~/repos`. Every member is silently assumed to want their murmurent
projects checked out there. The `$WIGAMIG_PROJECTS_ROOT` env var
overrides, but users have to know about it.

**Scope.** ~1 day. During `cable_guy`'s onboarding flow, prompt the
member for their preferred `<projects_root>`, write it to
`lab_mgmt/members/<handle>.md` (a new `projects_root:` frontmatter
field), and have `lab_mgmt_repo_root()` + `projects_root()` resolve
that path first. Fall back to `~/repos` only as a last resort with a
deprecation warning.

**First step.** Add the `projects_root:` field to the member
frontmatter schema + the membership.add() writer; then extend
`core/projects.py:projects_root()` to honour it.

---

## 7. Click-to-launch icon for non-Mac users

**Problem.** The PI has a Mac .app bundle that one-clicks `murmurent
dashboard --hifi --port 8771`. Linux and Windows users need an
equivalent — currently they have to remember the CLI invocation.

**Scope.** ~1 day. Generate three platform-specific launchers from
one template:

- **macOS** — `.app` bundle (already exists; document it in
  `docs/setup.md` so other Mac users can copy it).
- **Linux** — `.desktop` file installed to
  `~/.local/share/applications/murmurent.desktop` (auto-installed by
  `murmurent install --hooks` on Linux). Includes an SVG icon.
- **Windows** — `.lnk` shortcut on the desktop, generated by a
  one-line PowerShell snippet. (`murmurent install --hooks` on Windows
  runs that snippet if found.)

**First step.** Write the `.desktop` file template and have
`install_cmd.cmd_install()` write it when `platform.system() ==
"Linux"`. The icon can be the existing Mac one re-exported.

---

## 8. Smoke-test polish: `murmurent install --hooks` warns the user not to share their `~/.wigamig/registrar` sentinel

**Problem.** During item-2 dev, my own `~/.wigamig/registrar`
silently changed from `the_pi` to `tbrowne` (probably from a
runtime smoke test I ran), which broke 30 historical tests until I
reset it. The sentinel is per-machine identity for git commit
authorship and isn't supposed to gate access — but it does, via the
legacy fallback in `is_registrar()`.

**Scope.** ~30 minutes. Three lines of clarifying behavior:
- `murmurent install --hooks` should refuse to overwrite an existing
  `~/.wigamig/registrar` without `--force`.
- `murmurent centre-init` should default `--no-sentinel` when
  `--no-prompt` is passed (the scripted/server path).
- Test fixtures that monkeypatch `R.REGISTRAR_SENTINEL` should be
  audited for completeness.

**First step.** Add the `--force` check to `install_cmd.cmd_install`.
