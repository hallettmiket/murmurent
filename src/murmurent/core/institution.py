"""
Purpose: The institution pack: a folder of dated, sourced facts about one
         institution (offices, calendar, courses, procedures, letterhead)
         that the ``clerk`` agent answers from and nothing else (issue #291).
         Load and validate a pack, say how old a fact is, and do the clerk's
         three jobs: check a document against the directory and letterhead,
         compute a date N working days away without landing on a holiday,
         and walk a procedure to its next steps. ``refresh`` re-reads each
         fact from its source, within the pack's own domains only.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: ``institution/<unique_name>/`` (``institution.yaml``, ``directory.yaml``,
       ``calendar.yaml``, ``courses.yaml``, ``procedures/*.yaml``,
       ``templates/*.yaml``). Found through ``$MURMURENT_INSTITUTION_PACK``
       (a pack directory), else ``$MURMURENT_INSTITUTION_ROOT`` or
       ``<commons>/institution/`` plus the centre's ``unique_name``.
Output: Pure functions returning dataclasses and strings; ``refresh`` with
        ``apply=True`` rewrites the pack's YAML files in place.

A pack is deployment content, kept out of the public release the way
``rules/local/`` is. The schema here is what ships; ``institution/example/``
is the one pack that ships with it, for tests and as a starting point.
"""

from __future__ import annotations

import html as _html
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from .commons import commons_root

PACK_META = "institution.yaml"
DIRECTORY_FILE = "directory.yaml"
CALENDAR_FILE = "calendar.yaml"
COURSES_FILE = "courses.yaml"
FACTS_FILE = "facts.yaml"       # what the clerk looked up: question, answer, source, date_read
PROCEDURES_DIR = "procedures"
POLICIES_DIR = "policies"      # rules read from the institution's pages, applied to documents (a syllabus)
TEMPLATES_DIR = "templates"
LETTERHEAD_FILE = "letterhead.yaml"

DEFAULT_MAX_FACT_AGE_DAYS = 180
FETCH_TIMEOUT_SECONDS = 30
USER_AGENT = "murmurent-institution-refresh"

# Every fact in a pack carries these two, or validation refuses it.
FACT_PROVENANCE = ("source", "date_read")


class PackError(Exception):
    """A pack that cannot be read at all (missing, malformed meta)."""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class Fact:
    """One sourced, dated statement from a pack file."""
    kind: str                 # office | holiday | term | deadline | course | step | letterhead
    key: str                  # the office name, the holiday name, the course code, ...
    data: dict[str, Any]
    file: Path
    path: str                 # YAML path, for messages

    @property
    def source(self) -> str:
        return str(self.data.get("source") or "")

    @property
    def date_read(self) -> date | None:
        return _parse_date(self.data.get("date_read"))


@dataclass
class Pack:
    root: Path
    meta: dict[str, Any]
    offices: list[dict[str, Any]]
    calendar: dict[str, Any]
    courses: dict[str, Any]
    procedures: dict[str, dict[str, Any]]
    templates: dict[str, dict[str, Any]]
    learned: list[dict[str, Any]] = field(default_factory=list)   # facts.yaml: the clerk's memory of lookups
    policies: dict[str, dict[str, Any]] = field(default_factory=dict)   # policies/<name>.yaml: rules with source and date

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.root.name)

    @property
    def unique_name(self) -> str:
        return str(self.meta.get("unique_name") or self.root.name)

    @property
    def domains(self) -> list[str]:
        return [str(d).lower().lstrip(".") for d in (self.meta.get("domains") or [])]

    @property
    def deny_hosts(self) -> list[str]:
        """Hosts inside the domains that are never read: intranets behind a login."""
        return [str(d).lower().lstrip(".") for d in (self.meta.get("deny_hosts") or [])]

    @property
    def max_fact_age_days(self) -> int:
        try:
            return int(self.meta.get("max_fact_age_days") or DEFAULT_MAX_FACT_AGE_DAYS)
        except (TypeError, ValueError):
            return DEFAULT_MAX_FACT_AGE_DAYS

    # -- lookups -----------------------------------------------------------

    def holidays(self) -> list[dict[str, Any]]:
        return [h for h in (self.calendar.get("holidays") or []) if isinstance(h, dict)]

    def holiday_dates(self) -> dict[date, str]:
        out: dict[date, str] = {}
        for h in self.holidays():
            d = _parse_date(h.get("date"))
            if d is not None:
                out[d] = str(h.get("name") or "holiday")
        return out

    def terms(self) -> list[dict[str, Any]]:
        return [t for t in (self.calendar.get("terms") or []) if isinstance(t, dict)]

    def deadlines(self) -> list[dict[str, Any]]:
        return [t for t in (self.calendar.get("deadlines") or []) if isinstance(t, dict)]

    def office(self, name: str) -> dict[str, Any] | None:
        """An office by name, matched loosely (case, punctuation, spacing)."""
        want = _norm(name)
        for o in self.offices:
            if _norm(str(o.get("office", ""))) == want:
                return o
        for o in self.offices:
            if want and want in _norm(str(o.get("office", ""))):
                return o
        return None

    def letterhead(self) -> dict[str, Any]:
        return self.templates.get("letterhead") or {}

    def facts(self) -> list[Fact]:
        """Every dated fact in the pack, for validation, staleness and refresh."""
        out: list[Fact] = []
        for i, o in enumerate(self.offices):
            out.append(Fact("office", str(o.get("office", f"#{i}")), o,
                            self.root / DIRECTORY_FILE, f"offices[{i}]"))
        for section, kind in (("holidays", "holiday"), ("terms", "term"), ("deadlines", "deadline")):
            for i, h in enumerate(self.calendar.get(section) or []):
                if isinstance(h, dict):
                    out.append(Fact(kind, str(h.get("name", f"#{i}")), h,
                                    self.root / CALENDAR_FILE, f"{section}[{i}]"))
        for i, c in enumerate(self.courses.get("cache") or []):
            if isinstance(c, dict):
                out.append(Fact("course", str(c.get("code", f"#{i}")), c,
                                self.root / COURSES_FILE, f"cache[{i}]"))
        for pname, proc in self.procedures.items():
            for i, s in enumerate(proc.get("sources") or []):
                if isinstance(s, dict):
                    out.append(Fact("procedure_source", f"{pname}: {s.get('name', f'#{i}')}", s,
                                    self.root / PROCEDURES_DIR / f"{pname}.yaml", f"sources[{i}]"))
        for tname, tpl in self.templates.items():
            if isinstance(tpl, dict) and "source" in tpl:
                out.append(Fact("template", tname, tpl,
                                self.root / TEMPLATES_DIR / f"{tname}.yaml", "."))
        for i, f in enumerate(self.learned):
            if isinstance(f, dict):
                out.append(Fact("fact", str(f.get("question", f"#{i}")), f, self.root / FACTS_FILE, f"facts[{i}]"))
        for pname, pol in self.policies.items():
            for i, r in enumerate(pol.get("rules") or []):
                if isinstance(r, dict):
                    out.append(Fact("rule", f"{pname}: {r.get('id', f'#{i}')}", r,
                                    self.root / POLICIES_DIR / f"{pname}.yaml", f"rules[{i}]"))
        return out


@dataclass
class Finding:
    """One line of a check: ``Correct``, ``Fix`` or ``Unknown``, located."""
    verdict: str              # Correct | Fix | Unknown
    what: str                 # the thing in the document this is about
    detail: str               # what the pack says, or what it does not hold
    source: str = ""
    date_read: str = ""
    age_note: str = ""

    def format(self) -> str:
        line = f"{self.verdict}: {self.what}. {self.detail}"
        if self.source:
            line += f" [{self.source}, read {self.date_read or '?'}]"
        if self.age_note:
            line += f" ({self.age_note})"
        return line


@dataclass
class StepDue:
    """A procedure step with its deadline resolved against an anchor date."""
    number: int
    title: str
    form: str
    due: date | None
    deadline_rule: str
    source: str
    done: bool = False
    note: str = ""


