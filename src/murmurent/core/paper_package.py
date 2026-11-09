"""
Purpose: The queryable paper package and the thesis composed from paper
         packages (issue #284). A paper package is a manuscript repository
         with a ``paper.yaml`` manifest that maps every central claim to the
         code and data behind it, so that a reader, a reviewer or an examiner
         can open it in Claude Code and ask it questions. A thesis package
         (``thesis.yaml``) lists paper packages, or plain chapters carrying
         their own claims, plus the candidate's introduction, bridges,
         conclusion and front matter. This module scaffolds, checks and
         builds both, drafts the defence talk, and writes the Western (SGPS)
         submission paperwork checklist. ``murmurent paper`` and
         ``murmurent thesis`` wrap it; the ``docent`` agent reads what it
         produces.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-06
Input: A package directory holding ``paper.yaml`` or ``thesis.yaml``.
Output: Findings (errors and warnings) from ``check_paper`` /
        ``check_thesis``; ``build/claim_map.md``, ``build/main.tex``,
        ``build/talk.tex``, ``build/talk_plan.md``, ``build/paperwork.md``
        and optionally PDFs from the ``build_*`` functions.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

PAPER_MANIFEST = "paper.yaml"
THESIS_MANIFEST = "thesis.yaml"
PAPER_VERSION = 1
THESIS_VERSION = 1
QUERIES_DIR = "queries"
BUILD_DIR = "build"
CLAIM_MAP = "claim_map.md"

# Western SGPS limits, as read on 2026-11-06 from the SGPS thesis pages and
# the Senate "Procedure for Thesis Formats and Content". Change here, not in
# the checks.
LAY_SUMMARY_MAX_WORDS = 350
ABSTRACT_MAX_WORDS = {"doctoral": 350, "masters": 150}
SUPPLEMENT_MAX_MB = 100
PHD_LEAD_WORKING_DAYS = 25   # five working weeks before the defence
MASTERS_LEAD_WORKING_DAYS = 15  # three working weeks
# Examination boards (SGPS regulation 8.4; confirm with the program). A
# doctoral board has an External Examiner from another university; a master's
# board has no external and its composition is set by the program.
BOARD_ROLES = {"doctoral": {"external": 1, "university": 1, "program": 2},
               "masters": {"university": 1, "program": 1}}
BOARD_ROLES_OPTIONAL = ("knowledge_keeper",)


def degree_level(degree: str) -> str:
    """``"doctoral"`` or ``"masters"`` from the degree name."""
    d = (degree or "").lower()
    if "philosophy" in d or d.startswith("phd") or "doctor" in d or "d.phil" in d:
        return "doctoral"
    if "master" in d or d.startswith("msc") or d.startswith("m.sc") or d.startswith("ma"):
        return "masters"
    return "doctoral"

SENSITIVITIES = ("standard", "restricted", "protected")
PAPER_STATUSES = ("in-prep", "submitted", "published")
# Data references that live under the lab's data root rather than inside the
# package. ``rules/data-storage.md`` names the folders.
DATA_ROOT_FOLDERS = ("immutable", "append_only", "modifiable", "release")
LEGACY_DATA_ROOT_FOLDERS = {"immutable": "raw", "append_only": "refined"}
DATA_ROOT_ENV = ("MURMURENT_DATA_ROOT", "MURMURENT_LAB_VM_ROOT")
CHAPTER_KINDS = ("introduction", "paper", "chapter", "conclusion")


class PackageError(Exception):
    """A package cannot be read at all (no manifest, bad YAML)."""


@dataclass
class Finding:
    """One thing ``check`` has to say. ``level`` is ``error`` or ``warning``."""

    level: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.where}: {self.message}"


@dataclass
class CheckReport:
    findings: list[Finding] = field(default_factory=list)

    def error(self, where: str, message: str) -> None:
        self.findings.append(Finding("error", where, message))

    def warn(self, where: str, message: str) -> None:
        self.findings.append(Finding("warning", where, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def ok(self, *, strict: bool = False) -> bool:
        return not self.errors and not (strict and self.warnings)

    def extend(self, other: "CheckReport", prefix: str) -> None:
        for f in other.findings:
            self.findings.append(Finding(f.level, f"{prefix} > {f.where}", f.message))

    def format(self) -> str:
        if not self.findings:
            return "OK: no findings."
        lines = [str(f) for f in self.findings]
        lines.append(f"{len(self.errors)} error(s), {len(self.warnings)} warning(s).")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Reading manifests
# --------------------------------------------------------------------------- #


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PackageError(f"no {path.name} in {path.parent}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - yaml's own message
        raise PackageError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PackageError(f"{path} must hold a mapping at the top level")
    return data


def read_paper(package: Path) -> dict[str, Any]:
    return _load_yaml(Path(package) / PAPER_MANIFEST)


def read_thesis(package: Path) -> dict[str, Any]:
    return _load_yaml(Path(package) / THESIS_MANIFEST)


def data_root() -> Path | None:
    for name in DATA_ROOT_ENV:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def is_data_root_ref(ref: str) -> bool:
    parts = Path(ref).parts
    return bool(parts) and parts[0] in DATA_ROOT_FOLDERS


def resolve_data_ref(package: Path, ref: str) -> tuple[Path | None, str]:
    """Return ``(path, kind)`` for a data reference.

    ``kind`` is ``"package"`` for a file inside the package, ``"root"`` for a
    file under the lab's data root, and ``"unreachable"`` when the reference
    is a data-root path but no data root is set on this machine.
    """
    if is_data_root_ref(ref):
        root = data_root()
        if root is None:
            return None, "unreachable"
        path = root / ref
        if not path.exists():
            # A data root that still uses the previous folder names
            # (``rules/data-storage.md``: raw/ became immutable/, refined/
            # became append_only/) is read under those names.
            parts = Path(ref).parts
            legacy = LEGACY_DATA_ROOT_FOLDERS.get(parts[0])
            if legacy and (root / legacy).joinpath(*parts[1:]).exists():
                path = (root / legacy).joinpath(*parts[1:])
        return path, "root"
    return Path(package) / ref, "package"


def _sensitivity(raw: Any) -> str:
    s = str(raw or "standard")
    return "protected" if s == "clinical" else s


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _word_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"%.*", " ", text)
    text = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", text)  # drop LaTeX commands
    return len(text.split())


# --------------------------------------------------------------------------- #
# Claims: shared by paper packages and thesis chapters
# --------------------------------------------------------------------------- #


def _label_in_source(label: str, text: str) -> bool:
    return re.search(r"\\label\{" + re.escape(label) + r"\}", text) is not None


def _check_claims(base: Path, claims: Any, *, source_text: str, source_name: str,
                  sensitivity: str, rep: CheckReport, where_prefix: str = "") -> None:
    """Check a list of claims against the files under ``base``. Appends
    findings to ``rep``. A protected package may not bundle data."""
    if claims is None:
        claims = []
    if not isinstance(claims, list):
        rep.error(f"{where_prefix}claims", "`claims:` must be a list")
        return
    if not claims:
        rep.warn(f"{where_prefix}claims", "no claims are listed: readable but not re-runnable")
        return
    seen: set[str] = set()
    bundled: list[str] = []
    for i, c in enumerate(claims, start=1):
        if not isinstance(c, dict):
            rep.error(f"{where_prefix}claims[{i}]", "each claim must be a mapping")
            continue
        cid = str(c.get("id") or f"claim-{i}")
        where = f"{where_prefix}claim {cid}"
        if cid in seen:
            rep.error(where, "duplicate claim id")
        seen.add(cid)
        if not c.get("text"):
            rep.error(where, "missing `text:` (the claim in one sentence)")
        code = c.get("code")
        if not code:
            rep.warn(where, "no `code:`; this claim cannot be re-run")
        elif not (base / code).exists():
            rep.error(where, f"code path {code} does not exist")
        fig = c.get("figure")
        if fig and source_text and not _label_in_source(fig, source_text):
            rep.error(where, f"figure label `{fig}` is not defined in {source_name}")
        for ref in _as_list(c.get("data")):
            path, kind = resolve_data_ref(base, ref)
            if kind == "unreachable":
                rep.warn(where, f"data {ref} lives under the data root, which is not set on this machine")
            elif path is not None and not path.exists():
                if kind == "package":
                    rep.error(where, f"data {ref} does not exist")
                else:
                    rep.warn(where, f"data {ref} does not exist under the data root")
            if kind == "package":
                bundled.append(ref)
    if sensitivity == "protected" and bundled:
        rep.error(
            f"{where_prefix}sensitivity",
            "protected data must not be bundled in the package; keep it under the data root "
            f"and reference it there (bundled: {', '.join(bundled)})",
        )


def claim_rows(claims: Any) -> list[str]:
    """Markdown table rows, one per claim, for a claim map."""
    rows = ["| Claim | Where | Figure | Code | Data |", "|---|---|---|---|---|"]
    for i, c in enumerate(claims or [], start=1):
        if not isinstance(c, dict):
            continue
        data = ", ".join(f"`{d}`" for d in _as_list(c.get("data")))
        code = f"`{c['code']}`" if c.get("code") else "(none: not re-runnable)"
        rows.append(
            f"| **{c.get('id', i)}**: {c.get('text', '')} "
            f"| {c.get('where', '')} | {c.get('figure', '')} | {code} | {data} |"
        )
    return rows


# --------------------------------------------------------------------------- #
# Paper packages
# --------------------------------------------------------------------------- #


def check_paper(package: Path, *, _as_chapter: bool = False) -> CheckReport:
    """Check one paper package. Never raises on a bad package: every problem
    is a finding, so a thesis check can report all its papers at once."""
    package = Path(package)
    rep = CheckReport()
    try:
        m = read_paper(package)
    except PackageError as exc:
        rep.error(PAPER_MANIFEST, str(exc))
        return rep

    if m.get("paper") != PAPER_VERSION:
        rep.error(PAPER_MANIFEST, f"`paper:` must be {PAPER_VERSION}")
    for key in ("title", "authors", "source", "claims"):
        if key not in m:
            rep.error(PAPER_MANIFEST, f"missing required field `{key}`")
    status = m.get("status", "in-prep")
    if status not in PAPER_STATUSES:
        rep.error(PAPER_MANIFEST, f"`status:` must be one of {', '.join(PAPER_STATUSES)}")
    if status == "published" and not m.get("doi"):
        rep.warn(PAPER_MANIFEST, "status is `published` but no `doi:` is given")
    sensitivity = _sensitivity(m.get("sensitivity"))
    if sensitivity not in SENSITIVITIES:
        rep.error(PAPER_MANIFEST, f"`sensitivity:` must be one of {', '.join(SENSITIVITIES)}")

    source_text = ""
    source = m.get("source")
    if source:
        source_path = package / source
        if not source_path.is_file():
            rep.error("source", f"{source} does not exist")
        else:
            source_text = source_path.read_text(encoding="utf-8", errors="replace")

    _check_claims(package, m.get("claims"), source_text=source_text,
                  source_name=str(source), sensitivity=sensitivity, rep=rep)

    if not _as_chapter:
        if not (package / "CLAUDE.md").is_file():
            rep.warn("CLAUDE.md", "missing; `murmurent paper init` writes the reader's primer")
        if not (package / QUERIES_DIR).is_dir():
            rep.warn(QUERIES_DIR, "missing; the docent logs each reader's questions there")
        if not (package / ".murmurent.yaml").is_file():
            rep.warn(".murmurent.yaml", "the package is not murmurent-ready (no marker)")
    return rep


def paper_claim_map(package: Path) -> str:
    """The docent's map of one paper: every claim, where it is, how to re-run it."""
    package = Path(package)
    m = read_paper(package)
    head = [f"# Claim map: {m.get('title', '(untitled)')}", ""]
    head.append(f"Source: `{m.get('source')}`. Status: {m.get('status', 'in-prep')}."
                + (f" DOI: {m['doi']}." if m.get("doi") else ""))
    head.append("")
    rows = claim_rows(m.get("claims"))
    tail = ["", "A claim with no code cannot be re-run; say so rather than guessing."]
    return "\n".join(head + rows + tail) + "\n"


