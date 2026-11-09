"""The conscience movie: narration in the conscience's own voice, plain-statement cards checked against agents/conscience.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="conscience",
    title="The conscience",
    tagline="Equity, diversity, inclusion and decolonization review that says where every finding comes from",
    colour=SAND,
    icon="check",
    intro=["I am the conscience. I review what you write for equity, diversity, inclusion and "
           "decolonization, and I hand back the fixed text. A grant, a paper, a course outline, an ethics "
           "application, a study plan: anything with people in it."],
    does=[
        Quote("A grant: its sex- and gender-based analysis, SGBA+, and the funder's equity rules.", "SGBA"),
        Quote("A course: decolonization, whose perspectives are taught, which nations are named.", "course"),
        Quote("A paper: inclusive language, and who the study includes and leaves out.", "paper"),
        Quote("Quotes the exact line, cites a source for every finding, and hands back the rewrite.", "exact line"),
    ],
    does_narration=[
        "Three examples. A grant application: I check its sex- and gender-based analysis, SGBA plus, which "
        "the health funders require, and the equity rules of the funder you are applying to.",
        "A course outline: I check it for decolonization. Whose perspectives are taught, whether Indigenous "
        "peoples are named as the specific nations concerned or flattened into one word, which voices are missing.",
        "A paper: I check the language for exclusion, and who the study includes and leaves out, with a "
        "number where one exists. Every time, I quote the exact line, cite a source for the finding, and hand "
        "back a rewritten passage you can paste in."],
    refuses=[
        Quote("Uses what communities have published about themselves; never speaks for them.", "published"),
        Quote("Designs who a study includes and asks, before anything is built.", "design"),
        Quote("Edits your file only when you ask it to.", "apply"),
        Quote("Draws on the centre's curated resources; the bookworm adds to them.", "resources"),
    ],
    refuses_narration=[
        "About a community, I use what that community has published about itself, and I say where that "
        "stops; I never speak for one. When nothing is built yet, I return a design instead: who is "
        "included, who is asked, whose risk is named.",
        "I edit your file only when you ask me to apply the changes. My findings rest on the centre's "
        "curated resources, chosen for its region; the bookworm adds to them when I find a gap."],
    examples=[
        Exchange("1", ["A real run, on a made-up Participants paragraph. A member asks for a review.",
                       "My answer is Flagged: the draft calls an English-only cohort from one clinic "
                       "representative of Canada. Each finding quotes the line and names its source, and a "
                       "closing list says what I could not back up, for the bookworm to find."],
                 [("read the draft", True), ("read its resources", True), ("write the report", True)]),
    ],
    prompt="ask the conscience to review the SGBA+ section of my CIHR grant",
    give="The section to review, or, for a study in planning, the plan.",
    verdicts="OK or Flagged for a review, Designed for a plan, Gap when it cannot deliver. Each finding quotes its line and its source.",
    howto_narration=[
        "To use me, ask Claude Code for the conscience and point me at a section, a grant or a course outline. "
        "The first line is my verdict: OK or Flagged for a review, Designed for a plan, or Gap when I "
        "cannot deliver.",
        "I draw on a curated list of resources chosen for the centre's region. The bookworm can propose "
        "additions to the centre's list, such as a funder's equity guidance, and a person approves each one."],
    directions=[
        ("ask the conscience to review the SGBA+ section of my CIHR grant",
         "Each requirement of the funder's sex and gender policy checked, with the line to change and a rewrite."),
        ("ask the conscience to review my course outline for BIOCHEM 3391 for decolonization",
         "Where the readings and perspectives are only Euro-Western, which nations to name, and what to add."),
        ("ask the conscience to review the Participants and Discussion sections of my paper for EDI language",
         "Each excluding word with its origin and the inclusive term, and who the study leaves out."),
    ],
    directions_narration=[
        "Say what the document is and what you want checked: a grant's SGBA plus section, a course outline "
        "for decolonization, or a paper's language. The document types are examples; the review is the same."],
    docs=["docs/edid_resources.md"],
)
