# Tidying a project's space

`murmurent space scan` looks through one project's repositories and data
folders and lists files that could be deleted, compressed, moved, or asked
about, most pressing first. You decide on each one. The command never changes,
moves or deletes a file.

## Why use it

A shared server fills up slowly, and finding out why takes hours: whose files
are these, are they still needed, can they be made again? The scan does that
first pass for you. For each suggestion it gives a plain reason and the
evidence behind it, so you can decide in seconds rather than investigate.

## Scan a project

Run it from inside one of the project's repositories, or name the project:

```bash
murmurent space scan              # the project of the repository you are in
murmurent space scan my_project   # or name it
```

It reports what it found, with the three most pressing items first:

```
Scanning project my_project: ~/repos/my_project, append_only/my_project, immutable/my_project
Scanned 48,211 files, 2.3 TB.

Look at these first (of 37 waiting for a decision)
  1.  870.0 GB  duplicate, suggest delete  [row 12]
      append_only/my_project/02_align/sample_copy.bam
      An identical copy is kept at immutable/my_project/sample.bam.
      Evidence: same size and SHA-256 fingerprint as immutable/my_project/sample.bam.
      Owner jsmith, last changed 2026-03-02.
  ...

Nothing was changed, moved or deleted.
```

The scan runs at the lowest priority, so it does not slow anyone else down. On
a large project it can take a while; it prints a line every 50,000 files.

## What it looks for

| Category | What it means | Usual suggestion |
|---|---|---|
| temporary | Files programs leave behind: `nohup.out`, crash dumps, partial downloads, notebook checkpoints, `__pycache__` folders. Only once they are a week old (the lab can change this). | delete |
| intermediate | Output of a job you ran with `murmurent run` that could be made again (see below). | delete, or ask the owner |
| compressible | Large uncompressed text data: FASTQ, SAM, VCF, BED, CSV and similar. The reason names a lossless way to compress it. | compress |
| duplicate | Two files with the same size and the same fingerprint. The copy in the most protected place is kept. | delete |
| out of place | A large file inside a repository; a file loose at the top of the project's append-only folder; a data folder with no matching experiment folder in `exp/`. | move, or ask the owner |
| unattributed | Files owned by someone who is not a member of the project. Grouped by owner and folder. | ask the owner |
| listed | Files a member already listed in `src/ready_to_delete.md`. | delete |
| access | Files anyone on the server can change (or, for a protected project, read). These go to the security guard, not to you. | refer to security guard |
| unreadable | A folder the scan could not look into, so its size is unknown. | ask the owner |

A **fingerprint** (a checksum) is a short number worked out from a file's
contents. Two files with the same fingerprint are identical.

## What it never suggests

- **Nothing in `immutable/` is suggested for deletion or compression.** The
  lab's rule is that raw data is never changed. A duplicate or a listed file
  there is marked "ask the owner" instead.
- **Folders your project only reads** (`reads_from` in the project record) are
  not looked at.
