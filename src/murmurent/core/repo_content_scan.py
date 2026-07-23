"""
Purpose: the deterministic **local-repo content scanners** — issue #63 Phase 2,
         items 2(ii) output-location, 2(iii) network safety, 2(iv) data-shipping
         / external-API egress. For each LOCAL murmurent-ready repo, scan its
         source files with fast, read-only grep-style matching and emit
         :class:`Finding` rows into the personal-audit pipeline.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-23
Input: a member handle, the local repo inventory (``repo_inventory.RepoOnHost``),
       an ``is_clinical(repo) -> bool`` predicate, and the data-root resolver
       (``lab_vm``). All read-only.
Output: a flat list of :class:`Finding` (categories ``output`` / ``network`` /
        ``egress``), rolled up per directory so a repo with many hits collapses
        to a few rows.

Design notes / heuristics (deliberately CONSERVATIVE — false positives erode
trust in the report):

- **2(ii) output-location** — only a *literal, absolute/home-anchored* write
  target that resolves OUTSIDE the data root is flagged (warn; block on a
  clinical repo). Dynamic / variable / relative paths are NOT flagged: we cannot
  resolve them, and guessing produces noise. If the data root itself is
  unresolvable we emit ONE ``unverifiable`` finding rather than silently
  passing.
- **2(iii) network** — insecure transports (``http://`` to a non-localhost host,
  ``ftp://``, ``telnet``, plaintext ``smtplib.SMTP(``) warn; credentials
  embedded in a URL (``scheme://user:pass@host``) block. ``https``/``sftp``/
  ``ssh``/``scp`` are FINE and never flagged here.
- **2(iv) egress** — outbound/API usage is surfaced as **info** (not an error):
  "this repo reaches out to <destination>". Anthropic/OpenAI AI calls are tagged
  distinctly (expected AI usage) from arbitrary hosts / cloud uploads. On a
  **clinical** repo, data-shipping / upload / cloud / email egress escalates
  (clinical data must not leave the governed store).

Read-only by construction: this module only reads files. It never writes,
renames, deletes, or makes a network call of its own.
"""

from __future__ import annotations

import datetime as _dt
import os
import re as _re
from pathlib import Path

from . import lab_vm as _lab_vm
from .security_findings import (
    Finding,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SOURCE_SCANNER,
    VERIFY_UNVERIFIABLE,
    VERIFY_VERIFIED,
    rollup_by_directory,
)

# ---------------------------------------------------------------------------
# Areas + scan bounds
# ---------------------------------------------------------------------------

AREA_OUTPUT = "output"
AREA_NETWORK = "network"
AREA_EGRESS = "egress"

LOCAL_HOST = "local"

# Source file extensions we scan (lower-cased comparison, so ``.R``/``.Rmd``
# match). Everything else (binaries, data, notebooks-as-binary, images) is
# skipped up front.
SCAN_EXTS = frozenset({
    ".py", ".r", ".sh", ".ipynb", ".js", ".ts", ".sql", ".rmd", ".bash",
})

# Directories never descended into: VCS, dependency trees, caches, and the
# governed data store (immutable/append_only/raw/refined/clinical) which is
# data, not code.
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ipynb_checkpoints", ".tox", ".cache",
    "site-packages", "dist", "build", ".Rproj.user", ".next", "target",
    "immutable", "append_only", "raw", "refined", "clinical",
})

MAX_FILE_BYTES = 512 * 1024      # skip files larger than ~512 KB
MAX_FILES_PER_REPO = 1500        # cap files scanned per repo (log if truncated)
MAX_LINE_LEN = 4000              # skip absurdly long (minified) lines

# Hosts that appear in ``http://`` only as XML/namespace identifiers, never as
# a real network endpoint — skipped so schemas don't masquerade as insecure
# transport.
_NAMESPACE_HOSTS = frozenset({
    "www.w3.org", "w3.org", "schemas.xmlsoap.org", "purl.org", "xml.apache.org",
    "java.sun.com", "ns.adobe.com", "docbook.org", "jabber.org", "tempuri.org",
    "schemas.microsoft.com", "www.opengis.net", "maven.apache.org",
})
_LOCALHOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(handle: str) -> str:
    return str(handle or "").strip().lstrip("@").lower()


