"""
Purpose: Promote an entry from the personal Oracle (Obsidian vault) to
         the Lab Oracle (``lab_mgmt/oracle/`` in the lab-mgmt repo).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-16
Input: A draft file at ``<vault>/oracle/drafts/<slug>.md`` with
       frontmatter conforming to ``rules/oracle_schema.md``.
Output: A committed file at ``<lab-mgmt>/oracle/<YYYY-MM-DD>_<slug>.md``,
        plus a ``[Probe]``-style result summary the CLI can render.

Boundary: this module does NOT decide whether the lab should accept an
entry — that's a PI review concern handled separately. It only enforces
mechanical invariants (schema present, sensitivity not clinical/restricted,
slug doesn't clobber an existing entry) and copies + commits.

Path resolution:
  - Personal Oracle dir: ``machine.yaml.obsidian_vault_path / oracle_subfolder``,
    falling back to the most-recently-opened Obsidian vault. Overridable
    via ``$WIGAMIG_PERSONAL_ORACLE_DIR`` for tests.
  - Lab Oracle dir: ``core.repo.lab_mgmt_repo_root() / 'oracle'``,
    overridable via ``$WIGAMIG_LAB_MGMT_REPO``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from . import obsidian as _obsidian
from .repo import lab_mgmt_repo_root

REQUIRED_FIELDS: tuple[str, ...] = (
    "title", "date", "project", "sensitivity", "tags", "sources",
)
BLOCKED_SENSITIVITIES: frozenset[str] = frozenset({"clinical", "restricted"})
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")
ENV_PERSONAL = "WIGAMIG_PERSONAL_ORACLE_DIR"


class OracleError(ValueError):
    """Base for publish-flow failures the CLI surfaces verbatim."""


class DraftNotFound(OracleError):
    """The requested slug isn't in the vault drafts dir."""


class SchemaViolation(OracleError):
    """Frontmatter missing required fields or has an invalid value."""


class SensitivityBlocked(OracleError):
    """Refused: clinical/restricted entries must stay personal."""


class TargetExists(OracleError):
    """The lab oracle already has an entry at the target path."""


@dataclass(frozen=True)
class PublishResult:
    """What the CLI shows on success — the file that landed + commit sha."""

    source: Path
    target: Path
    commit_sha: str | None       # None when --no-commit was passed
    pushed: bool


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def personal_oracle_dir() -> Path:
    """Resolve the personal oracle dir on this machine.

    Order: ``$WIGAMIG_PERSONAL_ORACLE_DIR`` → ``machine.yaml`` vault +
    subfolder → most-recently-opened vault + ``oracle/``. Raises
    :class:`OracleError` if none of these resolve.

    Importing :mod:`murmurent.dashboard.machine_settings` is deferred so
    the core module stays loadable in environments that don't have the
    dashboard's optional deps installed.
    """
    pin = os.environ.get(ENV_PERSONAL, "").strip()
    if pin:
        return Path(pin).expanduser()
    try:
        from ..dashboard import machine_settings as _ms  # noqa: PLC0415
        s = _ms.load()
        if s.obsidian_vault_path:
            sub = s.oracle_subfolder or "oracle"
            return Path(s.obsidian_vault_path).expanduser() / sub
    except Exception:
        # machine_settings is best-effort; fall through to vault discovery.
        pass
    v = _obsidian.preferred_vault()
    if v is None:
        raise OracleError(
            "no Obsidian vault registered; set "
            "WIGAMIG_PERSONAL_ORACLE_DIR or save vault path via the dashboard"
        )
    return v.path / "oracle"


def lab_oracle_dir() -> Path:
    return lab_mgmt_repo_root() / "oracle"


def vault_drafts_dir() -> Path:
    return personal_oracle_dir() / "drafts"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def iter_vault_drafts() -> list[Path]:
    """Return every ``.md`` file under ``<vault>/oracle/drafts/``.

    Empty list when the dir doesn't exist (a fresh install).
    """
    d = vault_drafts_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".md")


# ---------------------------------------------------------------------------
# Read-access probe (Full Disk Access diagnosis)
# ---------------------------------------------------------------------------

# The macOS Full Disk Access (TCC) hint. iCloud-backed Obsidian vaults
# under ``~/Library/Mobile Documents/`` are TCC-protected: Obsidian can
# read them, but the terminal + ``claude`` + the MCP server process may
# not. When that happens the oracle MCP degrades silently to an empty
# personal/notebook tier (by design, so a sandbox denial never crashes
# search) — which looks exactly like "no entries yet". This probe exists
# so the failure is *loud and actionable* instead of invisible.
_FDA_HINT = (
    "cannot read the Obsidian vault at {path}: Operation not permitted.\n"
    "This is almost always macOS Full Disk Access: iCloud-backed vaults "
    "under ~/Library/Mobile Documents/ are TCC-protected.\n"
    "Fix: System Settings -> Privacy & Security -> Full Disk Access, then "
    "grant access to your terminal app AND the `claude` binary, then retry."
)

