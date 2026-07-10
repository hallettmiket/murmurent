# Cores end-to-end smoke runbook

A step-by-step validation that everything shipped in Phases 1–8 works
against the **real** bioCORE on lab-server (not the unit-test fixtures).

Audience: PI walking through it with Gary at the keyboard, or Gary
solo with `#claude-test` open to ping if anything looks off.

**Time:** ~45 minutes if nothing breaks. ~2 hours including the
one-time Google Cloud OAuth client setup.

Each section says:
- **Goal** — what we're verifying
- **Prereq** — what has to already be true
- **Steps** — copy-paste commands
- **Expected** — what to see on success
- **If it fails** — first thing to try

Section IDs (`§1`, `§2a`, …) map to the phases in
[`cores_plan.md`](cores_plan.md).

---

## §0 · Baseline check (10 min)

### Goal
The local install is healthy, bioCORE is registered, services + training
catalog are seeded, and the dashboard boots.

### Pick the right Python env

The repo's `.venv` is on Python 3.11, but `pyproject.toml` now requires
3.12+. Don't fight it — use a 3.12+ conda env (this dev box uses
`my-rdkit-env`, which is on 3.13) and install the murmurent extras there:

```bash
conda activate my-rdkit-env
pip install -e '/Users/mth/repos/wigamig[dev,dashboard,slack,gcal]'
which murmurent    # should print the rdkit-env path, not the .venv
```

### Steps

```bash
# 1. Confirm bioCORE is in the centre registry.
ls ~/.murmurent/lab_info/cores/biocore/lab-mgmt/
# Expect: lab.md, members/, services/, training/, training_roster/, requests/

# 2. Tests pass on this checkout.
cd ~/repos/wigamig
python -m pytest -q
# Expect: 1089 passed, 1 skipped (gcal extra).

# 3. CLI is current.
murmurent core-calendar-auth --help
murmurent core-invoice --help
murmurent core-remind --help
# Expect: each prints help without traceback.

# 4. Dashboard boots — pick a fresh port so the browser doesn't
#    hand you a cached JSX from a previous run.
murmurent dashboard --hifi --port 8771
# Open http://localhost:8771 in an INCOGNITO/private window
# (guarantees no Babel cache from prior sessions).
# Log in as @the_pi (PI).
# Scroll to "Core services" panel → confirm bioCORE shows
# itc_microcal_peaq / cd_jasco_j815 / centrifuge_avanti_jxn30
# with correct fees.
```

### Recurring gotcha — dashboard restart after code changes

Python modules are imported once at startup. Any change to
`src/murmurent/**` requires a Ctrl-C + relaunch of the dashboard.
JSX changes are picked up on browser reload (Babel runs in-browser),
but you may need Cmd-Shift-R to bust the Babel cache.

### If it fails
- Missing tests file or path: `git pull && pip install -e '.[dev,dashboard,slack,gcal]'`
- Dashboard 500 on `/`: check `~/.murmurent/lab_info/registrar` exists and
  contains your handle.
- `Error: hi-fi dashboard deps missing`: you're missing the
  `dashboard` extra — re-run the install above.

---

## §1 · Gary's one-time Google Calendar OAuth (20 min, one-off)

### Goal
Gary's calendar holds every booking event going forward. Refresh token
lands at `~/.murmurent/cores/biocore/google_calendar.json`.

### Prereq
- Gary has a Google account that will own the bioCORE calendar.
- Gary has access to a Google Cloud project (create one if needed —
  any free-tier project works).

### Steps

1. **Mint the OAuth client (Google Cloud Console)**

   The Google Cloud UI moved most pages behind the ☰ hamburger or
   the search box. Direct deep-links:

   - Enable Calendar API: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
   - OAuth consent screen (branding): https://console.cloud.google.com/auth/branding
   - **Audience** (where "Test users" lives now): https://console.cloud.google.com/auth/audience
   - Credentials list: https://console.cloud.google.com/apis/credentials

   Make sure a Cloud project is selected in the top bar first.

   In order:
   - **Enable** the Google Calendar API.
   - **OAuth consent screen → Branding**: app name, support email,
     developer email. User Type: External. Publishing status: Testing.
   - **OAuth consent screen → Audience**: scroll to **Test users** →
     **+ Add users** → paste the gmail you'll sign in with → Save.
     (Without this step the auth flow returns `Error 403: access_denied`.)
   - **Credentials → Create Credentials → OAuth 2.0 Client ID**:
     Application type **Desktop app** (NOT Web — InstalledAppFlow
     needs Desktop). Download the JSON.

