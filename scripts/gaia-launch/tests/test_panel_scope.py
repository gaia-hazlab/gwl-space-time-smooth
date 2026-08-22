#!/usr/bin/env python3
"""
test_panel_scope.py — what the science panel's verdicts are allowed to STOP.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_panel_scope.py
  python3 scripts/gaia-launch/tests/test_panel_scope.py   (also runnable standalone)

The gate's first supervised run (issue #186, 2026-08-20) is the whole motivation. Three
personas reviewed the pre-registered plan; all three returned `revise`; none voted `block`.
The aggregator stopped the batch anyway, because the rule was "any critical concern blocks"
and the panel had raised twelve. Reading them afterwards, one or two would genuinely have
propagated into the rest of the project and the rest were real science that belonged inside
the milestone -- but the gate could not tell those apart, so it escalated all of them and a
human was called mid-batch to re-derive a distinction the reviewers had already made.

So severity (how wrong) and scope (how far it reaches) are now separate fields, and only the
second decides whether work stops. These tests pin that rule, in both directions: it must
relax for an in-milestone concern, and it must NOT relax for anything else -- including the
fail-closed paths, which are the reason the gate is trustworthy at all.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
sys.path.insert(0, GAIA_DIR)

from gaia_panel import (DEFAULT_BLOCK_ON, aggregate, block_on,  # noqa: E402
                        normalise_verdict, render)


def concern(severity="critical", scope=None, claim="something is wrong",
            test="run the thing"):
    c = {"severity": severity, "claim": claim, "decisive_test": test}
    if scope is not None:
        c["scope"] = scope
    return c


def verdict(persona, v="revise", concerns=()):
    return normalise_verdict({"verdict": v, "concerns": list(concerns)}, persona)


class ScopeDecidesWhatStops(unittest.TestCase):

    def test_critical_in_milestone_does_not_stop_the_work(self):
        # The #186 case in miniature: real, critical science, whose correction lives inside
        # this issue. The panel says revise; the gate must not turn that into a stopped batch.
        agg = aggregate([verdict("twin-geostatistician", "revise",
                                 [concern(scope="in-milestone")])])
        self.assertEqual(agg["decision"], "revise")
        self.assertEqual(agg["blocking_concerns"], [])
        self.assertEqual(len(agg["deferred_concerns"]), 1)

    def test_critical_breaking_stops_the_work(self):
        agg = aggregate([verdict("twin-hydrogeologist", "revise", [concern(scope="breaking")])])
        self.assertEqual(agg["decision"], "block")
        self.assertEqual(agg["blocked_by"], ["twin-hydrogeologist"])
        self.assertEqual(len(agg["blocking_concerns"]), 1)

    def test_critical_wrong_physics_stops_the_work(self):
        agg = aggregate([verdict("twin-hydrogeologist", "revise",
                                 [concern(scope="wrong-physics")])])
        self.assertEqual(agg["decision"], "block")

    def test_severity_still_matters_within_a_blocking_scope(self):
        # "breaking" is about reach, not about importance. A major concern that happens to
        # touch an interface is not a reason to stop a batch.
        agg = aggregate([verdict("gaia-auditor", "revise",
                                 [concern(severity="major", scope="breaking")])])
        self.assertEqual(agg["decision"], "revise")
        self.assertEqual(len(agg["deferred_concerns"]), 1)

    def test_minor_concerns_are_neither_blocking_nor_deferred(self):
        # Deferred means "handed to the implementer as a must-address item". A minor concern
        # is on the record; padding that list teaches the implementer to skim it.
        agg = aggregate([verdict("gaia-auditor", "approve",
                                 [concern(severity="minor", scope="in-milestone")])])
        self.assertEqual(agg["decision"], "approve")
        self.assertEqual(agg["deferred_concerns"], [])

    def test_deferred_concerns_downgrade_an_approve_to_revise(self):
        agg = aggregate([verdict("gaia-auditor", "approve",
                                 [concern(severity="major", scope="in-milestone")])])
        self.assertEqual(agg["decision"], "revise")

    def test_a_clean_panel_still_approves(self):
        agg = aggregate([verdict("gaia-auditor", "approve"),
                         verdict("twin-hydrogeologist", "approve")])
        self.assertEqual(agg["decision"], "approve")


class FailingClosedSurvivesTheRelaxation(unittest.TestCase):
    """Every path that used to stop the work for a structural reason must still stop it."""

    def test_an_outright_block_vote_ignores_scope(self):
        # A persona that votes block is exercising judgment, not filing a concern. Scope is
        # about consequences of a claim; there is no claim to scope here.
        agg = aggregate([verdict("gaia-auditor", "block", [concern(scope="in-milestone")])])
        self.assertEqual(agg["decision"], "block")
        self.assertIn("gaia-auditor", agg["blocked_by"])

    def test_a_non_object_verdict_blocks(self):
        agg = aggregate([normalise_verdict("I approve!", "twin-geotech-engineer")])
        self.assertEqual(agg["decision"], "block")

    def test_an_unrecognised_verdict_blocks(self):
        agg = aggregate([normalise_verdict({"verdict": "looks fine"}, "gaia-auditor")])
        self.assertEqual(agg["decision"], "block")

    def test_an_undispatched_persona_still_blocks(self):
        # The queue synthesises exactly this shape when a persona was never dispatched as a
        # subagent -- the base model in costume. It must not become a deferred concern.
        synthetic = {"verdict": "block", "concerns": [
            {"severity": "critical", "claim": "persona was never dispatched as a subagent",
             "decisive_test": "re-run with the plugin installed"}]}
        agg = aggregate([normalise_verdict(synthetic, "twin-hydrogeologist")])
        self.assertEqual(agg["decision"], "block")

    def test_an_undeclared_scope_blocks(self):
        # A panel that ignores the new field behaves exactly like the old gate rather than
        # slipping past it. This is the property that makes the change safe to deploy against
        # personas whose prompt has not been updated yet.
        agg = aggregate([verdict("gaia-auditor", "revise", [concern()])])
        self.assertEqual(agg["decision"], "block")
        self.assertFalse(agg["blocking_concerns"][0]["scope_declared"])

    def test_an_invented_scope_blocks(self):
        agg = aggregate([verdict("gaia-auditor", "revise",
                                 [concern(scope="pretty-important")])])
        self.assertEqual(agg["decision"], "block")

    def test_underscores_are_accepted_for_wrong_physics(self):
        # The one spelling an agent plausibly reaches for; treating it as unrecognised would
        # block correctly but for the wrong reason, and the operator would never know.
        agg = aggregate([verdict("gaia-auditor", "revise",
                                 [concern(scope="wrong_physics")])])
        self.assertEqual(agg["decision"], "block")
        self.assertTrue(agg["blocking_concerns"][0]["scope_declared"])


class TheGateCannotBeClosedByATypo(unittest.TestCase):

    def test_default(self):
        self.assertEqual(block_on({}), DEFAULT_BLOCK_ON)

    def test_narrowing_is_allowed(self):
        self.assertEqual(block_on({"GAIA_PANEL_BLOCK_ON": "breaking"}), ("breaking",))

    def test_an_unrecognised_value_falls_back_rather_than_opening_the_gate(self):
        self.assertEqual(block_on({"GAIA_PANEL_BLOCK_ON": "whatever"}), DEFAULT_BLOCK_ON)
        self.assertEqual(block_on({"GAIA_PANEL_BLOCK_ON": ""}), DEFAULT_BLOCK_ON)

    def test_there_is_no_way_to_block_on_nothing(self):
        # Deliberate. To run without a science gate you set GAIA_SCIENCE_GATE=0, which is
        # visible in the run banner; silently neutering the panel is not an option.
        self.assertTrue(block_on({"GAIA_PANEL_BLOCK_ON": "in-milestone"}))

    def test_the_configured_scopes_are_reported_in_the_aggregate(self):
        agg = aggregate([verdict("gaia-auditor", "approve")], ("breaking",))
        self.assertEqual(agg["block_on"], ["breaking"])


class TheRenderedPanelSaysWhatItDid(unittest.TestCase):
    """The markdown is posted to the issue. It is what a human reads before adjudicating."""

    def test_a_deferred_critical_is_visibly_not_blocking(self):
        md = render(aggregate([verdict("twin-geostatistician", "revise",
                                       [concern(scope="in-milestone", claim="NST tails")])]))
        self.assertIn("0 blocking", md)
        self.assertIn("1 deferred", md)
        self.assertIn("in-milestone", md)

    def test_a_blocking_concern_is_marked_blocking_under_critical_issues(self):
        md = render(aggregate([verdict("twin-hydrogeologist", "revise",
                                       [concern(scope="wrong-physics", claim="sign error")])]))
        self.assertIn("### 3. Critical issues", md)
        self.assertIn("⛔ **BLOCKING**", md)
        self.assertIn("`wrong-physics` — sign error", md)

    def test_the_four_sections_are_always_present_and_ordered(self):
        # A reader arrives with the same four questions every time. They must be answerable
        # from the summary alone, in the same order, whether or not the chair reported.
        md = render(aggregate([verdict("gaia-auditor", "approve")]))
        idx = [md.index(h) for h in ("### 1. Agreements", "### 2. Disagreements",
                                     "### 3. Critical issues", "### 4. Proposed resolution",
                                     "## Individual reviewer reports")]
        self.assertEqual(idx, sorted(idx))

    def test_a_missing_chair_still_answers_all_four(self):
        # The chair is a reporter, not a gate. If it fails, the mechanical answers stand.
        md = render(aggregate([verdict("twin-hydrogeologist", "revise",
                                       [concern(scope="wrong-physics", claim="sign error")])]))
        self.assertIn("A human must decide", md)          # section 4, derived from the decision
        self.assertIn("chair did not report", md)         # section 2, honest about the gap

    def test_a_split_panel_is_announced(self):
        md = render(aggregate([verdict("gaia-auditor", "approve"),
                               verdict("twin-hydrogeologist", "revise",
                                       [concern(severity="major", scope="in-milestone")])]))
        self.assertIn("did not speak with one voice", md)

    def test_two_reviewers_on_the_same_referent_are_surfaced_as_agreement(self):
        md = render(aggregate([
            verdict("gaia-auditor", "revise",
                    [concern(severity="major", scope="in-milestone",
                             claim="Clopper-Pearson predicate is unstated in coverage.py")]),
            verdict("twin-geostatistician", "revise",
                    [concern(severity="major", scope="in-milestone",
                             claim="Clopper-Pearson assumes independent trials")])]))
        self.assertIn("Independently corroborated", md)
        self.assertIn("`Clopper-Pearson`", md)

    def test_one_reviewer_repeating_itself_is_not_agreement(self):
        md = render(aggregate([verdict("gaia-auditor", "revise", [
            concern(severity="major", scope="in-milestone", claim="coverage.py is wrong here"),
            concern(severity="major", scope="in-milestone", claim="coverage.py is wrong there")])]))
        self.assertIn("No two reviewers converged", md)

    def test_the_reviewers_own_words_are_published(self):
        v = normalise_verdict({"verdict": "revise", "report": "The sill is not unity because "
                               "the transform clips its tails.", "concerns": []},
                              "twin-geostatistician")
        md = render(aggregate([v]))
        self.assertIn("Individual reviewer reports", md)
        self.assertIn("the transform clips its tails", md)

    def test_an_undeclared_scope_is_flagged_to_the_reader(self):
        md = render(aggregate([verdict("gaia-auditor", "revise", [concern()])]))
        self.assertIn("scope not declared", md)


class RoundTwoIsAnAdjudication(unittest.TestCase):
    """A panel that starts fresh every round cannot converge — it can resolve nothing, drop
    what it said last time, and object to something else instead, forever. From round 2 each
    persona rules on its own prior concerns, and those rulings are counted."""

    def adjudicate(self, statuses, v="revise", concerns=()):
        return normalise_verdict(
            {"verdict": v, "concerns": list(concerns),
             "prior_concerns": [{"claim": f"c{i}", "status": s, "why": "because"}
                                for i, s in enumerate(statuses)]},
            "twin-geostatistician")

    def test_rulings_are_counted(self):
        agg = aggregate([self.adjudicate(["resolved", "resolved", "unresolved", "withdrawn"])])
        self.assertEqual(agg["prior_adjudicated"],
                         {"resolved": 2, "unresolved": 1, "withdrawn": 1})

    def test_a_round_that_resolves_everything_can_approve(self):
        agg = aggregate([self.adjudicate(["resolved", "withdrawn"], v="approve")])
        self.assertEqual(agg["decision"], "approve")
        self.assertFalse(agg["stalemate"])

    def test_nothing_moved_and_still_blocking_is_a_stalemate(self):
        agg = aggregate([self.adjudicate(["unresolved", "unresolved"],
                                         concerns=[concern(scope="breaking")])])
        self.assertEqual(agg["decision"], "block")
        self.assertTrue(agg["stalemate"])

    def test_progress_is_not_a_stalemate_even_while_still_blocking(self):
        # One concern answered and one still standing is exactly what a working revision cycle
        # looks like. Spending the next round on it is the right call.
        agg = aggregate([self.adjudicate(["resolved", "unresolved"],
                                         concerns=[concern(scope="breaking")])])
        self.assertEqual(agg["decision"], "block")
        self.assertFalse(agg["stalemate"])

    def test_withdrawing_counts_as_movement(self):
        # A panel that can never back down converges by attrition, which is not convergence.
        agg = aggregate([self.adjudicate(["withdrawn", "unresolved"],
                                         concerns=[concern(scope="breaking")])])
        self.assertFalse(agg["stalemate"])

    def test_round_one_is_never_a_stalemate(self):
        agg = aggregate([verdict("gaia-auditor", "revise", [concern(scope="breaking")])])
        self.assertFalse(agg["stalemate"])
        self.assertEqual(sum(agg["prior_adjudicated"].values()), 0)

    def test_an_unrecognised_status_does_not_get_to_claim_resolution(self):
        agg = aggregate([self.adjudicate(["definitely fixed"],
                                         concerns=[concern(scope="breaking")])])
        self.assertEqual(agg["prior_adjudicated"]["unresolved"], 1)
        self.assertTrue(agg["stalemate"])

    def test_the_rulings_are_rendered_for_the_human(self):
        md = render(aggregate([self.adjudicate(["resolved", "unresolved"])]))
        self.assertIn("1 resolved", md)
        self.assertIn("resolved* (prior round)", md)

    def test_a_stalemate_says_so_in_the_markdown(self):
        md = render(aggregate([self.adjudicate(["unresolved"],
                                               concerns=[concern(scope="breaking")])]))
        self.assertIn("stalemate", md)


class TheFirstSupervisedRun(unittest.TestCase):
    """#186's actual shape: unanimous `revise`, twelve criticals, nobody voting block."""

    def build(self, scopes):
        return [verdict("gaia-auditor", "revise", [concern(scope=s) for s in scopes[0]]),
                verdict("twin-hydrogeologist", "revise", [concern(scope=s) for s in scopes[1]]),
                verdict("twin-geostatistician", "revise", [concern(scope=s) for s in scopes[2]])]

    def test_as_it_ran_the_batch_stopped(self):
        agg = aggregate(self.build([[None] * 4, [None] * 2, [None] * 6]))
        self.assertEqual(agg["decision"], "block")
        self.assertEqual(len(agg["blocking_concerns"]), 12)

    def test_with_scope_declared_two_of_twelve_stop_it(self):
        agg = aggregate(self.build([["in-milestone"] * 4,
                                    ["wrong-physics", "in-milestone"],
                                    ["breaking"] + ["in-milestone"] * 5]))
        self.assertEqual(agg["decision"], "block")
        self.assertEqual(len(agg["blocking_concerns"]), 2)
        self.assertEqual(len(agg["deferred_concerns"]), 10)
        self.assertEqual(agg["blocked_by"], ["twin-geostatistician", "twin-hydrogeologist"])

    def test_a_milestone_scoped_panel_lets_the_work_proceed(self):
        agg = aggregate(self.build([["in-milestone"] * 4, ["in-milestone"] * 2,
                                    ["in-milestone"] * 6]))
        self.assertEqual(agg["decision"], "revise")
        self.assertEqual(len(agg["deferred_concerns"]), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
