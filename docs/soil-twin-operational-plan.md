# Soil twin operational execution plan

**Decision date:** 10 September 2026. **Status:** accepted direction for bounded local work and human-reviewed PRs; automation commissioning remains open. Marine accepted the two narrow fixes and requested implementation to begin. This plan supersedes the execution ordering in [Fable's response](reviews/soil-twin-audit-response-2026-09-10.md), informed by the [system audit](reviews/soil-twin-system-audit-2026-09-10.md) and [follow-up](reviews/soil-twin-audit-followup-2026-09-10.md). It does not supersede scientific acceptance criteria or existing human holds.

## Accepted repairs and operating boundary

The fixes are included at `98d2c36`:

| Accepted repair | Scope of acceptance | Still open |
|---|---|---|
| A2: only `approve` advances from the plan gate | `revise` replans with feedback and parks when its budget is exhausted. | Strict reviewer provenance/schema, concern continuity, result review and final-auditor contract. |
| AUTO-06: filter `needs-human-decision` issues | The grouper respects the hold in its fetched issue snapshot, including explicit selection. | Refresh at dispatch, concurrent label changes, PR reconciliation and authorized hold release. |

The recorded acceptance evidence is 36 passing automation tests, shell syntax validation and the [focused production-function probes](reviews/2026-09-10-followup/README.md). These repairs do not certify the whole runner.

**Begin the local work packages below through separate manual implementation and review. Do not invoke the current queue against live GitHub.** Watching a run does not prevent its ready, merge or incorrect closing actions. Live queue use requires a tested review-only mode and a recorded commissioning decision; unattended operation requires the fuller contract below and a separate decision. Local fake-GitHub/model harnesses may run now.

Main targeting was independently rechecked on 10 September: the effective-rules endpoint lists deletion, non-fast-forward, pull-request, required-status-check and Copilot-review rules, and the ruleset targets `refs/heads/main`. The [fresh read-only record](reviews/2026-09-10-operational-start/github-state.json) preserves this evidence separately from the historical audit. Marine's pull-request bypass remains; remote scheduler state and deployment are unverified. Existing holds remain in force: #163 and #186 are still open and held, and the #81–#86 Vs30 pause is not lifted by this plan.

## One work package, one acceptance record

Use a bounded package within an issue or explicitly named group. Record the scope, exclusions, owner, affected files, issue-body snapshot, acceptance-criterion IDs, input versions, reviewers, resource budget and proposed closure disposition before implementation. Marine's instruction authorizes the local starter packages below; it does not approve every issue's implementation or release. Any material expansion needs a recorded scope decision.

The lifecycle is:

1. **Human-approved scope → plan review.** Independent reviewers receive the same scoped plan and criteria. Declare mandatory roles and exact reviewer identities; assign the implementer separately. Missing mandatory seats block acceptance, even if optional reviewers are available.
2. **Plan review → implementation.** Every mandatory seat must return a valid, completed review and approve the current plan, with major/critical concerns resolved or explicitly adjudicated. An `approve` label cannot override its unresolved concern list.
3. **Implementation → validation and result review.** Run the relevant scientific/software checks; give reviewers the implementation, immutable test evidence, limitations and concern ledger. They assess the result against the original criteria. Copilot feedback is additional evidence; changes made in response require renewed affected reviews.
4. **Result review → bounded convergence.** Carry stable concern IDs, author responses, decisive evidence and reviewer dispositions between rounds. Default maximum: three plan rounds, three result rounds, and two retries per failed infrastructure seat. Declare lower limits and cost/time caps in the package; increasing a limit requires a recorded decision. Exhaustion parks with a concrete decision packet, never an implicit approval.
5. **Convergence → human publication/merge.** Require valid scientific approvals, an independent final audit with no unresolved blockers, and matching plan/candidate identities. Present Marine with the candidate SHA, evidence and exact accepted scope. Human publication and merge remain separate from machine acceptance; silence does not authorize either. Material changes invalidate affected approvals.

Invalid JSON, failed dispatch and timeouts are infrastructure failures: preserve the attempt and retry the affected seat with unchanged context. Scientific dissent requires a response or named human adjudication; do not replace a dissenting reviewer to obtain approval. Reviewers must not edit the candidate or publish. In the current manual workflow that is an assigned role, not a claim of technical isolation; commissioning must enforce read-only review access without publication credentials.

Use a per-issue ledger with `unstarted`, `planned`, `implemented`, `validated`, `accepted` and `parked` states. A partial batch cannot close unstarted or merely implemented issues. Bounded packages use “Refs #N”; `Closes #N` requires evidence for the complete issue or an explicit approved rescope. Preserve remaining criteria on #172 and parent epics.

## Concurrent work lanes

Scientific foundations start alongside automation repair. No scientific package waits for the entire runner redesign merely because it shares a stage number. Each package still needs its own prerequisites and reviewers.

| Package and existing issue mapping | First bounded deliverable | Mandatory review and decisive exit evidence |
|---|---|---|
| **B1 — Bibliography, #25** | First slice: apply exactly the eight documented corrections, preserving citation keys. A later slice repairs lookup accounting. Keep unresolved manuscript/software records unchanged and explicitly unknown. | Bibliography/provenance reviewer and independent scientific reader: every changed entry matches its recorded primary evidence. The full audit inventory accounts for 107 entries; later checker work must prevent unavailable lookups passing as verified. Eight corrected entries do not close #25. Closed #158 does not replace it. |
| **D1 — Current instructions, #204** | Align active agent instructions and product status with the present pipeline; label legacy/optional paths and distinguish calibration from held-out validation. | Scientific lead and repository reviewer: each active claim has code/data evidence or an explicit planned status; legitimate historical 1 km, monthly and LightGBM references retain their scope. Broader book rewrite remains open. |
| **S1 — Storage contract, #172/#89/#137, tracked by #171** | Document control volume, storage reference and signed boundary fluxes; turn the capillary reproduction into a decisive test before choosing the physical repair. | Hydrogeologist and numerical-methods reviewer: capillary transfers cancel; legacy/HAND branches, wet/dry bounds, multiple steps and timestep refinement obey the declared budget. The proposed one-line debit still leaves a 0.00404 mm legacy residual; do not accept it alone. A capillary repair does not complete the vadose/transit-store requirement. |
| **S2 — Operator statements, #198/#165/#162, documented under #204** | Correct coefficient units/sign, pressure convention and drained/undrained scope; describe the per-particle likelihood as approximate. | Rock-physics/hydrogeology and DA reviewers: dimensional table, declared head-perturbation response and explicit theta–saturation mapping agree with the equations. Full seismic integration still requires its scoped #187/#176 prerequisites. |
| **F1 — Reproducible fixtures, #153/#155/#156** | Freeze a small well/probe/forcing fixture and seeded execution contract. | Data/provenance and software/numerical reviewers: manifest includes source/version, units, support, QC, holdouts and checksums; a clean checkout reproduces the bounded run without private caches. Synthetic and observed fixtures are clearly distinguished. |
| **F2 — State contract, #52/#187** | Draft schema for states, parameters, forcing, observations and uncertainty, resolving the two-theta ambiguity. | Hydrogeology, DA and data-contract reviewers: fixture round-trip, units/support conventions and missing-data behavior are explicit. Drafting does not require every empirical calibration; operational uncertainty acceptance still needs the held #186 scope resolved by its owner. |

B1 and D1 are the first implementation slices. S1 begins with its contract/test design; F1 and F2 can proceed concurrently. Establish package ownership to avoid competing edits to shared physics/schema files. Hold-aware preparatory analysis is allowed, but no #186 implementation or claimed hold release is authorized here.

Repair #119–#125 identities and the 23 tracker conflicts as a separate reviewable issue-reconciliation packet before dependent dispatch. Record implemented/partial/superseded/deferred evidence; matching checkboxes alone is insufficient. For #163, preserve the backend delivered under #154/PR #216. Recover the failed reviewer only against a known runner/context; a valid `revise` or `block` is not approval. Retain substantive concerns and the hold until a named human records release.

## Automation commissioning lane

Implement these in small reviewed changes; use the [panel-contract checklist](reviews/2026-09-10-followup/automation/panel-contract-checklist.md) as acceptance criteria, not as a claim of current behavior.

| Package | Required evidence before acceptance |
|---|---|
| **O1 — Review-only boundary and safe stop** | Exercise the real runner with fake GitHub/model executables: approve, revise, exhausted budget, TERM, partial batch and resume. Review-only mode never marks ready, merges or closes issues on any path; closing trailers contain no unaccepted scopes. Preserve positive controls. |
| **O2 — Panel/result contract** | Strict types, nonempty required roster, exact identities and successful completion provenance; unresolved major concerns block; `converged` must be boolean true with an empty required blocker array. Failed or unseated mandatory reviewers block. All checklist negative cases and valid/revised positive controls pass. |
| **O3 — Trusted validation and ownership** | Every candidate/revision runs the same gates outside its editable control tree. Candidate edits cannot weaken trusted runner/helpers/personas/validators or manufacture evidence. Validate actual scope-appropriate tests, integrity and book rendering. Per-work-package locks, atomic ownership, idempotent resume and stop/cost handling prevent competing runs and duplicate actions. |
| **O4 — Provenance and release identity** | Append-only round manifests bind plan, issue/input snapshots, candidate and runner commits, dirty-state/helper/persona/policy hashes, model/CLI versions, invocation, reviewers, concern outcomes, tests and costs. Approval binds the candidate SHA; injected late pushes block merge. Automation credentials have no human bypass. |
| **O5 — Scoped scheduling** | Refresh issue/PR/hold state immediately before dispatch and after each disposition. Validate missing IDs/types, cycles, epic rejection, partial scopes and conditional triggers. Apply the existing Vs30 pause and #163/#186 holds independently of graph order. |

The [typed dependency registry](reviews/2026-09-10-followup/dependencies/typed-dependency-registry.proposed.json) remains a proposal. Approve owner/input manifests, scope mappings and activation rules before converting it into scheduler logic. Distinguish implementation prerequisites, release evidence, optional fidelity, external inputs and human decisions; whole-issue closure is not a universal dependency signal.

Commission review-only mode only after O1, the O2 plan/mandatory-review contract, and the necessary trusted-validation, ledger and recovery controls pass, with explicit inspection of the deployed invocation. Preventing merge alone does not authorize implementation against an invalid review. Full unattended commissioning additionally requires all of O2–O5, effective permissions checks and the complete forced-failure suite, followed by a supervised single-package trial and recorded human decision. No document edit alone establishes those conditions.

## Scientific progression and release

Use F1/F2 and accepted storage/uncertainty contracts to enter the bounded well/probe path: #189 records/operators → #188 cycling → #192 covariance diagnostics → #194 withheld-sensor value added. Keep a hydrology pilot independent of seismic operator completion; separately approve the evidence needed for its uncertainty claims.

Forecast forcing and flood, landslide and liquefaction integrations each need their native support, interface, conservation and independent validation evidence. Landlab's landslide component requires a physical adapter, not a renamed water-table field. Calibration scores, successful schema serialization and a working prototype do not establish hazard readiness. Publish only the specific claims supported by the accepted package evidence.