def _mk(area: str, rule: str, *, severity: str, path: str, current: str,
        expected: str = "", fix: str = "", handle: str | None = None,
        notes: str = "", verify_state: str = VERIFY_VERIFIED) -> Finding:
    """Content-scanner :class:`Finding` factory. Mirrors
    :func:`personal_audit._mk` (source=scanner, host=local) so rows render
    identically, without a circular import."""
    return Finding(
        severity=severity, category=area, rule=rule, host=LOCAL_HOST, path=path,
        current_state=current, expected_state=expected, suggested_fix=fix,
        detected_at=_now_iso(), source=SOURCE_SCANNER, verify_state=verify_state,
        owner_handle=(f"@{_norm(handle)}" if handle else None),
        rule_doc_anchor="docs/security-dashboard.md#personal-audit", notes=notes,
    )


# ===========================================================================
# 2(ii) — output-location matchers
# ===========================================================================
#
# Each pattern captures a single literal path argument in group(1). Only sinks
# whose target is a *string literal* are matched; a variable/dynamic target
# leaves group(1) unmatched, and the whole line is skipped (conservative).

_OUTPUT_PATTERNS: tuple[_re.Pattern, ...] = (
    # Python file open in a write/append mode: open("path", "w"/"a"/"wb"/…)
    _re.compile(r"""\bopen\(\s*['"]([^'"]+)['"]\s*,\s*['"][^'"]*[wa][^'"]*['"]"""),
    # pandas / numpy / matplotlib literal sinks
    _re.compile(r"""\.to_(?:csv|parquet|pickle|feather|hdf|json|excel)\(\s*['"]([^'"]+)['"]"""),
    _re.compile(r"""\b(?:savefig|ggsave)\(\s*['"]([^'"]+)['"]"""),
    _re.compile(r"""\bnp\.save(?:z|txt)?\(\s*['"]([^'"]+)['"]"""),
    # pathlib literal writers: Path("x").write_text(...) / Path("x").open("w")
    _re.compile(r"""\bPath\(\s*['"]([^'"]+)['"]\s*\)\s*\.\s*write_(?:text|bytes)"""),
    _re.compile(r"""\bPath\(\s*['"]([^'"]+)['"]\s*\)\s*\.\s*open\(\s*['"][^'"]*[wa][^'"]*['"]"""),
    # R writers — path is the 2nd (positional or file=/path= keyword) argument
    _re.compile(
        r"""\b(?:write\.csv|write\.csv2|write\.table|saveRDS|write_csv|write_tsv|"""
        r"""write_rds|write_delim|writeLines|write_parquet)\s*\([^,]*,\s*"""
        r"""(?:[A-Za-z_.]+\s*=\s*)?['"]([^'"]+)['"]"""),
)
# Shell redirect to an absolute or home-anchored literal path: > /tmp/x  >> ~/y
_OUTPUT_SH_REDIR = _re.compile(r""">>?\s*['"]?([~/][^\s'"|;&<>]*)""")


def _expand(raw: str) -> str:
    """Expand ``~`` and ``$HOME`` / ``${HOME}`` in a literal path string."""
    s = raw.strip()
    home = str(Path.home())
    s = s.replace("${HOME}", home).replace("$HOME", home)
    if s.startswith("~"):
        try:
            s = str(Path(s).expanduser())
        except (RuntimeError, ValueError):
            pass
    return s


def _is_under(path_str: str, root: Path) -> bool:
    """Lexical containment: is ``path_str`` at or under ``root``? Uses
    ``normpath`` (no filesystem access — the write target may not exist yet)."""
    p = os.path.normpath(path_str)
    r = os.path.normpath(str(root))
    return p == r or p.startswith(r.rstrip("/") + os.sep)


