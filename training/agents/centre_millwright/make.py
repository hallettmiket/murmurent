#!/usr/bin/env python3
"""Render this agent's movie: python3 training/agents/<agent>/make.py [--stills DIR] [--no-voice].
The content is in scenes.py and transcript.md beside this file; the renderer is training/lib/."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from lib.agent_movie import main  # noqa: E402
from scenes import SPEC  # noqa: E402

main(SPEC, HERE)
