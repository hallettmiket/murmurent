# Starting a choreography

A **choreography** is a recipe for how several people, and the agents they run,
work together on one question: who does what, in what order, and what each step
produces. (See [Choreographies](choreography.md) for the idea itself.)

You start one with a single command or a single dashboard button. It creates the
choreography's repository (the folder of code and notes, tracked by git, that
holds the method), poses its question, and asks your PI to make it a project.
You do not need a repository first.

## What it does for you

| Step | What happens |
|---|---|
| Folder | Creates `~/repos/<name>/` with `exp/`, `src/`, `obsolete/`, `data/` and `decisions/`, plus a README, a decision-log guide and a failure catalogue (`how_this_project_breaks.md`) |
| Git | Starts tracking the folder with git |
| Ready | Makes it murmurent-ready, so the patient-data check runs inside it |
| Declared | Writes the choreography's description into `.murmurent.yaml`, which is what `murmurent choreography install` reads |
| Question | Poses the question in your group's choreographies folder, so it appears on the dashboard and members can attach their work to it |
| Data folders | Creates `immutable/<name>/` and `append_only/<name>/` under the data root, when this machine has one |
| First commit | Commits the starter files |
| Project request | Asks your PI to make it a project with the members you name |

When your PI approves the request, murmurent creates the private GitHub
repository, the project's private Slack channel and your lead card (the file that
lets you sign members into the project). You do not create any of those yourself.

## From the dashboard

1. Open the dashboard (`murmurent dashboard --hifi`).
2. In the **Choreographies** panel, click **＋ new choreography**.
3. Fill in the form (each field is explained below) and click **start
   choreography**.
4. The form then lists each step with a tick, and below that, what is left for
   you to do.

**＋ pose a question**, next to it, poses a question with no repository behind it.
Use it when a group wants to advertise a target without a method of its own.

## From the terminal

```bash
murmurent choreography init pin1_inhibition
```

It asks for anything you have not given, shows what it is about to do, and waits
for you to confirm. Press Enter to accept a default.

To answer everything up front instead, for example in a script:

```bash
murmurent choreography init pin1_inhibition \
  --title "Pin1 inhibitors from four approaches" \
  --summary "Docking, an assay and two generative models, combined by the judge." \
  --approaches t1_docking,t2_assay,t3_generative,t4_combinatorial \
  --candidate-key inchikey \
  --criteria @judging_criteria.md \
  --members @bob,@carol \
  --yes
```

`--yes` means "ask nothing". If a required answer is missing, the command lists
what is missing and creates nothing.

## What you are asked

| Question | What it means |
|---|---|
| **Name** | The repository's name, and the project's. Lowercase letters, digits and underscores, starting with a letter, for example `pin1_inhibition`. |
| **Title** | One line a person would recognise it by. |
| **Summary** | One or two sentences: what the approaches are and how they are combined. People read this before installing it. |
| **Mode** | *Compositional* (the usual one): several approaches answer the same question and the judge agent combines them. *Coordination*: a sequence of people and approvals, such as onboarding, with no judge. |
| **Approaches** | Short names for the independent ways the question is attacked. You can add them later. |
| **Candidate key** | What every approach reports on, so their results can be lined up row by row. For molecules this is usually `inchikey` (a standard text code for a chemical structure); for genes, `gene_symbol`. Others: `smiles`, `uniprot`, or `other:<description>`. |
| **Criteria** | How the judge should rank and present results, in your own words. Give text, or `@file` to read it from a file. |
| **Members** | Who besides you should be in the project, as handles such as `@bob`. |

The candidate key and criteria together are the question. You can leave both out
and pose the question later with `murmurent choreography new`.

Other options: `--agents` changes which agents the choreography uses (default:
blacksmith, adversary, bookworm, artist and judge). `--sensitivity` sets the
project's data tier. `--no-project` skips the project request.

## What is left afterwards

The command and the dashboard both finish with this list, filled in with your
choreography's names.

1. **Your PI approves the project request** on the dashboard. Your lead card
   arrives as a Slack message. Import it with `murmurent import-card bundle.json`,
   then issue each member's card from the project's Members list.
2. **Each contributor describes their approach**: what they will report
   (`murmurent contribution contract new`) and the steps that produce it
   (`murmurent contribution spec new`). Then they state it to the group from the
   dashboard.
3. **Each contributor produces a results table** under
   `append_only/<name>/<contribution>/` in the data root, and sets `output:` in
   their spec to point at it.
4. **Attach the contributions** with the dashboard's **attach** button, and check
   that they line up with `murmurent choreography validate`.
5. **Run it**: `murmurent choreography prepare-run`, then ask the judge agent to
   combine the results and the adversary agent to review them, then
   `murmurent choreography freeze-run` to keep a permanent record.

[Assembling a choreography](assembling_choreographies.md) covers steps 2 to 5 in
detail.

## Publishing it

When the method is ready for others to use, push the repository, then open a pull
request adding one line to `choreographies.tsv` in the
[public hub](https://github.com/hallettmiket/murmurent_public): the name, a tab,
and the repository's git address. The decision records and the failure catalogue
are published with it, because they are the evidence for the method. Data is
never published.

## If something goes wrong

- **A step shows ✗.** Nothing after it ran. Fix what it names, then run the same
  command again: it reuses the folder and skips starter files that already exist.
- **"is already a choreography".** That folder has been started already. Pick
  another name, or carry on from the list above.
- **Project request shows "!".** The repository was still created. The usual
  reasons are that this machine has no member identity yet, or that a project with
  that name already exists. Use **＋ new project** on the dashboard and pick the
  repository.
- **First commit shows "!".** Usually git does not know your name yet. The message
  gives the command to run.
- **"this machine has no agent named ...".** The choreography names an agent your
  installation lacks. Check the spelling, or ask whoever maintains that agent.
