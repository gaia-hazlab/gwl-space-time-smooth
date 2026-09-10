# Automation audit: authoritative main snapshot and operational evidence

Audit date: 2026-09-10. Authoritative source snapshot: GitHub main at **435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f**, extracted to /tmp/soil-twin-audit/main. All line references below refer to that snapshot unless explicitly marked **local feature branch**. GitHub issue/comment/ruleset snapshots were supplied by the parent audit. No queue runner, bootstrap, model invocation, push, merge, issue comment, or other GitHub mutation was executed.

**Judgment:** the system has substantial implemented safeguards and real scientific panels; it is not ready for unattended backlog execution with merge authority. Several transitions can still ship a partial batch or lose reviewer requirements. The intended human/reviewer convergence process is not consistently enforced by the current implementation. It should operate in supervised, issue-specific, draft-PR mode until the P0 findings below are closed by failure-injection tests and effective GitHub protections.

The source reviewed first was the user's checked-out feature branch. It predates the safeguards now on main. Main has fixed the older unsupported gh-pr-create JSON flags, destructive abandonment, untracked-only change blindness, accidental staging of .gaia-runs logs, and some dirty-tree handling. Those older bugs are **not presented as current-main findings**. They remain a material warning that the current workspace cannot safely be treated as the deployed runner.

## What is implemented and worth preserving

- Three-member routed plan panels, with an independent Gaia auditor always requested, project-specific science personas, validated plan schemas, a bounded block→revise loop, and recorded issue comments: runner lines 449–592; gaia_panel.py 48–172.
- Separate plan, implementation, Copilot, arbitration, and final-auditor calls. Time/turn caps exist; the pipeline captures VCS ref state around implementation and revision calls: runner 71–97, 365–390, 1240–1282, 1589–1602.
- Work preservation via parked branches rather than deletion; dirty-tree and quarantine checks; draft PRs opened as commits land; batch tests before readiness: runner 270–364, 781–827, 1187–1426.
- Gate-integrity heuristics, transcript dashboards, provenance ledger, and a corpus that includes some science-gate failures: runner 421–444, 636–735, 1289–1320.
- Real panel activity: #186 was blocked after scientific objections, and #163 has multiple detailed plans, independent objections, response tracking, and a procedural reviewer failure. These are substantive scientific reviews, not a roster-only design. Examples: https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/186#issuecomment-5362594197 and https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/163#issuecomment-5381573362.

The gaps below concern enforcement, continuity, and provenance of these safeguards.

## Ranked current-main findings

### AUTO-01 — P0: a graceful stop or cost limit can advance a partially completed batch to merge and close unstarted issues

**Evidence:** runner 1145–1148 builds numbers and closing trailers from every planned issue. At 1202–1211 a stop/cost condition breaks only the inner issue loop; it does not set batch_failed. After the loop, 1383–1401 only checks batch_failed and any_committed. If one earlier issue committed, control proceeds to tests and readiness, guarantees every original closing trailer at 1465–1472, and invokes merge at 1670. The draft body already names the whole batch at 1368–1372. A no-op issue also remains in the closing list despite being skipped at 1284–1286.

**Failure case:** batch A/B/C commits A. The human sends TERM, or the configured cost limit is hit before B. The loop stops starting work, but a green test suite and auditor approval can still merge A and automatically close B/C. There is no deterministic completed-issue ledger for the auditor to inspect; it is told the PR resolves all numbers.

**Reproduction:** isolated shell control-flow reproduction in automation-main-repros.py yields: “gate-and-merge reachable; worked: 900; Closes list: 900 901.” This is reachability proof, not a claim that such a merge occurred in production.

**Fix:** explicit per-issue states and completed/verified issue sets. A stop in the middle of a batch must leave a partial draft and exit before ready/merge; alternatively split a new PR whose closing trailers name only independently verified completed issues. A no-op needs an explicit already-satisfied finding with evidence before closure.

**Acceptance test:** inject TERM and cost exhaustion between issues 1 and 2 of a three-issue batch; assert zero calls to ready/merge, issues 2/3 absent from closing trailers, and issue 1's work durably recoverable. Also test no-op and negative-result paths.

### AUTO-02 — P0: a panel's “revise” verdict is treated as approved, and its concerns drop out of the implementation/merge evidence

**Evidence:** gaia_panel.py 156–166 distinguishes approve/revise/block; runner 579 returns success for anything except block. The implementation receives the pre-registered plan at 1250–1258, described as “already reviewed and passed,” but not the panel's concern list. Only outright block feedback is passed to the next planner at 587–590. The final auditor is supplied final.diff and Copilot inline comments at 1049–1060; it is not supplied the issue acceptance criteria, plan-panel findings, decisive tests, reviewer responses, or a plan-versus-result account. The project science panel is never reconvened on the implementation.

