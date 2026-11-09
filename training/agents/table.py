#!/usr/bin/env python3
"""Print the movie table for training/README.md from training/index.yaml: one row per
agent with the live link, the length, whether it is narrated here, and the chapter times."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lib.agent_movie import parse_index_titles  # noqa: E402

ORDER = ["oracle", "bookworm", "adversary", "artist", "scribe", "teacher", "lab_oracle", "blacksmith",
         "conscience", "lawyer", "millwright", "centre_millwright", "judge", "registrar", "security_guard", "clerk", "docent"]
SITE = "https://mikehallett.science/assets/videos/murmurent_agent_"
info = parse_index_titles()
text = (HERE.parent / "index.yaml").read_text()
print("| Agent | Watch | Length | Narrated | Chapters |")
print("|---|---|---|---|---|")
for a in ORDER:
    e = info.get(a)
    if not e:
        continue
    block = re.search(rf"^- agent: {a}\n(.*?)(?=^- agent:|\Z)", text, re.S | re.M).group(1)
    chapters = re.findall(r'\["([^"]+)", "([^"]+)"\]', block)
    secs = int(e["seconds"])
    narrated = (HERE / a / f"{a}_narrated.mp4").exists()
    print(f"| [`{a}`](../agents/{a}.md) | [{e['title']}]({SITE}{a}.html) | {secs // 60}:{secs % 60:02d} | "
          f"{'yes' if narrated else 'not yet'} | " + ", ".join(f"{t} {n}" for t, n in chapters) + " |")