def build_paper(package: Path, *, pdf: bool = False) -> list[str]:
    """Write ``build/claim_map.md`` and, with ``pdf=True`` and latexmk on the
    machine, ``build/<source>.pdf``. Returns one line per thing done."""
    package = Path(package)
    out = package / BUILD_DIR
    out.mkdir(exist_ok=True)
    done: list[str] = []
    (out / CLAIM_MAP).write_text(paper_claim_map(package), encoding="utf-8")
    done.append(f"wrote {BUILD_DIR}/{CLAIM_MAP}")
    if pdf:
        source = read_paper(package).get("source")
        done.append(_latexmk(package, Path(source), out))
    return done


def _latexmk(cwd: Path, source: Path, out: Path) -> str:
    exe = shutil.which("latexmk")
    if exe is None:
        return "PDF skipped: latexmk is not installed on this machine"
    pdf = out / source.with_suffix(".pdf").name
    log = out / source.with_suffix(".log").name
    before = pdf.stat().st_mtime if pdf.exists() else None
    # A run that ended in errors leaves half-written contents and figure lists
    # that make the next run loop; start each build from clean auxiliaries.
    for ext in (".aux", ".lof", ".lot", ".toc", ".out", ".nav", ".snm"):
        stale = out / source.with_suffix(ext).name
        if stale.exists():
            stale.unlink()
    # No ``-f``: forcing latexmk past LaTeX errors makes a later pass loop on
    # the broken contents and figure lists the first pass wrote. A thesis with
    # errors gets its PDF from the first pass and a count of what to fix.
    try:
        proc = subprocess.run(
            [exe, "-pdf", "-interaction=nonstopmode", f"-outdir={out}", str(source)],
            cwd=str(cwd), capture_output=True, text=True, timeout=LATEXMK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"PDF failed: latexmk did not finish in {LATEXMK_TIMEOUT_S // 60} minutes"
    written = pdf.exists() and pdf.stat().st_mtime != before
    if proc.returncode == 0:
        return f"wrote {BUILD_DIR}/{pdf.name}"
    errors = 0
    biber = ""
    if log.exists():
        errors = sum(1 for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                     if line.startswith("! "))
    for line in proc.stdout.splitlines():
        if "Biber error" in line or "biber" in line.lower() and "FATAL" in line:
            biber = line.strip()
            break
    if written:
        # nonstopmode produced a PDF despite errors: say so, with where to look.
        msg = (f"wrote {BUILD_DIR}/{pdf.name} with {errors} LaTeX error(s); see {BUILD_DIR}/{log.name}. "
               "Citations and cross-references resolve once the errors are fixed")
        return msg + (f"; {biber}" if biber else "")
    tail = "\n".join(proc.stdout.splitlines()[-15:])
    return f"PDF failed: latexmk exited {proc.returncode}\n{tail}"


# --------------------------------------------------------------------------- #
# Thesis packages
# --------------------------------------------------------------------------- #


@dataclass
class ChapterInfo:
    """One chapter as the builders see it, whatever its kind."""

    index: int
    kind: str
    title: str
    claims: list[dict[str, Any]]
    source: Path | None          # LaTeX to include (a chapter's own file)
    package: Path | None         # the paper package, for kind == paper
    bridge: Path | None
    figures_dir: Path | None     # where \includegraphics paths resolve


def chapters_of(package: Path, m: dict[str, Any] | None = None) -> list[ChapterInfo]:
    package = Path(package)
    m = m or read_thesis(package)
    out: list[ChapterInfo] = []
    for i, c in enumerate(m.get("chapters") or [], start=1):
        if not isinstance(c, dict):
            continue
        kind = str(c.get("kind", ""))
        if kind == "paper" and c.get("package"):
            pkg = (package / c["package"]).resolve()
            try:
                pm = read_paper(pkg)
            except PackageError:
                pm = {}
            out.append(ChapterInfo(
                index=i, kind=kind, title=str(c.get("title") or pm.get("title") or f"Chapter {i}"),
                claims=[x for x in (pm.get("claims") or []) if isinstance(x, dict)],
                source=(pkg / pm["source"]) if pm.get("source") else None,
                package=pkg, bridge=(package / c["bridge"]) if c.get("bridge") else None,
                figures_dir=pkg,
            ))
        else:
            out.append(ChapterInfo(
                index=i, kind=kind, title=str(c.get("title") or kind.capitalize() or f"Chapter {i}"),
                claims=[x for x in (c.get("claims") or []) if isinstance(x, dict)],
                source=(package / c["source"]) if c.get("source") else None,
                package=None, bridge=None, figures_dir=package,
            ))
    return out


def check_thesis(package: Path) -> CheckReport:
    package = Path(package)
    rep = CheckReport()
    try:
        m = read_thesis(package)
    except PackageError as exc:
        rep.error(THESIS_MANIFEST, str(exc))
        return rep

    if m.get("thesis") != THESIS_VERSION:
        rep.error(THESIS_MANIFEST, f"`thesis:` must be {THESIS_VERSION}")
    for key in ("title", "candidate", "chapters"):
        if key not in m:
            rep.error(THESIS_MANIFEST, f"missing required field `{key}`")
    sensitivity = _sensitivity(m.get("sensitivity"))
    if sensitivity not in SENSITIVITIES:
        rep.error(THESIS_MANIFEST, f"`sensitivity:` must be one of {', '.join(SENSITIVITIES)}")

    front = m.get("front") or {}
    abstract_max = ABSTRACT_MAX_WORDS[degree_level(str(m.get("degree", "")))]
    for key, required in (("abstract", True), ("lay_summary", True),
                          ("genai_statement", True), ("coauthorship", False),
                          ("acknowledgements", False)):
        rel = front.get(key)
        if not rel:
            if required:
                rep.error("front", f"`front.{key}:` is required (SGPS asks for it)")
            continue
        path = package / rel
        if not path.is_file():
            rep.error("front", f"{rel} does not exist")
            continue
        n = _word_count(path)
        if key == "lay_summary" and n > LAY_SUMMARY_MAX_WORDS:
            rep.error("front", f"lay summary is {n} words; SGPS allows {LAY_SUMMARY_MAX_WORDS}")
        if key == "abstract" and n > abstract_max:
            rep.error("front", f"abstract is {n} words; SGPS allows {abstract_max}")
        if n == 0:
            rep.warn("front", f"{rel} is empty")

    chapters = m.get("chapters") or []
    if not isinstance(chapters, list):
        rep.error("chapters", "`chapters:` must be a list")
        chapters = []
    kinds = [c.get("kind") if isinstance(c, dict) else None for c in chapters]
    if kinds.count("introduction") != 1:
        rep.error("chapters", "a thesis needs exactly one chapter of kind `introduction`")
    if kinds.count("conclusion") != 1:
        rep.error("chapters", "a thesis needs exactly one chapter of kind `conclusion`")
    if not any(k in ("paper", "chapter") for k in kinds):
        rep.error("chapters", "a thesis needs at least one `paper` or `chapter` between the two")
    if kinds and kinds[0] != "introduction":
        rep.warn("chapters", "the introduction is not the first chapter")
    if kinds and kinds[-1] != "conclusion":
        rep.warn("chapters", "the conclusion is not the last chapter")

    multi_author = False
    for i, c in enumerate(chapters, start=1):
        where = f"chapter {i}"
        if not isinstance(c, dict):
            rep.error(where, "each chapter must be a mapping")
            continue
        kind = c.get("kind")
        if kind not in CHAPTER_KINDS:
            rep.error(where, f"`kind:` must be one of {', '.join(CHAPTER_KINDS)}")
            continue
        if kind == "paper":
            pkg = c.get("package")
            if not pkg:
                rep.error(where, "a paper chapter needs `package:` (path to the paper package)")
                continue
            pkg_path = (package / pkg).resolve()
            if not pkg_path.is_dir():
                rep.error(where, f"paper package {pkg} does not exist")
                continue
            rep.extend(check_paper(pkg_path, _as_chapter=True), f"{where} ({pkg})")
            try:
                pm = read_paper(pkg_path)
            except PackageError:
                pm = {}
            if len(pm.get("authors") or []) > 1:
                multi_author = True
            if pm.get("status") == "published" and not c.get("permission"):
                rep.error(where, "a published paper needs `permission:` (the publisher's copyright release)")
            elif c.get("permission") and not (package / c["permission"]).is_file():
                rep.error(where, f"permission file {c['permission']} does not exist")
            bridge = c.get("bridge")
            if bridge and not (package / bridge).is_file():
                rep.error(where, f"bridge {bridge} does not exist")
            elif not bridge:
                rep.warn(where, "no `bridge:`; SGPS asks for connecting text between articles")
            if _sensitivity(pm.get("sensitivity")) == "protected" and sensitivity != "protected":
                rep.error(where, "the paper is `protected` but the thesis is not; raise the thesis sensitivity")
        else:
            src = c.get("source")
            source_text = ""
            if not src:
                rep.error(where, f"a {kind} chapter needs `source:`")
            elif not (package / src).is_file():
                rep.error(where, f"{src} does not exist")
            else:
                source_text = (package / src).read_text(encoding="utf-8", errors="replace")
            if kind == "chapter":
                _check_claims(package, c.get("claims"), source_text=source_text,
                              source_name=str(src), sensitivity=sensitivity, rep=rep,
                              where_prefix=f"{where} ")

    if multi_author and not front.get("coauthorship"):
        rep.error("front", "a co-authored article needs `front.coauthorship:` (the candidate's contribution)")

    for i, a in enumerate(m.get("appendices") or [], start=1):
        if not isinstance(a, dict) or not a.get("source"):
            rep.error(f"appendix {i}", "each appendix needs `source:`")
        elif not (package / a["source"]).is_file():
            rep.error(f"appendix {i}", f"{a['source']} does not exist")

    if not (package / "CLAUDE.md").is_file():
        rep.warn("CLAUDE.md", "missing; `murmurent thesis init` writes the examiner's primer")
    if not (package / QUERIES_DIR).is_dir():
        rep.warn(QUERIES_DIR, "missing; the docent logs each examiner's questions there")
    return rep


_BODY_RE = re.compile(r"\\begin\{document\}(.*)\\end\{document\}", re.S)
_STRIP_RES = [
    re.compile(r"\\maketitle"),
    re.compile(r"\\begin\{abstract\}.*?\\end\{abstract\}", re.S),  # SGPS: no article abstracts
    re.compile(r"\\(title|author|date|affil|affiliation)\*?\{.*?\}\n?", re.S),
    re.compile(r"\\bibliography\{.*?\}"),
    re.compile(r"\\printbibliography.*"),
]


def paper_body_for_thesis(source_path: Path) -> str:
    """The part of a paper's LaTeX that goes into a thesis chapter: the body
    between ``\\begin{document}`` and ``\\end{document}``, without the title
    block, the abstract (SGPS presents articles without one) and the paper's
    own bibliography call. A source without a document environment is used
    whole, since it is already a fragment."""
    text = source_path.read_text(encoding="utf-8", errors="replace")
    mo = _BODY_RE.search(text)
    body = mo.group(1) if mo else text
    for rx in _STRIP_RES:
        body = rx.sub("", body)
    return body.strip() + "\n"


THESIS_DEFAULT_PREAMBLE = r"""% Default preamble. Set `preamble:` in thesis.yaml to use your own (for
% instance the one `murmurent thesis adopt` kept, or the SGPS LaTeX template).
\documentclass[12pt,oneside]{report}
\usepackage[margin=1in]{geometry}
\usepackage{graphicx,amsmath,hyperref,setspace}
"""

THESIS_TEMPLATE = r"""% Built by `murmurent thesis build` on {today}. Edit the sources, not this file.
% Front matter follows the SGPS order (title page, abstract, lay summary,
% co-authorship statement, GenAI statement, acknowledgements, contents, lists),
% then the body, bibliography and appendices.
{preamble}
\title{{{title}}}
\author{{{candidate}}}
\date{{}}
\begin{{document}}
\pagenumbering{{roman}}
\begin{{titlepage}}
\centering
{{\LARGE {title}\par}}\vspace{{2em}}
{{\large {candidate}\par}}\vspace{{1em}}
{{{degree}\par}}\vspace{{1em}}
{{{program}, {university}\par}}
\end{{titlepage}}
\chapter*{{Abstract}}\addcontentsline{{toc}}{{chapter}}{{Abstract}}\input{{{abstract}}}
\chapter*{{Summary for Lay Audience}}\addcontentsline{{toc}}{{chapter}}{{Summary for Lay Audience}}\input{{{lay_summary}}}
{coauthorship}
\chapter*{{Statement on the Use of Generative Artificial Intelligence}}\addcontentsline{{toc}}{{chapter}}{{Statement on the Use of Generative Artificial Intelligence}}\input{{{genai_statement}}}
{acknowledgements}
\tableofcontents
\listoftables
\listoffigures
\clearpage
\pagenumbering{{arabic}}
{chapters}
{bibliography}
\appendix
{appendices}
\end{{document}}
"""


def _tex_escape(s: Any) -> str:
    return re.sub(r"([&%$#_{}])", r"\\\1", str(s))


def _candidate_name(m: dict[str, Any]) -> str:
    cand = m.get("candidate") or {}
    return str(cand.get("name", "") if isinstance(cand, dict) else cand)


def thesis_claim_map(package: Path, m: dict[str, Any] | None = None) -> str:
    package = Path(package)
    m = m or read_thesis(package)
    lines = [f"# Claim map: {m.get('title', '')}", ""]
    for ch in chapters_of(package, m):
        if ch.kind in ("introduction", "conclusion"):
            continue
        lines.append(f"## Chapter {ch.index}: {ch.title}")
        lines.append("")
        if ch.package is not None:
            lines.append(f"Paper package: `{ch.package}`")
            lines.append("")
        lines.extend(claim_rows(ch.claims))
        lines.append("")
    lines.append("A claim with no code cannot be re-run; say so rather than guessing.")
    return "\n".join(lines) + "\n"


def build_thesis(package: Path, *, pdf: bool = False) -> list[str]:
    """Assemble ``build/main.tex`` from the manifest, write the combined claim
    map, and optionally run latexmk."""
    package = Path(package)
    m = read_thesis(package)
    out = package / BUILD_DIR
    chapters_dir = out / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    done: list[str] = []

    def rel(p: str | None) -> str:
        return str((package / p).resolve()) if p else ""

    front = m.get("front") or {}
    chapter_tex: list[str] = []
    for ch in chapters_of(package, m):
        parts = [f"\\chapter{{{_tex_escape(ch.title)}}}"]
        if ch.kind == "paper" and ch.package is not None and ch.source is not None:
            body = _absolute_graphics(paper_body_for_thesis(ch.source), ch.package)
            target = chapters_dir / f"{ch.index:02d}_{ch.package.name}.tex"
            target.write_text(body, encoding="utf-8")
            if ch.bridge is not None:
                parts.append(f"\\input{{{ch.bridge.resolve()}}}")
            parts.append(f"\\input{{{target.resolve()}}}")
            done.append(f"chapter {ch.index}: paper {ch.package.name} ({len(ch.claims)} claims)")
        elif ch.source is not None:
            parts.append(f"\\input{{{ch.source.resolve()}}}")
            done.append(f"chapter {ch.index}: {ch.kind} from {ch.source.name}"
                        + (f" ({len(ch.claims)} claims)" if ch.claims else ""))
        chapter_tex.append("\n".join(parts))

    appendices = "\n".join(
        f"\\chapter{{{_tex_escape(a.get('title', f'Appendix {i}'))}}}\n\\input{{{rel(a['source'])}}}"
        for i, a in enumerate(m.get("appendices") or [], start=1)
        if isinstance(a, dict) and a.get("source")
    )
    bib = m.get("bibliography")
    preamble_path = (package / m["preamble"]).resolve() if m.get("preamble") else None
    if m.get("bibliography_backend") == "biblatex":
        bibliography = "\\printbibliography[heading=bibintoc]"
        if preamble_path is not None:
            trimmed = _trim_bibliography_for(package, preamble_path, out)
            if trimmed is not None:
                preamble_path, note = trimmed
                done.append(note)
    elif bib:
        bibliography = (f"\\bibliographystyle{{{m.get('bibliography_style', 'plain')}}}\n"
                        f"\\bibliography{{{rel(bib).removesuffix('.bib')}}}")
    else:
        bibliography = "% no `bibliography:` in thesis.yaml"
    preamble = (f"\\input{{{preamble_path}}}" if preamble_path is not None else THESIS_DEFAULT_PREAMBLE)
    tex = THESIS_TEMPLATE.format(
        preamble=preamble,
        today=date.today().isoformat(),
        title=_tex_escape(m.get("title", "")),
        candidate=_tex_escape(_candidate_name(m)),
        degree=_tex_escape(m.get("degree", "Doctor of Philosophy")),
        program=_tex_escape(m.get("program", "")),
        university=_tex_escape(m.get("university", "Western University")),
        abstract=rel(front.get("abstract")),
        lay_summary=rel(front.get("lay_summary")),
        genai_statement=rel(front.get("genai_statement")),
        coauthorship=(f"\\chapter*{{Co-Authorship Statement}}\\input{{{rel(front['coauthorship'])}}}"
                      if front.get("coauthorship") else ""),
        acknowledgements=(f"\\chapter*{{Acknowledgements}}\\input{{{rel(front['acknowledgements'])}}}"
                          if front.get("acknowledgements") else ""),
        chapters="\n\n".join(chapter_tex),
        bibliography=bibliography,
        appendices=appendices,
    )
    (out / "main.tex").write_text(tex, encoding="utf-8")
    done.append(f"wrote {BUILD_DIR}/main.tex")
    (out / CLAIM_MAP).write_text(thesis_claim_map(package, m), encoding="utf-8")
    done.append(f"wrote {BUILD_DIR}/{CLAIM_MAP}")
    if pdf:
        # Run from the package so that relative figure paths in the chapters
        # resolve as they did in the original thesis.
        done.append(_latexmk(package, Path(BUILD_DIR) / "main.tex", out))
    return done


_GRAPHICS_RE = re.compile(r"(\\includegraphics\s*(?:\[[^\]]*\])?\s*\{)([^}]+)(\})")

# biber 2.12 (TeX Live 2019) dies with a segmentation fault on an author
# field holding ``{\relax CP}``, which Zotero writes to protect initials. The
# trimmed copy drops the wrapper; a current TeX Live does not need this.
_RELAX_RE = re.compile(r"\{\\relax\s+([^{}]*)\}")

# A bibliography exported whole from a reference manager can run to tens of
# megabytes, and biber 2.12 (TeX Live 2019) crashes on one that size. Above
# this many bytes the build cites from a trimmed copy holding only the keys
# the chapters use.
BIB_TRIM_BYTES = 2_000_000
LATEXMK_TIMEOUT_S = 20 * 60
_CITE_RE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}")
_BIB_ENTRY_RE = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,")
_ADDBIB_RE = re.compile(r"\\addbibresource\s*\{([^}]+)\}")


