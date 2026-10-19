"""
Purpose: The space scan for one project (issue #151, step 2). Walks the
         project's repositories and data folders, and suggests what could be
         deleted, compressed, moved or asked about, with the evidence for each.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   A project record; the files in its repositories and data folders
         (sizes, dates, owners and names); this person's job cards from
         ``murmurent run``; ``src/ready_to_delete.md`` in the code repository;
         the lab's policy file.
Output:  A :class:`core.space_table.ScanSummary`, and an updated
         ``~/.murmurent/space/data_dates.json`` (when each data folder last
         changed), which step 0 reads to work out when a project was last used.

What the scan reads. Sizes, dates, owners and names, never contents, with two
exceptions the PI agreed to on 2026-10-16:

1. To find duplicates, files of the same size (above a set size) are
   fingerprinted, which reads them. The fingerprint is a number; nothing in the
   file is kept or shown. ``--no-checksums`` turns this off.
2. For a file no project member owns, in a project not marked protected, the
   first three lines are kept in the table, so the PI can tell what it is. For
   a protected project, nothing inside a file is ever read for this.

What the scan never does. It changes no file, follows no link out of the
project, and never walks a folder the project only reads (``reads_from``).
Anything in ``immutable/`` is never suggested for deletion or compression,
because the lab's rule is that it is never changed.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from . import cert_projects as _cp
from . import lab_vm as _lab_vm
from . import project_unit as _pu
from . import sensitivity as _sens
from . import space_table as _st
from .millwright_policy import Policy, load_policy

_log = logging.getLogger(__name__)

MB = 1024 * 1024

#: Folders whose whole contents are temporary, by name.
TEMPORARY_FOLDERS = {
    ".ipynb_checkpoints": "notebook checkpoints Jupyter saves automatically",
    "__pycache__": "compiled Python files, remade automatically",
    ".pytest_cache": "test runner scratch files",
    ".mypy_cache": "type checker scratch files",
}

#: Folders holding installed software, not data. They are not walked: their
#: files are the environment's, and copies inside them are not duplicates
#: anyone should remove by hand. A folder is also one of these when it holds
#: ``pyvenv.cfg`` (a Python environment) or ``conda-meta`` (a conda one).
ENVIRONMENT_FOLDERS = {".venv", "venv", "node_modules", ".tox", ".nox", ".conda", ".snakemake",
                       ".Rproj.user"}

#: Temporary files, by exact name or by pattern, with what each is.
TEMPORARY_NAMES = {
    "nohup.out": "output captured by nohup",
    "Rplots.pdf": "plots R saves when no plot window is open",
}
TEMPORARY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^core\.\d+$"), "a memory dump from a program that crashed"),
    (re.compile(r".*\.(tmp|temp)$", re.I), "a temporary file"),
    (re.compile(r"^\..*\.sw[op]$"), "an editor's recovery file"),
    (re.compile(r".*\.(part|partial|crdownload)$", re.I), "an unfinished download"),
    (re.compile(r"^\.~lock\..*#$"), "a lock file left by an office program"),
)

#: Uncompressed text formats worth compressing, and the lossless way to do it.
COMPRESS_METHODS = {
    ".fastq": "gzip (or pigz, which is faster); every aligner reads .fastq.gz",
    ".fq": "gzip (or pigz, which is faster); every aligner reads .fq.gz",
    ".fasta": "gzip, or bgzip to keep it indexable with samtools faidx",
    ".fa": "gzip, or bgzip to keep it indexable with samtools faidx",
    ".sam": "convert to BAM with samtools view -b (lossless, about a quarter the size)",
    ".vcf": "bgzip, then tabix to index it",
    ".bed": "bgzip, then tabix to index it",
    ".gff": "bgzip, then tabix to index it",
    ".gff3": "bgzip, then tabix to index it",
    ".gtf": "bgzip, then tabix to index it",
    ".csv": "gzip or zstd; pandas and readr read .csv.gz directly",
    ".tsv": "gzip or zstd; pandas and readr read .tsv.gz directly",
    ".txt": "gzip or zstd",
    ".mtx": "gzip; Matrix Market readers accept .mtx.gz",
    ".json": "gzip or zstd",
    ".tab": "gzip or zstd",
}

#: Large-file types a rule already covers: compressed, binary formats, images.
#: A large file with any other ending is a gap in the lab's procedures.
KNOWN_TYPES = set(COMPRESS_METHODS) | {
    ".gz", ".bgz", ".bz2", ".xz", ".zst", ".zip", ".tar", ".7z",
    ".bam", ".bai", ".cram", ".crai", ".csi", ".tbi",
    ".h5", ".hdf5", ".h5ad", ".h5mu", ".loom", ".zarr", ".parquet", ".feather", ".arrow",
    ".rds", ".rda", ".rdata", ".qs", ".pkl", ".pickle", ".npy", ".npz", ".mat",
    ".bw", ".bigwig", ".bb", ".bigbed", ".hic", ".cool", ".mcool",
    ".fast5", ".pod5", ".bcl", ".cbcl", ".sra", ".mzml", ".mzxml", ".raw", ".wiff",
    ".tif", ".tiff", ".ome.tif", ".svs", ".ndpi", ".czi", ".lif", ".nd2", ".vsi", ".mrxs",
    ".nii", ".dcm", ".mrc", ".png", ".jpg", ".jpeg", ".pdf", ".mp4", ".avi", ".mov",
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".bin", ".sqlite", ".db",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
}

#: Seconds of slack either side of a job's start and end when deciding whether
#: a file was written by that job.
_JOB_WINDOW_SLACK = 120

#: How much of a file the quick fingerprint reads from each end.
_QUICK_FINGERPRINT_BYTES = 1 * MB

#: The most unreadable folders listed one by one; past this they are counted.
_MAX_UNREADABLE_ROWS = 200

#: Lines kept from the start of an unattributed file, and their longest length.
_PEEK_LINES = 3
_PEEK_LINE_CHARS = 120

#: Seconds to wait for one git command.
_GIT_TIMEOUT = 60

ROOT_REPO = "repository"
ROOT_IMMUTABLE = "immutable"
ROOT_APPEND_ONLY = "append_only"
ROOT_DATA = "data folder"
#: A project's folder in mothballed/ (#206): waiting for long-term storage.
#: People move files there; the scan never suggests deleting or changing them.
ROOT_MOTHBALLED = "mothballed"
#: Folders whose contents only a person decides about.
HANDS_OFF = frozenset({ROOT_IMMUTABLE, ROOT_MOTHBALLED})

# Where a copy is kept when there are duplicates: the most protected place.
_KEEP_ORDER = {ROOT_IMMUTABLE: 0, ROOT_MOTHBALLED: 1, ROOT_APPEND_ONLY: 2, ROOT_DATA: 3,
               ROOT_REPO: 4}


@dataclass(frozen=True)
class Root:
    """One folder the scan walks: a repository or a data folder."""

    path: Path
    kind: str
    disk: str = ""


@dataclass
class _Group:
    """Files gathered under one row while walking."""

    size: int = 0
    n_files: int = 0
    newest: float = 0.0
    example: str = ""
    example_size: int = -1

    def add(self, path: str, size: int, mtime: float) -> None:
        self.size += size
        self.n_files += 1
        self.newest = max(self.newest, mtime)
        if size > self.example_size:
            self.example, self.example_size = path, size


@dataclass
class _JobOutput:
    """A finished job's output folder, and what the walk found in it."""

    card: object
    folder: Path
    start: float
    end: float
    written: _Group = field(default_factory=_Group)
    other: _Group = field(default_factory=_Group)


