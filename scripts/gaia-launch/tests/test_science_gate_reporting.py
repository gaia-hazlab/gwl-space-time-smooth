#!/usr/bin/env python3
"""
test_science_gate_reporting.py — tests for what the science gate REPORTS about itself.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_science_gate_reporting.py
  python3 scripts/gaia-launch/tests/test_science_gate_reporting.py   (also runnable standalone)

Two failures of self-report motivated all of this, both found in the gate's first
supervised run (issue #186, 2026-08-20):

  1. The planning session was killed by `timeout` at 1205s and the queue reported
     "plan is not valid JSON". Timeout, crash, contract violation and genuine schema
     error all arrived as one message, so diagnosing a wall-clock problem meant reading
     a schema. gaia_plan.from_stream distinguishes them.

  2. The dashboard rendered every agent a Task block had ever NAMED, whether or not it
     did anything. One real run showed twelve agents of which ten were phantoms, and
     `n_agents` in the corpus counted them too -- so the headline "how many agents did
     this take?" was inflated at the source.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
sys.path.insert(0, GAIA_DIR)

from gaia_plan import from_stream                                    # noqa: E402
from gaia_trace import agent_family, display_name, prune_unused      # noqa: E402

VALID_PLAN = {
    "obstruction": "Stage-3 kriging variance is reported in log space.",
    "questions": ["Does back-transforming change the combined sigma?"],
    "approach": "Apply the lognormal back-transform before combining.",
    "artifacts": ["src/models/kriging.py"],
    "expected_files": 2,
    "expected_lines": 60,
    "expected_runtime_min": 5,
    "stopping_conditions": ["variance still negative after the transform"],
    "negative_result_criteria": "If sigma moves <1%, report it and open a narrower issue.",
    "out_of_scope": ["retuning the variogram"],
}


def write_stream(tmp, events):
    path = os.path.join(tmp, "plan.raw.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return path


def reply(text):
    return {"type": "result", "result": text}


def fenced(plan):
    return "Here is the plan.\n\n```json\n" + json.dumps(plan) + "\n```"


def task(subagent_type):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Task", "input": {"subagent_type": subagent_type}}]}}


class PlanFailureModes(unittest.TestCase):
    """Each way planning can fail must be reported as ITSELF, not as bad JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_no_transcript_at_all(self):
        plan, errs, _ = from_stream(os.path.join(self.tmp, "absent.jsonl"))
        self.assertIsNone(plan)
        self.assertIn("no transcript", errs[0])

    def test_empty_transcript_is_not_a_schema_error(self):
        # The exact shape of the first supervised run's failure.
        path = os.path.join(self.tmp, "empty.jsonl")
        open(path, "w").close()
        plan, errs, _ = from_stream(path)
        self.assertIsNone(plan)
        self.assertIn("no transcript", errs[0])
        self.assertNotIn("JSON", errs[0])

    def test_killed_mid_flight_leaves_work_but_no_reply(self):
        path = write_stream(self.tmp, [task("gaia:gaia-study-designer")])
        plan, errs, _ = from_stream(path)
        self.assertIsNone(plan)
        self.assertIn("never produced a final reply", errs[0])

    def test_replied_without_the_contract(self):
        path = write_stream(self.tmp, [reply("I considered it. Here is some prose.")])
        plan, errs, _ = from_stream(path)
        self.assertIsNone(plan)
        self.assertIn("no parseable fenced", errs[0])

    def test_schema_violation_is_reported_per_field(self):
        bad = dict(VALID_PLAN)
        del bad["negative_result_criteria"]
        bad["expected_files"] = "a lot"
        path = write_stream(self.tmp, [reply(fenced(bad))])
        plan, errs, _ = from_stream(path)
        self.assertIsNone(plan)
        joined = " ".join(errs)
        self.assertIn("negative_result_criteria", joined)
        self.assertIn("expected_files", joined)

    def test_valid_plan_survives_a_partial_stream(self):
        # A killed session still leaves everything it wrote. If the plan was emitted
        # before the kill, it is recoverable -- which is the whole reason for reading
        # the stream rather than the process's stdout.
        path = write_stream(self.tmp, [
            task("gaia:gaia-study-designer"), reply(fenced(VALID_PLAN))])
        plan, errs, warns = from_stream(path, expect="gaia:gaia-study-designer")
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])
        self.assertEqual(plan["expected_files"], 2)

    def test_undispatched_persona_warns_but_does_not_block(self):
        # The panel is where this pipeline fails closed; the plan it produced is about
        # to be reviewed on its merits either way. But the operator must be told.
        path = write_stream(self.tmp, [reply(fenced(VALID_PLAN))])
        plan, errs, warns = from_stream(path, expect="gaia:gaia-study-designer")
        self.assertEqual(errs, [])
        self.assertIsNotNone(plan)
        self.assertIn("never dispatched", warns[0])

    def test_last_block_wins_over_a_quoted_example(self):
        text = ("As an example the contract looks like:\n\n```json\n{\"obstruction\": "
                "\"example\"}\n```\n\nAnd here is the real one:\n\n" + fenced(VALID_PLAN))
        path = write_stream(self.tmp, [reply(text)])
        plan, errs, _ = from_stream(path)
        self.assertEqual(errs, [])
        self.assertEqual(plan["obstruction"], VALID_PLAN["obstruction"])


