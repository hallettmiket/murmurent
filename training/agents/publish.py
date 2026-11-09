#!/usr/bin/env python3
"""
Purpose: Copy the agent movies to the website repository: for each agent
         with a movie here (the narrated one when it exists, else the silent
         captioned one), write
         assets/videos/murmurent_agent_<agent>_720p.mp4, a .vtt made from the
         .srt, and a player page murmurent_agent_<agent>.html (same shape as
         murmurent_thesis_package.html). Commits nothing: the website repo may
         hold the owner's unstaged changes, so staging and pushing are done by
         hand, naming only these files.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-07
Input: training/agents/<agent>/{<agent>_narrated.mp4, <agent>.srt, scenes.py};
       training/index.yaml for the durations.
Output: the three files per agent under <site>/assets/videos/; then runs
        training/front_page.py, which writes index.html there; prints the list.
Usage: python3 training/agents/publish.py [--site ~/repos/hallettmiket.github.io] [agent ...]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lib.agent_movie import GLYPHS, parse_index_titles  # noqa: E402


def index_videos() -> list:
    import yaml
    return (yaml.safe_load((HERE.parent / "index.yaml").read_text()) or {}).get("videos", [])

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; padding: 24px 16px; font-family: system-ui, sans-serif; background: Canvas; color: CanvasText; }}
  main {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 16px; }}
  .avatar {{ display: inline-block; width: 2.4rem; height: 2.4rem; line-height: 2.4rem; text-align: center; font-size: 1.5rem; border-radius: 50%; background: color-mix(in srgb, CanvasText 10%, transparent); margin-right: 0.6rem; vertical-align: middle; }}
  video {{ width: 100%; height: auto; border-radius: 8px; background: #000; }}
  p {{ line-height: 1.5; }}
</style>
</head>
<body>
<main>
  <h1>{avatar}{title}</h1>
  <video controls preload="metadata">
    <source src="{stem}_720p.mp4" type="video/mp4">
    <track kind="captions" src="{stem}_720p.vtt" srclang="en" label="English">
  </video>
  <p>{tagline}. {minutes}; captions are in the picture; every terminal and chat scene is a real run.
  {source}
  All the training videos: <a href="index.html">mikehallett.science/assets/videos</a>.</p>
</main>
</body>
</html>
"""


def srt_to_vtt(srt: str) -> str:
    out = ["WEBVTT", ""]
    for line in srt.splitlines():
        if "-->" in line:
            line = line.replace(",", ".")
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="~/repos/hallettmiket.github.io")
    ap.add_argument("agents", nargs="*")
    args = ap.parse_args()
    dest = Path(args.site).expanduser() / "assets" / "videos"
    dest.mkdir(parents=True, exist_ok=True)
    info = parse_index_titles()
    agents = args.agents or sorted(p.name for p in HERE.iterdir() if (p / f"{p.name}.mp4").exists())
    jobs = [(HERE / a, a, f"murmurent_agent_{a}", info.get(a, {})) for a in agents]
    videos = {v.get("key"): v for v in index_videos()}
    skills = HERE.parent / "skills"
    if skills.is_dir() and not args.agents:
        for p in sorted(skills.iterdir()):
            if (p / f"{p.name}.mp4").exists():
                jobs.append((p, p.name, f"murmurent_{p.name}", videos.get(p.name, {})))
    for folder, key, stem, entry in jobs:
        narrated = (folder / f"{key}_narrated.mp4").exists()
        mp4 = folder / (f"{key}_narrated.mp4" if narrated else f"{key}.mp4")
        srt = folder / f"{key}.srt"
        if not mp4.exists() or not srt.exists():
            print(f"skip {key}: no movie or srt", file=sys.stderr)
            continue
        secs = int(entry.get("seconds", 0))
        minutes = f"{secs // 60} min {secs % 60} s" if secs else "A few minutes"
        if not narrated:
            minutes += " (captions only for now; the narration is added when the movie is re-voiced)"
        spec_text = (folder / "scenes.py").read_text()
        tagline = re.search(r'tagline="([^"]+)"', spec_text).group(1).rstrip(".")
        shutil.copyfile(mp4, dest / f"{stem}_720p.mp4")
        (dest / f"{stem}_720p.vtt").write_text(srt_to_vtt(srt.read_text()))
        (dest / f"{stem}.html").write_text(PAGE.format(
            title=entry.get("title", key), stem=stem, tagline=tagline, minutes=minutes,
            avatar=(f'<span class="avatar" aria-hidden="true">{GLYPHS[key]}</span>' if key in GLYPHS else ""),
            source=(f'The agent\'s own definition: <a href="https://github.com/hallettmiket/murmurent/blob/main/agents/{key}.md">agents/{key}.md</a>.'
                    if stem.startswith("murmurent_agent_") else
                    f'How it is made: <a href="https://github.com/hallettmiket/murmurent/blob/main/training/README.md">training/README.md</a>.')))
        print(f"{key}: {mp4.stat().st_size / 1e6:.1f} MB, {minutes}{'' if narrated else ', SILENT'}")
    subprocess.run([sys.executable, str(HERE.parent / "front_page.py"), "--site", args.site], check=True)


if __name__ == "__main__":
    main()
