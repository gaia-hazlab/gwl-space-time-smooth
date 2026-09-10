#!/usr/bin/env python3
"""
test_group_issues.py -- what the batch grouper refuses to dispatch.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_group_issues.py
  python3 scripts/gaia-launch/tests/test_group_issues.py   (also runnable standalone)

Background: the 2026-09-10 audit (docs/reviews/soil-twin-system-audit-2026-09-10.md,
finding AUTO-06) ran the grouper on a snapshot of the live issues and found that #163
and #186, both parked by a science panel under `needs-human-decision`, came out as
work. The queue wrote the label; nothing read it. These tests pin the hold.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPER = os.path.join(os.path.dirname(os.path.dirname(HERE)), "gaia_group_issues.py")


def load_grouper():
    spec = importlib.util.spec_from_file_location("gaia_group_issues", GROUPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def issue(number, labels=(), milestone="Applied math: DA estimator correctness"):
    return {"number": number, "title": f"Issue {number}",
            "milestone": {"title": milestone} if milestone else None,
            "labels": [{"name": name} for name in labels]}


def run_grouper(mod, issues):
    """Return (emitted issue numbers, stderr) for a fixed issue list; no GitHub call."""
    mod.fetch_issues = lambda: issues
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        mod.main()
    emitted = [i["number"] for line in out.getvalue().splitlines()
               for i in json.loads(line)["issues"]]
    return emitted, err.getvalue()


class HoldLabelTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GAIA_ONLY_ISSUES", None)
        self.mod = load_grouper()

    def test_parked_issue_is_held_and_logged(self):
        parked = issue(163, ["P0", "stage-3", self.mod.HOLD_LABEL])
        ready = issue(161, ["P0", "stage-3"])
        emitted, err = run_grouper(self.mod, [parked, ready])
        self.assertEqual(emitted, [161])
        self.assertIn("holding back #163", err)
        self.assertIn(self.mod.HOLD_LABEL, err)

    def test_same_issue_without_label_is_dispatched(self):
        emitted, _ = run_grouper(self.mod, [issue(163, ["P0", "stage-3"])])
        self.assertEqual(emitted, [163])

    def test_hold_beats_explicit_selection(self):
        # GAIA_ONLY_ISSUES narrows the run; it must not override a human hold.
        os.environ["GAIA_ONLY_ISSUES"] = "186"
        try:
            emitted, err = run_grouper(
                self.mod, [issue(186, ["bug", "P0", self.mod.HOLD_LABEL],
                                 milestone="v0.2 — Hydrogeologic realism")])
        finally:
            os.environ.pop("GAIA_ONLY_ISSUES", None)
        self.assertEqual(emitted, [])
        self.assertIn("holding back #186", err)

    def test_epics_still_excluded(self):
        emitted, _ = run_grouper(self.mod, [issue(171, ["epic"]), issue(172, ["P1"])])
        self.assertEqual(emitted, [172])


if __name__ == "__main__":
    unittest.main()