2. **Drop it on Gary's machine**
   ```bash
   mkdir -p ~/.murmurent/cores/biocore
   mv ~/Downloads/client_secret_*.json \
      ~/.murmurent/cores/biocore/google_oauth_client.json
   chmod 600 ~/.murmurent/cores/biocore/google_oauth_client.json
   ```

3. **Run the auth flow** (gcal extra already installed per §0)
   ```bash
   murmurent core-calendar-auth --core biocore
   ```
   A browser opens → Gary picks the bioCORE Google account → consent
   screen warns "Google hasn't verified this app" (expected in
   Testing mode) → click **Advanced** → **Go to … (unsafe)** → Allow
   → tab closes with "The authentication flow has completed."

4. **Verify the token landed**
   ```bash
   ls -l ~/.murmurent/cores/biocore/google_calendar.json
   # Expect: -rw------- (mode 0600), recent mtime.
   ```

### Expected
- CLI prints: `Calendar connected for core='biocore': /Users/…/google_calendar.json`
- Token file has `scopes: ['https://www.googleapis.com/auth/calendar.events']`
  and a non-empty `refresh_token`.

### If it fails
- `missing OAuth client secret`: file isn't at the expected path; check `ls`.
- `redirect_uri_mismatch`: in Google Cloud Console, ensure the OAuth client
  is **Desktop** type (not Web). InstalledAppFlow generates its own
  redirect URI; Desktop type accepts it.
- `Error 403: access_denied` after consent: your gmail isn't in the
  **Audience → Test users** list. Add it and re-run.
- `gcal extras not installed`: re-run the env install from §0.

---

## §2 · Training-roster sign-off + first booking with Calendar event (15 min)