- **When the project has a keep-until date** (`retain_until`, set from an
  ethics approval, a data-sharing agreement or a funder's rule), every "delete"
  becomes "keep" until that date.
- **Software environments** (`.venv`, `node_modules`, conda environments and
  similar) are skipped: they hold installed software, not data.

## When a job's output can be made again

If you start jobs with `murmurent run`, the scan can tell whether their output
is cheap to make again. Tell `murmurent run` what the job reads with
`--input`, as well as where it writes with `--out`:

```bash
murmurent run --name align --cores 8 \
    --input "$MURMURENT_DATA_ROOT/immutable/my_project/reads" \
    --out "$MURMURENT_DATA_ROOT/append_only/my_project/02_align" \
    -- bash exp/02_align/run_all.sh
```

The scan then suggests deleting that job's output only when all of these hold:

1. the job finished without error;
2. its script is committed to git and has not changed since the job ran;
3. every input it recorded still exists;
4. making the output again would take fewer CPU hours than the lab's limit
   (10 unless the lab sets another);
5. the output folder holds only files the job wrote.

If any one fails, the row says which, and suggests asking the owner. A scan
can only read your own job records, because they are kept in each person's
home folder.

## See the whole table

```bash
murmurent space show my_project                       # waiting rows, largest first
murmurent space show my_project --category duplicate  # one category
murmurent space show my_project --owner jsmith        # one person's files
murmurent space show my_project --min-size 10G        # only big items
murmurent space show my_project --all                 # include decided and kept rows
```

The order of "Look at these first" weighs four things: size, how full the disk
is, how long the item has waited, and how much it grew since the last scan.

Two things count as an **emergency** and are listed above everything else: a
disk more than 90% full, and a single item larger than a quarter of its disk's
free space.

## Record a decision

Each row has a number. Record what you decided:

```bash
murmurent space decide 12 delete --note "copy of the raw BAM, keep the original"
murmurent space decide 15 keep --note "needed for the revision"
murmurent space decide 15 undo
```

The PI can also record a decision on the dashboard's Space page: each row has
a "Decide" column. The choices are keep, delete, mothball, compress and move.
Recording a decision changes nothing on disk. Scanning again keeps every decision.

## Carry out decisions

`murmurent space carry-out` makes a copy for each mothball, compress or move
decision, checks the copy against fingerprints of the original, and logs who
did it and when. A fingerprint is a short code computed from a file's
contents: if two files have the same fingerprint, they are identical.

murmurent never removes the original. Once the copy is checked, you remove
the original yourself. This keeps a person in charge of every deletion.

```bash
murmurent space carry-out             # show what would be done; changes nothing
murmurent space carry-out --apply     # do it
murmurent space carry-out --row 12 --to /path/to/new/place --apply   # a move needs --to
murmurent space removable             # originals you may now remove
```

What each decision does:

- **mothball**: copies to the lab's backup drive, under a folder named after
  the project. The PI sets the drive in the lab's policy file
  (`mothball_target`); until then, mothballing is refused. A copy that would
  fill the drive past `mothball_target_fill_limit` (90% unless set) is
  refused.
- **compress**: writes a `.gz` copy beside a text file (FASTQ, FASTA, CSV,
  TSV, plain text; VCF, BED, GFF and GTF use bgzip when it is installed, so
  they stay indexable). Lossless only. Never inside `immutable/` or
  `mothballed/`. SAM files are not converted; do that by hand.
- **move**: copies to the place you give with `--to`.

Nothing is overwritten: if the copy's name is already taken, the row is
skipped. If any file in a copy does not match, the action is marked failed,
the copy is left for you to look at, and the original is not listed as
removable.

`murmurent space removable` lists originals whose copy was checked, and rows
you decided to delete. A project with a keep-until date in the future is
listed separately, as held. The log of every action is
`~/.murmurent/space/actions.log`, readable by you only.

## Gaps in the lab's procedures

When the scan meets a case the lab's rules do not cover, it records it with an
example: a large file of a type no rule mentions, or a project whose members
have no known server login. List them with:

```bash
murmurent space gaps my_project
```

These are for the PI, to decide whether a rule needs writing.

## Privacy

- The scan reads sizes, dates, owners and names. To find duplicates it reads
  large files of the same size to fingerprint them, up to a limit the lab sets
  (100 GB unless it says otherwise); add `--no-checksums` to skip that.
- For files owned by a non-member in a project **not** marked protected, the
  table keeps the first three lines, so you can tell what the file is. In a
  protected project nothing inside a file is read for this.
- The table is kept in your own murmurent folder (`~/.murmurent/space/`),
  readable only by you. It is never posted to Slack or GitHub, and nothing is
  written to the project's repositories.

## The lab's settings (for the PI)

The thresholds are in the lab's policy file, `policy/millwright.yaml` in the
lab's management repository, alongside the rules for `murmurent run`:

| Setting | Default | Meaning |
|---|---|---|
| `temporary_min_age_days` | 7 | Days before a temporary file is suggested for deletion |
| `large_file_in_repo_mb` | 100 | A file this big inside a repository is out of place |
| `compress_min_mb` | 100 | Text data this big is suggested for compression |
| `duplicate_min_mb` | 10 | Files this big are compared for duplicates |
| `duplicate_max_read_gb` | 100 | The most one scan reads in full to confirm duplicates; past it, matches are listed as probable |
| `remake_cheap_below_cpu_hours` | 10 | Below this, a job's output may be suggested for deletion |
| `disk_emergency_fill_fraction` | 0.90 | A disk fuller than this is an emergency |
| `emergency_item_share_of_free` | 0.25 | One item bigger than this share of free space is an emergency |
| `scan_threads` | 8 | Folders listed at once. On the lab's drive this made little difference (about 10 minutes per million files either way) |

`murmurent jobs policy` prints the settings in force.

## Turning the space audit on or off (for the PI)

The weekly lab scan below, and the dashboard's **space audit** page, are
optional. They suit a lab whose PI has an account on the lab's data server and
wants a weekly view of its disk use. Choose in the dashboard under
**⚙ Lab settings → Space audit**:

- **not chosen** (the starting point): the dashboard does not show the space
  audit. The Lab audits panel says it exists and how to turn it on.
- **on**: the dashboard shows the "space audit" button and the Space page.
  Then set up the weekly scan once on the data server (next section).
- **off**: the dashboard stops showing it, and the weekly scan does nothing
  if one was set up before (`murmurent space schedule --remove` deletes it).

The audit never needs administrator rights. What it does need: an account on
the data server, murmurent installed there, read access to the members'
project folders through the lab's group, and, for the scan to run while you
are logged out, an administrator to run `loginctl enable-linger <your login>`
once. Without that last step it runs only while you are logged in.

The per-project commands (`murmurent space scan`, `show`, `decide`) work in
any case: they are personal and need none of this.

## The weekly lab scan (for the PI)

A project nobody opens any more is never scanned by `murmurent space scan`, so
the lab also runs one scan of everything, once a week, on the server where the
data lives:

- every project's data folders (not repositories, which live in members' home
  folders);
