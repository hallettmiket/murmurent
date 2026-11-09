"""The millwright movie: narration in the millwright's own voice, cards checked against agents/millwright.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import TEAL

SPEC = AgentSpec(
    agent="millwright",
    title="The millwright",
    tagline="Gets a new member's computer connected to the lab, and sets up each new project",
    colour=TEAL,
    icon="folder",
    intro=["I am the millwright. I do the technical setup so that nobody else has to: I connect a new "
           "member's computer to the lab, and I set up the folders, the channel and the access for each new project."],
    does=[
        Quote("Connects a new member: the lab server, Claude Code, their own notes", "connect"),
        Quote("Sets up a project's code, private channel and data folders", "project starts"),
        Quote("Keeps the lab's rules for where files go", "rules"),
        Quote("Asks the PI before changing anything the lab shares", "ask the PI"),
    ],
    does_narration=[
        "When someone joins, I connect them: a checklist they follow on their own computer to reach the "
        "lab server, install Claude Code and create their personal notes. They get it in Slack and reply when it is done.",
        "When a project starts, I set up its code on GitHub, a private Slack channel for its members, and "
        "its data folders on the lab server, laid out the way the lab's rules say files are stored.",
        "I keep to those rules, and I check that each member's setup still works. Before I change anything the "
        "lab shares, I show the full plan and I ask the PI to confirm."],
    refuses=[
        Quote("Covers one lab; the centre millwright handles cross-lab projects", "centre millwright"),
        Quote("Each member makes their own secret key on their own computer", "secret key"),
        Quote("Reports untidy folders to the PI, who decides", "untidy"),
    ],
    refuses_narration=[
        "I cover one lab. When a project's members come from several labs, the centre millwright takes over.",
        "Security and privacy are part of the setup. Each member makes their own secret key on their own "
        "computer, and only the public half leaves it. Folders that break the lab's layout are untidy, and I "
        "report them to the PI, who decides. Data is never deleted; old records are archived."],
    examples=[
        Exchange("1", ["A real run that only reads. The PI asks me to check this machine's setup.",
                       "Murmurent runs, but the shared agents are not yet linked, and the safety checks use a "
                       "different copy of Python. Each problem comes with its fix, and nothing was changed."],
                 [("run the health check", True), ("check the project folder", True), ("fix anything", False)],
                 who="PI"),
    ],
    prompt="ask the millwright to set up a new project called Candida albicans imaging for this lab",
    give="For a project, its name and who is in it. For a new member, their name in the lab's records. For a check, nothing.",
    verdicts="Provisioned / Skipped / Failed, after a plan you confirmed.",
    howto_narration=[
        "To use me, the PI types to Claude Code and names me: ask the millwright to set up a project, add a "
        "new member, or check everyone's setup. I show the plan and wait for a yes.",
        "The first line is my verdict: Provisioned, Skipped or Failed. A lab tailors me through its own "
        "records: the lab's machines and folders fill in each new member's checklist."],
    docs=["docs/setup.md"],
)
