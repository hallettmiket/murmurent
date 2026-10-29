# Running long jobs

`murmurent run` starts a long computation so that a dropped connection does not
stop it, runs it at low priority within your lab's rules for sharing the
server, and posts one line to your project's Slack channel when it finishes,
fails or seems stuck. `murmurent jobs` tells you, in plain words, what is
running, for how long, and how earlier jobs ended.

## Why use it

Three things go wrong with long jobs on a shared server.

- **A dropped connection stops the job.** A job started in an ordinary terminal
  ends when the terminal closes: a laptop going to sleep is enough. `murmurent
  run` starts the job inside **tmux**, a program that keeps a command running
  after you disconnect.
- **One job can slow everyone down.** Numerical libraries (the ones R, numpy
  and many others use for matrix arithmetic) start one thread per core unless
  told otherwise, so a single script can occupy a whole server. `murmurent run`
  sets the job's priority to the lowest (`nice 19`, so other people's work
  always goes first), tells those libraries how many cores they may use, and
  chooses that number from your lab's rules and how busy the server is.
- **Nobody hears when a job stops.** A run that stops overnight on a full disk
  can go unnoticed for hours. `murmurent run` records how every job ends and
  tells the project's channel.

## Start a job

Run it from inside your project's folder. Put your own command after `--`:

```bash
cd ~/repos/my_project
murmurent run --name fit_models --cores 8 \
    --out "$MURMURENT_DATA_ROOT/append_only/my_project/01_models" \
    -- Rscript exp/01_models/run_all.R
```

It replies with what it chose, for example:

```
Started job fit_models on 8 cores, at priority nice 19.
  It cannot see any GPU. Use --gpus to ask for one.
  Output goes to the log: /home/you/.murmurent/runs/20261016-221000-a3f9.log
  Watch it live: tmux attach -t run-20261016-221000-a3f9
  Check on it: murmurent jobs show 20261016-221000-a3f9
  Slack: one line goes to the project's channel when it finishes, fails or stalls.
```

What it does:

- **Cores.** You get what you ask for with `--cores`, but never more than your
  lab allows one person across all their jobs, and never more than the server
  can spare right now. If it gives you fewer, it says why. Without `--cores`
  you get the lab's default, usually 1. The same number goes into the thread
  settings (`OMP_NUM_THREADS` and its relatives), so the libraries respect it.
- **GPUs.** With `--gpus 2`, it picks the two least busy GPUs and lets the job
  see only those. Without `--gpus`, the job sees no GPU, so it cannot take one
  by accident.
- **Memory.** It does not start a job when memory is low. If you say how much
  the job needs (`--memory 64G`), it checks that this fits and is within your
  allowance.
- **Disk.** It checks the free space where the job writes (`--out`). If you
  know roughly how much the job will write, say so with `--expect-disk 500G`
  and it refuses a job that would not fit.
- **Inputs.** Name what the job reads with `--input` (repeat it for several).
  Nothing is checked at the start; the folders are recorded, so that the
  [space scan](space_table.md) can later tell whether the job's output could be
  made again.
- **The job card.** It writes a small record of the job: the command, folders,
  cores and GPUs given, start and end times, exit code and estimates. Cards are
  kept in `~/.murmurent/runs/`, readable by you only.
- **Your settings.** The job gets the same environment you have (your conda
  environment, your R and Python), except for anything whose name looks like a
  secret: a token, a password or a key. Those are left out because the copy of
  your settings waits on disk until the job starts. If your job needs one, name
  it: `--pass-env HF_TOKEN`. The job card lists the names that were left out,
  never their values.

**If the server is too busy**, it refuses and says so. Add `--wait` to start the
job as soon as there is room instead.

**Your command runs exactly as typed, without a shell.** To use a pipe or `&&`,
wrap it: `murmurent run -- bash -c 'step_one && step_two'`.

## Start it later

```bash
murmurent run --at 22:00 --cores 40 -- python train.py        # tonight at 22:00
murmurent run --when-load-below 150 --cores 40 -- python train.py   # once the server is quieter
```

Cores and GPUs are chosen when the job actually starts, by the rules in force
at that time: your lab may allow more GPUs at night than during working hours.
Nothing else needs to be set up; the waiting happens inside the job's own tmux
window.

## Check on your jobs

```bash
murmurent jobs                    # what is running, waiting, and ended this week
murmurent jobs show fit_models    # everything about one job, by name or id
```

For example:

```
Now:
  fit_models [20261016-221000-a3f9]: running for 2 h 10 min on 8 cores.
      About 1 h 5 min left, finishing around 01:15 (an estimate from 3 earlier run(s)).
Ended in the last 7 days:
  prep [20261015-140200-77c1]: finished at 15:02 after 41 min (exit code 0).
```

To watch the output as it happens, attach to the job's tmux window with the
command it printed (`tmux attach -t run-...`). To leave without stopping the
job, press `Ctrl-b`, then `d`.

## When a job ends or stalls

One line goes to the project's Slack channel, for example:

```
Job fit_models (you) finished after 3 h 12 min. Exit code 0.
```

The line carries the job's name, whose it is, what happened, how long it ran
and its exit code (0 means success). **It never includes the command or any
file path**, because file names can identify patients. For the same reason, a
job name may not contain a slash: choose a name you would be happy to see in
the channel.

The channel is the project's own, the same one `/murmurent-update-me` posts to.
If murmurent cannot find a channel or the lab's Slack bot on your account, it
posts nothing and says so on the job card. Add `--no-notify` to turn the
message off for one job.

**Filling its disk.** In its first ten minutes the job's output folder is
measured to estimate how fast it grows. If, at that rate, the disk would be
full within a day, one extra line goes to the channel, again without any path.
`murmurent jobs` shows the estimate at any time.

