"""
Purpose: Put a line of text, a photo, a handwritten page, a sound note, a
         video or a result file into today's lab-notebook entry (issue #293).
         Small things stay in the vault; large things go to
         ``append_only/<project>/notebook/<date>/`` on the project's data host
         and the entry keeps a link, a thumbnail or poster frame, and any
         machine-made text marked as such.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   A file or text, the project (from the folder or ``--project``), the
         project's record (for its host and tier) and the hosts file.
Output:  A block appended to the entry; files under ``attachments/`` in the
         vault and under ``append_only/`` on the host. Nothing on the host is
         ever overwritten: a second file of the same name gets ``_2``.

Rules kept here, from the issue's pushback:
- a transcription or an image description is a reading, never the record:
  it is marked, and the original stays;
- a protected project's images never get a thumbnail in a vault that syncs;
- the PHI patterns run on every transcription before it enters the vault;
- the files on the host are append-only: a corrected transcript is a new
  line in the entry, not a change to the file.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import lab_notebook as _nb
from . import sensitivity as _sens

#: Result files at or below this size stay in the vault, beside the entry.
SMALL_BYTES = 2 * 1024 * 1024
THUMB_MAX_PX = 512
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".heic", ".tif", ".tiff", ".bmp", ".webp"}
SOUND_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".aiff", ".opus"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
KINDS = ("text", "image", "handwritten", "sound", "video", "file")
APPEND_ONLY = "append_only"
NOTEBOOK_FOLDER = "notebook"
ELEVENLABS_API = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "scribe_v1"
KEYCHAIN_SERVICE = "elevenlabs-api-key"

Transcriber = Callable[[Path], str]


class CaptureError(RuntimeError):
    """The capture cannot be carried out; the message says why."""


def infer_kind(path: Path, *, handwritten: bool = False) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "handwritten" if handwritten else "image"
    if suffix in SOUND_SUFFIXES:
        return "sound"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return "file"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Where a large file goes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    """The host and folder a large file is sent to."""

    host: Any            # core.hosts.Host
    folder: str          # absolute folder on the host

    @property
    def is_local(self) -> bool:
        return getattr(self.host, "kind", "local") == "local"

    def link(self, name: str) -> str:
        return f"{self.host.name}:{self.folder.rstrip('/')}/{name}"


def project_context(project: str | None, start: Path | None = None) -> tuple[str, str, str]:
    """``(project, sensitivity, host_name)`` for the capture. The project is
    the one named, else the one this folder belongs to. The tier comes from
    the project's record. The host is the one murmurent already knows for
    the project's data: the lab's ``data_host`` (``murmurent group-setup``),
    else the host of the project's main repository. With no record both are
    empty and the caller is told."""
    from . import cert_projects as _cp

    name = (project or "").strip()
    if not name:
        try:
            name = _cp.project_name_for_cwd(start) or ""
        except Exception:  # noqa: BLE001
            name = ""
    if not name:
        raise CaptureError(
            "no project: run this inside a project's folder or name one with --project")
    sensitivity, host = "standard", ""
    try:
        rec = _cp.get(name)
    except Exception:  # noqa: BLE001
        rec = None
    if rec is not None:
        sensitivity = _sens.normalize(rec.sensitivity) or "standard"
        host = _lab_data_host(getattr(rec, "lab", "")) or rec.host or "local"
    return name, sensitivity, host


def _lab_data_host(lab: str) -> str:
    """The lab's ``data_host`` from its records, or empty."""
    if not lab:
        return ""
    try:
        from . import registrar as _reg
        return (_reg.read_group_profile(lab).get("data_host") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def remote_data_root(host) -> str:
    """``$MURMURENT_DATA_ROOT`` in the host's login shell (the legacy
    ``MURMURENT_LAB_VM_ROOT`` is accepted), or empty."""
    res = _remote(host).run(
        'printf "%s" "${MURMURENT_DATA_ROOT:-${MURMURENT_LAB_VM_ROOT:-}}"', check=False, timeout=30)
    return res.stdout.strip() if res.ok else ""


def destination(project: str, host_name: str, date: str) -> Destination:
    """Resolve the folder ``append_only/<project>/notebook/<date>/`` on
    ``host_name`` (a name from ``murmurent host list``; ``local`` is this
    machine's data root)."""
    from . import hosts as _hosts
    from . import lab_vm as _lab_vm

    if not host_name:
        raise CaptureError(
            f"project {project!r} has no record naming a data host; add one with "
            "`murmurent host add <name> --ssh-host <alias>` and say --host <name>")
    try:
        host = _hosts.resolve(host_name)
    except _hosts.HostError as exc:
        raise CaptureError(
            f"no host known as {host_name!r} ({exc}); register it with "
            "`murmurent host add` or choose another with --host") from exc
    if host.kind == "local":
        folder = _lab_vm.project_append_only_dir(project) / NOTEBOOK_FOLDER / date
        return Destination(host=host, folder=str(folder))
    root = remote_data_root(host).rstrip("/")
    if not root:
        raise CaptureError(
            f"host {host.name!r} does not set MURMURENT_DATA_ROOT in its login shell, so "
            "murmurent cannot tell where append_only/ is there")
    return Destination(host=host, folder=f"{root}/{APPEND_ONLY}/{project}/{NOTEBOOK_FOLDER}/{date}")


def _remote(host):
    from .remote import Remote
    return Remote(host)


def _free_name(dest: Destination, name: str) -> str:
    """``name`` if nothing on the host has it, else ``stem_2.ext``: the
    notebook's files are append-only."""
    stem, suffix = Path(name).stem, Path(name).suffix
    existing = _existing_names(dest)
    cand, n = name, 2
    while cand in existing:
        cand = f"{stem}_{n}{suffix}"
        n += 1
    return cand


def _existing_names(dest: Destination) -> set[str]:
    if dest.is_local:
        p = Path(dest.folder)
        return {f.name for f in p.iterdir()} if p.is_dir() else set()
    res = _remote(dest.host).run(f"ls -1A {_q(dest.folder)} 2>/dev/null || true", check=False)
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def send(dest: Destination, src: Path, name: str) -> str:
    """Copy ``src`` to the host as ``name``; returns the link. Creates the
    folder; never overwrites (``name`` must come from :func:`_free_name`)."""
    if dest.is_local:
        folder = Path(dest.folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.exists():
            raise CaptureError(f"{target} already exists; append_only is never overwritten")
        shutil.copy2(src, target)
        return dest.link(name)
    remote = _remote(dest.host)
    remote.run(f"mkdir -p {_q(dest.folder)} && test ! -e {_q(dest.folder + '/' + name)}")
    remote.copy_to(src, f"{dest.folder}/{name}")
    return dest.link(name)


def fetch(link: str, into: Path) -> Path:
    """Bring a copy of the file behind ``<host>:<path>`` into ``into/``.
    A bare path is read as a local file."""
    from . import hosts as _hosts

    host_name, _, path = link.partition(":")
    if not path or host_name.startswith("/") or host_name.startswith("~"):
        host_name, path = "local", link
    try:
        host = _hosts.resolve(host_name)
    except _hosts.HostError as exc:
        raise CaptureError(f"no host known as {host_name!r}: {exc}") from exc
    into.mkdir(parents=True, exist_ok=True)
    local = into / Path(path).name
    if host.kind == "local":
        src = Path(path).expanduser()
        if not src.is_file():
            raise CaptureError(f"no file at {src}")
        shutil.copy2(src, local)
        return local
    _remote(host).copy_from(path, local)
    return local


# ---------------------------------------------------------------------------
# Thumbnails, poster frames, transcription
# ---------------------------------------------------------------------------


def make_thumbnail(src: Path, dst: Path, max_px: int = THUMB_MAX_PX) -> bool:
    """A small copy of an image, by Pillow or macOS ``sips``. False when
    neither is available."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(src) as im:
            im.thumbnail((max_px, max_px))
            im.convert("RGB").save(dst, "JPEG", quality=80)
        return True
    except Exception:  # noqa: BLE001 - Pillow missing or format unknown
        pass
    sips = shutil.which("sips")
    if sips:
        res = subprocess.run([sips, "-s", "format", "jpeg", "-Z", str(max_px), str(src),
                              "--out", str(dst)], capture_output=True, text=True)
        return res.returncode == 0 and dst.is_file()
    return False


def make_poster(src: Path, dst: Path, max_px: int = THUMB_MAX_PX) -> bool:
    """One frame from a video, by ffmpeg. False without it."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-ss", "1", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale='min({max_px},iw)':-2", str(dst)],
        capture_output=True, text=True)
    return res.returncode == 0 and dst.is_file()


def elevenlabs_key() -> str:
    """The ElevenLabs key from ``$ELEVENLABS_API_KEY`` or the macOS Keychain
    item ``elevenlabs-api-key``; empty when neither exists."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if key:
        return key
    security = shutil.which("security") or "/usr/bin/security"
    if not Path(security).exists():
        return ""
    try:
        res = subprocess.run([security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def elevenlabs_transcribe(path: Path, *, key: str = "", model: str = ELEVENLABS_MODEL) -> str:
    """Speech to text through ElevenLabs. Returns the text (empty when the
    recording has no speech). Raises :class:`CaptureError` on an HTTP error."""
    key = key or elevenlabs_key()
    if not key:
        raise CaptureError("no ElevenLabs key")
    boundary = f"----murmurent{uuid.uuid4().hex}"
    data = path.read_bytes()
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\n{model}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode(),
        data, b"\r\n", f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{ELEVENLABS_API}/speech-to-text", data=body,
        headers={"xi-api-key": key, "content-type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((body.get("detail") or {}).get("message") or body.get("detail") or "")
        except Exception:  # noqa: BLE001 - the code alone is still a usable message
            pass
        if "speech_to_text" in detail:
            detail = "the key lacks the speech-to-text permission; grant it at elevenlabs.io under API keys"
        raise CaptureError(f"ElevenLabs answered {exc.code}" + (f": {detail}" if detail else "")) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CaptureError(f"ElevenLabs could not be reached: {exc}") from exc
    return str(payload.get("text") or "").strip()


def phi_labels(text: str, *, protected: bool) -> list[str]:
    """PHI pattern labels found in ``text``: the explicit patterns always, the
    date-near-a-name heuristic only for a protected project."""
    from ..hooks import phi_check as _phi

    if protected:
        hits = _phi._pattern_hits(text)
    else:
        hits = [(label, m.group(0)) for label, pat in _phi.PHI_PATTERNS for m in pat.finditer(text)]
    return sorted({h[0] for h in hits})


# ---------------------------------------------------------------------------
# The capture itself
# ---------------------------------------------------------------------------


@dataclass
class Capture:
    """What one ``notebook add`` did, for printing."""

    kind: str
    entry: Path
    project: str
    sensitivity: str
    link: str = ""
    vault_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    block: list[str] = field(default_factory=list)
    dry_run: bool = False


def add_text(paths: _nb.NotebookPaths, text: str, *, project: str, sensitivity: str,
             when: _dt.datetime, dry_run: bool = False) -> Capture:
    date = when.strftime("%Y-%m-%d")
    entry = _nb.entry_path(paths, date)
    block = [_nb.time_heading(when), text.strip()]
    cap = Capture(kind="text", entry=entry, project=project, sensitivity=sensitivity,
                  block=block, dry_run=dry_run)
    if not dry_run:
        _nb.ensure_entry(entry, date=date, project=project, sensitivity=sensitivity)
        _nb.append_block(entry, block)
    return cap


def add_file(
    paths: _nb.NotebookPaths,
    src: Path,
    *,
    kind: str,
    project: str,
    sensitivity: str,
    host_name: str,
    when: _dt.datetime,
    note: str = "",
    dry_run: bool = False,
    transcriber: Transcriber | None = None,
    thumbnailer: Callable[[Path, Path], bool] | None = None,
    posterer: Callable[[Path, Path], bool] | None = None,
) -> Capture:
    """Add a file of ``kind`` to the day's entry (see the module docstring)."""
    if kind not in KINDS or kind == "text":
        raise CaptureError(f"kind must be one of {KINDS[1:]}")
    if not src.is_file():
        raise CaptureError(f"no file at {src}")
    date = when.strftime("%Y-%m-%d")
    entry = _nb.entry_path(paths, date)
    protected = _sens.is_protected(sensitivity)
    cap = Capture(kind=kind, entry=entry, project=project, sensitivity=sensitivity, dry_run=dry_run)
    size = src.stat().st_size
    digest = sha256_file(src)
    label = {"image": "image", "handwritten": "handwritten page", "sound": "sound note",
             "video": "video", "file": "file"}[kind]
    block = [_nb.time_heading(when, f"{label}: {src.name}")]

    stays_in_vault = kind == "file" and size <= SMALL_BYTES
    attach_dir = paths.attachments / date

    if stays_in_vault:
        target = _versioned(attach_dir / src.name)
        cap.vault_files.append(target)
        if not dry_run:
            attach_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        block.append(f"[[{paths.rel(target)}]] ({_human(size)}, sha256 {digest[:12]})")
    else:
        dest = destination(project, host_name, date)
        name = src.name if dry_run else _free_name(dest, src.name)
        link = dest.link(name)
        if not dry_run:
            link = send(dest, src, name)
        cap.link = link
        # a thumbnail or poster frame, unless the project is protected
        if kind in ("image", "handwritten", "video"):
            if protected:
                block.append("- no thumbnail: the project is protected, so the vault holds only the link")
                cap.notes.append("protected project: no thumbnail or poster frame was made")
            else:
                suffix = "_poster.jpg" if kind == "video" else "_thumb.jpg"
                small = _versioned(attach_dir / f"{src.stem}{suffix}")
                made = True
                if not dry_run:
                    make = (posterer or make_poster) if kind == "video" else (thumbnailer or make_thumbnail)
                    made = make(src, small)
                if made:
                    cap.vault_files.append(small)
                    block.append(f"![[{paths.rel(small)}]]")
                else:
                    block.append("- no thumbnail could be made on this machine (install Pillow or ffmpeg)")
                    cap.notes.append("no thumbnail: neither Pillow nor the system tools could make one")
        block.append(f"- original: `{link}` ({_human(size)}, sha256 {digest[:12]}); "
                     f"a copy to look at: `murmurent notebook open {link}`")

    if note.strip():
        block.append(f"- note: {note.strip()}")

    # machine-made text, always marked as such, never the record
    if kind == "image":
        block.append("> Machine reading (image description by Claude Code, not the record): "
                     "_to be added by Claude Code in this session; check it against the image_")
        cap.notes.append("describe the image in one line under the marked placeholder")
    elif kind == "handwritten":
        block.append("> Transcription (machine-made, not the record; check each value against the page): "
                     "_to be added by Claude Code in this session_")
        cap.notes.append("transcribe the page under the marked placeholder; the image stays the record")
    elif kind in ("sound", "video"):
        block.extend(_transcription_lines(src, protected=protected, dry_run=dry_run,
                                          transcriber=transcriber, cap=cap))

    cap.block = block
    if not dry_run:
        _nb.ensure_entry(entry, date=date, project=project, sensitivity=sensitivity)
        _nb.append_block(entry, block)
    return cap


def _transcription_lines(src: Path, *, protected: bool, dry_run: bool,
                         transcriber: Transcriber | None, cap: Capture) -> list[str]:
    if dry_run:
        return ["> Transcription: (would be attempted)"]
    if transcriber is None:
        if not elevenlabs_key():
            cap.notes.append("transcription skipped: no elevenlabs-api-key in the Keychain and no ELEVENLABS_API_KEY")
            return ["> Transcription skipped: no `elevenlabs-api-key` in the Keychain "
                    "(store one with `security add-generic-password -U -a \"$USER\" -s elevenlabs-api-key -w`)"]
        transcriber = elevenlabs_transcribe
    try:
        text = transcriber(src)
    except CaptureError as exc:
        cap.notes.append(f"transcription failed: {exc}")
        return [f"> Transcription failed: {exc}; the recording is on the server"]
    if not text.strip():
        return ["> Transcription: no speech found"]
    labels = phi_labels(text, protected=protected)
    if labels:
        cap.notes.append(f"transcription withheld: matched {', '.join(labels)} pattern(s)")
        return [f"> Transcription withheld: it matched {', '.join(labels)} pattern(s); "
                "the recording stays on the server, listen to it there"]
    one_line = " ".join(text.split())
    return [f"> Transcription (machine-made by ElevenLabs {ELEVENLABS_MODEL}, not the record; "
            f"check it against the recording): {one_line}"]


def _versioned(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


__all__ = [
    "CaptureError", "Capture", "Destination", "KINDS", "SMALL_BYTES", "infer_kind",
    "project_context", "destination", "send", "fetch", "add_text", "add_file",
    "make_thumbnail", "make_poster", "elevenlabs_key", "elevenlabs_transcribe", "phi_labels",
]
