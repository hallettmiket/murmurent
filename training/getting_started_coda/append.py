#!/usr/bin/env python3
"""
Purpose: Append the rendered coda (getting_started_coda_narrated.mp4, 1280x720) to the
         getting-started video (1920x1080) and extend its captions.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: --video <the 1080p mp4>, --vtt <its captions>, the narrated coda beside this script.
Output: the mp4 rewritten in place (re-encoded once), the vtt and
        training/murmurent_getting_started.srt extended with the coda's cues.
Usage: python3 training/getting_started_coda/append.py --video <mp4> --vtt <vtt>
"""
import argparse
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def secs(s: str) -> float:
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def fmt(t: float, sep: str) -> str:
    h, rem = divmod(t, 3600)
    m, rem = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(rem):02d}{sep}{int((rem % 1) * 1000):03d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--vtt", required=True)
    args = ap.parse_args()
    video, vtt = Path(args.video), Path(args.vtt)
    coda = HERE / "getting_started_coda_narrated.mp4"
    base_len = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                              "-of", "csv=p=0", str(video)], text=True))
    out = video.with_suffix(".with_coda.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(coda), "-filter_complex",
                    "[1:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v1];[1:a]aresample=48000[a1];"
                    "[0:v]fps=30,format=yuv420p[v0];[0:a]aresample=48000[a0];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)], check=True)
    out.replace(video)
    # captions: the coda's srt cues shifted by the old length
    cues = []
    for block in (HERE / "getting_started_coda.srt").read_text().strip().split("\n\n"):
        lines = block.split("\n")
        a, b = lines[1].split(" --> ")
        cues.append((secs(a) + base_len, secs(b) + base_len, " ".join(lines[2:])))
    v = vtt.read_text().rstrip("\n") + "\n\n" + "\n\n".join(f"{fmt(a, '.')} --> {fmt(b, '.')}\n{t}" for a, b, t in cues) + "\n"
    vtt.write_text(v)
    srt = HERE.parent / "murmurent_getting_started.srt"
    text = srt.read_text().rstrip("\n")
    n = text.count("-->")
    for i, (a, b, t) in enumerate(cues, 1):
        text += f"\n\n{n + i}\n{fmt(a, ',')} --> {fmt(b, ',')}\n{t}"
    srt.write_text(text + "\n")
    print(f"appended {len(cues)} cues after {base_len:.1f} s; wrote {video}, {vtt}, {srt}")


if __name__ == "__main__":
    main()
