"""The docent movie (short cut): plain statements checked against agents/docent.md, and two exchanges shared with the long thesis movie."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import LAV

SPEC = AgentSpec(
    agent="docent",
    title="The docent",
    tagline="Answers questions about a paper or thesis with the exact place in the work",
    colour=LAV,
    icon="doc",
    intro=["This is the docent. A reviewer or an examiner asks it about a paper or a thesis, and it answers "
           "with the exact place in the work: the chapter, the figure, the script."],
    does=[
        Quote("Every answer names the place in the work.", "place in the work it rests"),
        Quote("When a claim has code, it re-runs it before reporting the number.", "re-runs"),
        Quote("Absent, when the work does not address the question.", "Absent"),
        Quote("Every question and answer is kept in a log.", "log"),
    ],
    does_narration=[
        "Every answer names the place in the work it rests on, and quotes the sentence. When a claim has code, "
        "it re-runs it before reporting the number.",
        "When the work does not address the question, it says Absent, and names the nearest thing the work "
        "does cover. Every question and answer is kept in a log, part of the record of the examination."],
    refuses=[
        Quote("For reviewers and examiners: questions about the work.", "examiner"),
        Quote("For the author: the package, the defence talk, the paperwork.", "author"),
        Quote("The adversary audits the method; the examiner decides.", "adversary"),
        Quote("Offline, because a thesis under examination is not public.", "offline"),
    ],
    refuses_narration=[
        "It works for both sides. For a reviewer or an examiner, it answers questions about the work. For the "
        "author, it helps build the package: the work with each claim linked to its code and data.",
        "It points at the work and leaves the judging to others: the adversary audits the method, and the "
        "examiner decides. The institution's own steps and deadlines come from the clerk. It works offline, "
        "because a thesis under examination is not public."],
    examples=[
        Exchange("1", ["A real exchange, on a made-up thesis. The examiner asks where it shows that serum "
                       "enlarges colonies, and whether that result holds.",
                       "The docent names the chapter and the figure, re-runs the script, and gets the same "
                       "numbers. It also says what the text leaves out, and who should judge the test."],
                 [("read the list of claims", True), ("open the PDF", True), ("re-run the analysis", True)],
                 who="Examiner"),
        Exchange("2", ["Asked about incubation temperature, which the thesis never mentions, it answers "
                       "Absent, lists where it looked, and names the nearest thing the thesis does cover."],
                 [("search the package", True), ("fill the gap", False)], who="Examiner"),
    ],
    prompt="ask the docent where the thesis shows that serum enlarges colonies, and whether it holds",
    give="The paper or thesis package, and your question in plain words.",
    verdicts="Located, Absent or Incomplete, then the places, the re-run, and the log entry.",
    howto_narration=[
        "To use it, open the package in Claude Code and type your question to the docent. Give it the question "
        "in plain words; it works out whether you are the examiner or the author.",
        "The first line is the verdict: Located, Absent, or Incomplete when the package itself is missing "
        "something. The detail gives the places and the re-run. Each package carries its own note on where "
        "things are, and the docent reads it first."],
    docs=["docs/paper_package.md"],
)