**Failure case:** a geostatistician votes revise because the validation folds leak withheld observations. There is no critical finding, so implementation begins on the unrevised plan and may preserve the leakage. Later Copilot says nothing about scientific validation. A generic final auditor can approve without ever seeing the original objection.

**Reproduction:** a panel with auditor approve + geostatistician revise/major yields decision=revise; runner's exact success condition accepts it.

**Fix:** define revise as unfinished review. Bind stable finding IDs, severity/scope, owner, required evidence, response, and reviewer disposition to each issue and revision. Feed that record to implementation, and require responsible science reviewers to assess decisive tests against the final diff/results. Plan-level approval alone is not scientific acceptance of the implementation. Block when mandatory findings have no disposition; deliberate deferral requires an owner and follow-up, and a human where it changes the original acceptance claim.

**Acceptance test:** a revise/major panel cannot dispatch implementation until a revised plan is approved or explicit conditional acceptance carries machine-checked obligations; the final release gate must reject a PR with that obligation unresolved even when all software tests pass.

### AUTO-03 — P0: reviewer independence and final-auditor acceptance are not validated sufficiently

**Evidence:**
- gaia_panel.py 219–232 marks a persona “dispatched” from the existence of an Agent/Task tool-use request. It does not require a successful tool-result or completed reviewer output.
- Lines 204–216 and 279–291 take the wrapper session's last text as the verdict, not a result bound to the requested reviewer. The identity comparison at 281 accepts substring matches.
- aggregate([]) approves (156–166). normalise_verdict silently drops malformed concern entries and downgrades unknown severities to minor (146–153), despite its fail-closed claim.
- Final auditor and collision arbitrator use text-mode outputs and no dispatch verification: runner 894–931 and 1052–1103.
- Final convergence parsing tests only whether .converged prints true at 1091–1094. It never requires .blocking to be an empty array. A contradictory {"converged":true,"blocking":["unit mismatch unresolved"]} passes. String "true" also prints the accepted token.

**Reproduction:** a synthetic stream containing a failed gaia-auditor dispatch followed by the wrapper's approve JSON exits 0 with “dispatched.” Empty panels and malformed-concern approvals also reproduce. A jq probe of a converged=true/nonempty-blocking verdict returns true.

**Fix:** use strict schemas with types, required reviewer roster/quorum, exact canonical identity, successful completion, and verdict attribution to each reviewer result. Require boolean converged=true AND zero unresolved blocking findings. Apply the same verified dispatch/output path to the final auditor and arbitrator. Store raw reviewer outputs as well as the normalized decision. An adapter failure is a blocked infrastructure state, not a scientific vote.

**Acceptance tests:** failed dispatch, background dispatch with no completion, wrapper fabrication, malformed concern list, unknown severity, empty/missing roster, stale reviewer identity, and contradictory convergence JSON must all fail closed.

### AUTO-04 — P0: reviews, checks, and merges are not bound to the exact PR commit, and body-only findings are lost at the final gate

**Evidence:** wait_for_copilot_review (934–956) filters by login and submitted_at, not review.commit_id/current head; missing submitted_at is accepted. The first pass has no “since” filter; later round_since is recorded before revision work (1544). Review/comment requests are unpaginated (944–945, 1550), and comments include all historic inline comments. Copilot review body contributes to the fingerprint (1555–1564) but audit_pr_convergence receives only review_comments (1646), not review_body. Local final.diff is materialized from the local branch (1050); merge operates on GitHub PR state with no --match-head-commit (1670). GitHub checks are watched earlier (1635–1638).

**Failure cases:** an older-commit review finishes after the time filter and is accepted; a body-only objection disappears from the final auditor's inputs; another actor pushes a new head during auditor/drafting time and the merge applies to that newer commit. Default pagination can omit late findings or prevent recognition of a fresh review.

**Fix:** snapshot PR head SHA, issue/plan versions, and check-suite SHA. Require every reviewer decision to name that head; paginate all review data and preserve review bodies plus thread resolution state. Recheck head and required successful checks immediately before merge; use --match-head-commit. Any head change invalidates approvals and restarts relevant gates.

**Acceptance tests:** old-commit review arriving late, missing timestamp, >30 comments/reviews, actionable review body with zero inline comments, and a new push between checks and merge. Each must prevent an unreviewed-head merge.

### AUTO-05 — P0: the revision path bypasses safeguards applied to initial implementation

