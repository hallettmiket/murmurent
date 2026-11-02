# Running the server timers under a lab service account

**Who this is for.** A PI whose lab server runs the two murmurent timers that
police files and processes, the weekly space scan and the weekday etiquette
check, and who has been given a service account on that server by the
administrators. On biodatsci that account is `biodatsci-agent`.

**Why move them.** Both timers were first set up under the PI's own login,
because that was the only account there was. A service account is better in
three ways: the jobs no longer stop or change when the PI's account does; the
lab records say plainly that a machine account, not a person, reads everyone's
file names and process lists; and the account's permissions are exactly what the
jobs need and nothing more. The millwright agent's own description says it may
live on "a designated lab-server account". This is that account.

Nothing about the two commands changes. Each is the same `murmurent ... schedule
--install` run under the new account. One lab setting, `space_dir`, points both
accounts at one folder, so the PI keeps reading the scan's table from their own
login and from the dashboard.

## What the account needs

Ask the administrators for the first two; the PI can do the rest with `sudo`.

| Need | Why | Command (as an administrator) |
|---|---|---|
| Membership of the lab's data group | The data root is readable by that group only. Without it the scan opens nothing, and every total is zero. On biodatsci the group is `ssmd-ud-vmlab`. | the administrators' user-management tool |
| A way for the PI to get a shell as the account | Everything below is typed as the account. | `sudo -iu <account>` works when the PI has `sudo`; otherwise an SSH key the administrators add to the account |
| Lingering switched on | A systemd user timer runs only while the account has a session, unless the account lingers. | `sudo loginctl enable-linger <account>` |
| A folder both accounts can reach | The scan writes its table there; the PI reads it there. | see step 5 below |

Not needed: `sudo` for the account itself, `crontab`, or GitHub write access.
The timers read; they change no file and stop no job.

## As the service account

Open a shell as the account (`sudo -iu <account>`), then:

**1. Install murmurent.** The same two steps a member runs, from the released
repository:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/hallettmiket/murmurent.git ~/repos/murmurent
cd ~/repos/murmurent && uv tool install --python 3.12 -e .
```

The first `murmurent` command the account runs mints a key pair in its own
`~/.murmurent/keys/`. That is the account's machine identity, the same as on
any install; nobody issues it a membership card, and it is a member of nothing.

**2. Clone the lab records, read-only.** The scan needs the project records
and the roster; the etiquette check needs the roster and the lab's policy. The
records repository is private, so give the account a deploy key with read
access only:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "<account>@<server> murmurent timers"
cat ~/.ssh/id_ed25519.pub        # the PI adds this on GitHub, see step 2 under "As the PI"
git clone git@github.com:<owner>/murmurent_lab_mgmt_<lab>.git ~/repos/murmurent_lab_mgmt_<lab>
```

Before every run, both timers fast-forward this clone, so a project added or a
member who joined since the last run is seen. If the pull fails, the run goes
ahead on the clone as it is and writes one line about it to its log.

**3. Settings the timers need**, in `~/.profile` (the timers start through a
login shell, and `murmurent ... schedule --install` also copies these into the
unit file):

```bash
export MURMURENT_DATA_ROOT=/data/lab_vm
export MURMURENT_LAB_MGMT_REPO=$HOME/repos/murmurent_lab_mgmt_<lab>
```

Log out and in again (or `source ~/.profile`) before going on.

**4. The lab's Slack bot.** The messages go out through the lab's own bot, the
same one the PI's account uses. Store its token for this account with

```bash
murmurent group-slack-setup <lab>
```

which checks the token live and writes it to
`~/.config/murmurent/groups/<lab>/slack-token`, readable by this account only.
The PI reads the token from the same path under their own login and types it
in; nothing in murmurent copies a secret between accounts.

**5. A folder both accounts can reach.** Decide where the scan's table and
report live. The recommended place is a folder on the server's own disk, owned
by the service account, with the PI given access through an access control
list (ext4 supports these; the lab's data root is on NFS and should not hold
the table). As an administrator:

```bash
sudo install -d -o <account> -g <account> -m 0700 /var/lib/murmurent/space
sudo setfacl -m u:<pi>:rwx -m d:u:<pi>:rwx /var/lib/murmurent/space
```

