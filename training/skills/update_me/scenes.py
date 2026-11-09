"""/murmurent-update-me: the status update and its dry run (issue #290)."""
from lib.draw import SKY, TEAL
from lib.movie import Movie, Part, Quote

T_FACTS = """
$ python3 skills/murmurent-update-me/gather_facts.py
UPDATE-ME FACTS for murmurent (read-only; paths, times and owners only)
Clock: Sat 2026-11-07 12:20:28 EST (from `date`)
== Running now: this project's analyses and apps on this server ==
  Only this server is checked; a job on another machine does not appear.
== Agents ==
  Claude Code sessions open on this account: 0
== Git ==
  13 commits today by the PI, in step with GitHub
"""

MOVIE = Movie(
    key="update_me",
    title="A status update with /murmurent-update-me",
    tagline="A plain-English status note for the project's channel, from the facts",
    glyph="📣",
    colour=SKY,
    summary="The status-update skill: a plain-English note for the project's channel, built from facts the computer reads fresh each time, what stays out of the channel, and the dry run that shows the note without posting it.",
    parts=[
        Part("title", ["This skill writes a plain-English status note for the project's channel: what is running, "
                       "what finished, what is blocked and on whom. The facts come from the computer itself, not "
                       "from anyone's memory."]),
        Part("cards", chapter="Where the facts come from", heading="Facts first, then words",
             source="skills/murmurent-update-me/SKILL.md", colour=TEAL,
             quotes=[Quote("The facts are read from the computer, fresh each time.", "fresh"),
                     Quote("Where the project's status document and the facts disagree, the facts win.", "disagree"),
                     Quote("With dry run, it shows the note and posts nothing.", "dry run")],
             narration=["The skill reads the facts fresh each time, and that is what makes it special. Status reports "
                        "once went wrong three ways in one day: a job was missed, a stopped build was called running, "
                        "and times were guessed.",
                        "Where the project's status document and the facts disagree, the facts win and the update "
                        "says so. Add the words dry run, and it shows the note "
                        "without posting it."]),
        Part("terminal", chapter="The facts", heading="What the skill reads", transcript=T_FACTS, title="What the skill runs for you",
             colour=TEAL,
             notes=[("Running jobs, recent work, new results, progress on GitHub.", "jobs"),
                    ("It only reads. A check it cannot run says so.", "cannot run")],
             narration=["Behind the scenes it runs the skill's fact script, which only reads; the member typed only the "
                        "skill's name. It looks at running jobs on every lab account, the log of the agents, new "
                        "results and today's saved work.",
                        "A check it cannot run says so."]),
        Part("chat", chapter="A real dry run", key="1", agent="murmurent-update-me", agent_title="/murmurent-update-me", colour=SKY, who="Member",
             chips=[("gather facts", True), ("write the summary", True), ("check the rules", True), ("post", False)],
             narration=["Here is a real dry run. Here the job check could not run on a laptop, so the honest note says "
                        "it could not tell what was running. Thirteen pieces of work were saved today, nothing is "
                        "blocked, and the next step says whose it is.",
                        "Before posting, the skill checks the note against the lab's rules. Here it stops, because the "
                        "member asked for a dry run."]),
        Part("cards", chapter="What stays out", heading="What stays out of the channel", source="skills/murmurent-update-me/SKILL.md",
             colour=SKY, mark="cross",
             quotes=[Quote("No passwords or access keys.", "passwords"),
                     Quote("No results, only what ran and when.", "results"),
                     Quote("Nothing from a folder kept for publication.", "publication"),
                     Quote("No count under six of people or events.", "six")],
             narration=["A message in a channel is easy to copy, so some things stay out. No passwords. No results, "
                        "only what ran and when. Nothing from a publication folder. And no count under six of people "
                        "or events, which could identify someone. A note that breaks a rule is fixed before anything "
                        "is posted."]),
        Part("howto", heading="How to use it",
             prompt="/murmurent-update-me dry-run",
             cards=[("Type the skill", "In the project's folder. Add dry-run to read the note first."),
                    ("Tailor it", "Each project chooses its channel, results folder and people's names."),
                    ("Trust the facts", "If it says a job stopped, the computer showed it stopped.")],
             docs=["skills/murmurent-update-me/SKILL.md"],
             narration=["To use it, type the skill's name in Claude Code from the project's folder, with dry run the "
                        "first time. Each project can tailor it: which channel, which results folder, and the names "
                        "to use for each person. When the update says a job stopped, the computer showed it stop."]),
    ],
)
