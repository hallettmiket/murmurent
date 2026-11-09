"""
Purpose: Render the explainer "A thesis an examiner can question": what a paper
         package and a thesis package are, what the candidate, the examiners and
         the committee each do with one, how the docent answers, and how the
         defence talk and the Western paperwork come out of the same manifest.
         The picture moves with the words: people in the room are drawn as
         figures, claims are drawn as links that light up, chapters assemble
         into the thesis, questions flow from an examiner into the log, and the
         talk's slides share out the minutes. Every terminal scene shows the
         real output of the commands run on examples/thesis_example; every
         docent scene shows a real exchange kept in docent_transcript.md.
Author: Mike Hallett (with Claude Code, the artist)
Date: 2026-11-07
Input: docent_transcript.md (same folder); fonts from /System/Library/Fonts
       (macOS). ffmpeg on PATH. Python with PIL and numpy only. No outside
       images: every figure and icon is drawn here.
Output: thesis_package.mp4 (1280x720, 20 frames a second, captions burned in,
        no audio) and thesis_package.srt (the narration with timings, to voice
        with ElevenLabs and to use as subtitles), both in this folder. Frames
        are piped straight to ffmpeg; nothing is left on disk.
Usage: python3 training/thesis_package/make_movie.py [--out DIR] [--stills DIR]
       --stills DIR also saves one PNG every five seconds, for checking.
How it is built: each scene is a function draw(img, t, sc) that paints the
       picture at time t seconds. sc.when("some words") returns the moment the
       narrator reaches those words, so a bullet, a link or a figure can appear
       exactly then. Change the narration and the picture follows.
"""

from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1280, 720
FPS = 20
CHARS_PER_SECOND = 30     # typewriter speed for commands and questions
WORDS_PER_SECOND = 2.5    # narration pace used to time captions
LEAD = 0.4                # quiet moment at the start of a scene
TAIL = 0.6                # and at the end
XFADE = 0.4               # crossfade between scenes, seconds

# Palette. Amber is the candidate and the things the candidate writes, teal is
# the examiners and the evidence, lavender is the docent, sand the coordinator.
BG = (17, 28, 52)
BG2 = (26, 42, 76)
PANEL = (28, 44, 78)
PANEL2 = (36, 56, 96)
TEXT = (238, 238, 232)
MUTED = (160, 170, 194)
DIM = (92, 106, 140)
AMBER = (244, 162, 97)
TEAL = (52, 190, 170)
LAV = (178, 150, 235)
SAND = (214, 190, 140)
SKY = (110, 170, 235)
RED = (226, 100, 100)
TERM_BG = (12, 16, 28)
CAPTION_BG = (8, 11, 22)

FONT_DIR = Path("/System/Library/Fonts")


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = "Menlo.ttc" if mono else "HelveticaNeue.ttc"
    return ImageFont.truetype(str(FONT_DIR / name), size, index=1 if bold else 0)


F_BIG = font(60, bold=True)
F_SUB = font(30)
F_H = font(38, bold=True)
F_BODY = font(26)
F_LABEL = font(22, bold=True)
F_SMALL = font(20)
F_TINY = font(17)
F_CAP = font(25)
F_MONO = font(19, mono=True)
F_MONO_S = font(16, mono=True)
F_MONO_T = font(14, mono=True)

_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def tw(text: str, f) -> float:
    return _MEASURE.textlength(text, font=f)


# --------------------------------------------------------------------------- #
# Small maths
# --------------------------------------------------------------------------- #


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def P(t: float, t0: float, dur: float = 0.5) -> float:
    """Progress 0..1 of something that starts at t0 and lasts dur."""
    return clamp((t - t0) / dur)


def eout(x: float) -> float:
    return 1 - (1 - x) ** 3


def eio(x: float) -> float:
    return 3 * x * x - 2 * x ** 3


def eback(x: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def mix(c1, c2, x: float):
    return tuple(int(lerp(a, b, x)) for a, b in zip(c1, c2))


def dim(c, k: float = 0.7):
    return tuple(int(v * k) for v in c)


# --------------------------------------------------------------------------- #
# Background, captions and generic drawing helpers
# --------------------------------------------------------------------------- #

_BG_CACHE: list[Image.Image] = []


def background() -> Image.Image:
    if not _BG_CACHE:
        y = np.linspace(0, 1, H)[:, None]
        x = np.linspace(0, 1, W)[None, :]
        k = (0.65 * y + 0.35 * (1 - x)) ** 1.2
        arr = np.zeros((H, W, 3), dtype=np.float32)
        for i in range(3):
            arr[:, :, i] = BG2[i] + (BG[i] - BG2[i]) * k
        arr[::40, ::40] += 14           # a faint dot grid
        _BG_CACHE.append(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)))
    return _BG_CACHE[0].copy()


def wrap(text: str, f, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split(" "):
            trial = (cur + " " + w).strip()
            if tw(trial, f) <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def caption(img: Image.Image, text: str) -> None:
    if not text:
        return
    lines = wrap(text, F_CAP, W - 200)
    lh = 33
    band = lh * len(lines) + 26
    box = (0, H - band, W, H)
    region = img.crop(box)
    img.paste(Image.blend(region, Image.new("RGB", region.size, CAPTION_BG), 0.86), box[:2])
    d = ImageDraw.Draw(img)
    y = H - band + 13
    for line in lines:
        d.text(((W - tw(line, F_CAP)) / 2, y), line, font=F_CAP, fill=TEXT)
        y += lh


def appear(img: Image.Image, t: float, t0: float, fn, dur: float = 0.5, rise: int = 18) -> None:
    """Draw fn(draw) fading in and rising `rise` pixels from t0."""
    a = P(t, t0, dur)
    if a <= 0:
        return
    if a >= 1:
        fn(ImageDraw.Draw(img))
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fn(ImageDraw.Draw(layer))
    alpha = layer.getchannel("A").point(lambda v: int(v * eout(a)))
    layer.putalpha(alpha)
    img.paste(layer, (0, int(rise * (1 - eout(a)))), layer)


def text_c(d, cx: float, y: float, s: str, f, fill=TEXT) -> None:
    d.text((cx - tw(s, f) / 2, y), s, font=f, fill=fill)


def rrect(d, xy, fill=PANEL, outline=None, r: int = 14, w: int = 3) -> None:
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=w)


def heading(img: Image.Image, t: float, text: str, y: int = 34, t0: float = 0.0) -> None:
    def f(d):
        d.text((64, y), text, font=F_H, fill=AMBER)
    appear(img, t, t0, f, 0.5, 10)
    d = ImageDraw.Draw(img)
    x1 = 64 + tw(text, F_H) * eout(P(t, t0 + 0.1, 0.7))
    d.line([64, y + 52, x1, y + 52], fill=TEAL, width=3)


def card(d, x, y, w, h, title="", sub="", colour=TEAL, fill=PANEL, fsub=F_TINY, ftitle=F_LABEL) -> None:
    rrect(d, (x, y, x + w, y + h), fill=fill, outline=colour)
    yy = y + 10
    if title:
        d.text((x + 14, yy), title, font=ftitle, fill=colour)
        yy += ftitle.size + 8
    if sub:
        for line in wrap(sub, fsub, w - 28):
            d.text((x + 14, yy), line, font=fsub, fill=TEXT)
            yy += fsub.size + 5


def line_prog(d, a, b, p: float, colour=MUTED, width: int = 3) -> None:
    if p <= 0:
        return
    x = lerp(a[0], b[0], p)
    y = lerp(a[1], b[1], p)
    d.line([a, (x, y)], fill=colour, width=width)


def dashed(d, a, b, colour=DIM, width: int = 3, dash: int = 10) -> None:
    n = max(int(math.hypot(b[0] - a[0], b[1] - a[1]) // dash), 1)
    for i in range(0, n, 2):
        p0, p1 = i / n, min((i + 1) / n, 1)
        d.line([(lerp(a[0], b[0], p0), lerp(a[1], b[1], p0)), (lerp(a[0], b[0], p1), lerp(a[1], b[1], p1))],
               fill=colour, width=width)


_GLOW: dict = {}


def glow(img: Image.Image, x: float, y: float, r: int, colour, strength: float = 1.0) -> None:
    key = (colour, r)
    if key not in _GLOW:
        s = np.arange(-r * 2, r * 2 + 1)
        xx, yy = np.meshgrid(s, s)
        a = np.exp(-((xx ** 2 + yy ** 2) / (r * r)) * 1.1) * 255
        arr = np.zeros((len(s), len(s), 4), dtype=np.uint8)
        arr[:, :, 0], arr[:, :, 1], arr[:, :, 2] = colour
        arr[:, :, 3] = a.astype(np.uint8)
        _GLOW[key] = Image.fromarray(arr, "RGBA")
    g = _GLOW[key]
    if strength < 1:
        g = g.copy()
        g.putalpha(g.getchannel("A").point(lambda v: int(v * strength)))
    img.paste(g, (int(x - r * 2), int(y - r * 2)), g)


def pulse(img, a, b, t: float, period: float = 1.6, colour=AMBER, t0: float = 0.0, r: int = 7) -> None:
    """A bright dot travelling from a to b again and again."""
    if t < t0:
        return
    p = ((t - t0) % period) / period
    x, y = lerp(a[0], b[0], eio(p)), lerp(a[1], b[1], eio(p))
    glow(img, x, y, r, colour, 0.9)
    ImageDraw.Draw(img).ellipse([x - 3, y - 3, x + 3, y + 3], fill=TEXT)


# --------------------------------------------------------------------------- #
# Sprites: people and icons drawn big and shrunk, so edges are smooth
# --------------------------------------------------------------------------- #

_SPR: dict = {}


def person(colour, h: int = 110, kind: str = "person") -> Image.Image:
    key = ("p", colour, h, kind)
    if key in _SPR:
        return _SPR[key]
    S = 4
    w = int(h * 0.86)
    im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = w * S / 2
    hs = h * S
    body, headc = dim(colour, 0.78), mix(colour, (255, 255, 255), 0.22)
    if kind == "bot":
        d.rounded_rectangle([cx - .36 * hs, .55 * hs, cx + .36 * hs, 1.3 * hs], radius=int(.1 * hs), fill=body)
        d.rounded_rectangle([cx - .12 * hs, .66 * hs, cx + .12 * hs, .86 * hs], radius=int(.02 * hs), fill=TEXT)
        d.line([cx, .66 * hs, cx, .86 * hs], fill=dim(colour, .6), width=int(.02 * hs))
        d.rounded_rectangle([cx - .3 * hs, .1 * hs, cx + .3 * hs, .5 * hs], radius=int(.12 * hs), fill=headc)
        for ex in (-.12, .12):
            d.ellipse([cx + ex * hs - .06 * hs, .24 * hs, cx + ex * hs + .06 * hs, .36 * hs], fill=BG)
        d.line([cx, .1 * hs, cx, .0 * hs], fill=headc, width=int(.03 * hs))
        d.ellipse([cx - .05 * hs, -.04 * hs, cx + .05 * hs, .06 * hs], fill=AMBER)
    else:
        d.ellipse([cx - .4 * hs, .5 * hs, cx + .4 * hs, 1.3 * hs], fill=body)
        d.ellipse([cx - .2 * hs, .14 * hs, cx + .2 * hs, .52 * hs], fill=headc)
        if kind == "cap":
            d.polygon([(cx - .32 * hs, .16 * hs), (cx, .04 * hs), (cx + .32 * hs, .16 * hs), (cx, .27 * hs)], fill=(34, 36, 52))
            d.rectangle([cx - .14 * hs, .2 * hs, cx + .14 * hs, .29 * hs], fill=(34, 36, 52))
            d.line([cx + .27 * hs, .16 * hs, cx + .27 * hs, .36 * hs], fill=AMBER, width=int(.025 * hs))
        if kind == "glasses":
            for ex in (-.08, .08):
                d.ellipse([cx + ex * hs - .06 * hs, .28 * hs, cx + ex * hs + .06 * hs, .4 * hs], outline=dim(colour, .45), width=int(.02 * hs))
    out = im.resize((w, h), Image.LANCZOS)
    _SPR[key] = out
    return out


def paste_c(img: Image.Image, spr: Image.Image, cx: float, cy: float, scale: float = 1.0, alpha: float = 1.0) -> None:
    if scale <= 0.02:
        return
    if abs(scale - 1) > 0.01:
        spr = spr.resize((max(int(spr.width * scale), 1), max(int(spr.height * scale), 1)), Image.LANCZOS)
    if alpha < 1:
        spr = spr.copy()
        spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    img.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)), spr)


