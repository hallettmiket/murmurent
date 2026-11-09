"""The blacksmith movie: narration, quotes from agents/blacksmith.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import AMBER

SPEC = AgentSpec(
    agent="blacksmith",
    title="The blacksmith",
    tagline="Runs the analysis on your own data and shows you the code",
    colour=AMBER,
    icon="code",
    intro=["I am the blacksmith. I run the analysis: I load your data, compute what you ask for, "
           "train and test models, and build small apps to explore the results."],
    does=[
        Quote("Loads your data tables, such as CSV and Excel files", "load"),
        Quote("Computes features, statistics and classifiers on your data", "compute"),
        Quote("Builds interactive apps to explore a dataset", "apps"),
        Quote("Runs the computation itself and leaves the commented code beside the result", "computation itself"),
    ],
    does_narration=[
        "I load your data tables, such as CSV and Excel files, compute the features and statistics you ask for, and "
        "train and evaluate classifiers. I build interactive apps so you can explore a dataset.",
        "What makes me different: I run the computation itself on your data, and leave the commented "
        "code beside the result, so anyone can repeat it."],
    refuses=[
        Quote("Covers the computing: data, statistics, models and apps", "computing"),
        Quote("Leaves code the adversary can run again", "adversary"),
        Quote("Leaves original data untouched; new results go in new files", "original"),
    ],
    refuses_narration=[
        "I cover the computing: data, statistics, models and apps. I leave the commented code beside "
        "each result, so the adversary can run it again and check the method.",
        "I read your original data and leave it untouched. Each new result goes in a new, numbered file."],
    examples=[
        Exchange("1", ["A real run, on simulated data. Growth medium turned out to be mixed up with country, "
                       "so the member asks me for the serum effect within each country, with a matching test.",
                       "My answer is Done. The effect holds, but the countries disagree, and I "
                       "say so. I save the results and the code that made them."],
                 [("read the data", True), ("shuffle test within each country", True), ("write the results", True)]),
    ],
    prompt="ask the blacksmith to train a classifier on my experiment's data, with five-fold cross-validation",
    give="The data, where it lives, and what you want computed or predicted.",
    verdicts="Done, Failed or Partial, then the numbers, the files it wrote and the code that made them.",
    howto_narration=[
        "To use me, type to Claude Code and name me: ask the blacksmith to compute, train or build something. "
        "Tell me which data, and what you want out.",
        "My reply starts with Done, Failed or Partial. Then come the numbers, the files and the code, so the "
        "adversary can run it again."],
    directions=[
        ("ask the blacksmith to build an app over my quality-control results, so I can filter cells by mitochondrial fraction and watch the counts change",
         "A small app you open in your browser, reading your data and leaving it as it was."),
        ("ask the blacksmith to train a classifier with five-fold cross-validation, keeping each patient's samples in one fold, and report the result for each fold",
         "The model, the result for each fold, and commented code the adversary can rerun."),
        ("ask the blacksmith to normalise my counts table, keep the 2000 most variable genes and run a PCA, following our template script",
         "A new file for each step, nothing overwritten, and the code that made them."),
    ],
    directions_narration=[
        "Say what you want built: an app to explore your quality control, a classifier tested the way your "
        "data demand, or a series of steps on a counts table.",
        "I work in Python by default; name a template script in your request and I follow it."],
    docs=["rules/data-storage.md"],
)