@dataclass
class Change:
    """What ``refresh`` found for one fact."""
    fact: Fact
    status: str               # confirmed | changed | unreachable | no_source | off_domain | unchecked
    detail: str = ""


# --------------------------------------------------------------------------- #
# Finding and loading a pack
# --------------------------------------------------------------------------- #


def institution_root(env: dict[str, str] | None = None) -> Path:
    """The folder that holds packs: ``$MURMURENT_INSTITUTION_ROOT``, else
    ``<commons>/institution``."""
    env = os.environ if env is None else env
    override = env.get("MURMURENT_INSTITUTION_ROOT")
    if override:
        return Path(override).expanduser()
    return commons_root() / "institution"


def list_packs(env: dict[str, str] | None = None) -> list[Path]:
    root = institution_root(env)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / PACK_META).is_file())


def find_pack(name: str | None = None, env: dict[str, str] | None = None) -> Path | None:
    """The pack directory to use, or ``None`` when there is none to use.

    Order: an explicit ``name`` (a pack directory, or a pack name under the
    institution root); ``$MURMURENT_INSTITUTION_PACK`` (a directory); the
    centre's ``unique_name`` from ``centre.md``. A machine with no centre and
    no variable set has no pack: callers then fall back to whatever seed they
    carry, and the clerk answers ``Unknown``. The example pack is never picked
    by default; it is a starting point, not an institution.
    """
    env = os.environ if env is None else env
    if name:
        p = Path(name).expanduser()
        if (p / PACK_META).is_file():
            return p
        p = institution_root(env) / name
        return p if (p / PACK_META).is_file() else None
    override = env.get("MURMURENT_INSTITUTION_PACK")
    if override:
        p = Path(override).expanduser()
        return p if (p / PACK_META).is_file() else None
    try:
        from .centre_init import read_centre
        profile = read_centre(env)
    except Exception:
        profile = None
    if profile is not None and profile.install_id:
        p = institution_root(env) / profile.install_id
        if (p / PACK_META).is_file():
            return p
    return None


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError(f"{path}: not valid YAML: {exc}") from exc


def load_pack(root: Path) -> Pack:
    root = Path(root)
    meta = _read_yaml(root / PACK_META)
    if not isinstance(meta, dict):
        raise PackError(f"{root / PACK_META}: missing or not a mapping; this is not a pack")
    directory = _read_yaml(root / DIRECTORY_FILE) or {}
    calendar = _read_yaml(root / CALENDAR_FILE) or {}
    courses = _read_yaml(root / COURSES_FILE) or {}
    facts_doc = _read_yaml(root / FACTS_FILE) or {}
    procedures: dict[str, dict[str, Any]] = {}
    pdir = root / PROCEDURES_DIR
    if pdir.is_dir():
        for p in sorted(pdir.glob("*.yaml")):
            doc = _read_yaml(p)
            if isinstance(doc, dict):
                procedures[p.stem] = doc
    policies: dict[str, dict[str, Any]] = {}
    poldir = root / POLICIES_DIR
    if poldir.is_dir():
        for p in sorted(poldir.glob("*.yaml")):
            doc = _read_yaml(p)
            if isinstance(doc, dict):
                policies[p.stem] = doc
    templates: dict[str, dict[str, Any]] = {}
    tdir = root / TEMPLATES_DIR
    if tdir.is_dir():
        for p in sorted(tdir.glob("*.yaml")):
            doc = _read_yaml(p)
            if isinstance(doc, dict):
                templates[p.stem] = doc
    return Pack(
        root=root,
        meta=meta,
        offices=[o for o in ((directory.get("offices") if isinstance(directory, dict) else None) or [])
                 if isinstance(o, dict)],
        calendar=calendar if isinstance(calendar, dict) else {},
        courses=courses if isinstance(courses, dict) else {},
        procedures=procedures,
        templates=templates,
        learned=[f for f in ((facts_doc.get("facts") if isinstance(facts_doc, dict) else None) or [])
                 if isinstance(f, dict)],
        policies=policies,
    )


# --------------------------------------------------------------------------- #
# Validation and staleness
# --------------------------------------------------------------------------- #


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


LOGIN_REFUSED = "behind a login; the clerk reads public pages only"
_LOGIN_PATH = re.compile(r"/(login|signin|sign-in|sso|saml|cas|auth|idp|oauth2?)(/|\?|$)", re.I)
_LOGIN_PAGE = re.compile(r'<input[^>]+type=["\']?password|<title[^>]*>[^<]*(sign in|log in|login|sign-in)[^<]*</title>', re.I)


