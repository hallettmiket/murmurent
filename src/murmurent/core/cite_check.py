"""
Purpose: Check the citations in a file against the registries that issued them
         (issue #225). Pulls every DOI, PMID and arXiv ID out of a ``.bib``,
         ``.tex``, ``.md`` or plain-text file, looks each one up, and says
         whether it exists, whether it is the paper the file says it is, and
         whether it has been retracted or carries an expression of concern.
         No AI is involved: the same file gives the same answer every time.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-23
Input: A file path. Lookups go to Crossref (DOIs, with Retraction Watch data),
       NCBI E-utilities (PMIDs), DataCite (arXiv and other DataCite DOIs) and
       the doi.org handle service (DOIs registered elsewhere).
Output: One :class:`CheckResult` per identifier, worst first, and a plain-text
        or JSON report from :func:`format_report`.

What it can and cannot tell you. It checks that an identifier is real, that it
names the paper the bibliography entry claims, and that the registries know of
no retraction. It cannot tell whether a paper supports the sentence that cites
it, or whether a number appears in it: that needs a reader (the bookworm, then
the adversary). In a ``.md`` or ``.tex`` file with no bibliography entry there
is no claimed title to compare, so the report prints the real title beside the
line for a reader to compare.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

# ── statuses, worst first ───────────────────────────────────────────────────
NOT_FOUND = "NOT FOUND"  # the registry says this identifier does not exist
MISMATCH = "MISMATCH"  # it exists, but is not the paper the entry claims
RETRACTED = "RETRACTED"
CONCERN = "CONCERN"  # an expression of concern is attached
UNRESOLVED = "UNRESOLVED"  # could not be checked; the reason is given
MATCH = "MATCH"  # exists, and title agrees with the entry
EXISTS = "EXISTS"  # exists; nothing claimed to compare it against

STATUS_ORDER = (NOT_FOUND, MISMATCH, RETRACTED, CONCERN, UNRESOLVED, MATCH, EXISTS)
#: Statuses that make ``murmurent cite check`` exit non-zero.
FAILING = frozenset({NOT_FOUND, MISMATCH, RETRACTED})

#: Normalised titles at least this similar count as the same paper.
TITLE_MATCH_RATIO = 0.8
#: A shorter title wholly inside the longer one (a dropped subtitle) counts as
#: the same paper only when it is at least this long, so "Introduction" does not.
MIN_CONTAINED_TITLE = 20
#: PubMed's esummary accepts up to this many IDs per request.
PMID_BATCH = 200
#: Seconds between requests to one service, to stay inside public rate limits.
REQUEST_SPACING = 0.34

CROSSREF = "https://api.crossref.org/works/"
DATACITE = "https://api.datacite.org/dois/"
HANDLE = "https://doi.org/api/handles/"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
USER_AGENT = "murmurent-cite-check (+https://github.com/hallettmiket/murmurent)"

RETRACTION_NOTE = (
    "A clean result means no retraction or expression of concern "
    "known to Crossref (which carries Retraction Watch) or PubMed."
)

# ── extraction patterns ─────────────────────────────────────────────────────
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>{}\[\]|\\,;]+)", re.IGNORECASE)
_PMID_RE = re.compile(
    r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d{4,9})\b", re.IGNORECASE
)
#: "PMID 1701851", and lists such as "PMIDs 22178968, 28710453 and 1701851".
_PMID_LIST_RE = re.compile(
    r"\bPMIDs?\s*:?\s*(\d{4,9}(?:\s*(?:,|;|and|&)\s*(?:PMID\s*:?\s*)?\d{4,9}\b)*)", re.IGNORECASE
)
_ARXIV_RE = re.compile(
    r"(?:\barXiv\s*:?\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE
)
_ARXIV_DOI_PREFIX = "10.48550/arxiv."
_CITE_RE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")
_BIBFILES_RE = re.compile(r"\\(?:bibliography|addbibresource)\{([^}]*)\}")


@dataclass(frozen=True)
class Claim:
    """One identifier found in a file, with what the file says it is."""

    kind: str  # "doi" | "pmid" | "arxiv"
    ident: str
    where: str  # "refs.bib: basset1990" or "notes.md:12"
    context: str = ""  # the line it was found on, for text files
    claimed_title: str = ""
    claimed_author: str = ""  # first author's family name, as written


@dataclass
class Record:
    """What a registry says an identifier is."""

    title: str = ""
    first_author: str = ""
    year: str = ""
    retracted: bool = False
    concern: bool = False
    source: str = ""  # "Crossref", "PubMed", "DataCite"
    notes: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    """The verdict on one :class:`Claim`."""

    claim: Claim
    status: str
    detail: str
    found_title: str = ""
    found_author: str = ""
    found_year: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out.update(out.pop("claim"))
        return out


class LookupFailed(Exception):
    """A registry could not be reached or gave an unreadable answer."""


#: ``get_json(url, params) -> dict | None``: ``None`` means HTTP 404.
JsonGetter = Callable[[str, dict], "dict | None"]


# ── extraction ──────────────────────────────────────────────────────────────


def _clean_doi(raw: str) -> str:
    """Trim punctuation a sentence or URL wrapped around a DOI."""
    doi = raw.rstrip(".)]}>'\"")
    # A closing bracket that is part of the DOI has its opener inside it.
    while doi.count("(") > doi.count(")") and raw[len(doi) :].startswith(")"):
        doi += ")"
    return doi


def extract_from_text(text: str, source: str, *, skip_comments: bool = False) -> list[Claim]:
    """Every DOI, PMID and arXiv ID in ``text``, with its line number.

    Parameters
    ----------
    text : str
        The file's contents.
    source : str
        The file name to report in ``Claim.where``.
    skip_comments : bool
        Ignore LaTeX comment lines (``%`` first).

    Returns
    -------
    list[Claim]
        In file order, one per identifier per line.
    """
    claims: list[Claim] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if skip_comments and line.lstrip().startswith("%"):
            continue
        context = line.strip()[:200]
        for m in _DOI_RE.finditer(line):
            doi = _clean_doi(m.group(1))
            if doi.lower().startswith(_ARXIV_DOI_PREFIX):
                claims.append(
                    Claim("arxiv", doi[len(_ARXIV_DOI_PREFIX) :], f"{source}:{n}", context)
                )
            else:
                claims.append(Claim("doi", doi, f"{source}:{n}", context))
        pmids = [m.group(1) for m in _PMID_RE.finditer(line)]
        for m in _PMID_LIST_RE.finditer(line):
            pmids += re.findall(r"\d{4,9}", m.group(1))
        for pmid in dict.fromkeys(pmids):
            claims.append(Claim("pmid", pmid, f"{source}:{n}", context))
        for m in _ARXIV_RE.finditer(line):
            claims.append(Claim("arxiv", m.group(1), f"{source}:{n}", context))
    return claims


def _bib_value(text: str, i: int) -> tuple[str, int]:
    """Read one BibTeX field value starting at ``text[i]``; return it and the end."""
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return "", i
    if text[i] == "{":
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[i + 1 : j], j + 1
            j += 1
        return text[i + 1 :], len(text)
    if text[i] == '"':
        j = i + 1
        while j < len(text) and not (text[j] == '"' and text[j - 1] != "\\"):
            j += 1
        return text[i + 1 : j], j + 1
    m = re.match(r"[^,}\s]+", text[i:])
    return (m.group(0), i + m.end()) if m else ("", i)


def parse_bib(text: str) -> dict[str, dict[str, str]]:
    """A minimal BibTeX reader: ``{key: {field: value}}``, field names lower-case.

    Enough for Zotero and Better BibTeX exports. ``@string``, ``@comment`` and
    ``@preamble`` blocks are skipped.
    """
    entries: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if m.group(1).lower() in {"string", "comment", "preamble"}:
            continue
        fields: dict[str, str] = {}
        i = m.end()
        while i < len(text):
            fm = re.compile(r"\s*([A-Za-z][\w-]*)\s*=").match(text, i)
            if not fm:
                break
            value, i = _bib_value(text, fm.end())
            fields[fm.group(1).lower()] = " ".join(value.split())
            sep = re.compile(r"\s*,?").match(text, i)
            i = sep.end() if sep else i
            if text[i : i + 1] == "}":
                break
        entries[m.group(2)] = fields
    return entries


def _first_author_family(author_field: str) -> str:
    """The first author's family name from a BibTeX ``author`` field."""
    first = re.split(r"\s+and\s+", author_field.strip(), maxsplit=1)[0].strip()
    if not first:
        return ""
    if first.startswith("{") and first.endswith("}"):
        return first[1:-1]  # a group author such as {The Cancer Genome Atlas Network}
    if "," in first:
        return first.split(",", 1)[0].strip()
    return first.split()[-1]


