# The public directory hub — maintainer / mayor notes

Maintainer-facing notes for the global `murmurent_public` repo. It does **not**
live on the hub itself — the hub's own README
([`docs/murmurent_public/README.md`](https://github.com/hallettmiket/murmurent/blob/main/docs/murmurent_public/README.md)) is kept trivially
simple for prospective members.

## What the hub is (and is NOT)

A **single global repository** — `github.com/hallettmiket/murmurent_public` — that
is a **public directory only**: a list of participating institutions and, for
each, the **registrar's contact email**. That's the entire function.

**It collects nothing.** GitHub Issues are **disabled** on the repo, and there is
no form. Joining is by **email to the registrar** — a prospective member's
netname, institution, role, PI, justification, etc. never touch GitHub. This is
deliberate: we don't want a permanent, publicly-archived pile of "who wants to
join what, where" across institutions.

> The hub is **not** where the Murmurent code lives — that's
> [`github.com/hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent)
> (public, cloned via `bootstrap.sh`). You don't need the hub to get the code;
> you need it only to look up who to email.

## Creating the hub (one time, by the ecosystem maintainer)

Already done. It's created once for the whole ecosystem; an individual mayor does
**not** create a hub.

```bash
gh repo create hallettmiket/murmurent_public --public
git clone https://github.com/hallettmiket/murmurent_public /tmp/murmurent_public
cp -R docs/murmurent_public/. /tmp/murmurent_public/
cd /tmp/murmurent_public && git add -A \
  && git commit -m "seed murmurent_public directory" && git push
gh repo edit hallettmiket/murmurent_public --enable-issues=false   # no data collection
```

## Listing a centre in the directory (each mayor, once)

When an institution goes live, its mayor adds **one row** to the hub's
[`README.md`](https://github.com/hallettmiket/murmurent_public/blob/main/README.md) table — institution, a short description
(centre / department / group name), and the **join email** (`join_email` on the
centre, set via `murmurent centre-init --join-email …` or the `/registrar` profile
editor). Nothing else is published.

## Receiving + filing a join request (each mayor, ongoing)

1. A prospective member emails the registrar (the address in the directory).
2. The registrar reads the email and files the request **locally**:

   ```bash
   murmurent join-request submit --kind lab \
     --name <proposed_name> --pi @<netname> \
     --email <requester_email> --institution <institution> \
     --justification "…"
   ```
3. Then approves/declines as usual (`murmurent join-request approve|decline`, or
   the `/registrar` dashboard). Provisioning (Slack/GitHub/FS) fires on approval.

Everything about the requester stays on the registrar's own machine + the
centre's private `lab_info` — never on GitHub.

See [`docs/setup.md`](setup.md) for the full centre deployment runbook and
[`docs/slack_setup.md`](slack_setup.md) for the Slack fabric.