def host_denied(url: str, deny: list[str] | tuple[str, ...]) -> bool:
    """True when the host is one of the pack's ``deny_hosts`` or a subdomain of one:
    the intranets (the learning system, HR self-service, the student information
    system, the sign-on hosts) that a wide domain rule would otherwise admit."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return True
    return any(host == d or host.endswith("." + d) for d in (x.lower().lstrip(".") for x in deny) if d)


def host_allowed(url: str, domains: list[str], *, require_https: bool = True,
                 deny: list[str] | tuple[str, ...] = ()) -> bool:
    """True when ``url`` is https (or http too, with ``require_https=False``,
    for a redirect the institution's own site issues), its host is one of
    ``domains`` or a subdomain of one, and it is not on the ``deny`` list.
    ``uwo.ca`` admits ``grad.uwo.ca``; it does not admit ``uwo.ca.example.com``;
    and a denied intranet host is refused however the domain rule reads."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in (("https",) if require_https else ("https", "http")) or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if host_denied(url, deny):
        return False
    return any(host == d or host.endswith("." + d) for d in domains if d)


def validate_pack(pack: Pack) -> list[str]:
    """Every problem that makes the pack unsafe to answer from. Empty is good."""
    problems: list[str] = []
    for key in ("name", "unique_name", "domains", "keeper"):
        if not pack.meta.get(key):
            problems.append(f"{PACK_META}: `{key}:` is required")
    if pack.meta.get("domains") and not isinstance(pack.meta.get("domains"), list):
        problems.append(f"{PACK_META}: `domains:` must be a list of host names")
    domains = pack.domains
    for f in pack.facts():
        where = f"{f.file.name} {f.path} ({f.key})"
        for key in FACT_PROVENANCE:
            if not f.data.get(key):
                problems.append(f"{where}: `{key}:` is required on every fact")
        if f.data.get("date_read") and f.date_read is None:
            problems.append(f"{where}: `date_read:` must be YYYY-MM-DD")
        if f.source and domains and not host_allowed(f.source, domains, deny=pack.deny_hosts):
            problems.append(f"{where}: source {f.source} is outside the pack's domains {domains}")
        if f.kind == "holiday" and _parse_date(f.data.get("date")) is None:
            problems.append(f"{where}: holiday `date:` must be YYYY-MM-DD")
        if f.kind == "term":
            for k in ("start", "end"):
                if f.data.get(k) and _parse_date(f.data.get(k)) is None:
                    problems.append(f"{where}: term `{k}:` must be YYYY-MM-DD")
        if f.kind == "office":
            for k in ("office", "person", "title"):
                if not f.data.get(k):
                    problems.append(f"{where}: `{k}:` is required on an office")
            for k in f.data:
                if k not in OFFICE_KEYS:
                    problems.append(f"{where}: `{k}:` is not a directory field; the directory holds "
                                    f"only what the institution publishes ({', '.join(OFFICE_KEYS)})")
    for pname, proc in pack.procedures.items():
        steps = proc.get("steps")
        if not isinstance(steps, list) or not steps:
            problems.append(f"{PROCEDURES_DIR}/{pname}.yaml: `steps:` must be a non-empty list")
            continue
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or not s.get("title"):
                problems.append(f"{PROCEDURES_DIR}/{pname}.yaml steps[{i}]: needs a `title:`")
                continue
            dl = s.get("deadline")
            if dl is not None and not isinstance(dl, dict):
                problems.append(f"{PROCEDURES_DIR}/{pname}.yaml steps[{i}]: `deadline:` must be a mapping")
            elif isinstance(dl, dict) and "working_days" in dl and not isinstance(dl["working_days"], int):
                problems.append(f"{PROCEDURES_DIR}/{pname}.yaml steps[{i}]: `working_days:` must be an integer")
    fetch = pack.courses.get("fetch")
    if fetch is not None:
        if not isinstance(fetch, dict) or not fetch.get("url"):
            problems.append(f"{COURSES_FILE}: `fetch:` needs a `url:`")
        elif domains and not host_allowed(str(fetch["url"]), domains, deny=pack.deny_hosts):
            problems.append(f"{COURSES_FILE}: fetch url {fetch['url']} is outside the pack's domains")
    return problems


OFFICE_KEYS = ("office", "person", "title", "email", "address", "phone", "room",
               "source", "date_read", "note")


def fact_age_days(fact: Fact | dict[str, Any], today: date | None = None) -> int | None:
    today = today or date.today()
    d = fact.date_read if isinstance(fact, Fact) else _parse_date(fact.get("date_read"))
    return None if d is None else (today - d).days


def age_note(fact: Fact | dict[str, Any], pack: Pack, today: date | None = None) -> str:
    """The sentence to attach to an answer built on a fact older than the
    pack's limit; empty when the fact is fresh enough."""
    age = fact_age_days(fact, today)
    if age is None:
        return "read on an unknown date; treat as unverified"
    if age > pack.max_fact_age_days:
        return f"read {age} days ago, older than the pack's {pack.max_fact_age_days}-day limit; confirm before relying on it"
    return ""


def stale_facts(pack: Pack, today: date | None = None) -> list[tuple[Fact, int | None]]:
    out = []
    for f in pack.facts():
        age = fact_age_days(f, today)
        if age is None or age > pack.max_fact_age_days:
            out.append((f, age))
    return out


# --------------------------------------------------------------------------- #
# Job 1: check a document
# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6})\b")
_POSTAL_RE = re.compile(r"\b[A-Z]\d[A-Z] ?\d[A-Z]\d\b")


def _name_variants(person: str) -> list[str]:
    """``Dr. Jane Q. Smith`` is also ``Jane Smith`` and ``Smith``."""
    clean = re.sub(r"\b(dr|prof|professor|mr|mrs|ms|phd|md)\b\.?", " ", person, flags=re.I)
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = re.sub(r",.*$", "", clean)
    parts = [p for p in re.split(r"\s+", clean.strip()) if p and not re.fullmatch(r"[A-Z]\.?", p)]
    variants = [person.strip()]
    if len(parts) >= 2:
        variants.append(f"{parts[0]} {parts[-1]}")
    return [v for v in variants if v]


def _surname(person: str) -> str:
    v = _name_variants(person)
    last = v[-1].split()[-1] if v else ""
    return re.sub(r"[^\w-]", "", last)


def check_document(pack: Pack, text: str, today: date | None = None) -> list[Finding]:
    """Check a document's office holders, emails, addresses and letterhead
    against the pack. Each finding is located and carries its source. What
    the pack does not hold is ``Unknown``, never guessed."""
    findings: list[Finding] = []
    norm_text = _norm(text)
    today = today or date.today()

    # Office holders: an office named in the text must be held by the person
    # the pack names; a person named in the text with a title the pack gives
    # to someone else is a Fix.
    for o in pack.offices:
        office = str(o.get("office", ""))
        person = str(o.get("person", ""))
        title = str(o.get("title", office))
        note = age_note(o, pack, today)
        src = str(o.get("source", "")), str(o.get("date_read", ""))
        title_hits = [t for t in {office, title} if t and _norm(t) in norm_text]
        person_hit = any(v and _norm(v) in norm_text for v in _name_variants(person))
        # A bare surname counts only on the same line as the office or title:
        # a different Smith two paragraphs away is not this office's holder.
        surname = _surname(person)
        surname_hit = bool(surname) and re.search(
            r"\b" + re.escape(surname) + r"\b", _window(text, [title, office])) is not None
        if title_hits:
            if person_hit or surname_hit:
                findings.append(Finding("Correct", f"{title_hits[0]}", f"held by {person}", *src, note))
            else:
                # Someone else named with this title?
                other = _person_near(text, title_hits[0])
                detail = f"the pack names {person} as {title}"
                if other:
                    detail += f"; the document names {other}"
                findings.append(Finding("Fix", f"{title_hits[0]}", detail, *src, note))
        elif person_hit:
            findings.append(Finding("Correct", person, f"is {title} in the pack", *src, note))
        # Email: the office's address, if any email is given for it in the text.
        email = str(o.get("email", "") or "")
        if email and (person_hit or surname_hit or title_hits):
            near = _emails_near(text, [person, title, office])
            others = {str(x.get("email", "")).lower() for x in pack.offices if x is not o and x.get("email")}
            # An email that belongs to another office on the same line is
            # that office's business, not a wrong address for this one.
            wrong = [e for e in near if e.lower() != email.lower() and e.lower() not in others]
            if wrong:
                findings.append(Finding("Fix", f"email for {title}", f"document has {wrong[0]}; the pack has {email}", *src, note))
            elif email.lower() in {e.lower() for e in near}:
                findings.append(Finding("Correct", f"email for {title}", email, *src, note))
        # Address: postal code next to the office, when the pack has one.
        address = str(o.get("address", "") or "")
        pack_codes = set(_POSTAL_RE.findall(address.upper()))
        if pack_codes and (person_hit or surname_hit or title_hits):
            doc_codes = set(_POSTAL_RE.findall(_window(text, [person, title, office]).upper()))
            if doc_codes and not (doc_codes & pack_codes):
                findings.append(Finding("Fix", f"address for {title}",
                                        f"document has postal code {sorted(doc_codes)[0]}; the pack has {address}",
                                        *src, note))

    # Emails at the institution's domains that the pack does not hold.
    known = {str(o.get("email", "")).lower() for o in pack.offices if o.get("email")}
    for e in sorted(set(_EMAIL_RE.findall(text))):
        dom = e.split("@", 1)[1].lower()
        if any(dom == d or dom.endswith("." + d) for d in pack.domains) and e.lower() not in known:
            findings.append(Finding("Unknown", f"email {e}",
                                    "not in the directory; the pack cannot confirm or deny it"))

    # Letterhead: hex colours and fonts named in the document.
    lh = pack.letterhead()
    if lh:
        src = str(lh.get("source", "")), str(lh.get("date_read", ""))
        note = age_note(lh, pack, today)
        colours = {str(c.get("hex", "")).upper(): str(c.get("name", "")) for c in (lh.get("colours") or []) if isinstance(c, dict)}
        for h in sorted(set(x.upper() for x in _HEX_RE.findall(text))):
            if h in colours:
                findings.append(Finding("Correct", f"colour {h}", f"{colours[h]} in the letterhead", *src, note))
            else:
                findings.append(Finding("Fix", f"colour {h}", "not a letterhead colour; the letterhead colours are "
                                        + ", ".join(f"{n} {h2}" for h2, n in colours.items()), *src, note))
        fonts = [str(f.get("name", "")) for f in (lh.get("fonts") or []) if isinstance(f, dict)]
        for f in fonts:
            if f and re.search(r"\b" + re.escape(f) + r"\b", text, flags=re.I):
                findings.append(Finding("Correct", f"font {f}", "is a letterhead typeface", *src, note))
        for m in re.finditer(r"font(?:-family)?\s*[:=]\s*['\"]?([A-Za-z][A-Za-z ]+)", text):
            name = m.group(1).strip()
            if fonts and not any(name.lower() == f.lower() for f in fonts):
                findings.append(Finding("Fix", f"font {name}", "not a letterhead typeface; the letterhead fonts are "
                                        + ", ".join(fonts), *src, note))
    return findings


def _window(text: str, anchors: list[str]) -> str:
    """The lines of ``text`` that mention any anchor (a person, a title, an
    office). A line is the unit, so an email two paragraphs away is not
    charged to the wrong office."""
    out = []
    for line in text.splitlines():
        low = line.lower()
        for a in anchors:
            if not a:
                continue
            if any(v and v.lower() in low for v in (_name_variants(a) if " " in a else [a])):
                out.append(line)
                break
    return "\n".join(out)


def _emails_near(text: str, anchors: list[str]) -> list[str]:
    return sorted(set(_EMAIL_RE.findall(_window(text, anchors))))


def _person_near(text: str, title: str) -> str:
    """A capitalised two-word name on the same line as the title, if any,
    that is not part of the title itself."""
    win = _window(text, [title]).replace(title, " ")
    title_words = set(_norm(title).split())
    for m in re.finditer(r"\b((?:Dr\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][A-Za-z'-]+)\b", win):
        name = m.group(1)
        if not (set(_norm(name).split()) & title_words):
            return name
    return ""


def check_verdict(findings: list[Finding]) -> str:
    if any(f.verdict == "Fix" for f in findings):
        return "Fix"
    if any(f.verdict == "Correct" for f in findings):
        return "Correct"
    return "Unknown"


# --------------------------------------------------------------------------- #
# Job 2: compute a date
# --------------------------------------------------------------------------- #


def is_holiday(pack: Pack, d: date) -> str:
    """The holiday's name when ``d`` is one, else an empty string."""
    return pack.holiday_dates().get(d, "")


def is_working_day(pack: Pack, d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(pack, d)


def working_days_from(pack: Pack, start: date, n: int) -> date:
    """``n`` working days after ``start`` (before, when ``n`` is negative),
    skipping weekends and the pack's holidays. With ``n == 0`` the result is
    ``start`` moved forward to the next working day, so a date computed here
    never lands on a holiday."""
    step = 1 if n >= 0 else -1
    left = abs(n)
    d = start
    while left > 0:
        d += timedelta(days=step)
        if is_working_day(pack, d):
            left -= 1
    while not is_working_day(pack, d):
        d += timedelta(days=step if n else 1)
    return d


def holidays_between(pack: Pack, a: date, b: date) -> list[tuple[date, str]]:
    lo, hi = (a, b) if a <= b else (b, a)
    return sorted((d, n) for d, n in pack.holiday_dates().items() if lo <= d <= hi)


def explain_date(pack: Pack, start: date, n: int) -> str:
    """The computed date with the holidays it skipped, as a sentence."""
    result = working_days_from(pack, start, n)
    skipped = holidays_between(pack, start, result)
    direction = "after" if n >= 0 else "before"
    s = f"{abs(n)} working days {direction} {start.isoformat()} is {result.isoformat()} ({result.strftime('%A')})."
    if skipped:
        s += " Skipped: " + ", ".join(f"{d.isoformat()} {name}" for d, name in skipped) + "."
    stale = [f for f in pack.facts() if f.kind == "holiday" and age_note(f, pack)]
    if stale:
        s += f" {len(stale)} holiday(s) in the pack are past the {pack.max_fact_age_days}-day limit; run `murmurent institution refresh`."
    return s


# --------------------------------------------------------------------------- #
# Job 3: walk a procedure
# --------------------------------------------------------------------------- #


def walk_procedure(pack: Pack, name: str, anchor: date | None = None,
                   done: list[int] | None = None, variant: str | None = None) -> list[StepDue]:
    """The procedure's steps in order, each with its form and its deadline
    resolved against ``anchor`` (the defence date, say). A step's
    ``deadline:`` is a mapping: ``working_days`` (negative means before),
    ``relative_to`` (the anchor's name, informational), ``rule`` (the
    sentence to show), and optionally per-variant values under ``by``
    (``by: {doctoral: -25, masters: -15}``)."""
    proc = pack.procedures.get(name)
    if proc is None:
        raise PackError(f"no procedure `{name}` in {pack.root / PROCEDURES_DIR}; "
                        f"have: {', '.join(sorted(pack.procedures)) or 'none'}")
    done = set(done or [])
    out: list[StepDue] = []
    for i, s in enumerate(proc.get("steps") or [], start=1):
        if not isinstance(s, dict):
            continue
        dl = s.get("deadline") if isinstance(s.get("deadline"), dict) else {}
        days = dl.get("working_days")
        if isinstance(dl.get("by"), dict) and variant and variant in dl["by"]:
            days = dl["by"][variant]
        due = None
        note = ""
        if isinstance(days, int) and anchor is not None:
            due = working_days_from(pack, anchor, days)
        elif isinstance(days, int) or isinstance(dl.get("by"), dict):
            note = f"needs the {dl.get('relative_to', 'anchor')} date"
        out.append(StepDue(
            number=i, title=str(s.get("title", "")), form=str(s.get("form", "") or ""),
            due=due, deadline_rule=str(dl.get("rule", "") or ""),
            source=str(s.get("source", "") or proc.get("source", "") or ""),
            done=i in done, note=note,
        ))
    return out


def next_steps(steps: list[StepDue], today: date | None = None, limit: int = 3) -> list[StepDue]:
    """The first undone steps, soonest deadline first among dated ones."""
    pending = [s for s in steps if not s.done]
    dated = sorted((s for s in pending if s.due), key=lambda s: s.due)  # type: ignore[arg-type,return-value]
    undated = [s for s in pending if not s.due]
    return (dated + undated)[:limit]


def format_walk(pack: Pack, name: str, steps: list[StepDue], today: date | None = None) -> str:
    proc = pack.procedures.get(name) or {}
    today = today or date.today()
    lines = [f"# {proc.get('title', name)}", ""]
    if proc.get("read_on"):
        lines.append(f"Requirements as read on {proc['read_on']}; confirm anything dated with "
                     f"{proc.get('confirm_with', 'the office that owns the procedure')}.")
        lines.append("")
    for s in steps:
        mark = "x" if s.done else " "
        due = ""
        if s.due:
            late = " (PAST)" if s.due < today else ""
            due = f" by **{s.due.isoformat()}**{late}"
        elif s.note:
            due = f" ({s.note})"
        form = f" Form: {s.form}." if s.form else ""
        rule = f" {s.deadline_rule}" if s.deadline_rule else ""
        lines.append(f"- [{mark}] {s.number}. {s.title}{due}.{form}{rule}")
    srcs = proc.get("sources") or []
    if srcs:
        lines += ["", "Sources:"]
        for src in srcs:
            if isinstance(src, dict):
                lines.append(f"- {src.get('name', '')}: {src.get('source', src.get('url', ''))} (read {src.get('date_read', '?')})")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Fetching, narrowly
# --------------------------------------------------------------------------- #

Fetcher = Callable[[str, dict[str, str] | None], str]


def fetch_text(url: str, data: dict[str, str] | None = None, *, domains: list[str],
               deny: list[str] | tuple[str, ...] = (), timeout: int = FETCH_TIMEOUT_SECONDS) -> str:
    """GET (or POST ``data``) ``url`` and return the page as plain text. The
    host must be inside ``domains`` and off the ``deny`` list, or the call
    refuses before any network activity. Redirects to another host, or to a
    sign-in page, are refused; so is a 401 or 403, and a page that is itself a
    login form. None of these is retried with credentials: the clerk reads
    public pages only (the institution lists the tool as public-data-only and
    classes its intranet pages as sensitive)."""
    if host_denied(url, deny):
        raise PackError(f"refused: {url} is on the pack's deny list ({LOGIN_REFUSED})")
    if not host_allowed(url, domains, deny=deny):
        raise PackError(f"refused: {url} is outside the pack's domains {domains}")
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})

    class _NoCrossHost(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
            # A site that sends its own page to plain http stays inside its
            # domain; one that sends it to another host does not; and one that
            # sends it to a sign-in page is behind a login.
            if host_denied(newurl, deny) or _LOGIN_PATH.search(urllib.parse.urlsplit(newurl).path or ""):
                raise PackError(f"refused: {url} redirects to a sign-in page ({LOGIN_REFUSED})")
            if not host_allowed(newurl, domains, require_https=False, deny=deny):
                raise PackError(f"refused: {url} redirects to {newurl}, outside the pack's domains")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_NoCrossHost, urllib.request.HTTPSHandler(context=_ssl_context()))
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PackError(f"refused: {url} answered {exc.code} ({LOGIN_REFUSED})") from exc
        raise PackError(f"could not read {url}: {exc}") from exc
    except urllib.error.URLError as exc:
        raise PackError(f"could not read {url}: {exc}") from exc
    text = raw.decode(charset, errors="replace")
    if _LOGIN_PAGE.search(text[:20000]):
        raise PackError(f"refused: {url} is a sign-in page ({LOGIN_REFUSED})")
    return text


