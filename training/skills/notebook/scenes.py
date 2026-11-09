"""Your lab notebook: a bench scientist's day, in natural language, with the commands as footnotes
(issues #292 to #294, revised after the PI's review of the first cut)."""
from lib.draw import AMBER, LAV, RED, TEAL
from lib.movie import Movie, Part, Quote

ENTRY = """## 14:48
Run 3 serum plates look bigger than the controls; re-plate the two Peru isolates tomorrow.
## 15:28
Design: gel 27 on the four serum samples, lane 3 is the control; RNA from plates 5 and 6 after lunch.
## 15:28 image: gel_27.jpg
![[gel_27_thumb.jpg]]
- note: lane 3 is the control
> Machine reading (not the record): to be added by Claude Code in this session
## 15:28 sound note: gel27_voice.m4a
> Transcription failed; the recording is on the server""".split("\n")

T_REPORT = """
$ (what Claude Code runs: murmurent notebook report --for supervisor --since 2026-11-01)
Report for supervisor, 2026-11-01 to 2026-11-07: 1 entry of 2 in the range.
Entries drawn on (whole entries; audience is per entry):
  - lab-notebook/2026-11-07.md (2026-11-07, project demo_project, audience supervisor)
Files drawn on:
  - attachments/2026-11-07/gel_27_thumb.jpg (from the vault, embedded)
  - local:~/append_only/demo_project/notebook/2026-11-07/gel_27.jpg (on the server, linked)
Written: report.html (the page), material.md (for the scribe), sources.md (the source list)
Nothing has been sent. Read the page and the source list first; then deliver it:
  as a private Claude artifact, to the channel with murmurent project note, or as a file.
"""

MOVIE = Movie(
    key="notebook",
    title="Your lab notebook",
    tagline="A day at the bench, and how it reaches your notebook",
    glyph="📓",
    colour=LAV,
    summary="A bench scientist's day with the lab notebook: the experimental design if you like, a gel photo from the phone, a voice note with gloves on, a prompt written in Obsidian and sent to Claude Code with one keystroke, the day recalled, and a report for the supervisor. Natural language throughout; the commands as footnotes.",
    parts=[
        Part("title", ["Your lab notebook lives in your own Obsidian vault. Here is one day at the bench, and how "
                       "it reaches the notebook by talking to Claude Code. The command behind each step is a "
                       "footnote; you never type it."]),
        Part("story", chapter="The design", heading="First, if you like: the experimental design, in Obsidian", picture="bench",
             prompt="(in Obsidian, in today's entry) Design: gel 27 on the four serum samples, lane 3 is the control.",
             reply=["Nothing to run: the entry is a plain text note in your vault, and the oracle reads it as it is."],
             footnote="none: lab-notebook/2026-11-07.md is yours to write; murmurent reads it",
             narration=["First, you might write down the experimental design in Obsidian, in today's entry, "
                        "as you would in a paper notebook: a line or two. Or not; the day's entry starts "
                        "whenever you first add something to it."]),
        Part("story", chapter="The gel photo", heading="At the bench: the gel photo, phone to laptop to notebook", picture="phone",
             prompt="add this photo of gel 27 to today's notebook, lane 3 is the control",
             reply=["Added image gel_27.jpg to today's entry under 15:28.",
                    "The original is on the lab server, kept as it is; a small copy is in the vault.",
                    "Machine reading (not the record): to be added in this session."],
             footnote="murmurent notebook add ~/Desktop/gel_27.jpg --note \"lane 3 is the control\"",
             narration=["You photograph the gel with your phone and send it to the laptop (AirDrop on a Mac). Drag the file into "
                        "Claude Code and say: add this photo of gel 27 to today's notebook, lane 3 is the control.",
                        "The original goes to the lab server, kept as it is; the vault keeps a small copy. "
                        "Claude Code then writes one line on what it sees, marked as a reading, not the record."]),
        Part("story", chapter="A voice note", heading="Gloves on: a voice note", picture="gel",
             prompt="add my voice note gel27_voice.m4a to today's notebook",
             reply=["Added sound note gel27_voice.m4a under 15:28; the recording is on the lab server.",
                    "It is written out as text if a speech-to-text service is set up when you add it;",
                    "otherwise the entry says it was skipped."],
             footnote="murmurent notebook add ~/Desktop/gel27_voice.m4a",
             narration=["With gloves on, you record a voice note: lane four has an extra band, run it again "
                        "tomorrow. It goes to the server the same way. It is written out as text if a speech-to-text "
                        "service is set up when you add it; otherwise the entry says it was skipped."]),
        Part("obsidian", chapter="The entry", heading="The day's entry, as Obsidian shows it", note_title="2026-11-07",
             note_lines=ENTRY, sidebar=["2026-11-05", "2026-11-07", "attachments", "prompts", "sessions"],
             narration=["In Obsidian the day is one page: the design, the gel with its small copy and a link to the "
                        "original, and the voice note. The entry also records its project and its audience: who "
                        "may read it."]),
        Part("story", chapter="Prompts: write, send, keep", heading="Afternoon: a prompt written in Obsidian, sent with one key",
             picture="obsidian",
             prompt="(written in Obsidian, selected, sent with one key) ask the blacksmith to count the bands in gel_27.jpg per lane and compare lane 3, the control, with the others",
             reply=["The prompt lands in Claude Code and the blacksmith gets to work. It is kept in",
                    "today's sessions page with the time, and it leaves the note it was written in."],
             footnote="murmurent prompt send --quiet --text {{selection}}   (the Obsidian hotkey, set to replace the selection)",
             narration=["Long prompts are easier to write in Obsidian than in a terminal. Write one in any note, "
                        "select it and press one key, set up once: it goes into Claude Code and is kept with the time, like "
                        "every prompt Claude Code receives. Set the key to replace the selection and the prompt "
                        "leaves the note, so a day of prompts does not cloud the entry."]),
        Part("chat", chapter="End of day: ask", key="1", agent="oracle", colour=LAV, who="Member",
             chips=[("read today's entry", True), ("read the sessions", True)],
             narration=["At the end of the day you ask the oracle what you noted about gel 27 and what is planned "
                        "for tomorrow. It answers from the entry, block by block, with the times, and names the "
                        "parts still waiting for a reading."]),
        Part("terminal", chapter="End of week: the report", heading="End of week: a report for your supervisor",
             transcript=T_REPORT, title="What Claude Code runs when you ask for the report", colour=LAV,
             notes=[("Only entries your supervisor is allowed to read, each one whole.", "allowed"),
                    ("Every entry and file it drew on is listed first.", "lists"),
                    ("It waits for your word before anything is sent.", "sends nothing")],
             narration=["At the end of the week you ask: make my report for my supervisor since the first of "
                        "November. It takes only the entries your supervisor is allowed to read, lists every entry and file it drew on, and "
                        "writes a page. It sends nothing until you say so."]),
        Part("howto", heading="How to use it, day to day",
             prompt="add this photo of gel 27 to today's notebook, lane 3 is the control",
             cards=[("Photos and voice notes", "Send to the laptop, drag into Claude Code, say what it is."),
                    ("Prompts", "Write in any Obsidian note, select it, press one key (set up once)."),
                    ("Sharing", "Each entry names its audience; a report takes only those entries.")],
             docs=["docs/lab_notebook.md"],
             narration=["Day to day: photos and voice notes go from the phone into Claude Code with a sentence. "
                        "Prompts are written in Obsidian and sent with one key. Each entry says who may read it, "
                        "and a report follows that."]),
    ],
)
