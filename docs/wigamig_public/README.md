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

You'll send the registrar a short, **encrypted** join form. Only they can
decrypt it. You need [`age`](https://age-encryption.org) (a tiny encryption
tool — `brew install age`, or see their site).

1. **Find your institution** in the directory below; note its **email** and
   **age key**.
2. **Download** [`join/join-form.txt`](join/join-form.txt) and
   [`join/wigamig-join.sh`](join/wigamig-join.sh), and fill in the form.
3. **Encrypt it:**
   ```sh
   sh wigamig-join.sh join-form.txt <the age1... key from the directory>
   ```
   This writes `join-request.age`.
4. **Email `join-request.age`** to the registrar's address. Done — the
   registrar decrypts it on their machine and follows up.

Your netname isn't secret, but this keeps every detail off GitHub and readable
only by your registrar.

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