def _write_is_outside_root(raw_path: str, data_root: Path) -> bool:
    """True when ``raw_path`` is a literal ABSOLUTE (or home-anchored) path that
    resolves OUTSIDE ``data_root``. Relative / dynamic paths return False (we do
    not flag them — they resolve into the repo working dir, which is ambiguous,
    not clearly an over-share)."""
    expanded = _expand(raw_path)
    if not expanded.startswith("/"):
        return False  # relative or still-symbolic → skip (conservative)
    return not _is_under(expanded, data_root)


# ===========================================================================
# 2(iii) — network matchers
# ===========================================================================

# scheme://user:pass@host  — credentials embedded in a URL (BLOCK).
_NET_CRED_IN_URL = _re.compile(
    r"""[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:'"]+:[^/@\s'"]+@""")
# http:// to some host (we filter localhost + namespace hosts afterwards).
_NET_HTTP = _re.compile(r"""http://([A-Za-z0-9_.\-\[\]:]+)""")
_NET_FTP = _re.compile(r"""\bftp://""")
_NET_TELNET = _re.compile(r"""\btelnet(?://|\s)""")
# Plaintext SMTP (SMTP_SSL has a ``_`` after SMTP so it is not matched).
_NET_SMTP = _re.compile(r"""\bsmtplib\.SMTP\(""")


def _network_hits(line: str) -> list[tuple[str, str, str]]:
    """Return ``(rule, severity, message)`` tuples for network concerns on one
    line. ``https``/``sftp``/``ssh``/``scp`` are intentionally NOT matched."""
    out: list[tuple[str, str, str]] = []
    m = _NET_CRED_IN_URL.search(line)
    if m:
        # Redact the password so the finding itself never leaks the secret.
        shown = _re.sub(r"(://[^/\s:'\"]+:)[^/@\s'\"]+@", r"\1***@", m.group(0))
        out.append(("PERSONAL-NET-CRED-IN-URL-01", SEVERITY_BLOCK,
                    f"credentials embedded in a URL: {shown}"))
    for hm in _NET_HTTP.finditer(line):
        host = hm.group(1).lower().split(":")[0]
        if host in _LOCALHOSTS or host in _NAMESPACE_HOSTS:
            continue
        out.append(("PERSONAL-NET-INSECURE-HTTP-01", SEVERITY_WARN,
                    f"insecure http:// transport to {hm.group(1)}"))
        break  # one http finding per line is enough
    if _NET_FTP.search(line):
        out.append(("PERSONAL-NET-INSECURE-FTP-01", SEVERITY_WARN,
                    "insecure ftp:// transport (use sftp)"))
    if _NET_TELNET.search(line):
        out.append(("PERSONAL-NET-INSECURE-TELNET-01", SEVERITY_WARN,
                    "telnet transport (use ssh)"))
    if _NET_SMTP.search(line):
        out.append(("PERSONAL-NET-INSECURE-SMTP-01", SEVERITY_WARN,
                    "plaintext smtplib.SMTP (use SMTP_SSL / starttls)"))
    return out


# ===========================================================================
# 2(iv) — egress matchers
# ===========================================================================
#
# ``kind`` drives dashboard tinting + clinical escalation:
#   ai            → expected AI usage (Anthropic/OpenAI), never escalates
#   http-client   → generic outbound HTTP; clinical → warn (reaching out)
#   cloud         → cloud SDK; clinical → BLOCK (data must not leave)
#   transfer      → scp/rsync/upload/paramiko/curl; clinical → BLOCK
#   email         → smtplib/sendmail; clinical → BLOCK

