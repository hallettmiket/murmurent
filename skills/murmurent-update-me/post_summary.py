#!/usr/bin/env python3
"""
Purpose: Post a /murmurent-update-me summary to the project's Slack channel
         with the lab's own Slack bot, exactly as rules/slack.md in murmurent
         says, or show what would be posted (--dry-run).
Author: blacksmith (Claude Code) for Mike Hallett
Date: 2026-09-30 (survival project); generalised for every project 2026-10-14 (#152)
Input: A plain-text file holding the summary (Slack formatting: *bold*, "-" bullets).
       Channel and lab come from the `update_me:` block of the repository's
       .murmurent.yaml (see SKILL.md), or from the project's record. The Slack
       token is resolved at run time by murmurent, from the environment variable
       MURMURENT_GROUP_SLACK_TOKEN or ~/.config/murmurent/groups/<lab>/slack-token.
       It is never printed and never written anywhere.
Output: The message, printed in full. On a real post, one line (time, channel,
        account) appended to ~/.murmurent/update_me_posted.log, which
        gather_facts.py reads to know when the last update went out.

Run from inside the project's repository, with the Python that has murmurent:
    MPY="$HOME/.local/share/uv/tools/murmurent/bin/python3"
    "$MPY" ~/.claude/skills/murmurent-update-me/post_summary.py SUMMARY.txt --dry-run
    "$MPY" ~/.claude/skills/murmurent-update-me/post_summary.py SUMMARY.txt

Exit status: 0 posted (or dry run shown), 2 the text breaks a rule below,
3 murmurent is not importable, 4 no usable token, 5 Slack refused the post,
1 anything else. Every failure prints a sentence, not a traceback.
"""

from __future__ import annotations

import argparse
import subprocess
import datetime as dt
import logging
import os
import pwd
import re
import sys
from pathlib import Path

# Set by configure() from the repository's .murmurent.yaml before anything posts.
PROJECT = ""
CHANNEL_ID = ""
CHANNEL_NAME = ""
SLACK_GROUP = ""  # the lab whose bot posts
# The closing sentence once required by rules/local/slack_deployment.md, retired by Mike on
# 2026-10-01. It is stripped if a draft still carries it, and never added.
RETIRED_CLOSING_SENTENCE = "All worship me and I will let you serve me."
TOKEN_ENV = "MURMURENT_GROUP_SLACK_TOKEN"
TOKEN_FILE = Path.home() / ".config" / "murmurent" / "groups" / "<lab>" / "slack-token"  # set by configure()
SLACK_TOKEN_PREFIX = "xox"
POST_LOG = Path.home() / ".murmurent" / "update_me_posted.log"
POST_LOG_MODE = 0o600
MAX_LINES = 30
SLACK_LOGGER = "murmurent.dashboard.slack_notify"

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_RULE = 2
EXIT_NO_MURMURENT = 3
EXIT_NO_TOKEN = 4
EXIT_REFUSED = 5

# Checks on the text. Each is (pattern, what it catches). A match refuses the post.
SMALL_COUNT_RULE = (
    re.compile(
        r"\b[0-5]\s+(?:women|woman|men|man|patients?|participants?|subjects?|donors?|events?|recurrences?|"
        r"cases?|deaths?|samples?|people)\b",
        re.IGNORECASE,
    ),
    "a count under six (write 'fewer than six' or leave it out)",
)
RULES = [
    (re.compile(r"xox[abprse]-[A-Za-z0-9-]{6,}"), "something shaped like a Slack token"),
    (re.compile(r"(?:^|[/\s])publication/"), "a path inside a publication/ folder"),
    SMALL_COUNT_RULE,  # on by default; a project with no human data may set allow_small_counts
    (re.compile("—"), "an em dash (use a comma, a colon or two sentences)"),
]

def slack_errors() -> dict[str, str]:
    """Plain sentences for the Slack errors seen in practice, for this channel."""
    return {
        "invalid_auth": "the token is not valid. On an account other than the PI's the token file may hold "
        f"a placeholder. Ask the PI to post it, or set {TOKEN_ENV} for this one command.",
        "not_authed": "no token reached Slack.",
        "not_in_channel": f"the lab's bot is not a member of {CHANNEL_NAME}. In Slack, invite the bot to the "
        "channel once (/invite @<bot name>), then post again.",
        "channel_not_found": f"Slack cannot find channel {CHANNEL_ID} for this bot; the bot may belong to "
        "another workspace.",
    }


