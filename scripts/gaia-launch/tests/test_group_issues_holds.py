"""Holds, body-declared blockers, and ordering in scripts/gaia_group_issues.py."""
import importlib.util
import io
import json
import os
import pathlib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("gaia_group_issues", ROOT / "scripts" / "gaia_group_issues.py")
gg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gg)


def issue(n, labels=(), milestone=None, body=""):
    return {"number": n, "title": f"issue {n}", "body": body,
            "labels": [{"name": l} for l in labels],
            "milestone": {"title": milestone} if milestone else None}


def run(issues):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(gg, "fetch_issues", return_value=issues), \
         mock.patch.object(gg, "BLOCKED_BY", {}), redirect_stdout(out), redirect_stderr(err):
        gg.main()
    batches = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    return [[i["number"] for i in b["issues"]] for b in batches], err.getvalue()


class BodyBlockers(unittest.TestCase):
    def test_parses_current_scope_only(self):
        body = ("### Order and dependencies\n\nBlocked by: #232, #265.\n\n"
                "<details><summary>Original</summary>\nBlocked by: #223.\n</details>")
        self.assertEqual(gg.body_blockers(body), [232, 265])

    def test_bold_and_none(self):
        self.assertEqual(gg.body_blockers("**Blocked by:** #7 and #9"), [7, 9])
        self.assertEqual(gg.body_blockers("Blocked by: none."), [])
        self.assertEqual(gg.body_blockers(None), [])


class Cycles(unittest.TestCase):
    def test_acyclic(self):
        self.assertEqual(gg.dependency_cycles({1: [2], 2: [3], 3: []}), [])

    def test_two_cycle_and_self_free(self):
        self.assertEqual(gg.dependency_cycles({5: [6], 6: [5], 7: [5]}), [[5, 6]])

    def test_blocker_outside_graph_is_ignored(self):
        self.assertEqual(gg.dependency_cycles({1: [99]}), [])


class Queue(unittest.TestCase):
    def test_needs_human_decision_is_held(self):
        batches, err = run([issue(10, ["P1", "needs-human-decision"], "M"), issue(11, ["P1"], "M")])
        self.assertEqual(batches, [[11]])
        self.assertIn("#10", err)

    def test_hold_survives_explicit_selection(self):
        with mock.patch.dict(os.environ, {"GAIA_ONLY_ISSUES": "10"}):
            batches, err = run([issue(10, ["P1", "needs-human-decision"], "M"), issue(11, ["P1"], "M")])
        self.assertEqual(batches, [])
        self.assertIn("#10", err)

    def test_body_blocker_holds_until_closed(self):
        batches, _ = run([issue(20, ["P1"], "M"), issue(21, ["P1"], "M", "Blocked by: #20.")])
        self.assertEqual(batches, [[20]])
        batches, _ = run([issue(21, ["P1"], "M", "Blocked by: #20.")])  # 20 closed
        self.assertEqual(batches, [[21]])

    def test_compute_and_superseded_are_held(self):
        batches, err = run([issue(30, ["P1", "needs-compute"], "M"), issue(31, ["P1", "superseded"], "M"),
                            issue(32, ["P1"], "M")])
        self.assertEqual(batches, [[32]])
        self.assertIn("#30", err)
        self.assertIn("#31", err)

    def test_cycle_is_reported_and_held(self):
        batches, err = run([issue(40, ["P1"], "M", "Blocked by: #42."), issue(41, ["P1"], "M", "Blocked by: #40."),
                            issue(42, ["P1"], "M", "Blocked by: #41."), issue(43, ["P1"], "M")])
        self.assertEqual(batches, [[43]])
        self.assertIn("dependency cycle", err)
        self.assertIn("#40 -> #42 -> #41 -> #40", err)

    def test_cycle_through_unselected_issue_is_still_reported(self):
        with mock.patch.dict(os.environ, {"GAIA_ONLY_ISSUES": "50"}):
            batches, err = run([issue(50, ["P1"], "M", "Blocked by: #51."), issue(51, ["P1"], "M", "Blocked by: #50.")])
        self.assertEqual(batches, [])
        self.assertIn("dependency cycle", err)

    def test_table_is_empty_bodies_are_the_list(self):
        self.assertEqual(gg.BLOCKED_BY, {})

    def test_oldest_first_within_group(self):
        batches, _ = run([issue(175, ["P1"], "M"), issue(172, ["P1"], "M"), issue(173, ["P1"], "M")])
        self.assertEqual(batches, [[172, 173, 175]])


if __name__ == "__main__":
    unittest.main()
