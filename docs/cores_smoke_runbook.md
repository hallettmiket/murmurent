# Cores end-to-end smoke runbook

A step-by-step validation that everything shipped in Phases 1–8 works
against the **real** bioCORE on biodatsci (not the unit-test fixtures).

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

### Steps

```bash
# 1. Confirm bioCORE is in the centre registry.
ls ~/.wigamig/lab_info/cores/biocore/lab-mgmt/
# Expect: lab.md, members/, services/, training/, requests/

# 2. Tests pass on this checkout.
cd ~/repos/wigamig
.venv/bin/python -m pytest -q
# Expect: 1074 passed, 1 skipped (gcal extra).

# 3. CLI is current.
wigamig core-calendar-auth --help
wigamig core-invoice --help
wigamig core-remind --help
# Expect: each prints help without traceback.

# 4. Dashboard boots.
wigamig dashboard
# Open http://localhost:8000 → log in as @mhallet (PI).
# Click "Core services" panel → confirm bioCORE shows itc / cd /
# centrifuge services with correct fees.
```

### If it fails
- Missing tests file or path: `git pull && pip install -e .[dev,dashboard,slack]`
- Dashboard 500 on `/`: check `~/.wigamig/lab_info/registrar` exists and
  contains your handle.

---

## §1 · Gary's one-time Google Calendar OAuth (20 min, one-off)

### Goal
Gary's calendar holds every booking event going forward. Refresh token
lands at `~/.wigamig/cores/biocore/google_calendar.json`.

### Prereq
- Gary has a Google account that will own the bioCORE calendar.
- Gary has access to a Google Cloud project (create one if needed —
  any free-tier project works).

### Steps

1. **Mint the OAuth client (Google Cloud Console)**
   - APIs & Services → Library → enable **Google Calendar API**
   - APIs & Services → Credentials → Create Credentials → OAuth 2.0
     Client ID → Application type: **Desktop app**
   - Download the JSON.

2. **Drop it on Gary's machine**
   ```bash
   mkdir -p ~/.wigamig/cores/biocore
   mv ~/Downloads/client_secret_*.json \
      ~/.wigamig/cores/biocore/google_oauth_client.json
   chmod 600 ~/.wigamig/cores/biocore/google_oauth_client.json
   ```

3. **Install the gcal extra + run the auth flow**
   ```bash
   pip install 'wigamig[gcal]'
   wigamig core-calendar-auth --core biocore
   ```
   A browser opens → Gary picks the bioCORE Google account → consent
   → tab closes.

4. **Verify the token landed**
   ```bash
   ls -l ~/.wigamig/cores/biocore/google_calendar.json
   # Expect: -rw------- (mode 0600), recent mtime.
   ```

### Expected
- CLI prints: `Calendar connected for core='biocore': /Users/…/google_calendar.json`

### If it fails
- `missing OAuth client secret`: file isn't at the expected path; check `ls`.
- `redirect_uri_mismatch`: in Google Cloud Console, ensure the OAuth client
  is **Desktop** type (not Web). InstalledAppFlow generates its own
  redirect URI; Desktop type accepts it.
- `gcal extras not installed`: `pip install 'wigamig[gcal]'` again, confirm
  the venv that runs `wigamig` is the same one you just pip'd into.

---

## §2 · First end-to-end booking with Calendar event (10 min)

### Goal
A real member books a real bioCORE service slot, a real event lands on
Gary's calendar.