**Evidence:** initial implementation runs gate integrity and blast-radius checks at 1304–1328 and the full batch gate including Quarto at 1408–1426. Review revisions at 1604–1615 run only test + check-dois, then git add/commit/push; there is no integrity check, radius check, plan re-review, Quarto render, structured measurement, or cost accumulation. Revision errors/timeouts are converted to a warning at 1596. Reaching the round cap at 1569–1571 continues to the final gate; no-diff revision at 1626–1628 also continues. The added final auditor is a meaningful improvement over the old runner, but those paths do not prove Copilot “quiet” as the header claims.

**Failure case:** the second pass loosens a scientific tolerance or changes a rendered equation; the initial integrity/render gate has already run. The revised PR can become green without those safeguards running again.

**Fix:** one candidate-validation function, called on every implementation/revision head and after integration. It must execute integrity from a trusted baseline, relevant science acceptance tests, full software and documentation checks, scope checks, and structured accounting. Nonzero agent exit or exhausted revisions requires explicit parked state, not a path labeled convergence.

**Acceptance test:** introduce a raised tolerance, modified checker, >cap diff, broken Quarto source, and timed-out revision in separate mocked cases. No case may reach final merge until the same complete gates pass on the new head.

### AUTO-06 — P0/P1: human approval is a fallback, not a required gate; “needs-human-decision” is not honored by queue eligibility

**Evidence:** docs/gaia-automation.md 926–928 explicitly says Copilot+auditor substitute for the user's adversarial pass in unattended mode. Runner merges directly at 1670 with no human approval artifact. Science-blocked issues receive needs-human-decision at 582, but gaia_group_issues.py 176–188 excludes only epics and its fixed blocker map; it ignores that label. Existing PRs are skipped solely by a computed branch name (runner 1157–1160). The live snapshot labels both #163 and #186 needs-human-decision, yet the exact main grouper emits both as work.

**Reproduction:** current snapshots produce #163 in batch [198,163,162,161] and #186 in a solo batch. If no corresponding PR is open, the next unattended run can replan them despite the human hold.

**Fix:** reconcile the intended human loop with the automation policy explicitly. Use positive ready-for-agent approval plus hold labels that the scheduler enforces. Require human approval at architecture/acceptance changes and merge/release gates unless a clearly recorded, limited automation policy authorizes that class. An issue on hold must stay held until an authorized transition removes it. Environment flags disabling gates must be recorded and disallowed for production merge.

**Acceptance test:** run the queue preview on actual #163/#186 metadata; both must be held. Removing a hold without the required approval must not make an item runnable.

### AUTO-07 — P1: execution and review wrappers are not actually isolated/read-only, and gate code is mutable by the agent it judges

**Evidence:** GAIA_READONLY_DENY at runner 129 removes Edit/Write/NotebookEdit and named git/gh subcommands but leaves generic Bash available. Calls use --dangerously-skip-permissions. Shell/Python writes are possible without any prohibited Edit/Write tool. VCS assertions cover refs, not file immutability, and are not applied around plan/panel/auditor/drafter calls. Helper programs are executed directly from the editable checkout after the agent edits it, including gaia_gate_integrity.py at 1311. GATE_PATHS excludes runner/helper/persona logic (gaia_gate_integrity.py 39–46). The checker itself can change to return 0.

**Reproduction:** the unmodified main checker reports no finding for a patch that changes its blocking return to unconditional 0. Separately it misses weakening assert coverage > .90 to > .10 because the bare-bound logic only flags increases (160–172).

**Fix:** isolate each candidate in a disposable worktree/container. Keep orchestration/gate code and reviewer persona definitions outside candidate write access, pinned by immutable hash. Give reviewer wrappers an explicit read-tool allowlist; materialize inputs instead of allowing arbitrary Bash. Separate credentials so editing agents cannot publish. Treat changes to test collection, test helpers, workflow enforcement, persona definitions, or the checker as governance changes requiring independent approval. Keep heuristic integrity detection as useful triage, not a security boundary.

**Acceptance tests:** a reviewer trying Python file writes, an implementation changing its own gate, and lower-bound accuracy weakening must be blocked or require approval before being judged.

### AUTO-08 — P1: batch identity is positional and unstable; branch matching does not prevent duplicate or misattributed work

**Evidence:** grouper 217–227 builds branches from truncated milestone slug + tier + chunk index; it does not encode immutable issue IDs. Input ordering follows GitHub issue-list order; closing/adding/selecting issues repacks chunks. Slugs truncate to 40 characters (105–106). Runner only checks open PR by that branch string, then checkout -B (1157–1187).