def figure(img, t, t0, cx, bottom, colour, label="", sub="", h=108, kind="person", lab_w=190, label_below=True) -> None:
    """A person who pops in at t0, with a name and a line of detail under."""
    p = P(t, t0, 0.5)
    if p <= 0:
        return
    sp = person(colour, h, kind)
    paste_c(img, sp, cx, bottom - h / 2, eback(p), clamp(p * 3))
    if label and p >= 1 or (label and p > 0.4):
        a = P(t, t0 + 0.25, 0.4)
        def f(d):
            text_c(d, cx, bottom + 8, label, F_LABEL, colour)
            yy = bottom + 8 + F_LABEL.size + 4
            for ln in wrap(sub, F_TINY, lab_w):
                if ln:
                    text_c(d, cx, yy, ln, F_TINY, MUTED)
                    yy += F_TINY.size + 3
        appear(img, t, t0 + 0.25, f, 0.4, 8)


class SD:
    """Draw in a 100x100 box, scaled up for smooth sprites."""

    def __init__(self, d, k):
        self.d, self.k = d, k

    def p(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def line(self, pts, fill, w=4):
        self.d.line(self.p(pts), fill=fill, width=max(1, int(w * self.k)), joint="curve")

    def ell(self, box, fill=None, outline=None, w=4):
        self.d.ellipse([v * self.k for v in box], fill=fill, outline=outline, width=max(1, int(w * self.k)))

    def rr(self, box, r=6, fill=None, outline=None, w=4):
        self.d.rounded_rectangle([v * self.k for v in box], radius=int(r * self.k), fill=fill, outline=outline,
                                 width=max(1, int(w * self.k)))

    def poly(self, pts, fill):
        self.d.polygon(self.p(pts), fill=fill)

    def arc(self, box, a0, a1, fill, w=4):
        self.d.arc([v * self.k for v in box], a0, a1, fill=fill, width=max(1, int(w * self.k)))

    def text(self, cx, cy, s, size, fill):
        f = font(int(size * self.k), bold=True)
        self.d.text((cx * self.k, cy * self.k), s, font=f, fill=fill, anchor="mm")


def _ic_doc(s, c, a):
    s.rr((20, 8, 80, 92), 7, outline=c, w=5)
    for y in (32, 48, 64):
        s.line([(32, y), (68, y)], a, 4)
    s.line([(32, 80), (52, 80)], a, 4)


def _ic_chart(s, c, a):
    s.line([(16, 14), (16, 86), (88, 86)], c, 5)
    for x, y in ((28, 52), (46, 30), (64, 62)):
        s.rr((x, y, x + 14, 82), 2, fill=a)


def _ic_code(s, c, a):
    s.line([(38, 30), (14, 50), (38, 70)], c, 6)
    s.line([(62, 30), (86, 50), (62, 70)], c, 6)
    s.line([(56, 22), (44, 78)], a, 5)


def _ic_data(s, c, a):
    for y in (14, 42, 70):
        s.ell((20, y, 80, y + 22), outline=c, w=5)
    s.line([(20, 25), (20, 81)], c, 5)
    s.line([(80, 25), (80, 81)], c, 5)
    s.ell((20, 14, 80, 36), fill=mix(c, BG, .6), outline=c, w=5)


def _ic_slides(s, c, a):
    s.rr((8, 16, 92, 72), 6, outline=c, w=5)
    s.line([(22, 58), (36, 44), (50, 52), (74, 28)], a, 5)
    s.line([(50, 72), (50, 88)], c, 5)
    s.line([(34, 90), (66, 90)], c, 5)


def _ic_check(s, c, a):
    s.rr((18, 8, 82, 92), 7, outline=c, w=5)
    for y in (30, 52, 74):
        s.line([(28, y), (34, y + 6), (44, y - 6)], a, 4)
        s.line([(52, y), (72, y)], c, 4)


def _ic_clock(s, c, a):
    s.ell((10, 10, 90, 90), outline=c, w=6)
    s.line([(50, 50), (50, 24)], a, 6)
    s.line([(50, 50), (68, 60)], a, 6)


def _ic_cloud(s, c, a):
    for b in ((14, 44, 46, 76), (30, 24, 70, 64), (52, 38, 88, 74)):
        s.ell(b, fill=c)
    s.rr((30, 52, 70, 76), 4, fill=c)
    s.line([(16, 14), (86, 90)], BG, 14)
    s.line([(16, 14), (86, 90)], a, 7)


def _ic_scale(s, c, a):
    s.line([(50, 18), (50, 82)], c, 5)
    s.line([(28, 84), (72, 84)], c, 5)
    s.line([(16, 30), (84, 30)], c, 5)
    for cx in (22, 78):
        s.line([(cx, 30), (cx - 10, 56)], c, 3)
        s.line([(cx, 30), (cx + 10, 56)], c, 3)
        s.arc((cx - 14, 40, cx + 14, 70), 0, 180, c, 5)
    s.line([(10, 8), (90, 92)], BG, 13)
    s.line([(10, 8), (90, 92)], a, 7)


def _ic_lock(s, c, a):
    s.rr((24, 44, 76, 90), 8, fill=c)
    s.arc((32, 12, 68, 66), 180, 360, c, 7)
    s.line([(33, 40), (33, 46)], c, 7)
    s.line([(67, 40), (67, 46)], c, 7)
    s.ell((44, 58, 56, 70), fill=BG)
    s.line([(50, 66), (50, 78)], BG, 5)


def _ic_pencil(s, c, a):
    s.poly([(16, 84), (22, 62), (62, 22), (78, 38), (38, 78)], c)
    s.poly([(16, 84), (22, 62), (38, 78)], a)
    s.line([(10, 8), (90, 92)], BG, 13)
    s.line([(10, 8), (90, 92)], a, 7)


def _ic_stamp(s, c, a):
    s.rr((20, 8, 80, 88), 7, outline=c, w=5)
    for y in (26, 40, 54):
        s.line([(32, y), (68, y)], c, 4)
    s.ell((46, 56, 90, 100), outline=a, w=5)
    s.line([(56, 80), (64, 88), (80, 68)], a, 5)


def _ic_star(s, c, a):
    pts = []
    for i in range(10):
        r = 46 if i % 2 == 0 else 20
        ang = -math.pi / 2 + i * math.pi / 5
        pts.append((50 + r * math.cos(ang), 52 + r * math.sin(ang)))
    s.poly(pts, c)


def _ic_cal(s, c, a):
    s.rr((12, 18, 88, 90), 8, outline=c, w=5)
    s.rr((12, 18, 88, 40), 8, fill=c)
    s.line([(32, 8), (32, 26)], a, 6)
    s.line([(68, 8), (68, 26)], a, 6)
    for x in (28, 50, 72):
        for y in (54, 74):
            s.ell((x - 5, y - 5, x + 5, y + 5), fill=a)


def _ic_tick(s, c, a):
    s.line([(18, 54), (40, 76), (82, 24)], c, 11)


def _ic_cross(s, c, a):
    s.line([(24, 24), (76, 76)], c, 11)
    s.line([(76, 24), (24, 76)], c, 11)


def _ic_mag(s, c, a):
    s.ell((12, 10, 62, 60), outline=c, w=8)
    s.line([(56, 56), (88, 88)], c, 10)


def _ic_folder(s, c, a):
    s.rr((10, 24, 90, 84), 7, outline=c, w=5)
    s.poly([(10, 24), (10, 14), (38, 14), (46, 24)], c)
    s.line([(24, 52), (76, 52)], a, 4)
    s.line([(24, 66), (60, 66)], a, 4)


ICONS = {"doc": _ic_doc, "chart": _ic_chart, "code": _ic_code, "data": _ic_data, "slides": _ic_slides,
         "check": _ic_check, "clock": _ic_clock, "cloud": _ic_cloud, "scale": _ic_scale, "lock": _ic_lock,
         "pencil": _ic_pencil, "stamp": _ic_stamp, "star": _ic_star, "cal": _ic_cal, "tick": _ic_tick,
         "cross": _ic_cross, "mag": _ic_mag, "folder": _ic_folder}


def icon(img, name, cx, cy, size=64, colour=TEAL, accent=AMBER, scale=1.0, alpha=1.0) -> None:
    key = ("i", name, size, colour, accent)
    if key not in _SPR:
        k = 4
        im = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
        ICONS[name](SD(ImageDraw.Draw(im), size * k / 100), colour, accent)
        _SPR[key] = im.resize((size, size), Image.LANCZOS)
    paste_c(img, _SPR[key], cx, cy, scale, alpha)


def mono_block(img, items, x, y, w, h, f=F_MONO, title=None, wrap_lines=True) -> None:
    """A terminal-like panel. items: str or (str, colour). Scrolls to the newest line."""
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=TERM_BG, outline=(58, 70, 104), width=2)
    ty = y + 12
    if title:
        d.text((x + 16, ty), title, font=F_TINY, fill=MUTED)
        ty += 28
    lh = f.size + 7
    rows: list[tuple[str, tuple]] = []
    for it in items:
        s, c = (it, None) if isinstance(it, str) else it
        if c is None:
            c = TEXT
            if s.startswith("$ "):
                c = AMBER
            elif s.startswith(("OK", "Located", "wrote", "planned")):
                c = TEAL
        parts = wrap(s, f, w - 36) if (wrap_lines and s.strip()) else [s]
        # wrap() collapses leading spaces, so keep indentation of the original
        indent = len(s) - len(s.lstrip(" "))
        for i, p in enumerate(parts):
            rows.append((" " * indent + p if i == 0 else p, c))
    max_rows = (y + h - ty - 8) // lh
    for s, c in rows[-max_rows:]:
        d.text((x + 16, ty), s, font=f, fill=c)
        ty += lh


class Term:
    """A typed terminal session: commands type out, output lines drop in."""

    def __init__(self, transcript: str, lead: float = 0.6, line_s: float = 0.12) -> None:
        self.events: list[tuple[float, float, str]] = []
        t = lead
        for line in transcript.strip("\n").split("\n"):
            if line.startswith("$ "):
                dur = len(line) / CHARS_PER_SECOND
                self.events.append((t, t + dur, line))
                t += dur + 0.6
            else:
                self.events.append((t, t + 0.01, line))
                t += line_s if line.strip() else 0.3
        self.dur = t + 0.6

    def lines(self, t: float) -> list[str]:
        shown: list[str] = []
        for start, end, line in self.events:
            if t < start:
                break
            if line.startswith("$ ") and t < end:
                n = int(2 + (len(line) - 2) * (t - start) / (end - start))
                shown.append(line[:n] + "▌")
                return shown
            shown.append(line)
        shown.append("$ ▌" if int(t * 2) % 2 == 0 else "$ ")
        return shown

    def t_of(self, prefix: str) -> float:
        for start, _, line in self.events:
            if line.startswith(prefix):
                return start
        raise KeyError(prefix)


# --------------------------------------------------------------------------- #
# Scenes
# --------------------------------------------------------------------------- #


@dataclass
class Scene:
    name: str
    narration: list[str]
    draw: object                         # callable(img, t, sc)
    chapter: str | None = None
    min_anim: float = 0.0
    lead: float = LEAD
    tail: float = TAIL
    cues: list[float] = field(default_factory=list)
    durs: list[float] = field(default_factory=list)
    seconds: float = 0.0

    def __post_init__(self) -> None:
        t = self.lead
        for text in self.narration:
            d = max(len(text.split()) / WORDS_PER_SECOND + 0.5, 2.5)
            self.cues.append(t)
            self.durs.append(d)
            t += d
        self.seconds = max(t + self.tail, self.min_anim)

    def when(self, phrase: str) -> float:
        """The moment the narrator reaches these words."""
        for cue, d, text in zip(self.cues, self.durs, self.narration):
            pos = text.find(phrase)
            if pos >= 0:
                n = max(len(text.split()), 1)
                return cue + (d - 0.5) * len(text[:pos].split()) / n
        raise KeyError(f"{self.name}: no such words in the narration: {phrase!r}")

    def caption_at(self, t: float) -> str:
        cur = ""
        for start, text in zip(self.cues, self.narration):
            if t >= start:
                cur = text
        return cur

    def content(self, t: float) -> Image.Image:
        img = background()
        self.draw(img, t, self)
        return img


