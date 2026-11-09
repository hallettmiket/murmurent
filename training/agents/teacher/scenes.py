"""The teacher movie: narration, plain-statement cards checked against agents/teacher.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import AMBER

SPEC = AgentSpec(
    agent="teacher",
    title="The teacher",
    tagline="Plain words: in a minute in chat, on a page you annotate, or over weeks",
    colour=AMBER,
    icon="star",
    intro=["This is the teacher. It explains things in plain words: a sentence that lost you, in a minute; "
           "a method or a paper, in one sitting; a whole subject, over weeks."],
    does=[
        Quote("Re-explains the sentence that just lost you, in under a minute.", "lost you"),
        Quote("Explains a method or a paper in one sitting.", "method"),
        Quote("Writes a page you can annotate, when you ask for one.", "page"),
        Quote("Teacher course starts a weeks-long course in your own session.", "weeks"),
    ],
    does_narration=[
        "When a sentence Claude Code just wrote lost you, it says it again in plain words, in under a minute.",
        "It explains a method or a paper in one sitting: in chat, or on request as a page where you mark "
        "what lost you. For a subject that takes weeks, it runs a course in your own session, with lessons "
        "that remember what you have learned."],
    refuses=[
        Quote("Shows a real image or video first; draws only when needed.", "image"),
        Quote("Links only to what it has actually opened.", "opened"),
        Quote("A debrief stays offline, because your session is private.", "offline"),
        Quote("The artist draws from your data; the bookworm checks citations.", "artist"),
    ],
    refuses_narration=[
        "Its scope is teaching. It shows a real image or a video it has checked before drawing anything, and "
        "it links only to what it has actually opened. A debrief stays offline, because your session is private.",
        "Figures made from your data go to the artist, and citations it cannot verify go to the bookworm."],
    examples=[
        Exchange("1", ["A real run. A wet-lab biologist asks what a permutation test is, and why the example "
                       "uses five thousand of them.",
                       "The answer is Explained: short bullets, each technical term defined, the real numbers "
                       "from the analysis, which it re-ran, and a takeaway to carry to the next problem."],
                 [("read the analysis code", True), ("re-run it", True), ("web search", False)]),
    ],
    prompt="teacher explain what a permutation test is, for a wet-lab biologist",
    give="Debrief: nothing. Explain: the method or paper. Course: the subject.",
    verdicts="Explained / Gap. Gap means it says plainly that it cannot deliver.",
    howto_narration=[
        "The first line is Explained, or Gap when it cannot honestly deliver.",
        "Say who it is for in your request, such as a wet-lab biologist; otherwise it writes for a colleague "
        "from a neighbouring field."],
    directions=[
        ("teacher debrief", "The sentence that lost you, said again in plain words, in under a minute."),
        ("teacher explain what a permutation test is", "Short bullets in chat, or a page you can annotate if you ask."),
        ("teacher course on survival analysis", "Lessons over weeks that remember what you have learned."),
    ],
    directions_narration=[
        "There are three things to type, in this order: debrief, at the sentence that lost you; explain, "
        "with the method or paper; and course, with the subject."],
    docs=["skills/murmurent-course/SKILL.md"],
)
