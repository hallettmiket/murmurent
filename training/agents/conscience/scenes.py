"""The conscience movie: narration, plain-statement cards checked against agents/conscience.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="conscience",
    title="The conscience",
    tagline="Equity, diversity, inclusion and decolonization review that says where every finding comes from",
    colour=SAND,
    icon="check",
    intro=["This is the conscience. It reviews your writing for equity, diversity, inclusion and "
           "decolonization, and hands back the fixed text."],
    does=[
        Quote("Quotes the exact line, and says what a reader gets wrong.", "exact line"),
        Quote("Hands back a rewritten passage you can paste in.", "rewritten"),
        Quote("Cites a source for every finding, or marks it to check.", "source"),
        Quote("Designs who a study includes and asks, before anything is built.", "design"),
    ],
    does_narration=[
        "It quotes the exact line, says what a reader or a reviewer gets wrong because of it, and hands back "
        "a rewritten passage to paste in, with the version it recommends.",
        "Every finding cites the source it rests on, or is marked as its own knowledge to check. When nothing "
        "is built yet, it returns a design instead: who is included, who is asked, whose risk is named."],
    refuses=[
        Quote("Covers framing, language, and who a study includes.", "framing"),
        Quote("Uses what communities have published about themselves.", "published"),
        Quote("Statistics go to the adversary; lawfulness to the lawyer.", "adversary"),
        Quote("Edits your file only when you ask it to.", "apply"),
    ],
    refuses_narration=[
        "Its scope is equity: framing, language, and who a study includes. About a community, it uses what "
        "that community has published about itself, and says where that stops.",
        "Statistics go to the adversary and lawfulness to the lawyer. It edits your file only when you ask "
        "it to apply the changes."],
    examples=[
        Exchange("1", ["A real run, on a made-up Participants paragraph. A member asks for a review.",
                       "The answer is Flagged: the draft calls an English-only cohort from one clinic "
                       "representative of Canada. Each finding quotes the line and names its source, and a "
                       "closing list says what it could not back up, for the bookworm to find."],
                 [("read the draft", True), ("read its resources", True), ("write the report", True)]),
    ],
    prompt="ask the conscience to review the Participants section of my methods",
    give="The section to review, or, for a study in planning, the plan.",
    verdicts="OK or Flagged for a review, Designed for a plan, Gap when it cannot deliver. Each finding quotes its line and its source.",
    howto_narration=[
        "To use it, ask Claude Code for the conscience and point it at a section, a grant or a course outline. "
        "The first line is the verdict: OK or Flagged for a review, Designed for a plan, or Gap when it "
        "cannot deliver.",
        "It draws on a curated list of resources chosen for the centre's region. The bookworm can propose "
        "additions to the centre's list, such as a funder's equity guidance, and a person approves each one."],
    docs=["docs/edid_resources.md"],
)
