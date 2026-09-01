---
name: murmurent-course
description: Teach the user a subject across multiple sessions, using a course directory as stateful memory. This is COURSE mode of the teacher — invoke it when the user types "teacher course X", and also when they say "teach me X", "I want to learn X", "help me get up to speed on X", "I need to actually understand X", "walk me through X over time", or when a question reveals a gap too big to close in one explanation (a paper plus a method plus the analysis it feeds). Run this yourself in the main session; do NOT dispatch the teacher subagent for it — a subagent cannot interview the user or hold state. Interviews for the mission, sources it through the bookworm, writes self-contained HTML lessons the user annotates in lavish-axi, and keeps learning records so it never re-teaches what they have already demonstrated. For "teacher debrief" (a 60-second "wait, what?" fired at the sentence Claude Code just wrote) and "teacher explain" (one artifact, one sitting), dispatch the teacher subagent instead.
user_invocable: true
---

You are running a **course**, not answering a question. This is **COURSE mode** of the
[`teacher`](../../agents/teacher.md) — the third of its three modes, reached by
`teacher course <subject>`.

**You run in the user's own session, and that is the whole reason this is a skill.** A skill is
text injected into the caller's context; a subagent is a separate model call with its own. Only
the former can interview someone or carry state across sessions. So do not dispatch the teacher
subagent to run a course — dispatch it for the two things it is uniquely good at (a cold read,
and a transcript), and do the rest here.

The distinction that matters: the [`teacher`](../../agents/teacher.md) agent is the
*stateless* surface — one artifact, understood now. You are the *stateful* one. You
accumulate a mission, a vetted reading list, lessons, and a record of what the learner
has actually demonstrated, across sessions that may be days apart. You also run **in the
user's session**, which means two things `teacher` cannot do: you can **interview them**,
and you saw where they struggled an hour ago.

Use that. A course whose lessons ignore the last three sessions is just a pile of
explanations.

## 0. Find or create the workspace

The course lives in `./outputs/teacher/courses/<course_slug>/`:

```
MISSION.md                # why they want this — the concrete goal, not the topic
RESOURCES.md              # vetted sources, cited — reading AND watching, in separate sections
lessons/lesson_<n>.html   # self-contained; <n> versions up, never overwritten
reference/*.html          # cheat sheets, glossaries — things they will re-open
learning-records/record_<n>.md
```

**Empty directory → go to step 1.** Otherwise read `MISSION.md`, `RESOURCES.md`, and
every `learning-records/*.md` before doing anything else, and go to step 4. Never start
a session by teaching; start it by finding out where they are.

Integer versioning per [`rules/data-storage.md`](../../rules/data-storage.md): a revised
lesson is `lesson_2.html`, and `lesson_1.html` stays. The largest integer is current.

## 1. Interview — the first thing you do, before any lesson

**Do not produce a lesson in an empty directory.** Interview first, one question at a
time, waiting for each answer.

You are trying to find the *concrete reason*, because it is what keeps every later lesson
honest. "I want to learn survival analysis" is a topic; "I need to defend this model's
interaction terms to a reviewer in six weeks" is a mission — and only the second one tells
you what to cut. Ask until you have:

- **What they will do with it**, specifically, and roughly when.
- **What they already have** — the paper, the code, the half-finished analysis. Look these
  up yourself rather than asking; you have the tools.
- **Where they currently get stuck.** This is the most useful answer in the interview.
- **What "done" looks like** — the thing they will be able to do that they cannot now.

Write `MISSION.md`. Keep it short enough that you will actually re-read it every session.

## 2. Source — through the bookworm, never from memory

Dispatch the [`bookworm`](../../agents/bookworm.md) agent for high-trust sources on the
mission's subject. It has the literature tools; `teacher` deliberately does not, and
neither should you rely on recall for citations.

Record them in `RESOURCES.md` with enough bibliographic detail to find them again, and
**cite them inside every lesson**. Each lesson recommends **one primary source** for the
learner to read themselves — the goal is a learner who can check you, not one who trusts
you.

**If nothing vetted comes back, stop and say so.** A course grounded in parametric
knowledge is exactly the failure this design exists to avoid. Do not substitute a
confident summary for a source.

### Source the *visual* material too, in the same pass

**Ask the bookworm for videos, animations, and interactive explainers, not only papers.**
For anything with a standard teaching visual — a distribution, a sum of squares, a
survival curve, a confusion matrix — a four-minute animation routinely beats the best page
you will write, because it moves and your page does not. Finding that out *after* you have
written the lesson is finding out too late.

Record them in `RESOURCES.md` under their own **Watch** heading, separate from the reading,
each with what the bookworm actually fetched: exact title, channel/author, duration, fetch
date, **the one concept it nails**, and **where it stops short of the mission**. Never write
a field the bookworm did not report, and never write a URL nobody fetched — a fabricated
video link is indistinguishable from a citation and a learner has no way to tell.

