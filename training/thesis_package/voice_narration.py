"""
Purpose: Voice the narration of thesis_package.mp4 with ElevenLabs and mux it
         into the movie. Reads thesis_package.srt (one cue per caption), makes
         one clip per cue (cached by the text's hash, so a re-render that
         changes two sentences re-voices two clips), places each clip at its
         cue's start time, and writes thesis_package_narrated.mp4. Reports any
         clip longer than its slot, so the movie can be re-timed.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: thesis_package.srt and thesis_package.mp4 beside this script; the
       ElevenLabs API key in the macOS Keychain (service elevenlabs-api-key,
       as training/README.md step 4 stores it) or $ELEVENLABS_API_KEY.
Output: audio/<hash>.mp3 per cue, audio/narration.wav, thesis_package_narrated.mp4.
Usage: python3 training/thesis_package/voice_narration.py [--voice Matilda]
       [--dry-run]   (dry-run: parse, report slots, call nothing)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
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
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="Matilda")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cues = parse_srt(HERE / "thesis_package.srt")
    AUDIO.mkdir(exist_ok=True)
    print(f"{len(cues)} cues, {sum(len(t.split()) for _, _, t in cues)} words")
    if args.dry_run:
        return
    key = api_key()
    voices = json.loads(request("/voices", key))["voices"]
    # Names come back as "Matilda - Knowledgable, Professional"; match the name before the dash.
    voice_id = next((v["voice_id"] for v in voices
                     if v["name"].split(" - ")[0].strip().lower() == args.voice.lower()), None)
    if not voice_id:
        sys.exit(f"No voice named {args.voice!r}; available: {', '.join(v['name'] for v in voices)}")

    clips: list[tuple[float, Path]] = []
    overruns: list[str] = []
    for start, end, text in cues:
        h = hashlib.sha1((args.voice + MODEL + text).encode()).hexdigest()[:12]
        clip = AUDIO / f"{h}.mp3"
        if not clip.exists():
            clip.write_bytes(request(f"/text-to-speech/{voice_id}", key,
                                     {"text": text, "model_id": MODEL}, accept="audio/mpeg"))
            print(f"voiced {h}: {text[:60]}...")
        d = duration(clip)
        if d > end - start + 0.3:
            overruns.append(f"{start:7.1f}s  slot {end - start:5.1f}s  clip {d:5.1f}s  {text[:50]}...")
        clips.append((start, clip))

    # Place every clip at its start on one silent track the length of the movie.
    movie = HERE / "thesis_package.mp4"
    total = duration(movie)
    inputs: list[str] = []
    filters: list[str] = []
    for i, (start, clip) in enumerate(clips):
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad=whole_dur={total}[out]"
    narration = AUDIO / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
                    ";".join(filters + [mix]), "-map", "[out]", "-t", str(total), str(narration)], check=True)
    out = HERE / "thesis_package_narrated.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(movie), "-i", str(narration),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)], check=True)
    print(f"wrote {out}")
    if overruns:
        print("Clips longer than their caption slot (re-time the scene or shorten the line):")
        print("\n".join(overruns))


if __name__ == "__main__":
    main()
