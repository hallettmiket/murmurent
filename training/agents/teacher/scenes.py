"""The teacher movie: narration in the teacher's own voice, plain-statement cards checked against agents/teacher.md,
the real exchange in transcript.md, and a drawn permutation test (the one visual the movie makes itself)."""
import random

from PIL import ImageDraw

from lib.agent_movie import AgentSpec, Exchange, Extra, Quote
from lib.draw import AMBER, DIM, F_LABEL, F_SMALL, F_TINY, MUTED, PANEL, RED, TEAL, TEXT, P, appear, heading, rrect, text_c

# --------------------------------------------------------------------------- #
# The permutation test, drawn: twelve serum and twelve control colonies, their
# labels shuffled again and again, and the pile of gaps that chance makes.
# Synthetic numbers, seeded, so the picture is the same on every render.
# --------------------------------------------------------------------------- #

_rng = random.Random(3403)   # seed chosen so exactly one shuffle in 5000 reaches the real gap, as in the real run
N = 12
SERUM = [_rng.gauss(0, 0.6) for _ in range(N)]
CONTROL = [_rng.gauss(0, 0.6) for _ in range(N)]
SERUM = sorted(5.12 + v - sum(SERUM) / N for v in SERUM)      # the averages of the real example
CONTROL = sorted(4.17 + v - sum(CONTROL) / N for v in CONTROL)
VALUES = SERUM + CONTROL
REAL_GAP = sum(SERUM) / N - sum(CONTROL) / N
SHUFFLES = 5000
PERMS: list[list[int]] = []
GAPS: list[float] = []
for _ in range(SHUFFLES):
    idx = list(range(2 * N))
    _rng.shuffle(idx)
    PERMS.append(idx)
    a = sum(VALUES[i] for i in idx[:N]) / N
    b = sum(VALUES[i] for i in idx[N:]) / N
    GAPS.append(a - b)
BINS = 31
LO, HI = -1.25, 1.25


def _hist(k: int) -> list[int]:
    counts = [0] * BINS
    for g in GAPS[:k]:
        b = int((g - LO) / (HI - LO) * BINS)
        counts[max(0, min(BINS - 1, b))] += 1
    return counts