# --------------------------------------------------------------------------- #
# Content. Transcripts come from real runs on examples/thesis_example
# (murmurent 2026.11.0, 2026-11-07, paths shortened to the package name).
# --------------------------------------------------------------------------- #

T_CHECK = """
$ murmurent paper check paper_example
OK: no findings.

$ murmurent thesis check thesis_example
OK: no findings.
"""

T_BUILD = """
$ murmurent thesis build thesis_example --pdf
chapter 1: introduction from 01_introduction.tex
chapter 2: paper paper_example (1 claims)
chapter 3: chapter from 03_metadata.tex (1 claims)
chapter 4: conclusion from 99_conclusion.tex
wrote build/main.tex
wrote build/claim_map.md
wrote build/main.pdf
"""

T_TALK = """
$ murmurent thesis talk thesis_example --minutes 20
planned 10 slides for 20 minutes
wrote build/talk_plan.md
wrote build/talk.tex
"""

T_PAPERWORK = """
$ murmurent thesis paperwork thesis_example
wrote build/paperwork.md
"""

CLAIM_YAML = [
    "claims:",
    "  - id: c1",
    "    text: Colonies grown in serum are",
    "          larger than controls, and the",
    "          difference holds under permutation.",
    "    where: Results, first paragraph",
    "    figure: fig:signal",
    "    code: exp/1_signal/run_all.py",
    "    data: [data/signal.csv]",
]


def load_docent() -> tuple[dict[str, tuple[str, str, list[str]]], list[str]]:
    """Sections `## <n>`: first line `who: question`, then the reply lines.
    The section `## log` holds the examiner's log, whose own headings are `## HH:MM`."""
    text = (HERE / "docent_transcript.md").read_text()
    head, _, log_text = text.partition("\n## log\n")
    out: dict[str, tuple[str, str, list[str]]] = {}
    for m in re.finditer(r"^## (\d+)\n(.*?)(?=^## |\Z)", head, re.S | re.M):
        body = m.group(2).strip("\n").split("\n")
        who, _, question = body[0].partition(": ")
        reply = body[1:]
        while reply and not reply[0].strip():
            reply.pop(0)
        out[m.group(1)] = (who, question, reply)
    log_lines = [l.replace("**", "") for l in log_text.split("\n")[1:]]
    while log_lines and not log_lines[-1].strip():
        log_lines.pop()
    return out, log_lines


# --------------------------------------------------------------------------- #
# Scene drawing functions
# --------------------------------------------------------------------------- #


def s_title(img, t, sc):
    def head(d):
        for i, s in enumerate(["A thesis an", "examiner can", "question"]):
            d.text((70, 150 + i * 72), s, font=F_BIG, fill=TEXT)
        d.text((72, 390), "Paper packages, thesis packages", font=F_SUB, fill=AMBER)
        d.text((72, 430), "and the docent", font=F_SUB, fill=AMBER)
        d.text((72, 500), "Murmurent 2026.11.0", font=F_SMALL, fill=MUTED)
    appear(img, t, 0.3, head, 0.9, 24)
    hx, hy = 770, 330
    p = P(t, 0.9, 0.6)
    outs = [("doc", "the thesis", (1090, 190), "the thesis, the defence talk"),
            ("slides", "the defence talk", (1130, 330), "the defence talk"),
            ("check", "the paperwork", (1090, 470), "and the paperwork")]
    for ic, lab, pos, ph in outs:
        t0 = sc.when(ph)
        a = P(t, t0, 0.6)
        line_prog(ImageDraw.Draw(img), (hx + 66, hy), pos, eio(a), DIM, 3)
        if a > 0:
            pulse(img, (hx + 66, hy), pos, t, 1.8, AMBER, t0 + 0.6)
        appear(img, t, t0 + 0.2, lambda d, ic=ic: None, 0.1)
        if a > 0:
            icon(img, ic, pos[0], pos[1] - 6, 74, TEAL, AMBER, eback(P(t, t0 + 0.3, 0.5)))
            appear(img, t, t0 + 0.5, lambda d, lab=lab, pos=pos: text_c(d, pos[0], pos[1] + 44, lab, F_LABEL, TEXT), 0.4, 6)
    if p > 0:
        glow(img, hx, hy, 60, AMBER, 0.35 * p)
        d = ImageDraw.Draw(img)
        r = 66 * eback(p)
        d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=PANEL, outline=AMBER, width=4)
        if p > 0.7:
            text_c(d, hx, hy - 24, "claims", F_LABEL, AMBER)
            text_c(d, hx, hy + 2, "and their", F_TINY, MUTED)
            text_c(d, hx, hy + 20, "evidence", F_TINY, MUTED)
        for k, ic in enumerate(["chart", "code", "data"]):
            ang = t * 0.7 + k * 2.094
            icon(img, ic, hx + 108 * math.cos(ang), hy + 108 * math.sin(ang), 38, SKY, AMBER, eout(P(t, 1.3 + k * 0.2, 0.5)))


def s_people(img, t, sc):
    heading(img, t, "Who is in the room")
    d = ImageDraw.Draw(img)
    # the board's table is drawn after the examiners so they sit behind it
    ex = [(520, "External examiner", "from another university", ""),
          (730, "University examiner", "from another Western department", ""),
          (940, "Program examiner", "from the program", ""),
          (1150, "Program examiner", "(one, for a master's)", "")]
    t_board = sc.when("a board of examiners")
    t_ext = sc.when("one from another university")
    ts = [t_ext, sc.when("one from another Western department"), sc.when("one or two from the program"),
          sc.when("one or two from the program") + 0.5]
    for (x, lab, sub, _), t0 in zip(ex, ts):
        p = P(t, t0, 0.5)
        if p > 0:
            paste_c(img, person(TEAL, 128, "glasses"), x, 345 - 64, eback(p), clamp(p * 3))
    appear(img, t, t_board - 0.2, lambda d: rrect(d, (410, 322, 1240, 382), PANEL2, TEAL, 18), 0.6, 10)
    d = ImageDraw.Draw(img)
    for (x, lab, sub, _), t0 in zip(ex, ts):
        def f(d, x=x, lab=lab, sub=sub):
            text_c(d, x, 392, lab, font(19, bold=True), TEAL)
            yy = 392 + 24
            for ln in wrap(sub, F_TINY, 190):
                text_c(d, x, yy, ln, F_TINY, MUTED)
                yy += 21
        appear(img, t, t0 + 0.2, f, 0.4, 8)
    appear(img, t, t_board, lambda d: text_c(d, 825, 112, "The board of examiners", F_LABEL, TEAL), 0.5, 6)
    # candidate and supervisor
    figure(img, t, sc.when("a candidate"), 120, 345, AMBER, "The candidate", "writes the thesis, gives the talk, answers", 128, "cap", 170)
    figure(img, t, sc.when("a supervisor"), 300, 345, SKY, "The supervisor", "attends, does not vote", 128, "person", 150)
    if t > sc.when("does not vote"):
        a = P(t, sc.when("does not vote"), 0.4)
        d = ImageDraw.Draw(img)
        r = 15 * eback(a)
        d.ellipse([345 - r, 250 - r, 345 + r, 250 + r], fill=BG, outline=RED, width=3)
        d.line([345 - 7, 250 - 7, 345 + 7, 250 + 7], fill=RED, width=3)
        d.line([345 - 7, 250 + 7, 345 + 7, 250 - 7], fill=RED, width=3)
    # second sentence: reports, questions, the coordinator
    t_rep = sc.when("writes a preliminary report")
    for i, (x, *_r) in enumerate(ex):
        a = P(t, t_rep + i * 0.25, 0.5)
        if a > 0:
            icon(img, "doc", x, 352, 36, MUTED, TEAL, eback(a))
    appear(img, t, t_rep + 0.4, lambda d: text_c(d, 800, 395 + 0, "", F_TINY), 0.1)
    t_q = sc.when("questions the")
    cand_head = (120, 260)
    for i, (x, *_r) in enumerate(ex):
        ts_i = t_q + i * 0.55
        if t > ts_i:
            pp = ((t - ts_i) % 3.2) / 3.2
            px = lerp(x, cand_head[0] + 40, eio(pp))
            py = lerp(260, cand_head[1], eio(pp)) - 110 * math.sin(math.pi * pp)
            al = min(1.0, pp * 6, (1 - pp) * 4)
            glow(img, px, py, 16, AMBER, 0.55 * al)
            layer = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.ellipse([4, 4, 46, 46], fill=PANEL, outline=(*AMBER, 255), width=3)
            ld.text((25, 25), "?", font=F_LABEL, fill=(*TEXT, 255), anchor="mm")
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * al)))
            img.paste(layer, (int(px - 25), int(py - 25)), layer)
    t_c = sc.when("The program coordinator")
    figure(img, t, t_c, 120, 570, SAND, "", "", 96, "person")
    def coord(d):
        d.text((200, 500), "The Graduate Program Coordinator", font=F_LABEL, fill=SAND)
        d.text((200, 530), "opens the examination in Veritas", font=F_SMALL, fill=TEXT)
    appear(img, t, t_c + 0.3, coord, 0.5, 8)
    t_d = sc.when("confirms the deadlines")
    a = P(t, t_d, 0.5)
    if a > 0:
        icon(img, "cal", 700, 520, 58, SAND, AMBER, eback(a))
        appear(img, t, t_d + 0.2, lambda d: d.text((740, 506), "confirms every deadline and form", font=F_SMALL, fill=TEXT), 0.5, 6)


def s_problem(img, t, sc):
    heading(img, t, "What an examiner gets today")
    t_pdf = sc.when("Today the examiner gets a PDF")
    def pdf(d):
        rrect(d, (70, 130, 330, 470), (232, 232, 226), MUTED, 10, 3)
        for i in range(11):
            d.rectangle([96, 160 + i * 26, 304 - (40 if i % 4 == 3 else 0), 168 + i * 26], fill=(190, 192, 200))
        d.rectangle([96, 160, 200, 176], fill=(150, 155, 170))
        text_c(d, 200, 482, "thesis.pdf", F_LABEL, TEXT)
    appear(img, t, t_pdf, pdf, 0.7, 24)
    # "no code, no data" stamps
    for i, (txt, ph) in enumerate([("no code", "Today the examiner gets a PDF"), ("no data", "Today the examiner gets a PDF"), ("nothing to re-run", "Today the examiner gets a PDF")]):
        t0 = t_pdf + 1.0 + i * 0.9
        def f(d, txt=txt, i=i):
            rrect(d, (96, 515 - 0, 96 + tw(txt, F_SMALL) + 28, 515 + 30), BG, RED, 8, 2)
            d.text((110, 519), txt, font=F_SMALL, fill=RED)
        if i == 0:
            appear(img, t, t0, f, 0.4, 8)
        else:
            def g(d, txt=txt, i=i):
                x = 96 + (tw("no code", F_SMALL) + 36) * (1 if i == 1 else 1) + (0 if i == 1 else tw("no data", F_SMALL) + 36)
                rrect(d, (x, 515, x + tw(txt, F_SMALL) + 28, 545), BG, RED, 8, 2)
                d.text((x + 14, 519), txt, font=F_SMALL, fill=RED)
            appear(img, t, t0, g, 0.4, 8)
    # the questions
    qs = [("Where exactly is the claim made?", "where a claim is made"),
          ("Which script drew figure 12, from which data?", "what is behind a figure"),
          ("Does the result still hold if I re-run it?", "whether a result still holds"),
          ("What does the thesis not address at all?", "what the thesis does not")]
    t_wait = sc.when("all wait for the defence")
    t_few = sc.when("only a few of them")
    # the defence box
    def box(d):
        rrect(d, (905, 130, 1225, 470), PANEL, AMBER, 16, 3)
        d.text((925, 142), "The defence", font=F_LABEL, fill=AMBER)
    appear(img, t, t_wait - 0.3, box, 0.5, 10)
    a_clock = P(t, t_wait, 0.5)
    if a_clock > 0:
        icon(img, "clock", 1150, 160, 40, AMBER, TEXT, eback(a_clock))
        d = ImageDraw.Draw(img)
        # the time bar fills as questions are asked
        fill_p = P(t, t_wait + 0.3, t_few - t_wait + 1.6)
        d.rounded_rectangle([925, 195, 1205, 213], radius=8, fill=BG, outline=DIM, width=2)
        if fill_p > 0:
            d.rounded_rectangle([925, 195, 925 + 280 * fill_p, 213], radius=8, fill=mix(TEAL, RED, fill_p))
        d.text((925, 220), "time runs out", font=F_TINY, fill=MUTED)
    for i, (q, ph) in enumerate(qs):
        t0 = sc.when(ph)
        y = 130 + i * 86
        waits = t > t_wait
        late = i >= 2
        def f(d, q=q, i=i, y=y):
            rrect(d, (400, y, 880, y + 70), PANEL, TEAL if True else MUTED, 12, 2)
            d.text((420, y + 10), q if len(q) < 40 else q, font=F_SMALL, fill=TEXT)
        appear(img, t, t0 - 0.2, f, 0.5, 20)
        if t > t_wait + 0.4 + i * 0.4:
            # a slot in the defence box: the first two get through
            ok = i < 2
            ap = P(t, t_wait + 0.4 + i * 0.4, 0.5)
            ys = 244 + i * 46
            def g(d, ok=ok, ys=ys, i=i):
                col = TEAL if ok else RED
                rrect(d, (925, ys, 1205, ys + 38), BG, col, 10, 2)
                d.text((942, ys + 9), f"question {i + 1}" if ok else f"question {i + 1}: no time", font=F_TINY, fill=col)
            appear(img, t, t_wait + 0.4 + i * 0.4, g, 0.4, 8)
            if ap > 0:
                pulse(img, (880, y + 35), (925, ys + 21), t, 1.4, TEAL if ok else RED, t_wait + 0.4 + i * 0.4, 6)
    if t > t_few:
        appear(img, t, t_few, lambda d: d.text((925, 432), "only a few get answered", font=F_SMALL, fill=AMBER), 0.5, 6)


