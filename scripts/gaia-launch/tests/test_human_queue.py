#!/usr/bin/env python3
"""
test_human_queue.py — the escalation path, which is the part that has to work when nobody
is watching.

Usage
  python3 -m pytest scripts/gaia-launch/tests/test_human_queue.py
  python3 scripts/gaia-launch/tests/test_human_queue.py   (also runnable standalone)

The pipeline parks what it may not decide and labels the issue. Everything downstream of that
label — the packet on the issue, the digest, the page — is generated from ONE thing: the park
stamp the queue writes into its own park comment. These pin the contract on both sides of it:
the stamp survives a round trip through a GitHub comment, and every rendering degrades to a
smaller true statement rather than to a wrong one when the stamp is missing.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
GAIA_DIR = os.path.dirname(HERE)
sys.path.insert(0, GAIA_DIR)

from gaia_human_queue import (OVERDUE_DAYS, enrich, html,  # noqa: E402
                              markdown, packet, parse_stamp, stamp_from_comments,
                              waiting_days)

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(**kw):
    base = dict(ts=ago(3), sha="a" * 40, paths=["scripts/x.py"], cause="panel-block",
                decision="block", stalemate=False,
                blocking=[dict(scope="wrong-physics", claim="the interval assumes independence",
                               decisive_test="block bootstrap over well clusters",
                               persona="twin-geostatistician")])
    base.update(kw)
    return base


def row(issue=186, **kw):
    base = dict(issue=issue, title="Out-of-fold coverage validation",
                url=f"https://github.com/o/r/issues/{issue}", updated=ago(1), created=ago(60),
                assignees=[], milestone="Applied math", labels=["needs-human-decision"],
                stamp=stamp())
    base.update(kw)
    return base


class TheStampSurvivesGitHub(unittest.TestCase):
    """It travels as an HTML comment inside a comment body — invisible to a reader, handed
    back verbatim by the API. If this round trip breaks, CI can measure nothing at all."""

    def test_a_stamp_is_read_back_out_of_a_comment(self):
        body = f"⛔ **Parked**\n\n<!-- gaia-park:{json.dumps(stamp())} -->"
        self.assertEqual(parse_stamp(body)["sha"], "a" * 40)

    def test_the_last_stamp_wins(self):
        # A re-park supersedes the park before it: the decision now waiting on a person is the
        # second one, against the second commit.
        body = (f"<!-- gaia-park:{json.dumps(stamp(sha='1' * 40))} -->\n"
                f"<!-- gaia-park:{json.dumps(stamp(sha='2' * 40))} -->")
        self.assertEqual(parse_stamp(body)["sha"], "2" * 40)

    def test_a_malformed_stamp_is_skipped_not_crashed_on(self):
        body = f"<!-- gaia-park:{{not json}} -->\n<!-- gaia-park:{json.dumps(stamp())} -->"
        self.assertEqual(parse_stamp(body)["cause"], "panel-block")

    def test_prose_with_no_stamp_is_simply_empty(self):
        self.assertEqual(parse_stamp("just a person talking about the issue"), {})

    def test_fetch_asks_for_the_limit_and_warns_when_it_is_reached(self):
        import contextlib
        import io
        from unittest import mock

        import gaia_human_queue as hq
        listed = [{"number": n, "title": f"#{n}"} for n in range(3)]
        calls = []

        def fake_gh(args):
            calls.append(args)
            return listed if args[:2] == ["issue", "list"] else {"comments": []}

        for limit, warned in ((10, False), (3, True)):
            calls.clear()
            err = io.StringIO()
            with mock.patch.object(hq, "gh_json", fake_gh), contextlib.redirect_stderr(err):
                rows = hq.fetch("o/r", limit=limit)
            self.assertEqual(len(rows), 3)
            self.assertEqual(calls[0][calls[0].index("--limit") + 1], str(limit))
            self.assertEqual("::warning::" in err.getvalue(), warned)
        self.assertGreaterEqual(hq.FETCH_LIMIT, 1000)

    def test_braces_inside_a_string_value_do_not_truncate_the_stamp(self):
        # Free-text fields can carry code. The match ends only at a brace followed by -->.
        s = dict(stamp(), decisive_test="run f() { return {a: 1}; } and check }")
        body = f"<!-- gaia-park:{json.dumps(s)} -->"
        self.assertEqual(parse_stamp(body), s)

    def test_the_newest_stamped_comment_is_the_one_used(self):
        comments = [{"body": f"<!-- gaia-park:{json.dumps(stamp(cause='panel-stalemate'))} -->"},
                    {"body": "a human replying"},
                    {"body": f"<!-- gaia-park:{json.dumps(stamp(cause='panel-block'))} -->"}]
        self.assertEqual(stamp_from_comments(comments)["cause"], "panel-block")


class HowLongItHasBeenWaiting(unittest.TestCase):

    def test_waiting_is_measured_from_the_park_not_from_the_issue(self):
        # An issue may have existed for months before a panel ever looked at it. What is
        # waiting on a person is the decision, and the decision is as old as the park.
        r = row(stamp=stamp(ts=ago(2)), created=ago(300), updated=ago(200))
        self.assertEqual(waiting_days(r, NOW), 2.0)

    def test_without_a_stamp_it_falls_back_to_the_issue(self):
        r = row(stamp={}, updated=ago(5))
        self.assertEqual(waiting_days(r, NOW), 5.0)

    def test_overdue_is_a_statement_about_the_queue_not_an_sla(self):
        fresh = enrich([row(stamp=stamp(ts=ago(1)))], None, NOW)[0]
        old = enrich([row(stamp=stamp(ts=ago(OVERDUE_DAYS + 5)))], None, NOW)[0]
        self.assertFalse(fresh["overdue"])
        self.assertTrue(old["overdue"])

    def test_what_has_waited_longest_is_read_first(self):
        rows = enrich([row(191, stamp=stamp(ts=ago(1))), row(186, stamp=stamp(ts=ago(30)))],
                      None, NOW)
        self.assertEqual([r["issue"] for r in rows], [186, 191])


class WithoutAStampItSaysSoRatherThanGuessing(unittest.TestCase):
    """An issue labelled by hand has no stamp. Every rendering must stay truthful about that
    — the failure mode to avoid is a page that reports `fresh` because it measured nothing."""

    def test_staleness_is_unknown_not_fresh(self):
        r = enrich([row(stamp={})], None, NOW)[0]
        self.assertEqual(r["staleness"], "unknown")
        self.assertIn("no park stamp", r["reasons"][0])

    def test_a_stamp_with_nothing_in_it_is_a_pipeline_failure(self):
        # The plan never validated — a timeout, or output that never met the contract. That is
        # a different thing from a panel that blocked, and the packet must not imply science.
        md = packet(enrich([row(stamp=stamp(blocking=[]))], None, NOW)[0])
        self.assertIn("pipeline failure", md)

    def test_no_stamp_at_all_is_not_reported_as_a_failure(self):
        # An issue labelled by hand, or parked before stamps existed, failed at nothing.
        md = packet(enrich([row(stamp={})], None, NOW)[0])
        self.assertNotIn("pipeline failure", md)
        self.assertIn("no park stamp", md)

    def test_the_digest_row_keeps_the_two_apart(self):
        self.assertIn("pipeline failure",
                      markdown(enrich([row(stamp=stamp(blocking=[]))], None, NOW), now=NOW))
        self.assertIn("no park stamp",
                      markdown(enrich([row(stamp={})], None, NOW), now=NOW))


class ThePacketIsARequestForADecision(unittest.TestCase):
    """Not a request for an investigation. If the person has to reconstruct the situation
    before they can rule, the interruption cost is the reconstruction."""

    def test_it_says_what_is_being_asked(self):
        md = packet(enrich([row()], None, NOW)[0])
        self.assertIn("rule on the blocking concerns", md)
        self.assertIn("Nothing else in the run is waiting on this", md)

    def test_it_carries_the_decisive_test_verbatim(self):
        md = packet(enrich([row()], None, NOW)[0])
        self.assertIn("block bootstrap over well clusters", md)
        self.assertIn("wrong-physics", md)

    def test_it_says_how_the_label_comes_off(self):
        md = packet(enrich([row()], None, NOW)[0])
        self.assertIn("needs-human-decision", md)

    def test_it_names_the_commit_the_plan_was_judged_against(self):
        md = packet(enrich([row()], None, NOW)[0])
        self.assertIn("aaaaaaaaa", md)
        self.assertIn("scripts/x.py", md)


class TheDigestIsASittingNotAStream(unittest.TestCase):

    def test_an_empty_queue_says_nothing_is_waiting(self):
        md = markdown([], now=NOW)
        self.assertIn("Nothing is waiting on you", md)
        self.assertNotIn("|", md.split("*Rebuilt")[0].replace("`", ""))

    def test_one_decision_reads_as_one_decision(self):
        md = markdown(enrich([row()], None, NOW), now=NOW)
        self.assertIn("1 decision waiting", md)
        self.assertNotIn("1 decisions", md)

    def test_the_overdue_and_stale_piles_are_called_out_separately(self):
        rows = enrich([row(186, stamp=stamp(ts=ago(30))), row(191, stamp=stamp(ts=ago(1)))],
                      None, NOW)
        md = markdown(rows, now=NOW)
        self.assertIn(f"has waited more than {OVERDUE_DAYS} days", md)
        self.assertIn("#186", md)

    def test_it_says_it_is_edited_in_place(self):
        # The digest must not read like a notification, because it deliberately is not one.
        self.assertIn("updated in place", markdown(enrich([row()], None, NOW), now=NOW))


class ThePage(unittest.TestCase):

    def test_it_states_the_scope_of_what_it_lists(self):
        page = html(enrich([row()], None, NOW), now=NOW)
        self.assertIn("only", page)
        self.assertIn("reaches past its own issue", page)

    def test_an_empty_queue_is_not_an_empty_page(self):
        page = html([], now=NOW)
        self.assertIn("Nothing is waiting on you", page)

    def test_issue_text_is_escaped(self):
        page = html(enrich([row(title="<script>alert(1)</script>")], None, NOW), now=NOW)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_both_themes_are_defined_at_token_level(self):
        # The classic unreadable-artifact bug: a colour defined only inside a media query, so
        # the un-stamped default state renders one theme's text on the other theme's ground.
        page = html(enrich([row()], None, NOW), now=NOW)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn('[data-theme="dark"]', page)
        self.assertIn("background:var(--bg)", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