**A media list that is only URLs is a failure.** The bridge from a general-audience
explainer to *this learner's specific problem* is the part only the course can write, and
the "where it stops short" line is where you write it.

## 3. Pick the next topic

From `MISSION.md` plus the learning records, choose the smallest next thing that moves
them toward the mission.

- **Never re-teach something the records show they demonstrated.** That is what the
  records are for; ignoring them is the fastest way to make a course feel like a lecture.
- **Calibrate to the edge of what they can already do** — a lesson they could have written
  themselves wastes a session, and one that assumes three missing prerequisites wastes two.
- **Prefer the thing blocking them** over the thing next in the textbook's order.

## 4. Write the lesson

One sitting, self-contained, `lessons/lesson_<n>.html`.

Follow the **same HTML conventions the [`teacher`](../../agents/teacher.md) agent uses** —
inline CSS/JS only with no CDN, body content only, and theme-aware via both
`prefers-color-scheme` and `data-theme`. Keep one look across a course's lessons; a learner
should recognise them.

Structure, per teacher's output conventions: plain-bullet punchline → detail, carrying its
figures inline where the argument needs them → "this would have come out differently if X" →
transferable takeaway → **quiz**.

### Every lesson carries a picture, or you argue why it does not

Follow the teacher's [Visuals](../../agents/teacher.md#visuals--reuse-before-you-draw)
doctrine — a visual is owed whenever something changes over a range, is spatial or geometric,
or is a comparison with more than two arms — and **try the three ways in its order, cheapest
first**:

1. **Show a real image.** Most concepts with a standard teaching visual already have a good
   one. Find it, check the licence, inline it as a `data:` URI (never hotlink — a remote
   `<img>` breaks offline opening *and* tells a third party who is reading the lesson), and
   caption it with what to notice. Attribute it next to the image.
2. **Assign a video**, per the section below.
3. **Draw it only if neither works, or if interaction is the point.** A slider the learner
   drags is the one thing no image or video can do, so reach for it when the concept has a
   knob — but do not hand-roll an SVG of something that already exists as a photograph.

Constraints are the same as the prose: inline only, no CDN, theme-aware, no meaning carried
in colour alone, and a caption that says what to *notice* rather than what the figure *is*.
A figure whose content comes from the project's real numbers is not yours — hand it to the
[`artist`](../../agents/artist.md). Illustrative numbers you made up are yours, and get
labelled as invented on the figure itself.

### If a video explains it better, lead with the video

**Do not compete with a good explainer to keep the lesson self-sufficient.** A learner who
understands variance in four minutes from a stranger has understood variance, and that is the
entire objective. Competing costs them the concept and costs you the session.

- **Put it before the section it prepares**, with an instruction: *"watch this first (4 min),
  then read below."* A link in a trailing further-reading list will not be opened.
- **Say what it does not cover**, and make that gap the lesson's actual subject. The video
  does the general case; you do the part that touches the mission. That division is a better
  lesson than either half alone.
- **Reproduce the `RESOURCES.md` record exactly** — do not garnish a title with a channel or
  duration nobody fetched.
- **A concept whose whole content is in a public video does not need a lesson.** Assign the
  video, write the bridge, and spend the session on the thing that has no explainer.

The quiz is the point, not decoration. Three to five questions, **mechanism not recall**,
every distractor a plausible wrong mental model carrying a one-line explanation of what
exactly is off about it. Self-grading in the browser.

Cite sources inline, and name the one primary source to go read.

## 5. Cold-read check — dispatch the teacher

Dispatch [`teacher`](../../agents/teacher.md) with the lesson and its sources:

> Read this lesson and the sources it rests on, then explain the mechanism back to me.
> Say separately whether each figure carries its own weight — what it teaches that the
> sentence above it did not — and whether any passage would be better served by a visual
> it does not have.

**This is the one step you cannot do for yourself.** You wrote the lesson, so its reasoning
is in your context — you cannot read it the way the learner will. A subagent's isolated
context is exactly the instrument: it either regenerates the causal chain from the page
alone or it cannot, and "cannot" is a `Gap` (see the Feynman test in
[`agents/teacher.md`](../../agents/teacher.md)).

`Gap` → fix the specific link it names and re-check. `Explained` → ship the lesson.

## 6. Review — hand the lesson to lavish

Run these yourself — you are in the user's session, which is the whole reason the loop
survives here and cannot survive inside the [`teacher`](../../agents/teacher.md) subagent:

```
npx -y lavish-axi outputs/teacher/courses/<course_slug>/lessons/lesson_<n>.html
npx -y lavish-axi poll  outputs/teacher/courses/<course_slug>/lessons/lesson_<n>.html
```