@dataclass
class _Candidate:
    """A big file that may have a duplicate."""

    path: str
    size: int
    mtime: float
    owner: str
    root_kind: str
    disk: str
    dev: int
    ino: int


def _iso(ts: float) -> str:
    if not ts:
        return ""
    return _dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


@lru_cache(maxsize=4096)
def owner_name(uid: int) -> str:
    """The login that owns files with user number ``uid``, or the number."""
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)


def _ext(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".ome.tif"):
        return ".ome.tif"
    return os.path.splitext(lower)[1]


def _is_dir(path: Path) -> bool:
    """``path.is_dir()``, False when the account may not look (instead of raising)."""
    try:
        return path.is_dir()
    except OSError:
        return False


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# What to walk
# ---------------------------------------------------------------------------


def _root_kind(folder: Path, env: dict | None) -> str:
    for kind, base in ((ROOT_IMMUTABLE, _lab_vm.immutable_root(env)),
                       (ROOT_APPEND_ONLY, _lab_vm.append_only_root(env)),
                       (ROOT_MOTHBALLED, _lab_vm.data_root(env) / "mothballed")):
        base = Path(os.path.normpath(base))
        if _within(folder, base) or _within(_pu._resolved(folder), _pu._resolved(base)):
            return kind
    return ROOT_DATA


def project_roots(cp: _cp.CertProject, env: dict | None = None, *,
                  include_repos: bool = True) -> list[Root]:
    """The repositories on this machine and the data folders that exist, in order.

    A folder inside another root is left out, so nothing is counted twice.
    ``include_repos=False`` gives the data folders only, as the lab-wide scan
    walks them.
    """
    found: list[Root] = []
    for r in (cp.repos if include_repos else ()):
        if (r.host or "local") != "local" or not r.path:
            continue
        path = Path(os.path.normpath(Path(r.path).expanduser()))
        if _is_dir(path):
            found.append(Root(path=path, kind=ROOT_REPO))
    for folder in _pu.effective_data_folders(cp, env):
        if _is_dir(folder):
            found.append(Root(path=folder, kind=_root_kind(folder, env)))
    kept: list[Root] = []
    for root in found:
        if any(other.path != root.path and _within(root.path, other.path) for other in found):
            continue
        if root.path not in [k.path for k in kept]:
            kept.append(root)
    return kept


def _login_exists(name: str) -> bool:
    try:
        import pwd
        pwd.getpwnam(name)
    except (ImportError, KeyError):
        return False
    return True


def member_logins(cp: _cp.CertProject) -> tuple[set[str], list[str]]:
    """Server logins of the project's members and lead, and handles with none known.

    First the project access check's mapping: an ``os_user`` set in the
    member's file, else their institutional net name. Failing both, the handle
    itself when an account of exactly that name exists on this server, since a
    member's handle is their net name and the net name is their login. The
    access check does not make that last guess; here a wrong guess only changes
    which files are listed as unattributed, in a report a person reads.
    """
    from .project_access import resolve_member_os_user
    handles = {h.strip().lstrip("@") for h in (*cp.members, cp.lead) if str(h).strip()}
    logins: set[str] = set()
    unknown: list[str] = []
    for handle in sorted(handles):
        login = resolve_member_os_user(handle) or (handle if _login_exists(handle) else None)
        if login:
            logins.add(login)
        else:
            unknown.append(handle)
    return logins, unknown


def git_tracked(repo: Path) -> set[str] | None:
    """Paths git tracks in ``repo``, relative to it; None when git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                             capture_output=True, timeout=_GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}


def experiment_names(cp: _cp.CertProject) -> set[str] | None:
    """Folder names under ``exp/`` in the project's code repository on this machine.

    None when no code repository with an ``exp/`` folder is here, so the scan
    cannot check data folders against experiments.
    """
    for r in cp.repos:
        if r.role != "code" or (r.host or "local") != "local" or not r.path:
            continue
        exp = Path(r.path).expanduser() / "exp"
        if exp.is_dir():
            try:
                return {p.name for p in exp.iterdir() if p.is_dir()}
            except OSError:
                return None
    return None


# ---------------------------------------------------------------------------
# Job cards: which output can be made again, and at what cost
# ---------------------------------------------------------------------------


#: Programs that run a script named after them, such as ``python fit.py``.
INTERPRETERS = {"python", "python3", "rscript", "r", "bash", "sh", "zsh", "julia", "perl",
                "ruby", "node", "snakemake", "nextflow", "matlab", "octave", "uv", "conda"}


def _script_in(card, workdir: Path) -> Path | None:
    """The job's script: the program itself, or the first file given to an interpreter."""
    command = [str(a) for a in (getattr(card, "command", None) or [])]
    if not command:
        return None

    def as_file(arg: str) -> Path | None:
        path = Path(arg).expanduser()
        path = path if path.is_absolute() else workdir / path
        return path if path.is_file() else None

    if os.path.basename(command[0]).lower() not in INTERPRETERS:
        return as_file(command[0])
    for arg in command[1:]:
        if arg.startswith("-"):
            continue
        found = as_file(arg)
        if found:
            return found
    return None


