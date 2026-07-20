# The public directory (maintainer / mayor notes)

Maintainer-facing notes for the global `murmurent_public` repo. These
notes live here, separate from the public directory's own README
([`docs/murmurent_public/README.md`](https://github.com/hallettmiket/murmurent/blob/main/docs/murmurent_public/README.md)),
which stays trivially simple for prospective members.

## What the public directory is

A centre is one institution's own Murmurent installation. The public
directory is a different thing entirely: a **single global repository**
(`github.com/hallettmiket/murmurent_public`) that works as a public
directory only, a list of participating institutions and, for each, the
**registrar's contact email**. That's the entire function.

The repository holds only the institution list. GitHub Issues stay
**disabled**, and joining runs by **email to the registrar** rather
than a web form: a prospective member's netname, institution, role, PI,
justification, and so on reach only the registrar's inbox, kept off
GitHub entirely. This is deliberate, keeping the ecosystem free of a
permanent, publicly archived record of "who wants to join what, where"
across institutions.

> Murmurent's code lives at
> [`github.com/hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent)
> (public, cloned via `bootstrap.sh`). The public directory serves a
> single purpose: looking up who to email at each participating
> institution.

## Creating the public directory (one time, by the ecosystem maintainer)

Already done, created once for the whole ecosystem by the maintainer.
Each mayor's centre setup starts from here rather than repeating this
step.

```bash
gh repo create hallettmiket/murmurent_public --public
git clone https://github.com/hallettmiket/murmurent_public /tmp/murmurent_public
cp -R docs/murmurent_public/. /tmp/murmurent_public/
cd /tmp/murmurent_public && git add -A \
  && git commit -m "seed murmurent_public directory" && git push
gh repo edit hallettmiket/murmurent_public --enable-issues=false   # no data collection
```

## Listing a centre in the directory (each mayor, once)

When an institution goes live, its mayor adds **one row** to the public
directory's [`README.md`](https://github.com/hallettmiket/murmurent_public/blob/main/README.md)
table: institution, a short description (centre / department / group
name), and the **join email** (`join_email` on the centre, set via
`murmurent centre-init --join-email …` or the `/registrar` profile
editor). Only that row gets published.

## Receiving + filing a join request (each mayor, ongoing)

1. A prospective member emails the registrar (the address in the
   directory).
2. The registrar reads the email and files the request **locally**:

   ```bash
   murmurent join-request submit --kind lab \
     --name <proposed_name> --pi @<netname> \
     --email <requester_email> --institution <institution> \
     --justification "…"
   ```
3. Then approves or declines as usual (`murmurent join-request
   approve|decline`, or the `/registrar` dashboard). Provisioning
   (Slack/GitHub/FS) fires on approval.

Everything about the requester stays on the registrar's own machine and
the centre's private `lab_info`, kept local to the centre's own
infrastructure.

See [`docs/setup.md`](setup.md) for the full centre deployment runbook
and [`docs/slack_setup.md`](slack_setup.md) for the Slack fabric.
