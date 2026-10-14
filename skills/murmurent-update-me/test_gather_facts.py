#!/usr/bin/env python3
"""
Purpose: Tests for how gather_facts.py pairs agent start and finish lines,
         above all when several agents of one type run at once (four
         blacksmiths at 14:25 on 2026-09-30, when the first version paired
         the /update-me report with the wrong blacksmith).
Author: blacksmith (Claude Code) for Mike Hallett
Date: 2026-09-30
Input: None. Each test writes a small agent log in the real format (colour
       codes, the dash after "starting", blank lines between events) to a
       temporary file and reads it back through read_agent_log().
Output: unittest results on standard output. Writes nothing that outlives a test.

Run from anywhere:
    python3 -B .claude/skills/update-me/test_gather_facts.py
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gather_facts as gf  # noqa: E402  the skill folder is not a package

DAY = "2026-09-30"
NOW = dt.datetime(2026, 9, 30, 15, 30)
MIDNIGHT = dt.datetime(2026, 9, 30, 0, 0)
OLDEST_SESSION = dt.datetime(2026, 9, 30, 9, 58, 59)
COLOUR = "\x1b[96m"
RESET = "\x1b[0m"

# The real log lines from 14:03 to 15:04 on 2026-09-30, finish texts as the hook cut them.
REAL_OVERLAP = [
    ("14:03", "blacksmith", True, "Build the update_me skill"),
    ("14:25", "blacksmith", True, "Write the nCounter protocol record"),
    ("14:25", "blacksmith", True, "Build nCounter outcome-free groundwork"),
    ("14:25", "teacher", True, "Refresh tutorial decision boxes (#15)"),
    ("14:25", "blacksmith", False, "I've built the `/update-me` skill and tested it with a dry run. Nothing was "
     "posted to Slack, and nothing is committed or pushed; the main session will review and commit. **Name.** "
     "The folder and the s"),
    ("14:29", "blacksmith", True, "Build phase 2 results pages"),
    ("15:02", "blacksmith", False, "I wrote the protocol record, PROPOSED. It has 9 NEW items, all recommended for "
     "adoption, and one conflict with the exp/04 brief needs you now. Record: `/home/UWO/mhallet/repos/survival/"
     "decisions/2026-"),
    ("15:03", "blacksmith", False, "The protocol record is written and marked PROPOSED, and my report has gone back "
     "to the main session. **What it covers.** The record fixes every choice for stages A to D and the era and "
     "propensity anal"),
    ("15:04", "adversary", True, "Review the nCounter protocol"),
    ("15:04", "blacksmith", True, "Build nCounter stage code (simulated)"),
    ("15:04", "teacher", False, "I sent my report to the main session. The decision boxes are rewritten; no repo "
     "file was edited, and the app's tutorial tests need re-pinning before the new text goes in. - **Parts 1 to 10 "
     "and step 9b"),
]


def write_log(events: list[tuple[str, str, bool, str]], folder: Path) -> Path:
    """Write events as the murmurent hook writes them, and return the file."""
    path = folder / "agents.log"
    with path.open("w", encoding="utf-8") as handle:
        for clock, agent, is_start, text in events:
            body = f"starting — {text}" if is_start else text
            handle.write(f"{COLOUR}[{DAY} {clock}] {agent}: {body}{RESET}\n\n")
    return path


def match(events: list[tuple[str, str, bool, str]]) -> dict[str, list[dict]]:
    """Parse events through the real reader and matcher."""
    with tempfile.TemporaryDirectory() as folder:
        lines = gf.read_agent_log(write_log(events, Path(folder)))
    return gf.match_agent_lines(lines, MIDNIGHT, NOW, OLDEST_SESSION)


def finish_at(result: dict[str, list[dict]], agent: str, clock: str) -> dict:
    """The finish entry of one agent type at one time (clock 'HH:MM')."""
    hits = [item for item in result["finished"] if item["agent"] == agent and item["finished"] == f"{clock} today"]
    assert len(hits) == 1, f"expected one {agent} finish at {clock}, found {len(hits)}"
    return hits[0]


def open_task(result: dict[str, list[dict]], task: str) -> dict | None:
    """The open entry for a task, or None when the task is not open."""
    hits = [item for item in result["open"] if item["task"] == task]
    return hits[0] if hits else None


class OverlappingSameTypeAgents(unittest.TestCase):
    """The case that broke: several blacksmiths open when one finish line arrives."""

    def setUp(self) -> None:
        self.result = match(REAL_OVERLAP)

    def test_parser_strips_the_dash_and_colour(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            lines = gf.read_agent_log(write_log(REAL_OVERLAP, Path(folder)))
        self.assertEqual(len(lines), len(REAL_OVERLAP))
        self.assertEqual(lines[0].text, "Build the update_me skill")
        self.assertTrue(lines[0].is_start)
        self.assertFalse(lines[4].is_start)
        self.assertEqual(lines[4].agent, "blacksmith")

    def test_update_me_report_goes_to_the_update_me_task(self) -> None:
        entry = finish_at(self.result, "blacksmith", "14:25")
        self.assertEqual(entry["match"], "matched")
        self.assertEqual(entry["task"], "Build the update_me skill")
        self.assertIn("skill", entry["evidence"])

    def test_the_finished_task_is_not_shown_as_running(self) -> None:
        self.assertIsNone(open_task(self.result, "Build the update_me skill"))

    def test_the_groundwork_agent_stays_running_and_is_not_marked_finished(self) -> None:
        entry = open_task(self.result, "Build nCounter outcome-free groundwork")
        self.assertIsNotNone(entry)
        self.assertTrue(entry["status"].startswith("may still be running"))
        self.assertNotIn("may have finished", entry["status"])

    def test_protocol_report_goes_to_the_protocol_task(self) -> None:
        entry = finish_at(self.result, "blacksmith", "15:02")
        self.assertEqual(entry["match"], "matched")
        self.assertEqual(entry["task"], "Write the nCounter protocol record")

    def test_second_protocol_line_is_a_resumed_agent_and_closes_nothing(self) -> None:
        entry = finish_at(self.result, "blacksmith", "15:03")
        self.assertEqual(entry["match"], "resumed")
        self.assertEqual(entry["task"], "Write the nCounter protocol record")
        self.assertIsNotNone(open_task(self.result, "Build phase 2 results pages"))
        self.assertIsNotNone(open_task(self.result, "Build nCounter outcome-free groundwork"))

    def test_teacher_finish_goes_to_its_own_task(self) -> None:
        entry = finish_at(self.result, "teacher", "15:04")
        self.assertEqual(entry["match"], "matched")
        self.assertEqual(entry["task"], "Refresh tutorial decision boxes (#15)")


class UncertainFinishesAreNotGuessed(unittest.TestCase):
    """Where a finish could belong to more than one start, say so and close nothing."""

    TWO_OPEN = [
        ("14:29", "blacksmith", True, "Build phase 2 results pages"),
        ("15:04", "blacksmith", True, "Build nCounter stage code (simulated)"),
    ]

    def test_generic_finish_with_two_candidates_lists_both(self) -> None:
        result = match(self.TWO_OPEN + [("15:20", "blacksmith", False, "Report delivered.")])
        entry = finish_at(result, "blacksmith", "15:20")
        self.assertEqual(entry["match"], "not matched")
        self.assertEqual(
            sorted(candidate["task"] for candidate in entry["candidates"]),
            ["Build nCounter stage code (simulated)", "Build phase 2 results pages"],
        )
        for task in ("Build phase 2 results pages", "Build nCounter stage code (simulated)"):
            status = open_task(result, task)["status"]
            self.assertIn("may have finished", status)
            self.assertIn("15:20 today", status)

    def test_finish_naming_two_open_tasks_is_not_matched(self) -> None:
        result = match(self.TWO_OPEN + [("15:20", "blacksmith", False, "The results pages and the stage code are both built.")])
        entry = finish_at(result, "blacksmith", "15:20")
        self.assertEqual(entry["match"], "not matched")
        self.assertIn("more than one", entry["evidence"])
        self.assertEqual(len(entry["candidates"]), 2)

    def test_a_word_every_candidate_shares_does_not_decide(self) -> None:
        events = [
            ("14:25", "blacksmith", True, "Build nCounter outcome-free groundwork"),
            ("15:04", "blacksmith", True, "Build nCounter stage code (simulated)"),
            ("15:20", "blacksmith", False, "The nCounter work is finished and reported."),
        ]
        entry = finish_at(match(events), "blacksmith", "15:20")
        self.assertEqual(entry["match"], "not matched")
        self.assertEqual(len(entry["candidates"]), 2)

    def test_one_open_start_and_a_generic_finish_is_not_assumed(self) -> None:
        events = [
            ("12:35", "teacher", True, "Part 11 version 7 on the app copy"),
            ("12:53", "teacher", False, "I've sent my report to the session that dispatched me."),
        ]
        result = match(events)
        entry = finish_at(result, "teacher", "12:53")
        self.assertEqual(entry["match"], "not matched")
        self.assertEqual([candidate["task"] for candidate in entry["candidates"]], ["Part 11 version 7 on the app copy"])
        self.assertIn("may have finished", open_task(result, "Part 11 version 7 on the app copy")["status"])


class RestartsResumesAndStoppedSessions(unittest.TestCase):
    """The other rules, unchanged by the fix."""

    def test_restart_retires_the_first_attempt_and_a_resume_is_recognised(self) -> None:
        events = [
            ("10:00", "teacher", True, "Part 11 version 7 on the app copy"),
            ("12:35", "teacher", True, "Part 11 version 7 on the app copy"),
            ("13:00", "teacher", False, "Version 8 of Part 11 is written to `part11_expression_8/`."),
            ("13:30", "teacher", False, "Version 9 of Part 11 is in `part11_expression_9/` (19 files)."),
        ]
        result = match(events)
        first = [item for item in result["open"] if item["started"] == "10:00 today"]
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0]["status"].startswith("stopped: restarted with the same task at 12:35 today"))
        self.assertEqual(finish_at(result, "teacher", "13:00")["match"], "matched")
        self.assertEqual(finish_at(result, "teacher", "13:00")["started"], "12:35 today")
        self.assertEqual(finish_at(result, "teacher", "13:30")["match"], "resumed")

    def test_finish_with_nothing_open_or_named(self) -> None:
        entry = finish_at(match([("11:00", "bookworm", False, "Found 4 sources.")]), "bookworm", "11:00")
        self.assertEqual(entry["match"], "no start logged")

    def test_start_older_than_every_open_session_certainly_stopped(self) -> None:
        result = match([("09:19", "adversary", True, "Review phase 2 run 3 results")])
        self.assertTrue(open_task(result, "Review phase 2 run 3 results")["status"].startswith("stopped: the session"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
