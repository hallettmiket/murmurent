# A thesis an examiner can question (video, 6 min 20 s)

An animated walkthrough of paper packages, thesis packages and the docent
([`docs/paper_package.md`](../../docs/paper_package.md), issue #284): who is
in the room at a defence, what an examiner gets today, how every claim is
mapped to its evidence, what the candidate runs (`check`, `build`, `talk`,
`paperwork`), how an examiner questions the package through the docent, what
the committee as a whole sees in the query log, and what the package does
not do.

Everything on screen is real. The terminal scenes show the output of the
commands run on [`examples/thesis_example`](../../examples/thesis_example)
(Murmurent 2026.11.0, 7 November 2026). The three docent exchanges are the
docent's own replies to an examiner and to the candidate on that example,
kept verbatim in [`docent_transcript.md`](docent_transcript.md) and shortened
only to fit a frame. No real thesis appears: the pilot thesis is under
examination.

| | |
|---|---|
| **Where it is** | [mikehallett.science](https://mikehallett.science/assets/videos/murmurent_thesis_package.html), to watch in the browser. The [video file itself](https://mikehallett.science/assets/videos/murmurent_thesis_package_720p.mp4) (12 MB, 720p) can be downloaded. |
| **Transcript** | [`thesis_package.srt`](thesis_package.srt): the narration with timings, which also works as a subtitle file |
| **Made with** | `make_movie.py` for the picture; ElevenLabs (voice "Matilda") for the narration, through `voice_narration.py` |
| **Checked against** | Murmurent 2026.11.0 |

## Chapters

| Time | Chapter |
|---|---|
| 0:00 | Welcome |
| 0:15 | Who is in the room |
| 0:41 | The problem |
| 1:01 | The idea |
| 1:30 | The package |
| 1:46 | The candidate: check |
| 2:11 | The candidate: build |
| 2:38 | The candidate: the talk |
| 3:19 | The candidate: paperwork |
| 3:51 | The examiner: asking |
| 4:16 | The examiner: Absent |
| 4:35 | The committee |
| 5:07 | The candidate asks |
| 5:22 | From package to defence |
| 5:44 | What it does not do |
| 5:59 | Recap |

## How it is made

Everything is drawn in Python with PIL and numpy and encoded with ffmpeg; there
are no outside assets, so anyone in the lab can re-render it after a change:

```bash
python3 training/thesis_package/make_movie.py            # writes the mp4 and the srt
python3 training/thesis_package/make_movie.py --stills /tmp/stills   # one PNG every 5 s, no encoding
```

Each scene is drawn from its narration: the script asks "when does the
narrator reach these words" and makes the figure, link or bullet appear then,
and it refuses to render if a phrase is no longer in the narration. Caption
timing is estimated from a reading pace, not measured.

**Narration.** `voice_narration.py` voiced each caption with ElevenLabs (voice
Matilda, model `eleven_multilingual_v2`, as the getting-started video), caches
one clip per sentence, places each at its cue and writes
`thesis_package_narrated.mp4` (the file on the website). It needs the API key in the macOS Keychain, as
[`training/README.md`](../README.md) step 4 stores it, and reports any clip
longer than its caption slot so the scene can be re-timed. Audio clips are not
committed.

## When it goes out of date

If a command, an output or the Western requirements shown in it change, the
written documentation is correct and the video is not. Edit the narration or
the transcript constants in `make_movie.py`, re-render, re-voice the changed
lines (the cache re-voices only those), and update the chapter times and the
"Checked against" version above.