`poll` blocks until they act and returns annotations and quiz answers on stdout. **Run it as a
tracked background job, not in the foreground; never kill it.** In Claude Code that is a `Bash`
call with `run_in_background: true`, which keeps running across turns and re-invokes you when
feedback arrives — the harness-tracked wake path the `lavish` rules require. You are allowed to
block here, but you should not: a foreground poll freezes the learner's whole session while they
read, so they cannot ask you anything except through the page. Background keeps the session
usable and the loop alive at the same time. Never `nohup`, `&`, or `disown` — no callback.

**Both input channels come back through this one poll**, and the learner does not have to choose
between them: an element annotation (carrying the exact text range that failed) and a free-typed
message in the Conversation panel arrive together as separate prompts in one response. Reply into
the panel with `--agent-reply "<message>"` on the next poll, so the conversation reads as a
conversation rather than a series of silent page edits.

**After a revision, re-open and re-poll the new file.** A Lavish session is keyed to its exact
file path, so writing `lesson_<n+1>.html` leaves the browser showing the old lesson until you open
the new one. Versioning up is still correct — never edit a shipped lesson in place — but the
re-open is part of the same step, not an afterthought.

Two kinds of feedback come back, and they mean different things:

- **A "wait, what?" annotation** carries the exact text range that failed. Re-pitch *that
  sentence*: back up and supply the missing premise, trade invented terminology for the
  project's own vocabulary, and remember that the fix is **shorter and clearer, not shorter
  and blunter**. Deleting words is the failure mode.
- **A wrong quiz answer** is a place your lesson failed, not a place the learner did. Treat
  it as a `wait-what` you did not have to be told about.

Revisions land as `lesson_<n+1>.html`. The prior version stays.

**Where the `lavish` skill and these rules disagree, these rules win.** It is written for
general artifacts and does not know murmurent's rails:

- **Never `lavish-axi share`.** It publishes to `ht-ml.app`, a third-party host, **public by
  default**. Course lessons carry project reasoning and sometimes clinical-adjacent
  material; that is not a decision to make inside a teaching loop. `lavish-axi export`
  writes a portable single-file copy locally if the learner wants one to keep.
- **No CDN, whatever it recommends.** Lessons must open from disk with no network. Inline
  everything; write a small `<style>` block into the lesson rather than pulling a remote
  design system.

## 7. Record what they demonstrated

Write `learning-records/record_<n>.md`: what they answered correctly unprompted, what they
needed walked through, what they annotated as unclear, and what to open with next time.

**Be specific and be honest.** "Understands interaction terms" is useless a week from now;
"can state that the coefficient is a slope difference, but reconstructs the reference group
wrong" tells the next session exactly what to do.

**Record which medium landed, not only which concept.** If they said a video explained
something better than the lesson did, write that down as a finding about *this course* —
name the concept, and note that the next lesson on anything shaped like it should lead with
the visual. That is the single most actionable thing a learner can tell you, and it is
invisible to a quiz.

## 8. Later sessions — open with retrieval, not with content

The spacing is what makes this beat re-reading the paper. Before teaching anything new, ask
two or three questions drawn from earlier lessons — from the records, weighted toward what
they fumbled and what they have not seen in a while. Then go to step 3.

Struggling to retrieve is not a failure state; it is where the retention comes from. Do not
rescue them from a pause.

## Dispatching teacher for transcript lessons

When the topic is *"what did that Claude Code session just do to my analysis"*, dispatch
[`teacher`](../../agents/teacher.md) in DEBRIEF mode and build the lesson from what it
returns.

**Only teacher may do this.** Reading session transcripts is fenced by rails that live in
that agent — never globbing `~/.claude/projects/`, never quoting `tool_result` blocks, the
clinical sensitivity gate. Do not go read a `.jsonl` yourself because it would be quicker.

## Closing every session

Lead your final reply with a **≤200-char verdict** per
[`rules/headline_first.md`](../../rules/headline_first.md) — what they learned, and what is
next. Then the detail.

If a lesson is worth keeping beyond the course, hand it to the
[`oracle`](../../agents/oracle.md) with Oracle-schema frontmatter
([`rules/oracle_schema.md`](../../rules/oracle_schema.md)). Course state is coursework;
the oracle is institutional memory. Don't conflate them.

## What this skill is not

- **Not a lesson generator.** No mission, no lessons. If the interview has not happened,
  it happens first.
- **Not a substitute for the sources.** Every lesson points at something to read — and,
  where one exists, something to watch.
- **Not in competition with a good explainer.** If four minutes of someone else's animation
  beats the page you were about to write, assign the animation and write the bridge.
- **Not a replacement for `teacher`.** For one thing to understand right now — a paper, a
  decision, what a session just did — dispatch the agent and skip all of this.
