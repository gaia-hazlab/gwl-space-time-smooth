#!/usr/bin/env python3
"""
test_parked_staleness.py — the price of parking, measured.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_parked_staleness.py
  python3 scripts/gaia-launch/tests/test_parked_staleness.py   (also runnable standalone)

The science gate parks one issue and lets the batch continue. That is the right trade and it
has a cost nothing was watching: the parked issue keeps a plan written against a tree that
keeps moving underneath it. These pin the two properties that make the measurement worth
having — that it is driven by the plan's OWN files rather than by repository activity in
general, and that it never converts an unknown into reassurance.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
sys.path.insert(0, GAIA_DIR)

from gaia_parked import (age_days, latest, measure, plan_paths,  # noqa: E402
                         render, stamp, staleness)

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class WhatCountsAsStale(unittest.TestCase):
    """`touching` dominates on purpose: a hundred commits elsewhere do not make a parked plan
    wrong, and three commits rewriting the two files it names probably do."""

    def test_nothing_moved_is_fresh(self):
        self.assertEqual(staleness(2.0, 0, 0)["verdict"], "fresh")

    def test_activity_that_misses_the_plan_s_files_is_still_fresh(self):
        v = staleness(3.0, 40, 0)
        self.assertEqual(v["verdict"], "fresh")
        self.assertIn("none in this plan's files", v["reasons"][0])

    def test_one_commit_in_the_plan_s_files_is_aging(self):
        self.assertEqual(staleness(1.0, 9, 1)["verdict"], "aging")

    def test_the_plan_s_files_being_rewritten_is_stale(self):
        v = staleness(1.0, 9, 7)
        self.assertEqual(v["verdict"], "stale")
        self.assertIn("rewritten", v["reasons"][0])

    def test_time_alone_is_enough(self):
        # Even with the tree untouched, the brief the plan was written from ages out.
        self.assertEqual(staleness(40.0, 0, 0)["verdict"], "stale")

    def test_the_bounds_are_arguments_not_beliefs(self):
        self.assertEqual(staleness(40.0, 0, 0, max_days=90)["verdict"], "fresh")
        self.assertEqual(staleness(1.0, 9, 7, max_touching=10)["verdict"], "aging")

    def test_an_unmeasurable_park_is_unknown_not_fresh(self):
        # "We cannot tell" and "it is fine" are different answers, and only one is safe to act
        # on. A stamp whose commit is no longer in the tree must give the first.
        self.assertEqual(staleness(None, None, None)["verdict"], "unknown")
        self.assertEqual(staleness(3.0, None, None)["verdict"], "unknown")


class TheStamp(unittest.TestCase):

    def test_only_path_shaped_artifacts_are_kept(self):
        # `artifacts` is free text. A pathspec that matches nothing reports "nothing changed",
        # which is the one wrong answer this measurement must not give.
        paths = plan_paths({"artifacts": ["scripts/interpolate_residuals.py",
                                          "a figure showing the residuals",
                                          "`notebooks/coverage.ipynb`", "", "-v"]})
        self.assertEqual(paths, ["notebooks/coverage.ipynb",
                                 "scripts/interpolate_residuals.py"])

    def test_a_stamp_carries_the_commit_the_plan_was_judged_against(self):
        row = stamp(186, "Coverage", panel={"decision": "block", "blocking_concerns": [
            {"claim": "underpowered"}]}, plan={"artifacts": ["a/b.py"]}, sha="deadbeef",
            ts=ago(3))
        self.assertEqual((row["issue"], row["sha"], row["paths"]), (186, "deadbeef", ["a/b.py"]))
        self.assertEqual(row["blocking"], ["underpowered"])

    def test_the_newest_park_of_an_issue_wins(self):
        rows = [stamp(1, ts=ago(30), sha="old"), stamp(1, ts=ago(2), sha="new")]
        self.assertEqual(latest(rows)[1]["sha"], "new")

    def test_an_issue_that_landed_drops_out(self):
        rows = [stamp(1, ts=ago(30)), dict(event="unparked", issue=1, ts=ago(2))]
        self.assertEqual(latest(rows), {})

    def test_a_park_after_an_unpark_comes_back(self):
        rows = [stamp(1, ts=ago(30)), dict(event="unparked", issue=1, ts=ago(20)),
                stamp(1, ts=ago(2), sha="again")]
        self.assertEqual(latest(rows)[1]["sha"], "again")

    def test_age_is_read_from_the_stamp_and_survives_a_bad_one(self):
        self.assertEqual(age_days(ago(10), NOW), 10.0)
        self.assertIsNone(age_days("last tuesday", NOW))


class AgainstARealRepository(unittest.TestCase):
    """The git half. Offline and hermetic — a throwaway repository built in a temp dir."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not on PATH")            # visible skip, never a silent pass
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("plan_target.py", "x = 1")
        self.write("elsewhere.py", "y = 1")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.d, capture_output=True,
                              text=True).stdout.strip()

    def write(self, name, text):
        with open(os.path.join(self.d, name), "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def commit(self, name, text):
        self.write(name, text)
        self.git("add", "-A")
        self.git("commit", "-qm", f"touch {name}")

    def parked(self, **kw):
        return stamp(186, "Coverage", plan={"artifacts": ["plan_target.py"]},
                     sha=self.base, ts=ago(kw.pop("days", 1)))

    def test_commits_elsewhere_do_not_age_the_plan(self):
        for i in range(6):
            self.commit("elsewhere.py", f"y = {i}")
        m = measure(self.parked(), cwd=self.d, now=NOW)
        self.assertEqual((m["commits"], m["touching"]), (6, 0))
        self.assertEqual(m["verdict"], "fresh")

    def test_commits_in_the_plan_s_own_files_are_what_count(self):
        for i in range(5):
            self.commit("plan_target.py", f"x = {i}")
        m = measure(self.parked(), cwd=self.d, now=NOW)
        self.assertEqual(m["touching"], 5)
        self.assertEqual(m["verdict"], "stale")
        self.assertIn("plan_target.py", m["changed"])

    def test_a_commit_no_longer_in_the_tree_reports_unknown(self):
        m = measure(dict(self.parked(), sha="0" * 40), cwd=self.d, now=NOW)
        self.assertEqual(m["verdict"], "unknown")
        self.assertIsNone(m["commits"])

    def test_the_report_tells_a_person_what_to_do_about_a_stale_one(self):
        for i in range(5):
            self.commit("plan_target.py", f"x = {i}")
        md = render([measure(self.parked(), cwd=self.d, now=NOW)])
        self.assertIn("#186", md)
        self.assertIn("Re-plan rather than resume", md)
        self.assertIn("plan_target.py", md)

    def test_a_fresh_one_is_listed_but_not_lectured_about(self):
        md = render([measure(self.parked(), cwd=self.d, now=NOW)])
        self.assertIn("#186", md)
        self.assertNotIn("Re-plan rather than resume", md)

    def test_nothing_parked_says_so(self):
        self.assertIn("Nothing parked", render([]))

    def test_an_unchecked_issue_state_is_disclosed(self):
        # If `gh` could not be reached, the report must say the list may include issues a human
        # has since closed -- rather than quietly presenting a stale list as current.
        md = render([measure(self.parked(), cwd=self.d, now=NOW)], checked_gh=False)
        self.assertIn("not checked", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
