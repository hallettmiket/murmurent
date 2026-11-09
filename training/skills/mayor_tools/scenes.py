"""The mayor's and PI's tools: /murmurent-admin, /murmurent-onboard, /murmurent-reset (issue #290)."""
from lib.draw import LAV, RED, TEAL
from lib.movie import Movie, Part, Quote

T_ONBOARD = """
$ murmurent centre-status
(no centre initialised; run `murmurent centre-init`)
$ murmurent join-request list
(no join requests)
$ murmurent join-request decrypt request.age
$ murmurent join-request show <id>
$ murmurent join-request approve <id> --actor @mayor
"""

MOVIE = Movie(
    key="mayor_tools",
    title="The mayor's and PI's tools",
    tagline="For the centre's administrator and lab heads: three tools, typed by name",
    glyph="🏛️",
    colour=LAV,
    summary="The three administrative skills: priming context before admin work, processing an encrypted join request with an explicit decision, and resetting a machine after a backup and a dry run.",
    parts=[
        Part("title", ["Three tools for the people who run a centre or a lab: the centre's administrator, called "
                       "the mayor, and each lab's head. Each is typed by its slash name in Claude Code."]),
        Part("cards", chapter="/murmurent-admin", heading="/murmurent-admin: read the design first",
             source="skills/murmurent-admin/SKILL.md", colour=TEAL,
             quotes=[Quote("Before any change to the centre, it rereads the design.", "Before"),
                     Quote("The session then works from the documents and the code.", "documents"),
                     Quote("The mayor is a person who sets up the centre.", "mayor is a person")],
             narration=["Before anyone changes how the centre runs, how people join or how labs are set up, they "
                        "type slash murmurent admin. Claude Code first reads the centre's design documents and "
                        "code, so it works from the real design.",
                        "It also settles one question: the mayor is a person who sets up the centre once, and the "
                        "registrar is the agent that keeps the centre's list of labs and projects."]),
        Part("terminal", chapter="/murmurent-onboard", heading="/murmurent-onboard: a join request, end to end",
             transcript=T_ONBOARD, title="Terminal: what the skill would run on the mayor's machine", colour=LAV,
             notes=[("On this laptop there is no centre yet, so it stops.", "stops"),
                    ("It opens the request and shows who is asking.", "shows who"),
                    ("Approving a lab creates its Slack channel, GitHub space and folder access.", "approving")],
             narration=["Someone who wants to join emails the mayor a locked request, and the mayor types slash "
                        "murmurent onboard. It first checks that a centre exists; on this laptop there is none, so "
                        "it stops there, and the rest is what it runs on the mayor's machine.",
                        "It unlocks the request, shows who is asking and why, and asks: approve or decline? "
                        "Approving a new lab creates its Slack channel, a shared code space on GitHub, and access "
                        "to its folders, so it waits for a clear yes. A person joining an existing lab is approved by that lab's head."]),
        Part("cards", chapter="How onboard handles a request", heading="How it handles a request", source="skills/murmurent-onboard/SKILL.md",
             colour=RED, mark="tick",
             quotes=[Quote("It approves only after the mayor's clear yes.", "only after"),
                     Quote("It reads every detail from the request itself.", "request itself"),
                     Quote("It keeps the requester's contact details private.", "private")],
             narration=["It approves only after the mayor's clear yes. It reads every detail from the request "
                        "itself, and it keeps the requester's contact details private, out of Slack and GitHub."]),
        Part("chat", chapter="/murmurent-reset", key="1", agent="murmurent-reset", agent_title="/murmurent-reset", colour=RED, who="PI",
             chips=[("pick the level", True), ("a dry run", True), ("backup", True), ("run for real", False)],
             narration=["Slash murmurent reset returns a machine to a fresh start, for example before setting up a "
                        "centre again. It works in levels. Here is a real preview on this laptop: every step it "
                        "would take, the backup it writes first, and what it keeps.",
                        "Your access keys and other projects' settings stay unless you name them. It runs for real "
                        "only after you read the preview and say yes."]),
        Part("howto", heading="How to use them",
             prompt="/murmurent-reset",
             cards=[("Admin first", "Type /murmurent-admin before changing how the centre runs."),
                    ("Onboard with a yes", "/murmurent-onboard when a join request arrives; you approve or decline."),
                    ("Reset after a preview", "/murmurent-reset shows a preview, asks, then backs up before it changes anything.")],
             docs=["skills/murmurent-admin/SKILL.md", "skills/murmurent-onboard/SKILL.md", "skills/murmurent-reset/SKILL.md"],
             narration=["To use them: admin before changing how the centre runs. Onboard when a join request "
                        "arrives, and give the answer yourself. Reset after reading the preview; the backup is "
                        "taken for you."]),
    ],
)