def script_state(script: Path, started: float) -> tuple[bool, str]:
    """Whether ``script`` is committed and unchanged since the job ran, and why not."""
    repo = script.parent
    try:
        top = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False)
        if top.returncode != 0:
            return False, f"the script {script.name} is not in a git repository"
        root = top.stdout.strip()
        rel = os.path.relpath(script, root)
        tracked = subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", rel],
                                 capture_output=True, timeout=_GIT_TIMEOUT, check=False)
        if tracked.returncode != 0:
            return False, f"the script {script.name} is not committed"
        dirty = subprocess.run(["git", "-C", root, "diff", "--quiet", "HEAD", "--", rel],
                               capture_output=True, timeout=_GIT_TIMEOUT, check=False)
        if dirty.returncode != 0:
            return False, f"the script {script.name} has changes that are not committed"
        last = subprocess.run(["git", "-C", root, "log", "-1", "--format=%ct", "--", rel],
                              capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False)
        when = float(last.stdout.strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, f"git could not say whether {script.name} is committed"
    if when > started + _JOB_WINDOW_SLACK:
        return False, (f"the script {script.name} was changed after the job ran, so running it "
                       "again would not give the same files")
    return True, f"the script {script.name} is committed and unchanged since the job ran"


def job_outputs(project: str, roots: list[Root],
                env: dict | None = None) -> list[_JobOutput]:
    """Finished, successful jobs of this project whose output folder is scanned.

    One per output folder: the newest job wins. Only this person's job cards
    can be read, since cards live in each person's home folder.
    """
    from . import run_cards as _cards
    try:
        cards = _cards.list_cards(env)
    except OSError:
        return []
    want = project.strip().casefold()
    by_folder: dict[Path, _JobOutput] = {}
    for card in cards:
        if str(card.project or "").strip().casefold() != want:
            continue
        if card.state != _cards.STATE_FINISHED or card.exit_code != 0 or not card.out:
            continue
        start, end = _cards.from_iso(card.started_at), _cards.from_iso(card.ended_at)
        if start is None or end is None:
            continue
        folder = Path(os.path.normpath(card.out))
        root = next((r for r in roots if _within(folder, r.path)), None)
        if root is None or root.kind in HANDS_OFF:
            continue
        current = by_folder.get(folder)
        if current is None or end.timestamp() > current.end:
            by_folder[folder] = _JobOutput(card=card, folder=folder, start=start.timestamp(),
                                           end=end.timestamp())
    return list(by_folder.values())


def _cpu_hours(card) -> float:
    seconds = card.duration_seconds() or 0.0
    return round(max(int(card.cores or 0), 1) * seconds / 3600, 2)


def _intermediate_item(job: _JobOutput, roots: list[Root], policy: Policy) -> _st.Item | None:
    if job.written.n_files == 0:
        return None
    card = job.card
    cost = _cpu_hours(card)
    evidence: list[str] = [f"job {card.name} ({card.id}) wrote these files between "
                           f"{card.started_at} and {card.ended_at} and finished without error"]
    doubts: list[str] = []
    script = _script_in(card, Path(card.workdir))
    if script is None:
        doubts.append("the job's script could not be found")
    else:
        ok, why = script_state(script, job.start)
        (evidence if ok else doubts).append(why)
    inputs = list(card.inputs or [])
    if not inputs:
        doubts.append("the job did not record its inputs (use --input next time)")
    else:
        missing = [i for i in inputs if not os.path.exists(i)]
        if missing:
            doubts.append(f"{len(missing)} of its inputs no longer exist, such as {missing[0]}")
        else:
            evidence.append(f"all {len(inputs)} of its recorded inputs still exist")
    if job.other.n_files:
        doubts.append(f"the folder also holds {job.other.n_files} files the job did not write")
    if any(job.folder == r.path for r in roots):
        doubts.append("the job wrote straight into a top-level data folder, not a folder of its own")
    cheap = cost < policy.remake_cheap_below_cpu_hours
    if not cheap:
        doubts.append(f"making them again would take about {cost:g} CPU hours")
    disk = next((r.disk for r in roots if _within(job.folder, r.path)), "")
    if doubts:
        suggestion = _st.ASK_OWNER
        reason = "Made by a recorded job, but " + "; ".join(doubts) + "."
    else:
        suggestion = _st.DELETE
        reason = (f"Can be made again in about {cost:g} CPU hours from committed code and inputs "
                  "that still exist.")
    return _st.Item(path=str(job.folder), category=_st.INTERMEDIATE, suggestion=suggestion,
                    reason=reason, kind="files", size=job.written.size,
                    n_files=job.written.n_files, owner=str(card.user),
                    changed_at=_iso(job.written.newest), evidence="; ".join(evidence),
                    cost_cpu_hours=cost, disk=disk)


# ---------------------------------------------------------------------------
# ready_to_delete.md
# ---------------------------------------------------------------------------

_BACKTICKED = re.compile(r"`([^`]+)`")


def ready_to_delete_entries(cp: _cp.CertProject) -> list[tuple[str, Path]]:
    """Paths listed in ``src/ready_to_delete.md`` of the project's repositories.

    Returns (repository name, path) pairs. A path is taken from a list line,
    from text in backticks, or the line's first word when it looks like a path.
    Relative paths are read against the project's append-only folder, then the
    data root, then the repository.
    """
    found: list[tuple[str, Path]] = []
    for r in cp.repos:
        if (r.host or "local") != "local" or not r.path:
            continue
        repo = Path(r.path).expanduser()
        listing = repo / "src" / "ready_to_delete.md"
        try:
            text = listing.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*", "|")) and not _BACKTICKED.search(stripped):
                continue
            ticks = _BACKTICKED.findall(stripped)
            words = ticks or [stripped.lstrip("-*| ").split(" ")[0].strip("|")]
            for word in words:
                word = word.strip()
                if not word or ("/" not in word and "." not in word):
                    continue
                found.append((r.name or repo.name, _resolve_listed(word, cp, repo)))
    return found


def _resolve_listed(word: str, cp: _cp.CertProject, repo: Path) -> Path:
    path = Path(word).expanduser()
    if path.is_absolute():
        return Path(os.path.normpath(path))
    for base in (_lab_vm.project_append_only_dir(cp.name), _lab_vm.data_root(), repo):
        candidate = Path(os.path.normpath(Path(base) / path))
        if candidate.exists():
            return candidate
    return Path(os.path.normpath(_lab_vm.project_append_only_dir(cp.name) / path))


# ---------------------------------------------------------------------------
# Reading files, only where agreed
# ---------------------------------------------------------------------------


def peek(path: str) -> str:
    """The first few lines of a text file, shortened; a word for anything else."""
    if _ext(path) in {".gz", ".bgz", ".bz2", ".xz", ".zst", ".zip", ".bam", ".cram"}:
        return "(compressed; not opened)"
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return "(could not be read)"
    if b"\0" in head:
        return "(not text)"
    lines = head.decode("utf-8", "replace").splitlines()[:_PEEK_LINES]
    return "\n".join(line[:_PEEK_LINE_CHARS] for line in lines)


def _fingerprint(path: str, size: int, quick: bool) -> str | None:
    """A fingerprint of the file: both ends only when ``quick``, else all of it."""
    digest = hashlib.blake2b(digest_size=20) if quick else hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            if quick:
                digest.update(handle.read(_QUICK_FINGERPRINT_BYTES))
                if size > 2 * _QUICK_FINGERPRINT_BYTES:
                    handle.seek(size - _QUICK_FINGERPRINT_BYTES)
                    digest.update(handle.read(_QUICK_FINGERPRINT_BYTES))
            else:
                for chunk in iter(lambda: handle.read(8 * MB), b""):
                    digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _unique(copies: list[_Candidate]) -> list[_Candidate]:
    """One entry per file on disk (hard links are one file), most protected first."""
    unique = list({(c.dev, c.ino): c for c in copies}.values())
    unique.sort(key=lambda c: (_KEEP_ORDER.get(c.root_kind, 9), c.mtime, c.path))
    return unique


def duplicate_items(candidates: list[_Candidate], *, retention_blocked: bool,
                    max_read_bytes: int | None = None) -> list[_st.Item]:
    """See :func:`find_duplicates`; this returns only the rows."""
    return find_duplicates(candidates, retention_blocked=retention_blocked,
                           max_read_bytes=max_read_bytes)[0]
    # find_duplicates returns (rows, bytes read, files not compared)


def find_duplicates(candidates: list[_Candidate], *, retention_blocked: bool,
                    max_read_bytes: int | None = None) -> tuple[list[_st.Item], int, int]:
    """Rows for files with the same size and the same fingerprint.

    Within each set of identical files, the copy in the most protected place
    is kept (``immutable/``, then ``append_only/``, then other data folders,
    then repositories; the oldest wins a tie). Every other copy is a row. A copy
    in ``immutable/`` is never suggested for deletion, only asked about.

    Files of the same size are first compared by their first and last megabyte,
    which is quick. Only those that match are read in full, largest first,
    until ``max_read_bytes`` have been read. A match that does not fit in what
    is left is listed as a probable duplicate for a person to confirm, never
    suggested for deletion.
    """
    by_size: dict[int, list[_Candidate]] = defaultdict(list)
    for c in candidates:
        by_size[c.size].append(c)
    budget = max_read_bytes
    spent = 0
    skipped = 0
    groups: list[list[_Candidate]] = []
    # The quick comparison reads up to 2 MB of each file. Across millions of
    # files those reads add up to hundreds of gigabytes, so they come out of
    # the same budget as the full reads, largest files first.
    for size, same in sorted(by_size.items(), key=lambda kv: kv[0], reverse=True):
        if len(_unique(same)) < 2:
            continue
        quick_cost = len(same) * min(size, 2 * _QUICK_FINGERPRINT_BYTES)
        if budget is not None and quick_cost > budget:
            skipped += len(same)
            continue
        if budget is not None:
            budget -= quick_cost
        spent += quick_cost
        by_quick: dict[str, list[_Candidate]] = defaultdict(list)
        for c in same:
            fp = _fingerprint(c.path, size, quick=True)
            if fp:
                by_quick[fp].append(c)
        groups += [_unique(g) for g in by_quick.values() if len(_unique(g)) >= 2]

    items: list[_st.Item] = []
    for group in sorted(groups, key=lambda g: g[0].size * len(g), reverse=True):
        cost = group[0].size * len(group)
        if budget is not None and cost > budget:
            kept = group[0]
            for extra in group[1:]:
                items.append(_st.Item(
                    path=extra.path, category=_st.DUPLICATE, suggestion=_st.ASK_OWNER,
                    reason=(f"Probably an identical copy of {kept.path}: same size, and the same "
                            "first and last megabyte. Not confirmed, to save reading "
                            f"{cost / 1e9:.0f} GB."),
                    size=extra.size, owner=extra.owner, changed_at=_iso(extra.mtime),
                    disk=extra.disk, evidence="same size and same first and last megabyte"))
            continue
        if budget is not None:
            budget -= cost
        spent += cost
        by_full: dict[str, list[_Candidate]] = defaultdict(list)
        for c in group:
            fp = _fingerprint(c.path, c.size, quick=False)
            if fp:
                by_full[fp].append(c)
        for fp, copies in by_full.items():
            unique = _unique(copies)
            if len(unique) < 2:
                continue
            kept = unique[0]
            for extra in unique[1:]:
                in_immutable = extra.root_kind == ROOT_IMMUTABLE
                suggestion = _st.ASK_OWNER if extra.root_kind in HANDS_OFF else _st.DELETE
                reason = f"An identical copy is kept at {kept.path}."
                if in_immutable:
                    reason += " This copy is in immutable/, which is never deleted without the PI."
                elif extra.root_kind == ROOT_MOTHBALLED:
                    reason += " This copy is in mothballed/, which only people change."
                if retention_blocked and suggestion == _st.DELETE:
                    suggestion = _st.KEEP
                    reason += " The project keeps everything until its keep-until date."
                items.append(_st.Item(
                    path=extra.path, category=_st.DUPLICATE, suggestion=suggestion,
                    reason=reason, size=extra.size, owner=extra.owner,
                    changed_at=_iso(extra.mtime), disk=extra.disk,
                    evidence=f"same size and SHA-256 fingerprint ({fp[:16]}…) as {kept.path}"))
    return items, spent, skipped


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


@dataclass
class ScanOptions:
    """Choices for one scan."""

    checksums: bool = True
    progress: Callable[[int, int], None] | None = None
    progress_every: int = 50_000
    now: _dt.datetime | None = None
    #: False: data folders only (the lab-wide scan).
    include_repos: bool = True
    #: Bytes this scan may read in full to confirm duplicates; None = the policy's.
    max_read_bytes: int | None = None
    #: Folders listed at once; None = the policy's ``scan_threads``. Measured on
    #: the lab's drive it changed little (about 10 minutes per million files).
    threads: int | None = None


class _Walker:
    """Walks the roots once, gathering everything each check needs."""

    def __init__(self, cp: _cp.CertProject, roots: list[Root], policy: Policy,
                 options: ScanOptions, env: dict | None):
        self.cp = cp
        self.roots = roots
        self.root_paths = {r.path for r in roots}
        self.policy = policy
        self.options = options
        self.env = env
        self.now = (options.now or _dt.datetime.now().astimezone()).timestamp()
        self.protected = _sens.is_protected(cp.sensitivity)
        self.skip = [Path(os.path.normpath(p)) for p in _pu.resolve_reads_from(cp, env).folders]
        self.logins, self.unknown_members = member_logins(cp)
        self.experiments = experiment_names(cp)
        # The lab's layout (one folder per experiment) applies to the project's
        # own append-only folder, not to other data folders a record names.
        self.layout_root = Path(os.path.normpath(_lab_vm.project_append_only_dir(cp.name, env)))
        self.jobs = job_outputs(cp.name, roots, env)
        self.items: list[_st.Item] = []
        self.files = 0
        self.bytes = 0
        self.unreadable: list[str] = []
        #: {folder: entries in it the account may not look at}
        self.hidden_entries: dict[str, int] = {}
        self.candidates: list[_Candidate] = []
        self.unattributed: dict[tuple[str, str, str], _Group] = {}
        self.access: dict[tuple[str, str], _Group] = {}
        self.unknown_types: dict[str, _Group] = {}
        self.folder_newest: dict[str, float] = {}
        self.pending_folders: list[tuple[Root, Path, str]] = []
        self._next_progress = options.progress_every
        #: {top-level folder: {owner: [bytes, files, newest]}}, for the lab scan's
        #: report on folders no project claims.
        self.owners_by_folder: dict[str, dict[str, list[float]]] = {}
        self.environments: list[str] = []
        self.temporary_folders: dict[tuple[Root, str], list[tuple[Path, _Group]]] = {}

    # -- helpers -----------------------------------------------------------

    def _tick(self) -> None:
        if self.options.progress and self.files >= self._next_progress:
            self._next_progress = self.files + self.options.progress_every
            self.options.progress(self.files, self.bytes)

    def _skipped(self, path: Path) -> bool:
        return any(path == s or _within(path, s) for s in self.skip)

    def _old_enough(self, mtime: float) -> bool:
        return (self.now - mtime) >= self.policy.temporary_min_age_days * 86400

    def _date_key(self, root: Root, path: Path) -> str:
        """The data-dates entry a file counts toward: its top-level folder in the root."""
        try:
            first = path.relative_to(root.path).parts[0]
        except (ValueError, IndexError):
            return str(root.path)
        child = root.path / first
        return str(child) if child != path else str(root.path)

    # -- the walk ----------------------------------------------------------

    def walk(self) -> None:
        for root in self.roots:
            tracked = git_tracked(root.path) if root.kind == ROOT_REPO else None
            self._walk_root(root, tracked or set())

    def _walk_root(self, root: Root, tracked: set[str]) -> None:
        """Walk one root. Listing folders and reading file details runs in a
        few threads; everything that decides what a file is runs here, in one
        thread, so the checks need no locks."""
        threads = max(1, int(self.options.threads or self.policy.scan_threads))
        with ThreadPoolExecutor(max_workers=threads) as pool:
            pending = {pool.submit(_list_folder, root.path)}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    folder, listing, refused = future.result()
                    if listing is None:
                        self.unreadable.append(str(folder))
                        continue
                    if refused:
                        self.hidden_entries[str(folder)] = refused
                    for sub in self._folder(root, folder, listing, tracked):
                        pending.add(pool.submit(_list_folder, sub))

    def _folder(self, root: Root, folder: Path, listing: list[tuple[str, str, os.stat_result]],
                tracked: set[str]) -> list[Path]:
        """Look at one folder's entries; return the folders to walk next."""
        jobs_here = [j for j in self.jobs if folder == j.folder or _within(folder, j.folder)]
        nested: list[Path] = []
        for name, full, st in listing:
            path = Path(full)
            if stat.S_ISLNK(st.st_mode):
                continue
            if stat.S_ISDIR(st.st_mode):
                if name == ".git" and root.kind == ROOT_REPO:
                    continue
                if path in self.root_paths or self._skipped(path):
                    continue
                if _is_environment(path, name):
                    self.environments.append(str(path))
                    continue
                if name in TEMPORARY_FOLDERS:
                    self._temporary_folder(root, path, name)
                    continue
                if folder == root.path:
                    self._check_experiment_folder(root, path, st)
                nested.append(path)
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            self._file(root, path, name, st, tracked, jobs_here)
        return nested

    def _temporary_folder(self, root: Root, path: Path, name: str) -> None:
        group = _Group()
        for dirpath, _dirs, files in os.walk(path, onerror=lambda e: None):
            for f in files:
                full = os.path.join(dirpath, f)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode):
                    group.add(full, st.st_size, st.st_mtime)
        self.files += group.n_files
        self.bytes += group.size
        if group.n_files == 0 or not self._old_enough(group.newest):
            return
        self.temporary_folders.setdefault((root, name), []).append((path, group))

    def temporary_folder_items(self) -> list[_st.Item]:
        """One row per temporary folder, or one per root and name when there are several."""
        items: list[_st.Item] = []
        for (root, name), found in self.temporary_folders.items():
            suggestion = _st.ASK_OWNER if root.kind in HANDS_OFF else _st.DELETE
            what = TEMPORARY_FOLDERS[name]
            if len(found) == 1:
                path, group = found[0]
                items.append(_st.Item(
                    path=str(path), category=_st.TEMPORARY, suggestion=suggestion,
                    kind="folder", reason=f"A folder of {what}.", size=group.size,
                    n_files=group.n_files, changed_at=_iso(group.newest), disk=root.disk,
                    owner=self._owner_of(path),
                    evidence=f"folder name {name}; newest file changed {_iso(group.newest)[:10]}"))
                continue
            size = sum(g.size for _p, g in found)
            n_files = sum(g.n_files for _p, g in found)
            newest = max(g.newest for _p, g in found)
            items.append(_st.Item(
                path=str(root.path / "**" / name), category=_st.TEMPORARY,
                suggestion=suggestion, kind="files",
                reason=f"Every folder named {name} in here ({len(found)} folders): {what}.",
                size=size, n_files=n_files, changed_at=_iso(newest), disk=root.disk,
                owner=self._owner_of(found[0][0]),
                evidence=f"for example {found[0][0]}"))
        return items

    def _owner_of(self, path: Path) -> str:
        try:
            return owner_name(path.lstat().st_uid)
        except OSError:
            return ""

    def _check_experiment_folder(self, root: Root, path: Path, st: os.stat_result) -> None:
        """A top-level folder in append_only/<project> should match an experiment."""
        if root.path != self.layout_root or self.experiments is None:
            return
        if path.name in self.experiments:
            return
        self.pending_folders.append((root, path, owner_name(st.st_uid)))

    def _file(self, root: Root, path: Path, name: str, st: os.stat_result,
              tracked: set[str], jobs_here: list[_JobOutput]) -> None:
        size, mtime = st.st_size, st.st_mtime
        owner = owner_name(st.st_uid)
        spath = str(path)
        self.files += 1
        self.bytes += size
        self._tick()
        if root.kind != ROOT_REPO:
            key = self._date_key(root, path)
            self.folder_newest[key] = max(self.folder_newest.get(key, 0.0), mtime)
            tally = self.owners_by_folder.setdefault(key, {}).setdefault(owner, [0, 0, 0.0])
            tally[0] += size
            tally[1] += 1
            tally[2] = max(tally[2], mtime)
            self.folder_newest[str(root.path)] = max(
                self.folder_newest.get(str(root.path), 0.0), mtime)
        rel = os.path.relpath(spath, root.path) if root.kind == ROOT_REPO else ""
        is_tracked = rel in tracked
        ext = _ext(name)

        # Temporary files.
        what = TEMPORARY_NAMES.get(name) or next(
            (w for pattern, w in TEMPORARY_PATTERNS if pattern.match(name)), "")
        if what and not is_tracked and self._old_enough(mtime):
            self.items.append(_st.Item(
                path=spath, category=_st.TEMPORARY, reason=f"{what[0].upper()}{what[1:]}.",
                suggestion=_st.ASK_OWNER if root.kind in HANDS_OFF else _st.DELETE,
                size=size, owner=owner, changed_at=_iso(mtime), disk=root.disk,
                evidence=f"file name {name}; last changed {_iso(mtime)[:10]}"))

        # Out of place: large files inside a repository.
        if root.kind == ROOT_REPO and size >= self.policy.large_file_in_repo_mb * MB:
            where = _lab_vm.project_append_only_dir(self.cp.name, self.env)
            reason = (f"A large file inside a repository; data belongs in the project's data "
                      f"folders, such as {where}.")
            if is_tracked:
                reason += " It is tracked by git, so every copy of the repository carries it."
            self.items.append(_st.Item(
                path=spath, category=_st.OUT_OF_PLACE, suggestion=_st.MOVE, reason=reason,
                size=size, owner=owner, changed_at=_iso(mtime), disk=root.disk,
                evidence="tracked by git" if is_tracked else "not tracked by git"))

        # Out of place: files loose at the top of append_only/<project>.
        if (root.path == self.layout_root and path.parent == root.path
                and self.experiments is not None):
            self.items.append(_st.Item(
                path=spath, category=_st.OUT_OF_PLACE, suggestion=_st.ASK_OWNER,
                reason=("A file at the top of the project's append-only folder, outside any "
                        "experiment's folder. The lab's layout puts each experiment's output in "
                        "a folder named after it."),
                size=size, owner=owner, changed_at=_iso(mtime), disk=root.disk))

        # Compressible text data.
        if (ext in COMPRESS_METHODS and size >= self.policy.compress_min_mb * MB
                and root.kind not in HANDS_OFF):
            self.items.append(_st.Item(
                path=spath, category=_st.COMPRESSIBLE, suggestion=_st.COMPRESS,
                reason=f"Uncompressed {ext[1:].upper()} data. Lossless: {COMPRESS_METHODS[ext]}.",
                size=size, owner=owner, changed_at=_iso(mtime), disk=root.disk,
                evidence=f"file ending {ext}"))

        # A large file of a type no rule covers.
        if (root.kind != ROOT_REPO and size >= self.policy.compress_min_mb * MB
                and ext not in KNOWN_TYPES):
            self.unknown_types.setdefault(ext or "(no ending)", _Group()).add(spath, size, mtime)

        # Candidates for duplicates.
        if self.options.checksums and size >= self.policy.duplicate_min_mb * MB:
            self.candidates.append(_Candidate(
                path=spath, size=size, mtime=mtime, owner=owner, root_kind=root.kind,
                disk=root.disk, dev=st.st_dev, ino=st.st_ino))

        # Owned by someone who is not a member.
        if self.logins and owner not in self.logins:
            try:
                top = path.relative_to(root.path).parts[0]
                group_path = str(root.path / top) if (root.path / top) != path else str(root.path)
            except (ValueError, IndexError):
                group_path = str(root.path)
            self.unattributed.setdefault((owner, group_path, root.disk), _Group()).add(
                spath, size, mtime)

        # Questions about who can read or change it: the security guard's.
        if st.st_mode & stat.S_IWOTH:
            self.access.setdefault((str(root.path), "anyone on the server can change"),
                                   _Group()).add(spath, size, mtime)
        elif self.protected and st.st_mode & stat.S_IROTH:
            self.access.setdefault((str(root.path), "anyone on the server can read"),
                                   _Group()).add(spath, size, mtime)

        # Written by a recorded job.
        for job in jobs_here:
            if job.start - _JOB_WINDOW_SLACK <= mtime <= job.end + _JOB_WINDOW_SLACK:
                job.written.add(spath, size, mtime)
            else:
                job.other.add(spath, size, mtime)