def _ssl_context():
    """Python's own certificate store misses some university hosts'
    intermediates; the ``certifi`` bundle (installed with httpx) has them."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()


def html_to_text(markup: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", markup, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = _html.unescape(t)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


# --------------------------------------------------------------------------- #
# Courses: a fetch rule plus a cache
# --------------------------------------------------------------------------- #


def parse_timetable_tables(markup: str) -> list[dict[str, Any]]:
    """Western's master timetable (and any page shaped like it): an ``<h4>``
    per course, then a table whose first row is the header. Returns one dict
    per course: ``code``, ``title``, ``sections`` (one dict per row keyed by
    the lower-cased header). Columns the page does not show (room, days,
    time) are simply absent; see ``courses.yaml`` for the limits."""
    out: list[dict[str, Any]] = []
    for m in re.finditer(r"<h4[^>]*>(.*?)</h4>(.*?)(?=<h4|$)", markup, flags=re.S | re.I):
        heading = html_to_text(m.group(1))
        code, _, title = heading.partition(" - ")
        tbl = re.search(r"<table.*?</table>", m.group(2), flags=re.S | re.I)
        sections: list[dict[str, str]] = []
        if tbl:
            rows = re.findall(r"<tr.*?</tr>", tbl.group(0), flags=re.S | re.I)
            header: list[str] = []
            for r in rows:
                cells = [re.sub(r"\s+", " ", html_to_text(c)).strip()
                         for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)]
                if not cells:
                    continue
                if not header:
                    header = [re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in cells]
                    continue
                sections.append({h: v for h, v in zip(header, cells) if h})
        out.append({"code": code.strip(), "title": title.strip(), "sections": sections})
    return out


def fetch_course(pack: Pack, subject: str, number: str, fetcher: Fetcher | None = None,
                 today: date | None = None) -> dict[str, Any]:
    """Run the pack's ``courses.yaml`` fetch rule for one course and return
    the cache entry (with ``source`` and ``date_read``)."""
    rule = pack.courses.get("fetch")
    if not isinstance(rule, dict) or not rule.get("url"):
        raise PackError(f"{pack.root / COURSES_FILE} has no `fetch:` rule")
    url = str(rule["url"])
    fields = {k: str(v).format(subject=subject, number=number) for k, v in (rule.get("fields") or {}).items()}
    fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=pack.domains, deny=pack.deny_hosts))
    if not host_allowed(url, pack.domains, deny=pack.deny_hosts):
        raise PackError(f"refused: {url} is outside the pack's domains {pack.domains}")
    markup = fetcher(url, fields if str(rule.get("method", "GET")).upper() == "POST" else None)
    courses = parse_timetable_tables(markup)
    want = f"{subject} {number}".upper()
    hit = next((c for c in courses if c["code"].upper().startswith(want)), None)
    today = today or date.today()
    if hit is None:
        return {"code": want, "subject": subject, "number": str(number), "title": "", "sections": [],
                "found": False, "source": url, "date_read": today.isoformat()}
    return {"code": hit["code"], "subject": subject, "number": str(number), "title": hit["title"],
            "sections": hit["sections"], "found": True, "source": url, "date_read": today.isoformat()}


def course(pack: Pack, code: str) -> dict[str, Any] | None:
    want = _norm(code)
    for c in pack.courses.get("cache") or []:
        if isinstance(c, dict) and _norm(str(c.get("code", ""))).startswith(want):
            return c
    return None


# --------------------------------------------------------------------------- #
# Refresh: re-read each fact from its source
# --------------------------------------------------------------------------- #


def _fact_evidence(fact: Fact) -> list[str]:
    """The strings that, found on the source page, confirm the fact as it
    stands. A fact whose evidence is no longer on its page has changed."""
    d = fact.data
    if fact.kind == "office":
        ev = [str(d.get("person", ""))]
        if d.get("email"):
            ev.append(str(d["email"]))
        return [e for e in ev if e]
    if fact.kind == "holiday":
        dd = _parse_date(d.get("date"))
        return [f"{dd.strftime('%B')} {dd.day}"] if dd else []
    if fact.kind in ("term", "deadline"):
        return [str(d.get("evidence") or d.get("name") or "")]
    if fact.kind == "course":
        return [str(d.get("code", ""))]
    if fact.kind == "template":
        return [str(c.get("hex", "")) for c in (d.get("colours") or []) if isinstance(c, dict) and c.get("hex")]
    if fact.kind == "fact":
        return [str(d.get("evidence") or d.get("answer") or "")]
    if fact.kind == "rule":
        return [str(d.get("evidence") or d.get("says") or "")]
    return [str(d.get("evidence") or "")]


def refresh(pack: Pack, *, fetcher: Fetcher | None = None, today: date | None = None,
            apply: bool = False, kinds: tuple[str, ...] | None = None) -> list[Change]:
    """Re-read each fact from its source, inside the pack's domains only, and
    report what changed. Dry run unless ``apply``: then a confirmed fact gets
    today's ``date_read``, a course is re-fetched into the cache, and a fact
    whose evidence is gone is left as it was and reported, because what
    replaced it is a person's call, not a parser's."""
    today = today or date.today()
    domains = pack.domains
    fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=domains, deny=pack.deny_hosts))
    pages: dict[str, str | None] = {}
    changes: list[Change] = []

    def page(url: str) -> str | None:
        if url not in pages:
            try:
                pages[url] = html_to_text(fetcher(url, None))
            except PackError as exc:
                pages[url] = None
                pages[url + "#err"] = str(exc)
        return pages[url]

    for f in pack.facts():
        if kinds and f.kind not in kinds:
            continue
        if not f.source:
            changes.append(Change(f, "no_source"))
            continue
        if not host_allowed(f.source, domains, deny=pack.deny_hosts):
            changes.append(Change(f, "off_domain", f"{f.source} is outside {domains}"))
            continue
        if f.kind == "course":
            try:
                entry = fetch_course(pack, str(f.data.get("subject", "")), str(f.data.get("number", "")),
                                     fetcher=fetcher, today=today)
            except PackError as exc:
                changes.append(Change(f, "unreachable", str(exc)))
                continue
            if not entry["found"]:
                changes.append(Change(f, "changed", "course no longer on the timetable page"))
            elif entry["sections"] != (f.data.get("sections") or []):
                changes.append(Change(f, "changed", f"{len(entry['sections'])} section(s) now; cache had "
                                      f"{len(f.data.get('sections') or [])}"))
                if apply:
                    f.data.update(entry)
            else:
                changes.append(Change(f, "confirmed"))
                if apply:
                    f.data["date_read"] = today.isoformat()
            continue
        if f.kind == "procedure_source":
            text = page(f.source)
            if text is None:
                changes.append(Change(f, "unreachable", pages.get(f.source + "#err", "")))
            else:
                changes.append(Change(f, "confirmed", "page still there; its content is read by a person"))
                if apply:
                    f.data["date_read"] = today.isoformat()
            continue
        text = page(f.source)
        if text is None:
            changes.append(Change(f, "unreachable", pages.get(f.source + "#err", "")))
            continue
        evidence = [e for e in _fact_evidence(f) if e]
        if not evidence:
            changes.append(Change(f, "unchecked", "no evidence string to look for on the page"))
            continue
        low = text.lower()
        missing = [e for e in evidence if e.lower() not in low]
        if missing:
            changes.append(Change(f, "changed", "no longer on the page: " + "; ".join(missing)))
        else:
            changes.append(Change(f, "confirmed"))
            if apply:
                f.data["date_read"] = today.isoformat()
    if apply:
        write_pack(pack)
    return changes


def format_changes(changes: list[Change], today: date | None = None) -> str:
    today = today or date.today()
    counts: dict[str, int] = {}
    lines = []
    for c in changes:
        counts[c.status] = counts.get(c.status, 0) + 1
        if c.status == "confirmed":
            continue
        where = f"{c.fact.file.name} {c.fact.path}"
        lines.append(f"- {c.status.upper()}: {c.fact.kind} `{c.fact.key}` ({where})"
                     + (f": {c.detail}" if c.detail else "") + f" [read {c.fact.data.get('date_read', '?')}]")
    head = f"Refresh on {today.isoformat()}: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    return head + ("\n" + "\n".join(lines) if lines else "") + "\n"


def write_pack(pack: Pack) -> None:
    """Rewrite the pack's data files from memory. Comments in the YAML are
    lost, so a pack keeps its prose in ``README.md``, not in comments."""
    def dump(path: Path, doc: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")

    dump(pack.root / DIRECTORY_FILE, {"offices": pack.offices})
    dump(pack.root / CALENDAR_FILE, pack.calendar)
    if pack.courses:
        dump(pack.root / COURSES_FILE, pack.courses)
    if pack.learned or (pack.root / FACTS_FILE).exists():
        dump(pack.root / FACTS_FILE, {"facts": pack.learned})
    for name, proc in pack.procedures.items():
        dump(pack.root / PROCEDURES_DIR / f"{name}.yaml", proc)
    for name, tpl in pack.templates.items():
        dump(pack.root / TEMPLATES_DIR / f"{name}.yaml", tpl)
    for name, pol in pack.policies.items():
        dump(pack.root / POLICIES_DIR / f"{name}.yaml", pol)


# --------------------------------------------------------------------------- #
# Seeding a new pack
# --------------------------------------------------------------------------- #


def init_pack(root: Path, *, name: str, unique_name: str, domains: list[str], keeper: str,
              thesis_procedure: dict[str, Any] | None = None) -> list[Path]:
    """Scaffold an empty pack. Existing files are never overwritten. With
    ``thesis_procedure`` (see ``paper_package.seed_thesis_procedure``) the
    first procedure is written too."""
    root = Path(root)
    written: list[Path] = []

    def put(rel: str, doc: Any) -> None:
        p = root / rel
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
        written.append(p)

    put(PACK_META, {"name": name, "unique_name": unique_name, "domains": domains, "keeper": keeper,
                    "max_fact_age_days": DEFAULT_MAX_FACT_AGE_DAYS,
                    "verify_after_days": DEFAULT_VERIFY_AFTER_DAYS,
                    "lookup": {"pages": [f"https://www.{domains[0]}/a-z.html"] if domains else [],
                               "note": "Hub pages the crawl starts from when no web search is available; "
                                       "the clerk's first route is a web search limited to the domains above."},
                    "note": "The pack is the clerk's memory: what it looked up on the institution's own pages, "
                            "each with the page and the date read, plus what the centre keeps on purpose. "
                            "A fact that cannot be read is left out."})
    put(FACTS_FILE, {"facts": []})
    put(DIRECTORY_FILE, {"offices": []})
    put(CALENDAR_FILE, {"holidays": [], "terms": [], "deadlines": []})
    put(COURSES_FILE, {"fetch": None, "cache": []})
    put(f"{TEMPLATES_DIR}/{LETTERHEAD_FILE}", {"colours": [], "fonts": []})
    if thesis_procedure:
        put(f"{PROCEDURES_DIR}/thesis_examination.yaml", thesis_procedure)
    return written


__all__ = [
    "Pack", "Fact", "Finding", "StepDue", "Change", "PackError",
    "institution_root", "list_packs", "find_pack", "load_pack", "validate_pack",
    "fact_age_days", "age_note", "stale_facts", "host_allowed",
    "check_document", "check_verdict",
    "is_holiday", "is_working_day", "working_days_from", "holidays_between", "explain_date",
    "walk_procedure", "next_steps", "format_walk",
    "fetch_text", "html_to_text", "parse_timetable_tables", "fetch_course", "course",
    "refresh", "format_changes", "write_pack", "init_pack",
]


# --------------------------------------------------------------------------- #
# Looking a fact up when the pack lacks it, learning it, and verifying one on read
# --------------------------------------------------------------------------- #

DEFAULT_VERIFY_AFTER_DAYS = 0   # re-read a remembered fact every time; raise it only for an offline or slow machine
LOOKUP_MAX_PAGES = 12
_ROLE_WORDS = re.compile(r"(?i)\b(president|vice-president|vice president|provost|dean|chair|director|head|"
                         r"coordinator|co-ordinator|manager|lead|officer|registrar|secretary)\b")
_STOP = {"the", "of", "for", "and", "at", "in", "who", "is", "office", "a", "an", "to", "our", "western"}


@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    score: int


def _query_words(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP and len(w) > 1]


def _links(markup: str, base: str) -> list[tuple[str, str]]:
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', markup, flags=re.S | re.I):
        label = re.sub(r"<[^>]+>|\s+", " ", text).strip()
        link = urllib.parse.urljoin(base, _html.unescape(href).strip())
        link = urllib.parse.quote(link, safe=":/?&=%#+@;,~-._")   # a space in a link is the page's mistake, not ours
        out.append((link, label))
    return out


def _title(markup: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", markup, flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def lookup(pack: Pack, query: str, *, fetcher: Fetcher | None = None,
           max_pages: int = LOOKUP_MAX_PAGES) -> list[Hit]:
    """Find pages on the institution's own site that may hold a fact the pack
    lacks. Starts from the pack's ``lookup.pages`` (hub pages such as a
    websites A-Z), follows links whose text or address matches the question,
    up to two hops and ``max_pages`` pages, never leaving the pack's domains,
    and returns the pages that mention the question's words, best first, with
    a snippet around a role word (Dean, Director, Chair, ...). Nothing is
    written: the clerk reads the best page and records the fact with
    ``learn_office`` so the next session has it."""
    domains = pack.domains
    fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=domains, deny=pack.deny_hosts))
    words = _query_words(query)
    if not words:
        return []
    hubs = [str(u) for u in ((pack.meta.get("lookup") or {}).get("pages") or [])]
    seen: set[str] = set()
    queue: list[tuple[str, int, int]] = [(u, 0, 0) for u in hubs]
    hits: list[Hit] = []

    def matches(s: str) -> int:
        low = s.lower()
        return sum(1 for w in words if w in low)

    while queue and len(seen) < max_pages:
        url, hop, _ = queue.pop(0)
        if url in seen or not host_allowed(url, domains, require_https=False, deny=pack.deny_hosts):
            continue
        seen.add(url)
        try:
            markup = fetcher(url, None)
        except (PackError, ValueError, OSError):
            continue
        text = html_to_text(markup)
        score = matches(text)
        if score and hop > 0 or score >= len(words):
            low = text.lower()
            pos = min((low.find(w) for w in words if w in low), default=0)
            window = text[max(0, pos - 200): pos + 400]
            m = _ROLE_WORDS.search(window)
            snippet = re.sub(r"\s+", " ", window[max(0, (m.start() - 80) if m else 0):][:260]).strip()
            hits.append(Hit(url, _title(markup), snippet, score + (2 if m else 0)))
        if hop < 2:
            cands = []
            for link, label in _links(markup, url):
                s = matches(label) * 2 + matches(link)
                if s and host_allowed(link, domains, require_https=False, deny=pack.deny_hosts) and link not in seen:
                    cands.append((s, link))
            cands.sort(key=lambda c: -c[0])
            for s, link in cands[:6]:
                queue.append((link, hop + 1, s))
    hits.sort(key=lambda h: -h.score)
    return hits


def _check_source(pack: Pack, source: str) -> None:
    """A learned fact's page must be inside the domains and off the deny list."""
    if host_denied(source, pack.deny_hosts):
        raise PackError(f"refused: {source} is on the pack's deny list ({LOGIN_REFUSED})")
    if not host_allowed(source, pack.domains, deny=pack.deny_hosts):
        raise PackError(f"refused: {source} is outside the pack's domains {pack.domains}")