# Probe status vocabulary. ``blocked`` is the one that matters — it means
# the dir resolved but reads are denied (the FDA case). The others are
# benign / informational.
PROBE_OK = "ok"                    # resolved + a real .md read succeeded
PROBE_EMPTY = "empty"             # resolved + readable, but no entries yet
PROBE_MISSING = "missing"        # resolved, but the dir doesn't exist yet
PROBE_UNREGISTERED = "unregistered"  # no vault registered on this machine
PROBE_BLOCKED = "blocked"        # resolved, but reads denied (EPERM / FDA)


@dataclass(frozen=True)
class VaultProbe:
    """Outcome of :func:`probe_personal_oracle`.

    ``status`` is one of the ``PROBE_*`` constants. ``ok`` for the caller
    means the vault is genuinely readable on this machine; ``blocked`` is
    the loud Full-Disk-Access failure the CLI surfaces non-zero.
    """

    status: str
    detail: str
    path: str | None = None       # the resolved oracle dir, when known
    sample: str | None = None     # the .md file we managed (or tried) to read


def probe_personal_oracle() -> VaultProbe:
    """Resolve the personal Oracle dir and try to actually *read* a file.

    Unlike :func:`personal_oracle_dir` (which only resolves a path from
    ``obsidian.json`` and never touches the vault), this walks into the
    dir and reads one ``.md`` entry so a Full Disk Access denial surfaces
    as :data:`PROBE_BLOCKED` instead of the MCP's silent empty result.

    Never raises — every failure mode maps to a ``VaultProbe`` the CLI /
    dashboard can render.
    """
    try:
        d = personal_oracle_dir()
    except OracleError as exc:
        return VaultProbe(status=PROBE_UNREGISTERED, detail=str(exc))

    # ``exists()`` swallows OSError and returns False, so a TCC denial on
    # the parent can masquerade as "missing". Probe the read explicitly
    # below and let a PermissionError there be the authoritative signal.
    try:
        exists = d.exists()
    except OSError:
        return VaultProbe(
            status=PROBE_BLOCKED, detail=_FDA_HINT.format(path=d), path=str(d),
        )
    if not exists:
        return VaultProbe(
            status=PROBE_MISSING,
            detail=(
                f"personal Oracle dir does not exist yet: {d}\n"
                "(the Oracle agent creates it on first write, or it may be "
                "an unreadable iCloud path — run this after granting Full "
                "Disk Access if you expected entries)"
            ),
            path=str(d),
        )

    # List entries; a denial here is the classic iCloud/FDA symptom
    # (the dir stats fine but its contents can't be enumerated).
    try:
        md_files = sorted(p for p in d.rglob("*.md") if p.is_file())
    except (OSError, PermissionError):
        return VaultProbe(
            status=PROBE_BLOCKED, detail=_FDA_HINT.format(path=d), path=str(d),
        )
    if not md_files:
        return VaultProbe(
            status=PROBE_EMPTY,
            detail=f"Oracle dir is readable but has no .md entries yet: {d}",
            path=str(d),
        )

    # Actually read one entry — enumeration can succeed while per-file
    # reads are denied on some sandbox configurations.
    sample = md_files[0]
    try:
        sample.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        return VaultProbe(
            status=PROBE_BLOCKED,
            detail=_FDA_HINT.format(path=d),
            path=str(d),
            sample=str(sample),
        )
    return VaultProbe(
        status=PROBE_OK,
        detail=f"read {sample.name} successfully — vault is accessible",
        path=str(d),
        sample=str(sample),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict:
    """Return the parsed YAML frontmatter dict, or raise SchemaViolation.

    Tolerates trailing whitespace; rejects files without a fenced
    frontmatter block since we need the structured fields.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OracleError(f"could not read {path}: {exc}") from exc
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise SchemaViolation(
            f"{path.name}: missing YAML frontmatter block "
            f"(must start with `---` ... `---`)"
        )
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SchemaViolation(f"{path.name}: malformed YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SchemaViolation(f"{path.name}: frontmatter must be a mapping")
    return meta


def validate_for_publish(path: Path) -> dict:
    """Validate a draft against the schema; return its frontmatter.

    Raises one of the :class:`OracleError` subclasses on failure.
    """
    meta = _parse_frontmatter(path)
    missing = [f for f in REQUIRED_FIELDS if f not in meta or meta[f] in (None, "", [])]
    if missing:
        raise SchemaViolation(
            f"{path.name}: missing required field(s): {', '.join(missing)} "
            f"(see rules/oracle_schema.md)"
        )
    sensitivity = str(meta.get("sensitivity", "")).strip().lower()
    if sensitivity in BLOCKED_SENSITIVITIES:
        raise SensitivityBlocked(
            f"{path.name}: sensitivity={sensitivity!r} is blocked from "
            f"Lab Oracle publish — the entry must stay in your personal vault"
        )
    if not isinstance(meta.get("tags"), list) or not meta["tags"]:
        raise SchemaViolation(
            f"{path.name}: tags must be a non-empty list"
        )
    if not isinstance(meta.get("sources"), list) or not meta["sources"]:
        raise SchemaViolation(
            f"{path.name}: sources must be a non-empty list of '@handle's"
        )
    return meta


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def _target_filename(slug: str, meta: dict) -> str:
    """Build the target filename: ``<YYYY-MM-DD>_<slug>.md``.

    If the slug already starts with a date prefix (the user wrote
    ``2026-05-16_foo`` directly), use it as-is; otherwise prepend the
    ``date:`` from frontmatter. Falls back to today only if the
    frontmatter date is non-ISO (validate_for_publish lets it through
    as long as it's a non-empty string).
    """
    stem = slug.removesuffix(".md") if slug.endswith(".md") else slug
    if DATE_PREFIX_RE.match(stem):
        return f"{stem}.md"
    date_str = str(meta.get("date", "")).strip()
    return f"{date_str}_{stem}.md" if date_str else f"{stem}.md"


def publish_draft(
    slug: str,
    *,
    committer: str,
    commit: bool = True,
    push: bool = False,
) -> PublishResult:
    """Promote ``slug`` from the personal vault drafts to Lab Oracle.

    ``slug`` is the draft filename (with or without ``.md``); a date
    prefix gets added at the destination if not already present. The
    source draft is **removed** on success so the vault doesn't carry
    duplicates between personal and lab tiers.

    Set ``commit=False`` for a dry-run that just stages the file and
    reports what would happen. ``push`` requires ``commit`` and runs
    ``git push`` after the commit lands.
    """
    if not slug or not SLUG_RE.match(slug.removesuffix(".md")):
        raise OracleError(
            f"invalid slug {slug!r}: use [A-Za-z0-9_-] only"
        )

    stem = slug.removesuffix(".md") if slug.endswith(".md") else slug
    src = vault_drafts_dir() / f"{stem}.md"
    if not src.is_file():
        raise DraftNotFound(
            f"no draft at {src} — list with `murmurent oracle vault-drafts`"
        )

    meta = validate_for_publish(src)

    lab_dir = lab_oracle_dir()
    lab_dir.mkdir(parents=True, exist_ok=True)
    dest = lab_dir / _target_filename(stem, meta)
    if dest.exists():
        raise TargetExists(
            f"{dest} already exists — rename your draft slug or remove "
            f"the existing lab entry first"
        )

    shutil.copy2(src, dest)

    sha: str | None = None
    if commit:
        sha = _git_commit(dest, committer=committer, title=str(meta["title"]))
        if push:
            _git_push(dest.parent)

    # Only delete the source draft after a successful commit (or after a
    # successful copy if commit=False) so a failed git op leaves the
    # vault draft intact for the user to retry.
    try:
        src.unlink()
    except OSError:
        pass  # non-fatal — the lab side already landed

    return PublishResult(
        source=src, target=dest, commit_sha=sha, pushed=(commit and push),
    )


def _git_commit(path: Path, *, committer: str, title: str) -> str:
    """Stage + commit ``path`` to its repo. Returns short SHA.

    Runs all git commands from the file's parent dir so the call lands
    in the right working tree regardless of where the CLI was invoked.
    """
    repo = path.parent
    msg = (
        f"oracle: publish '{title}' from @{committer.lstrip('@')}'s vault\n\n"
        f"Promoted via `murmurent oracle publish` from the committer's "
        f"personal Oracle drafts into the Lab Oracle."
    )
    subprocess.run(
        ["git", "add", "--", str(path.name)],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, check=True, capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()
    return sha


def _git_push(cwd: Path) -> None:
    subprocess.run(["git", "push"], cwd=cwd, check=True, capture_output=True)
