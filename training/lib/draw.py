"""
Purpose: The drawing library shared by every script-rendered training movie:
         palette, fonts, easing, captions, panels, people and icon sprites, a
         terminal panel and a typed terminal session. Lifted from
         training/thesis_package/make_movie.py (PR #287) so that each movie is a
         short scene file rather than a copy of two thousand lines.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: fonts from /System/Library/Fonts (macOS). Python with PIL and numpy.
Output: nothing on its own; see scene.py for rendering and agent_movie.py for
        the standard four-part agent movie.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

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
        parts = wrap(s, f, w - 36) if (wrap_lines and s.strip() and tw(s, f) > w - 36) else [s]
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


# --------------------------------------------------------------------------- #
# Emoji badges: each agent has its own glyph, as on the seminar slides
# --------------------------------------------------------------------------- #

EMOJI_FONT = Path("/System/Library/Fonts/Apple Color Emoji.ttc")
_EMOJI: dict = {}


def emoji_sprite(glyph: str, size: int) -> Image.Image:
    """The glyph drawn with Apple's colour emoji font (bitmap at 160 px, scaled)."""
    key = (glyph, size)
    if key not in _EMOJI:
        f = ImageFont.truetype(str(EMOJI_FONT), 160)
        im = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((110, 110), glyph, font=f, embedded_color=True, anchor="mm")
        box = im.getbbox() or (0, 0, 220, 220)
        im = im.crop(box)
        k = size / max(im.width, im.height)
        _EMOJI[key] = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    return _EMOJI[key]


def badge(img: Image.Image, glyph: str, colour, cx: float, cy: float, size: int = 110,
          scale: float = 1.0, alpha: float = 1.0, ring: bool = True) -> None:
    """A round badge in the agent's colour with its emoji inside."""
    if scale <= 0.02:
        return
    key = ("badge", glyph, colour, size, ring)
    if key not in _SPR:
        S = 4
        im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if ring:
            d.ellipse([0, 0, size * S - 1, size * S - 1], fill=(*mix(colour, BG, 0.78), 255),
                      outline=(*colour, 255), width=int(size * S * 0.04))
        im = im.resize((size, size), Image.LANCZOS)
        g = emoji_sprite(glyph, int(size * 0.62))
        im.paste(g, (int((size - g.width) / 2), int((size - g.height) / 2)), g)
        _SPR[key] = im
    paste_c(img, _SPR[key], cx, cy, scale, alpha)
