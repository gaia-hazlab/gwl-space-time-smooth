# Scientific-document audit of the GAIA soil twin

Audit date: 2026-09-10. Read-only review of README, all 15 twin chapter/index files, assumptions/limitations, the July reviews and August prior/state/solver reviews, issue bodies and selected issue comments. Exact code lines were inspected where needed to distinguish stated design from actual behavior. All retained findings were verified against authoritative GitHub main `435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f` extracted to `/tmp/soil-twin-audit/main`; paths and line numbers below refer to that snapshot. The older local feature branch was used only for initial discovery. August review additions and PR #212/#216/#217 improvements are credited below. No repository files or GitHub objects were changed.

## Overall assessment

The intended architecture is scientifically coherent as a **regional antecedent-state research system**: explicit native-support operators, shared physical quantities, probabilistic handoffs, and independent evaluation are the right foundations. The newest roadmap is substantially more critical and accurate than the book. It already names many of the hard physical and statistical defects and does not pretend that a 90 m map solves parcel-scale decisions.

The present documentation nevertheless describes several unbuilt or demonstrational capabilities as operational, and it contains substantive mathematical errors that a multi-agent implementation must not inherit. The largest near-term risk is building additional filters and hazards on top of inconsistent storage accounting, unsupported observation operators, and uncertainty that has not demonstrated independent calibration. **Continue development, but do not treat the current product as scientifically validated for hazard decisions.** A visually coherent coupled animation is not evidence that assimilation improves held-out hazard-relevant states.

This is not a recommendation to implement every future capability before doing useful work. A small, reproducible, independently evaluated watershed experiment can proceed while nonlinear memory, finer hazards, and new satellites remain explicitly deferred.

## Ranked findings

### S1 — P0: The claimed closed coupled water budget is not closed

**Evidence.** `docs/twin/03a-physics-hydrology.qmd:49-53` says it enforces a closed water balance at each 90 m cell. Lines 59-78 add capillary rise to the root store but do not subtract it from groundwater; lines 82-87 assert exact mass balance and bidirectional exchange. `src/models/water_budget.py:217-219` adds `cap_eff` to S; `:266` lifts groundwater only by recharge and `:273` subtracts river discharge. There is no matching groundwater capillary debit. `docs/twin/00a-digital-twins-review.qmd:185-203` correctly explains that analysis increments also need a separate budget ledger, but the flagship independent-frame analysis does not implement that complete cycle.

**Consequence.** The central conservation claim fails before assimilation. Adding a positive capillary transfer creates total water; downstream flux totals and inferred groundwater changes can compensate through fitted coefficients. A per-compartment identity is insufficient when the exchange is not equal and opposite.

**Roadmap disposition.** This is acknowledged future repair in open **#171/#172**, with dependencies in **#187/#188**. The defect is known; the current-tense book/README claim is the contradiction.

**Required gate.** For an isolated column and connected pilot basin, report compartment storage changes and boundary fluxes in common water-equivalent units at every step. Capillary exchange must cancel when compartments are summed. Include no-input drydown, shallow-water-table capillary rise, storm recharge, snowmelt, and a nonzero analysis increment. Track the latter separately rather than silently forcing a physical flux to absorb it. Scientific review should approve the storage definition before downstream implementation.

### S2 — P0: Calibration is repeatedly labelled independent validation

**Evidence.** `docs/twin/03a-physics-hydrology.qmd:206-221` states that specific yield, anisotropy, and river-sink strength are fitted to amplitude, Q/P and BFI. `docs/twin/05-state-evaluation.qmd:378-386` then presents those same numerical results as **independent** evaluation. The hydrology text `:198-200` additionally calls a Lyne–Hollick decomposition the only direct observation of the flux partition; the direct gauge datum is total discharge, while its decomposition is a model-derived estimate. `docs/twin/00-structural-model.qmd:165-168` asserts `coverage_metrics.json` confirms calibrated 90% intervals, whereas the current issue **#186** still says those calibration tests must be rerun after correcting variance units.