_EGRESS_PATTERNS: tuple[tuple[_re.Pattern, str, str], ...] = (
    (_re.compile(r"""\b(?:import\s+anthropic|from\s+anthropic\b|anthropic\.|api\.anthropic\.com)"""),
     "ai", "Anthropic API"),
    (_re.compile(r"""\b(?:import\s+openai|from\s+openai\b|openai\.|api\.openai\.com)"""),
     "ai", "OpenAI API"),
    (_re.compile(r"""\b(?:import\s+requests|requests\.(?:get|post|put|patch|delete|head|request|Session))"""),
     "http-client", "requests"),
    (_re.compile(r"""\b(?:import\s+httpx|httpx\.)"""), "http-client", "httpx"),
    (_re.compile(r"""\b(?:urllib\.request|urllib3|from\s+urllib\b|import\s+urllib\b)"""),
     "http-client", "urllib"),
    (_re.compile(r"""\b(?:import\s+boto3|boto3\.)"""), "cloud", "AWS (boto3)"),
    (_re.compile(r"""\bfrom\s+google\.cloud\b|google\.cloud\."""), "cloud", "Google Cloud"),
    (_re.compile(r"""\b(?:import\s+azure|from\s+azure\b|azure\.storage)"""), "cloud", "Azure"),
    (_re.compile(r"""\b(?:import\s+paramiko|paramiko\.)"""), "transfer", "paramiko (ssh/scp)"),
    (_re.compile(r"""\b(?:rsync\s|scp\s|sftp\s)"""), "transfer", "scp/rsync/sftp"),
    (_re.compile(r"""\.upload(?:_file|_from_filename|_fileobj|_blob)?\("""),
     "transfer", "upload()"),
    (_re.compile(r"""\bcurl\s"""), "transfer", "curl"),
    (_re.compile(r"""\b(?:import\s+smtplib|smtplib\.|sendmail\()"""), "email", "email (smtplib)"),
)

# On a clinical repo these egress kinds mean data may leave the governed store.
_EGRESS_CLINICAL_BLOCK = frozenset({"cloud", "transfer", "email"})
_EGRESS_KIND_RULE = {
    "ai": "PERSONAL-EGRESS-AI-01",
    "http-client": "PERSONAL-EGRESS-HTTP-CLIENT-01",
    "cloud": "PERSONAL-EGRESS-CLOUD-01",
    "transfer": "PERSONAL-EGRESS-TRANSFER-01",
    "email": "PERSONAL-EGRESS-EMAIL-01",
}
_URL_HOST = _re.compile(r"""https?://([A-Za-z0-9_.\-]+)""")


def _egress_hits(line: str) -> list[tuple[str, str]]:
    """Return ``(kind, destination)`` tuples for egress signals on one line.
    ``destination`` prefers a concrete host parsed from a URL on the line, else
    the library label."""
    out: list[tuple[str, str]] = []
    host_m = _URL_HOST.search(line)
    host = host_m.group(1) if host_m else ""
    for pat, kind, label in _EGRESS_PATTERNS:
        if pat.search(line):
            dest = host if (host and kind in ("http-client", "cloud", "transfer")) else label
            out.append((kind, dest))
    return out


# ===========================================================================
# File iteration (bounded)
# ===========================================================================


def iter_source_files(repo_root: Path) -> tuple[list[Path], bool]:
    """Return ``(files, truncated)`` — up to :data:`MAX_FILES_PER_REPO` source
    files under ``repo_root`` with a scan-worthy extension and size under
    :data:`MAX_FILE_BYTES`. ``truncated`` is True when the cap was hit. Skips
    :data:`SKIP_DIRS` (VCS, deps, caches, the governed data store)."""
    files: list[Path] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune skip dirs in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".venv")]
        for fn in filenames:
            if Path(fn).suffix.lower() not in SCAN_EXTS:
                continue
            p = Path(dirpath) / fn
            try:
                if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(p)
            if len(files) >= MAX_FILES_PER_REPO:
                return files, True
    return files, truncated


def _scan_file_lines(path: Path):
    """Yield ``(lineno, line)`` for a text file, best-effort. Skips over-long
    lines (minified) and never raises on a decode/read error."""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh, start=1):
                if len(line) > MAX_LINE_LEN:
                    continue
                yield i, line
    except OSError:
        return


# ===========================================================================
# Per-repo scan
# ===========================================================================


