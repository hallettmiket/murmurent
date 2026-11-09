"""
Purpose: A scene timed from its narration, and the renderer that turns a list
         of scenes into an mp4 with burned-in captions, an srt of the narration
         and a list of chapter times. Lifted from
         training/thesis_package/make_movie.py (PR #287).
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: a list of Scene objects (see agent_movie.py for the standard set).
Output: <stem>.mp4 (1280x720, 20 frames a second, captions burned in, no
        audio), <stem>.srt, and the chapters as a list of (seconds, name).
Usage: from a movie script, render(scenes, out_dir, stem).
How it is built: each scene is a function draw(img, t, sc) that paints the
       picture at time t seconds. sc.when("some words") returns the moment the
       narrator reaches those words, so a bullet or a figure can appear
       exactly then, and it refuses to render if the words are no longer in
       the narration. Caption timing is estimated from a reading pace.
"""

from __future__ import annotations

import multiprocessing as mp
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from .draw import FPS, H, LEAD, TAIL, TEAL, W, WORDS_PER_SECOND, XFADE, background, caption, eio

EM_DASH = "—"

# Measured length of each narration sentence's voice clip, filled in by the movie
# script when the clips already exist (narrate.clip_durations). A sentence with a
# measured clip gets a slot of that length plus a breath; the rest are estimated
# from the reading pace, as before.
DURATIONS: dict[str, float] = {}


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
        for text in self.narration:
            if EM_DASH in text:
                raise ValueError(f"{self.name}: em dash in the narration: {text!r}")
        t = self.lead
        for text in self.narration:
            if text in DURATIONS:
                d = DURATIONS[text] + 0.45
            else:
                d = max(len(text.split()) / WORDS_PER_SECOND + 0.5, 2.5)
            self.cues.append(t)
            self.durs.append(d)
            t += d
        self.seconds = max(t + self.tail, self.min_anim)

    def when(self, phrase: str) -> float:
        """The moment the narrator reaches these words."""
        for cue, d, text in zip(self.cues, self.durs, self.narration):
            pos = text.lower().find(phrase.lower())
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
# Rendering. Module-level state so the frame workers (forked) can see it.
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


def mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def render(scenes: list[Scene], out: Path, stem: str, *, stills: Path | None = None,
           jobs: int | None = None) -> tuple[float, list[tuple[float, str]]]:
    """Write <out>/<stem>.mp4 and <out>/<stem>.srt. Returns (seconds, chapters)."""
    global SCENES, FRAMES, TOTAL
    SCENES = scenes
    FRAMES = []
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
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.srt").write_text("\n".join(srt))

    if stills is not None:
        stills.mkdir(parents=True, exist_ok=True)
        for i, (si, t, tg) in enumerate(FRAMES):
            if i % (5 * FPS) == 0:
                frame_image(i).save(stills / f"still_{int(tg):04d}_{SCENES[si].name}.png")
        print(f"stills in {stills}")
        return TOTAL, chapters

    mp4 = out / f"{stem}.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    ctx = mp.get_context("fork")
    with ctx.Pool(jobs or max(mp.cpu_count() - 1, 1)) as pool:
        for k, b in enumerate(pool.imap(frame_bytes, range(len(FRAMES)), chunksize=10)):
            ff.stdin.write(b)
            if k % 400 == 0:
                print(f"  {k}/{len(FRAMES)} frames", file=sys.stderr, flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"wrote {mp4} ({TOTAL:.0f} s, {len(FRAMES)} frames)")
    print(f"wrote {out / (stem + '.srt')}")
    print("chapters:")
    for t, name in chapters:
        print(f"  {mmss(t)}  {name}")
    return TOTAL, chapters
