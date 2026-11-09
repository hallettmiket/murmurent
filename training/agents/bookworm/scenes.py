"""The bookworm movie: narration, quotes from agents/bookworm.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import TEAL

SPEC = AgentSpec(
    agent="bookworm",
    title="The bookworm",
    tagline="Finds the literature and checks every citation against its source",
    colour=TEAL,
    icon="mag",
    intro=["This is the bookworm. It finds the published papers and database records your project needs, "
           "and it checks each one before you rely on it."],
    does=[
        Quote("Finds and summarises the papers your project needs", "finds"),
        Quote("Annotates your genes with what the databases already know", "databases"),
        Quote("Checks every citation against the paper itself", "checks every citation"),
        Quote("Labels every number verified, or says it cannot trace it", "labels"),
    ],
    does_narration=[
        "It finds and summarises the papers your project needs, keeps your reading list, and annotates "
        "your results with what the public databases already know about each gene.",
        "What makes it different: it checks every citation and every number it reports against the paper "
        "itself, and labels each one verified or not."],
    refuses=[
        Quote("Covers published papers and public databases", "published"),
        Quote("The blacksmith runs the analysis", "blacksmith"),
        Quote("The adversary judges the method; the artist draws the figures", "adversary"),
        Quote("Shows conflicting database records side by side", "conflict"),
    ],
    refuses_narration=[
        "The bookworm covers the published papers and the public databases. The blacksmith runs the "
        "analysis, the adversary judges the method, and the artist draws the figures.",
        "When two databases disagree, it shows you the conflict and names both sources."],
    examples=[
        Exchange("1", ["A real run. A draft cites a real paper for a striking number, and the member asks "
                       "the bookworm to check both.",
                       "The paper is real. The number is not in it. The bookworm labels each part, and "
                       "suggests dropping the figure or citing a study that measured it."],
                 [("check each citation", True), ("fetch the full text", True), ("search for the number", False)]),
    ],
    prompt="ask the bookworm to check the citations and numbers in the introduction of my draft",
    give="The paper and the sentence that relies on it, or your project question.",
    verdicts="How many sources it found, or, for a check, the problem it found. Then each item labelled verified, mismatch, retracted, secondary only or unresolved.",
    howto_narration=[
        "To use it, type to Claude Code and name it: ask the bookworm to check a draft, or to find what is "
        "known about a gene. Give it the paper and the sentence that relies on it.",
        "The reply starts with a one-line verdict: how many sources it found, or, for a check, the problem "
        "it found. Then each item carries a label, from verified to unresolved. An unresolved number is one you cannot use yet."],
    directions=[
        ("ask the bookworm for the five most cited papers on MMP11 in DCIS since 2020, as a reading list in my Zotero library",
         "Five papers, one paragraph each, every reference checked, each one added to your Zotero library if you have connected it."),
        ("ask the bookworm to check every reference in my manuscript and give me a table I can paste into my response to the reviewers",
         "One row per reference: its label, and what the source actually says."),
        ("ask the bookworm to add what is published in breast cancer about the top 50 genes in my results table, with PubMed numbers",
         "Your table with a column of findings and their sources, and any disagreement between databases shown."),
    ],
    directions_narration=[
        "Say what you want back: a reading list in your Zotero library, a table for the reviewers, or your "
        "gene list annotated with its sources.",
        "It searches PubMed, CrossRef and the preprint servers. If you have connected your own Zotero "
        "library, it adds each paper there. The checking is always done."],
    docs=["docs/reporting_guidelines.md"],
)