- every folder under the data root that no project claims, with who owns how
  much of it;
- for a project unused for 24 months (the lab can change this), a suggestion to
  mothball its data: back it up, then remove it from the server.

Other labs' folders are never scanned. The scan runs under the PI's account at
the lowest priority, only reads, and sends the PI one Slack direct message:
totals, emergencies and project names, never a file name.

Set it up once, on the server, as the PI:

```bash
murmurent space schedule --install    # every Sunday at 02:00; --day and --at change it
murmurent space schedule              # when it runs next, and whether it needs you logged in
```

This writes what runs, under whose account and what it may do into
`policy/scheduled_jobs.md` in the lab records repository; commit and push it
so the lab can see it.

**Logged in or not.** The scan uses the server's own scheduler for your
account. Unless the administrator has turned on "lingering" for your account,
it runs only while you have a session on the server, and a missed run happens
at your next login. `murmurent space schedule` says which applies. To have it
run while you are logged out, ask the administrator to run
`loginctl enable-linger <your login>`.

Run it by hand at any time with `murmurent space scan-lab`.
To redo the report's summaries from the last scan, without walking the drive
again (for example after murmurent is updated), run `murmurent space lab
--rebuild` on the server.

**What the scan cannot read is reported, not ignored.** Folders the scanning
account may not open, and files it may not look at, are in no total, so every
figure is low by an unknown amount. The report, the Slack message and the Space
page list them by owner, and each row gives the fix for the owner to run:
`chmod -R g+rX <folder>`, which lets the lab group read it.

## Seeing the lab report on your laptop

The report stays on the server, readable only by you. Your laptop fetches it
when you ask, through the same SSH connection murmurent already uses for that
server (`murmurent host list`):

```bash
murmurent space lab --host <server>   # in a terminal on your laptop
```

Or open **Space** at the top of your dashboard (PI view), choose the server and
click **Fetch report**. Both show emergencies, the three most pressing items
across the lab, and every project with how much is waiting for a decision. To
see every row of one project or record a decision, use `murmurent space show`
and `murmurent space decide` on the server.

For protected projects, and for folders no project claims, the lab-wide list of
pressing items gives sizes but no file names.

## What it cannot do yet

- It does not remove files: `carry-out` copies and checks, and a person
  removes the originals.
