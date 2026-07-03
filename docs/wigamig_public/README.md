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
so only your institution's registrar can read it; they reply and take it from
there.

(Prefer to do it by hand? [`join/join-form.txt`](join/join-form.txt) is the
plain form, and the directory below has each registrar's email + encryption key.)

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