def _list_folder(folder: Path) -> tuple[Path, list[tuple[str, str, os.stat_result]] | None, int]:
    """A folder's entries with their details, and how many could not be looked at.

    The listing is None when the folder itself cannot be opened. Runs in a
    worker thread. Links are not followed. An entry that vanished while being
    read is not counted; one the account may not look at is.
    """
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return folder, None, 0
    out: list[tuple[str, str, os.stat_result]] = []
    refused = 0
    for entry in entries:
        try:
            out.append((entry.name, entry.path, entry.stat(follow_symlinks=False)))
        except FileNotFoundError:
            continue
        except OSError:
            refused += 1
    return folder, out, refused


def _is_environment(path: Path, name: str) -> bool:
    if name in ENVIRONMENT_FOLDERS:
        return True
    if name == "library" and path.parent.name == "renv":
        return True
    # On a shared drive a folder may hold files the scanning account cannot
    # look at; that must not stop a scan of the whole lab.
    try:
        return (path / "pyvenv.cfg").is_file() or (path / "conda-meta").is_dir()
    except OSError:
        return False


def _disk_key(path: Path) -> str:
    try:
        return f"dev{os.stat(path).st_dev}"
    except OSError:
        return ""


def scan_project(cp: _cp.CertProject, *, env: dict | None = None,
                 policy: Policy | None = None,
                 options: ScanOptions | None = None) -> _st.ScanSummary:
    """Scan one project and return what it found. Changes no file.

    Parameters
    ----------
    cp : CertProject
        The project.
    env : dict, optional
        Environment for the data root and the lab repository.
    policy : Policy, optional
        The lab's thresholds; read from the policy file when not given.
    options : ScanOptions, optional
        Whether to fingerprint for duplicates, and a progress callback.

    Returns
    -------
    ScanSummary
        Rows, gaps in the lab's procedures, and the disks the files are on.
    """
    policy = policy or load_policy(env)
    options = options or ScanOptions()
    started = _st.now_iso()
    roots: list[Root] = []
    summary = _st.ScanSummary(project=cp.name, started_at=started,
                              scanned_by=_pu.local_handle() or os.environ.get("USER", ""))
    for root in project_roots(cp, env, include_repos=options.include_repos):
        key = _disk_key(root.path)
        roots.append(Root(path=root.path, kind=root.kind, disk=key))
        if key and key not in summary.disks:
            try:
                usage = shutil.disk_usage(root.path)
                summary.disks[key] = _st.Disk(label=str(root.path), total=usage.total,
                                              free=usage.free)
            except OSError:
                pass
    if not roots:
        summary.notes.append("No repository or data folder of this project is on this computer.")
        summary.finished_at = _st.now_iso()
        return summary

    walker = _Walker(cp, roots, policy, options, env)
    walker.walk()
    items = walker.items + walker.temporary_folder_items()

    for root, path, owner in walker.pending_folders:
        items.append(_st.Item(
            path=str(path), category=_st.OUT_OF_PLACE, suggestion=_st.ASK_OWNER, kind="folder",
            reason=(f"No experiment folder exp/{path.name} in the code repository. The lab's "
                    "layout gives each experiment's output a folder of the same name."),
            size=_folder_size(path), owner=owner, disk=root.disk,
            n_files=0))

    for job in walker.jobs:
        item = _intermediate_item(job, roots, policy)
        if item:
            items.append(item)

    items += _listed_items(cp, roots)
    budget = (options.max_read_bytes if options.max_read_bytes is not None
              else policy.duplicate_max_read_gb * 1024**3)
    found, summary.bytes_fingerprinted, not_compared = find_duplicates(
        walker.candidates, retention_blocked=_pu.retention_blocks_deletion(cp),
        max_read_bytes=budget)
    items += found
    if not_compared:
        summary.notes.append(f"{not_compared:,} files of matching sizes were not compared for "
                             "duplicates, to stay within the lab's reading limit "
                             "(duplicate_max_read_gb).")
    items += _unattributed_items(walker, roots)
    for (root_path, what), group in sorted(walker.access.items()):
        disk = next((r.disk for r in roots if str(r.path) == root_path), "")
        items.append(_st.Item(
            path=root_path, category=_st.ACCESS, suggestion=_st.REFER_SECURITY, kind="files",
            reason=f"{_files(group.n_files)} here that {what}.", size=group.size,
            n_files=group.n_files, changed_at=_iso(group.newest), disk=disk,
            evidence=f"for example {group.example}"))
    items += _unreadable_items(walker, roots)

    if _pu.retention_blocks_deletion(cp):
        for item in items:
            if item.suggestion == _st.DELETE:
                item.suggestion = _st.KEEP
                item.reason += f" The project keeps everything until {cp.retain_until}."

    summary.items = _dedupe(items)
    summary.sop_gaps = _sop_gaps(cp, walker)
    summary.owners_by_folder = walker.owners_by_folder
    summary.files = walker.files
    summary.bytes = walker.bytes
    summary.unreadable = len(walker.unreadable) + sum(walker.hidden_entries.values())
    places = len(walker.unreadable) + len(walker.hidden_entries)
    if summary.unreadable:
        summary.notes.append(
            f"{_files(summary.unreadable).replace('file', 'item')} could not be read, so no "
            "total includes them" + (f"; the first {_MAX_UNREADABLE_ROWS} places are listed"
                                     if places > _MAX_UNREADABLE_ROWS else "") + ".")
    if not options.checksums:
        summary.notes.append("Duplicates were not looked for (--no-checksums).")
    if walker.environments:
        many = len(walker.environments) > 1
        summary.notes.append(
            (f"{len(walker.environments)} software environment folders, such as "
             if many else "A software environment folder, ")
            + f"{walker.environments[0]}, {'were' if many else 'was'} not looked into; "
            "they hold installed software, not data.")
    if walker.unknown_members:
        summary.notes.append(
            "No server login is known for " + ", ".join(f"@{h}" for h in walker.unknown_members)
            + "; files they own may be listed as unattributed.")
    summary.finished_at = _st.now_iso()
    write_data_dates({k: v for k, v in walker.folder_newest.items()}, summary.finished_at)
    return summary


