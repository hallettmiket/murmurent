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
| Example University | Example Test Centre | join@example.edu | age1exampleplaceholderreplacewithyourrealpublickeyxxxxxxxxxxxxx |

**Don't see your institution?** It may not run murmurent yet — ask your PI or lab
manager. (Registrars add their row here when they go live.)

## Published choreographies

A **choreography** is one recurring multi-actor workflow: a question several
people attack, each with their own approach, with the agents they run, the
order they run in, and the artefacts that come out. Published ones are listed
in [`choreographies.tsv`](choreographies.tsv), and you install one with
murmurent itself:

```bash
murmurent choreography list                  # what is published
murmurent choreography install inhibition    # or a git URL directly
```

| Name | What it does | Repository |
|---|---|---|
| `inhibition` | *Dance with Inhibition.* Four independent approaches generate candidate covalent and non-covalent Pin1 inhibitors, are judged against one shared control, and are presented side by side for a medicinal chemist to adjudicate. The deliverable is the method, not the molecule. | [tt8804/inhibition_public](https://github.com/tt8804/inhibition_public) |

The table above is a courtesy for people reading this page in a browser. The
index itself carries **locations only**, and everything `install` shows you is
read from the choreography's own `.murmurent.yaml`, so no description here can
drift away from the repository it describes.

**Data is never included.** A choreography repository carries code, decision
records and documentation. Its data lives under a centre's own governed data
root, so installing one gives you the method, not the results.

### Starting your own

One command creates a choreography's repository, poses its question, and asks
your PI to make it a project. You do not need a repository first:

```bash
murmurent choreography init pin1_inhibition   # asks for anything you leave out
```

Or click **＋ new choreography** in the Choreographies panel of your dashboard.
Step by step, including what happens after your PI approves:
[Starting a choreography](https://hallettmiket.github.io/murmurent/starting_a_choreography/).

**Publishing yours:** push the repository, then open a pull request adding one
row to `choreographies.tsv`: the name, a tab, and the repository's git address.