def s_claim(img, t, sc):
    heading(img, t, "The idea: every claim carries its evidence")
    t0 = sc.when("The idea is small")
    x0, y0, w, hh = 64, 120, 580, 350
    def blk(d):
        pass
    a = P(t, t0, 0.6)
    if a > 0:
        mono_block(img, [], x0, y0, w, hh, title="paper.yaml") if a >= 1 else None
    appear(img, t, t0, lambda d: mono_block(img, [], x0, y0, w, hh, title="paper.yaml") if False else None, 0.1)
    # draw the yaml panel fading in
    def panel(d):
        d.rounded_rectangle([x0, y0, x0 + w, y0 + hh], radius=12, fill=TERM_BG, outline=(58, 70, 104), width=2)
        d.text((x0 + 16, y0 + 12), "paper.yaml", font=F_TINY, fill=MUTED)
    appear(img, t, t0, panel, 0.6, 20)
    d = ImageDraw.Draw(img)
    ly = [y0 + 48 + i * 33 for i in range(len(CLAIM_YAML))]
    for i, line in enumerate(CLAIM_YAML):
        ta = t0 + 0.5 + i * 0.12
        if t >= ta:
            d.text((x0 + 18, ly[i]), line, font=font(21, mono=True), fill=TEXT if i < 5 else MUTED)
    # the four pieces of evidence, each lit by its words
    nodes = [("The sentence it rests on", "doc", "the sentence", 5, 140),
             ("The figure", "chart", "the figure", 6, 240),
             ("The script", "code", "the script", 7, 340),
             ("The data", "data", "the data the script read", 8, 440)]
    nx = 800
    for k, (lab, ic, ph, li, ny) in enumerate(nodes):
        tt = sc.when(ph) if ph != "the sentence" else sc.when("the sentence it rests on")
        a = P(t, tt, 0.6)
        ya = ly[li] + 12
        end = (nx - 6, ny + 35)
        line_prog(d, (x0 + w - 6, ya), end, eio(P(t, tt, 0.5)), TEAL, 3)
        if a > 0:
            sc_ = eback(P(t, tt + 0.25, 0.5))
            def nd(d, lab=lab, ny=ny):
                rrect(d, (nx, ny, nx + 400, ny + 70), PANEL, TEAL, 14, 3)
                d.text((nx + 96, ny + 21), lab, font=F_LABEL, fill=TEXT)
            appear(img, t, tt + 0.2, nd, 0.4, 10)
            icon(img, ic, nx + 48, ny + 35, 48, TEAL, AMBER, sc_)
            glow(img, nx - 6, ny + 35, 10, AMBER, 0.6 * (1 - P(t, tt + 0.5, 1.0)))
    # a chain through the evidence once all four are in
    t_all = sc.when("the data the script read") + 0.8
    for k in range(3):
        a = P(t, t_all + k * 0.35, 0.4)
        d.line([(nx + 200, nodes[k][4] + 70), (nx + 200, nodes[k][4] + 70 + 30 * eio(a))], fill=AMBER, width=3)
    if t > t_all + 1.4:
        appear(img, t, t_all + 1.4, lambda d: d.text((64, 480), "One claim, four places an examiner can look.", font=F_BODY, fill=AMBER), 0.6, 10)


def s_compose(img, t, sc):
    heading(img, t, "The unit is the paper")
    # stage 1: one paper package, with readers
    t_a = sc.when("The unit is the paper")
    t_b = sc.when("A thesis is a composition")
    exit_a = P(t, t_b - 0.2, 0.6)
    if exit_a < 1:
        cx, cy = 640, 290
        a = P(t, t_a, 0.6)
        def pk(d):
            rrect(d, (cx - 160, cy - 80, cx + 160, cy + 80), PANEL, TEAL, 16, 3)
            d.text((cx - 140, cy - 66), "A paper package", font=F_LABEL, fill=TEAL)
            for i, s in enumerate(["the paper", "its claims", "scripts and data"]):
                d.ellipse([cx - 138, cy - 22 + i * 32, cx - 126, cy - 10 + i * 32], fill=AMBER)
                d.text((cx - 112, cy - 30 + i * 32), s, font=F_SMALL, fill=TEXT)
        layer_alpha = 1 - eio(exit_a)
        tmp = Image.new("RGB", (W, H))
        if a > 0:
            base = img.copy()
            appear(base, t, t_a, pk, 0.6, 20)
            if exit_a > 0:
                img.paste(Image.blend(img, base, layer_alpha))
            else:
                img.paste(base)
        t_r = sc.when("gains readers")
        pos = [(260, 200), (260, 400), (1020, 200), (1020, 400)]
        for i, (px, py) in enumerate(pos):
            a2 = P(t, t_r + i * 0.35, 0.5) * layer_alpha
            if a2 > 0:
                paste_c(img, person(TEAL, 96, "glasses" if i % 2 else "person"), px, py, eback(P(t, t_r + i * 0.35, 0.5)), a2)
                if t > t_r + i * 0.35 + 0.5:
                    ph = ((t - t_r - i * 0.35) % 2.4) / 2.4
                    qx = lerp(px + (60 if px < 600 else -60), cx + (-160 if px < 600 else 160), eio(ph))
                    qy = lerp(py - 10, cy + (-30 if py < 300 else 30), eio(ph))
                    glow(img, qx, qy, 12, AMBER, 0.5 * a2 * min(1, ph * 5, (1 - ph) * 4))
    # stage 2: five tiles become a thesis
    if t >= t_b - 0.2:
        tiles = [("Introduction", "the candidate's own", AMBER),
                 ("Paper package", "claims, code, data", TEAL),
                 ("Own chapter", "with its claims", AMBER),
                 ("Paper package", "claims, code, data", TEAL),
                 ("Conclusion", "the candidate's own", AMBER)]
        tx0 = 64
        for i, (a_, b_, col) in enumerate(tiles):
            tt = t_b + i * 0.45
            p = P(t, tt, 0.6)
            if p <= 0:
                continue
            x = tx0 + i * 238
            y = lerp(60, 230, eout(p))
            def f(d, x=x, y=y, a_=a_, b_=b_, col=col):
                rrect(d, (x, y, x + 222, y + 150), PANEL, col, 14, 3)
                d.text((x + 14, y + 12), a_, font=F_LABEL, fill=col)
                d.text((x + 14, y + 42), b_, font=F_TINY, fill=MUTED)
                if col == TEAL:
                    for k in range(3):
                        d.ellipse([x + 14 + k * 26, y + 90, x + 34 + k * 26, y + 110], outline=TEAL, width=2)
                    d.text((x + 14, y + 118), "readable by anyone", font=F_TINY, fill=TEXT)
                else:
                    d.text((x + 14, y + 100), "chapter text", font=F_TINY, fill=TEXT)
            appear(img, t, tt, f, 0.5, 0)
        t_end = t_b + 5 * 0.45 + 0.5
        a = P(t, t_end, 0.7)
        if a > 0:
            d = ImageDraw.Draw(img)
            yb = 405
            x1 = tx0 + 5 * 238 - 16
            d.line([tx0, yb, tx0 + (x1 - tx0) * eio(a), yb], fill=AMBER, width=3)
            for xx in (tx0, x1):
                d.line([xx, yb - 12, xx, yb], fill=AMBER, width=3)
            if a >= 1:
                text_c(d, (tx0 + x1) / 2, yb + 10, "The thesis: the manifest lists them in order", F_BODY, AMBER)
            # legend
            def lg(d):
                d.ellipse([tx0, 478, tx0 + 18, 496], fill=TEAL)
                d.text((tx0 + 28, 474), "a paper package, whole", font=F_SMALL, fill=TEXT)
                d.ellipse([tx0 + 330, 478, tx0 + 348, 496], fill=AMBER)
                d.text((tx0 + 358, 474), "the candidate's own writing", font=F_SMALL, fill=TEXT)
            appear(img, t, t_end + 0.5, lg, 0.5, 6)


def s_package(img, t, sc):
    heading(img, t, "A thesis package")
    t_y = sc.when("The manifest lists")
    d = ImageDraw.Draw(img)
    def yaml(d):
        rrect(d, (40, 130, 330, 470), PANEL, AMBER, 14, 3)
        d.text((66, 140), "thesis.yaml", font=F_LABEL, fill=AMBER)
    appear(img, t, t_y, yaml, 0.6, 20)
    items = [("title, candidate, degree", "The manifest lists"), ("defence date", "the defence date"), ("examiners", "the examiners"),
             ("chapters in order", "the chapters")]
    for i, (s, ph) in enumerate(items):
        tt = sc.when(ph)
        appear(img, t, tt, lambda d, s=s, i=i: (d.ellipse([68, 196 + i * 56, 80, 208 + i * 56], fill=TEAL),
                                                d.text((92, 188 + i * 56), s, font=F_TINY, fill=TEXT)), 0.4, 8)
    cmds = [("check", "is every claim backed?", 130, 64), ("build", "thesis of record + claim map", 210, 144),
            ("talk", "one timed slide per claim", 370, 64), ("paperwork", "the Western checklist", 450, 64)]
    cmds = [("check", "is every claim backed?", 128, 62), ("build", "the thesis and its claim map", 208, 142),
            ("talk", "one timed slide per claim", 366, 62), ("paperwork", "the Western checklist", 444, 62)]
    t4 = sc.when("Four commands")
    for i, (nm, sub, y, hh) in enumerate(cmds):
        tt = t4 + i * 0.45
        a = P(t, tt, 0.5)
        if a > 0:
            line_prog(d, (332, 300), (398, y + hh / 2), eio(P(t, tt, 0.5)), DIM, 3)
        def f(d, nm=nm, sub=sub, y=y, hh=hh):
            rrect(d, (400, y, 740, y + hh), PANEL, TEAL, 14, 3)
            d.text((416, y + 8), f"murmurent thesis {nm}", font=F_LABEL, fill=TEAL)
            d.text((416, y + 36), sub, font=F_TINY, fill=TEXT)
        appear(img, t, tt + 0.2, f, 0.4, 10)
    outs = [("(a clean bill, or a list of findings)", 128, None, "Four commands"),
            ("build/main.pdf", 208, "doc", "the thesis of record"),
            ("build/claim_map.md", 290, "chart", "the claim map"),
            ("build/talk_plan.md, talk.tex", 366, "slides", "the talk"),
            ("build/paperwork.md", 444, "check", "the paperwork")]
    srcs = {0: (740, 159), 1: (740, 279), 2: (740, 279), 3: (740, 397), 4: (740, 475)}
    for i, (s, y, ic, ph) in enumerate(outs):
        if i == 0:
            continue
        tt = sc.when(ph) if i != 3 else sc.when("the talk")
        a = P(t, tt, 0.7)
        if a > 0:
            line_prog(d, srcs[i], (820, y + 31), eio(a), DIM, 3)
            pulse(img, srcs[i], (820, y + 31), t, 1.6, AMBER, tt + 0.6, 6)
        def f(d, s=s, y=y):
            rrect(d, (820, y, 1235, y + 62), BG, MUTED, 12, 2)
            d.text((890, y + 20), s, font=F_SMALL, fill=TEXT)
        appear(img, t, tt + 0.3, f, 0.4, 10)
        if a > 0:
            icon(img, ic, 852, y + 31, 40, TEAL, AMBER, eback(P(t, tt + 0.3, 0.5)))
    # the log underneath
    t_l = sc.when("Everything an examiner asks")
    def lg(d):
        rrect(d, (50, 524, 1230, 576), PANEL, LAV, 12, 3)
        d.text((70, 538), "queries/<examiner>/<date>.md", font=F_MONO_S, fill=LAV)
        d.text((430, 538), "every question and answer, appended and never changed", font=F_SMALL, fill=TEXT)
    appear(img, t, t_l, lg, 0.6, 14)
    if t > t_l:
        icon(img, "folder", 1190, 550, 34, LAV, TEXT, eback(P(t, t_l + 0.3, 0.5)))