def repo_root() -> Path:
    """Top folder of the repository the session is open in."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return Path(out) if out else Path.cwd()


def configure(channel: str = "") -> None:
    """Set project, lab, channel and checks from .murmurent.yaml and the project record.

    Order for the channel: --channel, then update_me.channel, then the
    project's own Slack channel in its record. Without one, posting stops with
    a sentence saying where to set it.
    """
    global PROJECT, CHANNEL_ID, CHANNEL_NAME, SLACK_GROUP, TOKEN_FILE, RULES
    repo = repo_root()
    data: dict = {}
    try:
        import yaml
        loaded = yaml.safe_load((repo / ".murmurent.yaml").read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001 - no marker means defaults
        data = {}
    block = data.get("update_me") if isinstance(data.get("update_me"), dict) else {}
    PROJECT = str(block.get("project") or data.get("name") or repo.name)
    SLACK_GROUP = str(block.get("lab") or data.get("lab") or "").removeprefix("lab_")
    TOKEN_FILE = Path.home() / ".config" / "murmurent" / "groups" / (SLACK_GROUP or "<lab>") / "slack-token"
    CHANNEL_ID = channel or str(block.get("channel") or "")
    if not CHANNEL_ID:
        # The same resolver every murmurent note uses (issue #243): the
        # project's channel, else the lab's, never a shared channel.
        try:
            from murmurent.core.slack_routing import resolve_route
            CHANNEL_ID = resolve_route(repo, project=PROJECT or None, honour_marker=True).channel_id
        except Exception:  # noqa: BLE001 - a missing record is reported below, at post time
            CHANNEL_ID = ""
    CHANNEL_NAME = str(block.get("channel_name") or (f"the {PROJECT} channel" if CHANNEL_ID else ""))
    if block.get("allow_small_counts") is True:
        RULES = [rule for rule in RULES if rule is not SMALL_COUNT_RULE]


class StopWithMessage(Exception):
    """A failure that ends the script with a plain sentence and an exit status."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class _Collector(logging.Handler):
    """Keep the warnings murmurent logs when a post fails, to name the reason."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def build_message(text: str) -> str:
    """Return the text to post, without the retired closing sentence."""
    body = text.strip()
    if body.endswith(RETIRED_CLOSING_SENTENCE):
        body = body[: -len(RETIRED_CLOSING_SENTENCE)].rstrip()
    return body


def check_rules(message: str) -> list[str]:
    """Return one sentence per rule the message breaks; empty when it breaks none."""
    problems = []
    for pattern, what in RULES:
        match = pattern.search(message)
        if match:
            problems.append(f"it contains {what}: \"{match.group(0).strip()}\"")
    return problems


def token_source() -> tuple[str, str]:
    """Say where murmurent will find the token, without reading it into output.

    Returns
    -------
    tuple of (str, str)
        ('env' | 'file' | 'none', a sentence for the reader).
    """
    if os.environ.get(TOKEN_ENV, "").strip():
        return "env", f"from the environment variable {TOKEN_ENV}"
    if TOKEN_FILE.is_file():
        return "file", f"from {TOKEN_FILE}"
    return "none", f"not found: neither {TOKEN_ENV} nor {TOKEN_FILE} exists on this account"


def load_murmurent() -> tuple[object, object]:
    """Import the two murmurent functions rules/slack.md names."""
    try:
        from murmurent.core.group_reconcile import resolve_group_slack_token
        from murmurent.dashboard.slack_notify import _post
    except ImportError as exc:
        raise StopWithMessage(
            f"murmurent is not importable from this Python ({sys.executable}): {exc}. Run the script with "
            "murmurent's own Python, usually $HOME/.local/share/uv/tools/murmurent/bin/python3.",
            EXIT_NO_MURMURENT,
        ) from exc
    return resolve_group_slack_token, _post


def post(message: str) -> None:
    """Post the message with the lab bot; raise StopWithMessage on any failure."""
    if not CHANNEL_ID:
        raise StopWithMessage(
            f"No Slack channel is known for {PROJECT}. Set update_me.channel (a channel ID such as C0123ABC) "
            "in the repository's .murmurent.yaml, or pass --channel.", EXIT_UNEXPECTED)
    if not SLACK_GROUP:
        raise StopWithMessage(
            "No lab is known, so no bot can post. Set lab: in the repository's .murmurent.yaml.", EXIT_NO_TOKEN)
    resolve_group_slack_token, slack_post = load_murmurent()
    token = resolve_group_slack_token(SLACK_GROUP)
    if not token:
        raise StopWithMessage(
            f"No Slack token for group '{SLACK_GROUP}' on this account ({token_source()[1]}). Usually only the PI's "
            f"account holds the lab bot's token. Ask the PI to post, or set {TOKEN_ENV} for this one command.",
            EXIT_NO_TOKEN,
        )
    if not token.startswith(SLACK_TOKEN_PREFIX):
        raise StopWithMessage(
            f"The Slack token for group '{SLACK_GROUP}' ({token_source()[1]}) is not shaped like a Slack "
            "token, so it is probably a placeholder. Ask the PI to post this update.",
            EXIT_NO_TOKEN,
        )
    collector = _Collector()
    logging.getLogger(SLACK_LOGGER).addHandler(collector)
    try:
        is_posted = slack_post(CHANNEL_ID, message, token=token)
    finally:
        logging.getLogger(SLACK_LOGGER).removeHandler(collector)
    if is_posted:
        return
    reason = "Slack gave no reason"
    for record in collector.records:
        args = record.args if isinstance(record.args, tuple) else ()
        code = str(args[-1]) if args else record.getMessage()
        reason = slack_errors().get(code, f"Slack replied: {code}")
    raise StopWithMessage(f"The post to {CHANNEL_NAME} failed: {reason}", EXIT_REFUSED)


def record_post(now: dt.datetime) -> None:
    """Append the time of this post to the post log, readable by this account only."""
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    account = pwd.getpwuid(os.getuid()).pw_name
    with POST_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{now.isoformat(timespec='minutes')}\t{CHANNEL_ID}\t{account}\t{PROJECT}\n")
    POST_LOG.chmod(POST_LOG_MODE)


def show(message: str, heading: str) -> None:
    """Print the message between two rules, exactly as it is or would be posted."""
    rule = "-" * 72
    sys.stdout.write(f"{heading}\n{rule}\n{message}\n{rule}\n")


def run(args: argparse.Namespace) -> int:
    """Check, show and (unless --dry-run) post the summary."""
    path = Path(args.text_file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StopWithMessage(f"Cannot read the summary file {path}: {exc.strerror}.", EXIT_UNEXPECTED) from exc
    if not text.strip():
        raise StopWithMessage(f"The summary file {path} is empty.", EXIT_UNEXPECTED)
    configure(args.channel)
    message = build_message(text)
    problems = check_rules(message)
    line_count = len(message.splitlines())

    if args.dry_run:
        where = f"{CHANNEL_NAME} ({CHANNEL_ID})" if CHANNEL_ID else "NO CHANNEL SET (see SKILL.md, update_me.channel)"
        show(message, f"DRY RUN: this is what would be posted to {where}:")
        sys.stdout.write(f"Lines: {line_count} (aim for about 25; more than {MAX_LINES} is too long)\n")
        sys.stdout.write("Rules: " + ("all passed" if not problems else "BROKEN, " + "; ".join(problems)) + "\n")
        sys.stdout.write(f"Token: {token_source()[1]} (never shown)\n")
        try:
            load_murmurent()
            sys.stdout.write("murmurent: importable from this Python\n")
        except StopWithMessage as exc:
            sys.stdout.write(f"murmurent: {exc}\n")
        sys.stdout.write("Nothing was posted.\n")
        return EXIT_RULE if problems else EXIT_OK

    if problems:
        raise StopWithMessage("Not posted, because " + "; ".join(problems) + ". Fix the text and run again.", EXIT_RULE)
    post(message)
    now = dt.datetime.now()
    show(message, f"Posted to {CHANNEL_NAME} at {now:%H:%M}:")
    try:
        record_post(now)
    except OSError as exc:
        sys.stderr.write(f"Posted, but the time could not be recorded in {POST_LOG}: {exc.strerror}.\n")
    return EXIT_OK


def main(argv: list[str]) -> int:
    """Parse the command line and turn every failure into one plain sentence."""
    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    parser = argparse.ArgumentParser(description="Post a /murmurent-update-me summary to the project's channel.")
    parser.add_argument("text_file", help="file holding the summary text")
    parser.add_argument("--channel", default="", help="Slack channel ID, overriding .murmurent.yaml")
    parser.add_argument("--dry-run", action="store_true", help="show what would be posted; post nothing")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StopWithMessage as exc:
        sys.stderr.write(f"{exc}\n")
        return exc.status
    except Exception as exc:  # noqa: BLE001  a sentence, never a traceback
        sys.stderr.write(f"Unexpected problem, nothing posted: {type(exc).__name__}: {exc}\n")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
