#!/usr/bin/env python3
"""
test_concerns_ledger.py — the standing record of disagreements two rounds did not settle.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_concerns_ledger.py
  python3 scripts/gaia-launch/tests/test_concerns_ledger.py   (also runnable standalone)

Two review rounds are the whole budget. What survives them splits in two: a concern that
reaches past its own issue parks that issue for a human now, and everything else proceeds --
which used to mean the panel's real science was posted to an issue and then forgotten at the
end of the run, so the next issue over the same ground rediscovered it from scratch.

The ledger is where the second kind goes, and the grouping is its product: read one at a time
these are separate objections, read together they are a handful of problems. The grouping
tests below pin the thing that makes that work -- concerns are grouped by the CODE AND SYMBOLS
they point at, not by wording. Prose overlap was tried first against the real #186 panel and
failed: the best true pair (two personas independently on Clopper-Pearson) scored below a
false one, and shared boilerplate manufactured matches between unrelated concerns.
"""

import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
sys.path.insert(0, GAIA_DIR)

from gaia_concerns import (BLOCKED, DEFERRED, UNRESOLVED, affinity,  # noqa: E402
                           append, cluster, read, referents, render, rows_from_panel)


def panel(blocking=(), deferred=(), priors=()):
    return {
        "decision": "block" if blocking else "revise",
        "blocking_concerns": [dict(persona="twin-hydrogeologist", severity="critical",
                                   scope="wrong-physics", claim=c, decisive_test="t")
                              for c in blocking],
        "deferred_concerns": [dict(persona="twin-geostatistician", severity="major",
                                   scope="in-milestone", claim=c, decisive_test="t")
                              for c in deferred],
        "verdicts": [dict(persona="gaia-auditor", verdict="revise", concerns=[],
                          prior_concerns=[dict(claim=c, status=s, why="w")
                                          for c, s in priors])],
    }


class WhatGetsRecorded(unittest.TestCase):

    def test_each_disposition_is_kept_distinct(self):
        rows = rows_from_panel(panel(blocking=["sign error"], deferred=["CP is anticonservative"],
                                     priors=[("still pooled", "unresolved"),
                                             ("fixed", "resolved")]), 186)
        self.assertEqual(sorted(r["disposition"] for r in rows),
                         [BLOCKED, DEFERRED, UNRESOLVED])

    def test_a_resolved_prior_is_not_recorded(self):
        # The ledger is what is still open. A concern the revision answered is closed, and
        # filing it here would make the record grow with things nobody needs to act on.
        rows = rows_from_panel(panel(priors=[("fixed", "resolved"), ("gone", "withdrawn")]), 186)
        self.assertEqual(rows, [])

    def test_issue_context_travels_with_the_concern(self):
        rows = rows_from_panel(panel(deferred=["x"]), 186, title="Stage-3 sigma units",
                               milestone="Applied math", run_ts="T1", rounds=2)
        self.assertEqual(rows[0]["issue"], 186)
        self.assertEqual(rows[0]["milestone"], "Applied math")
        self.assertEqual(rows[0]["rounds"], 2)

    def test_an_empty_panel_records_nothing(self):
        self.assertEqual(rows_from_panel({}, 186), [])
        self.assertEqual(rows_from_panel(panel(), 186), [])


class TheLedgerAccumulates(unittest.TestCase):

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "concerns.jsonl"

    def test_appends_across_runs_and_reads_back(self):
        append(rows_from_panel(panel(deferred=["a"]), 186), self.path)
        append(rows_from_panel(panel(deferred=["b"]), 187), self.path)
        rows = read(self.path)
        self.assertEqual([r["issue"] for r in rows], [186, 187])

    def test_a_missing_ledger_reads_empty_rather_than_raising(self):
        self.assertEqual(read(self.path.parent / "absent.jsonl"), [])

    def test_a_corrupt_line_is_skipped_not_fatal(self):
        # This is a record, never a gate. A truncated write during a kill must cost one entry,
        # not the ability to read the other two hundred.
        append(rows_from_panel(panel(deferred=["a"]), 186), self.path)
        with self.path.open("a", encoding="utf-8") as f:
            f.write("{not json\n")
        append(rows_from_panel(panel(deferred=["b"]), 187), self.path)
        self.assertEqual(len(read(self.path)), 2)


