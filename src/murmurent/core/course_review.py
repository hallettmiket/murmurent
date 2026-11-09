"""Review a whole course outline against an institution's rules and calendar.

``murmurent institution check --policy`` applies one policy. This module is
the clerk's whole-document review: every policy that applies to the course's
level (undergraduate or graduate), every dated line checked against the
pack's holidays and non-instructional days, the grade weights added up, and
the places where the outline says too little to be checked. The result is a
structured ``Review`` and an HTML or Markdown report of it, which opens with the
term day by day: every date, and what the outline, the calendar, the deadlines
and the rules put on it.

Nothing here invents a rule. A rule comes from ``policies/<name>.yaml``,
quoted as the institution's page words it; a holiday or term from
``calendar.yaml``. The checks that are not rules (weights add to 100, a
lecture on a weekend, a missing section) are labelled as the clerk's own
observations, not the institution's.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import institution as inst

LEVELS = ("undergraduate", "graduate")

# Words that mark a line as a class meeting rather than an assessment.
_MEETING_WORDS = re.compile(r"\b(lecture|lab|laboratory|tutorial|seminar|class|session|week\s*\d+)\b", re.I)
_UNCLEAR_WORDS = re.compile(r"\b(TBA|TBD|to be (announced|determined|confirmed)|approximately|roughly|around)\b", re.I)
# Sections a course outline is expected to have. Observation, not a rule.
EXPECTED_SECTIONS = {
    "how to reach the instructor": re.compile(r"\b(office hours?|e-?mail|contact)\b", re.I),
    "academic consideration or accommodation": re.compile(r"\b(accommodat|academic consideration|medical)\w*", re.I),
    "academic integrity": re.compile(r"\b(integrity|plagiarism|scholastic offen)\w*", re.I),
    "learning outcomes": re.compile(r"\b(learning outcomes?|objectives?|by the end of (this|the) course)\b", re.I),
    "required material": re.compile(r"\b(textbook|required (text|reading)|course materials?)\b", re.I),
}


@dataclass
class ScheduleItem:
    name: str
    when: date
    line: str
    is_assessment: bool


@dataclass
class CalendarEntry:
    kind: str      # course | holiday | term | deadline | cutoff | marker
    label: str
    source: str = ""   # "[url, read date]" or "the outline" or the rule id


@dataclass
class CalendarDay:
    when: date
    entries: list[CalendarEntry] = field(default_factory=list)

    @property
    def weekend(self) -> bool:
        return self.when.weekday() >= 5

    @property
    def off(self) -> bool:
        """A day with no classes: a holiday or inside a non-instructional range."""
        return any(e.kind in ("holiday", "term") for e in self.entries)


@dataclass
class Review:
    level: str
    pack: str
    policies: list[str]
    calendar: list[CalendarDay] = field(default_factory=list)   # every day of the term
    calendar_note: str = ""                                     # what the calendar could not include
    rules: list[inst.Finding] = field(default_factory=list)       # the institution's rules
    schedule: list[inst.Finding] = field(default_factory=list)    # dates vs calendar
    grading: list[inst.Finding] = field(default_factory=list)     # weights
    clarity: list[inst.Finding] = field(default_factory=list)     # what the outline leaves unclear
    term_end: date | None = None
    term_end_source: str = ""

    def all(self) -> list[inst.Finding]:
        return self.rules + self.schedule + self.grading + self.clarity

    def verdict(self) -> str:
        return inst.check_verdict(self.all())

    def counts(self) -> dict[str, int]:
        c = {"Fix": 0, "Unknown": 0, "Correct": 0, "Note": 0}
        for f in self.all():
            c[f.verdict] = c.get(f.verdict, 0) + 1
        return c


def policies_for(pack: inst.Pack, level: str) -> list[str]:
    """Policies whose ``applies_to`` lists the level (a policy without one applies to both)."""
    out = []
    for name, pol in pack.policies.items():
        applies = pol.get("applies_to") or list(LEVELS)
        if isinstance(applies, str):
            applies = [applies]
        if level in [str(a).lower() for a in applies] or "all" in applies:
            out.append(name)
    return sorted(out)


def parse_schedule(text: str) -> list[ScheduleItem]:
    """Every line with a date: meetings and assessments alike."""
    out: list[ScheduleItem] = []
    for raw in text.splitlines():
        line = raw.strip().strip("|").strip()
        if not line or set(line) <= set("|-: "):
            continue
        dates = inst._parse_date_words(line)
        if not dates:
            continue
        if re.match(r"(?i)^\s*term\b", line):
            continue  # the term line itself
        name = re.split(r"\s*\|\s*", line)[0]
        name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip() or line[:40]
        is_assess = "%" in line or bool(inst._TEST_WORDS.search(name))
        is_meeting = bool(_MEETING_WORDS.search(name)) and not is_assess
        if not (is_assess or is_meeting):
            continue
        out.append(ScheduleItem(name, dates[0], line, is_assess))
    return out


def _non_instructional(pack: inst.Pack) -> list[tuple[date, date, str, str, str]]:
    """Ranges in the calendar's terms during which no classes are held: reading weeks,
    study days, non-instructional days, examination periods."""
    out = []
    for t in pack.terms():
        name = str(t.get("name", ""))
        if not re.search(r"reading|study day|non-instructional|examination period", name, re.I):
            continue
        a, b = inst._parse_date(t.get("start")), inst._parse_date(t.get("end"))
        if a and b:
            out.append((a, b, name, str(t.get("source", "")), str(t.get("date_read", ""))))
    return out


_CUTOFF_KINDS = {
    "no_tests_in_last_weeks": "last day a test may be scheduled",
    "no_final_exam_in_last_weeks": "last day a final examination may be held in class",
    "no_new_assignments_in_last_weeks": "last day a new assignment may be announced",
}


_TERM_SPAN = re.compile(
    r"(?i)(?:^|\n)[^\n]*?\b(term|classes)\b[^\n]*?"
    r"\b(?P<d1>\d{1,2}\s+(?:" + inst._MONTHS + r")|(?:" + inst._MONTHS + r")\s+\d{1,2})\.?,?(?:\s+(?P<y1>\d{4}))?"
    r"\s+(?:to|until|through|-|\u2013)\s+(?P<rest>[^\n]*)")


def _term_start_of(text: str, pack: inst.Pack, term_name: str, items: list[ScheduleItem]) -> tuple[date | None, str]:
    """The first day of classes: the outline's own term line ("Term: 10 September to 9 December
    2026", where a start without a year takes the end's), else the pack's term, else the
    earliest dated line."""
    m = _TERM_SPAN.search(text)
    if m:
        ends = inst._parse_date_words(m.group("rest"))
        year = m.group("y1") or (str(ends[0].year) if ends else "")
        if year:
            got = inst._parse_date_words(f"{m.group('d1')} {year}")
            if got:
                start = got[0]
                if ends and start > ends[0] and not m.group("y1"):
                    start = start.replace(year=start.year - 1)
                return start, "the outline's own term dates"
    if term_name:
        for t in pack.terms():
            name = str(t.get("name", "")).lower()
            if term_name.lower() in name and "classes" in name and not re.search(r"end", name):
                d = inst._parse_date(t.get("start"))
                if d:
                    return d, f"the pack's term {t.get('name')} [{t.get('source')}, read {t.get('date_read')}]"
    if items:
        return min(it.when for it in items), "the earliest dated line of the outline"
    return None, ""


def _src(t: dict[str, Any]) -> str:
    return f"[{t.get('source', '')}, read {t.get('date_read', '')}]"


def build_calendar(pack: inst.Pack, text: str, *, level: str = "undergraduate", term_name: str = "",
                   term_end: date | None = None) -> tuple[list[CalendarDay], str]:
    """Every day from the first day of classes to the end of the examination period, with what
    falls on it: the outline's meetings and assessments, the pack's holidays, reading weeks and
    study days, the pack's deadlines (add, drop, withdraw), and the cutoffs the rules imply
    (counted back from the last day of classes). Returns the days and a note on what could not
    be included."""
    items = parse_schedule(text)
    assess = {a.name: a for a in inst.parse_assessments(text)}
    start, start_src = _term_start_of(text, pack, term_name, items)
    end = term_end or inst.term_end_of(text, pack, term_name)[0]
    notes: list[str] = []
    if start is None or end is None:
        return [], "the calendar needs the first and last day of classes; give the term (--term) or put a `Term: <date> to <date>` line in the outline"
    # Extend to the end of the examination period that follows the last day of classes.
    exam = None
    for t in pack.terms():
        if "examination period" in str(t.get("name", "")).lower():
            a, b = inst._parse_date(t.get("start")), inst._parse_date(t.get("end"))
            if a and b and end <= a <= end + timedelta(days=30):
                exam = (a, b, str(t.get("name")), _src(t))
    last = exam[1] if exam else end
    by_day: dict[date, CalendarDay] = {}
    d = start
    while d <= last:
        by_day[d] = CalendarDay(d)
        d += timedelta(days=1)

    def put(when: date, entry: CalendarEntry) -> None:
        if when in by_day:
            by_day[when].entries.append(entry)

    put(start, CalendarEntry("marker", "First day of classes", start_src))
    put(end, CalendarEntry("marker", "Last day of classes", "the outline" if "outline" in start_src else start_src))
    for when, name in pack.holiday_dates().items():
        put(when, CalendarEntry("holiday", f"{name} (holiday, no classes)", "the pack's holiday list"))
    for a, b, name, source, read in _non_instructional(pack):
        d = a
        while d <= b:
            put(d, CalendarEntry("term", name, f"[{source}, read {read}]"))
            d += timedelta(days=1)
    if exam:
        pass  # already covered by _non_instructional when the name says "examination period"
    deadlines = pack.deadlines()
    if not deadlines:
        notes.append("the pack holds no deadlines (last day to add, to drop, to withdraw without penalty): the clerk records them in the pack's calendar from the institution's sessional dates page, and they will appear here")
    for t in deadlines:
        when = inst._parse_date(t.get("date"))
        if when:
            put(when, CalendarEntry("deadline", str(t.get("name", "deadline")), _src(t)))
    # Cutoffs the rules imply, counted back from the last day of classes.
    for name in policies_for(pack, level):
        for r in pack.policies[name].get("rules") or []:
            chk = r.get("check") or {}
            kind = str(chk.get("kind", ""))
            weeks = chk.get("weeks")
            if kind in _CUTOFF_KINDS and weeks:
                when = end - timedelta(weeks=int(weeks))
                put(when, CalendarEntry("cutoff", f"{_CUTOFF_KINDS[kind].capitalize()}: the last {weeks} weeks of classes begin tomorrow ({r.get('says', '')})", f"[{r.get('source', '')}, read {r.get('date_read', '')}]"))
            elif kind == "note" and re.search(r"last day", str(r.get("says", "")), re.I):
                put(end, CalendarEntry("cutoff", str(r.get("says", "")).strip().capitalize(), f"[{r.get('source', '')}, read {r.get('date_read', '')}]"))
    for it in items:
        label = it.name
        a = assess.get(it.name)
        if a is not None and a.weight:
            label = f"{it.name} ({a.weight:g}%)"
        put(it.when, CalendarEntry("course", label, "the outline"))
    for a in assess.values():
        if a.when is None:
            notes.append(f"{a.name} has no date in the outline and is not on the calendar")
    return list(by_day.values()), "; ".join(notes)


def review_course(pack: inst.Pack, text: str, *, level: str = "undergraduate",
                  term_name: str = "", today: date | None = None) -> Review:
    level = level.lower()
    if level not in LEVELS:
        raise inst.PackError(f"level must be one of {', '.join(LEVELS)}, not {level!r}")
    names = policies_for(pack, level)
    rv = Review(level=level, pack=pack.name, policies=names)
    end, end_src = inst.term_end_of(text, pack, term_name)
    rv.term_end, rv.term_end_source = end, end_src

    # 1. The institution's rules, every policy for this level.
    for name in names:
        for f in inst.check_syllabus(pack, text, name, term_name=term_name, today=today):
            f.what = f"{f.what} [{name}]"
            rv.rules.append(f)
    if not names:
        rv.rules.append(inst.Finding("Unknown", "rules", f"the pack holds no policy for {level} courses; the clerk learns one with `murmurent institution learn-rule`"))

    # 2. The schedule against the calendar.
    hol = pack.holiday_dates()
    ranges = _non_instructional(pack)
    items = parse_schedule(text)
    if not items:
        rv.schedule.append(inst.Finding("Unknown", "schedule", "no dated lectures, labs or assessments found, so nothing could be checked against the calendar"))
    for it in items:
        kind = "assessment" if it.is_assessment else "class meeting"
        if it.when in hol:
            rv.schedule.append(inst.Finding("Fix", it.name, f"{kind} on {it.when.isoformat()}, which is {hol[it.when]} (the pack's holiday list)"))
            continue
        hit = next((r for r in ranges if r[0] <= it.when <= r[1]), None)
        if hit and not (it.is_assessment and inst._FINAL_WORDS.search(it.name) and "examination period" in hit[2].lower()):
            rv.schedule.append(inst.Finding("Fix", it.name, f"{kind} on {it.when.isoformat()}, inside {hit[2]} ({hit[0].isoformat()} to {hit[1].isoformat()}) [{hit[3]}, read {hit[4]}]"))
            continue
        if it.when.weekday() >= 5:
            rv.schedule.append(inst.Finding("Note", it.name, f"{kind} on {it.when.isoformat()}, a {it.when.strftime('%A')}: check this is intended"))
            continue
        rv.schedule.append(inst.Finding("Correct", it.name, f"{kind} on {it.when.isoformat()}, a working day with classes"))
    # Two assessments on one day.
    by_day: dict[date, list[str]] = {}
    for it in items:
        if it.is_assessment:
            by_day.setdefault(it.when, []).append(it.name)
    for d, ns in by_day.items():
        if len(ns) > 1:
            rv.schedule.append(inst.Finding("Note", " and ".join(ns), f"both on {d.isoformat()}: two assessments on one day is allowed but worth a second look"))

    # 3. Grading: the weights.
    assess = inst.parse_assessments(text)
    total = sum(a.weight or 0 for a in assess)
    if not assess:
        rv.grading.append(inst.Finding("Unknown", "grade weights", "no lines with a percentage were found"))
    elif abs(total - 100) < 0.01:
        rv.grading.append(inst.Finding("Correct", "grade weights", f"{len(assess)} assessments add to 100%"))
    else:
        rv.grading.append(inst.Finding("Fix", "grade weights", f"{len(assess)} assessments add to {total:g}%, not 100%"))
    # 4. Clarity.
    for a in assess:
        if a.when is None:
            rv.clarity.append(inst.Finding("Unknown", a.name, "no date given for this assessment"))
        if _UNCLEAR_WORDS.search(a.line):
            rv.clarity.append(inst.Finding("Unknown", a.name, f"worded as not yet fixed: \"{a.line.strip()[:80]}\""))
    for label, rx in EXPECTED_SECTIONS.items():
        if not rx.search(text):
            rv.clarity.append(inst.Finding("Note", label, "nothing in the outline mentions this (the clerk's observation, not an institutional rule)"))
    if end is None:
        rv.clarity.append(inst.Finding("Unknown", "term dates", "the outline does not say when classes end and no term was given, so the last-weeks rules could not be placed"))
    # 5. The calendar: every day of the term and what falls on it.
    rv.calendar, rv.calendar_note = build_calendar(pack, text, level=level, term_name=term_name, term_end=end)
    return rv


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

_SECTIONS = (("rules", "The institution's rules"), ("schedule", "The schedule against the calendar"),
             ("grading", "Grading"), ("clarity", "What the outline leaves unclear"))


def render_markdown(rv: Review, title: str = "Course outline review") -> str:
    c = rv.counts()
    lines = [f"# {title}", "",
             f"**{rv.verdict()}**: {c['Fix']} to fix, {c['Unknown']} unknown, {c['Correct']} correct, {c['Note']} notes. "
             f"Reviewed as a {rv.level} course against {rv.pack}; policies applied: {', '.join(rv.policies) or 'none'}.", ""]
    if rv.term_end:
        lines += [f"Last day of classes taken as {rv.term_end.isoformat()} ({rv.term_end_source}).", ""]
    lines += ["## The term, day by day", ""]
    if rv.calendar_note:
        lines += [f"Not on the calendar: {rv.calendar_note}.", ""]
    if not rv.calendar:
        lines += ["No calendar could be built.", ""]
    month = None
    for day in rv.calendar:
        if (day.when.year, day.when.month) != month:
            month = (day.when.year, day.when.month)
            lines += ["", f"### {day.when.strftime('%B %Y')}", "", "| Day | | What happens |", "|---|---|---|"]
        what = "<br>".join(
            e.label if not e.source or e.source == "the outline"
            else (f"{e.label} {e.source}" if e.source.startswith("[") else f"{e.label} ({e.source})")
            for e in day.entries)
        mark = "off" if day.off else ("weekend" if day.weekend else "")
        lines.append(f"| {day.when.strftime('%a %d')} | {mark} | {what} |")
    lines.append("")
    for key, heading in _SECTIONS:
        fs: list[inst.Finding] = getattr(rv, key)
        lines += [f"## {heading}", ""]
        if not fs:
            lines += ["Nothing to report.", ""]
        for f in fs:
            lines.append(f"- **{f.verdict}** {f.what}: {f.detail}")
        lines.append("")
    lines += ["## What the clerk did not do", "",
              "- It did not judge the teaching, the workload or the fairness of the outline: ask the conscience for an equity review, which reports separately.",
              "- It did not rewrite the outline: ask the scribe for a corrected version, in the format you want (Markdown, HTML, PDF).",
              "- Every rule above is quoted from the institution's own page with the date it was read; a check marked as the clerk's observation is not a rule.", ""]
    return "\n".join(lines)


_CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#222;line-height:1.45}
h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:1.6rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}
.summary{padding:.8rem 1rem;border-radius:8px;background:#f4f4f4;margin:1rem 0}
.v{display:inline-block;min-width:4.6rem;text-align:center;font-weight:600;border-radius:4px;padding:0 .4rem;margin-right:.5rem;font-size:.85rem}
.Fix{background:#fde2e1;color:#8a1c14}.Unknown{background:#fff3cd;color:#7a5a00}.Correct{background:#e2f5e6;color:#1d6b2f}.Note{background:#e8eef9;color:#2b4a86}
li{margin:.35rem 0;list-style:none}ul{padding-left:0}.what{font-weight:600}.src{color:#666;font-size:.85rem}
table.cal{border-collapse:collapse;width:100%;margin:.6rem 0 1.2rem;font-size:.9rem}
table.cal td{border-top:1px solid #eee;padding:.25rem .5rem;vertical-align:top}
table.cal td.d{white-space:nowrap;width:5.5rem;color:#444}
tr.weekend td{background:#fafafa;color:#888}tr.off td{background:#fff8e6}
.k{display:inline-block;font-size:.75rem;border-radius:3px;padding:0 .35rem;margin-right:.35rem;color:#fff}
.k.course{background:#2b4a86}.k.holiday{background:#8a1c14}.k.term{background:#7a5a00}.k.deadline{background:#b3261e}.k.cutoff{background:#5b2d8a}.k.marker{background:#1d6b2f}
.ent{display:block;margin:.1rem 0}
"""


