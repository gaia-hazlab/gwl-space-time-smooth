# Reviewer round: twin-da-methodologist (2026-11-11)

Read-only agent report, transcribed. `[#N]` = issue body in the 2026-11-09 snapshot; `[plan:L]` =
`docs/reviews/2026-10-18-modflow-groundwater-core/plan.md` line L. Nothing rerun. My check of each
probe is in `adopt-reject.md`.

## Verdict

#188, #289 and #306 specify an ensemble Kalman filter that can be checked on its fixture. They do
not specify a production filter for a state of 1e6 to 1e7. Production ensemble size, localization
radius, cross-variable rules and the non-forcing part of Q are missing. The dependency graph has
one cycle hidden in an acceptance bullet and six missing edges.

## Leads

| Lead | Verdict | Evidence |
|---|---|---|
| L1 filter named, N | partly | [#188] "the EnKF at N = 500 matches the exact Kalman mean"; [plan:187] "LETKF or EnSRF"; only production-scale N is [#283] "projected cost of an N = 50 cycling filter" |
| L2 localization | partly | [#188] "tapers with distance and hydrogeologic connectivity; no hard zeros across layers"; no radius; vertical rule only [plan:203]; no cross-variable rule |
| L3 Q | partly | [#188] "AR(1)-perturbed precipitation, temperature and LSM drainage; parameter ensemble from PEST++"; [#284] GHB and SFR conductance multipliers; nothing adds error to heads; no land-surface parameter in any ensemble |
| L4 graph | confirmed | [#289] "clip rule that #304 shows passes" while [#304] "Blocked by: #289"; [#289] "decision #308 fixes the operation mode" with #308 off its blocker line; [#191] "Blocked by: #188." yet "Posterior initial conditions come from #306" |
| L5 gauge in both loops | confirmed | [#284] "baseflow at the pilot gauge"; [#306] "Gauges as total SFR outflow"; [#235] role rule is per "well-year" |
| L6 missing sensors | confirmed | SWE: [plan:236] points to #234, which has no operator; Sentinel-1 only in archived #109; GNSS-IR no issue; [#291] "no operator code in this issue"; GRACE context only |
| L7 proxy contract | partly | per-stream pieces: [#290] "anomaly or CDF matching", [#198] AR(1) bias state, [#239]; the observability condition is archived text only |
| L8 non-Gaussian, smoother | partly | [#304] single column only; smoother only in [#162] (attribution, held); joint estimation "is a later comparison" [#284] |
| L9 UZF and lead time | partly | [plan:172] "advanced but not updated"; [#303] UZF initialised "only through thti" |

## Three gaps most likely to pass the fixture and fail the pilot

| Gap | Mechanism | Decisive test |
|---|---|---|
| N and localization unset | fixture is one layer at N = 500 and needs no localization; pilot near N = 50 against > 1e6 unknowns; the gauge is a basin integral with no distance for a taper | multi-layer confined linear fixture, 30 wells, Matern L = 12 km, exact Kalman reference; localized filter at N = 20, 50, 100; analysis variance at held-out cells within 10 % of exact, gauge rule included |
| Q from forcing and the PEST++ posterior only | narrow parameter ensemble, deep layers respond weakly to forcing, spread collapses and inflation hides it | OSSE whose nature run uses a #292 geometry realization absent from the ensemble; spread/RMSE in 0.8-1.2 per layer over 365 cycles with inflation inside its stated bound |
| time convention tested with synchronous data only | [#9] evaluates at the measurement time, [#289] updates between stress periods | linear fixture with sub-daily observation times; increment under the assign-to-boundary rule against the exact filter at true times |

## Minimal proxy contract before assimilation

1. Forward operator on the model state at native support, never an inverted retrieval.
2. R with a cited source, including representativeness and temporal correlation (#239).
3. Declared bias treatment; a bias state only where an unbiased direct stream sees the same state
   inside the localization radius, otherwise anomalies.
4. An independent reference used to fit 2 and 3, kept out of both estimation loops.
5. A #235 role and a held-out value test, with "no value" an acceptable result.

| Sensor | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Wells (direct) | #9 | #9 | n/a | n/a | #235 |
| Gauge | #237 | #237 | none | none | dual role |
| Probes | #290 | #290 | none | none | #235 |
| SMAP | #290 | #290 | #290 | none | none |
| NISAR | #290 | #290 | none | none | none |
| dv/v | #198 | #164, #168 | #198 | none | #306 |
| GNSS, InSAR, SWE, Sentinel-1, GNSS-IR, GRACE | no | no | no | no | no |

No proxy meets all five on paper.

## Reanalysis

A smoother product is needed and unowned: seasonal-high depth to water is retrospective, and filter
analyses ignore later recession data and carry the update sawtooth; [#142] takes it from the
calibrated open-loop ensemble (#286). A smoothed product must never enter #305 evaluations.

## Proposals

| # | Title | Acceptance | Blockers |
|---|---|---|---|
| P1 | Amend #289, #188: constraint hook | the #304-selected rule runs in #188 (a) | see edits |
| P2 | Split #306 (c) into its own issue | per-sensor DFS and held-out scores | #306, #237, #290, #198, #164, #239, #30, P6 |
| P3 | Production estimator specification and scale test (amends #192) | gap-1 test | #188, #283 |
| P4 | Complete Q: additive head error, boundary-stage error, land-surface parameter ensemble | gap-2 OSSE | #188, #285, #292, #309 |
| P5 | Gauge-year is one datum (#235, #284) | #284 test rejects any gauge-year outside the calibration role | #235 |
| P6 | Proxy admission contract | synthetic with known AR(1) bias: recovered when the reference is present, declared unobservable when absent | #189, #235, #239 |
| P7 | Ensemble smoother reanalysis | matches exact RTS on the linear fixture; lower seasonal-high error than the filter at held-out wells | #306 |

Blocker-line edits: #289 `Blocked by: #275, #280, #155, #308.` and its #304 bullet becomes "Exposes
the analysis-constraint hook."; #188 `Blocked by: #289, #187, #304.`; #306 `Blocked by: #188, #285,
#9, #235.` with slice (c) moved to P2; #191 `Blocked by: #187, #306, #241.`
