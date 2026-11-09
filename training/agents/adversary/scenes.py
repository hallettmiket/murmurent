"""The adversary movie: narration in the adversary's own voice, plain-statement cards checked against agents/adversary.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import RED

SPEC = AgentSpec(
    agent="adversary",
    title="The adversary",
    tagline="The sceptical reviewer who tries to break your result before a referee does",
    colour=RED,
    icon="scale",
    intro=["I am the adversary, the sceptical reviewer. I try to break your result before a referee "
           "does: I re-run your analysis and I check what your write-up claims."],
    does=[
        Quote("Re-runs your analysis to see whether the numbers hold.", "re-run"),
        Quote("A t-test, a regression, a survival curve: the same checks as a classifier.", "t-test"),
        Quote("Looks for the classic faults: the wrong test, a hidden grouping, data leaking into training.", "faults"),
        Quote("Checks a write-up: each cited paper, and each reporting checklist item you missed.", "checklist"),
    ],
    does_narration=[
        "I re-run your code rather than trusting the write-up. Most of what I see is not a classifier: it is "
        "a t-test, an analysis of variance, a regression, a survival curve, the statistics of an ordinary thesis. "
        "I reproduce those the same way.",
        "I look for the classic faults: the wrong test for the data, a hidden grouping, samples that are not "
        "independent, a result that seems too good, and, for a prediction model, test data leaking into training.",
        "In a write-up, I check that each cited paper is real and says what you claim. For a prediction model, "
        "I go through the reporting checklist a journal will use, TRIPOD plus AI, and name each item you missed."],
    refuses=[
        Quote("Covers how a result was produced, and whether it holds.", "how a result"),
        Quote("Marks each finding as checked, or only suspected.", "suspected"),
        Quote("Refers patents and data rules to the lawyer itself, mid-audit.", "lawyer"),
        Quote("Audits what was built; it does not build.", "do not build"),
    ],
    refuses_narration=[
        "My scope is how a result was produced and whether it holds up. Each finding is marked as checked, "
        "when I confirmed it by running something, or only suspected.",
        "When a result touches a patent or governed data, I refer it to the lawyer myself, mid-audit, and fold "
        "their verdict into mine. I audit what was built; I do not build it."],
    examples=[
        Exchange("1", ["A real run, on the example paper that ships with Murmurent: do colonies grown in serum "
                       "come out larger, and does the difference hold?",
                       "The verdict is Questions. The number reproduces exactly, but the serum and control "
                       "samples come from different countries, the test is one-sided and the write-up does not say "
                       "so, and the Methods misdescribe the code. Each finding says whether I checked it or only suspect it."],
                 [("read the paper", True), ("re-run the code", True), ("check the grouping", True), ("refer to the lawyer", False)]),
    ],
    prompt="ask the adversary to audit the statistics in chapter 3 of my thesis",
    give="The analysis folder, or the write-up with its code and data.",
    verdicts="Pass, Questions or Reject, then each finding marked checked or suspected.",
    howto_narration=[
        "To use me, type to Claude Code and name me: ask the adversary to audit the statistics in a chapter, "
        "or a result before you submit it. Give me the folder with the code and the data.",
        "The first line is my verdict: Pass, Questions or Reject. Then each finding, marked checked or "
        "suspected, with what would settle it."],
    directions=[
        ("ask the adversary to audit the statistics in chapter 3 of my thesis, the t-tests and the ANOVA",
         "Each test re-run from the data; the wrong test, a missed assumption or a hidden grouping named."),
        ("ask the adversary to check my classifier for leakage and against TRIPOD plus AI before I submit",
         "The folds inspected, the model re-run, and each checklist item you missed."),
        ("ask the adversary to check the Results section of my draft against its own numbers and citations",
         "Each number traced to the analysis that produced it, each citation checked."),
    ],
    directions_narration=[
        "Say what to audit: the tests in a thesis chapter, a classifier before submission, or a Results "
        "section against its own numbers.",
        "Say what you want settled, and I say for each finding whether I checked it or only suspect it."],
    docs=["docs/reporting_guidelines.md"],
)