def _unreadable_items(walker: _Walker, roots: list[Root]) -> list[_st.Item]:
    """A row for each folder the scan could not open, or could not fully look into.

    Nothing in them is in any total, so the scan's figures are low by an unknown
    amount until the owner lets the lab group read them.
    """
    places = [(f, 0) for f in walker.unreadable] + sorted(walker.hidden_entries.items())
    items: list[_st.Item] = []
    for folder, hidden in places[:_MAX_UNREADABLE_ROWS]:
        disk = next((r.disk for r in roots if _within(Path(folder), r.path)), "")
        owner = walker._owner_of(Path(folder))
        who = f"its owner, {owner}," if owner else "its owner"
        what = ("The scan could not open this folder" if not hidden else
                f"{_files(hidden).replace('file', 'item')} in this folder could not be looked at")
        items.append(_st.Item(
            path=folder, category=_st.UNREADABLE, suggestion=_st.ASK_OWNER,
            kind="folder" if not hidden else "files", n_files=hidden, size=0, owner=owner,
            disk=disk,
            reason=(f"{what}, so no total includes it. Ask {who} to let the lab group read "
                    f"it: chmod -R g+rX {folder}"),
            evidence="permission denied to the scanning account"))
    return items


def _files(n: int) -> str:
    return "1 file" if n == 1 else f"{n:,} files"


