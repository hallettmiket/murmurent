"""
Purpose: ``murmurent institution``: validate, show, check, date, walk and
         refresh an institution pack (issue #291). Thin click wrappers over
         :mod:`murmurent.core.institution`; the clerk agent runs these.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: A pack directory (``--pack``, ``$MURMURENT_INSTITUTION_PACK``, or the
       centre's ``unique_name`` under ``institution/``).
Output: Reports on stdout. ``validate`` and ``check`` exit 1 when something
        needs fixing so an agent can stop on it. ``refresh`` is a dry run
        unless ``--apply``.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import click

from ..core import institution as inst


def _pack(name: str | None) -> inst.Pack:
    root = inst.find_pack(name)
    if root is None:
        have = [p.name for p in inst.list_packs()]
        click.echo("No institution pack found. Pass --pack <name or directory>, set "
                   "$MURMURENT_INSTITUTION_PACK, or create one with `murmurent institution init`."
                   + (f" Packs here: {', '.join(have)}." if have else ""), err=True)
        sys.exit(2)
    try:
        return inst.load_pack(root)
    except inst.PackError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)


def _date(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        click.echo(f"`{text}` is not a date; write it as YYYY-MM-DD.", err=True)
        sys.exit(2)


_PACK_OPT = click.option("--pack", "pack_name", default=None,
                         help="Pack name under institution/, or a pack directory.")


@click.group("institution", help="The institution pack: dated, sourced facts the clerk answers from.")
def institution_group() -> None:
    pass


@institution_group.command("init", help="Scaffold a pack in institution/<unique_name>/ (never overwrites).")
@click.argument("unique_name")
@click.option("--name", required=True, help="The institution's display name.")
@click.option("--domain", "domains", multiple=True, required=True,
              help="A domain the clerk may read from (repeatable), e.g. uwo.ca.")
@click.option("--keeper", default="bookworm", show_default=True, help="Who keeps the pack.")
@click.option("--seed-thesis", is_flag=True,
              help="Write procedures/thesis_examination.yaml from the seed built into murmurent.")
@click.option("--root", default=None, help="Folder to create the pack in (default: institution/).")
def institution_init(unique_name: str, name: str, domains: tuple[str, ...], keeper: str,
                     seed_thesis: bool, root: str | None) -> None:
    from ..core import paper_package as pp

    base = Path(root).expanduser() if root else inst.institution_root()
    written = inst.init_pack(base / unique_name, name=name, unique_name=unique_name,
                             domains=list(domains), keeper=keeper,
                             thesis_procedure=pp.seed_thesis_procedure() if seed_thesis else None)
    for p in written:
        click.echo(f"wrote {p}")
    if not written:
        click.echo("nothing written: every file already exists")
    click.echo(f"Next: fill directory.yaml and calendar.yaml, each fact with source and date_read, "
               f"then `murmurent institution validate --pack {unique_name}`.")


@institution_group.command("validate", help="Check the pack's shape: every fact sourced, dated, on-domain.")
@_PACK_OPT
def institution_validate(pack_name: str | None) -> None:
    pack = _pack(pack_name)
    problems = inst.validate_pack(pack)
    stale = inst.stale_facts(pack)
    for p in problems:
        click.echo(f"error: {p}")
    for f, age in stale:
        click.echo(f"stale: {f.kind} `{f.key}` read "
                   + (f"{age} days ago" if age is not None else "on an unknown date")
                   + f" (limit {pack.max_fact_age_days})")
    n = len(pack.facts())
    click.echo(f"{pack.name} ({pack.root}): {n} fact(s), {len(problems)} error(s), {len(stale)} stale.")
    if problems:
        sys.exit(1)


@institution_group.command("show", help="Show one thing from the pack: office, procedure, holiday, term, course, letterhead, packs.")
@click.argument("kind", type=click.Choice(["office", "procedure", "holiday", "term", "deadline", "course",
                                           "letterhead", "packs", "offices", "holidays", "terms", "procedures",
                                           "fact", "facts"]))
@click.argument("key", required=False)
@click.option("--no-verify", is_flag=True, help="Do not re-read an office's page even if the fact is older than verify_after_days.")
@_PACK_OPT
def institution_show(kind: str, key: str | None, no_verify: bool, pack_name: str | None) -> None:
    import yaml

    if kind == "packs":
        for p in inst.list_packs():
            click.echo(p.name + ("  (selected)" if inst.find_pack(pack_name) == p else ""))
        return
    pack = _pack(pack_name)

    def emit(doc, fact=None) -> None:
        click.echo(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).rstrip())
        if fact is not None:
            note = inst.age_note(fact, pack)
            if note:
                click.echo(f"note: {note}")

    if kind in ("office", "offices"):
        if key:
            o = pack.office(key)
            if o is None:
                near = ", ".join(str(x.get("office")) for x in pack.offices[:12])
                click.echo(f"Unknown: no office `{key}` in the pack. Nearest it holds: {near}")
                sys.exit(1)
            emit(o, o)
            if not no_verify and inst.needs_verify(pack, o):
                fact = next(f for f in pack.facts() if f.kind == "office" and f.data is o)
                change = inst.verify_fact(pack, fact)
                click.echo(f"verified on read: {change.status}" + (f" ({change.detail})" if change.detail else "")
                           + (f"; now read {date.today().isoformat()}" if change.status == "confirmed" else ""))
        else:
            for o in pack.offices:
                click.echo(f"- {o.get('office')}: {o.get('person')} ({o.get('title')}) read {o.get('date_read')}")
    elif kind in ("fact", "facts"):
        fs = pack.learned
        if key:
            fs = inst.recall(pack, key)
            fs = [f for f in fs if f.get("kind") == "fact"]
            if not fs:
                click.echo(f"Unknown: nothing remembered on `{key}`."); sys.exit(1)
        for f in fs:
            click.echo(f"- {f.get('question')}\n  {f.get('answer')}\n  [{f.get('source')}, read {f.get('date_read')}]")
            note = inst.age_note(f, pack)
            if note:
                click.echo(f"  note: {note}")
    elif kind in ("holiday", "holidays"):
        hs = pack.holidays()
        if key:
            hs = [h for h in hs if key.lower() in str(h.get("name", "")).lower() or key in str(h.get("date", ""))]
            if not hs:
                click.echo(f"Unknown: no holiday matching `{key}`."); sys.exit(1)
        for h in sorted(hs, key=lambda h: str(h.get("date"))):
            click.echo(f"- {h.get('date')}: {h.get('name')} [{h.get('source')}, read {h.get('date_read')}]")
    elif kind in ("term", "terms"):
        ts = pack.terms()
        if key:
            ts = [t for t in ts if key.lower() in str(t.get("name", "")).lower()]
            if not ts:
                click.echo(f"Unknown: no term matching `{key}`."); sys.exit(1)
        for t in ts:
            emit(t, t); click.echo("")
    elif kind == "deadline":
        ds = pack.deadlines()
        if key:
            ds = [d for d in ds if key.lower() in str(d.get("name", "")).lower()]
            if not ds:
                click.echo(f"Unknown: no named deadline matching `{key}`."); sys.exit(1)
        for d in ds:
            emit(d, d); click.echo("")
    elif kind in ("procedure", "procedures"):
        if not key:
            for name, proc in pack.procedures.items():
                click.echo(f"- {name}: {proc.get('title', '')} (read {proc.get('read_on', '?')}, "
                           f"{len(proc.get('steps') or [])} steps)")
            return
        if key not in pack.procedures:
            click.echo(f"Unknown: no procedure `{key}`. Have: {', '.join(pack.procedures) or 'none'}")
            sys.exit(1)
        click.echo(inst.format_walk(pack, key, inst.walk_procedure(pack, key)))
    elif kind == "course":
        if not key:
            for c in pack.courses.get("cache") or []:
                click.echo(f"- {c.get('code')}: {c.get('title')} ({len(c.get('sections') or [])} sections, read {c.get('date_read')})")
            rule = pack.courses.get("fetch")
            if rule:
                click.echo(f"fetch rule: {rule.get('method', 'GET')} {rule.get('url')}")
            return
        c = inst.course(pack, key)
        if c is None:
            click.echo(f"Unknown: `{key}` is not in the course cache; `murmurent institution refresh --kind course` "
                       "re-reads the cache, and `fetch-course` adds one.")
            sys.exit(1)
        emit(c, c)
    elif kind == "letterhead":
        lh = pack.letterhead()
        if not lh:
            click.echo("Unknown: the pack has no templates/letterhead.yaml."); sys.exit(1)
        emit(lh, lh)


@institution_group.command("check", help="Check a document's office holders, emails, addresses and letterhead against the pack; with --policy, a syllabus against the institution's rules.")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--policy", default=None, help="Apply this policy's rules (policies/<name>.yaml) to the document, e.g. course_outlines.")
@click.option("--term", default="", help="With --policy: the term whose last day of classes to count from, when the document does not say.")
@_PACK_OPT
def institution_check(path: str, policy: str | None, term: str, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if policy:
        try:
            findings = inst.check_syllabus(pack, text, policy, term_name=term)
        except inst.PackError as exc:
            click.echo(str(exc), err=True)
            sys.exit(2)
    else:
        findings = inst.check_document(pack, text)
    verdict = inst.check_verdict(findings)
    click.echo(f"{verdict}: {len(findings)} finding(s) in {path} against {pack.name}.")
    for f in findings:
        click.echo("- " + f.format())
    if verdict == "Fix":
        sys.exit(1)


@institution_group.command("review", help="Review a whole course outline: every rule for its level, the schedule against holidays and non-instructional days, the grade weights, and what it leaves unclear. Writes an HTML report.")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--level", type=click.Choice(["undergraduate", "graduate"]), default="undergraduate", show_default=True)
@click.option("--term", default="", help="The term whose last day of classes to count from, when the outline does not say.")
@click.option("--html", "html_out", default=None, help="Where to write the HTML report (default ./outputs/clerk/<name>_review.html).")
@click.option("--markdown", is_flag=True, help="Print the report as Markdown instead of the one-line-per-finding list.")
@_PACK_OPT
def institution_review(path: str, level: str, term: str, html_out: str | None, markdown: bool, pack_name: str | None) -> None:
    from ..core import course_review as cr
    pack = _pack(pack_name)
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        rv = cr.review_course(pack, text, level=level, term_name=term)
    except inst.PackError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    title = f"Course outline review: {Path(path).stem}"
    out = Path(html_out) if html_out else Path("outputs/clerk") / f"{Path(path).stem}_review.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cr.render_html(rv, title), encoding="utf-8")
    if markdown:
        click.echo(cr.render_markdown(rv, title))
    else:
        c = rv.counts()
        click.echo(f"{rv.verdict()}: {c['Fix']} to fix, {c['Unknown']} unknown, {c['Correct']} correct, {c['Note']} notes ({level}, {pack.name}; policies: {', '.join(rv.policies) or 'none'}).")
        for key, heading in cr._SECTIONS:
            fs = getattr(rv, key)
            if fs:
                click.echo(f"{heading}:")
            for f in fs:
                click.echo(f"- {f.verdict}: {f.what}: {f.detail}")
    click.echo(f"HTML report: {out}")
    if rv.verdict() == "Fix":
        sys.exit(1)


@institution_group.command("date", help="A date N working days from DATE (--days -25, --days 5), skipping weekends and the pack's holidays.")
@click.argument("start")
@click.option("--days", "n", required=True, type=int,
              help="Working days to move: negative for before, positive for after, 0 to land on a working day.")
@_PACK_OPT
def institution_date(start: str, n: int, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    d = _date(start)
    if (name := inst.is_holiday(pack, d)) and n == 0:
        click.echo(f"{d.isoformat()} is {name}; the next working day is "
                   f"{inst.working_days_from(pack, d, 0).isoformat()}.")
        return
    click.echo(inst.explain_date(pack, d, n))


@institution_group.command("walk", help="The steps of a procedure with their forms and dates from an anchor date.")
@click.argument("name")
@click.option("--anchor", default=None, help="The date the deadlines count from (the defence date, say).")
@click.option("--variant", default=None, help="A per-variant deadline key, e.g. doctoral or masters.")
@click.option("--done", default="", help="Comma-separated step numbers already done.")
@click.option("--next", "only_next", is_flag=True, help="Only the next three steps.")
@_PACK_OPT
def institution_walk(name: str, anchor: str | None, variant: str | None, done: str,
                     only_next: bool, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    done_nums = [int(x) for x in done.split(",") if x.strip().isdigit()]
    try:
        steps = inst.walk_procedure(pack, name, _date(anchor) if anchor else None, done_nums, variant)
    except inst.PackError as exc:
        click.echo(f"Unknown: {exc}"); sys.exit(1)
    if only_next:
        steps = inst.next_steps(steps)
    click.echo(inst.format_walk(pack, name, steps))


@institution_group.command("fetch-course", help="Run the pack's course fetch rule for one course and cache it.")
@click.argument("subject")
@click.argument("number")
@click.option("--apply", is_flag=True, help="Write the result into courses.yaml.")
@_PACK_OPT
def institution_fetch_course(subject: str, number: str, apply: bool, pack_name: str | None) -> None:
    import yaml

    pack = _pack(pack_name)
    try:
        entry = inst.fetch_course(pack, subject.upper(), number)
    except inst.PackError as exc:
        click.echo(f"Unknown: {exc}"); sys.exit(1)
    click.echo(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True).rstrip())
    if apply:
        cache = [c for c in (pack.courses.get("cache") or [])
                 if not (isinstance(c, dict) and str(c.get("code", "")).upper().startswith(entry["code"].upper()))]
        cache.append(entry)
        pack.courses["cache"] = cache
        inst.write_pack(pack)
        click.echo(f"wrote {pack.root / inst.COURSES_FILE}")


@institution_group.command("refresh", help="Re-read each fact from its source (pack domains only) and report what changed. Dry run unless --apply.")
@click.option("--apply", is_flag=True, help="Write today's date_read on confirmed facts and refresh the course cache.")
@click.option("--kind", "kinds", multiple=True, help="Only these fact kinds (office, holiday, term, deadline, course, template, procedure_source).")
@_PACK_OPT
def institution_refresh(apply: bool, kinds: tuple[str, ...], pack_name: str | None) -> None:
    pack = _pack(pack_name)
    changes = inst.refresh(pack, apply=apply, kinds=kinds or None)
    click.echo(inst.format_changes(changes).rstrip())
    if apply:
        click.echo(f"applied: confirmed facts now read {date.today().isoformat()}; changed facts left for a person to edit.")
    else:
        click.echo("dry run; add --apply to write.")


@institution_group.command("recall", help="What the pack already holds on a question: learned facts and offices, best first.")
@click.argument("question")
@_PACK_OPT
def institution_recall(question: str, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    found = inst.recall(pack, question)
    if not found:
        click.echo("nothing remembered on that; look it up on the institution's own pages and `learn` it")
        sys.exit(1)
    for f in found[:8]:
        if f["kind"] == "fact":
            click.echo(f"- {f.get('question')}\n  {f.get('answer')}\n  [{f.get('source')}, read {f.get('date_read')}]")
        else:
            click.echo(f"- {f.get('office')}: {f.get('person')} ({f.get('title')}) [{f.get('source')}, read {f.get('date_read')}]")
        note = inst.age_note(f, pack)
        if note:
            click.echo(f"  note: {note}")
        if inst.needs_verify(pack, f):
            click.echo(f"  verify before relying on it: `murmurent institution verify \"{f.get('question') or f.get('office')}\"`")


@institution_group.command("lookup", help="Without a web search: crawl from the pack's hub pages for pages on the institution's own site that mention the question.")
@click.argument("question")
@click.option("--max-pages", default=inst.LOOKUP_MAX_PAGES, show_default=True, type=int)
@_PACK_OPT
def institution_lookup(question: str, max_pages: int, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    hubs = (pack.meta.get("lookup") or {}).get("pages") or []
    if not hubs:
        click.echo("the pack lists no lookup.pages in institution.yaml (a websites A-Z, say); nothing to crawl from", err=True)
        sys.exit(2)
    hits = inst.lookup(pack, question, max_pages=max_pages)
    if not hits:
        click.echo(f"no page reached from {', '.join(hubs)} mentions that; a search limited to the pack's domains is the next step")
        sys.exit(1)
    for h in hits[:8]:
        click.echo(f"- {h.title or h.url}\n  {h.url}\n  {h.snippet}")


@institution_group.command("learn", help="Remember a fact read on one of the institution's pages: the page is fetched and must state it.")
@click.argument("question")
@click.option("--answer", required=True, help="The answer, in one or two sentences.")
@click.option("--source", required=True, help="The page it was read on (must be on the pack's domains).")
@click.option("--evidence", default="", help="A short phrase that is on the page (default: the answer itself).")
@click.option("--office", default=None, help="Record it as an office holder instead: the office name; --answer is the person.")
@click.option("--title", default="", help="With --office: the holder's title as the page gives it.")
@click.option("--email", default="", help="With --office: the office's public email.")
@click.option("--address", default="", help="With --office: the campus address.")
@click.option("--no-confirm", is_flag=True, help="Do not fetch the page (tests only; the page is normally checked).")
@_PACK_OPT
def institution_learn(question: str, answer: str, source: str, evidence: str, office: str | None, title: str,
                      email: str, address: str, no_confirm: bool, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    try:
        if office:
            entry = inst.learn_office(pack, office=office, person=answer, title=title, email=email, address=address,
                                      source=source, confirm=not no_confirm)
            click.echo(f"learned office {office}: {answer} [{source}, read {entry['date_read']}]")
        else:
            entry = inst.learn_fact(pack, question=question, answer=answer, source=source, evidence=evidence,
                                    confirm=not no_confirm)
            click.echo(f"learned: {question}\n  {answer}\n  [{source}, read {entry['date_read']}]")
    except inst.PackError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


@institution_group.command("verify", help="Re-read one remembered fact or office from its page now; restamp it if the page still says so.")
@click.argument("key")
@click.option("--no-apply", is_flag=True, help="Report only; do not restamp.")
@_PACK_OPT
def institution_verify(key: str, no_apply: bool, pack_name: str | None) -> None:
    pack = _pack(pack_name)
    want = inst._norm(key)
    fact = next((f for f in pack.facts() if f.kind in ("fact", "office") and
                 (inst._norm(f.key) == want or want in inst._norm(f.key))), None)
    if fact is None:
        click.echo(f"Unknown: nothing remembered under `{key}`."); sys.exit(1)
    change = inst.verify_fact(pack, fact, apply=not no_apply)
    click.echo(f"{change.status.upper()}: {fact.kind} `{fact.key}`" + (f": {change.detail}" if change.detail else "")
               + f" [{fact.source}, read {fact.data.get('date_read')}]")
    if change.status == "changed":
        click.echo("the page no longer states this; read it and `learn` the current fact, or leave it for a person")
        sys.exit(1)


@institution_group.command("learn-rule", help="Remember a rule read on one of the institution's pages, quoted as the page words it, into policies/<policy>.yaml.")
@click.argument("policy")
@click.option("--id", "rule_id", required=True, help="A short id for the rule, e.g. tests_last_3_weeks.")
@click.option("--says", required=True, help="The rule, verbatim from the page.")
@click.option("--source", required=True, help="The page (must be on the pack's domains).")
@click.option("--heading", default="", help="The heading the rule sits under on the page.")
@click.option("--check-kind", default="note", type=click.Choice(list(inst.RULE_KINDS)), show_default=True,
              help="How the check command applies it; note = by reading.")
@click.option("--weeks", default=None, type=int, help="For the last-weeks checks.")
@click.option("--percent", default=None, type=float, help="For min_weight_before_date.")
@click.option("--by", default=None, help="For min_weight_before_date: the date (YYYY-MM-DD).")
@click.option("--no-confirm", is_flag=True, help="Do not fetch the page (tests only).")
@_PACK_OPT
def institution_learn_rule(policy: str, rule_id: str, says: str, source: str, heading: str, check_kind: str,
                           weeks: int | None, percent: float | None, by: str | None, no_confirm: bool,
                           pack_name: str | None) -> None:
    pack = _pack(pack_name)
    check: dict = {"kind": check_kind}
    if weeks is not None:
        check["weeks"] = weeks
    if percent is not None:
        check["percent"] = percent
    if by:
        check["by"] = by
    try:
        e = inst.learn_rule(pack, policy=policy, rule_id=rule_id, says=says, source=source, heading=heading,
                            check=check, confirm=not no_confirm)
    except inst.PackError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(f"learned rule {policy}/{rule_id}: \"{says}\" [{source}, read {e['date_read']}]")