**Reproduction:** five issues initially put 101 in rest-1. When the first four close, issue 101 moves to rest-0, so an open rest-1 PR is not found. Adding 106 shifts membership while rest-0/rest-1 names remain unchanged, so skipped PRs may cover different issue sets. Two distinct long milestone titles produce exactly the same branch.

**Fix:** deterministic immutable batch ID from sorted issue IDs and issue-contract versions, plus a persistent issue→run→PR lease. Search all open PR issue links/owned run metadata before assigning work, regardless of branch name. Require explicit resume or supersede for parked runs. Do not overwrite an existing branch on name reuse.

**Acceptance tests:** issue addition, closure, milestone rename, GAIA_ONLY_ISSUES selection, long slug collision, and rerunning with an existing PR must never duplicate an issue or skip new work under a mismatched PR.

### AUTO-09 — P1: collision arbitration can claim a human hold while authorizing auto-merge, and API errors look like “no conflict”

**Evidence:** find_conflicting_prs returns success/no output on local-diff or gh-list failure, skips rival fetch failures, lists only default-count open gaia/ PRs, and tests only textual merge conflicts (842–859). arbitrate_collisions treats empty/error results as no conflicts (975–977). The posted message says “A human decides. Neither PR will be auto-merged while this conflict stands” (1012), but verdict A leaves proceed=0, labels only the rival, and allows the current PR into auto-merge (1023–1035). The arbitrator sees PR bodies, not the full issue statements its comment claims, and no verified reviewer dispatch.

**Fix:** distinguish enumeration/fetch failure from no conflict. Make the declared human hold apply to both branches until a recorded decision resolves it, or revise the policy to clearly authorize scoped auto-prioritization. Check dependency/interface conflicts separately from textual collisions; use issue and path ownership during scheduling rather than waiting until both implementations exist.

**Acceptance test:** inject list/fetch failure and A/B/reconcile/escalate verdicts. Posted decisions, labels, scheduler eligibility, and merge permission must agree.

### AUTO-10 — P1: review routing silently omits promised expertise when the panel fills

**Evidence:** gaia_panel.py MAX_PANEL=3 (97); milestone roles fill it first (109–114), then labels, then novelty/impact readers (120–121). add silently refuses later names once full (105–107). Thus the documented rule that a novelty/impact claim “must face” those readers is unenforced. The bug role exists in BY_LABEL but is absent from the label iteration at 115–117.

**Reproduction:** Applied math + uncertainty + explicit novelty/breakthrough claim returns only auditor, DA methodologist, geostatistician; literature/impact reviewers are absent.

**Fix:** distinguish mandatory expertise from optional breadth. Require coverage of scientific interfaces and novelty/impact claims, allow a justified budget override or a staged panel, and report unseated requirements instead of silently truncating. Use per-issue explicit reviewer requirements; a three-person cap is a resource preference, not a correctness invariant.

### AUTO-11 — P1: the measured “run cost” and “outcome” do not cover the full process

**Evidence:** accumulate_cost is called only for the implementation raw transcript (1269), excluding planning/panel loops, revisions, arbitration, final auditor, and drafters. Missing result/partial transcripts default to zero (397–402). Replanning overwrites plan.raw.jsonl and persona.raw.jsonl (498,551), and failed panel calls truncate their raw file to empty (551). write_measurement is reached only after a successful implementation and before commit; implementation timeout/error, no-op, integrity failure, and radius failure have no own measurement (1270–1286,1310–1332). Gate block recording skips missing raw transcripts (424–426). flush_measurements(pass) runs before later review/merge outcomes (1429–1433). A comparison helper exists, but the runner never invokes gaia_plan.py --compare.

**Fix:** immutable run manifest and append-only event ledger for every invocation/state transition; retain all rounds and failed transcripts. Track actual incurred/estimated spend for every call, preserve unknown rather than zero, and report scientific acceptance, software checks, publication, and merge as distinct outcomes. Compare plan outputs and decisive tests to achieved artifacts. A failed review is not implementation failure; a green suite is not issue acceptance.

**Acceptance tests:** cost cap with expensive panel and cheap implementation, timeout before a result event, no-op, integrity failure, reviewer adapter error, and merge failure. Every case must create an attributable record without silently zeroing cost or declaring end-to-end success.

## Additional implementation observations

