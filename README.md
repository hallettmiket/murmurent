<!-- The user-facing README. In the development repository this file is
     release/README_public.md; release/make_release.sh copies it to README.md
     when it builds the release tree. Edit it there, not here: a change made in
     the release repo is overwritten by the next release.

     Keep it short (issue #161): one command per step, and a link for every
     special case. Detail belongs in docs/. -->

# Murmurent

AI assistants for research groups, built on Claude Code. Each lab keeps
control of its own people and data, and can share with other labs when that
helps.

**▶ [Watch the 7-minute getting-started video](https://mikehallett.science/assets/videos/murmurent_getting_started.html)**

**📖 [Read the documentation](https://mikehallett.science/murmurent/)**: getting
started, joining a lab, projects, the agents, and every command.

You need a Mac or Linux computer with
[Claude Code](https://claude.com/claude-code) installed and signed in.

## 1. Install

Install `uv`, the tool that installs Murmurent:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal, then:

```bash
uv tool install murmurent
murmurent install
murmurent doctor
```

`murmurent doctor` checks the install. If something is wrong, it prints the
command that fixes it.

You also get a **Murmurent Dashboard** icon: in Applications on a Mac, in
the applications menu on Linux.

## 2. Say who you are

```bash
murmurent init
```

It asks for your name, your email and your role: **member** (you work in a
lab), **PI** (you lead a lab or core facility) or **mayor** (you run a centre).

## 3. Set up a folder

Do this for every folder that holds research data. It turns on the check that
removes patient identifiers from anything leaving your computer.

```bash
murmurent repo adopt ~/repos/<folder>
```

The folder must be a git repository inside your repositories folder (`~/repos`
unless you chose another).
[If it does not work](https://mikehallett.science/murmurent/install_special_cases/#setting-up-a-folder-did-not-work).

## 4. Start working

```bash
cd ~/repos/<folder>
claude
```

Ask Claude Code anything, including "how do I use Murmurent?".

## Updating

```bash
uv tool upgrade murmurent
murmurent install
```

## Next

- [See what Murmurent can do](https://mikehallett.science/murmurent/getting_started/)
- [Join your lab](https://mikehallett.science/murmurent/identity/#members-join-a-group)
- [Set up your lab or core](https://mikehallett.science/murmurent/identity/#pis-set-up-your-lab-standalone-no-mayor-needed)
- [Start a centre](https://mikehallett.science/murmurent/centre_overview/)
- [All documentation](https://mikehallett.science/murmurent/)

## Help

Ask Claude Code first. If that does not solve it, see
[installation special cases](https://mikehallett.science/murmurent/install_special_cases/)
or [report a problem](https://github.com/hallettmiket/murmurent_dev/issues).

---

Mike Hallett, michael.hallett@uwo.ca. Licensed under [Apache-2.0](LICENSE).
