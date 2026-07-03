# wigamig_public — seed contents for the global onboarding hub

This directory holds the **seed files for the public `wigamig_public`
repository** — the single global hub where anyone who wants to join a
wigamig-enabled institution files a request. It is *not* wired into the
wigamig package; it is content the mayor copies into a new public repo:

```bash
# create the public hub once (any neutral org; e.g. the wigamig project org)
gh repo create hallettmiket/wigamig_public --public
git clone https://github.com/hallettmiket/wigamig_public /tmp/wigamig_public
cp -R docs/wigamig_public/. /tmp/wigamig_public/
cd /tmp/wigamig_public && git add -A && git commit -m "seed wigamig_public hub" && git push
```

## What the hub is (and is not)

**Is:** a public directory of participating institutions and a structured
**GitHub-issue intake** for join requests. Each institution's wigamig
watcher ingests the issues addressed to it (by `institution` label) into
its private `join_requests/` queue, then routes them to the mayor + the
relevant PI over Slack.

**Is NOT:** a place for anything private. **No netnames, no server
hostnames, no data paths, no tokens.** Those are exchanged over the
private Slack channel *after* the registrar engages. The public issue
carries only: which institution, what kind of unit, a proposed name, the
requester's role, and a justification.

## How a prospective member uses it

1. Open a **"Request to join a wigamig centre"** issue (the form in
   [`.github/ISSUE_TEMPLATE/join.yml`](.github/ISSUE_TEMPLATE/join.yml)).
2. Pick the target institution and fill in the (non-sensitive) fields.
3. The institution's registrar is notified in Slack, reviews in the
   `/registrar` dashboard, and follows up privately.

## Institution directory

Institutions add themselves here (public name + how to reach the
registrar — again, **no private infra**). This table is illustrative:

| Institution | `unique_name` (issue label) | Registrar contact |
|---|---|---|
| _Example University_ | `exampleu` | via the join issue form |

Each centre's mayor appends their row when they go live.
