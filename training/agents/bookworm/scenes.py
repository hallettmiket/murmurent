"""The bookworm movie: narration in the bookworm's own voice, quotes from agents/bookworm.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import TEAL

SPEC = AgentSpec(
    agent="bookworm",
    title="The bookworm",
    tagline="Finds the papers and the database records your project needs, and checks each one against its source",
    colour=TEAL,
    icon="mag",
    intro=["I am the bookworm. I find the published papers and the database records your project needs, "
           "and I check each one before you rely on it."],
    does=[
        Quote("Finds and summarises the papers your project needs", "papers"),
        Quote("Looks up facts in the scientific databases: genes, proteins, compounds, trials", "databases"),
        Quote("Checks every citation against the paper itself", "every citation"),
        Quote("Labels every number verified, or says it cannot trace it", "label each"),
    ],
    does_narration=[
        "I find and summarise the papers your project needs, and I keep your reading list.",
        "I am not only about the literature. I look up facts in the scientific databases: a gene in UniProt, "
        "a compound and its measured activities in ChEMBL, a trial in a trials registry, and I annotate "
        "your results with what is already known.",
        "What makes me different: I check every citation and every number I report against the paper "
        "itself, and I label each one verified, mismatch, retracted, secondary only, or unresolved."],
    refuses=[
        Quote("Covers published papers and public databases", "published"),
        Quote("Never collapses two database records that disagree", "disagree"),
        Quote("Checks the citations the teacher and the conscience cannot verify", "teacher"),
        Quote("Keeps the centre's reporting guidelines and equity resources current", "guidelines"),
    ],
    refuses_narration=[
        "I cover the published papers and the public databases. When two databases disagree, I show you "
        "both records and name their sources; I never quietly pick one.",
        "Other agents lean on me: the teacher and the conscience send me the citations they cannot verify, "
        "and I keep the centre's reporting guidelines and equity resources current."],
    examples=[
        Exchange("1", ["A real run. A draft cites a real paper for a striking number, and the member asks "
                       "me to check both.",
                       "The paper is real. The number is not in it. I label each part, and suggest "
                       "dropping the figure or citing a study that measured it."],
                 [("check each citation", True), ("fetch the full text", True), ("search for the number", False)]),
    ],
    prompt="ask the bookworm to check the citations and numbers in the introduction of my draft",
    give="The paper and the sentence that relies on it, or your project question.",
    verdicts="How many sources it found, or, for a check, the problem it found. Then each item labelled verified, mismatch, retracted, secondary only or unresolved.",
    howto_narration=[
        "To use me, type to Claude Code and name me: ask the bookworm to check a draft, or to find what is "
        "known about a gene or a compound. Give me the paper and the sentence that relies on it.",
        "My reply starts with a one-line verdict: how many sources I found, or, for a check, the problem "
        "I found. Then each item carries a label, from verified to unresolved. An unresolved number is one you cannot use yet."],
    directions=[
        ("ask the bookworm for the five most cited papers on MMP11 in DCIS since 2020, as a reading list in my Zotero library",
         "Five papers, one paragraph each, every reference checked, each one added to your Zotero library if you have connected it."),
        ("ask the bookworm to check every reference in my manuscript and give me a table I can paste into my response to the reviewers",
         "One row per reference: its label, and what the source actually says."),
        ("ask the bookworm what ChEMBL and UniProt hold on the top 50 genes in my results table, with the accession numbers",
         "Your table with a column of findings and their sources, and any disagreement between databases shown."),
    ],
    directions_narration=[
        "Say what you want back, and in what form: a reading list in your Zotero library, a table for the "
        "reviewers, or your gene list annotated from the databases. HTML, PowerPoint, Word or LaTeX, as you ask.",
        "I search PubMed, CrossRef, the preprint servers and the databases. If you have connected your own Zotero "
        "library, I add each paper there. The checking is always done."],
    docs=["docs/reporting_guidelines.md"],
)