class AgentNaming(unittest.TestCase):
    """A reader must tell a generic gaia persona from one written for THIS twin."""

    def test_families(self):
        self.assertEqual(agent_family("twin-hydrogeologist"), "twin")
        self.assertEqual(agent_family("gaia:gaia-auditor"), "gaia")
        self.assertEqual(agent_family("general-purpose"), "other")
        self.assertEqual(agent_family(None), "session")

    def test_display_names(self):
        self.assertEqual(display_name("gaia:gaia-scientific-coder"), "Gaia · Scientific Coder")
        self.assertEqual(display_name("twin-hydrogeologist"), "Twin · Hydrogeologist")

    def test_domain_shorthand_is_not_title_cased(self):
        # "Da Methodologist" would read as a name, not a discipline.
        self.assertEqual(display_name("twin-da-methodologist"), "Twin · DA Methodologist")

    def test_unknown_agents_are_left_alone(self):
        self.assertEqual(display_name("general-purpose"), "general-purpose")
        self.assertEqual(display_name(None, fallback="subagent"), "subagent")


def agents_fixture(spec):
    """spec: {id: (parent, n_steps)} -> the agents dict shape parse() produces."""
    from collections import OrderedDict
    agents = OrderedDict()
    for aid, (parent, n) in spec.items():
        agents[aid] = {
            "id": aid, "parent": parent, "name": aid, "subagent_type": None,
            "prompt": None, "spawned": [], "depth": 0, "first": 0, "last": 1,
            "steps": [{"kind": "tool_use", "tool": "Bash", "ord": i, "input": {},
                       "is_error": False, "spawns": None} for i in range(n)],
        }
    for aid, (parent, _) in spec.items():
        if parent and parent in agents:
            agents[parent]["spawned"].append(aid)
    return agents


class PruningPhantomAgents(unittest.TestCase):
    """Dispatched-but-inactive agents are not agents; counting them inflates every stat."""

    def test_empty_agents_are_dropped(self):
        agents = agents_fixture({"root": (None, 5), "a": ("root", 3), "b": ("root", 0)})
        pruned, dropped = prune_unused(agents)
        self.assertEqual(dropped, 1)
        self.assertEqual(set(pruned), {"root", "a"})

    def test_root_survives_even_with_no_steps(self):
        agents = agents_fixture({"root": (None, 0)})
        pruned, dropped = prune_unused(agents)
        self.assertEqual(dropped, 0)
        self.assertIn("root", pruned)

    def test_empty_parent_of_a_working_child_is_kept(self):
        # Dropping it would detach the child and break the tree.
        agents = agents_fixture({"root": (None, 1), "mid": ("root", 0), "leaf": ("mid", 4)})
        pruned, dropped = prune_unused(agents)
        self.assertEqual(dropped, 0)
        self.assertEqual(set(pruned), {"root", "mid", "leaf"})

    def test_spawned_lists_lose_the_pruned_ids(self):
        agents = agents_fixture({"root": (None, 1), "ghost": ("root", 0)})
        pruned, _ = prune_unused(agents)
        self.assertEqual(pruned["root"]["spawned"], [])

    def test_nothing_to_prune_returns_the_input_untouched(self):
        agents = agents_fixture({"root": (None, 2), "a": ("root", 1)})
        pruned, dropped = prune_unused(agents)
        self.assertEqual(dropped, 0)
        self.assertIs(pruned, agents)

    def test_an_orphan_that_did_work_is_never_dropped(self):
        # A subagent whose spawning Task block never appeared is still real work.
        agents = agents_fixture({"root": (None, 1)})
        agents["orphan"] = agents_fixture({"orphan": ("missing", 6)})["orphan"]
        pruned, _ = prune_unused(agents)
        self.assertIn("orphan", pruned)


if __name__ == "__main__":
    unittest.main(verbosity=2)