def learn_office(pack: Pack, *, office: str, person: str, title: str = "", email: str = "",
                 address: str = "", source: str, note: str = "", today: date | None = None,
                 fetcher: Fetcher | None = None, confirm: bool = True) -> dict[str, Any]:
    """Record an office holder in the pack from a page on the pack's domains.
    With ``confirm`` (the default) the page is fetched and must contain the
    person's name, so a fact cannot be learned from memory under a borrowed
    address. Replaces an entry for the same office; keeps everything else.
    Only what an institution publishes about an office holder is accepted."""
    today = today or date.today()
    _check_source(pack, source)
    if confirm:
        fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=pack.domains, deny=pack.deny_hosts))
        text = html_to_text(fetcher(source, None)).lower()
        missing = [v for v in (person, email) if v and v.lower() not in text]
        if missing:
            raise PackError(f"refused: {source} does not show {', '.join(missing)}; a fact is learned only "
                            "from a page that states it")
    entry: dict[str, Any] = {"office": office, "person": person}
    if title:
        entry["title"] = title
    if email:
        entry["email"] = email
    if address:
        entry["address"] = address
    entry["source"] = source
    entry["date_read"] = today.isoformat()
    if note:
        entry["note"] = note
    pack.offices[:] = [o for o in pack.offices if _norm(str(o.get("office", ""))) != _norm(office)]
    pack.offices.append(entry)
    write_pack(pack)
    return entry


