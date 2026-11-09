"""The millwright movie: narration, cards checked against agents/millwright.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import TEAL

SPEC = AgentSpec(
    agent="millwright",
    title="The millwright",
    tagline="Sets up new members and new projects for your lab",
    colour=TEAL,
    icon="folder",
    intro=["This is the millwright. The PI uses it to set up the lab: a working computer for a new member, "
           "and the folders, channel and access for a new project."],
    does=[
        Quote("Gives a new member a step-by-step setup checklist", "checklist"),
        Quote("Sets up a project's code, private channel and data folders", "new project"),
        Quote("Checks that each member's setup still works", "still works"),
        Quote("Asks the PI before changing anything the lab shares", "asks the PI"),
    ],
    does_narration=[
        "For a new member, it gives them read access to the lab's records and writes a checklist they follow "
        "on their own computer: reach the lab server, install Claude Code, and create their personal notes. "
        "The member gets it in Slack and replies when it is done.",
        "For a new project, it sets up the project's code on GitHub, a private Slack channel for its members, "
        "and its data folders on the lab server.",
        "It also checks that each member's setup still works. Before it changes anything the lab shares, "
        "it shows the full plan and asks the PI to confirm."],
    refuses=[
        Quote("Covers one lab; the centre millwright handles cross-lab projects", "centre millwright"),
        Quote("Each member makes their own secret key on their own computer", "secret key"),
        Quote("Reports untidy folders to the PI, who decides", "untidy"),
    ],
    refuses_narration=[
        "It covers one lab. When a project's members come from several labs, the centre millwright takes over.",
        "Each member makes their own secret key on their own computer, and only the public half leaves it. "
        "Folders that break the lab's layout are untidy, and it reports them to the PI, who decides. "
        "Data is never deleted; old records are archived."],
    examples=[
        Exchange("1", ["A real run that only reads. The PI asks it to check this machine's setup.",
                       "Murmurent runs, but the shared agents are not yet linked, and the safety checks use a "
                       "different copy of Python. Each problem comes with its fix, and nothing was changed."],
                 [("run the health check", True), ("check the project folder", True), ("fix anything", False)],
                 who="PI"),
    ],
    prompt="ask the millwright to set up a new project called DCIS imaging for this lab",
    give="For a project, its name and who is in it. For a new member, their name in the lab's records. For a check, nothing.",
    verdicts="Provisioned / Skipped / Failed, after a plan you confirmed.",
    howto_narration=[
        "To use it, the PI types to Claude Code and names it: ask the millwright to set up a project, add a "
        "new member, or check everyone's setup. It shows the plan and waits for a yes.",
        "The first line is the verdict: Provisioned, Skipped or Failed. A lab tailors it through its own "
        "records: the lab's machines and folders fill in each new member's checklist."],
    docs=["docs/setup.md"],
)
