"""The judge movie: narration, plain cards checked against agents/judge.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="judge",
    title="The judge",
    tagline="Puts several answers to one question side by side, with who found what",
    colour=SAND,
    icon="scale",
    intro=["I am the judge. When several members or labs each answer the same question, I put "
           "their answers side by side and show who found what."],
    does=[
        Quote("Lines up every answer on the same items, such as compounds.", "line up"),
        Quote("Shows every contribution, even one that covers only some items.", "every contribution"),
        Quote("Names, for every number, who produced it.", "who produced"),
        Quote("Shows plainly where the answers disagree.", "disagree"),
    ],
    does_narration=[
        "I line up every answer on the same items, for example the same compounds, and rank them by the rules "
        "of the person who asked. Every contribution is shown, even one that covers only some of the items.",
        "Every number names who produced it, how it was measured, and how uncertain it is. Where the answers "
        "disagree, I say so. The person who asks sets the ranking rules; a lab can also adapt me to its own needs."],
    refuses=[
        Quote("It combines and presents; the person who asked decides.", "decides"),
        Quote("Hands its table to the artist for a figure.", "artist"),
        Quote("One combined score only when the measures share a scale.", "scale"),
    ],
    refuses_narration=[
        "My scope is combining and presenting. The answers arrive already produced, and the person who asked "
        "decides what happens next. I hand my table to the artist, who turns it into a figure.",
        "I give one combined score only when the measures share a scale. Otherwise the answer is Split, shown "
        "side by side. I never invent a consensus."],
    examples=[
        Exchange("1", ["A real run, on invented data: two labs and five compounds. One lab gives a computed "
                       "docking score, the other a measured binding strength.",
                       "My answer is Split: the two measures are on different scales, so there is no combined "
                       "score. Under the asker's rule, two compounds rank first. I flag the compound "
                       "that docks best but binds worst, and the untested one stays in the table."],
                 [("read the question and rules", True), ("line up by compound", True), ("one combined score", False)],
                 who="Member"),
    ],
    prompt="ask the judge to present the two labs' results for our compound screen",
    give="Each contribution's results table, the question, and the rules for ranking.",
    verdicts="Presented, Split or Insufficient, then the table with every number's source.",
    howto_narration=[
        "To use me, once the contributions are in, type to Claude Code: ask the judge to present the results. "
        "I need each contribution's table, the question, and the ranking rules.",
        "The first line is the answer: Presented, Split, or Insufficient when a result is missing. Then the "
        "table, every number with its source, ready for the artist."],
    docs=["docs/assembling_choreographies.md"],
)