### Goal
Demonstrate that training authority lives with the core (not the
member's lab), then book a real bioCORE service slot and watch a real
event land on Gary's calendar.

### Prereq
- §1 complete (Gary's calendar is connected).
- A test member exists in `lab-mgmt/members/` (use yourself: `@the_pi`).
- Dashboard running on http://localhost:8771 in an incognito tab.

### Background — where training records live

bioCORE owns its training roster at
`~/.murmurent/lab_info/cores/biocore/lab-mgmt/training_roster/<handle>.md`.
The core leader (Gary) writes here; the member's lab repo
(`~/repos/lab_mgmt/members/<handle>.md`) is NOT consulted for booking
prereqs. This mirrors real Western BioCORE policy.

### Steps

**As @the_pi (the requesting member):**

1. Open the dashboard. Scroll to **Core services**. ITC, CD, and
   centrifuge rows should all show a beige "Request training" button
   (because nobody is signed off yet).
2. Click **Request training** on the ITC row. Enter an optional note
   ("afternoons work best"). OK.
3. Switch to Slack → `#claude-test`. You should see:
   > 🎓 *biocore* training request — @the_pi wants @gary to train
   > them on `itc_basic_training` (**…**) (30 min, Room 100).

**As @gary (the core leader):**

4. Open `http://localhost:8771/core?core=biocore&user=gary` in a
   separate window. Scroll to the new **Training roster** card.
5. Click **＋ sign off**. Prompts in order:
   - Member: `@the_pi`
   - Training slug: `itc_basic_training` (the catalog list is shown)
   - Completed: today (YYYY-MM-DD)
   - Valid until: blank (auto-computed from `refresher_years`)
   - Notes: e.g. "in-person session 2026-05-23"
6. Alert says "Signed off: the_pi on itc_basic_training". The roster
   card refreshes to show @the_pi with a green "current" pill.

**Back as @the_pi:**

7. Reload the dashboard (Cmd-Shift-R). The ITC row's button is now
   green **Book**. (CD + centrifuge are still beige — Gary hasn't
   signed you off on those.)
8. Click **Book**. The modal opens with native date+time pickers
   (start defaults to next round hour; end auto-bumps to
   start + 90 min, the ITC default duration).
9. Take a slot ~1 hour from now, leave the tier at the default
   (`academic_internal`), add a note "smoke test §2". Click
   **Book slot**.

### Expected
- Modal closes; "My bookings" row appears with state `scheduled`.
- An event titled `MicroCal PEAQ-ITC … — @the_pi` lands on Gary's
  Google Calendar for the chosen time.
- Slack `#claude-test` gets:
  > 📅 Core *biocore*: @the_pi booked `itc_microcal_peaq` … — $80.00.
- In the booking response (browser devtools → Network → the POST):
  `calendar.event_id` is non-empty and `calendar.warning` is empty.

### If it fails
- **Greyed Book button after sign-off**: the dashboard was running
  before the training refactor; restart it (`Ctrl-C` + relaunch).
- **Booking returns `ok:true` but `calendar.event_id` is `""`**:
  `calendar.warning` will say "calendar not connected" — re-run §1
  on the machine running the dashboard (the token file is per-machine).
- **Modal opens but Book slot does nothing**: open browser devtools
  console; usually a JSON error from the API. Most often a tz-offset
  mismatch — the dashboard sends `YYYY-MM-DDTHH:mm:00±HH:MM`; if the
  backend has stale code, restart it.
- **"Request training" Slack message doesn't appear**: confirm the
  Slack MCP is wired (`grep -A2 mcp__claude_ai_Slack ~/.claude/settings.json`).

---

## §3 · Lifecycle round-trip (5 min)

### Goal
Advance → upload deliverable → confirm actual charge → cancel-style
ledger entry all visible to leader and requester.

### Steps (as `@gary` on `/core?core=biocore`)

```bash
# Open: http://localhost:8771/core?core=biocore&user=gary
```

In the **Requests inbox** card:
1. Find the row from §2.
2. Click **advance** → state flips to `in_progress`.
3. Click **upload** → pick a small `.png` from `~/Desktop/` → subdir:
   `refined`. Confirm dialog says "Uploaded refined/<file>.png".
4. Click **$ charge** → enter `120` (overtime) and note `ran 30 min over`.
5. Click **advance** again → state flips to `completed`.

In the **Deliverables overview** card (refresh if needed):
- The row for that job_id should show `file_count: 2` (manifest +
  upload), `last_upload_at` near now.

In the **Recent activity** card:
- See `request <id> -> in_progress`, `request <id> actual_charge $120.00 …`,
  `request <id> -> completed`.

### Switch back to `@the_pi`'s dashboard

In the **Core services** panel → **My bookings** → that row:
- State should show `completed`.
- Click **files** → JobFilesModal opens → shows the uploaded `.png`.
- Click the filename's **download** link → file downloads with original bytes.
- Click **download all (tar.gz)** → receive a tarball containing the job dir.

### If it fails
- Upload button does nothing on click: open browser devtools console.
  Most common: file too large for base64+JSON (we use a 10MB-ish
  practical ceiling). Use a smaller file.
- Download returns 413: the file is bigger than the default 50MB cap.
  Re-run with `?max_bytes=…` or use the MCP path (§4).

---

## §4 · MCP `murmurent-core-data` from a separate CC session (10 min)

### Goal
A member's CC session, started **after** the install in this checkout,
can list and read their job files via the MCP — no dashboard involved.

### Steps

```bash
# 1. Re-run install so murmurent-core-data is in ~/.claude/settings.json.
cd ~/repos/wigamig
murmurent install --hooks
grep -A2 murmurent-core-data ~/.claude/settings.json
# Expect: the MCP entry with args ["-m", "murmurent.mcp.core_data_server"].

# 2. Open a fresh CC session (new tab) in any project where you're
#    signed in as @the_pi (set $MURMURENT_USER if missing).
#    In CC, ask:
```

> "Use the murmurent-core-data MCP to list my jobs on biocore."

Then:

> "Get the manifest for job <paste the request_id from §3>."

Then:

> "Download every file in that job as a single tarball."

### Expected
- `list_my_jobs` returns the booked job from §2 (and only that one,
  unless you've booked more).
- `get_job_manifest` returns the JSON manifest with
  `requester_lab: hallett`, `state: completed`, `actual_charge.total: 120.0`.
- `bundle_job` returns base64 tar.gz; CC can decode it for you.

Audit log check:
```bash
tail -5 ~/.murmurent/cores/biocore/access.log
# Expect: one JSON line per MCP call, with caller="the_pi".
```

### If it fails
- MCP not listed in CC: `~/.claude/settings.json` may have been edited
  by hand; re-run `murmurent install --hooks` and confirm the diff.
- "no MURMURENT_USER / USER set": the MCP runs without your shell env.
  Add `MURMURENT_USER=the_pi` to the env block of the MCP entry in
  `~/.claude/settings.json` (mirror how the oracle MCP is wired on
  machines that need it).

---

## §5 · External customer + cross-lab billing (10 min)

### Goal
Register a non-Schulich customer; book a slot for them; generate
the monthly invoice and verify the external billing header lands.

### Steps (as `@the_pi`, the registrar)

```bash
# 1. Open /registrar.
open http://localhost:8771/registrar
```

In the **External customers** panel → click **＋ new external customer**:
- id: `acme-bio`
- name: `ACME Biosciences`
- kind: `industry`
- contact_name: `Jane Doe`
- billing email: `ap@acme.example`
- PO number: `PO-2026-001`

Row appears in the table.

```bash
# 2. Verify the resolver.
curl -s "http://localhost:8771/api/lab_roster/resolve?lab=acme-bio" | jq .
# Expect: {"kind": "external", "display_name": "ACME Biosciences",
#          "pi_or_contact": "ap@acme.example", "billing_meta": {...}}
```

3. **Sign ACME's operator off on the instrument first.** External
   customers go through the same training-roster as Schulich members
   — bioCORE still owns the prereq, regardless of who's paying. From
   the `/core` Training roster card click `＋ sign off`:
   - Member: `@external-acme`
   - Training slug: `itc_basic_training`
   - Completed: today; Valid until: blank (auto from `refresher_years`)
   - Notes: "ACME operator trained on instrument"

4. **Book a slot for ACME** — proxy booking from Gary's account:
   ```bash
   curl -s -X POST "http://localhost:8771/api/core/biocore/services/itc_microcal_peaq/book?user=gary" \
     -H "Content-Type: application/json" \
     -d '{
       "slot": {"start": "2026-05-23T16:00-04:00",
                "end":   "2026-05-23T17:00-04:00"},
       "requester": "@external-acme",
       "requester_lab": "acme-bio",
       "tier": "industry"
     }' | jq .
   ```
   Expect: `{"ok": true, "lab_resolution": {"kind": "external", "warning": ""}, ...}`

5. **Confirm + charge** through the inbox UI (as Gary). Pick `200` as
   actual_charge.

6. **Generate the invoice** (still as Gary on `/core`):
   - Billing card → month input shows current month
   - Click **preview** → see two rows: `hallett` (lab, $120) and
     `acme-bio` (external, $200), total $320
   - Click **generate** → confirm.

```bash
# 7. Verify the artifact.
ls ~/.murmurent/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/
# Expect: acme-bio.csv, acme-bio.md, hallett.csv, hallett.md, summary.md

cat ~/.murmurent/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/acme-bio.md
# Expect: ## Bill to block with PO-2026-001, ap@acme.example.

cat ~/.murmurent/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/summary.md
# Expect: "Breakdown by recipient kind: external: $200.00 (1), lab: $120.00 (1)"
```

### If it fails
- Proxy booking 403: confirm Gary is the registered leader of bioCORE
  (`grep leader ~/.murmurent/lab_info/cores/biocore/lab-mgmt/lab.md`).
  Non-leader/registrar can't book on behalf of someone else.
- Invoice generate writes nothing: check the slot is in the right month
  (a 2026-05-22 slot won't appear in 2026-06 invoices).

---

## §6 · Reminders dry-run (2 min)

### Goal
The `/routine`-able reminder scanner sees upcoming bookings.

### Steps

```bash
# Book a slot ~1h from now, then:
murmurent core-remind --core biocore
# Expect: at least one line like:
#   [1h] biocore/<rid> @the_pi → itc_microcal_peaq in ~60 min
# (no --apply: dry-run, doesn't post to Slack)
```

### If it fails
- "No reminders due": your test slot isn't in [now+55min, now+65min].
  Adjust the slot's start time to be ~1h from now and re-book.

---

## §7 · Smoke complete — what to write down

Capture in `lab-notebook/2026-05-23_cores_smoke.md` (or your daily
notebook entry):

```markdown
# Cores end-to-end smoke — 2026-05-23

- Stack version: <git rev-parse HEAD>
- Calendar OAuth: ✓ / ✗  (notes)
- §2 booking: ✓ / ✗
- §3 upload + download: ✓ / ✗
- §4 MCP from fresh CC: ✓ / ✗
- §5 external customer + invoice: ✓ / ✗
- §6 reminder dry-run: ✓ / ✗

Issues hit: …
Follow-ups: …
```

Any ✗ row → file a murmurent issue with the failing curl/click + the
error text, then loop back here when the fix lands.