def _scan_one_repo(repo_root: Path, *, clinical: bool, handle: str,
                   data_root: Path, data_root_ok: bool) -> list[Finding]:
    """Scan one repo's source files and return raw (un-rolled-up) findings for
    all three areas."""
    out: list[Finding] = []
    files, truncated = iter_source_files(repo_root)

    # De-dupe identical hits (same file + signature) so one messy line does not
    # spawn duplicate rows.
    seen_out: set[tuple[str, str]] = set()
    seen_net: set[tuple[str, str]] = set()
    seen_egr: set[tuple[str, str]] = set()

    for fpath in files:
        rel = str(fpath)
        for _lineno, line in _scan_file_lines(fpath):
            # -- 2(ii) output-location (only when the data root is resolvable) --
            if data_root_ok:
                literals: list[str] = []
                for pat in _OUTPUT_PATTERNS:
                    for m in pat.finditer(line):
                        literals.append(m.group(1))
                for m in _OUTPUT_SH_REDIR.finditer(line):
                    literals.append(m.group(1))
                for lit in literals:
                    if not _write_is_outside_root(lit, data_root):
                        continue
                    key = (rel, lit)
                    if key in seen_out:
                        continue
                    seen_out.add(key)
                    sev = SEVERITY_BLOCK if clinical else SEVERITY_WARN
                    out.append(_mk(
                        AREA_OUTPUT, "PERSONAL-OUTPUT-OUTSIDE-ROOT-01",
                        severity=sev, path=rel,
                        current=f"writes to a path outside the data root: {lit}",
                        expected=f"write under the data root ({data_root})",
                        fix="redirect output under $MURMURENT_DATA_ROOT/"
                            "append_only/<project>/…",
                        handle=handle,
                        notes=("clinical repo: out-of-root write escalated to BLOCK. "
                               if clinical else "")
                        + "heuristic: only literal out-of-root paths are flagged; "
                          "dynamic paths are not."))

            # -- 2(iii) network safety --------------------------------------
            for rule, sev, msg in _network_hits(line):
                key = (rel, rule)
                if key in seen_net:
                    continue
                seen_net.add(key)
                out.append(_mk(
                    AREA_NETWORK, rule, severity=sev, path=rel, current=msg,
                    expected="use TLS/SSH transports (https, sftp, ssh, scp); "
                             "no credentials in URLs",
                    handle=handle,
                    notes="clinical repo" if clinical else ""))

            # -- 2(iv) egress ------------------------------------------------
            for kind, dest in _egress_hits(line):
                key = (rel, f"{kind}:{dest}")
                if key in seen_egr:
                    continue
                seen_egr.add(key)
                rule = _EGRESS_KIND_RULE[kind]
                if clinical and kind in _EGRESS_CLINICAL_BLOCK:
                    sev = SEVERITY_BLOCK
                elif clinical:
                    sev = SEVERITY_WARN
                else:
                    sev = SEVERITY_INFO
                tag = "expected-ai" if kind == "ai" else kind
                note = f"egress-kind={tag}"
                if clinical and kind in _EGRESS_CLINICAL_BLOCK:
                    note += "; clinical data must not leave — escalated to BLOCK"
                elif clinical:
                    note += "; clinical repo reaches out — review"
                out.append(_mk(
                    AREA_EGRESS, rule, severity=sev, path=rel,
                    current=f"reaches out to {dest}",
                    expected="informational — surfaced so you can confirm it is "
                             "intended" if not clinical else "clinical data stays "
                             "in the governed store",
                    handle=handle, notes=note))

    if truncated:
        out.append(_mk(
            AREA_OUTPUT, "PERSONAL-SCAN-TRUNCATED-01", severity=SEVERITY_INFO,
            path=str(repo_root),
            current=f"scan hit the {MAX_FILES_PER_REPO}-file cap for this repo; "
                    "some files were not examined",
            expected="informational — a very large repo was only partially scanned",
            handle=handle, verify_state=VERIFY_UNVERIFIABLE,
            notes="Increase MAX_FILES_PER_REPO if full coverage is required."))
    return out