def cite_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for mo in _CITE_RE.finditer(text):
        for k in mo.group(1).split(","):
            k = k.strip()
            if k and k != "*":
                keys.add(k)
    return keys


def bib_entries(text: str) -> dict[str, str]:
    """``{key: entry text}`` for every ``@type{key, ...}`` entry, braces balanced.
    ``@comment``, ``@preamble`` and ``@string`` blocks are skipped."""
    entries: dict[str, str] = {}
    for mo in _BIB_ENTRY_RE.finditer(text):
        if mo.group(1).lower() in ("comment", "preamble", "string"):
            continue
        start = text.index("{", mo.start())
        _, end = _balanced_arg(text, start)
        entries[mo.group(2)] = text[mo.start():end]
    return entries


def _trim_bibliography_for(package: Path, preamble_path: Path, out: Path) -> tuple[Path, str] | None:
    """When the ``\\addbibresource`` files are large, write ``build/cited.bib``
    with only the cited entries and a copy of the preamble that points at it.
    Returns ``(new_preamble_path, note)`` or ``None`` when nothing was done."""
    preamble = preamble_path.read_text(encoding="utf-8", errors="replace")
    resources = [preamble_path.parent / r.strip() for r in _ADDBIB_RE.findall(preamble)]
    resources = [r for r in resources if r.is_file()]
    if not resources or sum(r.stat().st_size for r in resources) < BIB_TRIM_BYTES:
        return None
    keys: set[str] = set()
    for p in list((package / "chapters").glob("*.tex")) + list((package / "front").glob("*.tex")) \
            + list((package / "appendices").glob("*.tex")):
        keys |= cite_keys(p.read_text(encoding="utf-8", errors="replace"))
    if not keys:
        return None
    found: dict[str, str] = {}
    for r in resources:
        for k, entry in bib_entries(r.read_text(encoding="utf-8", errors="replace")).items():
            if k in keys and k not in found:
                found[k] = entry
    cited = out / "cited.bib"
    body = "\n\n".join(found[k] for k in sorted(found))
    relaxed = len(_RELAX_RE.findall(body))
    body = _RELAX_RE.sub(r"\1", body)
    cited.write_text("% Written by `murmurent thesis build`: only the entries the chapters cite.\n\n"
                     + body + "\n", encoding="utf-8")
    new_preamble = _ADDBIB_RE.sub("", preamble) + f"\n\\addbibresource{{{cited.resolve()}}}\n"
    target = out / "preamble.tex"
    target.write_text(new_preamble, encoding="utf-8")
    missing = sorted(keys - set(found))
    note = (f"wrote {BUILD_DIR}/cited.bib: {len(found)} of {len(keys)} cited keys from "
            f"{', '.join(r.name for r in resources)} ({sum(r.stat().st_size for r in resources) // 1_000_000} MB)")
    if missing:
        note += f"; not found: {', '.join(missing[:8])}" + (" ..." if len(missing) > 8 else "")
    if relaxed:
        note += f"; unwrapped {relaxed} {{\\relax ...}} initials that crash biber 2.12"
    return target.resolve(), note


