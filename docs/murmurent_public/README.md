# murmurent implementations directory

This page lists the institutions running **murmurent**. You only need it if you're
a **PI** registering a new lab or core, or a **mayor** listing a centre.

- **A member of a lab that already uses murmurent?** You don't come here — just ask
  your PI for a membership ID (they issue it; you run `murmurent import-card`).
- **New to murmurent?** Install it first:
  [github.com/hallettmiket/murmurent](https://github.com/hallettmiket/murmurent).

> This repository collects **nothing** — no form, no issues. A join request is
> **encrypted to your institution's registrar** and emailed to them; only they
> can read it, and nothing about you is ever posted publicly.

## PIs — register a lab or core

Find your institution in the directory below, then run the join script. It asks a
few questions, encrypts your request to that centre's key, and opens your email
app ready to send:

```sh
curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/join/murmurent-join.sh
sh murmurent-join.sh
```

Press **Send**. Once the mayor approves, they send you back your **PI ID** — see
[Registering your lab or core with a centre](https://github.com/hallettmiket/murmurent#pis-if-you-are-a-pi-registering-your-lab-or-core-with-an-existing-centre)
in the main README for how to import it and what comes next. *(By hand instead?
[`join/join-form.txt`](join/join-form.txt) is the plain form.)*

## Mayors — list your centre

From your centre, run:

```bash
murmurent centre-hub-publish --submit
```

It writes your directory row here plus your signing key + revocation list (so
members can verify IDs), and — with `--submit` — publishes it (a direct push if you
have write access to the hub, otherwise a fork + pull request). Drop `--submit` to
just write the files and print the push steps for you to run by hand. See the mayor
setup in the [code repo](https://github.com/hallettmiket/murmurent).

## Institutions using murmurent

One institution may run more than one installation (a centre, a department, a
named group), so match on the institution *and* the description. The **age key**
is the public key the join script encrypts to.

| Institution | Installation | Email to join | age key (encrypt to this) |
|---|---|---|---|
| Western University | Western Test Centre | tbrowne5@uwo.ca | age1y43uxhv7dp50mw8qnrqwh4wvamp7adz4alxezpxang4wn9usuumqmneuat |

**Don't see your institution?** It may not run murmurent yet — ask your PI or lab
manager. (Registrars add their row here when they go live.)