def scan_repos(handle: str, repos: list, env: dict | None,
               is_clinical) -> list[Finding]:
    """Scan every LOCAL murmurent-ready repo for content concerns (2ii–2iv).

    ``is_clinical(repo) -> bool`` decides clinical escalation per repo.
    Returns findings rolled up per directory. When the data root is unresolvable
    the output-location check emits a single ``unverifiable`` finding (and is
    otherwise skipped) so the report never silently passes.

    TODO(phase-3): the SEMANTIC LLM egress category — reasoning about whether a
    given outbound call actually ships restricted DATA vs. a benign metadata
    request — plugs in via ``security_agent_review.py`` (a new ``egress``
    reviewer), consuming these deterministic ``AREA_EGRESS`` findings as priors.
    Not built in this phase.
    """
    data_root = _lab_vm.data_root(env)
    data_root_ok = _data_root_resolvable(env)

    out: list[Finding] = []
    if not data_root_ok:
        out.append(_mk(
            AREA_OUTPUT, "PERSONAL-OUTPUT-UNVERIFIABLE-01", severity=SEVERITY_INFO,
            path=str(data_root),
            current="data root is unresolvable (no $MURMURENT_DATA_ROOT and the "
                    "default does not exist) — cannot judge output locations",
            expected="set $MURMURENT_DATA_ROOT so out-of-root writes can be checked",
            handle=handle, verify_state=VERIFY_UNVERIFIABLE,
            notes="Skipped the output-location check; network + egress still ran."))

    scanned_any = False
    for repo in repos:
        if not getattr(repo, "is_murmurent_ready", False):
            continue
        root = Path(getattr(repo, "path", ""))
        if not root.is_dir():
            continue
        scanned_any = True
        try:
            clinical = bool(is_clinical(repo))
        except Exception:  # noqa: BLE001
            clinical = False
        out += _scan_one_repo(root, clinical=clinical, handle=handle,
                              data_root=data_root, data_root_ok=data_root_ok)

    # Summary "clean" rows so the report shows a green per area rather than an
    # empty void when nothing matched.
    if scanned_any:
        if data_root_ok and not any(f.category == AREA_OUTPUT and
                                    f.rule == "PERSONAL-OUTPUT-OUTSIDE-ROOT-01"
                                    for f in out):
            out.append(_mk(AREA_OUTPUT, "PERSONAL-OUTPUT-CLEAN-01",
                           severity=SEVERITY_INFO, path="(local mm-ready repos)",
                           current="no literal out-of-root write targets detected",
                           handle=handle))
        if not any(f.category == AREA_NETWORK for f in out):
            out.append(_mk(AREA_NETWORK, "PERSONAL-NET-CLEAN-01",
                           severity=SEVERITY_INFO, path="(local mm-ready repos)",
                           current="no insecure transports or in-URL credentials "
                                   "detected",
                           handle=handle))
        if not any(f.category == AREA_EGRESS for f in out):
            out.append(_mk(AREA_EGRESS, "PERSONAL-EGRESS-NONE-01",
                           severity=SEVERITY_INFO, path="(local mm-ready repos)",
                           current="no outbound/API egress detected",
                           handle=handle))

    return rollup_by_directory(out)


def _data_root_resolvable(env: dict | None) -> bool:
    """True when the data root is trustworthy for out-of-root comparisons: an
    env var is set, OR the default root actually exists on disk. Otherwise we
    cannot reliably say what "outside the root" means."""
    src = os.environ if env is None else env
    if src.get(_lab_vm.ENV_VAR) or src.get(_lab_vm.LEGACY_ENV_VAR):
        return True
    try:
        return _lab_vm.data_root(env).exists()
    except OSError:
        return False


__all__ = [
    "AREA_OUTPUT", "AREA_NETWORK", "AREA_EGRESS",
    "SCAN_EXTS", "SKIP_DIRS", "MAX_FILE_BYTES", "MAX_FILES_PER_REPO",
    "MAX_LINE_LEN", "iter_source_files", "scan_repos",
]
