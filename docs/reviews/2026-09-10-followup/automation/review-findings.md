# Follow-up automation review of Fable's response

**Reviewed:** uncommitted working tree on `509c3c6f6bc7b58f6af0f219943c88e6a9025cd0`, 10 September 2026. Source hashes and interpreter are recorded in `manifest.json`. No implementation, existing audit evidence or GitHub state was modified. The production queue itself was not started.

## Cheap fixes: accept their narrow scope

1. **A2 plan transition is fixed.** `scripts/gaia_run_queue.sh:585` now returns success only for aggregate `approve`. An offline harness extracts the exact `science_gate()` function and uses real `gaia_plan.py`/`gaia_panel.py`, with fake model and GitHub calls. `approve` passes; `revise → approve` takes two plans and injects the first-round concern into the second planning prompt; `revise → revise` returns failure, requests `needs-human-decision`, and records `panel-revise`; `block → approve` still works. Evidence: `science-gate-results.json`, reproducible with `science-gate-harness.py`. This function-level test is stronger than a copied conditional, but it is not a complete runner integration test and does not establish draft/merge/closure safety.

2. **AUTO-06 scheduler label filtering is fixed for the fetched issue snapshot.** `scripts/gaia_group_issues.py:192` skips held issues before grouping and dependency processing; explicit issue selection does not bypass it. All four new unit tests pass. The complete automation suite passes **36 tests**, and `bash -n scripts/gaia_run_queue.sh` passes. CI's `pixi run test` includes this test directory (`pixi.toml:69–73`). No production regression was found in either narrow cheap fix. The added unittest `setUp` does discard a pre-existing `GAIA_ONLY_ISSUES` environment value rather than restoring it; this is a minor test-isolation issue, not a production blocker.

3. **The archived probe needs careful interpretation.** Re-running `automation-main-repros.py` changes only `real_human_blocked_issues_redispatched` to `[]` (see `baseline-comparison.json`). Its `panel_revise_is_nonblock` key still returns `decision=revise`, because that probe invokes the aggregator and never executes the repaired shell transition. Do not call that unchanged key a failed A2 fix, and do not call the whole archived output proof of A2 closure.

4. **The science counterexample is unchanged.** `reproduce_capillary_mass.py` reports root storage gain **0.7392331957817022 mm**, groundwater change **0 mm**, and no external fluxes with capillary rise enabled. Capillary-off residual is `1.4901161138336505e-06 mm` from numerical precision. Evidence: `capillary-working-tree-repros.json`.

## Plan corrections that remain necessary

**Stage 0.2 is currently a proposal, not an operative control.** The changed `docs/gaia-automation.md` still begins “Running the gaia agents unattended,” and lines 32–34 explicitly say “A PR is never left in draft.” The production runner automatically calls `gh pr ready` at line 1493 and `gh pr merge` at line 1676. `GAIA_ONLY_ISSUES` narrows the batch; it is not a draft-only or no-merge mode. Therefore the response's assertion that A2–A6 matter “only when the queue runs unattended” is too strong: a watched invocation still reaches those paths. Advancing science corrections before the larger runner redesign is reasonable only with a demonstrably separate manual workflow or an enforced draft-only/no-merge mode. Stage 0.2's exit evidence must include a fake-GitHub test proving `ready`, merge and issue closure cannot be reached, and deployment evidence that an old scheduler is disabled or cannot merge. A sentence in a document alone is insufficient.

**A2 is not fully closed.** The same exact science-gate harness still permits `approve` with an unresolved `major` concern, malformed concerns, a failed reviewer dispatch followed by wrapper approval, and an identity containing the expected identity as a substring. `gaia_panel.py:146–153` coerces/drops malformed concern content; `:157–172` counts major concerns but does not make them non-approving; `:281` uses substring identity matching. These are existing A2/A5 limitations, not regressions caused by the cheap fix. `schema-probes.json` also confirms omitted concerns, null claim/test values, an unknown severity and an empty panel all aggregate to approval.

**Final acceptance remains inconsistent with its own concerns.** An exact-function harness for `audit_pr_convergence()` confirms three invalid verdicts return success: boolean `converged=true` with nonempty `blocking`; string `converged="true"`; and `converged=true` with missing `blocking`. A proper `converged=false` control blocks. The prompt materializes only diff and code-review comments (`gaia_run_queue.sh:1055–1066`), and the decisive branch tests only the string value of `.converged` (`:1097–1100`). Evidence: `convergence-results.json`, `convergence-harness.py`. Require the expanded Stage 2.1 checklist, not only a couple of boolean guards.

**Snapshot holds are not dispatch-time holds.** The grouper still fetches the issue set once, and the runner consumes it through process substitution (`gaia_run_queue.sh`, final line). A human hold added after the snapshot can be missed by a still-running queue. The code also cannot establish that only a human removes the label; that is a policy assertion. Keep dispatch-time refresh and durable per-issue lifecycle in Stage 2.7; do not mark the whole AUTO-06 finding closed.

**Stage 2.5 needs stronger exit evidence.** An “unseated” log line is useful but insufficient for a mandatory reviewer. The expected behavior is refusal to accept while a required seat is unfilled; the reviewer-cap budget can be revised or the work package narrowed by an authorized decision. Stage 2.1's roster validation and Stage 2.5's routing must share this contract.

**Recovery of #163 must preserve the scientific record.** Retrying the failed persona is reasonable as an isolated review recovery; it does not by itself approve the plan, implement it, or authorize closure. Record the exact plan and source state, existing valid verdicts and concern IDs, retry provenance, and the successfully completed seat's own verdict. An infrastructure retry must not silently discard substantive dissent.

**Do not rewrite historical audit outputs.** The original bundle is evidence about the earlier source state. Save new outputs alongside a new working-tree manifest and comparison, as done here, rather than overwriting the earlier JSON as Stage 0.3/request 1 suggests.

## Evidence files

- `manifest.json`: HEAD, source hashes, UTC recording time and interpreter.
- `automation-working-tree-repros.json`, `baseline-comparison.json`, `capillary-working-tree-repros.json`: both requested archived reruns and exact automation delta.
- `automation-pytest.txt`, `group-issues-tests.txt`: 36 passing automation tests, including four new holds tests.
- `science-gate-harness.py`, `gate-fixture.py`, `science-gate-function.sh`, `science-gate-results.json`: exact gate function, real helper validators and eight offline cases. Per-case subdirectories retain fake prompts and stub calls.
- `convergence-harness.py`, `convergence-function.sh`, `convergence-results.json`: exact final-auditor function and five offline cases.
- `schema-probes.json`: six panel contract counterexamples.
- `panel-contract-checklist.md`: proposed Stage 2.1 acceptance contract.