def s_check(img, t, sc, term: Term):
    mono_block(img, term.lines(t), 40, 70, 640, 400, f=F_MONO, title="Terminal: the candidate checks the package")
    # right: a claim and its two links, lighting up when the check passes
    t_ok = term.t_of("OK")
    xs = 740
    def claim(d):
        rrect(d, (xs, 100, xs + 490, 170), PANEL, AMBER, 14, 3)
        d.text((xs + 16, 112), "claim c1", font=F_LABEL, fill=AMBER)
        d.text((xs + 16, 140), "serum enlarges colonies", font=F_SMALL, fill=TEXT)
    appear(img, t, 1.0, claim, 0.6, 14)
    d = ImageDraw.Draw(img)
    for k, (nm, ic, y) in enumerate([("exp/1_signal/run_all.py", "code", 230), ("data/signal.csv", "data", 330)]):
        tt = t_ok + k * 0.6
        a = P(t, 1.4 + k * 0.4, 0.6)
        line_prog(d, (xs + 245, 170 if k == 0 else 170), (xs + 245, y), eio(a), TEAL, 3)
        appear(img, t, 1.7 + k * 0.4, lambda d, nm=nm, y=y: (rrect(d, (xs + 80, y, xs + 410, y + 62), PANEL, TEAL, 12, 3),
                                                              d.text((xs + 150, y + 18), nm, font=F_MONO_S, fill=TEXT)), 0.4, 10)
        icon(img, ic, xs + 114, y + 31, 36, TEAL, AMBER, eback(P(t, 1.9 + k * 0.4, 0.5)))
        if t > t_ok + 0.2:
            ap = P(t, tt + 0.2, 0.5)
            icon(img, "tick", xs + 440, y + 31, 34, TEAL, TEAL, eback(ap))
    d.line([(xs + 245, 292), (xs + 245, 330)], fill=TEAL, width=3)
    # second half: a claim without a script
    t_n = sc.when("A claim with no script")
    def claim2(d):
        rrect(d, (xs, 430, xs + 230, 500), PANEL, AMBER, 14, 3)
        d.text((xs + 14, 442), "claim c9", font=F_LABEL, fill=AMBER)
        d.text((xs + 14, 470), "no script yet", font=F_SMALL, fill=TEXT)
    appear(img, t, t_n, claim2, 0.5, 14)
    a = P(t, t_n + 0.4, 0.8)
    if a > 0:
        dashed(d, (xs + 230, 465), (xs + 230 + 90 * eio(a), 465), AMBER, 3)
    appear(img, t, t_n + 1.2, lambda d: (rrect(d, (xs + 330, 436, xs + 490, 494), BG, AMBER, 10, 2),
                                         d.text((xs + 342, 446), "allowed, and", font=F_SMALL, fill=AMBER),
                                         d.text((xs + 342, 467), "marked", font=F_SMALL, fill=AMBER)), 0.5, 8)
    t_r = sc.when("readable, never")
    appear(img, t, t_r, lambda d: d.text((40, 490), "Readable, never broken.", font=F_BODY, fill=AMBER), 0.6, 10)


def s_build(img, t, sc, term: Term):
    mono_block(img, term.lines(t), 40, 70, 640, 400, f=F_MONO_S, title="Terminal: build")
    chapters = [("1  Introduction", "the candidate's own", AMBER, "chapter 1"),
                ("2  Paper package", "1 claim, c1", TEAL, "chapter 2"),
                ("3  Own chapter", "1 claim, c3.1", AMBER, "chapter 3"),
                ("4  Conclusion", "the candidate's own", AMBER, "chapter 4")]
    x = 760
    for i, (a_, b_, col, key) in enumerate(chapters):
        tt = term.t_of(key)
        p = P(t, tt, 0.6)
        if p <= 0:
            continue
        y = lerp(60, 120 + i * 84, eout(p))
        xx = lerp(x + 140, x, eout(p))
        def f(d, a_=a_, b_=b_, col=col, y=y, xx=xx):
            rrect(d, (xx, y, xx + 440, y + 70), PANEL, col, 14, 3)
            d.text((xx + 16, y + 10), a_, font=F_LABEL, fill=col)
            d.text((xx + 16, y + 40), b_, font=F_TINY, fill=MUTED)
        appear(img, t, tt, f, 0.5, 0)
    t_pdf = term.t_of("wrote build/main.pdf")
    a = P(t, t_pdf, 0.8)
    if a > 0:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x - 14, 104, x + 454, 104 + 352 * eio(a)], radius=18, outline=AMBER, width=3)
        if a >= 1:
            text_c(d, x + 220, 470, "build/main.pdf: the thesis of record", F_LABEL, AMBER)
    t_cm = term.t_of("wrote build/claim_map.md")
    a = P(t, t_cm, 0.6)
    if a > 0:
        icon(img, "chart", 800, 520, 44, SKY, AMBER, eback(a))
        appear(img, t, t_cm + 0.3, lambda d: d.text((832, 506), "claim_map.md", font=F_SMALL, fill=TEXT), 0.4, 6)
    t_k = sc.when("keeps the candidate's own")
    appear(img, t, t_k, lambda d: d.text((40, 490), "In the order SGPS asks for, with the candidate's own preamble.", font=F_SMALL, fill=MUTED), 0.6, 8)


def s_claim_map(img, t, sc):
    heading(img, t, "build/claim_map.md: what every examiner reads first")
    cols = [("Claim", 60, 100), ("Where it is made", 190, 190), ("Figure", 412, 150), ("Code", 594, 290), ("Data", 930, 290)]
    rows = [("c1", "Results, par. 1", "fig:signal", "exp/1_signal/run_all.py", 190),
            ("c3.1", "Section 3.2", "fig:country", "exp/3_metadata/run_all.py", 350)]
    dy = 270
    t_start = sc.when("every claim in every chapter")
    keys = [None, "where it is made", "which figure shows it", "which script made it", "from which data"]
    d = ImageDraw.Draw(img)
    tcol = [t_start, sc.when("where it is made"), sc.when("which figure shows it"), sc.when("which script made it"), sc.when("from which data")]
    centres: dict = {}
    for ci, (name, x, w) in enumerate(cols):
        t0 = tcol[ci]
        appear(img, t, t0, lambda d, name=name, x=x: d.text((x, 118), name.upper() if False else name, font=F_LABEL, fill=MUTED), 0.4, 6)
        for ri, row in enumerate(rows):
            y = row[4]
            if ci < 4:
                label = row[ci]
                col = AMBER if ci == 0 else TEAL
                mono = ci == 3
                def f(d, x=x, y=y, w=w, label=label, col=col, mono=mono):
                    rrect(d, (x, y, x + w, y + 56), PANEL, col, 12, 3)
                    d.text((x + 14, y + 16), label, font=F_MONO_S if mono else F_SMALL, fill=TEXT)
                appear(img, t, t0 + ri * 0.35, f, 0.45, 12)
            centres[(ci, ri)] = (x, y + 28, x + w)
    # the shared data node
    t_d = tcol[4]
    def datan(d):
        rrect(d, (930, dy - 28 + 28, 1220, dy + 28 + 28), PANEL, SKY, 12, 3)
    ry = dy - 28 + 28
    def dnode(d):
        rrect(d, (930, 270 - 2, 1220, 270 + 56 - 2), PANEL, SKY, 12, 3)
        d.text((944, 284), "data/signal.csv", font=F_MONO_S, fill=TEXT)
    appear(img, t, t_d, dnode, 0.45, 12)
    icon(img, "data", 1190, 296, 28, SKY, AMBER, eback(P(t, t_d + 0.2, 0.4)))
    # links, drawn column by column with a travelling light
    for ri, row in enumerate(rows):
        for ci in range(4):
            tt = tcol[ci] + 0.5 + ri * 0.35
            a = centres[(ci, ri)]
            if ci < 3:
                b = centres[(ci + 1, ri)]
                p0, p1 = (a[2], a[1]), (b[0], b[1])
            else:
                p0, p1 = (a[2], a[1]), (930, 298)
            line_prog(d, p0, p1, eio(P(t, tt, 0.5)), TEAL, 3)
    # light the data node when both rows arrive, then run a pulse down each row
    t_lit = t_d + 1.3
    if t > t_lit:
        pp = 0.5 + 0.5 * math.sin((t - t_lit) * 3)
        glow(img, 1075, 298, 40, SKY, 0.25 + 0.25 * pp)
        appear(img, t, t_lit, lambda d: d.text((930, 336), "shared by both rows", font=F_TINY, fill=SKY), 0.5, 6)
        for ri in range(2):
            y = rows[ri][4] + 28
            xa = 60 + 100
            path = [(160, y), (190, y), (380, y), (412, y), (562, y), (594, y), (884, y), (930, 298)]
            q = ((t - t_lit - ri * 0.9) % 4.0) / 4.0
            tot = sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]) for i in range(len(path) - 1))
            dist = q * tot
            for i in range(len(path) - 1):
                seg = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                if dist <= seg:
                    pr = dist / max(seg, 1)
                    glow(img, lerp(path[i][0], path[i + 1][0], pr), lerp(path[i][1], path[i + 1][1], pr), 8, AMBER, 0.9)
                    break
                dist -= seg
    # the examiner reading it
    figure(img, t, t_start - 0.5, 110, 575, TEAL, "", "", 96, "glasses")
    appear(img, t, t_start + 0.8, lambda d: (rrect(d, (190, 480, 800, 560), BG, TEAL, 14, 2),
                                             d.text((210, 492), "Where is it made? Which figure? Which script?", font=F_BODY, fill=TEXT),
                                             d.text((210, 524), "From which data? The map answers before the defence.", font=F_SMALL, fill=MUTED)), 0.6, 10)