The committed `data/processed/block_cv_metrics.json:3-9` records RMSE 18.493 m, bias +3.539 m and mean R² 0.089, not strong explanatory skill. The committed `data/processed/snotel_validation.json:2-8` records 5 stations, pooled r 0.404 and median anomaly r 0.214. These are useful baselines, but neither establishes event-scale skill, calibrated joint uncertainty or performance in unsampled hillslopes. The committed JSON summaries do not provide a current, versioned end-to-end calibration report.

**Consequence.** A parameter-fitting success can become the release acceptance result. Exact agreement with a calibration target does not demonstrate transfer to other basins, years, flood peaks or shallow/perched groundwater. A code-level coverage function is not a product-level calibration result.

**Roadmap disposition.** Accurately recognised in **#137/#175/#186/#194/#195**. The documentation and claimed maturity need to reflect their open state. Strengthen existing issues rather than duplicate them.

**Required gate.** Freeze calibration, tuning and test partitions before fitting; refit all learned transforms/baselines/hyperparameters inside training folds; hold out complete wells, basins and event windows with spatial/temporal buffers as appropriate. Report station and event counts, support, record version, residual units, coverage confidence intervals, proper scores, and seasonal versus anomaly/event skill. BFI uncertainty must include separation-method uncertainty. Publish fitted-target scores as calibration diagnostics, with held-out evidence in a separate table.

### S3 — P0: The detailed RBPF architecture is mathematically incorrect

**Evidence.** `docs/twin/04-assimilation.qmd:800-812` says that conditioning on a particle fixes the derivatives k_sat and S_theta and therefore makes dv/v **linear** in h and theta, permitting an **exact conditional likelihood**. The same chapter `:718-728` correctly gives nonlinear retention/effective-pressure/Hertz–Mindlin physics. Holding a derivative fixed creates a local affine approximation; it does not make the underlying function linear. The approximation also needs its intercept/reference state. The state split `:786-788` puts theta in the linear state and saturation Sw in the nonlinear state without stating their deterministic relationship through porosity. The caveat `:814-820` discusses nonlinear forecast error but does not repair the nonlinear conditional observation model.

**Consequence.** Agents following the book could build a filter advertised as exact while using an inconsistent conditional likelihood, duplicate hydrologic state, and understate uncertainty. A handful of nonlinear variables per region does not make the conditional hydrologic field linear-Gaussian.

**Roadmap disposition.** This is a substantive design correction to add to **#198/#162/#204**, not simply an unfinished feature. **#198 already gives the better direction**: evaluate the common nonlinear observation operator inside the likelihood/ensemble update. Its August comment also correctly states that dv/v is an observation on the hydrologic state, with covariance HBHᵀ+R, not a new independent field prior.

**Required gate.** Either construct and prove a genuinely conditionally linear-Gaussian model, or call the design a particle-conditioned approximate EnKF/EKF and quantify approximation error. Start with a low-dimensional known-truth benchmark using the full nonlinear H, compare posterior marginals with a numerical reference, and demonstrate that duplicated theta/Sw states cannot diverge. Do not select the particle architecture until actual non-Gaussian failure and identifiability justify it.

### S4 — P0: The saturated dv/v-to-head coefficient has incorrect units and sign

**Evidence.** `docs/twin/03b-physics-hydromechanics.qmd:88-91` defines dv/v = beta × strain and beta = -mu' kappa/(2 mu), so beta is dimensionless. Lines `:99-101` then define k_sat = -beta rho_w g in dv/v = k_sat Delta h. The proposed k_sat has units Pa/m, rather than 1/m; for the negative beta quoted in `:94`, it is positive even though `:75-86` says increasing pore pressure decreases velocity.

