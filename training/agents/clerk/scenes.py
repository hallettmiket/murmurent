"""The clerk movie: narration, plain statements checked against agents/clerk.md, and the real exchanges in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="clerk",
    title="The clerk",
    tagline="Ask it anything about your institution; it reads the answer off the institution's own pages",
    colour=SAND,
    icon="cal",
    intro=["This is the clerk. Ask it anything about your institution: who runs an office, when an exam must "
           "be printed, whether a course outline follows the rules. It reads the answer on the institution's "
           "own pages, then and there."],
    does=[
        Quote("Reads the institution's own public pages when you ask.", "public pages"),
        Quote("Names the page it read and the date.", "names the page"),
        Quote("Remembers what it found, and re-reads the page next time.", "remembers"),
        Quote("Reviews a whole course outline against the rules and calendar.", "course outline"),
    ],
    does_narration=[
        "It reads the institution's public pages when you ask, and names the page and the date. It "
        "remembers what it found, and re-reads the page before relying on it, because people change offices.",
        "It also reviews a whole course outline: every rule it has on file for the course's level, and the "
        "others by reading; every date against holidays; and whether the grades add to one hundred."],
    refuses=[
        Quote("Unknown, when the institution's pages do not say.", "Unknown"),
        Quote("Public pages only; behind a login, it says where to look.", "login"),
        Quote("The conscience then reviews the outline for equity and inclusion.", "conscience"),
        Quote("The scribe redoes the outline with the fixes, on request.", "scribe"),
    ],
    refuses_narration=[
        "When the pages do not say, the answer is Unknown, with the nearest thing they do say. A page "
        "behind a login it leaves to you, and says where to read it.",
        "After a course review, the conscience reviews the outline for equity and inclusion, and the scribe "
        "redoes it with the fixes on request."],
    examples=[
        Exchange("1", ["A real run. An instructor asks when their final exam must be printed this fall.",
                       "The clerk quotes the rule and the exam period, each with its page, and works out the date. "
                       "The course's own exam date sits behind a login, so that part is Unknown."],
                 [("check its memory", True), ("search the university's site", True), ("read the pages", True), ("remember it", True)]),
        Exchange("2", ["Asked who runs the equity, diversity and inclusion office, it answers with the name, "
                       "title and public email, each from a page it opened."],
                 [("check its memory", True), ("search the university's site", True), ("read the pages", True), ("remember it", True)]),
        Exchange("3", ["Then a whole course outline. Two things must change: a quiz in the last three weeks of classes, and a lab report "
                       "announced too late. Each comes with the rule quoted and the page it was read from."],
                 [("read the outline", True), ("apply the rules", True), ("check the calendar", True), ("write the report", True)]),
    ],
    prompt="ask the clerk when the final exam for BIOCHEM 3391 has to be printed this fall",
    give="Your question in plain words. For a review, the course outline and its level.",
    verdicts="Correct, Fix or Unknown, each with the page it read and the date.",
    howto_narration=[
        "To use it, type your question to Claude Code and name the clerk. The first line is the verdict: "
        "Correct, Fix or Unknown.",
        "Its memory holds short facts from your university's pages, each with its page and date; another "
        "university gets a memory of its own."],
    directions=[
        ("ask the clerk to review my course outline for BIOCHEM 3391, an undergraduate course this fall",
         "A report: each rule with its page, every date checked, the grade total."),
        ("ask the clerk who the Graduate Chair of Biochemistry is and how to reach them",
         "The name, title and public email, with the page and the date."),
        ("ask the clerk for 25 working days before 26 March 2027, skipping holidays",
         "The date, the weekday, and the holidays it skipped."),
    ],
    directions_narration=[
        "Say what to look at: a course outline and its level, who holds an office, or a count of "
        "working days that skips holidays."],
    docs=["docs/institution_pack.md", "institution/README.md"],
)
