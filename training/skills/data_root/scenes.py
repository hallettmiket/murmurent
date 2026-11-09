"""The data root (tier-3 memory): the lab folder protocol, what each folder is for, how a project's folders
mirror its repository, and what the hooks refuse. Every terminal scene is a real run on a demo data root."""
from lib.draw import AMBER, RED, TEAL
from lib.movie import Movie, Part, Quote

T_TREE = """
$ echo $MURMURENT_DATA_ROOT
/data/lab_vm
$ ls /data/lab_vm
append_only  cottage  db  immutable  modifiable  mothballed  release  tools
$ ls /data/lab_vm/immutable/project_x /data/lab_vm/append_only/project_x
immutable/project_x:
reads_lane1.fastq.gz
append_only/project_x:
3_qc
$ ls ~/repos/project_x/exp
3_qc
"""

T_HOOKS = """
$ # Claude Code asks to write into immutable; the hook answers
immutable data is read-only by lab policy; refusing Write on
/data/lab_vm/immutable/project_x/reads_lane1.fastq.gz
$ # Claude Code asks to overwrite a result under append_only
protected path is write-once by lab policy; refusing Write that would overwrite
/data/lab_vm/append_only/project_x/3_qc/qc_table_1.csv.
Use an integer-versioned name (e.g. file_2.csv) instead.
$ # Claude Code asks to edit a result under append_only
protected path is write-once by lab policy; refusing Edit on
/data/lab_vm/append_only/project_x/3_qc/qc_table_1.csv. Write a new version-suffixed file instead.
"""

T_LAYOUT = """
$ murmurent space layout
Lab folder: /data/lab_vm
Being phased out:
  - sandbox/ is being phased out; ask its owners to move what they still need into a project's folders or their cottage.
Loose files:
  - notes_from_2019.txt is a file at the top of the lab folder; files belong inside a project's folder or a person's cottage.
Named after no project:
  - append_only/stuff/ does not match any project's name; rename it to its project, or make a project for it.
(on this laptop, with no project records, every project folder is listed the same way)
"""

MOVIE = Movie(
    key="data_root",
    title="The data root: where big files live",
    tagline="Where the lab's big files live, and what each folder is for",
    glyph="🗄️",
    colour=TEAL,
    summary="Murmurent's third tier of memory: the lab's data root on its server, what immutable, append_only, modifiable, mothballed, release, cottage, tools and db are for, how a project's folders mirror its repository, what the hooks refuse, and the layout check.",
    parts=[
        Part("title", ["The data root is where a lab's big files live, on the lab's server, in folders with clear "
                       "rules. Here is what each folder is for."]),
        Part("cards", chapter="Three tiers", heading="The big files, on the lab's server", source="rules/data-storage.md",
             colour=TEAL,
             quotes=[Quote("A lab's big files live in one folder on its server.", "one folder"),
                     Quote("Protected and very large data stays on the server.", "stays there")],
             narration=["Murmurent remembers at three levels: what an agent sees in one session, what the oracle "
                        "keeps, and the big files. The big files live in one folder on the lab's server, the data "
                        "root. Protected or very large data stays there, and you reach it from your laptop over "
                        "the network."]),
        Part("terminal", chapter="The folders", heading="One data root, one folder per purpose", transcript=T_TREE,
             title="Terminal, a demo data root", colour=TEAL,
             notes=[("Eight folders at the top; inside most, one folder per project.", "eight folders"),
                    ("Project x has a folder in immutable and one in append_only.", "project x keeps"),
                    ("Results carry the same experiment names as the code.", "same experiment names")],
             narration=["Eight folders sit at the top. Inside most, every project has a folder with its own name. "
                        "So a project called project x keeps its original data in immutable and its results in "
                        "append only, under the same experiment names as its code."]),
        Part("folders", chapter="What each folder is for", heading="What each folder is for", colour=AMBER,
             folders=[("immutable", "original data, kept exactly as it arrived", "immutable"),
                      ("append_only", "analyses; each new file or version is added", "append only"),
                      ("modifiable", "working data that may change", "modifiable"),
                      ("mothballed", "waiting for long-term storage, then off the server", "mothballed"),
                      ("release", "the lab's copy of what it published", "release"),
                      ("cottage", "one person's large files, such as software environments", "cottage"),
                      ("tools", "programs the whole lab uses", "tools"),
                      ("db", "databases several people use", "db")],
             narration=["Immutable is the data as it arrived: from the instrument, a collaborator or a public "
                        "source. It stays exactly as placed, so every analysis traces back to it.",
                        "Append only is where analyses write. Each new result or version is added beside the last, "
                        "so a result you reported last year is still there. Modifiable holds a project's working "
                        "files, the data that may change.",
                        "Mothballed is how the server makes room. Move there what you no longer need on the "
                        "server; it goes to long-term storage and then leaves the server. Release holds the lab's "
                        "own copy of what it published: the papers and the software.",
                        "Cottage holds each person's large files, such as software environments, because home "
                        "folders are small. Tools holds programs the whole lab uses, and db the databases several "
                        "people share."]),
        Part("terminal", chapter="What Claude Code refuses", heading="What Claude Code refuses, in its own words", transcript=T_HOOKS,
             title="Inside a Claude Code session", colour=RED,
             notes=[("A change to immutable data: refused.", "immutable"),
                    ("Writing over a result in append_only: refused.", "writes over"),
                    ("Overwriting anything in immutable or append_only: refused.", "overwriting")],
             narration=["Once installed, guards inside Claude Code keep these rules for every agent. Overwriting "
                        "anything in immutable or append only is refused, in these words: a change to immutable "
                        "data, a result that writes over an older one, an edit to a result. The guards catch an agent's mistake; what you do yourself in a terminal "
                        "is yours to keep careful."]),
        Part("terminal", chapter="Keeping it tidy", heading="The layout check: it reports, the PI decides", transcript=T_LAYOUT,
             title="Terminal: a demo data root with three mistakes", colour=AMBER,
             notes=[("A folder being retired, a loose file, a folder named after no project.", "three"),
                    ("The PI decides; agents report and leave every file in place.", "decides")],
             narration=["One check compares the data root with these rules, here on a demo with three planted "
                        "mistakes. It reads names only. The PI decides; agents report and leave every file where "
                        "it is."]),
        Part("howto", heading="How to use it",
             prompt="ask the blacksmith to run the 3_qc experiment for project_x and save the results in append_only, as a new version",
             cards=[("Name the folder", "Original data to immutable, results to append_only, working files to modifiable."),
                    ("Add a version", "A new result gets the next number, beside the old one; both stay."),
                    ("Big files: the server", "Reach it from your laptop over the network.")],
             docs=["rules/data-storage.md", "docs/lab_folders.md", "rules/project-structure.md"],
             narration=["When you ask an agent for work, name the folder: original data to immutable, results to "
                        "append only, working files to modifiable. A new result is a new version beside the old "
                        "one. Big data stays on the server."]),
    ],
)
