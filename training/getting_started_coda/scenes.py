"""A 20-second coda appended to the getting-started video (issue #290): point at the Claude Code movie.
append.py puts it on the end of the 1080p file and extends the captions."""
from lib.draw import AMBER
from lib.movie import Movie, Part

MOVIE = Movie(
    key="getting_started_coda",
    title="Before you start working",
    tagline="Watch the two-minute movie on working through Claude Code",
    glyph="💬",
    colour=AMBER,
    summary="Coda of the getting-started video.",
    index=False,
    parts=[
        Part("title", ["One more thing. Before you start working, watch the two-minute movie on working through "
                       "Claude Code: how to address an agent by name, what a verdict line is, and what the hooks refuse.",
                       "All the videos are at mikehallett dot science, slash assets, slash videos."], chapter="Coda"),
    ],
)
