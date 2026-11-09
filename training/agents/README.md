# One short movie per commons agent

Seventeen movies, one per agent in [`agents/`](../../agents/), each between
90 seconds and 3 minutes (issue #288). Every movie answers four questions in
the same order: **what it does**, **what it will not do**, **one real example
end to end**, and **how to use it properly through Claude Code**. Members reach
the agents by typing to Claude Code and naming the agent, not by running the
command line, so that is what the movies show.

The list of movies with their links and chapter times is in
[`training/README.md`](../README.md).

## How a movie is made

| File | What it holds |
|---|---|
| `<agent>/scenes.py` | the narration, the quotes, the example's cues and the how-to text, as one `AgentSpec` |
| `<agent>/transcript.md` | the agent's real replies, verdict lines verbatim, detail shortened to fit a frame |
| `<agent>/make.py` | renders the movie (same ten lines in every folder) |
| [`../lib/`](../lib/) | the shared renderer: drawing, scenes timed from the narration, narration with ElevenLabs |
| [`../index.yaml`](../index.yaml) | one entry per movie: version, date and the hash of the agent file it was checked against; chapters |

```bash
python3 training/agents/oracle/make.py                 # renders oracle.mp4 + oracle.srt, then voices oracle_narrated.mp4
python3 training/agents/oracle/make.py --no-voice      # the silent movie only
python3 training/agents/oracle/make.py --stills /tmp/s # one PNG every five seconds, for checking a scene
python3 training/agents/publish.py oracle              # copy to the website repo (see below)
```

Rendering needs Python with PIL and numpy, and ffmpeg. Voicing needs the
ElevenLabs key in the macOS Keychain (service `elevenlabs-api-key`, as
[`training/README.md`](../README.md) step 4 stores it). **Each agent speaks
in its own voice**: the narration is written in the first person ("I am the
bookworm"), and `AGENT_VOICES` in [`../lib/agent_movie.py`](../lib/agent_movie.py)
names an ElevenLabs stock voice for each agent, chosen to match the voice the
spoken verdicts give it (`docs/vscode-workflow.md`): a wise old voice for the
teacher, a steady broadcaster for the judge, a neutral one for the conscience,
which has no persona. `--voice <name>` overrides it for one render; a skill
movie has no agent and keeps the narrator, Matilda. Changing an agent's voice
re-voices its whole movie, since clips are cached by voice and text.
Rendered mp4s and audio clips are not committed. Clips are cached by the text
of the sentence, so a re-render that changes two sentences re-voices two. When
the clips exist, each scene is timed from the measured length of its clip, so
the picture follows the voice; a sentence not yet voiced is timed from a
reading pace and may need a second render once it is.

**The agent's file is the source.** The "what it does" and "what it will not
do" scenes quote `agents/<agent>.md`, and the renderer refuses to run if a
quote is no longer in the file. So a change to the agent is visibly a change
to the movie, not a drift between them. Pick quote fragments without em dashes;
the narration is checked for them too. The verdict lines in the transcripts are
the agents' own output and are kept exactly as they came, dashes included.

**The example is real.** Each transcript is the reply of the agent itself,
run as a subagent on `examples/` or on synthetic data made for the movie
(a throwaway vault, a demo repository with a fake token, an invented run
package), never on a lab member's project. Re-run the agent to refresh it, and
keep the verdict line verbatim.

## When a movie goes out of date

A hook (`murmurent.hooks.agent_movie`, registered by `murmurent install
--hooks`) watches for edits to `agents/<x>.md` in a Claude Code session. When
the file's hash no longer matches the stamp in `index.yaml`, it says so once
per session and names the command to re-render. The release checklist in
[`docs/versioning.md`](../../docs/versioning.md) has the same step. Until the
movie is re-rendered, the agent's file is right and the movie is not.

To update one: edit `scenes.py` if a quote or the narration must change, re-run
the agent if the example must, then `make.py` (which rewrites the entry in
`index.yaml`) and `publish.py`, and commit the website files.

## Publishing

`publish.py` copies each narrated movie, a `.vtt` made from its `.srt`, and a
small player page into `~/repos/hallettmiket.github.io/assets/videos/`, named
`murmurent_agent_<agent>...`. It commits nothing. In that repository, stage
only those files, commit, fetch and fast-forward (`git merge --ff-only
origin/master`, never pull, since the repository may hold unstaged changes),
push, and post the note with `murmurent project note`.