def claims_from_bib(
    entries: dict[str, dict[str, str]], source: str, keys: set[str] | None = None
) -> list[Claim]:
    """One claim per identifier in each entry (all entries, or only ``keys``)."""
    claims: list[Claim] = []
    for key, f in entries.items():
        if keys is not None and key not in keys:
            continue
        title = f.get("title", "")
        author = _first_author_family(f.get("author", ""))
        where = f"{source}: {key}"
        found: list[tuple[str, str]] = []
        if f.get("doi"):
            doi = _clean_doi(
                re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", f["doi"].strip(), flags=re.IGNORECASE)
            )
            if doi.lower().startswith(_ARXIV_DOI_PREFIX):
                found.append(("arxiv", doi[len(_ARXIV_DOI_PREFIX) :]))
            else:
                found.append(("doi", doi))
        if f.get("pmid"):
            found.append(("pmid", f["pmid"].strip()))
        if f.get("eprint") and f.get("archiveprefix", f.get("eprinttype", "")).lower() == "arxiv":
            found.append(("arxiv", re.sub(r"v\d+$", "", f["eprint"].strip())))
        if not found:  # an identifier left only in a url or note field
            for c in extract_from_text(" ".join((f.get("url", ""), f.get("note", ""))), source):
                found.append((c.kind, c.ident))
        for kind, ident in dict.fromkeys(found):
            claims.append(Claim(kind, ident, where, "", title, author))
    return claims