def _folder_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                st = os.lstat(os.path.join(dirpath, f))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


def _listed_items(cp: _cp.CertProject, roots: list[Root]) -> list[_st.Item]:
    items: list[_st.Item] = []
    for repo_name, path in ready_to_delete_entries(cp):
        root = next((r for r in roots if path == r.path or _within(path, r.path)), None)
        if root is None or path == root.path:
            continue
        try:
            st = path.lstat()
        except OSError:
            continue
        is_file = stat.S_ISREG(st.st_mode)
        size = st.st_size if is_file else _folder_size(path)
        in_immutable = root.kind in HANDS_OFF
        items.append(_st.Item(
            path=str(path), category=_st.LISTED,
            suggestion=_st.ASK_OWNER if in_immutable else _st.DELETE,
            kind="file" if is_file else "folder",
            reason=("A member listed this in src/ready_to_delete.md." if not in_immutable else
                    "Listed in src/ready_to_delete.md, but it is in immutable/, which is never "
                    "deleted without the PI."),
            size=size, owner=owner_name(st.st_uid), changed_at=_iso(st.st_mtime),
            disk=root.disk, evidence=f"listed in {repo_name}/src/ready_to_delete.md"))
    return items


def _unattributed_items(walker: _Walker, roots: list[Root]) -> list[_st.Item]:
    items: list[_st.Item] = []
    for (owner, group_path, disk), group in sorted(walker.unattributed.items()):
        single = group.n_files == 1 and group.example == group_path
        text = "" if walker.protected else peek(group.example)
        reason = (f"Owned by {owner}, who is not a member of this project we can match."
                  if not walker.unknown_members else
                  f"Owned by {owner}, who is not a member of this project we can match "
                  "(some members have no known server login).")
        items.append(_st.Item(
            path=group_path, category=_st.UNATTRIBUTED, suggestion=_st.ASK_OWNER,
            kind="file" if single else "files", reason=reason, size=group.size,
            n_files=group.n_files, owner=owner, changed_at=_iso(group.newest), disk=disk,
            evidence=f"{group.n_files} files owned by {owner}; largest {group.example}",
            peek=text))
    return items


