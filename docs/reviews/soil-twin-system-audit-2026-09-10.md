# Soil digital twin: scientific roadmap and multi-agent system audit

**Audit date:** 10 September 2026. **Authoritative code:** GitHub `main`, [`435445f`](https://github.com/gaia-hazlab/gwl-space-time-smooth/tree/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f). **Local checkout:** `feat/nisar-soil-moisture-fetcher`, `5e80767`, draft [PR #222](https://github.com/gaia-hazlab/gwl-space-time-smooth/pull/222). The local branch has an older base and lacks important automation fixes already merged into main.

## Decision

**Continue the research, but do not dispatch the full backlog or rely on automatic merging in the current system.** The scientific direction is credible: a common regional state, observations and hazards evaluated at their own support, persistent probabilistic updates, and independently tested downstream value. The issue collection captures much of the difficult science unusually explicitly. The current implementation does not yet enforce that plan reliably.

Three things require attention before scaling agent execution:

1. **Make approval and completion enforceable.** GitHub currently reports no active rules applying to main. The runner accepts `revise` as permission to implement, loses science-panel findings before its final audit, and can close unstarted issues after a partial batch.
2. **Reconcile the executable roadmap.** Its dependency map is incomplete, some foundational work is scheduled late, paused work remains eligible, and milestone/issue/document status disagrees. Issue closure does not reliably mean scientific acceptance.
3. **Establish a small validated hydrologic cycle.** Fix storage accounting and uncertainty semantics, provision reproducible observations and holdouts, and demonstrate a real cycling nowcast before expanding mechanical memory, fine-scale hazards, or the geographical domain.

The audit added review artifacts only. It did not edit code, change GitHub settings/issues, submit reviews, run the autonomous queue, or merge anything.

## Scope and evidence

Three parallel reviews covered the scientific design, issue roadmap, and operational implementation. The primary reviewer checked live repository settings, recent CI and PR review records, source-version differences, and executable counterexamples, then reconciled the reviews.

| Material | Coverage |
|---|---|
| GitHub issues | All 160 issue bodies: 126 open, 34 closed; all 74 repository issue/PR conversation comments retrieved |
| Open work | 12 epic trackers and 114 non-epic tasks; 35 open issues without milestones; all 126 without GitHub assignees |
| Roadmap organization | All 12 milestones; current dependency/grouping code; snapshot-fed queue simulation |
| Pull requests | Metadata for all 62: 59 merged, 2 closed unmerged, 1 open draft; targeted review records for recent science-gate changes |
| Scientific documents | All 15 twin chapter/index sources; README, ROADMAP, probabilistic roadmap, assumptions, limitations, conventions and previous reviews |
| Operations | Current runner, grouping, plan/panel/integrity helpers, project and GAIA personas, CI, bootstrap and August incident postmortem |
| Executable checks | 217 scientific/software tests passed, 5 warnings; 32 automation unittests passed; isolated queue/panel/control-flow probes and a water-conservation counterexample |

The tests ran against the downloaded main snapshot using the existing local Pixi Python environment, not a newly provisioned environment. They do not establish clean-checkout data reproducibility. Recent GitHub CI on main also reports success. No full real-data reanalysis, GPU forecast, independent hazard validation or exhaustive bibliography verification was rerun.

Detailed evidence and the disposition of every issue are in the [science review](2026-09-10-audit/science-review.md), [automation review](2026-09-10-audit/automation-review.md), [roadmap review](2026-09-10-audit/roadmap-review.md), and [160-issue inventory](2026-09-10-audit/issue-inventory.json). The [audit snapshot](2026-09-10-audit/snapshot.json) records the source versions and repository-rule responses. Appendix source line references refer to the audited main snapshot unless explicitly marked local or historical.

## Findings that block dependable autonomous execution

Here **P0** means repair before unattended execution or a scientific release claim; **P1** means resolve before the affected work proceeds. These audit severities are distinct from existing issue labels.

### A1 — P0: The named branch protection does not protect main

The live `protect-main` ruleset has an empty `conditions.ref_name.include` list. More decisively, `GET /repos/gaia-hazlab/gwl-space-time-smooth/rules/branches/main` returned `[]`; the classic branch-protection endpoint returned `404: Branch not protected`. GitHub documents the former as the endpoint returning active rules applicable to that branch. This is direct API evidence, not inference from a ruleset name. See the [ruleset](https://github.com/gaia-hazlab/gwl-space-time-smooth/rules/19355902) and [GitHub API semantics](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch).

The configured but non-applying ruleset also grants a user PR bypass. The runner ultimately invokes `gh pr merge` without a required human approval step. Recent sampled PR review APIs contain Copilot `COMMENTED` records, not formal human approvals; that does not establish whether discussion or approval occurred elsewhere.

**Repair:** explicitly target main, require the relevant test and science-evidence checks, and require a human review for scientific/contract changes. Use a distinct automation identity that cannot bypass those requirements. Confirm the effective-rules endpoint returns the expected rules. A harmless supervised test PR should demonstrate that missing approval, failed checks and a changed commit prevent merging. Do not perform this test by bypassing protection or pushing directly to main.

### A2 — P0: “Revise” currently means “proceed,” and panel concerns disappear

[`gaia_run_queue.sh:579`](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/scripts/gaia_run_queue.sh#L579) returns success for any decision other than `block`, including `revise`. The implementation prompt carries the original plan, not a mandatory concern-resolution record. The final auditor receives the diff and inline Copilot comments, without the issue acceptance criteria, science-panel report, decisive-test results or full review-body feedback. It is consequently not a second pass by the science panel that approved the plan.

**Repair:** require `approve` from every mandatory role after all critical/major concerns are resolved or explicitly adjudicated. Persist concerns under stable IDs with the requested evidence and resolution. Re-run the affected scientific reviewers on the implemented result and any material revision. Give the final auditor the complete evidence bundle, including original acceptance criteria and justified rebuttals. A review cap means “stop and retain unresolved findings,” not “scientific convergence.”

### A3 — P0: Partial batches can close work that never ran

The runner establishes the batch's issue list before execution. A stop or cost ceiling between issues breaks the inner loop without marking the batch failed. If an earlier issue produced a commit, the remaining path can publish closing references for the whole original batch and merge. The independent auditor is not provided the missing issue bodies needed to reliably detect this. See [`:1202`](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/scripts/gaia_run_queue.sh#L1202), `:1465` and `:1670`.

**Repair:** maintain per-issue states and an explicit accepted set. Generate `Closes` references only from accepted work supported by the PR's evidence. A stopped batch remains draft or is reduced to a separately reviewed completed subset. Reproduce stop, cost exhaustion, no-op, partial implementation and panel failure in an isolated fake-GitHub harness; prove unstarted and unaccepted issues stay open.

### A4 — P0: Later edits can bypass checks applied to the first implementation

The initial issue path applies gate-integrity and fixed diff-size checks. The Copilot revision path re-runs tests/DOI checks and commits with `git add -A`, but does not repeat gate-integrity, fixed diff-size checks or Quarto rendering. Declared-versus-actual plan enforcement is absent throughout. It can therefore introduce a weakened test or an unreviewed scientific change after the strongest controls ran. See [`:1604–1615`](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f/scripts/gaia_run_queue.sh#L1604).

**Repair:** use one validation function for every candidate commit, whether initial, revised, rebased or conflict-resolved. Bind all approvals and check results to the same commit SHA and merge with that expected SHA. Changes to scientific semantics invalidate the relevant science reviews; changes to test/runner/gate code require independent governance review.

### A5 — P1: “Independent, read-only, valid reviewer” is not fully verified

The panel checks for an `Agent`/`Task` dispatch request, not successful completion by that exact agent. An isolated transcript with failed dispatch followed by a wrapper-written approval was accepted. Other probes show empty panels and malformed concern content can produce approvals. Unknown severities are downgraded to minor. The final auditor accepts `converged=true` even with a nonempty `blocking` array. These are contract-validation defects, not evidence that every historical review was invalid.

The outer “read-only” process still has generic Bash; denying named editing tools and selected git commands does not establish filesystem immutability. Gate helpers are read from the same checkout the editing agent can change. The integrity scanner does not protect all of those helpers. Repeated-round logs also need distinct, immutable identities.

**Repair:** validate verdicts strictly against a required roster; match successful agent completion and its own result to the reviewed plan/commit. Reject empty rosters, inconsistent verdicts, missing fields and unknown severities. Run reviewers with read-only filesystem access and no write credentials; execute gate logic from a trusted revision outside the editable candidate tree. Preserve every plan/review round and classify infrastructure failure separately from scientific disagreement.

The August [#163 park record](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/163#issuecomment-5381573459) illustrates the distinction: its machine-recorded blocker is `unrecognised verdict None`. Recovering a missing review is a different action from asking a human to decide the underlying scientific model.

### A6 — P1: Reviewer selection and deployed-version provenance need explicit contracts

The router caps panels at three members including the auditor, then fills seats by milestone/label order. Once full, additional relevant roles—including the promised novelty reviewers—are silently omitted. A geology/statistics/rock-physics change needs expertise chosen for its acceptance claims, not simply the first matching labels. The five project personas are useful, but do not cover every depth-sensitive seismic or hazard-routing question by themselves.

The August #163 comments contain scope/resolution fields and a `gaia-park` payload absent from the audited main implementation. This suggests additional deployed or manually generated workflow behavior; it does not prove a particular remote code version. The local NISAR branch also differs materially from main. No supplied runtime manifest identifies the code, plugin and persona revisions used for every review.

**Repair:** declare mandatory reviewers in each work package, permit additional specialists, and make panel cost limits explicit. Record repository SHA, runner SHA, plugin/persona versions, model identifiers, run ID and data versions. A review must remain attributable even after the agent implementation changes. Keep shared-model biases in mind: persona diversity helps but is not a substitute for independent data, numerical oracles and human scientific judgment.

## Roadmap and scientific-readiness findings

### R1 — P0: The runnable queue is not the documented dependency graph

The current-main simulation emitted **38 batches containing 100 tasks**, holding back only 14 of the 114 non-epic tasks. This is not a proposed execution schedule. It demonstrates the present grouping logic:

| Queue evidence | Why it matters |
|---|---|
| Batch 2: `#198, #163, #162, #161` | The common operator is eligible despite prerequisites described in issue bodies; competing estimator/prior work shares a batch |
| Batch 13: `#86, #85, #84, #83`; batch 14: `#82, #81` | Measured-profile validation anchor #81 comes after the downscaling work it is meant to gate |
| #52 in batch 25; #89 in batch 35 | State-definition and timestep foundations follow many consuming milestones |
| Paused v0.3 Vs30 work remains eligible | A human pause in ROADMAP is not an executable eligibility rule |
| #187 depends on epic #171 | Epics are intentionally human-closed trackers, so this can become an indefinite dependency even after required child work is done |

`BLOCKED_BY` is a partial hardcoded list; references and native GitHub dependencies are not reconciled. No native dependency/subissue links were populated in the retrieved issue metadata. The runner also does not exclude the parked `needs-human-decision` issues reliably through a durable lifecycle contract.

**Repair:** use one machine-readable work-package graph with typed prerequisite capabilities, readiness state, pause/human-block state, accepted evidence and touched interfaces. Reject cycles, missing prerequisites and ambiguous epic blockers. Order by readiness before priority and milestone. Group only a coherent change with a common acceptance target, not merely up to four issues sharing a label. Refresh eligibility before dispatch and after merges. Preserve the intended small hydrology pilot; do not make every exploratory mechanical or hazard branch a prerequisite for it.

### R2 — P1: Issue identities and status have drifted

The complete inventory records **23 checkbox/state disagreements** in trackers #1/#60/#127/#150. These are reconciliation candidates, not instructions to auto-close issues. #119 has an empty body; memory issues #120–#124 contain shifted title/body content, and #124/#125 duplicate chapter scope. Several old tasks have implemented subsets or explicit “addressed” text while remaining open.

Conversely, [#100](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/100) is intentionally still open: its discussion says the April phase criterion is not met. ROADMAP nevertheless calls v0.4 done and the eastern extension next. Closed #110 and #114 were absorbed/duplicated into other issues, not delivered as independent scientific capabilities. Deriving a chapter's “implemented” status solely from `closed` would therefore be wrong.

**Repair:** reconcile titles, bodies, dependencies and residual acceptance one issue family at a time. Record closure disposition: `implemented-and-verified`, `negative-result`, `superseded`, `duplicate`, or `cancelled`. Add an owner, acceptance reviewer and evidence location. Reopen or retain only the outstanding scope; do not erase productive historical work.

### S1 — P0: The conservation claim fails a direct counterexample

On main, an isolated dry-day calculation with zero precipitation and PET, a 1 m root zone, theta initially 0.1, water table 0.5 m deep and specific yield 0.3 adds **0.739233 mm** to soil storage through capillary rise. Groundwater storage does not decrease and all external outflows are zero. Total water is created. The code credits capillary water to the root store without the equal groundwater debit.

This substantiates the already open [#171/#172 storage work](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/172). The priority is to implement it and correct current-tense “closed budget” claims, not create a duplicate issue. Every transfer must cancel across compartments; only boundary fluxes and explicitly logged DA increments may change the total. See the science appendix and executable reproduction.

### S2 — P0: Fitted targets are being used as validation evidence

The same amplitude, runoff coefficient and baseflow-index targets used to calibrate the daily model appear under “independent” state evaluation. The reported calibration success is useful; it does not establish predictive performance on new basins, years or hazards. The available groundwater summary has RMSE about **18.49 m**, bias **+3.54 m**, and mean R² **0.089**. These pooled numbers do not establish the local shallow-water accuracy required by liquefaction or the pressure accuracy needed on a failure plane.

Keep [#137](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/137), #186, #194 and #195 as empirical gates. Freeze holdouts before tuning, refit all learned stages inside folds, score observations at their real support, and report domain/event uncertainty and sample adequacy. A function that computes coverage is not evidence that the product achieves it. After a change to the predictive distribution, revalidate the product.

### S3 — P0: Resolve mathematical contracts before additional filters are built

The book's RBPF argument treats frozen derivatives of a nonlinear hydromechanical operator as making it exactly linear and its conditional likelihood exact. That is a local approximation, not a proof of a conditionally linear-Gaussian model. Theta and saturation also need an explicit deterministic relationship rather than duplicate unconstrained state entries. The displayed saturated dv/v–head coefficient is dimensionally inconsistent with the preceding definition of beta and has a sign conflict.

Update [#198](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/198), #165/#162 and #204 with a consistent derivation, reference state, units and approximation limits. Validate the nonlinear observation operator against a low-dimensional numerical posterior oracle. Demonstrate a need for particle conditioning before committing to that architecture. The simpler hydrologic EnKF pilot can proceed within an explicitly limited state/observation contract.

### S4 — P1: Native support must include quantity, depth, time and likelihood

Horizontal footprints alone do not turn gauge discharge into head, a shallow probe into root-zone average moisture, or GRACE total storage into groundwater storage. A synthetic datum generated from the model is not independent information; even a zero-innovation synthetic observation changes posterior covariance and real-observation weights. The flagship notebook still mixes synthetic observations and climatological substitutes into its analysis and updates frames independently rather than carrying a posterior forward.

Operationalize [#189](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/189), #164/#168 and #188 with typed measurement targets, units, vertical/temporal support, source/availability timestamps, correlated error blocks, explicit synthetic/imputed status and fixed holdouts. Use a physical state-to-flux/routing operator for gauges. Keep model intercomparison separate from independent observational validation.

### S5 — P1: Hazard integration requires tested consumers and bounded claims

The 90 m regional grid is a shared computational/delivery grid, not proof of 90 m effective accuracy. The book's tiered-resolution chapter already gives the right distinction: regional screening, finer local physics, and site investigation.

The Landlab export does not establish that `LandslideProbability` uses the intended transient groundwater and moisture states. Its component contract requires a scientific adapter, not just compatible raster files. The planned liquefaction output should remain a conditional regional susceptibility screen, with its depth-to-water and shaking uncertainty; #141's GLM implementation is still open. Depth-resolved triggering is a later scope. Floods need routed source terms and hydrograph/inundation validation. Preserve those separate acceptance paths under #129/#141/#199–202/#193. Full joint hazard ensembles should not block a limited, explicitly deterministic routing/adapter experiment needed to discover interface errors.

### S6 — P1: Documents and agent instructions need one current scientific contract

The new probabilistic roadmap is generally more candid than README, the older assumptions register, conventions and some chapter claims. Copilot instructions still direct a 1 km monthly/LightGBM workflow; conventions still refer to a separate Pillar-1 comparison module that is absent. Static RF tree spread is presented as a calibrated resolving-power quantity; it is not automatically predictive uncertainty or demonstrated spatial resolution. Several old overclaims were corrected by PR #212, so those repairs should be preserved, not reported as still missing.

Use [#204](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/204) to align every entry point and generated artifact with a versioned state/evidence contract. Mark capabilities separately as implemented, synthetic demonstration, demonstrated on real data, empirically validated, or planned. Scientific gate status must come from evidence, not prose or issue closure. Verify equation/source correspondence and competitor descriptions; the DOI-resolution CI check alone cannot detect a valid DOI assigned to the wrong paper.

## A workable execution order

| Stage | Work package | Exit evidence |
|---|---|---|
| 0 | Operational repairs A1–A6; reconcile issue identity/readiness | Isolated failure-path tests pass; effective GitHub protections verified; supervised one-issue run preserves all approvals and artifacts |
| 1A | #153 data snapshot/fixtures; assign calibration/test roles and owners | A compact watershed/event fixture builds from a clean checkout with versions, checksums and expected outputs |
| 1B | #52/#89/#137/#171–177 storage, timestep and deterministic physics | Common water-equivalent ledger; transfer cancellation; bounds; convergence and recession/event tests; calibration distinguished from holdout results |
| 1C | #186 UQ; #187 state/interface schema; document current prior/barrier assumptions | Correct units/distributions, no silent zero uncertainty, unambiguous state/diagnostic relationships; measured resource envelope using the landed stationary backend; further #163 anisotropy research remains conditional |
| 2 | #189 → #188 → #192 → #194; hydrology-only first | Real-observation cycling pilot; persistent posterior; explicit DA increments; calibrated withheld-sensor value added against identical-forcing open loop. Assimilate dv/v only after #164/#165/#198 provide defensible covariance and a shared observation operator |
| 3 | #136/#71/#32 → #191; #203 as an adapter contract | Actual forcing execution; as-of data; dependent P/T members; lead-zero continuity; member water accounting and lead-time scores |
| 4 | Hazard-specific pilots: #129, #141, #200–202; #193/#195 for probabilistic release | Working consumers, perturbation tests, independent hazard/event baselines, preserved member identity and stated use limits |
| Conditional research | #169 then #190/#121–124, using #198 when seismic observations are included; further #163 anisotropy; finer Vs30; eastern extension | Identifiability, validation data, and evidence that the simpler core is inadequate; explicit reauthorization of paused work |

The ordering above distinguishes schema design, experimental prototypes and scientific release. A storage/schema draft need not wait for every empirical calibration experiment; production certification must. Likewise a hydrologic nowcast need not wait for seismic attribution or all three hazard products. Split broad issues into those acceptance boundaries rather than making the graph cyclic or needlessly serial.

Choose one small watershed and event window for the first integrated demonstration, including well/probe/gauge coverage and an independent withheld period. Select the first hazard pilot according to available observations and validation inventory. The audit does not assume all three hazards must become operational together.

## Required review and human-decision protocol

Each work package should carry: issue IDs and residual scope; prerequisites; responsible human; implementing agent; required reviewer roles; affected interfaces; scientific assumptions; immutable data/holdouts; compute/time budget; decisive tests; artifacts; stop conditions; permitted negative result; and a closure disposition.

The implementation lifecycle should be:

```text
triaged → ready → plan submitted → plan approved → implementing
        → result/evidence submitted → science and code revisions
        → accepted at a specific commit → human approval where required
        → merged → per-issue closure verified

revise → return to the relevant author/reviewer with stable concern IDs
scientific block → explicit scientific decision, retaining dissent and evidence
review/service failure → bounded retry, then infrastructure-blocked
stop/budget exhausted → preserve work; never infer completion
```

The plan panel should be retained through result review. Fixing a review means addressing the concern or providing an evidence-backed rebuttal; replacing a dissenting reviewer or weakening its criteria is not convergence. Change the panel only for missing expertise, a demonstrable conflict or an infrastructure problem, with the reason recorded. A reviewer may change its position after evidence, and that change should remain visible.

Mandatory scientific findings need a test/evidence link and a disposition. Disagreement should converge through a bounded number of revisions with the same acceptance criteria. A cap reached with substantive disagreement routes to a named human; an invalid JSON response routes to retry/repair. Neither is approval.

The final review bundle must include the exact issue/plan versions, completed concern table, code SHA, data/run manifest, real-versus-synthetic roles, test and validation outputs, limitations, declared-versus-actual cost, unresolved dissent and proposed closure set. A human should be asked to decide only a concrete remaining scientific choice or approve that reviewable result. Routine reversible engineering within an approved scope need not repeatedly request permission.

For the first supervised runs, require explicit human approval of the scientific plan and of the final result. Once failure-path behavior and review quality are demonstrated, narrowly authorize automatic merging for specified low-impact work classes. Scientific schema, physical assumptions, validation criteria, public product releases and substantial compute allocations should retain named human gates.

## Concrete operational repair tickets to prepare

These are proposed work packages, not new GitHub issues created by this audit. Existing scientific issues should be amended instead of duplicated.

| Ticket | Acceptance test |
|---|---|
| Apply effective main protection and define automation authority | API confirms target/rules; unapproved or stale-approval test PR cannot merge |
| Enforce strict reviewer lifecycle and persistent concern resolution | `revise`, major findings, empty roster, failed agent completion and malformed verdict all prevent acceptance |
| Track per-issue completion and make batch stopping safe | Interrupt after first issue of a multi-issue batch; no other issue is referenced as closed |
| Run uniform gates on every final commit | A revision weakening a test, breaking docs or changing scientific scope blocks before push/merge |
| Protect and version the runner/review environment | Candidate code cannot modify active judges; read-only reviewers cannot write; every result identifies runner/persona/commit |
| Replace partial hardcoded scheduling with the accepted work graph | Queue respects #81 before dependents, human parks and pauses; no child waits indefinitely on a tracking epic |
| Reconcile all issue identities and closure evidence | All 160 inventory rows dispositioned; shifted memory issues and 23 tracker conflicts resolved without falsely claiming acceptance |
| Demonstrate one complete supervised issue lifecycle | Successful run and forced review failure, timeout, stop, no-op, stale-SHA and partial-batch scenarios produce the correct durable states |

## Limits and remaining uncertainty

The main source and public GitHub record were audited as retrieved on the stated date. The running remote server's filesystem, cron/process state, installed plugin revisions and any uncommitted newer runner were not available. Therefore this report does not certify the deployed system or claim a currently active job was stopped. The user was asked for a newer operational checkout if one exists.

The main snapshot is substantially safer than the older local runner: it fixes the unsupported `gh pr create --json` failure, preserves failed work, adds planning/science reviews, records more outcomes, and tests automation helpers in CI. Those improvements are real. The remaining recommendations address the current gaps and the next scientific acceptance boundaries.
