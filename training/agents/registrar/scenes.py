"""The registrar movie: narration, cards checked against agents/registrar.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SKY

SPEC = AgentSpec(
    agent="registrar",
    title="The registrar",
    tagline="The centre's one list of labs, cores and collaborations",
    colour=SKY,
    icon="stamp",
    intro=["I am the registrar. I work for the centre's administrator, such as a research director, "
           "and keep one list of every lab, core facility and collaboration, and who leads each."],
    does=[
        Quote("Keeps one list of the centre's labs, cores and collaborations", "one list"),
        Quote("Each PI leads at most one lab or core", "at most one"),
        Quote("Shows whose required training has expired, centre-wide", "expired"),
        Quote("Signs each PI's identity card", "identity card"),
    ],
    does_narration=[
        "I keep one list of the centre's labs, cores and collaborations, each with its lead and its status, "
        "and I hold to one rule: each PI leads at most one lab or core.",
        "I show the administrator which members, in any lab, have expired or missing training, such as "
        "research ethics. And I sign each PI's identity card, the signed record that says who they are."],
    refuses=[
        Quote("Each lab keeps its own notebooks, code and member list", "own notebooks"),
        Quote("Archiving a lab changes its status; its files stay", "archiving"),
        Quote("The centre millwright sets up what the registrar approves", "approve"),
    ],
    refuses_narration=[
        "I see each lab from the outside. Each lab keeps its own notebooks, code, memory and "
        "member list, and edits them itself. Archiving a lab changes its status in the list, and its files stay.",
        "When a collaboration needs channels and folders, I approve them and the centre millwright "
        "sets them up."],
    examples=[
        Exchange("1", ["A real run that only reads. The administrator asks me for the centre-wide view.",
                       "I find one lab and its PI, no cores or collaborations yet, and one gap named plainly: "
                       "nobody is recorded as registrar. I changed nothing."],
                 [("read the registry", True), ("find each lab's records", True), ("read inside the lab", False)],
                 who="Director"),
    ],
    prompt="ask the registrar which labs and cores are registered and whether any entry is incomplete",
    give="For the view, nothing. For a new lab or core, its name and its PI.",
    verdicts="Recorded / Conflict / Skipped, then the list or what stopped it.",
    howto_narration=[
        "To use me, the administrator types to Claude Code and names me: ask the registrar which labs and cores "
        "are registered, or whether an entry is incomplete. I refuse a PI who already leads another group.",
        "When I record, find a conflict or skip, the first line says so: Recorded, Conflict or Skipped. A centre chooses its own registrar and "
        "records its own labs, cores and collaborations."],
    docs=["docs/identity.md"],
)