**Stalled** means the job's log has not grown for an hour (your lab may set a
different time). The job is not stopped; look at its log and decide. If your
program writes its progress to its own file instead of the screen, point
`--watch` at that file so the check looks there.

## Stop or restart a job

```bash
murmurent jobs stop fit_models       # asks it to end cleanly, then stops it by force 30 s later
murmurent jobs restart fit_models    # runs the same command again from its card
```

A restart starts the command again from the beginning, with the same folders
and requests and fresh choices of cores and GPUs. It cannot continue a job from
where it stopped unless your program saves its own checkpoints and picks up
from them.

## Asking for more than your allowance

Sometimes a job needs more than your lab allows one person, for example all the
GPUs on a quiet weekend. Ask in the server's channel first. Then give the reason
and when the exception ends:

```bash
murmurent run --gpus 8 --exception "agreed in the server channel, nobody else on" --until "2026-10-19 08:00" -- python train.py
```

The exception is recorded on the job card. It lifts your personal allowances
(cores, GPUs and memory). It never lifts the protections that keep the server
usable for everyone: new work is still held when the server is busy, memory is
still kept free, and the disk must still have room.

## Estimates

Estimates are labelled as estimates, and often there is none yet.

- **Time** comes from earlier finished runs of the same command in the same
  folder. A first run has no time estimate.
- **Disk** comes from how fast the output folder (`--out`) grows in the job's
  first ten minutes, compared with the free space. If the disk would fill
  before the job is expected to finish, `murmurent jobs` says so.

## The lab's rules (for the PI)

The rules live in one file in your lab's management repository,
`policy/millwright.yaml`, so the written procedure and what the tool does stay
the same. `murmurent pi-init` creates it from the commented example that ships
with murmurent; for a lab set up before that, create it once and change the
numbers. Any setting left out keeps murmurent's modest built-in default. To see
the rules in force and the files they came from:

```bash
murmurent jobs policy --init   # creates the file if the lab has none
murmurent jobs policy          # the rules in force
```

| Setting | Built-in default | What it controls |
|---|---|---|
| `priority` | 19 | The `nice` priority of every job |
| `max_cores_per_person` | 16 | Cores one person's jobs may use at once |
| `default_cores` | 1 | Cores for a job that does not ask |
| `hold_new_work_at_load_fraction` | 0.8 | New work waits once the server's load passes this share of its cores |
| `min_free_memory_fraction` | 0.20 | A job may not leave less memory free than this share |
| `memory_per_person_fraction` | 0.25 | Memory one person may claim with `--memory` without an exception |
| `working_hours` | weekdays 08:00 to 18:00 | When the daytime GPU allowance applies |
| `gpus_per_person_working_hours` | 1 | GPUs per person in working hours |
| `gpus_per_person_outside_hours` | 2 | GPUs per person at other times; `all` means every idle GPU |
| `stall_minutes` | 60 | Minutes without output before a job is reported as stalled |
| `disk_fill_limit_fraction` | 0.95 | A stated output may not fill the disk past this share |

The **load** is the number of processes running or waiting for a core, averaged
over the last minute; `uptime` prints it. A value in the file that murmurent
cannot use (a typing mistake, say) is ignored and named by `murmurent jobs
policy`, and the earlier value is kept, so a mistake cannot remove a limit.

## Server etiquette: a daily check (for the PI)

`murmurent etiquette check` looks at the server and reports lab members whose
jobs run above nice 19, use more cores than `max_cores_per_person`, or hold
more GPUs than the allowance for the time of day. It reads each process's
account, priority, CPU share and age, and which GPUs it holds; never command
lines, which can contain file names. It needs no administrator rights and
never changes anyone's jobs.

- Only members of your lab are named. Other accounts appear as a count, so you
  can raise a persistent problem with the server's administrator.
- Each person is compared with their own allowance, not with other people.
- A process counts only after it has run for 10 minutes, and a priority note
  needs at least a core's worth of work, so an editor or a short burst is not
  reported.

By default it only prints its report. With `--notify`, the person gets a
direct message the first day, saying what was seen, why it matters and the
exact command that fixes it (for example `renice -n 19 -u <login>`). If it is
still there at the next check, a line goes to the lab's Slack channel; after
that, to you. A day without the issue starts again from the beginning.

Each day it also sends a summary: lab members over the rules by name, and
other accounts as counts. It goes to you as a direct message, unless your
lab's policy file names a Slack channel for it:

```yaml
# in policy/millwright.yaml of your lab's management repository
etiquette_summary_channel: "#computers"
```

Invite the lab's bot into that channel once (`/invite @<bot name>` in Slack).
If a post fails, the summary comes to you instead.

To run it every weekday at 11:00 under your account:

```bash
murmurent etiquette schedule --install            # report only, to begin
murmurent etiquette schedule --install --notify   # once the report looks right
murmurent etiquette schedule --remove
```

The schedule is written into `policy/scheduled_jobs.md` in the lab records
repository, beside the space scan, so the lab can see what runs in your name.

## What it cannot do

- **It does not enforce limits.** It sets the priority and the thread settings
  and chooses sensibly; a program that starts its own workers (R's `parallel`
  package, Python's `multiprocessing`) uses whatever number you give it. Give
  it the same number, for example from `Sys.getenv("OMP_NUM_THREADS")` in R or
  `os.environ["OMP_NUM_THREADS"]` in Python.
- **It needs tmux.** If tmux is not installed, `murmurent run` says so and
  starts nothing. Ask the server's administrator to install it.
- **It watches only your own jobs.** Other people's jobs are not its business.