def verify_after_days(pack: Pack) -> int:
    try:
        return int(pack.meta.get("verify_after_days") or DEFAULT_VERIFY_AFTER_DAYS)
    except (TypeError, ValueError):
        return DEFAULT_VERIFY_AFTER_DAYS


def verify_fact(pack: Pack, fact: Fact, *, fetcher: Fetcher | None = None, today: date | None = None,
                apply: bool = True) -> Change:
    """Re-read one fact's source page now. A fact the page still confirms is
    restamped with today's date (when ``apply``); one it no longer confirms is
    reported as changed and left for a person. This is what keeps an office
    holder current between scheduled refreshes: the clerk verifies on read
    once a fact is older than ``verify_after_days``."""
    today = today or date.today()
    fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=pack.domains, deny=pack.deny_hosts))
    if not fact.source:
        return Change(fact, "no_source")
    if not host_allowed(fact.source, pack.domains, deny=pack.deny_hosts):
        return Change(fact, "off_domain", f"{fact.source} is outside {pack.domains}")
    try:
        text = html_to_text(fetcher(fact.source, None)).lower()
    except PackError as exc:
        return Change(fact, "unreachable", str(exc))
    evidence = [e for e in _fact_evidence(fact) if e]
    missing = [e for e in evidence if e.lower() not in text]
    if missing:
        return Change(fact, "changed", "no longer on the page: " + "; ".join(missing))
    if apply:
        fact.data["date_read"] = today.isoformat()
        write_pack(pack)
    return Change(fact, "confirmed")


