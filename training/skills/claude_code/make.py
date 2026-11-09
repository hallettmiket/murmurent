#!/usr/bin/env python3
"""Render this movie: python3 training/skills/<name>/make.py [--stills DIR] [--no-voice].
The content is in scenes.py and transcript.md beside this file; the renderer is training/lib/."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from lib.movie import main  # noqa: E402
from scenes import MOVIE  # noqa: E402

main(MOVIE, HERE)