def s_talk(img, t, sc, term: Term):
    mono_block(img, term.lines(t), 40, 70, 560, 230, f=F_MONO_S, title="Terminal: the defence talk")
    t_p = term.t_of("planned")
    names = ["title", "outline", "the problem", "data", "objectives", "claim c1", "claim c3.1", "meaning", "limits", "thanks"]
    cols = [SKY] * 5 + [TEAL, TEAL] + [AMBER, AMBER, SKY]
    x0, y0 = 625, 90
    for i, nm in enumerate(names):
        tt = t_p + i * 0.18
        p = P(t, tt, 0.4)
        if p <= 0:
            continue
        cx = x0 + (i % 5) * 118
        cy = y0 + (i // 5) * 110
        def f(d, cx=cx, cy=cy, i=i, nm=nm):
            rrect(d, (cx, cy, cx + 106, cy + 82), PANEL, cols[i], 8, 3)
            d.text((cx + 8, cy + 6), str(i + 1), font=F_LABEL, fill=cols[i])
            d.text((cx + 8, cy + 54), nm, font=F_TINY, fill=TEXT)
            d.line([cx + 30, cy + 24, cx + 94, cy + 24], fill=DIM, width=3)
            d.line([cx + 30, cy + 36, cx + 80, cy + 36], fill=DIM, width=3)
        appear(img, t, tt, f, 0.4, 14)
    t_b = sc.when("backup slides")
    for k, nm in enumerate(["background", "methods"]):
        def f(d, k=k, nm=nm):
            x = 625 + k * 150
            rrect(d, (x, 330, x + 130, 400), BG, MUTED, 8, 2)
            d.text((x + 10, 340), "backup", font=F_TINY, fill=MUTED)
            d.text((x + 10, 366), nm, font=F_SMALL, fill=TEXT)
        appear(img, t, t_b + k * 0.4, f, 0.5, 14)
    t_c = sc.when("one timed slide per claim")
    d = ImageDraw.Draw(img)
    a = P(t, t_c, 0.6)
    if a > 0:
        for (cx, cy) in ((x0 + 5 * 126, y0 + 110), (x0 + 6 * 126, y0 + 110)):
            pass
        pulse(img, (180, 360), (x0 + 5 * 118 + 50, y0 + 110 + 41), t, 2.2, AMBER, t_c, 8)
    # claim map feeding the talk
    def src(d):
        rrect(d, (40, 340, 320, 420), PANEL, AMBER, 12, 3)
        d.text((56, 350), "the same claim map", font=F_LABEL, fill=AMBER)
        d.text((56, 380), "one claim, one slide", font=F_SMALL, fill=TEXT)
    appear(img, t, t_c - 0.2, src, 0.5, 12)


def s_talk_plan(img, t, sc):
    heading(img, t, "build/talk_plan.md: the minutes are a budget")
    mins = [0.5, 1, 1, 1, 1, 6.2, 6.2, 1.2, 1.2, 0.5]
    names = ["title", "outline", "problem", "data", "objectives", "claim c1", "claim c3.1", "meaning", "limits", "thanks"]
    cols = [SKY] * 5 + [TEAL, TEAL, AMBER, AMBER, SKY]
    x0, x1, y = 70, 1210, 160
    scale = (x1 - x0) / 20.0
    t0 = sc.when("The minutes are a budget")
    d = ImageDraw.Draw(img)
    # ruler
    appear(img, t, t0, lambda d: [(d.line([x0 + m * scale, y + 78, x0 + m * scale, y + 90], fill=MUTED, width=2),
                                   text_c(d, x0 + m * scale, y + 94, f"{m} min", F_TINY, MUTED)) for m in (0, 5, 10, 15, 20)], 0.5, 6)
    x = x0
    for i, m in enumerate(mins):
        tt = t0 + 0.4 + i * 0.28
        p = eout(P(t, tt, 0.5))
        wseg = m * scale
        if p > 0:
            d.rectangle([x, y, x + wseg * p - 2, y + 70], fill=cols[i])
            if p > 0.9:
                lab = str(i + 1)
                text_c(d, x + wseg / 2 - 1, y + 20, lab, F_LABEL, BG)
                if m > 5:
                    text_c(d, x + wseg / 2, y + 44, f"{m} min", F_SMALL, BG)
        x += wseg
    t_r = t0 + 0.4 + 10 * 0.28 + 0.6
    # clock counting up
    ck = P(t, t0 + 0.4, 10 * 0.28 + 0.5)
    icon(img, "clock", 90, 300, 40, AMBER, TEXT)
    d.text((124, 283), f"{20 * ck:4.1f} minutes", font=F_BODY, fill=AMBER)
    # the two claim slides get the time
    t_res = sc.when("The results get the time")
    for k, (lab, code, xc) in enumerate([("6  Colonies grown in serum are larger ...", "exp/1_signal/run_all.py", 0),
                                         ("7  Colony size does not differ by country", "exp/3_metadata/run_all.py", 1)]):
        def f(d, lab=lab, code=code, k=k):
            xx = 70 + k * 580
            rrect(d, (xx, 320, xx + 560, 386), PANEL, TEAL, 12, 3)
            d.text((xx + 14, 328), lab, font=F_SMALL, fill=TEXT)
            d.text((xx + 14, 356), code + "  :  6.2 min", font=F_MONO_S, fill=TEAL)
        appear(img, t, t_res + k * 0.5, f, 0.5, 10)
    # chips: who writes the words, who redraws the figure
    t_s = sc.when("scribe's job")
    t_a = sc.when("redrawn by the artist")
    for tt, who, what, xx, col in [(t_s, "scribe", "writes the sentences on each slide", 70, SAND),
                                    (t_a, "artist", "redraws a page figure for the screen", 650, LAV)]:
        def f(d, who=who, what=what, xx=xx, col=col):
            rrect(d, (xx, 408, xx + 560, 452), BG, col, 22, 2)
            d.text((xx + 18, 419), who, font=F_LABEL, fill=col)
            d.text((xx + 100, 421), what, font=F_SMALL, fill=TEXT)
        appear(img, t, tt, f, 0.5, 8)
    # the over-budget bar
    t_m = sc.when("When there are more claims than minutes")
    def lab(d):
        d.text((70, 478), "34 claims, 42 slides, 20 minutes", font=F_LABEL, fill=TEXT)
    appear(img, t, t_m, lab, 0.5, 8)
    bx0, bx1 = 70, 700
    a = eout(P(t, t_m + 0.4, 1.6))
    if a > 0:
        d.line([bx0, 508, bx0, 548], fill=MUTED, width=2)
        d.line([bx1, 504, bx1, 552], fill=RED, width=3)
    n = int(42 * a)
    for k in range(n):
        xk = bx0 + k * (1140 - bx0 - 70) / 42
        wk = (1140 - bx0 - 70) / 42 - 3
        d.rectangle([xk, 512, xk + wk, 544], fill=TEAL if xk < bx1 else RED)
    t_w = sc.when("the plan says so")
    appear(img, t, t_w, lambda d: (rrect(d, (790, 456, 1210, 502), BG, AMBER, 12, 3),
                                   d.text((806, 467), "warning: more claims than minutes", font=F_SMALL, fill=AMBER)), 0.5, 8)
    appear(img, t, t_w + 0.2, lambda d: text_c(d, bx1, 556, "20 min", F_TINY, RED), 0.4, 4)


def s_paperwork_term(img, t, sc, term: Term):
    mono_block(img, term.lines(t), 40, 70, 600, 150, f=F_MONO_S, title="Terminal: paperwork")
    def man(d):
        rrect(d, (700, 100, 880, 230), PANEL, AMBER, 14, 3)
        d.text((716, 112), "thesis.yaml", font=F_LABEL, fill=AMBER)
        d.text((716, 144), "the manifest", font=F_SMALL, fill=TEXT)
    appear(img, t, 0.8, man, 0.6, 14)
    a = P(t, 1.8, 0.8)
    line_prog(ImageDraw.Draw(img), (884, 165), (1010, 165), eio(a), TEAL, 4)
    pulse(img, (884, 165), (1010, 165), t, 1.4, AMBER, 2.6, 7)
    def doc(d):
        rrect(d, (1014, 80, 1230, 300), (232, 232, 226), MUTED, 10, 3)
        d.text((1030, 92), "paperwork.md", font=F_LABEL, fill=BG)
        for i in range(5):
            d.rectangle([1030, 134 + i * 30, 1030 + 14, 148 + i * 30], outline=BG, width=2)
            d.line([1056, 142 + i * 30, 1200 - (20 if i % 2 else 0), 142 + i * 30], fill=(150, 155, 170), width=4)
    appear(img, t, 2.0, doc, 0.6, 14)
    for i in range(3):
        icon_t = 3.2 + i * 0.4
        if t > icon_t:
            icon(img, "tick", 1036, 141 + i * 30, 20, TEAL, TEAL, eback(P(t, icon_t, 0.4)))
    t_w = sc.when("from the manifest")
    appear(img, t, t_w, lambda d: d.text((40, 260), "Western University, SGPS: one checklist, made from your own manifest.", font=F_BODY, fill=AMBER), 0.6, 10)


def s_paperwork(img, t, sc):
    heading(img, t, "build/paperwork.md: counted back from the defence date")
    ax0, ax1, ay = 110, 1170, 250
    d = ImageDraw.Draw(img)
    t_cb = sc.when("counted back from the defence date")
    a = P(t, t_cb - 0.3, 0.8)
    d.line([ax0, ay, ax0 + (ax1 - ax0) * eio(a), ay], fill=DIM, width=4)
    days = lambda n: ax0 + 20 + n * 24.0
    marks = [("2027-03-12", "Examination request +", "preliminary submission", 0, "the examination request", TEAL, 1),
             ("2027-04-09", "Examiners' reports", "5 working days before", 28, "the examiners' reports", TEAL, -1),
             ("2027-04-16", "THE DEFENCE", "hybrid", 35, "counted back from the defence date", AMBER, 1),
             ("about a week after", "Final submission", "PDF and package archived", 42, "the final submission", SKY, -1)]
    order = [2, 0, 1, 3]
    for idx in order:
        date, l1, l2, dd, ph, col, side = marks[idx]
        tt = sc.when(ph)
        x = days(dd)
        a = P(t, tt, 0.5)
        if a <= 0:
            continue
        big = idx == 2
        if big:
            icon(img, "star", x, ay, 54, AMBER, AMBER, eback(a))
            glow(img, x, ay, 30, AMBER, 0.3 + 0.15 * math.sin(t * 3))
        else:
            r = 11 * eback(a)
            d.ellipse([x - r, ay - r, x + r, ay + r], fill=col)
        def f(d, x=x, date=date, l1=l1, l2=l2, col=col, side=side):
            yy = ay - 108 if side < 0 else ay + 30
            wmax = 230
            xl = min(max(x - wmax / 2, 30), W - wmax - 30)
            text_c(d, xl + wmax / 2, yy, date, F_LABEL, col)
            text_c(d, xl + wmax / 2, yy + 26, l1, F_SMALL, TEXT)
            text_c(d, xl + wmax / 2, yy + 50, l2, F_TINY, MUTED)
        appear(img, t, tt + 0.2, f, 0.5, 8)
    # the board checklist
    t_b = sc.when("The board is checked")
    def bx(d):
        rrect(d, (70, 380, 640, 570), PANEL, TEAL, 14, 3)
        d.text((88, 390), "The board, checked against the regulation", font=F_LABEL, fill=TEAL)
    appear(img, t, t_b, bx, 0.5, 10)
    rows = [("1 external examiner listed", True), ("1 university examiner listed", True),
            ("2 program examiners listed", True), ("Supervisor's approval form signed", False)]
    for i, (s, ok) in enumerate(rows):
        tt = t_b + 0.6 + i * 0.45
        yy = 428 + i * 34
        if t >= tt:
            d.rectangle([92, yy + 2, 112, yy + 22], outline=TEAL if ok else AMBER, width=3)
            if ok:
                icon(img, "tick", 102, yy + 12, 22, TEAL, TEAL, eback(P(t, tt, 0.35)))
            d.text((124, yy), s, font=F_SMALL, fill=TEXT if ok else AMBER)
    t_w = sc.when("word limits")
    appear(img, t, t_w, lambda d: (rrect(d, (680, 380, 1210, 440), BG, SAND, 12, 2),
                                   d.text((698, 392), "Word limits checked against the front matter", font=F_SMALL, fill=SAND)), 0.5, 8)
    t_r = sc.when("The requirements were read")
    appear(img, t, t_r, lambda d: (icon_off := None, rrect(d, (680, 458, 1210, 518), BG, MUTED, 12, 2),
                                   d.text((698, 470), "Requirements read from the SGPS pages", font=F_SMALL, fill=TEXT),
                                   d.text((698, 494), "on a stated date: 2026-11-06", font=F_TINY, fill=MUTED)), 0.5, 8)
    t_g = sc.when("the Graduate Program Coordinator")
    figure(img, t, t_g, 1160, 598, SAND, "", "", 84, "person")
    appear(img, t, t_g + 0.3, lambda d: d.text((690, 540), "The Graduate Program Coordinator confirms", font=F_SMALL, fill=SAND), 0.5, 6)


def s_chat(img, t, sc, who, question, reply, chips, kind, colour_first, avatar_col):
    heading(img, t, "In Claude Code, with the docent", 28)
    # avatars
    figure(img, t, 0.3, 100, 250, avatar_col, who.split(" ")[0] if kind != "cand" else "Candidate", "", 100, "cap" if kind == "cand" else "glasses", 150)
    figure(img, t, 0.5, 100, 470, LAV, "docent", "", 100, "bot", 150)
    # question typed
    q0 = 0.8
    q_dur = len(question) / CHARS_PER_SECOND
    n = int(len(question) * P(t, q0, q_dur))
    d = ImageDraw.Draw(img)
    rrect(d, (200, 92, 1225, 172), PANEL, avatar_col, 16, 3)
    d.text((218, 100), who, font=F_TINY, fill=avatar_col)
    ql = wrap(question[:n] + ("|" if n < len(question) else ""), F_SMALL, 980)
    for i, l in enumerate(ql[:2]):
        d.text((218, 122 + i * 26), l, font=F_SMALL, fill=TEXT)
    t_c = q0 + q_dur + 0.5
    # the docent's working: chips
    cw = 1015 / max(len(chips), 1)
    for i, (txt, ok) in enumerate(chips):
        tt = t_c + i * 0.55
        if t < tt:
            continue
        x = 200 + i * cw
        done = t > tt + 0.5
        col = (TEAL if ok else MUTED) if done else LAV
        def f(d, x=x, txt=txt, col=col):
            rrect(d, (x, 186, x + cw - 10, 222), BG, col, 18, 2)
            d.text((x + 34, 194), txt, font=F_TINY, fill=TEXT)
        appear(img, t, tt, f, 0.3, 6)
        if done:
            icon(img, "tick" if ok else "cross", x + 18, 204, 18, TEAL if ok else DIM, TEAL, eback(P(t, tt + 0.5, 0.3)))
        else:
            ang = (t - tt) * 10
            d.arc([x + 8, 194, x + 28, 214], ang * 57, ang * 57 + 250, fill=LAV, width=3)
    t_r = t_c + len(chips) * 0.55 + 0.7
    k = int(max(t - t_r, 0) / 0.3)
    items = []
    first_blank = next((i for i, l in enumerate(reply) if not l.strip()), len(reply))
    for i, l in enumerate(reply[:k]):
        c = colour_first if i < first_blank else TEXT
        items.append((l, c))
    rrect(d, (200, 236, 1225, 585), TERM_BG, (58, 70, 104), 12, 2) if False else None
    mono_block(img, items, 200, 236, 1025, 350, f=font(17, mono=True), title="docent")
    # a small pulse from the docent to the panel when a line lands
    if 0 < t - t_r < 0.6:
        glow(img, 190, 470, 14, LAV, 0.6)


def s_log(img, t, sc, log_lines):
    heading(img, t, "The committee as a whole")
    t_a = sc.when("Every question is appended")
    # three examiners, a stream of questions into the log
    people = [("External", 175), ("University", 295), ("Program", 415)]
    for i, (lab, y) in enumerate(people):
        figure(img, t, t_a - 0.4 + i * 0.25, 90, y + 70, TEAL, "", "", 78, "glasses")
        appear(img, t, t_a - 0.1 + i * 0.25, lambda d, lab=lab, y=y: d.text((140, y + 20), lab, font=F_TINY, fill=MUTED), 0.4, 6)
        if t > t_a + 0.8 + i * 0.9:
            ph = ((t - t_a - 0.8 - i * 0.9) % 3.0) / 3.0
            sx, sy = 190, y + 32
            ex_, ey = 360, 330
            x = lerp(sx, ex_, eio(ph))
            yy = lerp(sy, ey, eio(ph))
            al = min(1.0, ph * 6, (1 - ph) * 5)
            glow(img, x, yy, 14, AMBER, 0.6 * al)
            d = ImageDraw.Draw(img)
            if al > 0.3:
                text_c(d, x, yy - 12, "?", F_LABEL, TEXT)
    # the log file
    def fileb(d):
        rrect(d, (360, 110, 960, 560), TERM_BG, LAV, 12, 3)
        d.text((378, 120), "queries/examiner/2026-11-07.md", font=F_SMALL, fill=LAV)
        d.text((378, 146), "append-only", font=F_TINY, fill=MUTED)
    appear(img, t, t_a, fileb, 0.6, 14)
    t0 = t_a + 1.0
    k = int(max(t - t0, 0) / 0.35)
    d = ImageDraw.Draw(img)
    y = 176
    rows = []
    for l in log_lines[:k]:
        for p in (wrap(l, F_MONO_T, 560) if l.strip() else [""]):
            rows.append(p)
    rows = rows[-26:]
    for r in rows:
        c = TEAL if r.startswith("Verdict") else (AMBER if r.startswith("Question") else (LAV if r.startswith("Locations") else TEXT))
        if r.startswith("## "):
            c = MUTED
        d.text((378, y), r, font=F_MONO_T, fill=c)
        y += 18
    # claims on the right
    pts = [("Part of the record of the examination", "the record of the examination", 130),
           ("Visible to the whole board, before the defence", "visible, before the defence", 230),
           ("What the thesis answered, and what it could not", "what the thesis answered", 330)]
    for txt, ph, y in pts:
        tt = sc.when(ph)
        def f(d, txt=txt, y=y):
            rrect(d, (990, y, 1235, y + 84), PANEL, TEAL, 12, 3)
            for i, l in enumerate(wrap(txt, F_SMALL, 205)):
                d.text((1004, y + 10 + i * 24), l, font=F_SMALL, fill=TEXT)
        appear(img, t, tt, f, 0.5, 12)
    t_x = sc.when("what it could not")
    for k, (lab, col, y) in enumerate([("Located", TEAL, 394), ("Absent", AMBER, 394)]):
        pass
    t_cd = sc.when("The candidate should run")
    figure(img, t, t_cd, 1110, 590, AMBER, "", "", 100, "cap")
    appear(img, t, t_cd + 0.4, lambda d: (rrect(d, (990, 440, 1235, 500), BG, AMBER, 12, 2),
                                          d.text((1004, 452), "runs the docent on", font=F_SMALL, fill=AMBER),
                                          d.text((1004, 474), "their own thesis first", font=F_SMALL, fill=AMBER)), 0.5, 6)


def s_timeline(img, t, sc):
    heading(img, t, "From package to defence")
    ms = [("Package ready", "check passes, claim map built", AMBER),
          ("Examination request", "25 working days before: form and preliminary submission", SAND),
          ("Examiners read", "the PDF of record with the package beside it", TEAL),
          ("Preliminary reports", "5 working days before the defence", TEAL),
          ("The defence", "the talk, then what the log did not settle", AMBER),
          ("Final submission", "about a week after: PDF and package archived", SKY)]
    ay = 270
    x0, step = 110, 212
    d = ImageDraw.Draw(img)
    a = P(t, 0.5, 1.0)
    d.line([x0 - 40, ay, x0 - 40 + (5 * step + 90) * eio(a), ay], fill=DIM, width=4)
    phr = ["the candidate makes the package pass", "questions it first", "The examiners", "ask as they read",
           "The defence then spends", "which is what a"]
    ts = [sc.when("Put together"), sc.when("questions it first"), sc.when("The examiners"), sc.when("ask as they read"),
          sc.when("The defence then spends"), sc.when("which is what a")]
    for i, ((a_, b_, col), tt) in enumerate(zip(ms, ts)):
        x = x0 + i * step
        p = P(t, tt, 0.5)
        if p <= 0:
            continue
        big = i == 4
        r = (16 if big else 11) * eback(p)
        d.ellipse([x - r, ay - r, x + r, ay + r], fill=col)
        if big:
            glow(img, x, ay, 26, AMBER, 0.35 + 0.2 * math.sin(t * 3))
        def f(d, x=x, a_=a_, b_=b_, col=col, i=i):
            above = i % 2 == 0
            yy = ay - 152 if above else ay + 36
            text_c(d, x, yy, a_, F_LABEL, col)
            for j, l in enumerate(wrap(b_, F_TINY, 190)):
                text_c(d, x, yy + 28 + j * 21, l, F_TINY, MUTED if not big else TEXT)
        appear(img, t, tt + 0.15, f, 0.5, 8)
    # the candidate travels along the line
    tc = ts[0]
    prog = P(t, tc + 0.5, ts[4] - tc)
    cx = x0 + 4 * step * eio(prog) if t > tc else x0
    if t > tc:
        paste_c(img, person(AMBER, 48, "cap"), cx, ay - 32, eback(P(t, tc, 0.5)))
    # the questions: many get settled in the log, a few go to the defence
    t_q = sc.when("ask as they read")
    t_s = sc.when("what the log did not settle")
    n = 14
    for i in range(n):
        tt = t_q + i * 0.14
        if t < tt:
            continue
        x = 140 + i * 56
        y = 470
        settled = i not in (4, 9, 12)
        p = P(t, tt, 0.4)
        r = 15 * eback(p)
        col = AMBER
        ys = y
        if t > t_s:
            if settled:
                col = mix(AMBER, DIM, P(t, t_s + i * 0.05, 0.5))
            else:
                k2 = P(t, t_s + 0.8 + (i % 3) * 0.25, 1.4)
                ys = lerp(y, ay + 46, eio(k2))
                x = lerp(x, x0 + 4 * step + (i % 3 - 1) * 34, eio(k2))
        d.ellipse([x - r, ys - r, x + r, ys + r], fill=col)
        if p > 0.9:
            text_c(d, x, ys - 11, "✓" if (settled and t > t_s + i * 0.05 + 0.3) else "?", F_SMALL, BG)
    appear(img, t, t_q + 0.4, lambda d: d.text((140, 506), "questions asked and logged before the defence", font=F_SMALL, fill=MUTED), 0.5, 6)
    t_k = sc.when("which is what a")
    appear(img, t, t_k, lambda d: d.text((140, 540), "Most are settled in the log. The defence keeps the few that matter.", font=F_BODY, fill=AMBER), 0.6, 8)


def s_limits(img, t, sc):
    heading(img, t, "What it does not do")
    items = [("scale", RED, "It does not grade", "The adversary audits. The examiner decides.", "It does not grade"),
             ("cloud", RED, "It is offline", "A thesis under examination is not public, and a web search is outbound text.", "It is offline"),
             ("stamp", AMBER, "The PDF is the record", "A disagreement with the package is a finding, not a correction.", "The PDF stays"),
             ("lock", AMBER, "Protected data stays put", "It stays on the server that holds it, reached there and never copied.", "Protected data"),
             ("pencil", RED, "It never edits", "Not the thesis, the chapters, the manifest or the data.", "never edits")]
    for i, (ic, col, a_, b_, ph) in enumerate(items):
        tt = sc.when(ph)
        x = 52 + i * 232
        p = P(t, tt, 0.6)
        if p <= 0:
            continue
        def f(d, x=x, a_=a_, b_=b_, col=col):
            rrect(d, (x, 130, x + 216, 500), PANEL, col, 16, 3)
            for j, l in enumerate(wrap(a_, F_LABEL, 190)):
                d.text((x + 16, 262 + j * 28), l, font=F_LABEL, fill=col)
            for j, l in enumerate(wrap(b_, F_SMALL, 186)):
                d.text((x + 16, 322 + j * 26), l, font=F_SMALL, fill=TEXT)
        appear(img, t, tt, f, 0.5, 26)
        icon(img, ic, x + 108, 196, 90, MUTED if ic != "lock" else AMBER, col, eback(P(t, tt + 0.2, 0.5)))


def s_recap(img, t, sc):
    heading(img, t, "Where to start")
    cmds = [("murmurent thesis adopt thesis.tex my_thesis    # or: thesis init, paper init", "adopt an existing thesis", "doc"),
            ("murmurent thesis check my_thesis", "check, build", "tick"),
            ("murmurent thesis build my_thesis --pdf", "build, draft", "chart"),
            ("murmurent thesis talk my_thesis --minutes 20", "draft the talk", "slides"),
            ("murmurent thesis paperwork my_thesis", "write the paperwork", "check")]
    d = ImageDraw.Draw(img)
    rrect(d, (50, 100, 1230, 360), TERM_BG, (58, 70, 104), 12, 2)
    d.text((68, 110), "Terminal", font=F_TINY, fill=MUTED)
    for i, (cmd, ph, ic) in enumerate(cmds):
        t0 = sc.when(ph)
        n = int(len(cmd) * P(t, t0, len(cmd) / CHARS_PER_SECOND))
        y = 144 + i * 40
        if t >= t0:
            d.text((68, y), "$ " + cmd[:n] + ("▌" if n < len(cmd) else ""), font=F_MONO, fill=AMBER)
            if n >= len(cmd):
                icon(img, ic, 1196, y + 12, 26, TEAL, AMBER, eback(P(t, t0 + len(cmd) / CHARS_PER_SECOND, 0.4)))
    t_a = sc.when("ask the docent")
    figure(img, t, t_a, 130, 560, LAV, "", "", 110, "bot")
    def b(d):
        rrect(d, (220, 410, 880, 520), PANEL, LAV, 18, 3)
        d.text((242, 424), "then open the package in Claude Code", font=F_BODY, fill=TEXT)
        d.text((242, 462), "and ask the docent.", font=F_BODY, fill=LAV)
    appear(img, t, t_a + 0.2, b, 0.6, 10)
    t_d = sc.when("docs slash paper package")
    def doc(d):
        d.text((910, 410), "docs/paper_package.md", font=F_MONO_S, fill=AMBER)
        d.text((910, 440), "agents/docent.md", font=F_MONO_S, fill=AMBER)
        d.text((910, 470), "examples/thesis_example", font=F_MONO_S, fill=AMBER)
        d.text((910, 506), "Checked against Murmurent 2026.11.0.", font=F_TINY, fill=MUTED)
    appear(img, t, t_d, doc, 0.6, 10)


# --------------------------------------------------------------------------- #
# The scene list
# --------------------------------------------------------------------------- #


def build_scenes() -> list[Scene]:
    docent, log_lines = load_docent()
    sc: list[Scene] = []

    sc.append(Scene("title", [
        "This is how a thesis becomes something an examiner can question, and how the same "
        "package helps the candidate present it: the thesis, the defence talk and the paperwork, "
        "all from one map of the claims."], s_title, "Welcome"))

    sc.append(Scene("people", [
        "A defence at Western has a candidate, a supervisor who attends but does not vote, "
        "and a board of examiners: one from another university, one from another Western "
        "department, and one or two from the program.",
        "Each examiner reads the thesis, writes a preliminary report, and then questions the "
        "candidate. The program coordinator opens the examination and confirms the deadlines."],
        s_people, "Who is in the room"))

    sc.append(Scene("problem", [
        "Today the examiner gets a PDF. The questions worth asking, where a claim is made, "
        "what is behind a figure, whether a result still holds, what the thesis does not "
        "address, all wait for the defence, where there is time for only a few of them."],
        s_problem, "The problem"))

    sc.append(Scene("claim", [
        "The idea is small. Every central claim is written down with its evidence: the sentence "
        "it rests on, the figure, the script that made the figure, and the data the script read."],
        s_claim, "The idea"))

    sc.append(Scene("compose", [
        "The unit is the paper, so every paper gains readers who can question it, not only the "
        "one thesis. A thesis is a composition of paper packages plus the candidate's own chapters."],
        s_compose))

    sc.append(Scene("package", [
        "The manifest lists the chapters, the examiners and the defence date. Four commands "
        "turn it into the thesis of record, the claim map, the talk and the paperwork. "
        "Everything an examiner asks is logged beside them."], s_package, "The package"))

    t_check = Term(T_CHECK + "\n")
    sc.append(Scene("check", [
        "The candidate's side first. The check refuses a package whose claims point at code or "
        "data that is not there. Here the synthetic example passes with nothing to report.",
        "A claim with no script is allowed and marked, so a package degrades to readable, never "
        "to broken. The work of mapping is real, and it is the candidate's."],
        lambda img, t, s: s_check(img, t, s, t_check), "The candidate: check", min_anim=t_check.dur))

    t_build = Term(T_BUILD)
    sc.append(Scene("build", [
        "Build assembles the chapters in the order SGPS asks for, keeps the candidate's own "
        "preamble, and writes the claim map."],
        lambda img, t, s: s_build(img, t, s, t_build), "The candidate: build", min_anim=t_build.dur))

    sc.append(Scene("claim_map", [
        "The claim map is what every examiner reads first: every claim in every chapter, where "
        "it is made, which figure shows it, which script made it, from which data."],
        s_claim_map, tail=5.0))

    t_talk = Term(T_TALK)
    sc.append(Scene("talk", [
        "The defence talk is drafted from the same map: one timed slide per claim, with the "
        "background and the methods as backup slides."],
        lambda img, t, s: s_talk(img, t, s, t_talk), "The candidate: the talk", min_anim=t_talk.dur))

    sc.append(Scene("talk_plan", [
        "The minutes are a budget, not a script. The results get the time; the introduction "
        "and the conclusion get what is left. The sentences on each slide are the scribe's job "
        "and a figure made for a page is redrawn by the artist.",
        "When there are more claims than minutes, the plan says so. The pilot thesis, with "
        "thirty-four claims, got forty-two slides and a warning, which is the right answer."],
        s_talk_plan))

    t_pw = Term(T_PAPERWORK)
    sc.append(Scene("paperwork", [
        "Paperwork writes the Western checklist from the manifest."],
        lambda img, t, s: s_paperwork_term(img, t, s, t_pw), "The candidate: paperwork", min_anim=t_pw.dur))

    sc.append(Scene("paperwork_md", [
        "The deadlines are counted back from the defence date: the examination request and "
        "the preliminary submission, the examiners' reports, the final submission. The board "
        "is checked against the regulation, and the word limits against the front matter.",
        "The requirements were read from the SGPS pages on a stated date. Where a deadline or a "
        "form matters, the Graduate Program Coordinator confirms it."], s_paperwork))

    def chat_scene(key, kind, narr, chips, col_first, av, chapter):
        who, q, reply = docent[key]
        return Scene("chat" + key, narr,
                     lambda img, t, s: s_chat(img, t, s, who, q, reply, chips, kind, col_first, av), chapter,
                     min_anim=0.8 + len(q) / CHARS_PER_SECOND + 0.5 + len(chips) * 0.55 + 0.7 + len(reply) * 0.3 + 1.5)

    sc.append(chat_scene("1", "ex", [
        "Now the examiner. They open the package in Claude Code and ask the docent, in plain words. "
        "Every answer carries a location: a section, a figure, a script, a data file.",
        "Before it reports a number, the docent re-runs the script behind the claim and shows "
        "what it printed. The examiner is not asked to trust a sentence."],
        [("read claim_map.md", True), ("open the PDF, ch. 2", True), ("re-run run_all.py", True)],
        TEAL, TEAL, "The examiner: asking"))

    sc.append(chat_scene("2", "ex", [
        "When the thesis does not address something, the answer is Absent, said plainly, with "
        "the nearest thing the thesis does address and where. The gap is not filled with what "
        "the field generally believes. A fluent wrong answer would be worse than the PDF."],
        [("thesis.yaml", False), ("claim_map.md", False), ("chapters", False), ("main.tex", False),
         ("PDF text", False), ("data columns", False)],
        AMBER, TEAL, "The examiner: Absent"))

    sc.append(Scene("log", [
        "Every question is appended to a log under the examiner's handle, with the answer and "
        "the locations it rests on. The log is part of the record of the examination.",
        "That is what the package does for the committee as a whole: what was asked, what the "
        "thesis answered and what it could not are all visible, before the defence. "
        "The candidate should run the docent on their own thesis before anyone else does."],
        lambda img, t, s: s_log(img, t, s, log_lines), "The committee"))

    sc.append(chat_scene("3", "cand", [
        "The candidate asks the same agent about the package rather than about the work: "
        "whether the talk fits, what paperwork is open. The docent infers which side it is on "
        "from the question and never asks."],
        [("talk_plan.md", True), ("paperwork.md", True), ("thesis.yaml", True)],
        TEAL, AMBER, "The candidate asks"))

    sc.append(Scene("timeline", [
        "Put together: the candidate makes the package pass and questions it first. The examiners "
        "read the PDF of record with the package beside it, and ask as they read.",
        "The defence then spends its time on what the log did not settle, which is what a "
        "defence is for."], s_timeline, "From package to defence"))

    sc.append(Scene("limits", [
        "Some things it does not do, on purpose. It does not grade. It is offline. The PDF stays "
        "the thesis of record. Protected data stays on its server. And it never edits the thesis."],
        s_limits, "What it does not do"))

    sc.append(Scene("recap", [
        "To try it: adopt an existing thesis or start a new package, check, build, draft the talk, "
        "write the paperwork, then open the package in Claude Code and ask the docent. "
        "The design and its known hard problems are in docs slash paper package."],
        s_recap, "Recap", tail=2.0))
    return sc


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

SCENES: list[Scene] = []
FRAMES: list[tuple[int, float, float]] = []   # (scene index, time in scene, time overall)
TOTAL = 0.0


def srt_time(s: float) -> str:
    h, rem = divmod(s, 3600)
    m, rem = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(rem):02d},{int((rem % 1) * 1000):03d}"


