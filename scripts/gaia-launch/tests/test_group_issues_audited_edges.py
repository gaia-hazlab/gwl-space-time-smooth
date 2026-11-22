"""Audited dependency edges, replayed through scripts/gaia_group_issues.py with mocks only.

Bodies are the verbatim 'Blocked by:' lines of the open issues on 2026-11-22
(docs/reviews/2026-11-22-issue-231-closure/snapshot/open_issues.json), inlined so the test
reads no file and no network. Expected edges are hand-written from two records that predate
this test, never computed with body_blockers. #81 to #86 carry no hold label here, unlike
the live issues, so that their body edges are evaluated.
"""
import importlib.util
import io
import json
import os
import pathlib
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("gaia_group_issues", ROOT / "scripts" / "gaia_group_issues.py")
gg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gg)

GUARD = "Blocked by: none (beyond the queue-guard PR, #231)."
BODY = {
    81: GUARD,
    82: "Blocked by: #81.",
    83: "Blocked by: #81.",
    84: "Blocked by: #81.",
    86: "Blocked by: #81, #84.",
    141: "Blocked by: #260, #270.",
    143: GUARD,
    144: GUARD,
    231: "Blocked by: none.",
    260: "Blocked by: none.",
    270: "Blocked by: #143, #144, #260.",
}

AUDITED = {
    # docs/reviews/2026-10-08-physics-backlog-audit/issues/liquefaction-vs30.md:188
    # "Add BLOCKED_BY entries 82:[81], 83:[81], 84:[81], 86:[81,84], ..."
    82: [81],
    83: [81],
    84: [81],
    86: [81, 84],
    # docs/reviews/2026-11-07-fable-soil-state-review/TRACKER.md:40 (#270: #143, #144, #260)
    270: [143, 144, 260],
    # TRACKER.md:56 (#260: none)
    260: [],
    # TRACKER.md:57 (#141: #260, #270)
    141: [260, 270],
    # The pre-registered plan for this record: the parenthesis of GUARD names #231.
    81: [231],
    143: [231],
    144: [231],
    231: [],
}


def issue(n, labels=("P1",)):
    return {"number": n, "title": f"issue {n}", "body": BODY[n],
            "labels": [{"name": l} for l in labels], "milestone": {"title": "M"}}


def run(numbers, labels=None):
    issues = [issue(n, *((labels[n],) if labels and n in labels else ())) for n in numbers]
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(gg, "fetch_issues", return_value=issues), \
         mock.patch.object(gg, "BLOCKED_BY", {}), mock.patch.dict(os.environ), \
         redirect_stdout(out), redirect_stderr(err):
        os.environ.pop("GAIA_ONLY_ISSUES", None)
        gg.main()
    dispatched = {i["number"] for l in out.getvalue().splitlines() if l.strip()
                  for i in json.loads(l)["issues"]}
    return dispatched, err.getvalue()


class AuditedEdges(unittest.TestCase):
    def assertHeld(self, err, n, blockers):
        reason = ", ".join(f"#{b}" for b in blockers)
        self.assertRegex(err, re.compile(rf"^holding back #{n} \(.*\): blocked by open {reason}$", re.M))

    def test_parsed_edges_match_the_audited_table(self):
        self.assertEqual(sorted(AUDITED), sorted(BODY))
        for n, expected in AUDITED.items():
            self.assertEqual(gg.body_blockers(BODY[n]), expected, f"#{n}")

    def test_vs30_family_is_held_behind_81(self):
        dispatched, err = run([81, 82, 83, 84, 86])
        self.assertEqual(dispatched, {81})
        for n in (82, 83, 84):
            self.assertHeld(err, n, [81])
        self.assertHeld(err, 86, [81, 84])

    def test_82_83_84_dispatch_once_81_is_closed(self):
        dispatched, err = run([82, 83, 84, 86])
        self.assertEqual(dispatched, {82, 83, 84})
        self.assertHeld(err, 86, [84])

    def test_86_needs_both_81_and_84_closed(self):
        dispatched, err = run([81, 86])  # #84 closed, #81 open
        self.assertNotIn(86, dispatched)
        self.assertHeld(err, 86, [81])
        dispatched, err = run([86])
        self.assertEqual(dispatched, {86})
        self.assertNotIn("holding back #86 ", err)

    def test_guard_line_names_231_and_holds_143(self):
        self.assertEqual(gg.body_blockers("Blocked by: none (beyond the queue-guard PR, #231)."), [231])
        dispatched, err = run([141, 143, 144, 231, 260, 270])
        self.assertEqual(dispatched, {231, 260})
        self.assertHeld(err, 143, [231])
        self.assertHeld(err, 144, [231])

    def test_liquefaction_chain_after_231_closes(self):
        # #260 carries needs-human-decision on the live issue; the chain holds with or without it.
        for labels in (None, {260: ("needs-human-decision",)}):
            dispatched, err = run([141, 143, 144, 260, 270], labels)
            self.assertEqual(dispatched, {143, 144} if labels else {143, 144, 260})
            self.assertHeld(err, 270, [143, 144, 260])
            self.assertHeld(err, 141, [260, 270])

    def test_141_is_transitively_behind_143_144_260(self):
        edges = {n: gg.body_blockers(b) for n, b in BODY.items()}
        seen, todo = set(), [141]
        while todo:
            for b in edges.get(todo.pop(), []):
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        self.assertLessEqual({143, 144, 260}, seen)
        self.assertEqual(gg.dependency_cycles(edges), [])


if __name__ == "__main__":
    unittest.main()
