# Issue #231 closure: evidence for the grouper holds

Date 2026-11-22. Written by Claude through the gaia agents, at the PI's request. The plan named
Opus 5.5; the coder session that wrote these files reports its own model as Fable 5.2. Tree at
`025a9bc5ee304e1195bc4d4eb55ba87ecdda17e2`. No GitHub issue, label or PR was changed.

## What was run

| Item | Source | Result |
|---|---|---|
| Open issues | `gh issue list --state open --limit 500 --json number,title,labels,milestone,body`, saved as [`snapshot/open_issues.json`](snapshot/open_issues.json) | 229 rows, below the 500 limit |
| Grouper replay | `main()` of `scripts/gaia_group_issues.py` with `fetch_issues` returning the snapshot, `BLOCKED_BY` as shipped (empty), `GAIA_ONLY_ISSUES` unset | [`grouper_stdout.txt`](grouper_stdout.txt) (16 batches), [`grouper_stderr.txt`](grouper_stderr.txt) (181 lines) |
| Same replay, script at `025a9bc` | pre-fix copy kept outside the repository | stdout identical; stderr 178 lines |
| Second post-fix replay from the saved snapshot | | reproduces both saved files byte for byte |
| `test_group_issues_holds.py` | `pixi run pytest ... -q -p no:cacheprovider` | 14 passed before, 17 after |
| `test_group_issues_audited_edges.py` (new) | same | 7 passed |
| Full suite | `pytest tests/ scripts/gaia-launch/tests/` with `OMP_NUM_THREADS=4` (also OpenBLAS, MKL) | 409 passed, 1 skipped, 2 xfailed in 257 s |

Plain `pixi run test` did not finish. Two attempts were stopped, the second after 38 minutes on
one test in `tests/test_prior_calibration.py` with 185 tests done. The host is shared, with 48
cores and a load average near 115 at the time. With the thread cap the same command line finished.
I read the stall as thread oversubscription, and I have not tested that reading.

The replay driver and the pre-fix script are not in the repository. They sat in
`/tmp/gaia-issue-231/` on the machine that ran this.

## The defect and the fix

The per-issue loop in `main()` skipped issues labelled `epic` before it logged label holds. An
issue carrying both `epic` and a hold label was never dispatched, and it was never named on stderr
either. Acceptance criterion 3 of #231 asks for every `needs-human-decision` issue to be named.

The fix moves the hold check above the epic skip. An epic with a hold label is now named once and
skipped. An epic without one is skipped silently, as before. Nothing else in the script changed.

## Replay result

Three sets come from the one snapshot. A is the open issues labelled `needs-human-decision`. H is
the issue numbers on stderr lines matching `^holding back #(\d+) \(.*\): labelled (.*)$` whose
label list contains `needs-human-decision`. D is the issue numbers in the stdout batches.

| | A | H | D | A ∩ D | A − H |
|---|---|---|---|---|---|
| pre-fix (`025a9bc`) | 38 | 36 | 34 | empty | #204, #228 |
| post-fix | 38 | 38 | 34 | empty | empty |

Both members of A − H before the fix carry the `epic` label, and no other cause of an unnamed
issue appeared. After the fix H equals A. The fix adds three stderr lines and removes none:

```
holding back #228 (R6: hydrothermal alteration as a control on water pathways (edifice and lowland lahar cap)): labelled needs-human-decision
holding back #204 ([epic] Book/twin rewrite — the codex editorial framework (operating loop, unified notation, status boxes, State2Hazard rename)): labelled needs-human-decision
holding back #171 ([epic] Water budget: restore the unsaturated zone; validate the calibration): labelled superseded
```

Across all three hold labels, 52 open issues are held and none is in D.

The 2026-11-10 record saved a stderr after its issues were posted, and that file names 37
`needs-human-decision` issues. The like-for-like number today is the pre-fix 36. #265 and #269 were
named then and are not labelled now, though both are still open; #353 is new. The remaining
difference between 36 and 38 is the two epics.

## Unit tests

Three tests were added to `test_group_issues_holds.py`. An issue with `epic` and
`needs-human-decision` is named exactly once and is in no batch, with a held #100 in the same run
so that a substring match on `#10` would pass wrongly. An epic without a hold label produces no
line. The hold survives `GAIA_ONLY_ISSUES=10`.

Against the script at `025a9bc` the first and third of these fail and the second passes
(2 failed, 22 passed over the two files). The first fails with `Regex didn't match: '^holding back
#10 \(.*\): labelled needs-human-decision$' not found in 'holding back #100 (issue 100): labelled
needs-compute\n'`. The fixed script was then copied back and `git diff` shows the fix in place.

