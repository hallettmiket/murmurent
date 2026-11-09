"""The judge movie: narration, plain cards checked against agents/judge.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="judge",
    title="The judge",
    tagline="Puts several answers to one question side by side, with who found what",
    colour=SAND,
    icon="scale",
    intro=["This is the judge. When several members or labs each answer the same question, the judge puts "
           "their answers side by side and shows who found what."],
    does=[
        Quote("Lines up every answer on the same items, such as compounds.", "lines up"),
        Quote("Shows every contribution, even one that covers only some items.", "every contribution"),
        Quote("Names, for every number, who produced it.", "who produced"),
        Quote("Shows plainly where the answers disagree.", "disagree"),
    ],
    does_narration=[
        "It lines up every answer on the same items, for example the same compounds, and ranks them by the rules "
        "of the person who asked. Every contribution is shown, even one that covers only some of the items.",
        "Every number names who produced it, how it was measured, and how uncertain it is. Where the answers "
        "disagree, it says so. The person who asks sets the ranking rules; a lab can also adapt the judge itself."],
    refuses=[
        Quote("It combines and presents; the person who asked decides.", "decides"),
        Quote("The artist turns its table into a figure.", "artist"),
        Quote("The adversary checks how it combined the answers.", "adversary"),
        Quote("One combined score only when the measures share a scale.", "scale"),
    ],
    refuses_narration=[
        "Its scope is combining and presenting. The answers arrive already produced, and the person who asked "
        "decides what happens next. The artist turns the table into a figure, and the adversary checks how it "
        "combined them.",
        "It gives one combined score only when the measures share a scale. Otherwise the answer is Split, shown "
        "side by side. It never invents a consensus."],
    examples=[
        Exchange("1", ["A real run, on invented data: two labs and five compounds. One lab gives a computed "
                       "docking score, the other a measured binding strength.",
                       "The answer is Split: the two measures are on different scales, so there is no combined "
                       "score. Under the asker's rule, two compounds rank first. The compound "
                       "that docks best but binds worst is flagged, and the untested one stays in the table."],
                 [("read the question and rules", True), ("line up by compound", True), ("one combined score", False)],
                 who="Member"),
    ],
    prompt="ask the judge to present the two labs' results for our compound screen",
    give="Each contribution's results table, the question, and the rules for ranking.",
    verdicts="Presented, Split or Insufficient, then the table with every number's source.",
    howto_narration=[
        "To use it, once the contributions are in, type to Claude Code: ask the judge to present the results. "
        "It needs each contribution's table, the question, and the ranking rules.",
        "The first line is the answer: Presented, Split, or Insufficient when a result is missing. Then the "
        "table, every number with its source, ready for the artist."],
    docs=["docs/assembling_choreographies.md"],
)