def extract_claims(path: Path) -> list[Claim]:
    """Every identifier in the file at ``path``, read according to its type.

    A ``.tex`` file contributes its inline identifiers plus the bibliography
    entries it cites, from the ``\\bibliography{}`` or ``\\addbibresource{}``
    files beside it.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".bib":
        return claims_from_bib(parse_bib(text), path.name)
    if suffix != ".tex":
        return extract_from_text(text, path.name)
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("%"))
    claims = extract_from_text(text, path.name, skip_comments=True)
    cited = {k.strip() for m in _CITE_RE.finditer(body) for k in m.group(1).split(",")}
    for m in _BIBFILES_RE.finditer(body):
        for name in m.group(1).split(","):
            bib = path.parent / (
                name.strip() if name.strip().endswith(".bib") else f"{name.strip()}.bib"
            )
            if bib.is_file():
                entries = parse_bib(bib.read_text(encoding="utf-8", errors="replace"))
                claims += claims_from_bib(entries, bib.name, cited or None)
    return claims


# ── comparison ──────────────────────────────────────────────────────────────


def normalise(text: str) -> str:
    """Lower-case, accents and LaTeX markup removed, punctuation to spaces."""
    text = re.sub(r"\\[a-zA-Z]+\s*", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"<[^>]+>", " ", text)  # Crossref titles can carry <i>, <sub>
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def titles_match(claimed: str, found: str) -> bool:
    """True when two titles name the same paper, allowing for a dropped subtitle."""
    a, b = normalise(claimed), normalise(found)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= MIN_CONTAINED_TITLE and short in long_:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= TITLE_MATCH_RATIO


def authors_match(claimed: str, found: str) -> bool:
    """True when the claimed first-author family name appears in the found one."""
    a, b = normalise(claimed), normalise(found)
    return not a or not b or a in b or b in a


# ── lookups ─────────────────────────────────────────────────────────────────


def http_get_json(url: str, params: dict) -> dict | None:
    """GET ``url`` and parse JSON; ``None`` on 404, :class:`LookupFailed` otherwise."""
    import httpx

    try:
        r = httpx.get(
            url,
            params=params,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        raise LookupFailed(f"could not reach {httpx.URL(url).host} ({type(exc).__name__})") from exc
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise LookupFailed(f"{httpx.URL(url).host} answered HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as exc:
        raise LookupFailed(f"{httpx.URL(url).host} sent something that is not JSON") from exc


class Resolver:
    """Looks identifiers up. ``get_json`` and ``sleep`` are injectable for tests."""

    def __init__(
        self,
        get_json: JsonGetter = http_get_json,
        sleep: Callable[[float], None] = time.sleep,
        ncbi_api_key: str | None = None,
    ) -> None:
        self.get_json = get_json
        self.sleep = sleep
        self.ncbi_api_key = (
            ncbi_api_key if ncbi_api_key is not None else os.environ.get("NCBI_API_KEY", "")
        )
        self._last: dict[str, float] = {}

    def _get(self, service: str, url: str, params: dict | None = None) -> dict | None:
        wait = self._last.get(service, 0.0) + REQUEST_SPACING - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        try:
            return self.get_json(url, params or {})
        finally:
            self._last[service] = time.monotonic()

    def pmids(self, ids: list[str]) -> dict[str, Record | None | LookupFailed]:
        """Look up PMIDs in batches; ``None`` means PubMed has no such record."""
        out: dict[str, Record | None | LookupFailed] = {}
        for start in range(0, len(ids), PMID_BATCH):
            batch = ids[start : start + PMID_BATCH]
            params = {"db": "pubmed", "retmode": "json", "id": ",".join(batch)}
            if self.ncbi_api_key:
                params["api_key"] = self.ncbi_api_key
            try:
                data = self._get("ncbi", ESUMMARY, params) or {}
                result = data["result"]
            except (LookupFailed, KeyError, TypeError) as exc:
                failure = (
                    exc
                    if isinstance(exc, LookupFailed)
                    else LookupFailed("PubMed sent an answer that could not be read")
                )
                out.update({i: failure for i in batch})
                continue
            for pmid in batch:
                rec = result.get(pmid)
                out[pmid] = None if not rec or "error" in rec else _pubmed_record(rec)
        return out

    def doi(self, doi: str) -> Record | None:
        """Crossref, then DataCite, then the doi.org handle service."""
        data = self._get("crossref", CROSSREF + quote(doi, safe="/"))
        if data is not None:
            return _crossref_record(data.get("message") or {})
        record = self._datacite(doi)
        if record is not None:
            return record
        handle = self._get("doi.org", HANDLE + quote(doi, safe="/"))
        if handle is not None and handle.get("responseCode") == 1:
            raise LookupFailed(
                "registered, but with neither Crossref nor DataCite, "
                "so its title and retraction status could not be checked"
            )
        return None

    def arxiv(self, arxiv_id: str) -> Record | None:
        """arXiv IDs through their DataCite DOI."""
        record = self._datacite(f"10.48550/arXiv.{arxiv_id}")
        if record is not None:
            record.notes.append("arXiv withdrawals are not checked")
        return record

    def _datacite(self, doi: str) -> Record | None:
        data = self._get("datacite", DATACITE + quote(doi, safe="/"))
        if data is None:
            return None
        attrs = (data.get("data") or {}).get("attributes") or {}
        titles = attrs.get("titles") or [{}]
        creators = attrs.get("creators") or [{}]
        return Record(
            title=titles[0].get("title", ""),
            first_author=creators[0].get("familyName") or creators[0].get("name", ""),
            year=str(attrs.get("publicationYear") or ""),
            source="DataCite",
            notes=["DataCite carries no retraction data"],
        )


def _pubmed_record(rec: dict) -> Record:
    authors = rec.get("authors") or []
    name = authors[0].get("name", "") if authors else ""
    # PubMed writes "Basset P": the family name is everything before the initials.
    family = " ".join(name.split()[:-1]) if len(name.split()) > 1 else name
    refs = rec.get("references") or []
    reftypes = {str(r.get("reftype", "")).lower() for r in refs}
    pubtypes = {str(p).lower() for p in rec.get("pubtype") or []}
    return Record(
        title=str(rec.get("title", "")).rstrip("."),
        first_author=family,
        year=str(rec.get("pubdate", ""))[:4],
        retracted="retracted publication" in pubtypes or "retraction in" in reftypes,
        concern="expression of concern in" in reftypes,
        source="PubMed",
    )


def _crossref_record(msg: dict) -> Record:
    titles = msg.get("title") or [""]
    authors = msg.get("author") or [{}]
    first = authors[0]
    parts = ((msg.get("issued") or {}).get("date-parts") or [[None]])[0]
    updates = {str(u.get("type", "")).lower() for u in msg.get("updated-by") or []}
    title = titles[0] if titles else ""
    return Record(
        title=title,
        first_author=first.get("family") or first.get("name", ""),
        year=str(parts[0] or "") if parts else "",
        retracted="retraction" in updates or title.upper().startswith("RETRACTED"),
        concern="expression_of_concern" in updates,
        source="Crossref",
    )


# ── checking ────────────────────────────────────────────────────────────────


def _judge(claim: Claim, record: Record | None) -> CheckResult:
    if record is None:
        registry = {"pmid": "PubMed", "arxiv": "arXiv (via DataCite)"}.get(claim.kind, "doi.org")
        return CheckResult(claim, NOT_FOUND, f"{registry} has no record of this identifier")
    found = dict(found_title=record.title, found_author=record.first_author, found_year=record.year)
    notes = list(record.notes)
    if (
        claim.claimed_author
        and record.first_author
        and not authors_match(claim.claimed_author, record.first_author)
    ):
        notes.append(f"first author is {record.first_author}, not {claim.claimed_author}")
    flags = [
        w
        for w, on in (
            ("retracted", record.retracted),
            ("carries an expression of concern", record.concern),
        )
        if on
    ]
    if claim.claimed_title and not titles_match(claim.claimed_title, record.title):
        detail = f"{record.source} says this is a different paper"
        if flags:
            detail += f" (which is also {' and '.join(flags)})"
        return CheckResult(claim, MISMATCH, "; ".join([detail, *notes]), **found)
    if record.retracted:
        return CheckResult(
            claim, RETRACTED, "; ".join([f"{record.source} lists a retraction", *notes]), **found
        )
    if record.concern:
        return CheckResult(
            claim,
            CONCERN,
            "; ".join([f"{record.source} lists an expression of concern", *notes]),
            **found,
        )
    if claim.claimed_title:
        return CheckResult(
            claim, MATCH, "; ".join([f"title agrees ({record.source})", *notes]), **found
        )
    return CheckResult(
        claim,
        EXISTS,
        "; ".join(
            [f"exists ({record.source}); compare the title with the sentence citing it", *notes]
        ),
        **found,
    )


def check_claims(claims: list[Claim], resolver: Resolver | None = None) -> list[CheckResult]:
    """Look every claim up once per distinct identifier; return results worst first."""
    resolver = resolver or Resolver()
    lookups: dict[tuple[str, str], Record | None | LookupFailed] = {}
    pmids = list(dict.fromkeys(c.ident for c in claims if c.kind == "pmid"))
    if pmids:
        for pmid, rec in resolver.pmids(pmids).items():
            lookups[("pmid", pmid)] = rec
    for c in claims:
        key = (c.kind, c.ident.lower())
        if c.kind == "pmid" or key in lookups:
            continue
        try:
            lookups[key] = resolver.doi(c.ident) if c.kind == "doi" else resolver.arxiv(c.ident)
        except LookupFailed as exc:
            lookups[key] = exc
    results = []
    for c in claims:
        rec = lookups[("pmid", c.ident) if c.kind == "pmid" else (c.kind, c.ident.lower())]
        if isinstance(rec, LookupFailed):
            results.append(CheckResult(c, UNRESOLVED, str(rec)))
        else:
            results.append(_judge(c, rec))
    return sorted(results, key=lambda r: STATUS_ORDER.index(r.status))


def check_file(path: str | Path, resolver: Resolver | None = None) -> list[CheckResult]:
    """Extract and check every identifier in the file at ``path``."""
    return check_claims(extract_claims(Path(path)), resolver)


# ── reporting ───────────────────────────────────────────────────────────────


def format_report(results: list[CheckResult], *, as_json: bool = False) -> str:
    """Plain text for a person, or JSON for an agent."""
    if as_json:
        return json.dumps(
            {"results": [r.to_dict() for r in results], "note": RETRACTION_NOTE}, indent=2
        )
    if not results:
        return "No DOIs, PMIDs or arXiv IDs found."
    counts = {s: sum(r.status == s for r in results) for s in STATUS_ORDER}
    lines = [", ".join(f"{n} {s}" for s, n in counts.items() if n), ""]
    for r in results:
        c = r.claim
        lines.append(f"{r.status:<10} {c.kind.upper()} {c.ident}  ({c.where})")
        if c.claimed_title:
            lines.append(f"           claimed: {c.claimed_title}")
        if r.found_title:
            who = ", ".join(x for x in (r.found_author, r.found_year) if x)
            lines.append(f"           actual:  {r.found_title}" + (f" ({who})" if who else ""))
        if c.context and not c.claimed_title:
            lines.append(f"           line:    {c.context}")
        lines.append(f"           {r.detail}")
    lines += ["", RETRACTION_NOTE]
    return "\n".join(lines)


__all__ = [
    "NOT_FOUND",
    "MISMATCH",
    "RETRACTED",
    "CONCERN",
    "UNRESOLVED",
    "MATCH",
    "EXISTS",
    "STATUS_ORDER",
    "FAILING",
    "Claim",
    "Record",
    "CheckResult",
    "LookupFailed",
    "Resolver",
    "extract_from_text",
    "parse_bib",
    "claims_from_bib",
    "extract_claims",
    "normalise",
    "titles_match",
    "authors_match",
    "check_claims",
    "check_file",
    "format_report",
    "http_get_json",
]