class GroupedByWhatTheyPointAt(unittest.TestCase):
    """Verbatim claims from the real #186 panel, which is what this was tuned against."""

    CP_AUDITOR = ("The Clopper-Pearson gate predicate is unstated ('CI contains 0.90' rewards "
                  "small n and inverts the plan's intent), CP is anticonservative under "
                  "spatially clustered wells")
    CP_GEOSTAT = ("Clopper-Pearson assumes independent Bernoulli trials, but withheld wells "
                  "are spatially correlated at the variogram range, so the CI the gate is "
                  "built on is too narrow")
    UNIT_SILL = ("The unit-sill remedy 'rescales (zhat, sigma_z)' - but kriging weights are "
                 "invariant to multiplying the variogram by a constant, so zhat must not be "
                 "rescaled")
    CEILING = ("The Phase-3 synthetic truth omits the mechanism that makes a glacial-aquifer "
               "water table non-Gaussian: the table is bounded above by a drainage ceiling")

    def test_referents_are_extracted_not_prose(self):
        r = referents("interpolate_residuals.py:79 sets n_quantiles with MIN_SITES_PER_MONTH "
                      "and Clopper-Pearson under NST")
        self.assertIn("interpolate_residuals.py", r)      # line number dropped on purpose
        self.assertIn("MIN_SITES_PER_MONTH", r)
        self.assertIn("Clopper-Pearson", r)
        self.assertIn("NST", r)
        self.assertNotIn("sets", r)

    def test_the_line_number_is_dropped_so_two_reviewers_still_match(self):
        a = referents("cross_validate.py:55-71 overlaps")
        b = referents("cross_validate.py:131 leaks")
        self.assertTrue(a & b)

    def test_the_pair_prose_similarity_got_wrong(self):
        # The regression that motivated the whole approach: these two ARE the same problem.
        rows = [dict(claim=c) for c in (self.CP_AUDITOR, self.CP_GEOSTAT, self.UNIT_SILL,
                                        self.CEILING)]
        df = Counter()
        for r in rows:
            df.update(referents(r["claim"]))
        n = len(rows)
        together = affinity(self.CP_AUDITOR, self.CP_GEOSTAT, df, n)
        apart = affinity(self.CP_AUDITOR, self.UNIT_SILL, df, n)
        self.assertGreater(together, apart)
        self.assertGreaterEqual(together, 1.0)   # 1.0 is the grouping threshold
        self.assertEqual(apart, 0.0)

    def test_the_score_does_not_change_when_unrelated_concerns_are_added(self):
        # The property textbook IDF lacked: these two are the same problem whether the ledger
        # holds three entries or three hundred, so their score must not depend on the rest.
        pair = (self.CP_AUDITOR, self.CP_GEOSTAT)
        scores = []
        for extra in ([], [self.CEILING], [self.CEILING, self.UNIT_SILL] * 20):
            df = Counter()
            for c in list(pair) + extra:
                df.update(referents(c))
            scores.append(affinity(*pair, df, 2 + len(extra)))
        self.assertEqual(len(set(scores)), 1, f"score drifted with ledger size: {scores}")

    def test_unrelated_concerns_are_not_grouped(self):
        rows = [dict(claim=c, issue=186, persona="p", disposition=DEFERRED, scope="s",
                     decisive_test="", title="", milestone="")
                for c in (self.CP_AUDITOR, self.CEILING)]
        groups, _ = cluster(rows)
        self.assertEqual([len(g) for g in groups], [1, 1])

    def test_related_concerns_group_and_the_reason_is_reported(self):
        rows = [dict(claim=c, issue=186, persona=p, disposition=DEFERRED, scope="s",
                     decisive_test="", title="", milestone="")
                for c, p in ((self.CP_AUDITOR, "gaia-auditor"),
                             (self.CP_GEOSTAT, "twin-geostatistician"),
                             (self.CEILING, "twin-hydrogeologist"))]
        groups, common = cluster(rows)
        self.assertEqual(len(groups[0]), 2)
        self.assertIn("Clopper-Pearson", common[0])

    def test_a_claim_with_no_referents_never_drags_others_in(self):
        # An unreferenced concern is a lone entry, not a magnet that chains groups together.
        rows = [dict(claim=c, issue=186, persona="p", disposition=DEFERRED, scope="s",
                     decisive_test="", title="", milestone="")
                for c in ("this plan is not rigorous enough", "nor is it well motivated",
                          self.CP_AUDITOR)]
        groups, _ = cluster(rows)
        self.assertEqual(sorted(len(g) for g in groups), [1, 1, 1])


class TheRenderedDocument(unittest.TestCase):

    def rows(self, claims):
        return [dict(claim=c, issue=186, persona="gaia-auditor", disposition=DEFERRED,
                     scope="in-milestone", decisive_test="run it", title="Sigma units",
                     milestone="Applied math") for c in claims]

    def test_an_empty_ledger_says_so_plainly(self):
        md = render([])
        self.assertIn("Nothing recorded", md)

    def test_the_counts_are_stated_up_front(self):
        md = render(self.rows(["coverage.py:87 is a tolerance statement"]))
        self.assertIn("**1** concerns across **1** issues", md)
        self.assertIn("1 were deferred", md)

    def test_a_lone_concern_produces_no_grouping_section(self):
        md = render(self.rows(["coverage.py:87 is a tolerance statement"]))
        self.assertNotIn("Converging on the same thing", md)

    def test_grouping_is_shown_before_the_per_issue_listing(self):
        # The whole point is that it is read as a set first. Per-issue is the index, not the
        # document.
        md = render(self.rows([GroupedByWhatTheyPointAt.CP_AUDITOR,
                               GroupedByWhatTheyPointAt.CP_GEOSTAT]))
        self.assertLess(md.index("Converging on the same thing"), md.index("## By issue"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