def needs_verify(pack: Pack, fact: Fact | dict[str, Any], today: date | None = None) -> bool:
    """Whether a remembered fact must be re-read from its page before it is relied on.
    With the default ``verify_after_days: 0`` that is every time: the memory says where
    to look, and the answer comes from the page as it reads today."""
    age = fact_age_days(fact, today)
    return age is None or age >= verify_after_days(pack) if verify_after_days(pack) > 0 else True


def learn_fact(pack: Pack, *, question: str, answer: str, source: str, evidence: str = "",
               today: date | None = None, fetcher: Fetcher | None = None, confirm: bool = True) -> dict[str, Any]:
    """Remember an answer the clerk read on one of the institution's pages:
    the question in the asker's words, the answer in one or two sentences, the
    page, the date, and ``evidence``, a short string from the page that the
    refresh and the verify-on-read look for (the answer itself when none is
    given). With ``confirm`` the page is fetched and must contain the
    evidence, so nothing enters the memory from the model's own recollection.
    A fact for the same question replaces the older one."""
    today = today or date.today()
    _check_source(pack, source)
    evidence = evidence or answer
    if confirm:
        fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=pack.domains, deny=pack.deny_hosts))
        text = re.sub(r"\s+", " ", html_to_text(fetcher(source, None))).lower()
        if re.sub(r"\s+", " ", evidence).lower() not in text:
            raise PackError(f"refused: {source} does not show {evidence!r}; a fact is learned only from a page "
                            "that states it (give --evidence a phrase that is on the page)")
    entry = {"question": question, "answer": answer, "evidence": evidence, "source": source,
             "date_read": today.isoformat()}
    pack.learned[:] = [f for f in pack.learned if _norm(str(f.get("question", ""))) != _norm(question)]
    pack.learned.append(entry)
    write_pack(pack)
    return entry


def recall(pack: Pack, query: str) -> list[dict[str, Any]]:
    """Learned facts and offices whose question or answer shares words with
    the query, best first. What the clerk checks before it looks anything up."""
    words = set(_query_words(query))
    if not words:
        return []
    scored = []
    for f in pack.learned:
        text = (str(f.get("question", "")) + " " + str(f.get("answer", ""))).lower()
        n = sum(1 for w in words if w in text)
        if n:
            scored.append((n, {"kind": "fact", **f}))
    for o in pack.offices:
        text = (str(o.get("office", "")) + " " + str(o.get("title", ""))).lower()
        n = sum(1 for w in words if w in text)
        if n:
            scored.append((n, {"kind": "office", **o}))
    scored.sort(key=lambda t: -t[0])
    return [d for _, d in scored]


# --------------------------------------------------------------------------- #
# Policies: rules read from the institution's pages, applied to a document such as a syllabus
# --------------------------------------------------------------------------- #

RULE_KINDS = ("no_tests_in_last_weeks", "no_new_assignments_in_last_weeks", "no_final_exam_in_last_weeks",
              "min_weight_before_date", "note")
