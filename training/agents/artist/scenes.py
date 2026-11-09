"""The artist movie: narration, quotes from agents/artist.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SKY

SPEC = AgentSpec(
    agent="artist",
    title="The artist",
    tagline="Figures, reports and slides made from your real results",
    colour=SKY,
    icon="chart",
    intro=["I am the artist. I turn your results into figures, reports and slides that make the "
           "science clear."],
    does=[
        Quote("Draws publication figures from your real results", "publication"),
        Quote("Model-accuracy curves, heatmaps, volcano plots and more", "heatmaps"),
        Quote("Builds slide decks and a running project report", "slide"),
        Quote("Draws each figure from your real data, at print resolution", "print resolution"),
    ],
    does_narration=[
        "I draw publication figures, from model-accuracy curves to heatmaps and volcano plots, each one labelled, with "
        "proper axes and legends. I build slide decks, and keep a project report of the figures so far.",
        "What makes me different: I draw each figure from your real data and save it at print resolution."],
    refuses=[
        Quote("Covers figures, reports and slides", "cover"),
        Quote("Draws the numbers as they arrive; it computes none itself", "as they arrive"),
        Quote("It never invents a data point", "invent"),
    ],
    refuses_narration=[
        "I cover figures, reports and slides. I draw the numbers as they arrive, from your results or "
        "an analysis already run; I compute none myself.",
        "I never invent a data point to fill a plot; when an input is missing, I say so."],
    examples=[
        Exchange("1", ["A real run, on simulated data. The member asks me for one figure: colony size by growth "
                       "medium, every point shown, the means marked.",
                       "My answer is Rendered. The image itself says the data are simulated, the caption "
                       "says what to notice, and I state that I ran no test."],
                 [("read the data", True), ("draw the figure", True), ("write the caption", True)],
                 figure="colony_by_medium.png"),
    ],
    prompt="ask the artist to make a figure for the paper from the classifier results the blacksmith produced",
    give="The results, what the figure is for, and which comparison matters.",
    verdicts="Rendered, Skipped or Failed, then the figure and its caption.",
    howto_narration=[
        "To use me, type to Claude Code and name me: ask the artist for a figure from your results, and say "
        "what it is for. A figure for a talk differs from one for a paper.",
        "My reply starts with Rendered, Skipped or Failed. Then the figure, and a caption that says what to "
        "notice."],
    directions=[
        ("ask the artist for the colony size figure at single-column width for Nature, in our lab colours, as PNG and PDF",
         "The figure in both formats at print resolution, with a draft caption."),
        ("ask the artist for a slide deck of this month's classifier results for lab meeting, in our university's colours",
         "A deck built from the real figures, one take-home line per slide."),
        ("ask the artist to add the new heatmap to our project report, with a caption a first-year student could follow",
         "The report updated, and a caption that says what to notice."),
    ],
    directions_narration=[
        "Say what you want and where it is going: a figure sized for a journal, a deck for lab meeting, or a "
        "new page in the project report.",
        "Name your colours and figure size in the request; within a project I keep one palette for every "
        "figure."],
    docs=[],
)
