# Stage 2.1 acceptance checklist: panel and final-auditor contract

Proposed review contract, 10 September 2026. This is the specification for the fix PR, not a statement that the current implementation passes. Run the component cases against production validators, then exercise the production runner in a disposable repository under fake GitHub/model executables. A test that copies the decision logic does not satisfy the integration requirement. No external GitHub writes or paid model calls are needed.

Use one valid baseline fixture: an explicitly declared nonempty mandatory roster, a validated plan with stable acceptance-criterion IDs, successful completion by every exact reviewer identity, approvals tied to that plan hash, and no unresolved critical/major concerns. The baseline permits implementation. After implementation, a complete result-review bundle and fresh approvals tied to the candidate SHA permit final acceptance. Change one condition at a time in negative cases; assert both the rejected state and absence of implementation/ready/merge/closure calls.

## Strict schema and decision consistency

- [ ] Required fields and types are enforced, including schema version; run/work-package/plan identifiers; plan hash and review round; reviewer identity; verdict enum; and a concerns **array**. Reject missing, null, wrong-type, unrecognized enum and unsupported-version values. Do not coerce malformed data into a valid approval.
- [ ] Each concern has a stable ID, allowed severity (`critical`, `major`, `minor`), nonempty claim, affected acceptance criterion, and explicit required evidence/decisive test. Reject non-object concerns, unknown or absent severity, null/non-string/empty claims and missing evidence requests. An inconclusive scientific concern must remain visible; absence of an easy numerical test cannot silently erase it.
- [ ] Empty and malformed rosters, missing mandatory seats, duplicate reviewer identities, unexpected identities, and duplicate verdicts for one seat prevent acceptance. One reviewer cannot fill two independent seats by submitting twice.
- [ ] **Original probe: empty panel.** `aggregate([])` cannot approve; a command-line aggregation with zero verdict files also fails closed. The check uses the required roster, not merely the number of returned files.
- [ ] **Original probe: malformed concerns.** `{verdict: approve, concerns: "critical issue"}` is invalid, not an empty concern set. Parameterize omitted/null/dictionary/list-of-string concern cases as well.
- [ ] **Original probe: unknown severity.** A typo or unsupported severity never becomes `minor`. Surface a contract/infrastructure error, retain its raw evidence, and deny acceptance.
- [ ] A reviewer saying `approve` while listing an unresolved critical/major concern is rejected as inconsistent or yields a non-approving decision. All mandatory reviewers must approve with substantive concerns resolved or explicitly adjudicated in the concern ledger.
- [ ] **Original revise probe.** `revise` cannot dispatch implementation. A revised plan is reviewed anew; `revise → approve` proceeds only after the second valid approval. `revise → revise` exhausts the configured budget, preserves the unresolved concern and parks without implementation. Preserve the passing `approve` control.

## Roster and completed dispatch

- [ ] Bind each mandatory role to its exact canonical persona identity, configuration/version or content hash, model identity, and invocation/task ID. Validate these fields against trusted dispatch records; model-written claims alone do not prove identity.
- [ ] A tool-use request without a successful corresponding completion is not a review. Match tool result to tool-use ID, reject `is_error`, missing result, timeout/crash/truncated output, and background dispatch that never joins.
- [ ] **Original failed-dispatch probe.** A failed auditor call followed by a wrapper-written approval remains invalid. The accepted verdict must originate from the matched successful reviewer result, not the wrapper's final fenced JSON.
- [ ] Exact identity matching rejects `not-gaia:gaia-auditor-imposter`, prefix/suffix variants, another persona's valid result, and completion from another run/plan/round. No substring-based acceptance.
- [ ] Missing specialist seats remain explicitly unfilled and prevent approval. A cost cap cannot silently remove mandatory novelty, impact, hydrogeology, DA or other declared reviewers. Stage 2.5 must satisfy the same invariant; merely printing an “unseated” line is insufficient.
- [ ] Retrying an invalid/missing result retries that seat with the same review context and preserves the failed attempt. It does not replace a dissenting reviewer to obtain approval. Infrastructure failure and scientific disagreement have different durable states and escalation reasons.

## Concern continuity and revision scope

- [ ] Preserve every plan, roster, transcript, verdict and aggregation round in immutable per-round records. A second round must not overwrite the first plan and panel files.
- [ ] Carry unresolved concern IDs forward with author response, evidence links, disposition, reviewer acceptance and any named human adjudication. Dropping, renaming or downgrading a major concern without a recorded resolution cannot produce convergence.
- [ ] Rebuttals are evidence-backed and accepted by the originating reviewer or a named authorized human. A maker's own “resolved” flag is insufficient.
- [ ] Changing the plan, acceptance criteria, required roster or scientifically material implementation invalidates affected approvals. Re-review the affected roles; preserve why any roster or criterion change was authorized. No result is accepted against weaker criteria invented after observing failure.
- [ ] Exhausted revision budgets retain dissent and route a concrete remaining decision to a named human. An invalid JSON result routes to bounded infrastructure retry/repair. Neither path becomes an approval.
- [ ] Declare separate maximum plan-review, result-review and infrastructure-retry rounds. On exhaustion, freeze a human decision packet containing unresolved concern IDs, the competing options, supporting evidence, and the exact requested choice; stop automatic iteration until a named authorized human records a disposition tied to that plan/candidate. Silence or elapsed time cannot authorize resumption, and an adjudicated concern retains its dissent and rationale.

## Final auditor and implementation review

- [ ] Materialize the exact issue bodies/versions, approved plan and acceptance criteria, all panel rounds, concern/disposition table, candidate SHA, code diff, tests/validation evidence, data and execution manifest, scientific limitations, declared-versus-actual costs, and proposed accepted issue/closure set. Assert that each required artifact is supplied in the final-auditor harness, rather than relying on the auditor to discover it in the checkout.
- [ ] The mandatory scientific reviewers evaluate the implemented result, including material Copilot revisions. A plan approval alone is insufficient evidence that the resulting code meets its criteria.
- [ ] Validate the final-auditor schema strictly: `converged` is a JSON boolean; `blocking` is a required array of nonempty concern references/entries; rationale is required; plan/candidate identity must match. Reject the string `"true"`, missing `blocking`, null lists and malformed JSON.
- [ ] **Converged-with-blocking probe.** `{converged: true, blocking: ["unresolved mass residual"], ...}` must block. Successful final acceptance requires boolean `true`, an empty blocking array, valid current scientific approvals, and complete accepted-issue evidence.
- [ ] Verify the final auditor's actual successful dispatch and exact identity using the same contract as the plan panel. An unverified wrapper approval cannot merge.
- [ ] A changed candidate SHA invalidates final approval before publication/merge. The final merge command uses the approved head SHA; the separate Stage 2.3 harness injects a late push and verifies refusal.
- [ ] Reviewers lack filesystem write capability and write credentials; trusted validation executes outside the candidate's editable gate/persona tree. A candidate cannot weaken the validators or manufacture its own trusted completion/evidence records.

## Integration exit evidence

- [ ] The test suite exercises the actual entry points and real shell control flow with fake `gh`, fake model, bounded fixture time, and temporary repository/remote. Record all external-action calls; prove that every invalid/unfinished scenario leaves affected issues open, dispatches no unauthorized implementation, and never readies or merges a PR.
- [ ] An ordinary valid run completes in the harness; the “all paths blocked” implementation is not acceptable. Preserve positive controls for initial approval, revised-plan approval, a genuinely resolved concern, and final acceptance tied to an unchanged SHA.
- [ ] CI runs the suite and publishes concise case results plus fixture and source hashes. The production runner and validators tested must be the same versions proposed for deployment.
