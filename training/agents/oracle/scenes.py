"""The oracle movie: narration, cards on what the oracle does, and the real exchanges in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import LAV

SPEC = AgentSpec(
    agent="oracle",
    title="The oracle",
    tagline="Your personal research memory",
    colour=LAV,
    icon="doc",
    kind="bot",
    intro=["I am the oracle, your personal research memory. Everybody in the lab has an oracle. "
           "A chat window forgets; I keep what you found, and you can search those memories "
           "whenever you like."],
    does=[
        Quote("Keeps your key findings, each with where it came from", "key findings"),
        Quote("Searches them across all your projects, over the years", "across"),
        Quote("Searches your lab notebook: daily notes and your prompts", "lab notebook"),
        Quote("Everything lives in your own Obsidian notes", "Obsidian"),
    ],
    does_narration=[
        "I store your key findings, each with the project and experiment it came from, and "
        "search them across all your projects, over the years.",
        "I also search your lab notebook: your notes for each day, and the prompts you gave "
        "Claude Code, which are recorded automatically. Everything lives in your own Obsidian notes, a folder you "
        "can open and browse yourself."],
    refuses=[
        Quote("Passes findings you choose to the lab oracle", "lab oracle"),
        Quote("Protected and restricted findings stay in your own notes", "protected"),
        Quote("Keeps what you found, not what the literature says", "what you found"),
        Quote("If it holds nothing on a topic, it says so", "factual"),
    ],
    refuses_narration=[
        "When you choose, I prepare a finding for the lab oracle, the lab's shared memory, and you "
        "publish it. Protected and restricted findings, such as patient data or unpublished "
        "results, stay in your own notes.",
        "I keep what you found, not what the literature says. "
        "I remain factual: if I hold nothing on a topic, I say so."],
    examples=[
        Exchange("1", ["A real run. In March, in a project on liver nodules, the small growths in a "
                       "scarred liver that can turn into cancer, the member asks me to remember "
                       "that the gene GPC3 marks early hepatocellular carcinoma, the first stage of liver "
                       "cancer, and tells it apart from a nodule that has not turned.",
                       "I file the finding with its project and experiment."],
                 [("read its index", True), ("write the entry", True), ("update its index", True)]),
        Exchange("2", ["Eight months later, in a liver screening project, the member passes me six genes "
                       "and asks what they know about early liver cancer.",
                       "I recall GPC3, because early hepatocellular carcinoma is early liver "
                       "cancer. For the other five, I say plainly that I hold nothing of theirs."],
                 [("read its index", True), ("read the entry", True)]),
    ],
    prompt="ask the oracle to remember that GPC3 marks early hepatocellular carcinoma, from the nodule experiment",
    give="The finding and where it came from.",
    verdicts="Remembered when it files something; Found, Not found or Unsure when you ask.",
    howto_narration=[
        "To use me, just ask Claude Code: ask the oracle to remember a finding, or what you know about "
        "a topic. Give me the finding and where it came from; I ask for anything missing.",
        "The first line of the reply is the verdict: Remembered, Found, Not found or Unsure. You can open "
        "every entry in Obsidian."],
    docs=["rules/oracle_schema.md", "docs/oracle-workflow.md"],
)
