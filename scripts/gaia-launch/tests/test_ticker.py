#!/usr/bin/env python3
"""
test_ticker.py — tests for gaia_ticker.py's stateful live reader.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_ticker.py
  python3 scripts/gaia-launch/tests/test_ticker.py     (also runnable standalone)

Fixture: scripts/gaia-launch/tests/fixtures/sample_run.jsonl — a main agent that reads a file,
spawns three subagents (two named via subagent_type, one falling back to
description), edits a file, and reruns tests; one subagent hits a tool
error; the stream ends with an unrecognised event type, a malformed line,
and a truncated final line with no trailing newline.
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "sample_run.jsonl")

sys.path.insert(0, GAIA_DIR)
import gaia_ticker  # noqa: E402
import gaia_trace  # noqa: E402


def run_ticker(fixture_bytes):
    proc = subprocess.run(
        [sys.executable, os.path.join(GAIA_DIR, "gaia_ticker.py")],
        input=fixture_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc


def feed_ticker(ticker, fixture_bytes):
    """Drive a Ticker directly, the same way main() does line by line."""
    for raw in fixture_bytes.splitlines(keepends=True):
        try:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            ev = json.loads(line)
        except Exception:
            continue
        ticker.process(ev)


class TestPassthrough(unittest.TestCase):

    def test_byte_equality(self):
        with open(FIXTURE, "rb") as f:
            fixture_bytes = f.read()
        proc = run_ticker(fixture_bytes)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, fixture_bytes)

    def test_no_traceback_on_malformed_or_truncated_lines(self):
        with open(FIXTURE, "rb") as f:
            fixture_bytes = f.read()
        proc = run_ticker(fixture_bytes)
        self.assertNotIn(b"Traceback", proc.stderr)


class TestNameMappingAndCounts(unittest.TestCase):

    def setUp(self):
        with open(FIXTURE, "rb") as f:
            self.fixture_bytes = f.read()
        self.ticker = gaia_ticker.Ticker(color=False)
        feed_ticker(self.ticker, self.fixture_bytes)

    def test_subagent_type_is_resolved(self):
        self.assertEqual(self.ticker.names["toolu_task_a"], "code-diagnostician")
        self.assertEqual(self.ticker.names["toolu_task_b"], "test-runner")

    def test_missing_subagent_type_falls_back_to_description(self):
        self.assertEqual(self.ticker.names["toolu_task_c"], "double-check the diff")

    def test_no_raw_id_fragments_appear_as_names(self):
        for name in self.ticker.order:
            self.assertNotIn(name, ("toolu_task_a", "toolu_task_b", "toolu_task_c"))

    def test_main_agent_call_count(self):
        # Read, Task x3, Edit, Bash
        self.assertEqual(self.ticker.calls["main"], 6)

    def test_subagent_call_counts(self):
        self.assertEqual(self.ticker.calls["code-diagnostician"], 2)  # Grep, Read
        self.assertEqual(self.ticker.calls["test-runner"], 2)         # Bash x2
        self.assertEqual(self.ticker.calls["double-check the diff"], 1)  # Bash

    def test_tool_error_is_attributed_to_the_right_agent(self):
        self.assertEqual(self.ticker.errors["test-runner"], 1)
        self.assertEqual(self.ticker.errors["main"], 0)
        self.assertEqual(self.ticker.errors["code-diagnostician"], 0)

    def test_summary_rows_total(self):
        rows = self.ticker.summary_rows()
        total_calls = sum(r[1] for r in rows)
        total_errors = sum(r[2] for r in rows)
        self.assertEqual(total_calls, 11)
        self.assertEqual(total_errors, 1)


class TestCountsMatchArchivedTrace(unittest.TestCase):
    """gaia_trace.py --counts, run over the archived raw.jsonl, must agree
    with the table the live ticker ended with."""

    def test_agent_rows_match_ticker_totals(self):
        ticker = gaia_ticker.Ticker(color=False)
        with open(FIXTURE, "rb") as f:
            feed_ticker(ticker, f.read())
        live = {name: (calls, errs) for name, calls, errs, _ in ticker.summary_rows()}

        events, _ = gaia_trace.load(FIXTURE)
        session, agents = gaia_trace.parse(events)
        archived = {name: (calls, errs)
                    for name, calls, errs, _ in gaia_trace.agent_rows(agents)}

        self.assertEqual(live, archived)


class TestParsePlaceholderSubagentMerge(unittest.TestCase):
    """A subagent's own events can arrive before its spawning Task block on a
    reordered/corrupted transcript; parse() then creates a placeholder agent
    to hold them (see the comment at the top of parse()'s loop). Once the
    real Task block is later found, its steps must be kept (not dropped by
    being overwritten with a fresh dict) and it must end up attached to its
    real parent exactly once (not left duplicated under the placeholder's
    guessed parent, "root")."""

    def _event(self, ord_, etype, parent, content):
        return {"_ord": ord_, "type": etype, "parent_tool_use_id": parent,
                "message": {"content": content}}

    def test_steps_survive_and_agent_is_reparented_once(self):
        events = [
            {"_ord": 0, "type": "system", "subtype": "init",
             "session_id": "s", "model": "m"},
            # root spawns an outer subagent
            self._event(1, "assistant", None, [
                {"type": "tool_use", "id": "toolu_outer", "name": "Task",
                 "input": {"subagent_type": "outer-agent"}}]),
            # a not-yet-known agent's own tool call arrives BEFORE its
            # spawning Task block -- triggers the placeholder path
            self._event(2, "assistant", "toolu_late", [
                {"type": "tool_use", "id": "toolu_grep", "name": "Grep",
                 "input": {"pattern": "x"}}]),
            # the outer agent NOW spawns that same id, with its real parent
            self._event(3, "assistant", "toolu_outer", [
                {"type": "tool_use", "id": "toolu_late", "name": "Task",
                 "input": {"subagent_type": "late-bound-agent"}}]),
        ]
        _, agents = gaia_trace.parse(events)

        late = agents["toolu_late"]
        self.assertEqual(len(late["steps"]), 1)  # the Grep step wasn't dropped
        self.assertEqual(late["steps"][0]["tool"], "Grep")
        self.assertEqual(late["name"], "late-bound-agent")
        self.assertEqual(late["parent"], "toolu_outer")
        self.assertIn("toolu_late", agents["toolu_outer"]["spawned"])
        self.assertNotIn("toolu_late", agents["root"]["spawned"])


class TestSecretRedaction(unittest.TestCase):
    """dashboard.html is published to GitHub Pages via gaia_run_queue.sh, so a
    secret embedded anywhere in a transcript -- not just a Bash command --
    must never survive into it (or transcript.md) verbatim."""

    # Shaped to match each pattern in gaia_trace.redact() (right prefix, right
    # length) but filled with an obviously-fake "FAKE" repeat rather than
    # plausible-looking characters -- a realistic-looking synthetic value
    # here previously tripped GitHub's own push-protection secret scanner.
    SECRETS = [
        "sk-ant-" + "FAKE" * 4,
        "ghp_" + "FAKE" * 6,
        "AKIA" + "FAKE" * 4,
        "xoxb-" + "FAKE" * 4,
        "AIza" + "FAKE" * 8 + "FAK",
    ]

    def setUp(self):
        s = self.SECRETS
        events = [
            {"_ord": 0, "type": "system", "subtype": "init",
             "session_id": "s", "model": "m"},
            {"_ord": 1, "type": "assistant", "parent_tool_use_id": None,
             "message": {"content": [
                {"type": "thinking", "thinking": f"the key I found is {s[0]}"},
                {"type": "text", "text": f"I noticed a token {s[1]} while reading"},
                {"type": "tool_use", "id": "t1", "name": "Write",
                 "input": {"file_path": "config.py",
                           "content": f'API_KEY = "{s[0]}"'}},
             ]}},
            {"_ord": 2, "type": "assistant", "parent_tool_use_id": None,
             "message": {"content": [
                {"type": "tool_use", "id": "t2", "name": "Edit",
                 "input": {"file_path": "x.py", "old_string": "k=1",
                           "new_string": f'TOKEN="{s[1]}"'}},
             ]}},
            {"_ord": 3, "type": "assistant", "parent_tool_use_id": None,
             "message": {"content": [
                {"type": "tool_use", "id": "t3", "name": "Bash",
                 "input": {"command": "echo done"}},
             ]}},
            {"_ord": 4, "type": "user", "parent_tool_use_id": None,
             "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t3", "is_error": False,
                 "content": f"output contained {s[2]} and {s[3]}"}]}},
            {"_ord": 5, "type": "result", "num_turns": 3, "total_cost_usd": 0.01,
             "duration_ms": 1000, "is_error": False,
             "result": f"Done. Left the credential {s[4]} in place as requested."},
        ]
        session, agents = gaia_trace.parse(events)
        self.dash = gaia_trace.dashboard(session, agents, "adversarial-test.jsonl")
        self.md = gaia_trace.markdown(session, agents)

    def test_no_secret_survives_into_dashboard_html(self):
        for secret in self.SECRETS:
            self.assertNotIn(secret, self.dash)

    def test_no_secret_survives_into_transcript_md(self):
        for secret in self.SECRETS:
            self.assertNotIn(secret, self.md)

    def test_redaction_actually_ran_rather_than_dropping_content(self):
        # A passing "not in" test could also mean the content vanished
        # entirely -- confirm [REDACTED] markers actually appear in its place.
        self.assertIn("[REDACTED]", self.dash)
        self.assertIn("[REDACTED]", self.md)


if __name__ == "__main__":
    unittest.main()