def _dedupe(items: list[_st.Item]) -> list[_st.Item]:
    seen: dict[tuple[str, str], _st.Item] = {}
    for item in items:
        seen.setdefault((item.path, item.category), item)
    return list(seen.values())


def _sop_gaps(cp: _cp.CertProject, walker: _Walker) -> list[_st.SopGap]:
    gaps: list[_st.SopGap] = []
    for ext, group in sorted(walker.unknown_types.items(), key=lambda kv: -kv[1].size):
        gaps.append(_st.SopGap(
            kind="file type", detail=f"No rule says what to do with large {ext} files.",
            example=group.example, count=group.n_files, size=group.size))
    if walker.experiments is None and any(r.kind == ROOT_APPEND_ONLY for r in walker.roots):
        gaps.append(_st.SopGap(
            kind="layout",
            detail=("The code repository has no exp/ folder on this computer, so data folders "
                    "cannot be matched to experiments.")))
    if walker.options.include_repos and not any(r.kind == ROOT_REPO for r in walker.roots):
        gaps.append(_st.SopGap(
            kind="layout",
            detail=("No repository of this project is on this computer, so files cannot be "
                    "checked against the code that made them.")))
    if walker.unknown_members and not walker.logins:
        gaps.append(_st.SopGap(
            kind="members",
            detail=("No member of this project has a known server login, so files cannot be "
                    "matched to people. Set os_user in each member's file."),
            count=len(walker.unknown_members)))
    return gaps