def s_permutation(img, t, sc):
    heading(img, t, "The idea, drawn: shuffle the labels and count")
    d = ImageDraw.Draw(img)
    t_shuffle = sc.when("shuffle them")
    t_pile = sc.when("pile is")
    # how many shuffles have been done at time t: slowly at first, then all of them
    if t < t_shuffle:
        k = 0
    elif t < t_pile:
        p = P(t, t_shuffle, t_pile - t_shuffle)
        k = max(1, int(SHUFFLES ** p))
    else:
        k = SHUFFLES
    # left panel: the colonies, coloured by their current label
    rrect(d, (70, 100, 590, 600), PANEL, None, 14, 0)
    perm = PERMS[min(k, SHUFFLES) - 1] if k > 0 else list(range(2 * N))
    label_of = {i: ("serum" if j < N else "control") for j, i in enumerate(perm)}
    d.text((90, 110), "serum" if k == 0 else "called serum", font=F_LABEL, fill=AMBER)
    d.text((340, 110), "control" if k == 0 else "called control", font=F_LABEL, fill=TEAL)
    groups = {"serum": [], "control": []}
    for i, v in enumerate(VALUES):
        groups[label_of[i]].append(v)
    for gi, (name, col, x0) in enumerate((("serum", AMBER, 90), ("control", TEAL, 340))):
        vals = groups[name]
        for j, v in enumerate(vals):
            cx = x0 + 20 + (j % 4) * 52
            cy = 160 + (j // 4) * 52
            r = 6 + int((v - 3.3) * 6)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        mean = sum(vals) / max(len(vals), 1)
        d.text((x0, 330), f"average {mean:.2f} mm", font=F_SMALL, fill=col)
    gap = (sum(groups["serum"]) / N) - (sum(groups["control"]) / N)
    d.text((90, 380), ("real gap" if k == 0 else f"shuffle {min(k, SHUFFLES):,}: gap") + f"  {gap:+.2f} mm",
           font=F_LABEL, fill=TEXT)
    d.text((90, 420), f"the real gap is {REAL_GAP:+.2f} mm", font=F_TINY, fill=MUTED)
    appear(img, t, sc.when("labels would not matter"),
           lambda dd: dd.text((90, 470), "If serum did nothing, the labels\nwould not matter. So shuffle them.",
                              font=F_SMALL, fill=TEXT), 0.5, 8)
    # right panel: the pile of gaps
    x0, y0, w, h = 620, 100, 590, 500
    rrect(d, (x0, y0, x0 + w, y0 + h), PANEL, None, 14, 0)
    d.text((x0 + 20, y0 + 10), "gaps that chance alone made", font=F_LABEL, fill=TEXT)
    base = y0 + h - 60
    bw = (w - 60) / BINS
    counts = _hist(k)
    top = max(max(counts), 1)
    for b, c in enumerate(counts):
        if c == 0:
            continue
        bh = (h - 140) * c / top
        bx = x0 + 30 + b * bw
        d.rectangle([bx + 1, base - bh, bx + bw - 1, base], fill=DIM if k < SHUFFLES else TEAL)
    d.line([x0 + 30, base, x0 + w - 30, base], fill=MUTED, width=2)
    for v in (-1.0, 0.0, 1.0):
        x = x0 + 30 + (v - LO) / (HI - LO) * (w - 60)
        text_c(d, x, base + 8, f"{v:+.0f} mm", F_TINY, MUTED)
    xr = x0 + 30 + (REAL_GAP - LO) / (HI - LO) * (w - 60)
    d.line([xr, y0 + 50, xr, base], fill=RED, width=3)
    d.text((xr - 150, y0 + 46), "the real gap", font=F_LABEL, fill=RED)
    d.text((x0 + 20, base + 30), f"{min(k, SHUFFLES):,} of {SHUFFLES:,} shuffles", font=F_SMALL, fill=TEXT)
    if k >= SHUFFLES:
        beyond = sum(1 for g in GAPS if g >= REAL_GAP)
        appear(img, t, t_pile + 0.3,
               lambda dd: dd.text((x0 + 300, base + 30), f"as big as the real one: {beyond} of {SHUFFLES:,}",
                                  font=F_SMALL, fill=RED), 0.5, 6)


SPEC = AgentSpec(
    agent="teacher",
    title="The teacher",
    tagline="Plain words, like Feynman: in a minute in chat, on a page with a quiz, or over weeks",
    colour=AMBER,
    icon="star",
    intro=["I am the teacher. I explain things in plain words: a sentence that lost you, in a minute; "
           "a method or a paper, in one sitting; a whole subject, over weeks. I answer to Feynman."],
    does=[
        Quote("Re-explains the sentence that just lost you, in under a minute.", "lost you"),
        Quote("Explains a method or a paper in one sitting, in chat or on a page you annotate.", "method"),
        Quote("Writes a quiz with the page, so you can test whether it landed.", "quiz"),
        Quote("Teacher course starts a weeks-long course in your own session.", "weeks"),
    ],
    does_narration=[
        "When a sentence Claude Code just wrote lost you, I say it again in plain words, in under a minute.",
        "I explain a method or a paper in one sitting: in chat, or on request as a page where you mark "
        "what lost you, ending in a short quiz that grades itself. For a subject that takes weeks, I run a "
        "course in your own session, with lessons that remember what you have learned."],
    refuses=[
        Quote("Feynman's rule: if it cannot be said simply, it is not understood yet.", "simply"),
        Quote("At most three technical terms, each defined; otherwise it says Gap.", "three"),
        Quote("Shows a real image or video first; draws only when needed.", "image"),
        Quote("A debrief stays offline, because your session is private.", "offline"),
    ],
    refuses_narration=[
        "I work by Feynman's rule: if it cannot be said simply, it is not understood yet. AI loves jargon, and "
        "jargon is where a reader gets lost. So I allow myself at most three technical terms, each defined, and "
        "when I cannot honestly explain, I say Gap rather than sound fluent.",
        "I show a real image or a video I have checked before drawing anything, and I link only to what I have "
        "actually opened. A debrief stays offline, because your session is private."],
    examples=[
        Exchange("1", ["A real run. A wet-lab biologist asks what a permutation test is, and why the example "
                       "uses five thousand of them.",
                       "My answer is Explained: short bullets, each term defined, the real numbers from the "
                       "analysis, which I re-ran, and a takeaway for the next problem."],
                 [("read the analysis code", True), ("re-run it", True), ("web search", False)]),
    ],
    extras=[
        Extra("permutation",
              ["On a page I would also draw it. Serum colonies on the left, controls on the right, and the "
               "real gap between their averages, nearly one millimetre.",
               "If serum did nothing, the labels would not matter. So I shuffle them, measure the gap again, "
               "and add it to the pile. Again and again, five thousand times.",
               "The pile is what chance alone produces. The real gap sits far out on the right, reached once "
               "in five thousand shuffles. That is the whole test; the quiz asks what fifty shuffles would change."],
              s_permutation, "The idea, drawn"),
    ],
    prompt="teacher explain what a permutation test is, for a wet-lab biologist",
    give="Debrief: nothing. Explain: the method or paper. Course: the subject.",
    verdicts="Explained / Gap. Gap means it says plainly that it cannot deliver.",
    howto_narration=[
        "The first line is Explained, or Gap when I cannot honestly deliver.",
        "Say who it is for when you type your request, such as a wet-lab biologist; otherwise I write for a colleague "
        "from a neighbouring field."],
    directions=[
        ("teacher debrief", "The sentence that lost you, said again in plain words, in under a minute."),
        ("teacher explain what a permutation test is, as a page", "A page you can annotate, with a drawn figure and a quiz that grades itself."),
        ("teacher course on survival analysis", "Lessons over weeks that remember what you have learned."),
    ],
    directions_narration=[
        "Three things to type: debrief, at the sentence that lost you; explain, with the method or paper, "
        "adding 'as a page' for the figure and the quiz; and course, with the subject."],
    docs=["skills/murmurent-course/SKILL.md"],
)
