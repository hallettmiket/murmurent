"""The lawyer movie: narration in the lawyer's own voice, plain statements checked against agents/lawyer.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import SKY

SPEC = AgentSpec(
    agent="lawyer",
    title="The lawyer",
    tagline="Patents, and whether your project's data may move or be shared",
    colour=SKY,
    icon="scale",
    intro=["I am the lawyer. I search the patent databases around a gene, a molecule or a device. And I "
           "rule on whether a project may move or share data that a privacy law, an agreement or an ethics "
           "approval controls, always from the law, agreement or approval itself."],
    does=[
        Quote("Searches patent databases worldwide for genes, molecules and devices.", "search"),
        Quote("Explains patent claims in plain words you can act on.", "plain words"),
        Quote("Rules on moving data from the signed agreement itself.", "signed agreement"),
        Quote("Checks first whether there is anything to search.", "check first"),
    ],
    does_narration=[
        "I search the patent databases worldwide for genes, proteins, molecules and devices, and I explain "
        "the claims in plain words a scientist can act on: who owns what, what has expired, what is pending.",
        "For data, I read the signed agreement or the ethics approval before I rule, and I name what is "
        "missing when I cannot find one. I check first whether there is anything to search, so a question "
        "with no patent at stake costs one step."],
    refuses=[
        Quote("A binding opinion goes through the institution's research office.", "binding"),
        Quote("Speaks the vocabulary of Ontario's IP Foundations course: patent, copyright, trademark, trade secret.", "Ontario"),
        Quote("Takes referrals from the adversary mid-audit, and triages them first.", "adversary"),
        Quote("Says whether each status is confirmed or inferred.", "confirmed"),
    ],
    refuses_narration=[
        "I inform your decision. A binding opinion goes through the institution's research office, and the "
        "institution's patent office does the filing.",
        "I speak the vocabulary of the short course Ontario asks its researchers to take, IP Foundations: a "
        "patent for an invention, copyright for a paper or code, a trademark, a trade secret. And I name which one applies.",
        "The adversary refers work to me in the middle of an audit; I triage first, so a referral with nothing "
        "to search costs one step. For every patent, I say whether the status is confirmed across databases or only inferred."],
    examples=[
        Exchange("1", ["A real run, on a made-up question: may we publish a short protocol note and post our "
                       "script under an open licence? That is a freedom-to-operate question: whether anyone's "
                       "patent blocks you.",
                       "My verdict is Clear, after the first check alone. Publishing is not an act a patent "
                       "reaches, so I searched no database, and I say so. I add the one deadline "
                       "to know: publishing starts the clock on filing a patent of your own."],
                 [("first check", True), ("patent search", False), ("licence check", True)]),
    ],
    prompt="ask the lawyer whether we can order and test these three compounds, with their identifiers",
    give="What you intend to do, and with what. For data, the agreement or ethics approval.",
    verdicts="Clear, Conflict or Unknown, then what it searched or which clause it read.",
    howto_narration=[
        "To use me, type to Claude Code and name the lawyer. Give me the molecule or the data, and what you "
        "intend to do with it.",
        "The first line is my verdict: Clear, Conflict or Unknown. The detail names what I searched, or the "
        "clause I relied on. I read the agreements and ethics approvals your lab keeps in its project records."],
    docs=[],
)