_KIND_WORD = {"course": "course", "holiday": "holiday", "term": "no classes", "deadline": "deadline",
              "cutoff": "cutoff", "marker": "term"}


def _render_calendar_html(rv: Review) -> list[str]:
    e = html.escape
    parts = ["<h2>The term, day by day</h2>",
             "<p>Every day from the first day of classes to the end of the examination period. "
             "Blue is the outline's own events, red a holiday or a deadline, amber a day without classes, "
             "purple a cutoff the institution's rules imply, green the term's own markers.</p>"]
    if rv.calendar_note:
        parts.append(f"<p class='src'>Not on the calendar: {e(rv.calendar_note)}.</p>")
    if not rv.calendar:
        parts.append("<p>No calendar could be built.</p>")
        return parts
    month = None
    for day in rv.calendar:
        if (day.when.year, day.when.month) != month:
            if month is not None:
                parts.append("</table>")
            month = (day.when.year, day.when.month)
            parts.append(f"<h3>{day.when.strftime('%B %Y')}</h3><table class='cal'>")
        cls = "off" if day.off else ("weekend" if day.weekend else "")
        cells = []
        for en in day.entries:
            src = ""
            if en.source and en.source != "the outline":
                src = re.sub(r"\[(https?://[^\s\]]+), read ([0-9-]+)\]", r"<span class='src'>[<a href='\1'>source</a>, read \2]</span>", e(en.source))
                if not src.startswith("<span"):
                    src = f"<span class='src'>({src})</span>"
            cells.append(f"<span class='ent'><span class='k {en.kind}'>{_KIND_WORD[en.kind]}</span>{e(en.label)} {src}</span>")
        parts.append(f"<tr class='{cls}'><td class='d'>{day.when.strftime('%a %d')}</td><td>{''.join(cells)}</td></tr>")
    parts.append("</table>")
    return parts


