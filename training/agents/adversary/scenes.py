"""The adversary movie: narration, plain-statement cards checked against agents/adversary.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import RED

SPEC = AgentSpec(
    agent="adversary",
    title="The adversary",
    tagline="The sceptical reviewer who tries to break your result before a referee does",
    colour=RED,
    icon="scale",
    intro=["This is the adversary, the sceptical reviewer. It tries to break your result before a referee "
           "does: it re-runs your analysis and checks what your write-up claims."],
    does=[
        Quote("Re-runs your analysis to see whether the numbers hold.", "re-runs"),
        Quote("Looks for test data leaking into training.", "leaking"),
        Quote("Checks that each cited paper is real and says what you claim.", "cited paper"),
        Quote("For a written-up prediction model, names the checklist items you missed.", "checklist"),
    ],
    does_narration=[
        "It re-runs your code rather than trusting the write-up, and looks for the classic faults: test data "
        "leaking into training, a result that seems too good, a step nobody can reproduce.",
        "In a write-up, it checks that each cited paper is real and says what you claim. For a written-up "
        "prediction model, it goes through the reporting checklist a journal will use and names each item you missed."],
    refuses=[
        Quote("Covers how a result was produced, and whether it holds.", "how a result"),
        Quote("Marks each finding as checked, or only suspected.", "suspected"),
        Quote("Asks the lawyer about patents and data rules itself.", "lawyer"),
        Quote("The blacksmith builds, the artist draws, the bookworm finds reading.", "blacksmith"),
    ],
    refuses_narration=[
        "Its scope is how a result was produced and whether it holds up. Each finding is marked as checked, "
        "by re-running or reading, or as only suspected, and an unclear result is reported as unclear.",
        "When the work names a compound to make or data about to move, it asks the lawyer itself and "
        "includes the answer. The blacksmith builds the analysis, the artist draws the figures, and the "
        "bookworm finds the reading."],
    examples=[
        Exchange("1", ["A real run, on the made-up example that ships with Murmurent. A member asks whether "
                       "colonies grown in serum really are larger than controls.",
                       "The answer is Questions. The number reproduces exactly, but the serum and control "
                       "samples come from different countries, and the Methods describe a step the code never "
                       "takes. The last line says no legal question arises."],
                 [("re-run the analysis", True), ("split by country", True), ("read the write-up", True),
                  ("ask the lawyer", False)]),
    ],
    prompt="ask the adversary to check my serum colony result before I send it to the PI",
    give="The code and the data, or the write-up with them.",
    verdicts="Pass, Questions or Reject first; the report closes with Sound, Needs revision or Major concerns.",
    howto_narration=[
        "To use it, ask Claude Code for the adversary and say what to check. Give it the code and the data, "
        "not a summary, because it runs them. The first line is the verdict: Pass, Questions or Reject.",
        "Its checklists cover prediction models and single-marker studies; for other study designs it names "
        "the right checklist but does not check it."],
    directions=[
        ("ask the adversary whether my classifier leaks between training and test, re-running the split rather than reading it",
         "Each finding marked as checked or only suspected, and Pass, Questions or Reject."),
        ("ask the adversary to check my risk-score manuscript against TRIPOD+AI, the reporting checklist for prediction models",
         "The checklist items missing and those it could not check, each with where it looked, and a count of those reported."),
        ("ask the adversary to check that every paper cited in my grant draft is real and says what I claim",
         "Every citation that is wrong, retracted or could not be checked, a count of those verified, and the numbers behind the main claims traced."),
    ],
    directions_narration=[
        "Say what to check and what worries you: leakage in a classifier, a manuscript against the checklist "
        "a journal will use, or whether the papers you cite are real and say what you claim."],
    docs=["docs/reporting_guidelines.md"],
)