_TEST_WORDS = re.compile(r"\b(test|quiz|quizzes|midterm|exam|examination)\b", re.I)
_PENALTY_WORDS = re.compile(r"\b(late|penalt\w*|per (day|week)|deduct\w*|bonus)\b", re.I)
_FINAL_WORDS = re.compile(r"\bfinal (exam|examination)\b", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE_WORDS = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\.?\s+(\d{{4}})\b|\b({_MONTHS})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b|\b(\d{{4}}-\d{{2}}-\d{{2}})\b", re.I)


def _parse_date_words(text: str) -> list[date]:
    out = []
    for m in _DATE_WORDS.finditer(text):
        try:
            if m.group(7):
                out.append(date.fromisoformat(m.group(7)))
            elif m.group(1):
                out.append(datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}", "%d %b %Y").date())
            else:
                out.append(datetime.strptime(f"{m.group(5)} {m.group(4)[:3]} {m.group(6)}", "%d %b %Y").date())
        except ValueError:
            continue
    return out


@dataclass
class Assessment:
    name: str
    when: date | None
    weight: float | None
    line: str
    announced: date | None = None
    is_test: bool = False
    is_final: bool = False


def parse_assessments(text: str) -> list[Assessment]:
    """Lines of a syllabus that carry a percentage: the assessment's name, its date (the
    first date on the line), its weight, and whether it is a test or a final examination.
    A date after the word 'announced' or 'new' is the announcement date."""
    out: list[Assessment] = []
    for raw in text.splitlines():
        line = raw.strip().strip("|").strip()
        if not line or "%" not in line or set(line) <= set("|-: "):
            continue
        if _PENALTY_WORDS.search(line):
            continue  # "late work loses 5% per day" is a penalty, not an assessment
        m = _PCT.search(line)
        if not m:
            continue
        weight = float(m.group(1))
        dates = _parse_date_words(line)
        ann = None
        am = re.search(r"(announced|new)[^|]*?(" + _DATE_WORDS.pattern + ")", line, re.I)
        if am:
            got = _parse_date_words(am.group(0))
            ann = got[0] if got else None
        when = next((d for d in dates if d != ann), dates[0] if dates else None)
        if ann is None and when is not None:
            # "announced 20 November" with no year: the year is the assessment's
            am2 = re.search(rf"(?i)(announced|new)\D{{0,20}}?(\d{{1,2}})\s+({_MONTHS})\b|(announced|new)\D{{0,20}}?({_MONTHS})\.?\s+(\d{{1,2}})\b", line)
            if am2:
                try:
                    dd, mm = (am2.group(2), am2.group(3)) if am2.group(2) else (am2.group(6), am2.group(5))
                    ann = datetime.strptime(f"{dd} {mm[:3]} {when.year}", "%d %b %Y").date()
                except ValueError:
                    ann = None
        name = re.split(r"\s*\|\s*", line)[0]
        name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip() or line[:40]
        out.append(Assessment(name, when, weight, line, ann, bool(_TEST_WORDS.search(name)), bool(_FINAL_WORDS.search(name))))
    return out


def term_end_of(text: str, pack: Pack | None = None, term_name: str = "") -> tuple[date | None, str]:
    """The last day of classes: from a 'Term: ... to <date>' line in the document, else the
    pack's term of that name (calendar.yaml terms with `classes_end`), else None."""
    m = re.search(r"(?i)(term|classes)[^\n]*?\bto\s+(" + _DATE_WORDS.pattern + ")", text)
    if m:
        got = _parse_date_words(m.group(2))
        if got:
            return got[0], "the document's own term dates"
    if pack is not None and term_name:
        for t in pack.terms():
            if term_name.lower() in str(t.get("name", "")).lower():
                for key in ("classes_end", "end", "last_day_of_classes"):
                    d = _parse_date(t.get(key))
                    if d:
                        return d, f"the pack's term {t.get('name')} [{t.get('source')}, read {t.get('date_read')}]"
    return None, ""


def check_syllabus(pack: Pack, text: str, policy: str, *, term_name: str = "",
                   today: date | None = None) -> list[Finding]:
    """Apply a policy's rules to a syllabus. Each finding quotes the rule as the institution's
    page states it, with the source and the date read; what the parser could not establish
    (no term end, no date on a line) is reported as Unknown rather than passed."""
    pol = pack.policies.get(policy)
    if pol is None:
        raise PackError(f"no policy `{policy}` in the pack; the clerk learns one with `murmurent institution learn-rule`"
                        + (f" (have: {', '.join(pack.policies)})" if pack.policies else ""))
    items = parse_assessments(text)
    end, end_src = term_end_of(text, pack, term_name)
    out: list[Finding] = []
    for r in pol.get("rules") or []:
        chk = r.get("check") or {}
        kind = chk.get("kind", "note")
        cite = f"[{r.get('source')}, read {r.get('date_read')}]"
        says = f"The {pack.name} rule says: \"{r.get('says')}\" {cite}"
        if kind == "note":
            out.append(Finding("Note", str(r.get("id")), f"{says} (applied by reading, not by the parser)"))
            continue
        if end is None:
            out.append(Finding("Unknown", str(r.get("id")), f"cannot place the last weeks of term: no 'Term: ... to <date>' line and no term given; {says}"))
            continue
        weeks = int(chk.get("weeks", 0))
        start = end - timedelta(weeks=weeks)
        for a in items:
            if kind == "no_tests_in_last_weeks" and a.is_test and not a.is_final:
                if a.when is None:
                    out.append(Finding("Unknown", a.name, f"no date on this line, so its place in the last {weeks} weeks is unknown; {says}"))
                elif start < a.when <= end:
                    out.append(Finding("Fix", a.name, f"a test on {a.when.isoformat()}, inside the last {weeks} weeks of classes (from {start.isoformat()} to {end.isoformat()}, {end_src}); {says}"))
                else:
                    out.append(Finding("Correct", a.name, f"on {a.when.isoformat()}, outside the last {weeks} weeks; {cite}"))
            elif kind == "no_final_exam_in_last_weeks" and a.is_final and a.when is not None:
                if start < a.when <= end:
                    out.append(Finding("Fix", a.name, f"a final examination on {a.when.isoformat()}, inside the last {weeks} weeks of classes; {says}"))
            elif kind == "no_new_assignments_in_last_weeks" and not a.is_test:
                if a.announced is not None and start < a.announced <= end:
                    out.append(Finding("Fix", a.name, f"announced {a.announced.isoformat()}, inside the last {weeks} weeks of classes (from {start.isoformat()}); {says}"))
                elif a.announced is None and a.when is not None and start < a.when <= end:
                    out.append(Finding("Unknown", a.name, f"due {a.when.isoformat()}, inside the last {weeks} weeks: allowed if it was announced before {start.isoformat()}; the document does not say when; {says}"))
            elif kind == "min_weight_before_date":
                pass
        if kind == "min_weight_before_date":
            by = _parse_date(chk.get("by")) or (pack.deadline_date(chk.get("deadline", "")) if hasattr(pack, "deadline_date") else None)
            need = float(chk.get("percent", 0))
            if by is None:
                out.append(Finding("Unknown", str(r.get("id")), f"the date to count to is not in the pack; {says}"))
            else:
                total = sum(a.weight or 0 for a in items if a.when and a.when <= by)
                out.append(Finding("Correct" if total >= need else "Fix", str(r.get("id")),
                                   f"{total:g}% of the grade is assessed by {by.isoformat()} (the rule asks {need:g}%); {says}"))
    return out


def learn_rule(pack: Pack, *, policy: str, rule_id: str, says: str, source: str, heading: str = "",
               check: dict[str, Any] | None = None, today: date | None = None, fetcher: Fetcher | None = None,
               confirm: bool = True) -> dict[str, Any]:
    """Record a rule the clerk read on one of the institution's pages, quoted as the page
    states it. With ``confirm`` the page is fetched and must contain the quote, so no rule
    enters the pack from recollection. ``check`` makes it machine-checkable
    (kind in RULE_KINDS, with weeks or percent); without it the rule is applied by reading."""
    today = today or date.today()
    _check_source(pack, source)
    if check and check.get("kind") not in RULE_KINDS:
        raise PackError(f"check.kind must be one of {RULE_KINDS}")
    if confirm:
        fetcher = fetcher or (lambda u, d: fetch_text(u, d, domains=pack.domains, deny=pack.deny_hosts))
        text = re.sub(r"\s+", " ", html_to_text(fetcher(source, None))).lower()
        if re.sub(r"\s+", " ", says).lower() not in text:
            raise PackError(f"refused: {source} does not state {says!r}; a rule is learned only as the page words it")
    entry: dict[str, Any] = {"id": rule_id, "says": says, "source": source, "date_read": today.isoformat()}
    if heading:
        entry["heading"] = heading
    entry["check"] = check or {"kind": "note"}
    pol = pack.policies.setdefault(policy, {"name": policy, "rules": []})
    pol["rules"] = [r for r in (pol.get("rules") or []) if str(r.get("id")) != rule_id] + [entry]
    write_pack(pack)
    return entry