**Consequence.** This is not a calibration caveat: the physical identification written in the book cannot be used in an implementation with consistent units. For the pure pore-pressure contribution the earlier displayed equations instead imply k_sat = -(mu'/(2mu)) rho_w g = beta rho_w g/kappa; any additional loading term and drained/undrained convention must be stated separately.

**Roadmap disposition.** Add this dimensional/sign acceptance test to **#198/#165**, while keeping empirical K_SAT as an explicitly named temporary mode.

**Required gate.** A units table for every beta/kappa/mu'/k_sat convention, analytic sign and scale checks, and a head-perturbation test in which the declared pore-pressure increase gives the declared softening. Have a rock-physics/acoustoelasticity reviewer approve the derivation.

### S5 — P1: Gauge, probe and satellite operators are oversimplified as exact point/average measurements

**Evidence.** `docs/twin/04-assimilation.qmd:109-121` describes every datum as a normalized average of a state field, including discharge and surface-water classification. Lines `:694-710` retain the exactness claim for probes; a newly added caveat correctly conditions the well claim on measurement target. Yet `docs/twin/01-input-data.qmd:23-28` itself notes mixed aquifers and fixed-depth probes, while the modeled moisture in `03a:55` is averaged over a root zone. The gauge checkerboard `04:521-553` and observability figure `05:171-186` treat basin discharge as a Gaussian footprint on groundwater head, with apparent information concentrated around basin outlets. Geometry alone does not convert m of head into m³/s of discharge. Binary inundation likewise requires a classification/threshold likelihood, not a normalized average of head.

The new measurement-target classifier and guarded well operator are real improvements (`04:84-106`); they do not complete operational observation-record wiring (#189), nor repair probe-depth and gauge-flux semantics.

**Consequence.** Native horizontal footprint is necessary but insufficient. A sensor at 5–20 cm does not directly measure a 1 m root-zone average; a screened interval can measure confined head instead of the water table; a gauge constrains routed flux from distributed state, parameters, history and upstream boundaries. These mismatches can manufacture information gain even if no pixels are resampled.

**Roadmap disposition.** **#52/#165/#189/#198/#201** cover much of the needed contract. Add an explicit gauge state-to-flux/routing operator acceptance criterion and mark current gauge information maps as geometrical illustrations until that operator is present.

**Required gate.** Typed physical quantity, units, vertical support, timestamp/accumulation interval, datum and well-screen target on every record. End-to-end H tests must produce the observable in its own units. Include representation and operator error in R; do not infer Gaussian exactness from a linear-looking horizontal footprint.

### S6 — P1: 'Spatial resolution from static layers' is an uncertainty surrogate presented as demonstrated information

**Evidence.** `docs/twin/05-state-evaluation.qmd:270-299` identifies RF tree spread with virtual-observation noise and claims the resulting C_static is mathematically identical to a joint Bayesian update of virtual and real observations. Even in a scalar case, a prior variance v and independent observation-noise variance r yield posterior (1/v + 1/r)^-1, not r. Assigning C_static = diag(sigma_rf) rho diag(sigma_rf) is a valid covariance construction, but not the asserted inference equivalence. Lines `:306-318` then equate the map with real 90 m resolution and block-CV R². Lines `:403-412` separately acknowledge overconfident RF extrapolation and 44% low-confidence terrain. These cannot all be read as established, calibrated information.

The main branch now correctly distinguishes variance reduction from spatial resolving power and adds averaging-kernel/width helpers (`05:147-167`). The later virtual-observation/static-resolution block remains unreconciled with that correction.

**Consequence.** Tree agreement is not predictive error, and neither is a measure of spatial resolving power. A model can confidently miss an entire regime. The map can rank sensor placement by an unvalidated prior rather than empirical skill. Fine covariates add potential spatial structure; they do not establish 90 m accuracy.

**Roadmap disposition.** Correct the mathematical interpretation in **#192/#194/#204**. Keep the valid nonstationary covariance construction only after cross-fitted residual calibration; make any virtual-observation formulation explicit about the prior and information sources to avoid double-counting wells used for baseline training.

**Required gate.** Compare the stated covariance with held-out residual covariance and coverage; show sensitivity to prior scale, kernel and applicability mask; report recovery as a function of spatial wavelength/averaging kernel, not solely fraction of prescribed variance removed. Preserve negative value-added results.

### S7 — P1: Demonstration, real-data assimilation and forecasts remain inconsistently labelled

**Evidence.** `README.md:10-16` says the living state is built from assimilated sensors/satellites and ambient dv/v. `docs/twin/05-state-evaluation.qmd:11-23` calls four networks actually ingested and assimilated, including seismic and gauges. But `06-forecast.qmd:64-71` says measured dv/v is the remaining stream and that synthetic dv/v derives from the model. `06:31-35` correctly states a live FuXi run has not been produced end-to-end, while `A-compute-and-deployment.qmd:55-67` uses present-tense generated forecasts. `03c-memory-disturbance.qmd:7-27` says memory is absent, while `:115-120` says hysteresis is integrated and on by default; issue #176 correctly distinguishes observable hysteresis from hydrologic flux memory.

`notebooks/make_twin_gif.py:225-244` inserts synthetic observations generated from the prior together with real data. Even with zero expected innovation, these rows change the gain/precision and hence the weighting of genuine observations; they are not an inert visual consistency check. `:212-224` substitutes monthly well climatology with the same WELL_VAR as fresh reports. `:194` uses each probe's whole-window mean, so this hindcast is not an as-of-information forecasting experiment. The notebook's `:248-252` independent-frame loop is not a cycling nowcast.

**Consequence.** A reader or agent can mistake synthetic self-assimilation, imputed climatology and an unexecuted adapter for evidence of an operational observing system.

**Roadmap disposition.** **#188/#189/#191/#194/#204** explicitly cover most of this. Make the doc correction immediate rather than waiting for all underlying work to finish. Add statuses for `implemented`, `demonstrated on real data`, `synthetic demonstration`, `uncalibrated assumption`, and `planned`, as the August #204 comment recommends.

**Required gate.** Each headline figure/metric must reference a run manifest with code revision, datasets, real/synthetic/imputed status, issue evidence, and calibration/test roles. Real-observation experiments must exclude synthetic self-observations or quantify their influence explicitly. Live-data status and forecast timestamps must use actual record availability.

### S8 — P1: Depth separation and disturbance attribution are asserted more strongly than observability permits

**Evidence.** `docs/twin/03b-physics-hydromechanics.qmd:142-147` promises two hydrologic states from one measurement; `04-assimilation.qmd:562-570` treats the water-table split and gains as sufficient. Yet `05-state-evaluation.qmd:106-108` says the shallowest band peaks near 45 m, versus a roughly 1 m root zone, and `03c:102-110` claims the BLUE innovation partitions hydrology, damage and disturbance. Different relaxation times do not ensure identifiable parameters over a finite record or under overlapping events.

**Consequence.** Depth inversion can be regularization-dominated; uncertain water-table location moves the regime boundary; loading, temperature, damage and water can remain confounded. A noise-free checkerboard or inversion through its own H does not test wrong kernels, wrong physics, common processing biases or real depth discrimination.

**Roadmap disposition.** **#168/#169/#198** already recognise kernel and rank/conditioning issues. **#164** must also preserve correlated coda/processing errors before posterior contraction is meaningful.

**Required gate.** Cross-kernel/model synthetic tests (different truth and inverse operators), posterior resolution/cross-talk matrices for shallow/deep states, uncertainty in the phreatic split and reference Vs(z), known event timing, finite-window conditioning and posterior multimodality. Verify incremental value against held-out colocated probes/wells instead of using dv/v as its own only truth.

### S9 — P1: The landslide handoff needs a scientific adapter, not just file export

**Evidence.** `docs/twin/07-hazard-integration.qmd:21-33` names LandslideProbability and calls water-table depth, moisture fraction and recharge exports LandLab-ready. Main further asserts explicitly at `docs/twin/07-hazard-integration.qmd:59-61` that LandslideProbability takes `water_table__depth`; that API statement is false. The official component derives relative perched wetness from recharge plus soil/topographic inputs; its declared input fields do not directly include the exported water-table or moisture names. [Landlab component documentation](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.landslides.landslide_probability.html).

**Consequence.** Format compatibility does not show that the intended transient state drives factor of safety. Passing recharge into a component that reconstructs its own wetness may ignore or duplicate the twin's perched/deep water states. A regional groundwater surface is also not automatically the failure-plane pressure in a convergent hollow.

**Roadmap disposition.** Already correctly identified in **#129/#130/#133/#135**. The physical state and adapter should be reviewed jointly with the downstream repository. Do not mark a hazard integration complete solely because export filenames and units validate.

**Required gate.** A reproducible pilot consuming the actual adapter, explicit state-to-pressure/wetness equations, controlled perturbations showing which fields affect FS, and withheld inventory/event scoring. Preserve member identity and spatial dependence under **#193**. Document when the component is a susceptibility model rather than a transient slope-failure model.

### S10 — P1: The 90 m objective needs to remain a regional product contract

**Evidence.** `docs/twin/index.qmd:28-32` and `00-structural-model.qmd:42-52` say hazard requirements determine a 90 m state and that this is the resolution dynamics inherit. The much better `07b-resolution-requirements.qmd:29-51` distinguishes 1–10 m landslide physics, 1–5 m local inundation, regional liquefaction screening and point CPT/SPT. It explicitly introduces regional/fine/site tiers `:82-112`. Current water-table RMSE is ~19 m and 44% of terrain is outside strong applicability (`05:397-412`); a fine output grid cannot fix those limitations.

**Consequence.** The same book alternates between delivery spacing and scientifically resolved, actionable hazard scale. Vs30 class probability is not itself liquefaction triggering probability or a site-specific engineering decision (`07:85-95`). The tier chapter already solves the conceptual issue; its contract must govern the overview, outputs and roadmap acceptance.

**Roadmap disposition.** **#135/#140/#146/#147/#199-202/#204** correctly preserve this distinction. Retain tiered hazard scope; do not expand the regional core into a uniform metre-scale model.

**Required gate.** Per-variable native/effective/delivered scale, allowed hazard use, applicability mask, and separate vertical accuracy requirements. A regional screening release must be benchmarked against an existing regional baseline; higher-tier claims require independent local pressure/stratigraphy/hazard evidence.

### S11 — P1: Independent evaluation products require role and lineage corrections

**Evidence.** `docs/twin/02-evaluation-data.qmd:16-19` groups SMAP L4, ERA5-Land, NLDAS and GRACE under independent references. Lines `:35-36` say GRACE independently constrains groundwater storage and water-table trends. GRACE actually senses total storage including soil moisture, snow, surface water and groundwater; groundwater estimates require removing other stores and carrying those errors. [NASA's explanation of the GRACE storage observable](https://science.nasa.gov/earth/earth-observatory/weighing-earths-water-from-space/). The book's own new review chapter `00a:235` correctly calls it total water storage. An independent forcing/model chain can be a valuable cross-check but is not independent ground truth; **#195** correctly labels ERA5-Land/NLDAS model intercomparisons.

**Consequence.** A groundwater model can seem validated against a quantity dominated by snow or surface water. Distinct model names do not prove independent errors. SMAP surface versus root-zone/L4 products also require distinct depth/support and assimilation-lineage metadata.

**Roadmap disposition.** Tighten **#29/#189/#195/#204** with explicit TWS compartment accounting, mascon support/leakage, and product-level lineage. Roles must be mutually exclusive per datum/run, not permanently by broad dataset family (e.g. some wells assimilated, other wells held out).

**Required gate.** Compare GRACE to summed modeled storage at its real footprint, or explicitly derive groundwater with an uncertainty-bearing partition. Declare model intercomparison versus independent measurement validation in every metric table. Use source versions and acquisition/availability dates.

### S12 — P2: Scientific novelty and literature descriptions need correction

**Evidence.** `docs/twin/03a-physics-hydrology.qmd:26-30` says Fan et al. (2013) regressed water-table depth on 17 variables. The primary article abstract describes observations plus a groundwater model forced by climate, terrain and sea level. [Fan et al. 2013, original abstract](https://pubmed.ncbi.nlm.nih.gov/23430651/). Lines `:42-45` make an unqualified claim that no published product combines the named elements. The broader literature-review chapter is more restrained and explicitly calls for simpler baseline comparisons (`00a:272-276`).

**Consequence.** Misclassifying the comparator weakens the scientific motivation and may bias roadmap benchmarking toward a straw-man baseline.

**Roadmap disposition.** Correct under **#204**, audit source-to-claim mappings for the major physical equations and competitor descriptions, and replace absolute novelty claims with a dated, scoped comparison table.

### S13 — P2: Assumptions and limitations are a stale product contract

**Evidence.** `docs/assumptions.md:10-22` still uses 1 km cells, 50 km distance rules, 150 m well screening and a GRACE-driven temporal predictor. `docs/limitations.md:12-15,23-33` focuses on national/arid/karst/permafrost issues and labels monthly aliasing low impact. `README.md:87-99` still describes a monthly Puget pilot, while the book describes a daily 2.96-million-cell western-Cascades domain. The assumptions changelog remains `_today_`.

**Consequence.** A supposed living limitations register no longer bounds the implemented product, and a human reviewer cannot tell which assumptions apply to a run. For an event-hazard model, monthly aliasing cannot remain a low-impact blanket limitation.

**Roadmap disposition.** **#204** and **#187** should jointly derive these documents from a versioned scientific contract. Add explicit statuses and evidence for shallow/perched versus confined head, missing vadose storage, model/time-step identity, petrophysical calibration, measurement support, approximate barriers and applicability.

## Prior-review reconciliation

The July review's fabricated HAND-to-Vs30 complaint has been materially addressed by the SVM/Wald–Allen source descriptions and explicit 200 m native Vs support. Do not repeat it as a current unchanged defect. The book correctly demotes shared-forcing TerraClimate and MERRA-2 correlations, acknowledges no live end-to-end FuXi run, discloses broad hillslope extrapolation, and now contains the excellent hazard tiering and digital-shadow framing.

PR #212 has materially improved the MVP metric table (`docs/twin/05-state-evaluation.qmd:445-498`): real/model/synthetic categories, R²≈0.09, 200 km fallback-CV versus variogram-block disagreement, and the snow tuning generalization failure are now explicit. Do not describe that table as still unlabelled. The water-budget table at lines 383-386 and operational-network claims remain contradictory. The July recommendations on depth mismatch, independent evaluation, closed storage and operational cycling remain only partially reconciled. The issue graph accurately carries them, but the book still promises them elsewhere. The August review and merged #217 introduce explicit head/DTW/storage/pressure vocabulary, water-table measurement classification, separate prior hyperparameters per state, and variance-reduction/averaging-kernel distinctions. These are valuable implemented improvements; full operational propagation remains open. The dimensional k_sat, conditional-linear RBPF and static virtual-observation errors survive those additions.

PR #216 also removes the dense-prior representation requirement with StationaryGridPrior. The measured benchmark separates ν change from SPDE boundary effects and explicitly says numerical scalability is not evidence of 90 m resolving power (`docs/reviews/prior-operator-benchmark.md:319-343,371-389`). Do not repeat a full-domain dense-B requirement as an unresolved universal architecture defect; the production run and fitted/scientifically appropriate covariance are separate remaining questions.

The **#163** comments provide a positive example of review changing a proposed method: the plan now separates statistical model choice from numerical scalability, recognises ν changes as a confound, and asks whether anisotropy is estimable before adding a backend. Its latest parked status is **not evidence of a scientific impasse**: the park metadata on 2026-08-22 says the sole blocker is `unrecognised verdict None`, with decisive test `re-run the persona`. That should trigger invalid-review recovery rather than force a human to adjudicate a nonexistent scientific verdict.

The **#186** comments also show productive iteration toward skew-aware quantiles, units, synthetic oracles and honest calibration limitations. However, a scientifically correct estimator fix and independently calibrated product are distinct milestones. A release cannot inherit a previous `#5 closed` calibration claim after changing the predictive law without re-evaluation.

## Suggested science acceptance sequence

1. **Define the scientific objects before parallel implementation:** storage/head/DTW/pressure/depth support, compartments, observable operators, units, parameter modes, uncertainty sources and evidence status (**#52/#137/#171/#172/#186/#187/#198**).
2. **Run a compact deterministic conservation/operator fixture:** capillary exchange, transit/perched response, head sign/units, gauge flux and common forward/inverse petrophysics. A code test alone must not certify empirical parameter validity.
3. **Run a true small cycling experiment:** real timestamped observations, physical/representation R including dv/v covariance, no self-generated observations counted as evidence, auditable increments, replayable state, and downstream derived variables recomputed after each update (**#164/#188/#189/#192**).
4. **Establish independent value added:** fixed station/basin/event holdouts; identical forcing in open-loop versus DA comparisons; calibrated proper scores and event/anomaly skill, with failures retained (**#194/#195**).
5. **Demonstrate one regional hazard handoff:** pressure/relative-wetness semantics for landslides, probabilistic regional susceptibility for liquefaction, or member-preserving routed discharge for floods; benchmark against an established simpler baseline (**#129/#141/#193/#199-202**).
6. **Escalate only on evidence:** nonlinear branch particles, terrain-anisotropic priors, new disturbance parameters and fine-scale hazard models should be gated on identifiability, observed failure of a simpler model, and availability of independent validation data.

Recommended reviewer expertise by issue group: hydrologic storage and fluxes; hydrogeologic measurement targets and applicability; rock physics/coda sensitivity; statistical inference and calibration; hazard-specific downstream mechanics; independent validation/data lineage. The panel should distinguish `implementation correct`, `assumption uncalibrated`, `empirical target met`, and `scope limited`. Convergence of agents on one answer is not an empirical acceptance test.


## Executed counterexample on authoritative main

No code was patched. The test imports main `435445f17b90e1cdc4ee4e12a9e1cb17338f7e3f` directly. Run:

```bash
python reproduce_capillary_mass.py /path/to/audited-main-checkout
```

A one-day isolated column starts at θ_wp=0.1, with θ_fc=0.3, θ_sat=0.5, a 1 m root zone, 0.5 m water-table depth, S_y=0.3, and no rainfall or PET. The capillary-off control has only float32 rounding residual (1.49e-6 mm). With the default 30 mm/month capillary limit:

| Accounting quantity | Result |
|---|---:|
| Capillary transfer into root zone | 0.7392348647 mm |
| Root storage increase | 0.7392331958 mm |
| Groundwater storage change | 0 mm |
| External water input | 0 mm |
| External water output | 0 mm |
| **Unexplained net water created** | **0.7392331958 mm** |

Results are stored in `capillary-mass-result.json`. The defect exceeds numerical rounding by roughly 500,000× and disappears in the capillary-off control. This is an implementation-level falsification of the exact-conservation claim, not an empirical calibration inference. It substantiates existing #172 and should be a required regression test for its fix.

## Verified main citation index for the most consequential findings

| Finding | Main path and lines | Existing work to sharpen |
|---|---|---|
| S1 capillary mass creation | src/models/water_budget.py:217-219,266-278; docs/twin/03a-physics-hydrology.qmd:49-87 | #171/#172/#187/#188 |
| S2 calibration labelled independent | docs/twin/05-state-evaluation.qmd:378-386; docs/twin/03a-physics-hydrology.qmd:206-221 | #137/#175/#186/#194/#195 |
| S3 false conditional-linear RBPF | docs/twin/04-assimilation.qmd:800-812 | #198/#162/#204 |
| S4 dimensional/sign error in k_sat | docs/twin/03b-physics-hydromechanics.qmd:88-101 | #198/#165 |
| S5 gauge/probe quantity mismatch | docs/twin/04-assimilation.qmd:109-121,521-553,694-710 | #189/#165/#201 |
| S6 invalid virtual-observation equivalence | docs/twin/05-state-evaluation.qmd:270-318 | #192/#194/#204 |
| S7 claimed assimilated streams versus synthetic use | docs/twin/05-state-evaluation.qmd:11-23; docs/twin/06-forecast.qmd:64-71; notebooks/make_twin_gif.py:212-244 | #188/#189/#191/#194/#204 |
| S8 depth/attribution identifiability | docs/twin/03b-physics-hydromechanics.qmd:142-147; docs/twin/03c-memory-disturbance.qmd:102-110 | #164/#168/#169/#198 |
| S9 incorrect Landlab API/adapter claim | docs/twin/07-hazard-integration.qmd:59-61 | #127/#128/#129 |
| S10 hazard-grid versus decision scale | docs/twin/index.qmd:28-32; docs/twin/07b-resolution-requirements.qmd:29-51,82-112 | #135/#140/#147/#199/#204 |
| S11 GRACE groundwater versus TWS | docs/twin/02-evaluation-data.qmd:18,35-36 | #29/#189/#195/#204 |
