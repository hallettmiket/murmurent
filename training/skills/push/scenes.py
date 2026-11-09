"""/murmurent-push and /murmurent-project-push: what the pre-flight refuses and where the note goes (issue #290)."""
from lib.draw import AMBER, RED, TEAL
from lib.movie import Movie, Part, Quote

T_NOTE = """
$ murmurent project note --dry-run ""
no Slack channel is recorded for the project 'push_demo' (there is no project record of that name)
$ cd ~/repos/dcis_imaging
$ murmurent project note --dry-run ""
C0A1B2C3D4E: the channel of project 'dcis_imaging'
"""

MOVIE = Movie(
    key="push",
    title="Backing up with /murmurent-push",
    tagline="Back up your work safely, and tell the project's channel",
    glyph="📤",
    colour=TEAL,
    summary="The two backup skills: the checks that keep an access key or a large data file from leaving, backing up a whole project at once, and the note to the project's channel.",
    parts=[
        Part("title", ["This skill backs up your work. You type its name, murmurent push, in Claude Code. It saves "
                       "your changes to GitHub, the lab's online copy, and tells the project's channel what changed."]),
        Part("cards", chapter="The checks", heading="The checks before anything leaves", source="skills/murmurent-push/SKILL.md",
             colour=RED, mark="cross",
             quotes=[Quote("A file named like a password or key stays behind.", "named like"),
                     Quote("An access key or token written inside a file stops the backup.", "inside"),
                     Quote("A data file over one megabyte stops the backup.", "megabyte"),
                     Quote("Nothing from the lab's original data or results folders goes to GitHub.", "results")],
             narration=["What makes it special are the checks it runs before anything leaves your computer. A file "
                        "named like a password or a key stays behind. An access key or token written inside a file "
                        "stops the backup, and the skill shows only a few letters from each end.",
                        "A data file over one megabyte stops the backup, and the skill names where the file belongs. "
                        "Nothing from the lab's data folders on the server, original data or results, is ever saved "
                        "to GitHub."]),
        Part("chat", chapter="A real run", key="1", agent="murmurent-push", agent_title="/murmurent-push", colour=RED, who="Member",
             chips=[("file names", True), ("keys in files", True), ("large files", True), ("save to GitHub", False)],
             narration=["Here are the real checks the skill runs, on a practice folder made for this movie. The member typed only the "
                        "skill's name. It found two access keys written into a settings file and showed them cut short.",
                        "It left a credentials file behind, named a three-megabyte data file and where it should go, "
                        "and saved nothing to GitHub."]),
        Part("terminal", chapter="Where the note goes", heading="Where the note goes", transcript=T_NOTE,
             title="What the skill runs for you", colour=TEAL,
             notes=[("The note goes to the project's own channel.", "own channel"),
                     ("With no channel on record, nothing is posted, and it says so.", "says so")],
             narration=["After a backup, the skill decides where the note goes. These commands show where a note "
                        "would go; after a real backup the skill posts it there.",
                        "The note goes to the project's own channel, else the lab's. With no channel on record, "
                        "nothing is posted, and it says so."]),
        Part("cards", chapter="The whole project", heading="Backing up a whole project",
             source="skills/murmurent-project-push/SKILL.md", colour=TEAL,
             quotes=[Quote("Every part of the project on this computer is backed up at once.", "every part"),
                     Quote("A part that fails a check waits; the rest are saved.", "waits"),
                     Quote("One summary goes to the project's channel.", "summary")],
             narration=["A second skill, murmurent project push, backs up every part of a project on this computer at once: the code, "
                        "the manuscript and the rest. Each part gets the same checks.",
                        "A part that fails waits for you while the others are saved, and one summary goes to the "
                        "project's channel."]),
        Part("howto", heading="How to use them",
             prompt="/murmurent-push",
             cards=[("Type the skill", "/murmurent-push for this folder; /murmurent-project-push for the whole project."),
                    ("Read what stopped it", "It names the file and the reason. Remove the cause and run it again."),
                    ("Find the note", "In the project's channel, with a line on what changed.")],
             docs=["skills/murmurent-push/SKILL.md", "docs/slack_routing.md"],
             narration=["To use it, type the skill's name in Claude Code. If something stops it, it names the file "
                        "and the reason: remove the cause and run it again. The project-wide skill can also keep a "
                        "second copy in a partner lab's GitHub account."]),
    ],
)