def render_html(rv: Review, title: str = "Course outline review") -> str:
    c = rv.counts()
    e = html.escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)}</title><style>{_CSS}</style></head><body>",
             f"<h1>{e(title)}</h1>",
             f"<div class='summary'><span class='v {rv.verdict()}'>{rv.verdict()}</span> {c['Fix']} to fix, {c['Unknown']} unknown, "
             f"{c['Correct']} correct, {c['Note']} notes. Reviewed as a {e(rv.level)} course against {e(rv.pack)}; "
             f"policies applied: {e(', '.join(rv.policies) or 'none')}."]
    if rv.term_end:
        parts.append(f"<br>Last day of classes taken as {rv.term_end.isoformat()} ({e(rv.term_end_source)}).")
    parts.append("</div>")
    parts += _render_calendar_html(rv)
    for key, heading in _SECTIONS:
        fs: list[inst.Finding] = getattr(rv, key)
        parts.append(f"<h2>{e(heading)}</h2><ul>")
        if not fs:
            parts.append("<li>Nothing to report.</li>")
        for f in fs:
            detail = e(f.detail)
            detail = re.sub(r"\[(https?://[^\s\]]+), read ([0-9-]+)\]", r"<span class='src'>[<a href='\1'>source</a>, read \2]</span>", detail)
            parts.append(f"<li><span class='v {f.verdict}'>{f.verdict}</span><span class='what'>{e(f.what)}</span>: {detail}</li>")
        parts.append("</ul>")
    parts.append("<h2>What the clerk did not do</h2><ul>"
                 "<li>It did not judge the teaching, the workload or the fairness of the outline: the conscience does that in a separate report.</li>"
                 "<li>It did not rewrite the outline: the scribe does that on request, in the format you want.</li>"
                 "<li>Every rule is quoted from the institution's own page with the date it was read; a check marked as the clerk's observation is not a rule.</li>"
                 "</ul></body></html>")
    return "\n".join(parts)