The PI needs write access as well as read, because `murmurent space decide`
records decisions in the same table. Then, in the lab records repository,
`policy/millwright.yaml`:

```yaml
space_dir: /var/lib/murmurent/space
```

Commit and push it, and pull it into the service account's clone. From now on
every `murmurent space` command on this server, under either account, reads and
writes that folder. With the setting empty, each account uses its own
`~/.murmurent/space/`, which is why the PI's dashboard would otherwise keep
showing the PI's last scan for ever.

**6. Install the timers**, exactly as the PI did before:

```bash
murmurent etiquette check                    # once by hand: quick, and shows the roster is read
murmurent etiquette schedule --install --notify
murmurent space schedule --install           # Sunday 02:00; --day and --at change it
murmurent space schedule                     # says when it runs next and that it lingers
systemctl --user list-timers
```

The space scan takes a while (about ten minutes per million files), so there is
no need to run it by hand; the Sunday run will come. Its log is
`~/.murmurent/space/lab_scan.log` under the service account; the etiquette
check's is `~/.murmurent/etiquette/check.log`. The etiquette check's memory of
who was told what (`state.json`) also lives there, so the escalation starts
afresh under the new account: a first message is a direct message again.

## As the PI

**1. Remove the timers from your own account**, so a scan does not run twice:

```bash
murmurent space schedule --remove
murmurent etiquette schedule --remove
```

**2. Add the deploy key** from step 2 above to the lab records repository, read
only:

```bash
gh repo deploy-key add <path to the .pub file> --repo <owner>/murmurent_lab_mgmt_<lab> --title "<account> on <server>"
```

**3. Record what runs.** `schedule --install` wrote the two entries into
`policy/scheduled_jobs.md` in the service account's clone, with its account
name, but that clone cannot push. Copy the file into your own clone, commit and
push it, then put the service account's clone back on the branch so its next
pull is a fast-forward:

```bash
sudo cat ~<account>/repos/murmurent_lab_mgmt_<lab>/policy/scheduled_jobs.md > ~/repos/murmurent_lab_mgmt_<lab>/policy/scheduled_jobs.md
git -C ~/repos/murmurent_lab_mgmt_<lab> commit -am "Scheduled jobs now run under <account>" && git -C ~/repos/murmurent_lab_mgmt_<lab> push
sudo -iu <account> git -C ~<account>/repos/murmurent_lab_mgmt_<lab> checkout -- policy/scheduled_jobs.md
sudo -iu <account> git -C ~<account>/repos/murmurent_lab_mgmt_<lab> pull --ff-only
```

Anyone in the lab can then read, in the records, that the jobs run under
`<account>`, what they may do and what they may not.

**4. Check that you still see the result.** On the server, as yourself,
`murmurent space lab` reads the shared folder. On your laptop, `murmurent space
lab --host <server>` and the dashboard's **Space** page run that same command
over SSH as you, so they show the service account's scan without any change.

## If something does not work

- **Every total is zero, or "could not read" lists every folder.** The account
  is not in the data group yet. Check with `id <account>`.
- **The timer never fires while nobody is logged in.** Lingering is off:
  `loginctl show-user <account> -p Linger` should say `Linger=yes`.
- **"no Slack token for '<lab>'".** Step 4 was skipped under this account; the
  token file lives per account.
- **"lab records not refreshed: ..."** in a log. The clone diverged, usually
  because `scheduled_jobs.md` was left modified (step 3 under "As the PI"), or
  the deploy key was not added.
- **The PI's `murmurent space lab` says there is no report.** `space_dir` is not
  set in the policy the PI's account reads, or the access list is missing on
  the folder: `getfacl /var/lib/murmurent/space` should list the PI.

## See also

- [The space table](space_table.md): what the scan looks for and how the PI
  reads it.
- [`policy/millwright.yaml`](space_table.md#the-labs-settings-for-the-pi): the
  lab's settings, including `space_dir`.
- [The millwright](https://github.com/hallettmiket/murmurent/blob/main/agents/millwright.md), whose policing these timers are.
