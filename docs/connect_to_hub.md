# Connect your centre to the onboarding hub

A paste-able runbook for a **mayor** whose centre is bootstrapped but not yet
receiving join requests from the public `wigamig_public` hub. Do this once (then
schedule step 4). The worked example is Western (`unique_name: western`) — swap
in your own values.

**Prerequisite:** the hub row for your installation exists in
[`wigamig_public`](https://github.com/hallettmiket/wigamig_public)'s directory,
and the hub is public (so your `gh` can read its issues).

## 1. Update the wigamig CLI

Older builds lack `--unique-name` / the ingest command. Refresh:

```bash
cd ~/repos/wigamig && git pull && uv tool install --reinstall .
wigamig join-request --help | grep ingest   # should list `ingest`
```

## 2. Tell your centre its ID + the hub

Edit the frontmatter of `~/.wigamig/lab_info/centre.md` and add these two lines
(match the `ID` column in the hub directory exactly):

```yaml
unique_name: western
public_hub: github.com/hallettmiket/wigamig_public#western
```

Then record it in the centre's git ledger:

```bash
git -C ~/.wigamig/lab_info commit -am "connect centre to wigamig_public hub"
wigamig centre-status        # confirms the install id is set
```

(You can also set these from the `/registrar` dashboard profile editor instead
of hand-editing.)

## 3. Make sure `gh` can read the hub

The ingest reads issues via the GitHub CLI:

```bash
gh auth status || gh auth login
```

## 4. Poll the hub

```bash
wigamig join-request ingest       # files any new hub requests locally
wigamig join-request list         # see what landed
```

Re-run this to pick up new requests — schedule it (cron or a `/routine`) so
joining is hands-off. Each run only processes issues not seen before.

## Verify end-to-end

1. File a test issue on the hub via the join form (institution = your `ID`).
2. `wigamig join-request ingest` → it appears in `join-request list`, and the
   issue gets a "routed as #NNNN" comment.
3. Approve it (`wigamig join-request approve <id>` or the `/registrar`
   dashboard) → the approval is posted back on the issue.
4. Delete the test issue when done.

After this, a real person can file a join request from the hub and you handle it
from `/registrar`. See [`docs/hub_setup.md`](hub_setup.md) for the wider hub
model and [`docs/setup.md`](setup.md) for moving the centre to a server.
