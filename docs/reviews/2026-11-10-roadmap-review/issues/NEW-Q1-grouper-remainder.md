# NEW-Q1: GAIA grouper: paused milestones, epic-blocker rejection, and tests on the audited table (remainder of #231)

Milestone: Software. Labels: enhancement, P1.
Split from #231 on 2026-11-11 on the PI's instruction, so that #231 can close on what PR #272 delivers.

## Purpose
PR #272 (branch `gaia/queue-holds-and-blockers`, head `618fea9`) gives the GAIA grouper
(`scripts/gaia_group_issues.py`, the script that turns open issues into agent-queue batches) the
label hold, the body "Blocked by:" lines, the audited dependency table and oldest-first ordering.
Three items of #231's scope are not in that diff, and the table it ships disagrees with the issue
bodies in six places. This issue carries those.

## Deliverable
In `scripts/gaia_group_issues.py` and `scripts/gaia-launch/tests/`:
1. A `PAUSED_MILESTONES` set. An issue in a listed milestone is held and logged to stderr like a
   label hold, including under `GAIA_ONLY_ISSUES`. Initial content: the v0.3 Vs30 milestone, by the
   exact title in `MILESTONE_ORDER`.
2. A check before grouping: a declared blocker (table or body line) that is an open issue labelled
   `epic` stops the run with a non-zero exit and a message naming both issues.
3. The table reconciled with the issue bodies (rows below).
4. Tests that run against the shipped `BLOCKED_BY`, not a table patched to `{}` as in
   `test_group_issues_holds.py:26`.

## Inputs and conventions
- State read 2026-11-11 with `gh issue list`: the five open v0.3 issues (#81, #82, #83, #84, #86)
  and #146 all carry `needs-human-decision`, so the pause holds today through the label alone. A new
  v0.3 issue without the label would be dispatched.
- No open issue names an epic as a blocker today (checked over 226 open bodies and the table with
  `body_blockers`); the check guards against the next one.
- Table at `618fea9` against #231's text and the body lines:

| Issue | #231 text | Table at `618fea9` | Body line, 2026-11-11 |
|---|---|---|---|
| #141 | #143, #144, a decision issue | #260, #270 | #260, #270 |
| #146 | #141 | no entry | #231 (and held by label) |
| #224 | #128, #134, #223 | #223, #128 | #128, #223 |
| #225 | #172 | #172 | #232 |
| #226 | #187, #189, #172 | #187, #189, #100, #172 | #187, #189, #282 |
| #227 | #223, #172 | #223, #232, #234, #263 | #223, #232, #234, #263 |
| #264 (R6c) | #223, #46, #21, #14 | no entry | #9, #21, #223 |

- The grouper takes the union of table and body. #172 is open and labelled `superseded`, so #225
  and #226 stay held by the table after their body blockers close.
- Rule proposed: where an issue body carries a "Blocked by:" line in its current scope, the body
  governs and the table entry is deleted; the table keeps entries only for issues with no such line.

## Acceptance
- Fixture: an unlabelled issue in the v0.3 milestone is absent from the batches and named on stderr;
  the same under `GAIA_ONLY_ISSUES`.
- Fixture: an issue whose body says "Blocked by: #N", with #N open and labelled `epic`, makes
  `main()` exit non-zero; the message contains both numbers.
- Fixture with the shipped table: #224 to #227 are each named on stderr as held while one blocker is
  open, and each is dispatched once all of its body blockers are absent from the open list.
- Every row of the table above is either removed from `BLOCKED_BY` or kept with a one-line comment
  giving the reason; the PR lists which.
- `python -m unittest discover scripts/gaia-launch/tests` passes; the count of tests is stated.

## Hard blockers
Blocked by: #231.

## Advisory
Same file as PR #272, hence the blocker. Checks for a blocker that is a pull request number, a
missing number, or a cycle are item O5 of `docs/soil-twin-operational-plan.md` (present only on
branch `docs/soil-twin-audit-and-plan-revision-2026-09-10`) and are not in this scope.