### Prereq
- §1 complete (Gary's calendar is connected).
- A test member exists in `lab-mgmt/members/` (use yourself: `@mhallet`).

### Steps (as the booking member, e.g. `@mhallet`)

```bash
# 1. Confirm prereqs would block before training is set.
curl -s "http://localhost:8000/api/core/biocore/services/itc_microcal_peaq/can_book?member=@mhallet" | jq .
# Expect: {"ok": false, "training_slug": "itc_basic_training", "reason": "..."}

# 2. Seed the training record on @mhallet's member file.
$EDITOR ~/repos/lab_mgmt/members/mhallet.md
# Add under frontmatter:
#   training:
#     - name: itc_basic_training
#       completed: 2026-05-22
#       by: '@gary'
#       valid_until: 2028-05-22

# 3. Re-check.
curl -s "http://localhost:8000/api/core/biocore/services/itc_microcal_peaq/can_book?member=@mhallet" | jq .
# Expect: {"ok": true, ...}

# 4. Open the dashboard → Core services panel → ITC row → click Book.
#    Pick a slot ≥1h in the future:
#      Start: 2026-05-23T14:00-04:00
#      End:   2026-05-23T15:00-04:00
#    Click "Book slot".
```

### Expected
- Modal closes; "My bookings" row appears with state=scheduled.
- An event titled "ITC — @mhallet" appears on Gary's Google Calendar
  for the chosen time.
- Slack #claude-test gets:
  `:calendar: Core *biocore*: @mhallet booked itc_microcal_peaq …`

### If it fails
- Booking returns `ok:true` but `calendar.event_id` is `""` and
  `calendar.warning` shows "calendar not connected": go re-run §1
  on the machine running the dashboard (the token file is
  per-machine).
- Booking 422 with training reason: re-check `valid_until` is a
  future date and `name` matches the training slug exactly.

---

## §3 · Lifecycle round-trip (5 min)

### Goal
Advance → upload deliverable → confirm actual charge → cancel-style
ledger entry all visible to leader and requester.

### Steps (as `@gary` on `/core?core=biocore`)

```bash
# Open: http://localhost:8000/core?core=biocore&user=gary
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

### Switch back to `@mhallet`'s dashboard

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

## §4 · MCP `wigamig-core-data` from a separate CC session (10 min)

### Goal
A member's CC session, started **after** the install in this checkout,
can list and read their job files via the MCP — no dashboard involved.

### Steps

```bash
# 1. Re-run install so wigamig-core-data is in ~/.claude/settings.json.
cd ~/repos/wigamig
wigamig install --hooks
grep -A2 wigamig-core-data ~/.claude/settings.json
# Expect: the MCP entry with args ["-m", "wigamig.mcp.core_data_server"].

# 2. Open a fresh CC session (new tab) in any project where you're
#    signed in as @mhallet (set $WIGAMIG_USER if missing).
#    In CC, ask:
```

> "Use the wigamig-core-data MCP to list my jobs on biocore."

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
tail -5 ~/.wigamig/cores/biocore/access.log
# Expect: one JSON line per MCP call, with caller="mhallet".
```

### If it fails
- MCP not listed in CC: `~/.claude/settings.json` may have been edited
  by hand; re-run `wigamig install --hooks` and confirm the diff.
- "no WIGAMIG_USER / USER set": the MCP runs without your shell env.
  Add `WIGAMIG_USER=mhallet` to the env block of the MCP entry in
  `~/.claude/settings.json` (mirror how the oracle MCP is wired on
  machines that need it).

---

## §5 · External customer + cross-lab billing (10 min)

### Goal
Register a non-Schulich customer; book a slot for them; generate
the monthly invoice and verify the external billing header lands.

### Steps (as `@mhallet`, the registrar)

```bash
# 1. Open /registrar.
open http://localhost:8000/registrar
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
curl -s "http://localhost:8000/api/lab_roster/resolve?lab=acme-bio" | jq .
# Expect: {"kind": "external", "display_name": "ACME Biosciences",
#          "pi_or_contact": "ap@acme.example", "billing_meta": {...}}
```

3. **Book a slot for ACME** — proxy booking from Gary's account:
   ```bash
   curl -s -X POST "http://localhost:8000/api/core/biocore/services/itc_microcal_peaq/book?user=gary" \
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

4. **Confirm + charge** through the inbox UI (as Gary). Pick `200` as
   actual_charge.

5. **Generate the invoice** (still as Gary on `/core`):
   - Billing card → month input shows current month
   - Click **preview** → see two rows: `hallett` (lab, $120) and
     `acme-bio` (external, $200), total $320
   - Click **generate** → confirm.

```bash
# 6. Verify the artifact.
ls ~/.wigamig/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/
# Expect: acme-bio.csv, acme-bio.md, hallett.csv, hallett.md, summary.md

cat ~/.wigamig/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/acme-bio.md
# Expect: ## Bill to block with PO-2026-001, ap@acme.example.

cat ~/.wigamig/lab_info/cores/biocore/lab-mgmt/invoices/2026-05/summary.md
# Expect: "Breakdown by recipient kind: external: $200.00 (1), lab: $120.00 (1)"
```

### If it fails
- Proxy booking 403: confirm Gary is the registered leader of bioCORE
  (`grep leader ~/.wigamig/lab_info/cores/biocore/lab-mgmt/lab.md`).
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
wigamig core-remind --core biocore
# Expect: at least one line like:
#   [1h] biocore/<rid> @mhallet → itc_microcal_peaq in ~60 min
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

Any ✗ row → file a wigamig issue with the failing curl/click + the
error text, then loop back here when the fix lands.