def _absolute_graphics(body: str, base: Path) -> str:
    """Make every relative ``\\includegraphics`` path absolute under ``base``,
    so a paper's figures still resolve once its body is included elsewhere."""

    def fix(mo: re.Match) -> str:
        p = mo.group(2).strip()
        if p.startswith("/"):
            return mo.group(0)
        return f"{mo.group(1)}{(base / p)}{mo.group(3)}"

    return _GRAPHICS_RE.sub(fix, body)


# --------------------------------------------------------------------------- #
# Adopting a monolithic thesis
# --------------------------------------------------------------------------- #

# SGPS front-matter chapter names, as they appear as ``\chapter*{...}`` in a
# thesis written from the SGPS template, mapped to the package's front files.
_FRONT_NAMES = {
    "abstract": "abstract",
    "summary for lay audience": "lay_summary",
    "lay summary": "lay_summary",
    "co-authorship statement": "coauthorship",
    "coauthorship statement": "coauthorship",
    "acknowledgements": "acknowledgements",
    "acknowledgments": "acknowledgements",
    "statement on the use of generative artificial intelligence": "genai_statement",
    "statement on the use of generative ai": "genai_statement",
    "genai statement": "genai_statement",
}
_CHAPTER_RE = re.compile(r"^[ \t]*\\chapter(\*?)\s*(\[[^\]]*\])?\s*\{", re.M)
_CONCLUSION_WORDS = ("discussion", "conclusion", "concluding", "general discussion")


