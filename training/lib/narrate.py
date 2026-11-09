"""
Purpose: Voice a rendered movie's narration with ElevenLabs and mux it in.
         Reads <stem>.srt (one cue per caption), makes one clip per cue (cached
         by the text's hash, so a re-render that changes two sentences re-voices
         two clips), places each clip at its cue's start and writes
         <stem>_narrated.mp4. Reports any clip longer than its slot. Lifted
         from training/thesis_package/voice_narration.py (PR #287).
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: <folder>/<stem>.srt and <folder>/<stem>.mp4; the ElevenLabs API key in
       the macOS Keychain (service elevenlabs-api-key, as training/README.md
       step 4 stores it) or $ELEVENLABS_API_KEY.
Output: <folder>/audio/<hash>.mp3 per cue, audio/narration.wav,
        <folder>/<stem>_narrated.mp4. None of them is committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_multilingual_v2"   # the model the getting-started video used


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    try:
        return subprocess.check_output(
            ["/usr/bin/security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", "elevenlabs-api-key", "-w"], text=True).strip()
    except subprocess.CalledProcessError:
        sys.exit("No ElevenLabs key: store one with "
                 "`security add-generic-password -U -a \"$USER\" -s elevenlabs-api-key -w` "
                 "(training/README.md, step 4).")


def request(path: str, key: str, data: dict | None = None, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(API + path, headers={"xi-api-key": key, "accept": accept})
    if data is not None:
        req.add_header("content-type", "application/json")
        req.data = json.dumps(data).encode()
    # ElevenLabs sometimes answers a burst of requests with a 401 or a 429 that goes
    # away on its own; retry a few times before giving up.
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (401, 429, 500, 502, 503) or attempt == 4:
                raise
            print(f"  ElevenLabs {e.code}; retrying in {5 * (attempt + 1)} s", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    def secs(s: str) -> float:
        h, m, rest = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text().strip()):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        a, b = lines[1].split(" --> ")
        cues.append((secs(a), secs(b), " ".join(lines[2:])))
    return cues


def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(path)], text=True)
    return float(out.strip())


def voice_id_for(name: str, key: str) -> str:
    voices = json.loads(request("/voices", key))["voices"]
    # Names come back as "Matilda - Knowledgable, Professional"; match the name before the dash.
    vid = next((v["voice_id"] for v in voices if v["name"].split(" - ")[0].strip().lower() == name.lower()), None)
    if not vid:
        sys.exit(f"No voice named {name!r}; available: {', '.join(v['name'] for v in voices)}")
    return vid


def clip_durations(folder: Path, texts: list[str], voice_name: str = "Matilda") -> dict[str, float]:
    """The measured length of every sentence whose clip is already cached, so a
    scene can be timed from the real narration rather than a reading-pace guess."""
    out: dict[str, float] = {}
    for text in texts:
        h = hashlib.sha1((voice_name + MODEL + text).encode()).hexdigest()[:12]
        clip = folder / "audio" / f"{h}.mp3"
        if clip.exists():
            out[text] = duration(clip)
    return out


def voice(folder: Path, stem: str, voice_name: str = "Matilda", dry_run: bool = False) -> Path | None:
    audio = folder / "audio"
    cues = parse_srt(folder / f"{stem}.srt")
    audio.mkdir(exist_ok=True)
    print(f"{len(cues)} cues, {sum(len(t.split()) for _, _, t in cues)} words")
    if dry_run:
        return None
    key = api_key()
    vid = voice_id_for(voice_name, key)
    clips: list[tuple[float, Path]] = []
    overruns: list[str] = []
    for start, end, text in cues:
        h = hashlib.sha1((voice_name + MODEL + text).encode()).hexdigest()[:12]
        clip = audio / f"{h}.mp3"
        if not clip.exists():
            clip.write_bytes(request(f"/text-to-speech/{vid}", key, {"text": text, "model_id": MODEL}, accept="audio/mpeg"))
            print(f"voiced {h}: {text[:60]}...")
        d = duration(clip)
        if d > end - start + 0.3:
            overruns.append(f"{start:7.1f}s  slot {end - start:5.1f}s  clip {d:5.1f}s  {text[:50]}...")
        clips.append((start, clip))
    movie = folder / f"{stem}.mp4"
    total = duration(movie)
    inputs: list[str] = []
    filters: list[str] = []
    for i, (start, clip) in enumerate(clips):
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad=whole_dur={total}[out]"
    narration = audio / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
                    ";".join(filters + [mix]), "-map", "[out]", "-t", str(total), str(narration)], check=True)
    out = folder / f"{stem}_narrated.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(movie), "-i", str(narration),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)], check=True)
    print(f"wrote {out}")
    if overruns:
        print("Clips longer than their caption slot (re-time the scene or shorten the line):")
        print("\n".join(overruns))
    return out