# ---------------------------------------------------------------------------
# When each data folder last changed (read by step 0)
# ---------------------------------------------------------------------------


def write_data_dates(newest: dict[str, float], scanned_at: str,
                     path: Path | None = None) -> Path:
    """Merge this scan's dates into ``data_dates.json``, written atomically.

    Folders this scan did not see keep their earlier entries, since another
    project's scan wrote them.
    """
    path = path or _pu.data_dates_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    folders = _pu.read_data_dates(path)
    for folder, ts in newest.items():
        if ts:
            folders[folder] = {"newest_change": _iso(ts), "scanned_at": scanned_at}
    data = {"schema": _pu.DATA_DATES_SCHEMA, "folders": dict(sorted(folders.items()))}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return path


__all__ = [
    "COMPRESS_METHODS", "KNOWN_TYPES", "TEMPORARY_FOLDERS", "TEMPORARY_NAMES",
    "ROOT_REPO", "ROOT_IMMUTABLE", "ROOT_APPEND_ONLY", "ROOT_DATA", "ROOT_MOTHBALLED", "HANDS_OFF",
    "Root", "ScanOptions", "project_roots", "member_logins", "git_tracked",
    "experiment_names", "ENVIRONMENT_FOLDERS", "script_state", "job_outputs", "ready_to_delete_entries",
    "peek", "duplicate_items", "scan_project", "write_data_dates", "owner_name",
]
