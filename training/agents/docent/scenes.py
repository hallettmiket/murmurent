"""The docent movie (short cut): plain statements checked against agents/docent.md, and two exchanges shared with the long thesis movie."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import LAV

SPEC = AgentSpec(
    agent="docent",
    title="The docent",
    tagline="Answers questions about a paper or thesis with the exact place in the work",
    colour=LAV,
    icon="doc",
    intro=["I am the docent. A reviewer or an examiner asks me about a paper or a thesis, and I answer "
           "with the exact place in the work: the chapter, the figure, the script."],
    does=[
        Quote("Every answer names the place in the work.", "place in the work it rests"),
        Quote("When a claim has code, it re-runs it before reporting the number.", "re-run"),
        Quote("Absent, when the work does not address the question.", "Absent"),
        Quote("Every question and answer is kept in a log.", "log"),
    ],
    does_narration=[
        "Every answer I give names the place in the work it rests on, and quotes the sentence. When a claim has code, "
        "I re-run it before reporting the number.",
        "When the work does not address the question, I say Absent, and name the nearest thing the work "
        "does cover. Every question and answer is kept in a log, part of the record of the examination."],
    refuses=[
        Quote("For reviewers and examiners: questions about the work.", "examiner"),
        Quote("For the author: the package, the defence talk, the paperwork.", "author"),
        Quote("Points at the work; the examiner decides.", "examiner decides"),
        Quote("Offline, because a thesis under examination is not public.", "offline"),
    ],
    refuses_narration=[
        "I work for both sides. For a reviewer or an examiner, I answer questions about the work. For the "
        "author, I help build the package: the work with each claim linked to its code and data.",
        "I point at the work and leave the judging to others: the examiner decides. For the institution's "
        "own steps and deadlines, I ask the clerk. I work offline, "
        "because a thesis under examination is not public."],
    examples=[
        Exchange("1", ["A real exchange, on a made-up thesis. The examiner asks me where it shows that serum "
                       "enlarges colonies, and whether that result holds.",
                       "I name the chapter and the figure, re-run the script, and get the same "
                       "numbers. I also say what the text leaves out, and who should judge the test."],
                 [("read the list of claims", True), ("open the PDF", True), ("re-run the analysis", True)],
                 who="Examiner"),
        Exchange("2", ["Asked about incubation temperature, which the thesis never mentions, I answer "
                       "Absent, list where I looked, and name the nearest thing the thesis does cover."],
                 [("search the package", True), ("fill the gap", False)], who="Examiner"),
    ],
    prompt="ask the docent where the thesis shows that serum enlarges colonies, and whether it holds",
    give="The paper or thesis package, and your question in plain words.",
    verdicts="Located, Absent or Incomplete, then the places, the re-run, and the log entry.",
    howto_narration=[
        "To use me, open the package in Claude Code and type your question to the docent. Give me the question "
        "in plain words; I work out whether you are the examiner or the author.",
        "The first line is the verdict: Located, Absent, or Incomplete when the package itself is missing "
        "something. The detail gives the places and the re-run. Each package carries its own note on where "
        "things are, and I read it first."],
    docs=["docs/paper_package.md"],
)
