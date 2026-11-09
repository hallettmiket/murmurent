"""The scribe movie: narration in the scribe's own voice, cards on what the scribe does, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SAND

SPEC = AgentSpec(
    agent="scribe",
    title="The scribe",
    tagline="Scientific writing in your lab's own voice",
    colour=SAND,
    icon="pencil",
    intro=["I am the scribe. I write and revise scientific text in a house style built from one "
           "PI's own edits, which your lab can replace with its own. I keep every fact."],
    does=[
        Quote("Revises your text and lists every change, with its reason", "revise"),
        Quote("Drafts a section from your results, figures and notes", "draft"),
        Quote("Writes in your lab's voice, without being asked", "voice"),
        Quote("Writes in whatever form you ask for, and edits the file when asked", "whatever"),
    ],
    does_narration=[
        "I revise text you give me, mostly by cutting, and I list every change with its reason. "
        "And I draft a section from your results, figures and notes.",
        "I write in your lab's voice by default; nobody has to ask for the house style. I write in "
        "whatever form you ask for: the LaTeX of a manuscript, a Word file for a grant, a Markdown page, "
        "a letter to an editor, a thesis chapter, a lay summary. And I edit the file itself when you ask."],
    refuses=[
        Quote("Every fact, number and citation stays as you wrote it", "number"),
        Quote("Marks a missing citation or number for you to fill", "missing"),
        Quote("A lab adds its own papers and its PI's edits", "tailors"),
    ],
    refuses_narration=[
        "Every fact, number and citation stays as you wrote it; one that looks wrong is flagged for "
        "you to check. Where a citation or a number is missing, I mark the place. If the material "
        "has a hole, say a number nobody has measured, I answer Gap and say what would fill it.",
        "A lab tailors me by adding its own published papers and its PI's edits as examples."],
    examples=[
        Exchange("1", ["A real run, on a passage written to be bad. The member asks for a revision.",
                       "My verdict is Revised. Every number survives, each change is listed with its "
                       "reason, and the one change to the claim itself is shown for the author to accept "
                       "or refuse."],
                 [("read the writing guide", True), ("rewrite", True), ("list each change", True)]),
    ],
    prompt="ask the scribe to tighten the Discussion of our Candida albicans biotherapeutics paper and list what it changed",
    give="The text, or your results and notes, and which part of the paper.",
    verdicts="Revised, Drafted or Gap, then the text and what changed.",
    howto_narration=[
        "To use me, just ask Claude Code: ask the scribe to tighten a section, or to draft one from "
        "your results and notes. Give me the text and say which part of the paper it is for.",
        "The first line of my reply is the verdict: Revised, Drafted or Gap. Then the text, and what "
        "changed and why."],
    directions=[
        ("ask the scribe to tighten the Discussion of our Candida albicans biotherapeutics paper and list what it changed",
         "The Discussion, shorter, every number kept, each change listed with its reason."),
        ("ask the scribe to draft the Methods from my notes on the biotherapeutics screen",
         "A Methods section, with the places marked where a citation or number is missing."),
        ("ask the scribe to write the legend for figure 2 of our grant, in Word, under 120 words",
         "The legend in the lab's voice, under 120 words, as Word text ready to paste into the grant."),
    ],
    directions_narration=[
        "Say what you want in one plain sentence. Tighten the Discussion and list the changes. Draft "
        "the Methods from your notes, with the missing pieces marked.",
        "Or write a figure legend for a grant, in Word, under a word limit. Those are examples; ask for "
        "any piece of scientific writing, in any form."],
    docs=["docs/scientific_writing.md"],
)