def frame_image(i: int) -> Image.Image:
    si, t, tg = FRAMES[i]
    sc = SCENES[si]
    img = sc.content(t)
    if si > 0 and t < XFADE:
        prev = SCENES[si - 1].content(SCENES[si - 1].seconds - 1.0 / FPS)
        img = Image.blend(prev, img, eio(t / XFADE))
    caption(img, sc.caption_at(t))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 4, W * tg / TOTAL, H], fill=TEAL)
    return img


def frame_bytes(i: int) -> bytes:
    return frame_image(i).tobytes()


def main() -> None:
    global SCENES, FRAMES, TOTAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--stills", default=None, help="also save a PNG every five seconds to this folder")
    ap.add_argument("--jobs", type=int, default=max(mp.cpu_count() - 1, 1))
    args = ap.parse_args()
    out = Path(args.out)

    SCENES = build_scenes()
    t0 = 0.0
    srt: list[str] = []
    chapters: list[tuple[float, str]] = []
    for si, sc in enumerate(SCENES):
        if sc.chapter:
            chapters.append((t0, sc.chapter))
        for i, (cue, text) in enumerate(zip(sc.cues, sc.narration)):
            end = sc.cues[i + 1] if i + 1 < len(sc.cues) else sc.seconds
            srt.append(f"{len(srt) + 1}\n{srt_time(t0 + cue)} --> {srt_time(t0 + end)}\n{text}\n")
        n = int(round(sc.seconds * FPS))
        for k in range(n):
            FRAMES.append((si, k / FPS, t0 + k / FPS))
        t0 += n / FPS
    TOTAL = t0
    (out / "thesis_package.srt").write_text("\n".join(srt))

    if args.stills:
        sd = Path(args.stills)
        sd.mkdir(parents=True, exist_ok=True)
        for i, (si, t, tg) in enumerate(FRAMES):
            if i % (5 * FPS) == 0:
                frame_image(i).save(sd / f"still_{int(tg):04d}_{SCENES[si].name}.png")
        print(f"stills in {sd}")
        return

    mp4 = out / "thesis_package.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    ctx = mp.get_context("fork")
    with ctx.Pool(args.jobs) as pool:
        for k, b in enumerate(pool.imap(frame_bytes, range(len(FRAMES)), chunksize=10)):
            ff.stdin.write(b)
            if k % 400 == 0:
                print(f"  {k}/{len(FRAMES)} frames", file=sys.stderr, flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"wrote {mp4} ({TOTAL:.0f} s, {len(FRAMES)} frames)")
    print(f"wrote {out / 'thesis_package.srt'}")
    print("chapters:")
    for t, name in chapters:
        print(f"  {int(t // 60)}:{int(t % 60):02d}  {name}")


if __name__ == "__main__":
    main()
