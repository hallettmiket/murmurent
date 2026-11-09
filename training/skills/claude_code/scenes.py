"""Working through Claude Code: the two-minute movie every other movie assumes (issue #290)."""
from lib.draw import AMBER, RED, TEAL
from lib.movie import Movie, Part, Quote

T_OPEN = """
$ cd ~/repos/demo_project
$ ls -a
.  ..  .git  .murmurent.yaml  data  src
$ ls -l ~/.claude/agents | head -3
adversary.md -> ~/repos/murmurent/agents/adversary.md
artist.md -> ~/repos/murmurent/agents/artist.md
blacksmith.md -> ~/repos/murmurent/agents/blacksmith.md
$ ls ~/.claude/rules
data-storage.md  headline_first.md  oracle_schema.md
project-structure.md  slack.md  voice.md
$ claude
"""

T_LOG = """
$ tail -F ~/.murmurent/agents.log
[2026-11-07 09:31] blacksmith: Done: serum effect survives stratifying by country. Weighted within-country difference is +0.85 mm
[2026-11-07 09:32] bookworm: Found 3 sources: two cohort studies and one meta-analysis on serum and wound healing
[2026-11-07 09:32] conscience: Flagged: the draft calls an English-only cohort from one clinic "representative of the Canadian population"
[2026-11-07 12:14] adversary: Pass: folds are clean and the result holds when each site is left out
"""

MOVIE = Movie(
    key="claude_code",
    title="Working through Claude Code",
    tagline="Type plain English; name an agent when you want one",
    glyph="💬",
    colour=AMBER,
    summary="You type plain English to Claude Code, name an agent when you want one, read the first line of every reply for the answer, and keep what you find in your own notebook and oracle.",
    parts=[
        Part("title", ["This is how you work with Murmurent: you type to Claude Code in plain English. "
                       "Every other movie assumes these two minutes."]),
        Part("terminal", chapter="Opening a project", heading="Opening your project",
             transcript=T_OPEN, title="Terminal",
             notes=[("Your project folder is already set up for Murmurent.", "set up"),
                    ("The agents and the shared rules arrive once, with the install.", "install"),
                    ("Start Claude Code in the folder; from then on, you type English.", "English")],
             narration=["You open your project folder, which is already set up for Murmurent. The agents and the "
                        "shared rules arrive once, with the install, so every session has them.",
                        "Then you start Claude Code in that folder. From then on, you type English."]),
        Part("cards", chapter="Asking an agent", heading="Asking an agent by name",
             source="docs/agents.md", colour=TEAL,
             quotes=[Quote("Ask in plain English; Claude Code does the work.", "plain English"),
                     Quote("Name an agent when you want one.", "name"),
                     Quote("Each agent has one job, such as remembering or checking.", "one job")],
             narration=["Ask for what you want in plain English, and Claude Code does the work. When you want a "
                        "specialist, name it: ask the bookworm for papers, ask the adversary to check an analysis, "
                        "ask the oracle to remember a finding. Each agent has one job."]),
        Part("chat", chapter="A real exchange", key="1", agent="security_guard", colour=RED, who="Member",
             chips=[("read the changes", True), ("secret patterns", True), ("patient details", True)],
             narration=["Here is a real exchange. The member names the security guard and says what to check.",
                        "The first line of every reply is the answer. Here it is Blocked. Read that line first; the "
                        "detail below says where and why."]),
        Part("terminal", chapter="Watching the agents", heading="Watching the agents work", transcript=T_LOG,
             title="Terminal, bottom right", colour=TEAL,
             notes=[("Each agent's first line appears here when it finishes.", "finishes"),
                    ("Keep this window in a corner of the screen.", "corner")],
             narration=["Each agent's first line also appears in a small window as it finishes. Keep that window "
                        "in a corner of the screen, and you can follow the agents without reading their full replies."]),
        Part("bullets", chapter="Where your work goes", heading="Where your work goes", colour=TEAL, mark="tick",
             notes=[("Every request is kept in your notebook, except patient details or passwords.", "notebook"),
                    ("Ask the oracle to remember a finding, and it keeps it.", "oracle"),
                    ("Agents are stopped from changing your lab's original data.", "original data")],
             narration=["Your work is kept. Every request you type is kept in your notebook's record of sessions, "
                        "except one that looks like patient details or a password. Ask the oracle to remember a finding, and it keeps it for "
                        "the next time you ask.",
                        "And inside Claude Code, agents are stopped from changing your lab's original data."]),
        Part("howto", heading="The habits that matter",
             prompt="ask the adversary to check my classifier results before I send them to my PI",
             cards=[("Name the agent", "Say which agent, and give it the files themselves, not a summary."),
                    ("Read the first line", "The first line of every reply is the answer."),
                    ("Keep what you find", "Ask the oracle to remember it; your notebook keeps the rest.")],
             docs=["docs/agents.md", "docs/vscode-workflow.md", "rules/headline_first.md"],
             narration=["Three habits matter. Name the agent and give it the files themselves. Read the first line "
                        "of the reply. And ask the oracle to remember what you find.",
                        "Each agent has its own short movie that shows it this way."]),
    ],
)
