"""The clerk movie: narration in the clerk's own voice, plain statements checked against agents/clerk.md, and the real exchanges in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="clerk",
    title="The clerk",
    tagline="Ask it anything about your institution; it reads the answer off the institution's own pages",
    colour=SAND,
    icon="cal",
    intro=["I am the clerk. Ask me anything about your institution: who runs an office, when an exam must "
           "be printed, whether a course outline follows the rules. I read the answer on the institution's "
           "own pages, then and there."],
    does=[
        Quote("Reads the institution's own public pages when you ask.", "public pages"),
        Quote("Names the page it read and the date.", "name the page"),
        Quote("Remembers what it found, and re-reads the page next time.", "remember"),
        Quote("Reviews a whole document against the rules and calendar, a course outline for instance.", "course outline"),
    ],
    does_narration=[
        "I read the institution's public pages when you ask, and I name the page and the date. I "
        "remember what I found, and I re-read the page before relying on it, because people change offices.",
        "I can also review a whole document against the institution's rules, a course outline for instance: "
        "every rule for the course's level, every date against the calendar and the holidays, and whether the "
        "grades add to one hundred."],
    refuses=[
        Quote("Unknown, when the institution's pages do not say.", "Unknown"),
        Quote("Public pages only; behind a login, it says where to look.", "login"),
        Quote("Hands a reviewed outline on to the conscience, and the fixes to the scribe.", "conscience"),
        Quote("Supplies the docent with the institution's own paperwork and deadlines.", "docent"),
    ],
    refuses_narration=[
        "When the pages do not say, my answer is Unknown, with the nearest thing they do say. A page "
        "behind a login I leave to you, and I say where to read it.",
        "I work with other agents: after a course review, the conscience reviews the outline for equity and "
        "inclusion, and the scribe redoes it with the fixes. The docent asks me for a thesis's paperwork and deadlines."],
    examples=[
        Exchange("1", ["A real run, one example among many. An instructor asks when their final exam must be printed this fall.",
                       "I quote the rule and the exam period, each with its page, and work out the date. "
                       "The course's own exam date sits behind a login, so that part is Unknown."],
                 [("check my memory", True), ("search the university's site", True), ("read the pages", True), ("remember it", True)]),
        Exchange("2", ["Another example. Asked who runs the equity, diversity and inclusion office, I answer with the name, "
                       "title and public email, each from a page I opened."],
                 [("check my memory", True), ("search the university's site", True), ("read the pages", True), ("remember it", True)]),
        Exchange("3", ["Then a whole course outline. The university has a rule: no test in the last three weeks of classes. "
                       "This outline puts a quiz there, so I flag it, quoting the rule and its page. A lab report "
                       "announced too late breaks a second rule."],
                 [("read the outline", True), ("apply the rules", True), ("check the calendar", True), ("write the report", True)]),
    ],
    prompt="ask the clerk when the final exam for BIOCHEM 3391 has to be printed this fall",
    give="Your question in plain words. For a review, the document and, for a course, its level.",
    verdicts="Correct, Fix or Unknown, each with the page it read and the date.",
    howto_narration=[
        "To use me, type your question to Claude Code and name me, the clerk. The first line is my verdict: "
        "Correct, Fix or Unknown.",
        "My memory holds short facts from your university's pages, each with its page and date; another "
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
        "These are examples, not a list of what I can do. Ask me anything the institution's pages answer: "
        "a policy, a deadline, a form, a fee, a room."],
    docs=["docs/institution_pack.md", "institution/README.md"],
)
