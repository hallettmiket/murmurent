"""The centre millwright movie: narration, cards checked against agents/centre_millwright.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import TEAL

SPEC = AgentSpec(
    agent="centre_millwright",
    title="The centre millwright",
    tagline="Keeps every project's access consistent across the centre",
    colour=TEAL,
    icon="cloud",
    intro=["I am the centre millwright. I work for the centre's administrator, the registrar, and keep "
           "each project's access the same everywhere: its Slack channel, its code and its data folders."],
    does=[
        Quote("Compares each project's member list with who actually has access", "compare"),
        Quote("Reports drift: every difference, with what it would change", "drift"),
        Quote("Sets up projects whose members come from several labs", "several labs"),
        Quote("One project at a time, after the registrar approves", "approves"),
    ],
    does_narration=[
        "Each project has a list of its members. I compare that list with who is actually "
        "in the project's channel, on its code, and on its folders on the shared servers. Any difference is "
        "drift, and I report each one with what I would change.",
        "I also set up projects whose members come from several labs, inviting the others as guests. "
        "I work one project at a time, and change nothing until the registrar approves."],
    refuses=[
        Quote("Each lab's millwright sets up that lab's members", "lab's own millwright"),
        Quote("Reads each lab's records; the lab's PI keeps them", "read"),
        Quote("Archives an unused channel, so the registrar can restore it", "archive"),
    ],
    refuses_narration=[
        "Each lab's own millwright sets up that lab's members; I take over once a project "
        "crosses labs. I read each lab's records, which the lab's PI keeps.",
        "When a channel is no longer needed, I archive it, so the registrar can bring it back."],
    examples=[
        Exchange("1", ["A real run that changes nothing. The registrar asks me to check the centre's records on "
                       "this machine.",
                       "The comparison of members with their access could not run here, and I say so. I then "
                       "list eight local items, each with what I would do."],
                 [("read the centre's record", False), ("check local records", True), ("change anything", False)],
                 who="Registrar"),
    ],
    prompt="ask the centre millwright whether the DCIS imaging project's access matches its members in both labs",
    give="The project, or nothing to check every project. It shows each difference before changing anything.",
    verdicts="Reconciled / Drift / BLOCKED, with each difference and the approval it needs.",
    howto_narration=[
        "To use me, ask the centre millwright, on the registrar's computer, to check one project or every "
        "project. I show each difference before anything changes.",
        "The first line is the verdict: Reconciled, Drift, or Blocked while I wait for approval. A centre "
        "sets its own name, Slack workspace and GitHub organisation, and every project's names follow from them."],
    docs=["docs/reconcile.md"],
)