def _balanced_arg(text: str, start: int) -> tuple[str, int]:
    """``text[start]`` is ``{``; return the argument inside the braces and the
    index after the closing brace."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return text[start + 1:], len(text)


def _plain_title(tex: str) -> str:
    """LaTeX to plain words: comments, commands, braces and math markers go;
    escaped characters become themselves, so the result can be re-escaped."""
    t = re.sub(r"(?<!\\)%.*", " ", tex)
    t = re.sub(r"\\(em|it|bf|tt|emph|textit|textbf|texttt)\b", "", t)
    t = re.sub(r"\\([#%&_$])", r"\1", t)
    t = t.replace("\\ ", " ")
    t = re.sub(r"\\[A-Za-z]+\s*", " ", t)
    t = re.sub(r"[{}~$]", " ", t)
    return re.sub(r"\s+", " ", t).strip().rstrip(".").strip()


# Chapters whose figures are not the candidate's own claims: no drafts there.
_NO_CLAIM_WORDS = ("background", "introduction", "methods", "literature")


def _slug(s: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:limit].rstrip("_") or "chapter"


def _split_chapters(body: str) -> list[tuple[bool, str, str]]:
    """Split a thesis body at every ``\\chapter``. Returns
    ``(starred, title, content)`` in order; text before the first chapter is
    returned with an empty title."""
    out: list[tuple[bool, str, str]] = []
    pos = 0
    pending: tuple[bool, str] | None = None
    for mo in _CHAPTER_RE.finditer(body):
        head = body[pos:mo.start()]
        if pending is None:
            out.append((False, "", head))
        else:
            out.append((pending[0], pending[1], head))
        title, after = _balanced_arg(body, mo.end() - 1)
        pending = (mo.group(1) == "*", title)
        pos = after
    if pending is None:
        out.append((False, "", body[pos:]))
    else:
        out.append((pending[0], pending[1], body[pos:]))
    return out


_CAPTION_RE = re.compile(r"\\caption\s*(\[[^\]]*\])?\s*\{")


def _draft_claims(content: str, prefix: str) -> list[dict[str, Any]]:
    """One draft claim per figure label, with the caption's first sentence as
    the text. The candidate rewrites them; the check warns on each until a
    script is named."""
    claims: list[dict[str, Any]] = []
    for k, mo in enumerate(re.finditer(r"\\label\{(fig:[^}]+)\}", content), start=1):
        label = mo.group(1)
        before = content[:mo.start()]
        cap = None
        for cm in _CAPTION_RE.finditer(before):
            cap = cm
        text = ""
        if cap is not None and mo.start() - cap.start() < 4000:
            raw, _ = _balanced_arg(content, cap.end() - 1)
            text = _plain_title(re.split(r"(?<=[.!?])\s", raw.strip(), maxsplit=1)[0])
        claims.append({"id": f"{prefix}.{k}", "text": text or f"(write the claim behind {label})",
                       "where": "", "figure": label, "code": "", "data": []})
    return claims


def adopt_thesis(tex_path: Path, target: Path, *, title: str = "", candidate: str = "",
                 lab: str | None = None) -> list[str]:
    """Turn one monolithic thesis ``.tex`` into a thesis package: the
    preamble kept as ``preamble.tex``, the SGPS front matter split into
    ``front/``, each ``\\chapter`` into ``chapters/NN_slug.tex`` with its kind
    inferred, a draft claim per figure, figures and bibliographies copied, and
    ``thesis.yaml`` written. Nothing in ``tex_path``'s folder is changed."""
    tex_path = Path(tex_path).resolve()
    target = Path(target)
    src_dir = tex_path.parent
    text = tex_path.read_text(encoding="utf-8", errors="replace")
    done: list[str] = []

    mo = re.search(r"\\begin\{document\}", text)
    if mo is None:
        raise PackageError(f"{tex_path.name} has no \\begin{{document}}")
    preamble, rest = text[:mo.start()], text[mo.end():]
    end = re.search(r"\\end\{document\}", rest)
    body = rest[:end.start()] if end else rest

    t = re.search(r"\\title\s*\{", preamble + body)
    if not title and t:
        title = _plain_title(_balanced_arg(preamble + body, t.end() - 1)[0])
    a = re.search(r"\\author\s*\{", preamble + body)
    if not candidate and a:
        candidate = _plain_title(_balanced_arg(preamble + body, a.end() - 1)[0])
    title = title or tex_path.stem.replace("_", " ")

    init_thesis(target, title=title, candidate=candidate, lab=lab)
    (target / "preamble.tex").write_text(
        "% Preamble kept by `murmurent thesis adopt` from " + tex_path.name + "\n"
        + re.sub(r"\\(title|author|date)\s*\{.*?\}\s*\n?", "", preamble, flags=re.S), encoding="utf-8")
    done.append("kept the preamble as preamble.tex")

    front_written: dict[str, str] = {}
    chapters: list[dict[str, Any]] = []
    n = 0
    for starred, ch_title, content in _split_chapters(body):
        content = re.sub(r"\\addcontentsline\{toc\}\{chapter\}\{[^}]*\}\s*", "", content)
        if not ch_title:
            continue  # pagenumbering, toc and such: the template regenerates them
        key = _FRONT_NAMES.get(_plain_title(ch_title).lower())
        if starred and key:
            rel_path = f"front/{key}.tex"
            (target / rel_path).write_text(content.strip() + "\n", encoding="utf-8")
            front_written[key] = rel_path
            done.append(f"front matter: {rel_path}")
            continue
        if starred:
            # An unnumbered chapter we do not know: keep it as an appendix.
            rel_path = f"appendices/{_slug(_plain_title(ch_title))}.tex"
            (target / rel_path).parent.mkdir(exist_ok=True)
            (target / rel_path).write_text(content.strip() + "\n", encoding="utf-8")
            chapters.append({"_appendix": True, "title": _plain_title(ch_title), "source": rel_path})
            continue
        n += 1
        plain = _plain_title(ch_title)
        if n == 1:
            kind = "introduction"
        elif any(w in plain.lower() for w in _CONCLUSION_WORDS) \
                and not any(c.get("kind") == "conclusion" for c in chapters):
            kind = "conclusion"
        else:
            kind = "chapter"
        rel_path = f"chapters/{n:02d}_{_slug(plain)}.tex"
        (target / rel_path).write_text(content.strip() + "\n", encoding="utf-8")
        entry: dict[str, Any] = {"kind": kind, "title": plain, "source": rel_path}
        if kind == "chapter":
            entry["claims"] = ([] if any(w in plain.lower() for w in _NO_CLAIM_WORDS)
                               else _draft_claims(content, f"c{n}"))
        chapters.append(entry)
        done.append(f"chapter {n} ({kind}): {rel_path}"
                    + (f", {len(entry.get('claims', []))} draft claims" if kind == "chapter" else ""))

    for key in ("abstract", "lay_summary", "genai_statement", "coauthorship"):
        if key not in front_written:
            done.append(f"front matter not found in the source: front/{key}.tex left as a stub")

    # Figures and bibliographies: copy what the chapters and preamble refer to.
    copied = 0
    for g in _GRAPHICS_RE.finditer(body):
        rel = g.group(2).strip()
        src = src_dir / rel
        if src.is_file() and not (target / rel).exists():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target / rel)
            copied += 1
    if copied:
        done.append(f"copied {copied} figure file(s)")
    bibs = re.findall(r"\\addbibresource\s*\{([^}]+)\}", preamble) \
        + [b.strip() for grp in re.findall(r"\\bibliography\s*\{([^}]+)\}", body) for b in grp.split(",")]
    backend = "biblatex" if re.search(r"\\addbibresource", preamble) else "bibtex"
    for b in bibs:
        name = b if b.endswith(".bib") else b + ".bib"
        if (src_dir / name).is_file() and not (target / name).exists():
            shutil.copy2(src_dir / name, target / name)
            done.append(f"copied {name}")
    for sty in src_dir.glob("*.sty"):
        if not (target / sty.name).exists():
            shutil.copy2(sty, target / sty.name)

    m = yaml.safe_load((target / THESIS_MANIFEST).read_text(encoding="utf-8"))
    m["title"] = title
    m["candidate"] = {"name": candidate}
    m["format"] = "monograph"
    m["preamble"] = "preamble.tex"
    m["front"] = {k: f"front/{k}.tex" for k in ("abstract", "lay_summary", "genai_statement", "coauthorship")}
    if "acknowledgements" in front_written:
        m["front"]["acknowledgements"] = front_written["acknowledgements"]
    m["chapters"] = [c for c in chapters if not c.get("_appendix")]
    m["appendices"] = [{"title": c["title"], "source": c["source"]} for c in chapters if c.get("_appendix")]
    m["bibliography"] = bibs[0] if bibs else ""
    m["bibliography_backend"] = backend
    (target / THESIS_MANIFEST).write_text(
        "# Written by `murmurent thesis adopt`. Chapter kinds were inferred; every claim is a\n"
        "# draft (one per figure) with no code yet. Fix both, then `murmurent thesis check`.\n"
        + yaml.safe_dump(m, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    done.append(f"wrote {THESIS_MANIFEST}: {len(m['chapters'])} chapters, "
                f"{sum(len(c.get('claims', [])) for c in m['chapters'])} draft claims")
    return done


# --------------------------------------------------------------------------- #
# The defence talk
# --------------------------------------------------------------------------- #

# Fixed slots of a defence talk, in minutes. What is left after these goes to
# the result chapters, in proportion to their claims. SGPS allows the
# candidate a 10 to 15 minute introduction when there is no public lecture;
# a program that asks for 20 minutes gets the default below.
TALK_FIXED = {
    "title": 0.5, "outline": 1.0, "introduction": 3.0,
    "conclusion": 2.5, "acknowledgements": 0.5,
}


@dataclass
class Slide:
    section: str
    title: str
    minutes: float
    body: list[str]
    notes: str
    figure: str | None = None
    evidence: str | None = None


def talk_plan(package: Path, *, minutes: int = 20, m: dict[str, Any] | None = None) -> list[Slide]:
    """One slide per claim, timed. The result is a plan a person edits, not a
    finished talk: the scribe writes the words, the artist redraws figures."""
    package = Path(package)
    m = m or read_thesis(package)
    chapters = chapters_of(package, m)
    intro = next((c for c in chapters if c.kind == "introduction"), None)
    concl = next((c for c in chapters if c.kind == "conclusion"), None)
    middle = [c for c in chapters if c.kind in ("paper", "chapter")]
    # Background, methods and supplementary chapters are not defended on the
    # clock: their claims become backup slides after the acknowledgements.
    results = [c for c in middle if not any(w in c.title.lower() for w in _BACKUP_WORDS)]
    backup = [c for c in middle if c not in results]

    slides: list[Slide] = []
    title = str(m.get("title", ""))
    slides.append(Slide("title", title, TALK_FIXED["title"],
                        [_candidate_name(m), str(m.get("program", "")), str(m.get("university", ""))],
                        "Say your name and the one-sentence version of the thesis."))
    slides.append(Slide("outline", "Outline", TALK_FIXED["outline"],
                        [f"{c.title} (Chapter {c.index})" for c in chapters],
                        "One line per chapter; say which chapters carry the two or three results you will defend."))
    if intro is not None:
        per = TALK_FIXED["introduction"] / 3
        slides.append(Slide("introduction", "The problem", per,
                            ["Why it matters, in one sentence a non-specialist follows",
                             "What was not known before this work"],
                            f"From Chapter {intro.index}. No methods yet."))
        slides.append(Slide("introduction", "The data and the setting", per,
                            ["What was measured, on what, how much"],
                            "One figure of the raw material beats a table."))
        slides.append(Slide("introduction", "Objectives", per,
                            [f"Objective {i}: ..." for i in range(1, max(2, len(results)) + 1)],
                            "Number them; the result slides refer back by number."))

    remaining = minutes - sum(TALK_FIXED.values())
    weights = [max(1, len(c.claims)) for c in results]
    total_w = sum(weights) or 1
    for c, w in zip(results, weights):
        share = remaining * w / total_w
        if c.claims:
            per = share / len(c.claims)
            for cl in c.claims:
                ev = " ; ".join(filter(None, [cl.get("code"), ", ".join(_as_list(cl.get("data")))]))
                slides.append(Slide(
                    f"chapter {c.index}", str(cl.get("text", "")), per,
                    ["What the figure shows, in one sentence", "What it does not show"],
                    f"Chapter {c.index}, claim {cl.get('id', '')}. Evidence: {ev or 'none listed'}."
                    + (f" Figure {cl['figure']}." if cl.get("figure") else ""),
                    figure=cl.get("figure"), evidence=ev or None,
                ))
        else:
            slides.append(Slide(f"chapter {c.index}", c.title, share,
                                ["Main result", "Why it holds"],
                                f"Chapter {c.index} lists no claims; add them to the manifest."))
    if concl is not None:
        slides.append(Slide("conclusion", "What the results mean together", TALK_FIXED["conclusion"] / 2,
                            ["Objective 1: ...", "Objective 2: ..."],
                            f"From Chapter {concl.index}. Return to the objectives slide, one line each."))
        slides.append(Slide("conclusion", "Limits and what comes next", TALK_FIXED["conclusion"] / 2,
                            ["The one limitation an examiner will raise first", "The next experiment"],
                            "Say the limitation before an examiner does."))
    slides.append(Slide("acknowledgements", "Acknowledgements", TALK_FIXED["acknowledgements"],
                        ["Supervisor, committee, collaborators, funding"], "Then stop."))
    for c in backup:
        for cl in c.claims:
            ev = " ; ".join(filter(None, [cl.get("code"), ", ".join(_as_list(cl.get("data")))]))
            slides.append(Slide("backup", str(cl.get("text", "")), 0.0,
                                ["Shown only if an examiner asks"],
                                f"Backup from Chapter {c.index} ({c.title}), claim {cl.get('id', '')}.",
                                figure=cl.get("figure"), evidence=ev or None))
    return slides


_BACKUP_WORDS = ("background", "method", "supplement", "appendix")


def format_talk_plan(slides: list[Slide], *, minutes: int) -> str:
    total = sum(s.minutes for s in slides)
    lines = [f"# Defence talk plan: {minutes} minutes, {len(slides)} slides", ""]
    lines.append("One slide per claim. The scribe writes the sentences; the artist redraws any "
                 "figure that was made for a page rather than a screen. Times are a budget, not a script.")
    lines.append("")
    lines.append("| # | Section | Slide | Minutes | Figure | Evidence |")
    lines.append("|---|---|---|---|---|---|")
    for i, s in enumerate(slides, start=1):
        lines.append(f"| {i} | {s.section} | {s.title} | {s.minutes:.1f} | {s.figure or ''} | {s.evidence or ''} |")
    lines.append("")
    lines.append(f"Total: {total:.1f} minutes.")
    result_slides = [s for s in slides if s.section.startswith("chapter")]
    fast = [s for s in result_slides if s.minutes < 0.75]
    if fast:
        lines.append("")
        lines.append(f"**Too many result slides for the time.** {len(fast)} result slides get under 45 seconds each. "
                     "Keep the claims an examiner will ask about; move the rest to backup slides after the acknowledgements.")
    return "\n".join(lines) + "\n"


_BEAMER_HEAD = r"""% Built by `murmurent thesis talk` on {today}: a timed skeleton, one slide per
% claim. Replace each placeholder; keep the \note timings until a rehearsal says
% otherwise.
\documentclass[aspectratio=169]{{beamer}}
\usetheme{{default}}
\usepackage{{graphicx}}
\setbeamertemplate{{navigation symbols}}{{}}
\setbeamertemplate{{footline}}[frame number]
\title{{{title}}}
\author{{{candidate}}}
\institute{{{program}, {university}}}
\date{{{defence}}}
\begin{{document}}
"""


def talk_tex(slides: list[Slide], m: dict[str, Any]) -> str:
    defence = (m.get("defence") or {}).get("date", "") if isinstance(m.get("defence"), dict) else ""
    out = [_BEAMER_HEAD.format(
        today=date.today().isoformat(), title=_tex_escape(m.get("title", "")),
        candidate=_tex_escape(_candidate_name(m)), program=_tex_escape(m.get("program", "")),
        university=_tex_escape(m.get("university", "Western University")), defence=_tex_escape(defence),
    )]
    for i, s in enumerate(slides, start=1):
        if s.section == "title":
            out.append("\\begin{frame}\\titlepage\\end{frame}\n")
            out.append(f"\\note{{{_tex_escape(s.notes)} ({s.minutes:.1f} min)}}\n")
            continue
        short = s.title if len(s.title) <= 90 else s.title[:87].rstrip() + "..."
        out.append(f"% slide {i}: {s.section}, {s.minutes:.1f} min")
        out.append(f"\\begin{{frame}}{{{_tex_escape(short)}}}")
        if s.figure:
            out.append(f"  % figure {s.figure}: \\includegraphics[width=0.8\\linewidth]{{figures/{s.figure}.png}}")
        if s.evidence:
            out.append(f"  % evidence: {s.evidence}")
        out.append("  \\begin{itemize}")
        for b in s.body:
            out.append(f"    \\item {_tex_escape(b)}")
        out.append("  \\end{itemize}")
        out.append("\\end{frame}")
        out.append(f"\\note{{{_tex_escape(s.notes)} ({s.minutes:.1f} min)}}\n")
    out.append("\\end{document}\n")
    return "\n".join(out)


def build_talk(package: Path, *, minutes: int = 20, pdf: bool = False) -> list[str]:
    package = Path(package)
    m = read_thesis(package)
    out = package / BUILD_DIR
    out.mkdir(exist_ok=True)
    slides = talk_plan(package, minutes=minutes, m=m)
    (out / "talk_plan.md").write_text(format_talk_plan(slides, minutes=minutes), encoding="utf-8")
    (out / "talk.tex").write_text(talk_tex(slides, m), encoding="utf-8")
    done = [f"planned {len(slides)} slides for {minutes} minutes",
            f"wrote {BUILD_DIR}/talk_plan.md", f"wrote {BUILD_DIR}/talk.tex"]
    if pdf:
        done.append(_latexmk(out, Path("talk.tex"), out))
    return done


# --------------------------------------------------------------------------- #
# Western (SGPS) paperwork
# --------------------------------------------------------------------------- #

PAPERWORK_SOURCES = [
    ("SGPS thesis pages", "https://grad.uwo.ca/academics/thesis/index.html"),
    ("SGPS formatting", "https://grad.uwo.ca/academics/thesis/formatting.html"),
    ("SGPS examination", "https://grad.uwo.ca/academics/thesis/examination.html"),
    ("SGPS timelines", "https://grad.uwo.ca/academics/thesis/timelines.html"),
    ("Procedure for Thesis Formats and Content (Senate)",
     "https://www.uwo.ca/univsec/pdf/academic_policies/grad_postdoc/thesis_procedures_format.pdf"),
    ("Veritas student instructions (Schulich copy)",
     "https://www.schulich.uwo.ca/biochem/about_us/forms/New%20Veritas%20Thesis%20Examination%20Portal%20-%20StudentInstructions.pdf"),
]
PAPERWORK_READ_ON = "2026-11-06"
THESIS_PROCEDURE = "thesis_examination"
PROCEDURES_DIR_NAME = "procedures"

# The steps below, as data. This is the SEED for an institution pack's
# ``procedures/thesis_examination.yaml`` (``murmurent institution init
# --seed-thesis``); once a pack exists, ``paperwork()`` reads the pack and
# these constants are not consulted. A centre that is not Western replaces
# the pack, not this code.
_SEED_STEPS: list[dict[str, Any]] = [
    {"title": "Supervisor confirms the thesis is ready for examination",
     "owner": "supervisor"},
    {"title": "Date, time and format of the defence agreed with the supervisor and examiners",
     "owner": "candidate"},
    {"title": "Proposed Examiner Form, to the Graduate Program Coordinator",
     "form": "Proposed Examiner Form", "owner": "candidate",
     "deadline": {"relative_to": "defence", "by": {"doctoral": -PHD_LEAD_WORKING_DAYS,
                                                   "masters": -MASTERS_LEAD_WORKING_DAYS},
                  "rule": "With the examination request, five working weeks before a doctoral "
                          "defence and three before a master's."}},
    {"title": "Thesis Examination Request Form, to the Graduate Program Coordinator "
              "(no signatures needed since June 2026)",
     "form": "Thesis Examination Request Form", "owner": "candidate",
     "deadline": {"relative_to": "defence", "by": {"doctoral": -PHD_LEAD_WORKING_DAYS,
                                                   "masters": -MASTERS_LEAD_WORKING_DAYS},
                  "rule": "Latest day for the examination request and the preliminary "
                          "submission in Veritas."}},
    {"title": "Preliminary submission in Veritas: log in to the Graduate Student Web Services "
              "Portal, open the Veritas Thesis Examination Portal, begin the submission "
              "(title, format, the formatting, copyright and publication confirmations), "
              "upload the thesis (.pdf or .docx) and the supplementary files, submit for "
              "preliminary examination (files lock after this)",
     "form": "Veritas Thesis Examination Portal", "owner": "candidate",
     "deadline": {"relative_to": "defence", "by": {"doctoral": -PHD_LEAD_WORKING_DAYS,
                                                   "masters": -MASTERS_LEAD_WORKING_DAYS},
                  "rule": "Same day as the examination request."}},
    {"title": "Complete the candidate approval request Veritas sends", "owner": "candidate"},
    {"title": "Supervisor confirms readiness; Graduate Chair approves the request",
     "owner": "supervisor, graduate chair"},
    {"title": "Examiners' preliminary reports", "owner": "examiners",
     "deadline": {"relative_to": "defence", "working_days": -5,
                  "rule": "Due five working days before the defence."}},
    {"title": "The defence: talk of 10 to 15 minutes when no public lecture is required, or "
              "the length the program sets; examiners question in rounds (about 15 to 20 "
              "minutes each, then 5 to 10); no personal devices", "owner": "candidate",
     "deadline": {"relative_to": "defence", "working_days": 0, "rule": "The defence date."}},
    {"title": "Revisions approved by the examiners who asked for them", "owner": "candidate"},
    {"title": "Final submission (Open Repository): final thesis uploaded with its metadata, "
              "embargo requested if needed, release for research purposes authorized, "
              "non-exclusive licence granted (Library and Archives Canada; copyright stays "
              "with the candidate), SGPS formatting review passed",
     "form": "Open Repository (Scholarship@Western)", "owner": "candidate",
     "deadline": {"relative_to": "defence", "working_days": 5,
                  "rule": "Within about one week after the defence, and by the last day of the "
                          "current term, or registration and fees continue into the next term."}},
]


def seed_thesis_procedure(read_on: str = PAPERWORK_READ_ON) -> dict[str, Any]:
    """The thesis examination procedure as pack data, from the constants at
    the top of this file. Written once into a new pack; edited there after."""
    return {
        "title": "Thesis examination (SGPS)",
        "read_on": read_on,
        "confirm_with": "the Graduate Program Coordinator, who is the only person who can "
                        "open the examination in Veritas",
        "constants": {
            "lay_summary_max_words": LAY_SUMMARY_MAX_WORDS,
            "abstract_max_words": dict(ABSTRACT_MAX_WORDS),
            "supplement_max_mb": SUPPLEMENT_MAX_MB,
            "lead_working_days": {"doctoral": PHD_LEAD_WORKING_DAYS, "masters": MASTERS_LEAD_WORKING_DAYS},
            "board_roles": {k: dict(v) for k, v in BOARD_ROLES.items()},
            "board_roles_optional": list(BOARD_ROLES_OPTIONAL),
        },
        "board_text": {
            "doctoral": "Doctoral boards (SGPS regulation 8.4): one External Examiner from another "
                        "university, one University Examiner from another Western department, and two "
                        "Program Examiners; a Knowledge Keeper may be added. The supervisor attends but "
                        "does not vote.",
            "masters": "Master's boards (SGPS regulation 8.4): no external examiner; at least one "
                       "examiner from outside the program, the rest set by the program. Confirm the "
                       "composition with the Graduate Program Coordinator.",
        },
        "steps": [dict(s) for s in _SEED_STEPS],
        "sources": [{"name": n, "source": u, "date_read": read_on} for n, u in PAPERWORK_SOURCES],
    }


def _thesis_procedure() -> tuple[dict[str, Any], Any | None]:
    """The procedure to use: the institution pack's, when a pack is found and
    holds one, else the seed. Returns ``(procedure, pack_or_None)``."""
    from . import institution as _inst

    root = _inst.find_pack()
    if root is not None:
        try:
            pack = _inst.load_pack(root)
        except _inst.PackError:
            pack = None
        if pack is not None and THESIS_PROCEDURE in pack.procedures:
            return pack.procedures[THESIS_PROCEDURE], pack
    return seed_thesis_procedure(), None


def working_days_before(day: date, n: int, holidays: set[date] | None = None) -> date:
    """``n`` working days (Monday to Friday) before ``day``, skipping
    ``holidays`` when given. Without a pack no holidays are known, so the
    real deadline may be a day or two earlier."""
    holidays = holidays or set()
    d = day
    left = n
    while left > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            left -= 1
    return d


def _dir_size_mb(root: Path) -> float:
    total = 0
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts and BUILD_DIR not in p.parts:
            total += p.stat().st_size
    return total / 1e6


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")


def paperwork(package: Path, m: dict[str, Any] | None = None) -> str:
    """The submission checklist, pre-filled from the manifest. What the
    manifest cannot know is left as a box to tick."""
    package = Path(package)
    m = m or read_thesis(package)
    rep = check_thesis(package)
    degree = str(m.get("degree", "Doctor of Philosophy"))
    level = degree_level(degree)
    doctoral = level == "doctoral"
    proc, pack = _thesis_procedure()
    consts = proc.get("constants") or {}
    lead_days = consts.get("lead_working_days") or {}
    lead = int(lead_days.get(level, PHD_LEAD_WORKING_DAYS if doctoral else MASTERS_LEAD_WORKING_DAYS))
    abstract_max = int((consts.get("abstract_max_words") or {}).get(level, ABSTRACT_MAX_WORDS[level]))
    lay_max = int(consts.get("lay_summary_max_words") or LAY_SUMMARY_MAX_WORDS)
    supplement_max = int(consts.get("supplement_max_mb") or SUPPLEMENT_MAX_MB)
    board_roles = (consts.get("board_roles") or {}).get(level) or BOARD_ROLES[level]
    read_on = str(proc.get("read_on") or PAPERWORK_READ_ON)
    holidays = set(pack.holiday_dates()) if pack is not None else set()
    where_from = (f"the `{pack.unique_name}` institution pack ({pack.root})" if pack is not None
                  else "the seed built into murmurent; no institution pack found")
    front = m.get("front") or {}
    defence = m.get("defence") if isinstance(m.get("defence"), dict) else {}
    examiners = [e for e in (m.get("examiners") or []) if isinstance(e, dict)]

    def val(x: Any, missing: str = "**[missing]**") -> str:
        return str(x) if x not in (None, "", [], {}) else missing

    def box(ok: bool | None, text: str) -> str:
        mark = "x" if ok else " "
        return f"- [{mark}] {text}"

    lines = [f"# Submission paperwork: {m.get('title', '')}", ""]
    lines.append(f"{m.get('university', 'Western University')}, School of Graduate and Postdoctoral Studies (SGPS). "
                 f"Requirements as read on {read_on}; confirm anything dated with "
                 f"{proc.get('confirm_with', 'the Graduate Program Coordinator')}. "
                 f"Procedure from {where_from}.")
    lines.append("")
    lines.append("## The thesis")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for k, v in (("Title", m.get("title")), ("Candidate", _candidate_name(m)),
                 ("Supervisor", m.get("supervisor")), ("Degree", degree),
                 ("Program", m.get("program")), ("Format", m.get("format")),
                 ("Keywords", ", ".join(_as_list(m.get("keywords"))) or None),
                 ("Sensitivity", _sensitivity(m.get("sensitivity")))):
        lines.append(f"| {k} | {val(v)} |")
    lines.append("")

    # Timeline
    lines.append("## Timeline")
    lines.append("")
    ddate = defence.get("date")
    if ddate:
        try:
            d = datetime.strptime(str(ddate), "%Y-%m-%d").date()
            prelim = working_days_before(d, lead, holidays)
            lines.append(f"Proposed defence: **{d.isoformat()}** ({defence.get('format', 'format not set')}).")
            lines.append("")
            holiday_note = ("the pack's holidays are skipped" if pack is not None
                            else "statutory holidays are not counted, so aim earlier")
            lines.append(f"- Latest day for the Thesis Examination Request Form and the preliminary "
                         f"submission in Veritas: **{prelim.isoformat()}** ({lead} working days before; "
                         f"{holiday_note}).")
            lines.append("- Examiners' preliminary reports: due 5 working days before the defence "
                         f"(**{working_days_before(d, 5, holidays).isoformat()}**).")
            lines.append("- Final submission: within about one week after the defence, and by the last day "
                         "of the current term, or registration and fees continue into the next term.")
        except ValueError:
            lines.append(f"`defence.date` is `{ddate}`; write it as YYYY-MM-DD.")
    else:
        lines.append("No `defence.date:` in thesis.yaml. Add it to get the deadlines; the rule is "
                     f"{lead} working days between the examination request and the defence.")
    lines.append("")

    # Board
    lines.append("## Examination board")
    lines.append("")
    lines.append(str((proc.get("board_text") or {}).get(level) or seed_thesis_procedure()["board_text"][level]))
    lines.append("")
    counts: dict[str, int] = {}
    for e in examiners:
        counts[str(e.get("role", ""))] = counts.get(str(e.get("role", "")), 0) + 1
    if examiners:
        lines.append("| Role | Name | Affiliation |")
        lines.append("|---|---|---|")
        for e in examiners:
            lines.append(f"| {e.get('role', '')} | {val(e.get('name'))} | {val(e.get('affiliation'))} |")
        lines.append("")
    for role, n in board_roles.items():
        have = counts.get(role, 0)
        lines.append(box(have >= n, f"{n} {role} examiner(s): {have} listed"))
    lines.append("")

    # Before the preliminary submission
    lines.append("## Before the preliminary submission")
    lines.append("")
    lines.append(box(None, "Supervisor confirms the thesis is ready for examination"))
    lines.append(box(None, "Date, time and format of the defence agreed with the supervisor and examiners"))
    lines.append(box(bool(examiners), "Proposed Examiner Form, to the Graduate Program Coordinator"))
    lines.append(box(None, "Thesis Examination Request Form, to the Graduate Program Coordinator (no signatures needed since June 2026)"))
    lines.append("")

    # The document
    lines.append("## The document")
    lines.append("")
    errs = {f.where for f in rep.errors}
    ok_front = "front" not in errs
    lines.append(box(ok_front, "`murmurent thesis check` passes "
                     f"({len(rep.errors)} error(s), {len(rep.warnings)} warning(s))"))
    for key, label in (("abstract", f"Abstract (at most {abstract_max} words)"),
                       ("lay_summary", f"Summary for Lay Audience (at most {lay_max} words)"),
                       ("genai_statement", "Statement on the use of generative AI (use or non-use, stated explicitly)"),
                       ("coauthorship", "Co-authorship statement (required when any article has co-authors)"),
                       ("acknowledgements", "Acknowledgements (optional)")):
        rel_path = front.get(key)
        present = bool(rel_path) and (package / rel_path).is_file() and _word_count(package / rel_path) > 0
        lines.append(box(present, f"{label}: {val(rel_path, 'not set')}"))
    published = [c for c in (m.get("chapters") or []) if isinstance(c, dict) and c.get("kind") == "paper"]
    for c in published:
        try:
            pm = read_paper((package / c["package"]).resolve())
        except (PackageError, KeyError):
            pm = {}
        if pm.get("status") == "published":
            lines.append(box(bool(c.get("permission")) and (package / c["permission"]).is_file(),
                             f"Publisher's copyright release for {pm.get('title', c.get('package'))}: {val(c.get('permission'))}"))
    lines.append(box((package / BUILD_DIR / "main.pdf").is_file(),
                     "Thesis PDF built (`murmurent thesis build --pdf`); Veritas takes .pdf or .docx"))
    # Contact details must be removed, including from appendices and the CV.
    leaks: list[str] = []
    for p in list((package / "front").glob("*.tex")) + list((package / "chapters").glob("*.tex")) \
            + list((package / "appendices").glob("*")):
        if p.is_file() and p.suffix in (".tex", ".md", ".txt"):
            t = p.read_text(encoding="utf-8", errors="replace")
            if _EMAIL_RE.search(t) or _PHONE_RE.search(t):
                leaks.append(p.name)
    lines.append(box(not leaks, "No email addresses, phone numbers or signatures in the text, appendices or CV"
                     + (f" (found in: {', '.join(leaks)})" if leaks else "")))
    size = _dir_size_mb(package)
    lines.append(box(size <= supplement_max,
                     f"Each supplementary file at most {supplement_max} MB (package without build/ and .git: {size:.0f} MB)"))
    lines.append(box(None, "Supplementary files: the link to this package and how an examiner opens it"))
    lines.append("")

    # Veritas
    lines.append("## Preliminary submission (Veritas, from June 2026)")
    lines.append("")
    for step in ("Log in to the Graduate Student Web Services Portal and open the Veritas Thesis Examination Portal",
                 "Begin Thesis Submission: title, format, and the formatting, copyright and publication confirmations",
                 "Upload the thesis (.pdf or .docx) and the supplementary files",
                 "Submit for preliminary examination (files lock after this)",
                 "Complete the candidate approval request Veritas sends",
                 "Supervisor confirms readiness; Graduate Chair approves the request"):
        lines.append(box(None, step))
    lines.append("")

    # The defence
    lines.append("## The defence")
    lines.append("")
    lines.append(box(bool((package / BUILD_DIR / "talk.tex").is_file()),
                     "Talk drafted (`murmurent thesis talk`); 10 to 15 minutes when no public lecture is required, "
                     "or the length the program sets"))
    lines.append(box(None, "Examiners question in rounds (about 15 to 20 minutes each, then 5 to 10); no personal devices"))
    lines.append("")

    # Final submission
    lines.append("## Final submission (Open Repository)")
    lines.append("")
    for step in ("Revisions approved by the examiners who asked for them",
                 "Final thesis uploaded with its metadata; embargo requested if needed",
                 "Release for research purposes authorized",
                 "Non-exclusive licence granted (Library and Archives Canada); copyright stays with the candidate",
                 "SGPS formatting review passed"):
        lines.append(box(None, step))
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    for src in proc.get("sources") or []:
        if isinstance(src, dict):
            lines.append(f"- [{src.get('name', '')}]({src.get('source', '')}) (read {src.get('date_read', '?')})")
    if pack is not None:
        lines.append("")
        lines.append(f"Institution-specific steps are kept in `{PROCEDURES_DIR_NAME}/{THESIS_PROCEDURE}.yaml` of the "
                     f"pack; `murmurent institution walk {THESIS_PROCEDURE} --anchor <defence date>` lists them with dates, "
                     "and `murmurent institution refresh` re-reads their sources.")
    return "\n".join(lines) + "\n"


def build_paperwork(package: Path) -> list[str]:
    package = Path(package)
    out = package / BUILD_DIR
    out.mkdir(exist_ok=True)
    (out / "paperwork.md").write_text(paperwork(package), encoding="utf-8")
    return [f"wrote {BUILD_DIR}/paperwork.md"]


# --------------------------------------------------------------------------- #
# Scaffolding
# --------------------------------------------------------------------------- #

PAPER_CLAUDE_MD = """# {title}: a queryable paper package

This repository is a **paper package**: the manuscript, the code and data
behind each of its central claims, and a map between them (`paper.yaml`,
rendered to `build/claim_map.md` by `murmurent paper build`). Open it in
Claude Code and ask the `docent` to walk you through it: where a claim is
made, what evidence sits behind it, how to re-run it, and what the paper does
not address.

## Rules for a reader, reviewer or examiner

- **Read, do not change.** Nothing outside `build/` and `queries/` is written
  by a reader's session. If an analysis is re-run, its outputs go in `build/`.
- **Every answer carries a location**: a section or figure in the source, a
  file under `exp/`, or a data path. An answer with no location is a guess
  and is labelled one.
- **Questions are logged.** The docent appends each question and its answer to
  `queries/<your-handle>/<date>.md`. The log is append-only and is part of the
  record of the review.
- **Data stays where its tier puts it.** Paths under `immutable/`,
  `append_only/` and the other data-root folders are reached on the machine
  that holds them, never copied into this package.

## Where things are

| What | Where |
|---|---|
| Manuscript source | `{source}` |
| Claims and their evidence | `paper.yaml`, `build/claim_map.md` |
| Code that made each figure | `exp/<n>_<slug>/` |
| Small data | `data/` |
| Query log | `queries/` |

Start with: `murmurent paper check` then `murmurent paper build`.
"""

THESIS_CLAUDE_MD = """# {title}: a queryable thesis package

This repository is a **thesis package**: chapters that are paper packages
(each with its own `paper.yaml` mapping claims to code and data) or plain
chapters carrying their own claims, plus the candidate's introduction,
bridging text, conclusion and front matter (`thesis.yaml`).
`murmurent thesis build` writes `build/main.tex`, the thesis of record, and
`build/claim_map.md`, the map of every claim in every chapter.
`murmurent thesis talk` drafts the defence talk; `murmurent thesis paperwork`
writes the Western submission checklist.

Open it in Claude Code and ask the `docent`. It walks a candidate through
building and checking the package, and walks an examiner through reading it:
where a claim is made, what sits behind it, how to re-run it, and what the
thesis does not address.

## Rules for an examiner

- **Read, do not change.** Nothing outside `build/` and `queries/` is written
  by an examiner's session.
- **Every answer carries a location.** An answer with no location is labelled
  a guess.
- **Questions are logged** to `queries/<your-handle>/<date>.md`, append-only.
  The log is part of the record of the examination.
- **The PDF is the thesis of record.** This package supplements it; a
  disagreement between the two is a finding, and the PDF wins until fixed.
- **Data stays in its tier.** Protected data is reached on the server that
  holds it, never copied here.

## Where things are

| What | Where |
|---|---|
| Chapters and front matter | `thesis.yaml`, `chapters/`, `front/` |
| Paper packages | listed under `chapters:` with `kind: paper` |
| The assembled thesis | `build/main.tex` (and `build/main.pdf` after `--pdf`) |
| Every claim with its evidence | `build/claim_map.md` |
| The defence talk | `build/talk_plan.md`, `build/talk.tex` |
| Submission checklist | `build/paperwork.md` |
| Query log | `queries/` |

Start with: `murmurent thesis check` then `murmurent thesis build`.
"""

QUERIES_README = """# Query log

One file per reader per day, `<handle>/<YYYY-MM-DD>.md`, written by the
docent. Append only: a session adds to today's file and never edits an
earlier one. Each entry is the question as asked, the answer as given, and
the locations the answer rests on.
"""

_PAPER_YAML = """# Paper package manifest. `murmurent paper check` validates it;
# `murmurent paper build` renders build/claim_map.md from it.
paper: 1
title: {title}
authors:
  - name: {author}
status: in-prep          # in-prep | submitted | published
doi: ''
sensitivity: standard    # standard | restricted | protected
source: main.tex
# One entry per central claim. `code` is the script or folder that produces
# the evidence; `data` lists files inside the package or paths under the lab
# data root (immutable/..., append_only/...); `figure` is a \\label in the source.
claims:
  - id: c1
    text: ''
    where: Results
    figure: ''
    code: ''
    data: []
"""

_PAPER_MAIN_TEX = r"""\documentclass{article}
\usepackage{graphicx}
\title{%s}
\author{%s}
\begin{document}
\maketitle
\begin{abstract}
\end{abstract}
\section{Introduction}
\section{Methods}
\section{Results}
\section{Discussion}
\end{document}
"""

_THESIS_YAML = """# Thesis package manifest. `murmurent thesis check` validates it;
# `murmurent thesis build` assembles build/main.tex and build/claim_map.md;
# `murmurent thesis talk` and `murmurent thesis paperwork` draft the rest.
thesis: 1
title: {title}
candidate:
  name: {candidate}
supervisor: ''
degree: Doctor of Philosophy
program: ''
university: Western University
format: integrated-article   # or monograph: then use `kind: chapter` with claims
keywords: []
sensitivity: standard        # the highest tier of any chapter in it
defence:
  date: ''                   # YYYY-MM-DD; drives the deadlines in paperwork.md
  format: in-person          # in-person | hybrid | remote
examiners: []                # - {{role: external|university|program|knowledge_keeper, name, affiliation}}
front:
  abstract: front/abstract.tex
  lay_summary: front/lay_summary.tex        # at most 350 words (SGPS)
  genai_statement: front/genai_statement.tex
  coauthorship: front/coauthorship.tex
chapters:
  - kind: introduction
    title: Introduction
    source: chapters/01_introduction.tex
  # - kind: paper
  #   package: ../my_paper          # a paper package (its own repository)
  #   bridge: chapters/02_bridge.tex
  #   permission: permissions/my_paper.pdf   # required once published
  # - kind: chapter                  # a monograph chapter with its own claims
  #   title: ...
  #   source: chapters/03_results.tex
  #   claims:
  #     - {{id: c3.1, text: '', figure: '', code: exp/3_results/run_all.py, data: []}}
  - kind: conclusion
    title: Conclusion
    source: chapters/99_conclusion.tex
appendices: []
bibliography: ''
"""


def _marker(kind: str, lab: str | None) -> str:
    lines = ["murmurent: 1"]
    if lab:
        lines.append(f"lab: {lab}")
    lines += [f"ready_since: '{date.today().isoformat()}'", f"kind: {kind}", "agents: [docent]"]
    return "\n".join(lines) + "\n"


_GITIGNORE = "build/\n*.aux\n*.log\n*.out\n*.fls\n*.fdb_latexmk\n*.synctex.gz\n*.nav\n*.snm\n*.toc\n"


def init_paper(target: Path, *, title: str, author: str = "", lab: str | None = None) -> list[Path]:
    """Scaffold a paper package. Existing files are never overwritten."""
    target = Path(target)
    files = {
        PAPER_MANIFEST: _PAPER_YAML.format(title=title, author=author or "''"),
        "main.tex": _PAPER_MAIN_TEX % (title, author),
        "CLAUDE.md": PAPER_CLAUDE_MD.format(title=title, source="main.tex"),
        f"{QUERIES_DIR}/README.md": QUERIES_README,
        ".murmurent.yaml": _marker("paper", lab),
        ".gitignore": _GITIGNORE,
        "exp/README.md": "One folder per analysis, `<n>_<slug>/`, each with a `run_all.*` entry point.\n",
        "data/README.md": "Small files only. Anything large lives under the lab data root and is referenced by path.\n",
    }
    return _write_files(target, files)


def init_thesis(target: Path, *, title: str, candidate: str = "", lab: str | None = None) -> list[Path]:
    """Scaffold a thesis package. Existing files are never overwritten."""
    target = Path(target)
    files = {
        THESIS_MANIFEST: _THESIS_YAML.format(title=title, candidate=candidate or "''"),
        "CLAUDE.md": THESIS_CLAUDE_MD.format(title=title),
        f"{QUERIES_DIR}/README.md": QUERIES_README,
        ".murmurent.yaml": _marker("thesis", lab),
        ".gitignore": _GITIGNORE,
        "front/abstract.tex": "% Abstract: at most 350 words.\n",
        "front/lay_summary.tex": "% Summary for Lay Audience: at most 350 words.\n",
        "front/genai_statement.tex": (
            "% Required by SGPS: a high-level statement of how generative AI was or was not used.\n"
        ),
        "front/coauthorship.tex": "% Co-authorship statement: the candidate's contribution to each article.\n",
        "chapters/01_introduction.tex": "% Introduction: objectives, and how the chapters form one thesis.\n",
        "chapters/99_conclusion.tex": "% Conclusion: what the studies mean together, and what comes next.\n",
        "permissions/README.md": "Publisher copyright releases, one per published article.\n",
        "figures/README.md": "Figures redrawn for the talk go here, named after the claim's figure label.\n",
    }
    return _write_files(target, files)


def _write_files(target: Path, files: dict[str, str]) -> list[Path]:
    written: list[Path] = []
    for rel, content in files.items():
        path = target / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def find_package(start: Path | None = None) -> tuple[Path, str] | None:
    """Walk up from ``start`` to the nearest directory holding ``paper.yaml``
    or ``thesis.yaml``. Returns ``(dir, "paper"|"thesis")``."""
    current = (Path(start) if start else Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / THESIS_MANIFEST).is_file():
            return candidate, "thesis"
        if (candidate / PAPER_MANIFEST).is_file():
            return candidate, "paper"
    return None
