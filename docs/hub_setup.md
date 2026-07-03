# The global onboarding hub — maintainer / mayor notes

This is **maintainer-facing** documentation for the global `wigamig_public`
hub. It does **not** live on the public hub itself — the hub's own README
([`docs/wigamig_public/README.md`](wigamig_public/README.md)) is kept
trivially simple for prospective members. Keep the two separate: novice
users should never see setup mechanics.

## What the hub is

A **single global repository** — `github.com/hallettmiket/wigamig_public` —
that is the public front door for *every* wigamig deployment. It holds:

- a **directory** of participating institutions (public names only — **no
  netnames, server hostnames, data paths, or tokens**), and
- a **GitHub-issue intake** form
  ([`.github/ISSUE_TEMPLATE/join.yml`](wigamig_public/.github/ISSUE_TEMPLATE/join.yml)).

Each centre's registrar polls the hub for issues addressed to their
institution and ingests them into their private `join_requests/` queue.
Private details are exchanged over Slack/email *after* the registrar
engages — never on the public issue.

## Creating the hub (one time, by the ecosystem maintainer)

The hub already exists. It only needs to be created once for the whole
ecosystem — an individual institution's mayor does **not** create a hub.

```bash
gh repo create hallettmiket/wigamig_public --public
git clone https://github.com/hallettmiket/wigamig_public /tmp/wigamig_public
cp -R docs/wigamig_public/. /tmp/wigamig_public/
cd /tmp/wigamig_public && git add -A \
  && git commit -m "seed wigamig_public hub" && git push
# labels the ingest flow uses:
gh label create join-request --repo hallettmiket/wigamig_public --color 0e8a16
gh label create ingested     --repo hallettmiket/wigamig_public --color ededed
```

## Connecting a centre to the hub (each mayor, once)

When an institution goes live, its mayor:

1. **Points the centre at the hub** — set `public_hub` in `centre.md` to
   `github.com/hallettmiket/wigamig_public#<unique_name>` (the mayor
   server-setup form / `wigamig centre-init --public-hub` does this).
2. **Adds their installation to the directory** — a one-line row in the
   hub's [`README.md`](wigamig_public/README.md) table: institution, a short
   description (a centre / department / group name — one institution can run
   several installations), and the `unique_name` members enter on the form.
3. **Polls the hub** — run `wigamig join-request ingest` on the centre
   (schedule it from a routine/cron). It ingests only issues whose
   `Institution` field matches the centre's `unique_name`, files a local
   join request, comments on the issue, and later posts the registrar's
   decision back on that issue.

A paste-able step-by-step for these three is in
[`docs/connect_to_hub.md`](connect_to_hub.md).

See [`join_ingest`](../src/wigamig/core/join_ingest.py) for the ingest
implementation and [`docs/setup.md`](setup.md) for the full centre
deployment runbook.
