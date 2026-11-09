"""The lab oracle movie: narration, cards on what the lab oracle does, and the real exchanges in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import LAV

SPEC = AgentSpec(
    agent="lab_oracle",
    title="The lab oracle",
    tagline="The lab's shared memory",
    colour=LAV,
    icon="folder",
    intro=["This is the lab oracle, the lab's shared memory. It answers one question: what has the "
           "lab agreed on, and who said so?"],
    does=[
        Quote("Holds the findings the whole lab has agreed on", "agreed"),
        Quote("Names who published each finding, and when", "who published"),
        Quote("Findings arrive when a member publishes them from their own oracle", "arrive"),
        Quote("Everybody reads it; new entries arrive only by publishing", "everybody reads"),
    ],
    does_narration=[
        "It holds the findings the whole lab has agreed on, and for each one it names who published "
        "it and when.",
        "Findings arrive when a member publishes them from their own oracle. "
        "Everybody reads it; new entries arrive only by publishing."],
    refuses=[
        Quote("Your oracle holds your notes; the lab oracle holds the lab's", "your own oracle"),
        Quote("Says which memory each answer comes from", "which memory"),
        Quote("If the lab has no entry, it says so", "no entry"),
    ],
    refuses_narration=[
        "Your own oracle holds your working notes; the lab oracle holds what the lab has agreed. "
        "It always says which memory an answer comes from.",
        "The bookworm finds papers and the blacksmith runs analyses. If the lab has no entry on a "
        "topic, it says so, and suggests you check your own oracle."],
    examples=[
        Exchange("1", ["A real run, on a demo lab memory. The member asks what the lab agreed on for "
                       "a quality threshold in single-cell experiments, and who published it.",
                       "It finds one entry: the threshold, who published it, the lab meeting that "
                       "decided it, and the value used before."],
                 [("read its index", True), ("read the entry", True)]),
        Exchange("2", ["Then the member asks it to change the number. It answers that changes arrive by "
                       "publishing, shows what the entry says now, and leaves it as it is: a member "
                       "writes the change in their own oracle and publishes it, once the lab has decided."],
                 [("read the entry", True), ("edit", False)]),
    ],
    prompt="ask the lab oracle what the lab has agreed on for the reference genome",
    give="The topic you want the lab's view on.",
    verdicts="Found, Not found or Unsure, naming who published the entry.",
    howto_narration=[
        "To use it, just ask Claude Code: ask the lab oracle what the lab has agreed on about a topic. "
        "To add something, ask your own oracle to prepare it, and publish it to the lab.",
        "The first line of the reply is the verdict: Found, Not found or Unsure, with the name of who "
        "published the entry."],
    docs=["docs/oracle-workflow.md"],
)
