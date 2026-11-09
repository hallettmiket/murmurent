"""The lawyer movie: narration, plain statements checked against agents/lawyer.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SKY

SPEC = AgentSpec(
    agent="lawyer",
    title="The lawyer",
    tagline="Patents, and whether your project's data may move or be shared",
    colour=SKY,
    icon="scale",
    intro=["This is the lawyer. It searches the patent databases around a gene, a molecule or a device. And it "
           "rules on whether a project may move or share data that a privacy law, an agreement or an ethics "
           "approval controls, always from the law, agreement or approval itself."],
    does=[
        Quote("Searches patent databases worldwide for genes, molecules and devices.", "searches"),
        Quote("Explains patent claims in plain words you can act on.", "plain words"),
        Quote("Rules on moving data from the signed agreement itself.", "signed agreement"),
        Quote("Checks first whether there is anything to search.", "checks first"),
    ],
    does_narration=[
        "It searches the patent databases worldwide for genes, proteins, molecules and devices, and explains "
        "the claims in plain words a scientist can act on: who owns what, what has expired, what is pending.",
        "For data, it reads the signed agreement or the ethics approval before it rules, and names what is "
        "missing when it cannot find one. It checks first whether there is anything to search, so a question "
        "with no patent at stake costs one step."],
    refuses=[
        Quote("A binding opinion goes through the institution's research office.", "binding"),
        Quote("The institution's patent office does the filing.", "filing"),
        Quote("The bookworm reads journal papers; the lawyer reads patent filings.", "bookworm"),
        Quote("It says whether each status is confirmed or inferred.", "confirmed"),
    ],
    refuses_narration=[
        "It informs your decision. A binding opinion goes through the institution's research office, and the "
        "institution's patent office does the filing. The bookworm reads journal papers; the lawyer reads "
        "patent filings.",
        "For every patent, it says whether the status is confirmed across databases or only inferred."],
    examples=[
        Exchange("1", ["A real run, on a made-up question: may we publish a short protocol note and post our "
                       "script under an open licence? That is a freedom-to-operate question: whether anyone's "
                       "patent blocks you.",
                       "The verdict is Clear, after the first check alone. Publishing is not an act a patent "
                       "reaches, so no database was searched, and the answer says so. It adds the one deadline "
                       "to know: publishing starts the clock on filing a patent of your own."],
                 [("first check", True), ("patent search", False), ("licence check", True)]),
    ],
    prompt="ask the lawyer whether we can order and test these three compounds, with their identifiers",
    give="What you intend to do, and with what. For data, the agreement or ethics approval.",
    verdicts="Clear, Conflict or Unknown, then what it searched or which clause it read.",
    howto_narration=[
        "To use it, type to Claude Code and name the lawyer. Give it the molecule or the data, and what you "
        "intend to do with it.",
        "The first line is the verdict: Clear, Conflict or Unknown. The detail names what it searched, or the "
        "clause it relied on. It reads the agreements and ethics approvals your lab keeps in its project "
        "records. The adversary also sends it questions during an audit."],
    docs=[],
)
