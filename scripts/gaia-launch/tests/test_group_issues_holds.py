"""Holds, body-declared blockers, and ordering in scripts/gaia_group_issues.py."""
import importlib.util
import io
import json
import pathlib
import sys
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


class Queue(unittest.TestCase):
    def test_needs_human_decision_is_held(self):
        batches, err = run([issue(10, ["P1", "needs-human-decision"], "M"), issue(11, ["P1"], "M")])
        self.assertEqual(batches, [[11]])
        self.assertIn("#10", err)

    def test_body_blocker_holds_until_closed(self):
        batches, _ = run([issue(20, ["P1"], "M"), issue(21, ["P1"], "M", "Blocked by: #20.")])
        self.assertEqual(batches, [[20]])
        batches, _ = run([issue(21, ["P1"], "M", "Blocked by: #20.")])  # 20 closed
        self.assertEqual(batches, [[21]])

    def test_oldest_first_within_group(self):
        batches, _ = run([issue(175, ["P1"], "M"), issue(172, ["P1"], "M"), issue(173, ["P1"], "M")])
        self.assertEqual(batches, [[172, 173, 175]])


if __name__ == "__main__":
    unittest.main()
