# Training

Material for learning Murmurent, and for the tools used to make it.

1. [Getting started with Murmurent](#getting-started-with-murmurent-video-6-min-50-s), a 7-minute video
2. [Using ElevenLabs from Claude Code](#using-elevenlabs-from-claude-code), from signing up to making audio, including the free student offer

## Getting started with Murmurent (video, 6 min 50 s)

A narrated walkthrough for someone who has never used Murmurent. It explains
what Murmurent is, then goes through installing it, checking the install,
saying who you are and setting up a folder to work in. It then introduces the
agents and shows how members, lab heads (PIs) and centres join up. Each step
appears on screen as the commands you would type.

| | |
|---|---|
| **Where it is** | [mikehallett.science](https://mikehallett.science/assets/videos/murmurent_getting_started.html), to watch in the browser with captions. The [video file itself](https://mikehallett.science/assets/videos/murmurent_getting_started_1080p.mp4) (33 MB, 1080p) can be downloaded. |
| **Transcript** | [murmurent_getting_started.srt](murmurent_getting_started.srt), in this folder: the full narration with timings, which also works as a subtitle file |
| **Made with** | [ElevenLabs](https://elevenlabs.io): the narration (voice "Matilda") and the music |
| **Checked against** | Murmurent 2026.9.9 |

### Chapters

| Time | Chapter | Covers |
|---|---|---|
| 0:00 | Welcome | |
| 0:14 | What Murmurent is | the agents, members, groups, projects and centres; choreography, not orchestration |
| 0:55 | The plan | |
| 1:10 | Before you start | a terminal on macOS or Linux, git, Claude Code |
| 1:28 | Step 1: install | `uv tool install murmurent`, `murmurent install` |
| 2:00 | Step 2: check the install | `murmurent doctor` |
| 2:20 | Step 3: say who you are | `murmurent init`, the three roles, `murmurent whoami` |
| 2:48 | Step 4: set up a folder | `murmurent repo status`, `repo adopt`, `repo upgrade` |
| 3:20 | Meet the agents | the commons and what each agent does |
| 3:58 | Joining a lab (members) | `murmurent enroll`, member cards, confirming the trust root, `import-card` |
| 4:38 | Joining a centre (PIs) | the public hub, the encrypted join request, the PI ID |
| 5:09 | Starting a centre (mayors) | `centre-init`, `centre-hub-publish` |
| 5:26 | Choreographies | `choreography list`, `install`, `init`, publishing one to the hub |
| 6:03 | Getting help | asking Claude Code, `murmurent doctor`, where to report bugs |
| 6:30 | Recap | |

### How it was made

The narration and music were generated with ElevenLabs from a written script,
using the setup in the next section, and combined with on-screen slides and
terminal animations. Every command shown was run against Murmurent 2026.9.9,
and the output on screen comes from those runs, with the home folder replaced
by `~` or a demo user. The profile details, the example centre and its key are
invented. No real member's contact details appear.

### When it goes out of date

If a later release changes a command shown in the video, the written
documentation is correct and the video is not. To update it, re-voice the
changed lines with ElevenLabs (same voice, "Matilda", and model
`eleven_multilingual_v2`), rebuild the video, and replace the video and
captions in the Google Drive folder. Then replace
`murmurent_getting_started.srt` here and update the chapter times and the
"Checked against" version above.

## Using ElevenLabs from Claude Code

[ElevenLabs](https://elevenlabs.io) makes AI voice and audio. Connected to
Claude Code, it lets you ask Claude, in plain words, to:

- read text aloud and save it as an audio file
- transcribe a recording, with each speaker labelled
- make sound effects or music
- clone a voice, or design a new one from a description
- clean background noise out of a recording

The steps below are for macOS and take about 15 minutes. They were tested in
October 2026.

> **Before you send anything:** text and audio you give ElevenLabs go to its
> servers. Never use it with clinical or restricted data, or with recordings of
> people who haven't agreed to it.

### Step 1: Get an ElevenLabs account (free for 3 months if you're a student)

**University students** can get the ElevenLabs **Creator plan free for 3
months**, which includes the API that Claude Code uses. As of October 2026 the
offer is for university students aged 18 and over in Canada, the US, the UK,
the EU and Australia.

1. Go to <https://elevenlabs.io/students> and click **Get 3 months free**.
2. Sign up, or sign in if you already have an account.
3. Verify that you're a student when asked.
4. Check it worked: in your account, the plan should say **Creator**.

**Check what happens after 3 months.** ElevenLabs doesn't say publicly whether
the plan then starts charging or drops back to free. Look at
**Subscription** in your account settings as soon as you're in, and put a
reminder in your calendar a week before the 3 months end. Cancel then if you
don't want to pay.

The same page also offers a separate free year of **ElevenReader Ultra**, an
app that reads documents aloud. You don't need it for anything here.

**Not a student?** The free plan works for everything below. It gives 10,000
credits a month (roughly 10,000 characters of speech) but doesn't include voice
cloning.

### Step 2: Create an API key

The API key is the password Claude Code uses to reach your ElevenLabs account.

1. Go to <https://elevenlabs.io/app/settings/api-keys> and create a new key.
2. Name it (for example `claude`) and leave **Expire After** on **Never**. For
   full access, don't restrict it.
3. **Copy the key from the popup straight away.** It starts with `sk_` and is
   shown only this once. Afterwards the website only shows the key's ID, which
   looks similar but doesn't work as a key. If you lose the key, delete it and
   create another.

Never paste the key into a chat (with Claude, Slack or anyone), an email, or a
file in a repository. The next steps store it where only your Mac can read it.

### Step 3: Install the ElevenLabs connector

You need Claude Code and [`uv`](https://docs.astral.sh/uv/), which you already
have if you installed Murmurent. In a terminal:

```bash
uv tool install elevenlabs-mcp
```

This is ElevenLabs' official connector for the full API. ElevenLabs has also
released a hosted connector that needs no key, but it only covers voice agents
and simple text-to-speech, so it isn't used here.

### Step 4: Store the key in your Mac's Keychain

```bash
security add-generic-password -U -a "$USER" -s elevenlabs-api-key -w
```

Paste the `sk_` key when asked, press Enter, then paste it again. Nothing
appears while you paste; that's normal. Running the command again replaces the
stored key.

### Step 5: Add a launcher that reads the key

This makes a small script that fetches the key from the Keychain each time the
connector starts, so the key is never written into a settings file. Copy the
whole block into a terminal:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/elevenlabs-mcp-keychain <<'EOF'
#!/bin/sh
# Start the ElevenLabs connector with the API key from the macOS Keychain.
if [ -z "$ELEVENLABS_API_KEY" ]; then
  ELEVENLABS_API_KEY="$(/usr/bin/security find-generic-password \
    -a "${USER:-$(id -un)}" -s elevenlabs-api-key -w 2>/dev/null)" || {
    echo "elevenlabs-mcp: no API key in Keychain (service 'elevenlabs-api-key')" >&2
    exit 1
  }
  export ELEVENLABS_API_KEY
fi
exec "$HOME/.local/bin/elevenlabs-mcp" "$@"
EOF
chmod 700 ~/.local/bin/elevenlabs-mcp-keychain
```

### Step 6: Connect it to Claude Code

```bash
claude mcp add --scope user elevenlabs -- "$HOME/.local/bin/elevenlabs-mcp-keychain"
```

`--scope user` makes ElevenLabs available in every project. If your terminal
says `claude: command not found` (common if you only use the Claude desktop
app), open a Claude Code session and ask it to *"add a user-scope MCP server
called elevenlabs that runs ~/.local/bin/elevenlabs-mcp-keychain"*.

### Step 7: Check it works

Start a **new** Claude Code session (sessions that were already open don't see
new connectors) and ask:

> Check my ElevenLabs subscription.

Claude should reply with your plan and how many credits you've used. If it
says *"API key ID used as API key"*, you stored the key's ID rather than the
key: go back to Step 2, create a new key, and repeat Step 4.

### Step 8: Use it

Ask for what you want in plain words, for example:

- *"Use ElevenLabs to read this paragraph aloud in a calm voice and save it."*
- *"Transcribe `meeting.m4a` on my Desktop, with speakers labelled."*
- *"Make a 5-second sound effect of rain on a window."*
- *"List the ElevenLabs voices that sound like a British narrator."*

Things to know:

- **Files go to your Desktop.** Audio Claude makes is saved there, and audio
  you want transcribed, cloned or cleaned must be on your Desktop too. To use
  another folder, run Step 6 like this instead (remove the old one first with
  `claude mcp remove elevenlabs -s user`):

  ```bash
  claude mcp add --scope user elevenlabs --env ELEVENLABS_MCP_BASE_PATH="$HOME/Documents/audio" -- "$HOME/.local/bin/elevenlabs-mcp-keychain"
  ```
- **Everything uses credits.** Ask *"check my ElevenLabs subscription"* to see
  how many you have left.
- **One tool makes real phone calls.** The connector can place outbound calls
  through ElevenLabs voice agents. They reach real numbers and cost money, so
  only approve that tool if you meant to.
- **Claude asks before each ElevenLabs action**, depending on your permission
  settings. Read what it's about to do before you approve.

### Removing it

```bash
claude mcp remove elevenlabs -s user
uv tool uninstall elevenlabs-mcp
security delete-generic-password -a "$USER" -s elevenlabs-api-key
rm ~/.local/bin/elevenlabs-mcp-keychain
```

Then delete the key at <https://elevenlabs.io/app/settings/api-keys>, and
cancel the plan under **Subscription** if you no longer need it.
