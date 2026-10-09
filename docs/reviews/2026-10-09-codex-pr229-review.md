# PR 229 review and guidance for issue writing and queuing

**Date:** 9 October 2026. **Reviewer:** Codex. **Audience:** Claude and maintainers of
`gaia-hazlab/gwl-space-time-smooth`.

Marine accepted this review and requested that it be saved in the repository to
guide issue writing and queuing. The scientific target is a physically consistent
estimate of soil and its hydromechanical state, informed by hydrological and
geophysical measurements, with a preserved water budget. A conservative storage
model is appropriate. Full flow PDEs and a new scientific discovery program are
not prerequisites for the first implementation.

The review covers all 49 changed files and 7,185 added lines in
[PR 229](https://github.com/gaia-hazlab/gwl-space-time-smooth/pull/229), at head
`ad6fb25b4da98288b9c9f19bc45122b4c71ff1d1`, against base
`435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f`. The PR adds an audit archive and
probes; it changes no production model code. The recommendation is to correct
the synthesis before using it as an implementation plan.

These findings are bound to that snapshot. Before changing an issue or queue edge,
read the current issue body, comments, implemented code and existing review
records. Carry forward subsequent corrections, including any split of issue 198.
The local storage-conservation checkout already contains a capillary repair and
ongoing work; the historical finding below is not a claim that this repair is
absent from the current checkout.

## Minimum implementation scope

Use one shared state with explicit water inventories and depth bounds. Carry snow
and canopy stores where applicable, root-zone and deeper vadose storage,
groundwater storage, and any transit or stream store needed to represent delayed
outflow. Document which physical volumes each store represents so water is not
counted twice. Add perched or confined stores when the pilot observations or
boundary conditions require them.

Every internal transfer must debit its donor and credit its receiver by the same
water volume. Limit transfers by available water and receiver capacity. Report
rainfall, snowmelt, canopy evaporation, soil evaporation, transpiration, outlet
discharge and relevant boundary exchanges explicitly. Recharge is an internal
transfer when groundwater belongs to the modeled domain. Use calibrated reservoir
or conductance closures and simple conservative routing before requiring a
regional groundwater PDE solver.

Diagnose moisture, suction, head, pore pressure and effective stress from that
shared state through a documented depth-dependent mapping. Predict seismic
observations with the same hydromechanical operator used by assimilation. Wells,
soil probes, geophysical measurements and downstream discharge need observation
operators at their actual spatial, depth and temporal support. Discharge observes
outlet flux and routed storage release; it is not a direct water-table observation.

Distinguish forecast conservation from analysis corrections. A data-assimilation
increment changes the estimated inventory, not a measured physical flux. Report
increments per store and reconcile net corrections with uncertain rainfall,
initial storage or boundary fluxes over the evaluation window. Logging arbitrary
increments alone does not establish physical budget closure. Conversely, do not
require every analysis to preserve the previously estimated total if observations
justify correcting it.

## Review findings

### P1 Reduce the required architecture to the stated objective

The synthesis requires 2D Boussinesq groundwater and Richards columns at every
assimilated sensor. Neither is necessary for algebraic water conservation in a
compartment model. Conservative reservoir transfers, bounded drainage and simple
stream routing can provide the first implementation. Detailed solvers can serve
as optional benchmarks or later refinements when a measured deficiency justifies
them.

**Change:** Rewrite the foundation issues around shared stores, transfers,
boundaries and observation operators. Remove full-flow solvers and new sensor
acquisition from mandatory foundation gates unless a particular deliverable
actually requires them. Distinguish numerical conservation from predictive skill
against gauges; missing a process can reduce skill without violating conservation.

Sources: [target architecture](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/README.md#L123),
[sensor-column requirement](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/README.md#L224).

### P1 Reconcile the dependency recommendations

The README makes hysteresis issue 176 depend on operator issue 198, while the
water-budget audit and verdict JSON make 198 depend on 176. The README also makes
137 depend on 100, while the JSON makes 100 depend on 137 even though its
`final_verdict` text explicitly corrects that blocker to 70. Combining these
recommendations would create cycles.

**Change:** Establish one canonical dependency list using current issue IDs. Split
the basic shared operator, optional hysteresis and assimilation integration into
separate deliverables where needed. The basic operator should accept the agreed
hydrological state contract without requiring a completed hysteresis extension.
Update the issue prose, structured verdicts and scheduler consistently. Check the
resulting graph for cycles and stranded tasks before dispatch.

Sources: [README dependencies](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/README.md#L385),
[opposite family dependency](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/issues/water-budget-core.md#L88),
[inconsistent JSON blocker](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/issue_verdicts.json#L575).

### P2 Correct the shallow seismic sensitivity conclusion

Marine's correction appears at the top of the hydromechanics report, but the
recommendations still require new frequency bands or dropping vadose sensitivity.
The archived top-1 m probe uses a grid whose first node is at 5 m. Its top-1 m
perturbation therefore contains no perturbed nodes. That demonstrates a
representation defect, not physical zero sensitivity. Sensitivity also does not
by itself establish that individual depth layers can be resolved independently.

**Change:** Use a grid that represents the shallow layers and evaluate the
site-specific kernels for the actual observed bands. Assess forward sensitivity,
noise and recoverable combinations of the state before prescribing additional
acquisition. Do not impose a universal frequency threshold from this probe.

Sources: [uncorrected recommendation](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/lenses/hydromechanics.md#L152),
[zero-node shallow perturbation](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/probes/memory/probe.py#L24).

### P2 Separate water creation from drainage and equilibration

In the audited code, capillary rise credits the root zone without debiting
groundwater. Disabling capillary rise removes the reproduced zero-forcing water
creation; a missing valley outlet is a separate drainage problem. The linear
groundwater reservoir can have a stable equilibrium when mean recharge differs
from `R_ref`, contrary to the statement that it is unstable unless recharge is
exactly 3 mm/day. Likewise, discharge exceeding rainfall minus ET can be accounted
for by groundwater depletion over a finite window.

**Change:** Give missing transfer debits, missing outlets, initial-state/spin-up
bias and parameter calibration separate diagnoses and acceptance criteria. Check
the complete identity including storage change before labeling a result a mass
leak. A simple conservative outlet closure can repair drainage behavior without
requiring lateral groundwater PDEs.

Sources: [budget table](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/README.md#L43),
[equilibrium claim](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/lenses/geohydrology-budget.md#L58).

### P2 Archive the actual groundwater identifiability probe

The report attributes parameter Jacobians and condition numbers to `ident.py`,
but the archived file evaluates damage/healing temporal bases. Its verifier
expects groundwater variables absent from that file. Resolving the path still
produces `NameError: cells is not defined`.

**Change:** Archive the actual groundwater probe with pinned inputs, dependencies,
invocation and outputs, or mark those numerical results as unreproduced. Do not
turn the reported condition numbers into issue gates until their computation is
recoverable. Keep any independently supported analytical identifiability argument
distinct from the missing numerical evidence.

Sources: [numerical claim](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/lenses/da-physics-coupling.md#L124),
[broken verifier](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/probes/verify-da-physics-coupling/sub.py#L3).

### P2 Replace the biased innovation acceptance criterion

The synthetic assimilation proposal requires a nonzero innovation mean.
Independent truth and forecast runs can have zero-mean innovations, which is
desirable for an unbiased estimator. Requiring a nonzero mean rewards bias.

**Change:** Assert independent nature and forecast generation, meaningful
differences before analysis, and an observation operator evaluated on nature.
Evaluate innovation variance, state recovery, uncertainty coverage and budget
accounting. Do not require the innovation mean to differ from zero.

Source: [proposed acceptance criterion](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/issues/hydromech-dvv-memory.md#L168).

### P2 Fix the correlated observation acceptance test

Identical footprints with perfectly correlated errors produce a singular matrix,
so ordinary positive-definite Cholesky cannot pass the proposed test. The stated
posterior variance reduction of exactly `1/N` is also generally incorrect with a
finite prior. For scalar prior variance B and independent observation variance r,
the posterior variance is `B*r/(r + N*B)`. Its ratio to the single-observation
posterior is `(r + B)/(r + N*B)`.

**Change:** Test redundant observations against the correct analytical posterior,
using deduplication or an explicitly supported semidefinite solve. Use a separate
positive-definite correlated-error case for Cholesky. Any regularization must be
declared and reflected in the expected result rather than added to make the test
pass.

Source: [proposed test](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/issues/da-estimator.md#L53).

## Verification and archive correction

The review independently reproduced the 22.5 mm capillary leak in the dry-month
case and the runoff mapping of 100 units into 155. The correlated-observation
probe reproduced Cholesky failure and posterior variances of 0.2000 for redundant
observations versus 0.0476 for five independent observations. The groundwater
verifier failed as described above. All 29 archived Python probes parse; that
does not establish that they all execute or reproduce their associated claims.

The [benchmark JSON](https://github.com/gaia-hazlab/gwl-space-time-smooth/blob/ad6fb25/docs/reviews/2026-10-08-physics-backlog-audit/probes/scale/bench_365.json#L20)
contains nonstandard `NaN` values. Replace unavailable numbers with `null`, retain
an explicit failure reason, and reject nonstandard constants when validating JSON.
Keep verdict actions machine-readable; put explanations in separate fields rather
than embedding prose in an action value.

## Instructions for Claude when revising issues

1. Read the current implementation and live issue before drafting. Preserve work
   already delivered and subsequent scope corrections. Cite evidence and source
   revisions when closing or superseding an issue; do not treat closure alone as
   proof of implementation or validation.
2. Give each issue one concrete deliverable. Separate the state contract,
   conservation repair, parameter calibration, observation operator, assimilation
   integration and optional process extensions when they have different inputs or
   acceptance criteria.
3. State the inputs and outputs, units, physical volumes, depth bounds and
   measurement support. Use explicit storage, head and depth-to-water conventions.
   Identify uncertain parameters and the observation that can constrain them.
4. Write acceptance criteria that establish the intended behavior. Conservation
   checks need initial and final inventories, every boundary flux, internal
   transfer cancellation, bounds and cumulative error. Derive tolerances from the
   numerical precision and reported outputs; do not impose an unattainable fixed
   tolerance on quantized data.
5. Separate calibration, assimilation and held-out validation data. Evaluate gauge
   budgets over a stated basin and time window including storage change. Record
   synthetic demonstrations as synthetic, and label uncalibrated closures.
6. List only indispensable prerequisites as hard blockers. Put useful comparisons,
   optional solvers and later science extensions in advisory scope notes. A basic
   well/probe pilot need not wait for every geophysical covariance or hazard task.

A useful issue body has the following short sections: **Purpose**, **Deliverable**,
**Inputs and conventions**, **Acceptance**, **Hard blockers**, and **Advisory
follow-ups**. Use actual current issue IDs and name the interface needed from each
hard blocker. Avoid broad gates such as “all physics complete.”

## Instructions for Claude when revising the queue

Use one canonical dependency list and keep the scheduler, issue prose and
structured verdicts consistent. Resolve the two historical cycles above against
the current issue splits. A draft shared-state contract can precede completion of
all model repairs; runnable assimilation must depend on the particular repaired
model and observation operators it actually uses.

Before dispatch, verify that:

- The dependency graph is acyclic and a topological ordering exists.
- Every hard blocker names a real issue or a documented external condition.
- Human holds and pauses are enforced by the scheduler's actual filter, not merely
  by prose or a label it does not read.
- Epics are trackers, not indefinite implementation blockers; use the necessary
  child deliverables as prerequisites.
- Split issues receive their dependency edges in the same queue update.
- Tasks editing the same core state/transfer loop are sequenced or deliberately
  combined around one agreed interface.
- A dry-run queue holds tasks whose required inputs are unavailable while allowing
  independent foundation work to proceed.

For scheduler changes, add focused fixtures for cycles, held issues, completed
blockers, epic handling and the revised operator/hysteresis ordering. Record the
queue dry run and the reason each held task is held. Preserve existing human
decisions and do not infer that acceptance of this review releases every hold.

The first deliverable should demonstrate a consistent shared state, bounded
conservative water transfers, predictions at sensor support, and a complete basin
budget. Add physical detail when observations or a consuming model require it.
