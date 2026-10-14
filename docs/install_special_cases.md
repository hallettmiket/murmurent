# Installing: special cases

The [README](https://github.com/hallettmiket/murmurent#readme) covers the usual
install. This page covers everything else. Find your situation below.

## `murmurent: command not found`

Close the terminal and open a new one. `uv` puts the command in
`~/.local/bin`, and a terminal opened before the install does not look there
yet.

## I want one command that does everything

This needs only `git`. It installs `uv` for you if it is missing.

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

To read the installer before running it, download the repository and run
`scripts/bootstrap.sh` from inside it.

## I installed from a copy of the repository, not from PyPI

Update with these instead of `uv tool upgrade`. The example assumes your copy
is in your repositories folder (`~/repos` unless you chose another;
`murmurent config repos-root` shows it):

```bash
cd ~/repos/murmurent
git pull                                          # download the changes
uv tool install --python 3.12 --reinstall -e .   # install them
murmurent install
```

Use `uv`, not `pip`. The `pip` on your path often belongs to a different Python,
such as a conda environment, and the update then lands in the wrong place or
stops with an error about the Python version.

## The data services do not connect

Claude Code may report that `murmurent-oracle`, `murmurent-data`,
`murmurent-core-data` or `murmurent-inventory` failed to connect. Installs made
before version 2026.10.0 could pick up a version of a library those services
do not support. Update, then restart Claude Code:

```bash
uv tool upgrade murmurent
murmurent install
```

## I keep my repositories somewhere other than ~/repos

Tell Murmurent which folder you use, for example `~/repositories`:

```bash
murmurent config repos-root ~/repositories
```

Run it without a folder to see the current setting. Repositories already on
your computer are not moved.

## A folder holds patient data

Add this line to the folder's `.murmurent.yaml` file:

```yaml
sensitivity: clinical
```

## Setting up a folder did not work

Ask what state the folder is in:

```bash
murmurent repo status ~/repos/<folder>
```

Then run the command beside the answer you get.

| Answer | What it means | What to run |
|---|---|---|
| `✗ no such folder` | the path is wrong | check the path |
| `✗ not tracked by git` | git is not tracking the folder | `git -C ~/repos/<folder> init`, then the next row |
| `• not set up yet` | Murmurent has never set it up | `murmurent repo adopt ~/repos/<folder>` |
| `± half set up` | set up by a very old Murmurent | `murmurent repo upgrade ~/repos/<folder>` |
| `✓ ready`, older version | set up by an earlier Murmurent | `murmurent repo upgrade ~/repos/<folder>` |
| `✓ ready`, current | nothing to do | open Claude Code in it |

Neither command changes anything already in the folder. Commit the two files it
adds, `.murmurent.yaml` and `CLAUDE.md`, so everyone else working in that folder
gets the same setup.

## Which repository is which

| Repository | What it is |
|---|---|
| [`murmurent`](https://github.com/hallettmiket/murmurent) | The released versions. This is what you install. |
| [`murmurent_dev`](https://github.com/hallettmiket/murmurent_dev) | Where Murmurent is written. Report problems and ask for features here. |
| [`murmurent_public`](https://github.com/hallettmiket/murmurent_public) | The public directory of institutions that run Murmurent, and how to join one. |

## Still stuck

Ask Claude Code. It has Murmurent's documentation and commands, and can usually
find and fix an install problem. Then see
[`TROUBLESHOOTING.md`](https://github.com/hallettmiket/murmurent/blob/main/TROUBLESHOOTING.md),
or [report the problem](https://github.com/hallettmiket/murmurent_dev/issues).
