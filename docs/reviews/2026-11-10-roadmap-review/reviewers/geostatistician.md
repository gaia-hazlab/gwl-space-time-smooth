# Reviewer round: twin-geostatistician (2026-11-11)

Read-only agent report, transcribed. "#N" = read from the issue in the 2026-11-09 snapshot;
`file:line` = opened by the agent. Nothing rerun. My check of each probe is in `adopt-reject.md`.

## Leads

| Lead | Verdict | Evidence |
|---|---|---|
| L1 Gaussian-only verification code | confirmed | `src/evaluation/coverage.py:36-57` closed forms only; grep of `src/` for rank_hist, desroziers, energy_score, variogram_score, crps_ensemble, brier: 0 hits |
| L2 no numeric thresholds in the hydrologic filter issues | confirmed, with a regression | #188, #306: "rank histograms, 90 % coverage, lag-1 innovation autocorrelation per stream with a stated threshold" (no number); #188's archived scope had "spread/RMSE ratio within 0.8-1.2" and the rescope dropped it |
| L3 geometry and structure not in members | partly | #289 `Ensemble(members, param_sets, forcing_perturbations, seed)`; #292 "indexed so a PEST++ realization can carry one": geometry reaches PEST++ only; structural members exist only for the statistical stack (#32) |
| L4 forcing uncertainty | confirmed | #70 keeps TerraClimate versus PRISM as "the forcing-spread item"; #188 AR(1) perturbations with no source for the magnitude; #241, #191 carry precipitation and temperature only |
| L5 compound and threshold probabilities | partly | #193 "P(FS < 1)", #258 "P(Q > Q_T)", #191 "threshold probabilities" (unnamed, no support); no joint probability across hazards |
| L6 IES posterior width | confirmed | plan.md:198-199 "recorded, not solved"; #284 tests the prior range only |
| L7 effective sample size in #305 | partly refuted | #305 has "minimum n per stratum and spatial-block bootstrap confidence intervals"; missing: n_eff, blocking in time, event clustering |
| L8 sub-metre DTW need | partly refuted | #142: "about 1.5-2 m for the #141 screen, sub-metre only for #146" |

## Uncertainty budget implied by the roadmap

| Source | Treatment | Owner |
|---|---|---|
| Forcing, hindcast | members (AR(1), two products); magnitude uncalibrated; PRISM undercatch not sampled | #188, #70, #32 |
| Forcing, forecast | members (P, T); the #242 downscaler is deterministic, its error ignored | #241, #191, #242 |
| Initial state | members | #191 from #306 |
| Parameters | members; posterior width never checked | #284, #285, #289 |
| Geometry | sampled in #292, ignored by the filter | #292 |
| Model structure | ignored; benchmarks only | #294, #295, #302, #192 |
| Observation | analytic R | #189, #164, #239 |
| Representativeness | analytic for soil moisture; for wells estimated, never in the filter | #290, #284, #7 |
| Proxy operator (dv/v) | kernel ensemble added into R | #168, #198 |
| Hazard inputs | Vs30 degenerate; FS gets a first-order sigma | #193, #128 |
| 90 m to hazard support | ignored | none |

Largest ignored term per consumer (agent ranking):

| Consumer | Term | Reason given |
|---|---|---|
| Landslide | structure (perched pressure) and downscaling below 90 m | #128: regional h_w "near zero on most hillslopes", so head spread barely moves FS |
| Liquefaction | Vs30 | #142: 1 m of DTW is about 0.008 in P; Vs30 enters directly and is sampled nowhere |
| Flood | precipitation pattern below 0.25 degrees | #136: bias correction "cannot recover event-scale spatial structure" |
| Wildfire | operator from root-zone water to fuel | no consumer issue |

## Variance reduction versus resolution

- #191 outputs per-cell sigma, quantiles and threshold probabilities with no support field.
- #283 allows MODFLOW cells of k x 90 m under the 90 m ledger; one 270 m head copied to nine cells
  is one cell's information shown nine times; no issue owns that change of support.
- `src/evaluation/uncertainty_stack.py:195-199` adds dependent sigmas in quadrature, which #32
  forbids; sigma_response is scaled by an undeclared 5.0 m (`:191`).
- Change-of-support owners: storm-time landslide (1-10 m): none; MODFLOW heads to 90 m: none;
  liquefaction and flood are safe while members survive (#193, #200).

## Verification design gaps

Fair CRPS, rank histogram, Desroziers and NIS code (new); energy and variogram scores (#195 a);
threshold-weighted CRPS and Brier at named thresholds with support (#195 b); n_eff and time blocking
(#305); a static susceptibility map as the hazard reference forecast (#195 b); multiple-testing
control across lead x domain x season x stream.

## Proposals

1. New: ensemble scoring library `src/evaluation/ensemble_scores.py`. Acceptance: the variogram score
   ranks the coherent ensemble above the independent one in >= 95 % of bootstrap draws on the 18
   #299 configurations.
2. Amend #188, #306, #286: restore numeric thresholds (spread/RMSE 0.8-1.2; 90 % coverage +-0.05).
3. New: does IES under-cover when the model is wrong? Synthetic nature run on a different #292
   framework. Blocked by #284, #292.
4. Amend #289, #187: framework-realization argument on the ensemble.
5. New: change-of-support operator (270 to 90 m, 90 to 10 m) carrying its variance; `support_m`
   stamped on #191, #193 products. Blocked by #187, #283 (a).
6. Amend #305: n_eff per stratum; bootstrap blocked in space and time.

Decision raised: whether #193 also owns joint probabilities across hazards from shared members.
