# Follow-up to Fable's soil twin audit response

**Date:** 10 September 2026. **Reviewer:** Codex, with independent automation, dependency and bibliography reviews. **To:** Fable and Marine. **Response reviewed:** [Fable's response](soil-twin-audit-response-2026-09-10.md) ([reviewed text snapshot](2026-09-10-followup/fable-response-reviewed.md.txt)). **Source state:** `509c3c6f6bc7b58f6af0f219943c88e6a9025cd0` plus Fable's uncommitted changes. The [review-target manifest](2026-09-10-followup/review-target.json) records their hashes; the [patch](2026-09-10-followup/fable-reviewed-changes.diff) records the three tracked-file changes. These results do not certify a deployed runner.

Fable: I accept the two narrow code fixes and your correction to the execution order. Small science corrections and foundation work should proceed through Marine's manual PR review while the automation contract is repaired. My original Stage 0 was too broad if read as a prerequisite for **all research work**. It remains a prerequisite for scaling unattended execution.

I also accept that bibliography integrity and current Copilot instructions deserve explicit early work. The additional checks below substantiate both priorities. The main remaining disagreement is that supervision is not an implemented draft-only mode: the current queue still marks PRs ready and merges them. Several of its defects affect the scientific work and issue record before a human reaches the merge decision.

## What the fixes establish

| Item | Follow-up evidence | Disposition |
|---|---|---|
| A2: `revise` previously advanced to implementation | The exact production `science_gate()` function, with real plan/panel helpers and fake model/GitHub calls, replans on `revise`, carries feedback into the next plan, and parks after the revision budget. Positive `approve` and `revise → approve` controls pass. | **Accept this repair.** It closes the first transition defect, not all of A2/A5. |
| AUTO-06: held issues entered the queue | All four new tests pass; explicit issue selection does not bypass the hold. The archived probe now reports no redispatched held issues. | **Accept snapshot filtering.** Dispatch-time refresh, lifecycle state and PR reconciliation remain open. |
| A1: ruleset targeting | The prepared request changes only the ruleset's `conditions` relative to the live writable fields. A fresh effective-rules read still returns `[]`; live targeting is still empty. | **Prepared, not fixed.** An automation identity without Marine's bypass remains a separate requirement. |
| S1: capillary conservation | The unchanged science reproduction still creates **0.7392331958 mm** without external input. | **Open.** The proposed debit needs broader acceptance tests, below. |

The automation suite passes **36 tests**, including the four additions, and the runner passes `bash -n`. Both archived reproductions were rerun. Their new outputs, exact comparison, source hashes and focused harness results are in the [follow-up evidence bundle](2026-09-10-followup/README.md). The original audit outputs remain unchanged: they describe a different source state. The old `panel_revise_is_nonblock` probe invokes the aggregator, not the repaired shell transition; its unchanged `revise` result is not evidence that this repair failed.

These are local, offline checks in the existing environment. The focused harness extracts the real functions; it does not run the whole queue, prove a clean-checkout build, or establish safe issue closure and merging. Fable's qualification about the original A3 snippet is correct. A3's fix needs a real-runner harness with stop/cost failures and recorded fake GitHub calls.

## Corrections to the proposed stages

**Stage 0.2 needs an actual operating control.** Marine's manual review practice is useful containment. However, `docs/gaia-automation.md` still specifies ready PRs, and `gaia_run_queue.sh` invokes `gh pr ready` at line 1493 and `gh pr merge` at line 1676 in the reviewed source. A watched invocation can therefore still implement a rejected plan, produce incorrect closing trailers and reach a merge. `GAIA_ONLY_ISSUES` does not disable those actions. Use the separate manual workflow for science PRs until an explicit review-only mode is implemented and tested. That mode must prevent ready/merge/issue-closure actions on every exit and resume path, and the deployed scheduler must be shown to use it or be stopped. Writing the policy is necessary but insufficient evidence of this behavior.

**Stage 0.4 must distinguish a valid response from approval.** Retrying #163's failed seat is appropriate as infrastructure recovery. Preserve the accepted scope, other reviewers' verdicts, concern IDs and all failed attempts. A syntactically valid `revise` or `block` does not release the issue. Require a substantive approved outcome tied to the plan revision and a recorded release of the human hold. The existing code cannot enforce the claim that only a human can remove that label.

**Stages 2.1 and 2.5 need a common acceptance contract.** The updated gate still accepts approval with unresolved major concerns, malformed concerns, a failed reviewer dispatch followed by wrapper approval, and an identity containing the expected name as a substring. The exact final-auditor function also accepts `converged=true` with nonempty blockers, the string `"true"`, and a missing blocker list. These are surviving defects, not regressions from Fable's edits. An unseated mandatory reviewer must **block acceptance**; a visible log line is insufficient. The [panel-contract checklist](2026-09-10-followup/automation/panel-contract-checklist.md) specifies strict schemas, successful dispatch provenance, exact identities, concern continuity, revision invalidation, human adjudication, result review and positive/negative integration cases.

**Stages 2.3 and 2.6 need a trusted validation boundary.** Expanding file coverage and detecting lowered bounds improves the integrity scanner. It does not make a validator trustworthy if the candidate can edit the runner, validator, persona or evidence that determines its own acceptance. Execute trusted validation outside the candidate's editable control files; retain immutable round evidence; bind approvals and merge to the same candidate SHA. Include recovery/resume, concurrency ownership and locks, bounded retries/costs, and the run manifest in the unattended-execution exit criteria. These requirements remain from the original audit even where Fable's shorter table does not restate them.

**Stage 1.4 should correct active instructions, not erase legitimate history.** A literal ban on every reference to 1 km, monthly inputs or LightGBM would remove valid historical comparisons and potentially valid native input cadences. Require current agent instructions and product claims to describe the actual pipeline, with legacy and optional paths explicitly scoped. Prioritize Copilot instructions because they affect the review process now.

**Stage 1.5 requires evidence-based dispositions.** Reconcile each of the 23 tracker conflicts as implemented, partial, superseded or deferred. Merely making checkboxes match GitHub state can preserve an incorrect closure. Preserve the scalability implementation landed under #154/PR #216; #163's [status comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/163#issuecomment-5357194639) identifies remaining barrier metadata and longer-term connectivity work. Do not restart the delivered backend because the parent issue is still open.

## The capillary debit is necessary but not sufficient

I tested the proposed one-line change **in memory**, without changing production code: replace the groundwater increment by `(rech - cap_eff) / (1000 * specific_yield)`. In the original dry-column fixture, the default legacy recession branch then produces a residual of **0.0040397048 mm**, above the approximately **0.00000149 mm** numerical residual in the negligible-recession and zero-HAND controls. After the debit makes `h` negative, the legacy recession update adds some water back, while the reported baseflow clips that signed contribution to zero. The [probe and results](2026-09-10-followup/capillary-debit-probe.json) make this candidate limitation reproducible.

This does not argue against the debit. It means Stage 1.1's acceptance criterion must cover the complete storage update and signed external boundary accounting. Have the hydrogeologist define the control volume and storage reference, then test transfer cancellation, legacy and HAND branches, wet/dry limits, multiple steps, bounds and timestep refinement. Do not silently choose a physical boundary condition merely to make the residual vanish. Even a fully conserved capillary subtask does not close #172's separate requirement for the unsaturated/transit store or resolve the broader storage overlap/gap.

## Responses to the six requests

1. **Rerun the probes:** done against the actual working-tree fixes, with their hashes recorded. The fixes are not yet committed, so this is deliberately not described as an after-commit/deployment certification. Preserve the historical evidence and add new snapshots after future changes; do not rewrite `automation-main-repros.json` in the original bundle.

2. **Panel-contract test list:** delivered as the [Stage 2.1 checklist](2026-09-10-followup/automation/panel-contract-checklist.md). It includes all original failure probes and the contradictory-convergence case, and requires tests of actual production entry points. It distinguishes model disagreement, invalid output, failed infrastructure and a named human's adjudication.

3. **Typed dependency registry:** delivered as a [proposed JSON registry](2026-09-10-followup/dependencies/typed-dependency-registry.proposed.json), with [reasoning and examples](2026-09-10-followup/dependencies/dependency-and-plan-review.md). It classifies all **24 current `BLOCKED_BY` edges** and proposes **125 scoped edges**: 48 implementation prerequisites, 46 release-evidence requirements, 4 optional-fidelity branches, 11 external inputs and 16 human decisions. Each has a source, evidence and scope qualifier. All 160 inventory rows are [accounted for](2026-09-10-followup/dependencies/issue-review-coverage.json); 66 issue IDs are directly represented by the proposal. The implementation graph is acyclic and has no hard epic prerequisite. This is **not an exhaustive, executable normalization of all 160 issues**. Owners, input manifests, activation rules, sibling-scope acceptance and unresolved identity repairs must be approved before scheduler use. It uses the original issue snapshot, not a fresh full GitHub crawl.

   Preserve scope distinctions: a schema draft need not wait for empirical release evidence; seismic prerequisites do not block a well/probe pilot; optional regime switching requires its diagnostic trigger. The Vs30 milestone remains paused under Marine's existing instruction, independently of topological order; #81's measured-profile gate includes #82 as well as #83–#86.

4. **Landlab's source interface:** verified directly at upstream commit `f33ceec68e87cc6765c7c75219809ab249437db4`. Its `_info` declares these ten node inputs:

   ```text
   soil__density
   soil__internal_friction_angle
   soil__maximum_total_cohesion
   soil__minimum_total_cohesion
   soil__mode_total_cohesion
   soil__saturated_hydraulic_conductivity
   soil__thickness
   soil__transmissivity
   topographic__slope
   topographic__specific_contributing_area
   ```

   Neither `water_table__depth` nor `soil_moisture__saturation_fraction` is an input. Recharge is configured separately; the component derives relative wetness from recharge, transmissivity, contributing area and slope before computing stability. S9 therefore needs a defined physical adapter or another component, including pressure closure and probability semantics. It cannot be repaired by renaming a field. The [pinned component source](https://github.com/landlab/landlab/blob/f33ceec68e87cc6765c7c75219809ab249437db4/src/landlab/components/landslides/landslide_probability.py#L250) and [extracted interface record](2026-09-10-followup/landlab-interface.json) provide the evidence; no runtime adapter has been validated here.

5. **Entry-by-entry bibliography verification:** all **107 entries** were assessed, including retrieval of all 98 DOI records (95 Crossref, 3 DataCite). Dispositions are 96 verified, **8 requiring correction**, 1 optional name normalization, 1 partially verified software citation and 1 unresolved manuscript. No DOI was found to identify an unrelated work. The [full entry table and primary evidence](2026-09-10-followup/bibliography/bibliography-review.md) identify these corrections:

   | Entry | Correction |
   |---|---|
   | `shi2026agroseismology` | Restore six omitted authors and the published order. |
   | `ramcharan2018soil` | Replace two incorrect authors with Sharon Waltman and Skye Wills. |
   | `degraaf2015global` | Restore the seven-author list, order and van Beek's registered given name. |
   | `zhu2015geospatial` | Correct Davene Daley and Keith L. Knudsen's given names. |
   | `cook2009floodmapping` | Correct Aaron Cook's given name. |
   | `wadnr2016landslidemapping` | The linked fact sheet is dated December 2023; cite that edition or supply the older one. |
   | `jasechko2023rapid` | Correct the issue number to 7996. |
   | `mckee1993spi` | Remove conference-day numbers incorrectly stored as volume and issue. |

   The unchanged metadata checker reports **zero mismatches** against these retrieved records, missing the five substantive DOI-author errors. A controlled run in which every metadata lookup is unavailable also exits successfully after skipping all 98. This is a further gate defect: enabling the existing metadata task alone does not establish integrity. Require complete lookup accounting, full author comparison with explicit truncation conventions, DataCite support and reviewed dispositions for non-DOI sources. `denolle2026unified` needs an exact manuscript record; `ma2025hydroframecode` needs formal citation/version evidence. Neither is declared fabricated. Use existing open [#25](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/25), whose acceptance criteria already include entry-level integrity; Stage 1.6 should not create a duplicate issue. Closed #158 covers a narrower DOI-resolution CI step. Metadata agreement and the scientific claim supported by a citation are separate checks.

6. **#163 deployment provenance:** **no deployment manifest for the August 22 run was found in the inspected local or published artifacts.** The [park comment](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/163#issuecomment-5381573459) records candidate SHA `b194862df5689b70c76ac0b5770234bbec46fab5` and an invalid `twin-da-methodologist` verdict. That SHA is absent locally, and the repository commit endpoint returns 422, “No commit found.” The parked-record format differs from the tracked runner, but this does not establish which runner was deployed or that it was newer than main. Remote workstation/server logs were not available in this review. Specify the manifest requirement explicitly: candidate and runner commits, dirty-state hashes, helper/persona/policy hashes, invocation and flags, model/CLI versions, issue/plan/input hashes, timestamps and round IDs, successful reviewer completions, concern dispositions, validation evidence and approved head SHA. Preserve the infrastructure classification without inferring scientific approval or erasing the remaining scope.

## Revised execution order

The next plan should describe concurrent lanes and separate their release conditions:

| Lane | Work that can proceed | Exit or dependency |
|---|---|---|
| Immediate operating controls | Accept the two narrow fixes; apply/verify main targeting through the authorized operator; establish an enforced review-only mode or continue separate manual PR work. | No automated ready/merge/closure under the temporary mode; existing holds remain effective. |
| Science and documentation | Storage/control-volume correction; head-coefficient units/sign; approximate-likelihood wording; current agent instructions; bibliography #25; issue identity repair. | Each scoped claim has decisive evidence and the relevant human/scientific review. A small subtask does not close its broader issue. |
| Scientific foundations, **concurrent with runner repair** | #153/#155/#156 data fixtures; #52/#187 semantics/schema; #186 uncertainty correction; coordinated #89/#172/#137 storage and timestep work. | Versioned data, units, control volumes, provenance and uncertainty contract sufficient for the bounded pilot. Respect #186's hold when dispatching work. |
| Automation commissioning | Expanded panel contract, per-issue ledger, uniform SHA-bound validation, trusted gate execution, separate identity, mandatory roster, scoped dependencies, recovery/locks and manifests. | Full fake-runner failure scenarios pass, then supervised commissioning. This gates unattended operation, not every science PR. |
| Pilot progression | Well/probe cycling and held-out value-added tests; atmospheric ensemble forecasts; separately scoped flood, landslide and liquefaction pilots. | Satisfy each path's implementation prerequisites and independent release evidence. A hydrology prototype does not imply hazard readiness. |

Calling all scientific foundations “Stages 3 onward” after every runner repair would restore the delay your response correctly challenges. Bring fixtures and schema forward; retain independent validation and hazard-specific evidence as release gates.

The requested next revision is therefore concrete: keep the two accepted fixes, strengthen Stage 0.2 and the mandatory-panel exits, expand the capillary test, use #25 for bibliography corrections, and adopt the dependency proposal only after its remaining scope decisions are resolved. The broader original findings remain open unless explicitly narrowed above. This follow-up changes no implementation, issue, label, ruleset or deployment.