`test_group_issues_audited_edges.py` feeds the grouper the verbatim `Blocked by:` lines of
#81 to #84, #86, #141, #143, #144, #231, #260 and #270. The expected edges are written by hand
from `docs/reviews/2026-10-08-physics-backlog-audit/issues/liquefaction-vs30.md` line 188 and
`docs/reviews/2026-11-07-fable-soil-state-review/TRACKER.md` lines 40, 56 and 57. The edges from
#81, #143 and #144 to #231 have no independent source: they come from the plan for this record.
The fixtures for #81 to #86 carry no hold label, because the live labels would mask the body edges.

## Deviations from the audited table

- **#85 is closed** (2026-10-08). It is not in the snapshot, so no fixture and no test covers it.
- **#81.** The plan expected a line reading "nothing". The live line is
  `Blocked by: none (beyond the queue-guard PR, #231).`, which parses to #231. No open issue has a
  blocker line reading "nothing".
- **#146 → #141 is missing.** The live line on #146 is
  `Blocked by: none (beyond the queue-guard PR, #231).` The label `needs-human-decision` holds #146
  today. If #231 closes and that label is removed, the grouper will dispatch #146 without waiting
  for #141.
- **#142 → #137 is not on a blocker line**, so it is not asserted. The live line is
  `Blocked by: #286, #9.` The body mentions #137 only in the bullet `- Depends on #137 (specific
  yield/held-out validation) and a DTW time series, neither encoded`. #137 is now labelled
  `superseded`, and TRACKER.md line 39 lists #9 and #286.
- **#141.** The audit gave `141:[143,144,<decision issue>]`. The live line is
  `Blocked by: #260, #270.`, matching the tracker. #143 and #144 are reached through #270, and the
  test checks that.
- **Epics with a hold label:** #204 and #228 (`needs-human-decision`), #171 (`superseded`).

## Parser check

This was a single pass over the snapshot, not a test. Of 229 issues, 223 have a line containing
"blocked by" above the first `<details>`. Each of the 223 has exactly one line the parser anchors
on, and none continues onto a following line. 39 parse to no blocker, and all 39 read
`Blocked by: none.` I found no parser miss of the kind the plan describes.

Four things a person should still look at.

- Six issues have no blocker line at all: #52, #72, #157, #197, #274, #296. The last two are epics.
  The other four are dispatched in this replay.
- #336 reads `Blocked by: #187. (Removes #198 from part (a); part (b) keeps it.)` and parses to
  #187 and #198. The parser reads the parenthesis as a blocker. The error holds more, not less, and
  #336 is label-held anyway.
- The same reading of a parenthesis is what makes 58 issues name #231.
- Twelve issues name, in prose near the words "blocked by", a number that is not on their blocker
  line: #30, #186, #189, #191, #198, #231, #241, #242, #243, #255, #327, #350. Most quote a
  previous blocker line in an amendment note. #30, #186 and #198 propose splits whose slices would
  be blocked by other issues (`30b, blocked by #198c/#164/#189`; `blocked by #153`; `198b ...
  blocked by #176 and 198a`). I did not judge whether those belong on the blocker line.

## What remains

Closing #231 is the PI's action. The queue runner appends `Closes #231` to the PR body, which
would close the issue on merge without that action. That conflict is the subject of #353 and is
not handled here. The epic-as-blocker rule and the dependency table belong to #352. Neither script
logic nor any issue body was edited for the deviations above.

Not verified here: the fix against the live `gh` call (the replay uses the saved snapshot), and
any issue opened or relabelled after the snapshot.

## Independent check (debugger)

pending

## Comment for #231

Draft for the PI to post. It has not been posted.

> Evidence for closure is in `docs/reviews/2026-11-22-issue-231-closure/` (written with Claude
> through the gaia agents).
>
> Replay of the 229 open issues of 2026-11-22 through the grouper: 38 issues carry
> `needs-human-decision`, none of the 38 is in a batch, and all 38 are named on stderr. 34 issues
> are dispatched in 16 batches.
>
> One defect was found and fixed. An issue labelled both `epic` and a hold label was skipped
> without being named (#204, #228, and #171 for `superseded`). Stdout is unchanged by the fix.
>
> The body edges 82→81, 83→81, 84→81, 86→81,84, 270→143,144,260 and 141→260,270 are tested against
> the 2026-10-08 audit and the 2026-11-07 tracker.
>
> Open points, not fixed here: #146 no longer names #141; #142 does not name #137; #85 is closed;
> #336's blocker line parses a parenthesis as a blocker. The runner's forced `Closes #231` is #353.
