# Join a wigamig institution

**wigamig** is shared AI research infrastructure used by universities and
research centres. This page is a **directory**: if your institution runs
wigamig and you'd like to join a lab or core, find it below and **email its
registrar**.

> This repository collects **nothing**. There is no form to submit and issues
> are disabled. Your request is **encrypted to your registrar's key** and sent
> to them by email — only they can read it, and nothing about you is ever
> posted publicly.

## How to join

**Run one script.** It installs the encryption tool if you don't have it, asks
you a few questions, encrypts your answers to your registrar's key, and opens
your email app with the request ready to send.

```sh
curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/wigamig_public/main/join/wigamig-join.sh
sh wigamig-join.sh
```

Then just press **Send** in the email that pops up. That's it — you don't edit
any files, and **nothing about you is posted here**. Your request is encrypted
so only your institution's registrar can read it.

(Prefer to do it by hand? [`join/join-form.txt`](join/join-form.txt) is the
plain form, and the directory below has each registrar's email + encryption key.)

## After you send it

You're now waiting on the **Mayor** — the person who runs wigamig at your
institution. Expect **two things back**:

1. **An email reply from the Mayor.** Watch your inbox (and your spam folder).
2. **A Slack invite** to your institution's `wigamig-<centre>` workspace,
   included in that reply. **Accept it** — from then on, everything happens in
   Slack, and you'll land in a private channel for your lab or core.

If a few days pass with no reply, reply to your own sent email to nudge them.

## Install the software (you can do this now, while you wait)

You don't have to wait to be approved to install wigamig — **the code is
public**, and installing it just gets your computer ready. Approval only
decides which lab/core you join, not whether you can have the software. The
one-script joiner above offers to do this for you at the end; or run it
yourself, anytime:

```sh
curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/wigamig_public/main/install-wigamig.sh
sh install-wigamig.sh
```

It downloads wigamig to `~/repos/wigamig`, installs the `wigamig` command, and
wires up the shared agents, rules, and tools — installing the `uv` helper for
you if you don't already have it (you just need `git`). When the Mayor's reply
and Slack invite arrive, you'll already be set, and the rest of onboarding is
walked through for you in Slack.

## Institutions using wigamig

One institution may run more than one wigamig installation (a centre, a
department, a named group), so match on the institution *and* the description.

| Institution | Installation | Email to join | age key (encrypt to this) |
|---|---|---|---|
| Western University | Bioconvergence Centre | _(added when the centre goes live)_ | _(added when the centre goes live)_ |

**Don't see your institution?** It may not run wigamig yet — ask your PI or
lab manager. (Registrars add their row here when they go live.)

## Where's the software?

The wigamig **code** lives in a different repo:
[github.com/hallettmiket/wigamig](https://github.com/hallettmiket/wigamig).
You only need that if you're *setting up* wigamig at an institution (as a
mayor) or *building* wigamig — not to join one. To join, just email your
registrar above.