- Bootstrap installs neither jq nor uv, although runner requires jq and plugin .mcp.json invokes uv. It advertises linux arm64 downloads (gaia_bootstrap.sh 20–23), but pixi's supported platforms omit linux-aarch64. Pin and preflight the actual deployment platform and external CLI/tool versions.
- PID-file check/write is not atomic (runner 142–148); flock exists only in the suggested external invocation. Multiple direct launches can pass the check simultaneously. Lock inside the runner and use isolated worktrees per active batch.
- The runner's queue is a single process-substitution snapshot (1713). Upstream enumeration failure is not captured as a queue failure, blockers aren't refreshed between batches, and metadata is limited to 500 issues. Use explicit validated snapshot loading with pagination and a known-success exit before dispatch.
- BLOCKED_BY is a small hardcoded map (grouper 86–101) rather than a complete graph from issue links/contracts. Do not infer a blocker is satisfied merely because it is absent from a truncated or partial open-issue snapshot.
- Narrative claims are ahead of enforcement in places: head comments still say squash while actual merge is --merge; epic comments report squash (1709); “nothing merges after any failure” is too strong; “readonly physically cannot touch the tree” is false for the wrappers; “every exit measured” excludes several failures; “before every invocation ref check” applies only to implementation/revision.
- Public dashboard rendering is thoughtful and redacts known secrets, but full transcripts need deliberate publication policy and review; automated pattern redaction cannot establish that all local/private material is publishable. This audit did not inspect the full public transcript corpus.

## Version/deployment drift that must be resolved

Three states are visible: the older local feature branch, newer committed main, and issue comments apparently produced by a still-newer panel implementation. For example #163's August 22 comments describe scoped breaking/wrong-physics blockers, deferred in-milestone concerns, per-finding resolution accounting, and round-2 summaries. Main gaia_panel.py has no scope/resolution fields and blocks every critical concern indiscriminately. The live deployment directory and command line were not available. Therefore this report does **not** claim main is the deployed executable.

Record the deployment commit, dirty diff (if any), runner/helper/persona hashes, CLI/model versions, enabled flags, input issue snapshot, and start time in every run. A public comment's mechanism claims must be traceable to the version that produced it. Bring intended runtime fixes into a reviewed commit before another unattended run.

## Proposed operational contract

A small explicit state machine should own publication instead of relying on shell fall-through:

1. Human triage makes an issue/batch ready, with versioned acceptance criteria, blocked-by links, scope, required panel roles, compute/data budget, and named human owner.
2. Scheduler acquires a durable issue lease, validates all dependencies, snapshots metadata, and creates an isolated worktree/run manifest.
3. Planner emits a preregistered approach. Independently completed reviewer reports become a finding ledger. Revise returns to planning; block parks with reason; approve/conditional approve carries explicit obligations.
4. Implementers edit only the candidate. An independent tester runs decisive scientific and software checks from trusted tooling. Every revision repeats applicable checks.
5. The science panel assesses achieved results and closes/rebuts/delegates each finding. Cross-issue interface checks run for the complete batch. Negative results are accepted only if they satisfy that issue's predeclared scientific question; they do not automatically satisfy downstream implementation dependencies.
6. Open/update a draft PR with only completed issue links and a review package: commit SHA, acceptance matrix, reviewer ledger, numerical evidence, provenance, unresolved limitations, and run-cost account.
7. Complete code review and final independent scientific acceptance on the same SHA. Nonconvergence, adapter failure, or unresolved blocker parks for a human; no “no new text” proxy.
8. Human approves the concrete PR and merge/release decision under the agreed policy. Trusted merge service rechecks SHA and required checks, merges exactly that SHA, verifies resulting state/issue closure, and releases the lease.
9. Record failure/stop/resume at any step. Resume the existing run after authorized changes; do not silently start over because a positional batch name changed.

The highest-value acceptance suite is a mocked end-to-end runner state-machine suite, not additional happy-path helper tests. It should inject the failures named under AUTO-01 through AUTO-09, assert the exact allowed/forbidden side effects, and run from outside the candidate checkout. Then conduct one supervised scientific issue and one multi-issue batch with no merge authority, review the evidence package, and only then consider a narrowly scoped unattended policy.

## Reproduction artifacts

- /tmp/soil-twin-audit/automation-main-repros.py — current-main pure-helper tests plus isolated control-flow snippet.
- /tmp/soil-twin-audit/automation-main-repros.json — observed outputs.
- /tmp/soil-twin-audit/automation-repros.py and automation-repros.json — **older local-feature-branch diagnostics only**, retained to show source divergence; do not cite as current-main bugs.

The current-main reproduction uses the installed pixi Python, imports snapshot helper modules, mocks issue retrieval from the captured JSON, and writes only under /tmp. It never runs the queue, its model commands, or GitHub mutations.
