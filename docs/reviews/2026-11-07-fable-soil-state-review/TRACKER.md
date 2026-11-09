# Tracker: soil-state validation ladder

Regenerated 2026-11-09 17:36Z by `scripts/review_tracker.py` from GitHub. Outcome and evidence columns come from `outcomes.json` (hand-maintained by the PR that completes a row); state, blockers and dates come from GitHub. Record: `README.md` in this folder; epic: gaia-hazlab/gwl-space-time-smooth#296.

## Ladder

| key | issue | type | batch | blocked by | state | outcome | evidence | date |
|---|---|---|---|---|---|---|---|---|
| R0 | gwl-space-time-smooth#296 | epic | 0 | none | PR |  |  | 2026-11-09 |
| L1 | gwl-space-time-smooth#297 | experiment | 0 | none | PR | fail (defect confirmed): +0.2464 mm/d created at DTW 1.5 m, 79.3 mm/yr; valley cell without sink reaches the surface on day 158 from rain alone | results/l1_closed_column.json; tests/test_ledger_legacy.py (xfail strict on combined conservation) | 2026-11-09 |
| L2 | gwl-space-time-smooth#298 | experiment | 0 | none | PR | fail (defect confirmed): segmented snow run loses 50 of 150 mm melt; no state argument; theta_ref post-step; centring leakage -0.30 m; two snow models differ on 60 of 120 days | results/l2_reinitialisation.json; tests/test_forecast_restart_legacy.py (xfail strict on segmented equivalence) | 2026-11-09 |
| U1 | gwl-space-time-smooth#299 | experiment | 0 | none | PR | sensitivity recorded: P(min DTW over 1.8 km < 1 m) 0.08-0.55 coherent vs 0.75-0.99 independent across 18 configurations | results/u1_dependence_sensitivity.json; tests/test_dependence_sensitivity.py | 2026-11-09 |
| C1 | gwl-space-time-smooth#300 | experiment | 0 | none | PR | confirmed: Landlab 2.10.1 LandslideProbability lists none of the exported fields; failure probability monotone in recharge mean (0.0071 at 20 mm/d to 0.0279 at 60 mm/d, then saturated); outputs bit-identical under x0.5 and x2 of exported DTW, saturation and recharge-rate fields | results/c1_landlab_causal.json; tests/test_landlab_consumer.py (skips without landlab) | 2026-11-09 |
| P1 | gwl-space-time-smooth#301 | experiment | 0 | none | PR | measured 34.5 ns per cell-step (one member); 400^2 tile 2.18 s; 800^2 refused by preflight; domain member-year projected 56 s; full history 113 GB if allocated | results/p1_bounded_performance.json | 2026-11-09 |
| H1 | hydrostate#1 | experiment | 0 | none | open |  |  | 2026-11-09 |
| H2 | hydrostate#2 | docs | 0 | none | open |  |  | 2026-11-09 |
| M1 | mechanicalstate#1 | experiment | 0 | none | open |  |  | 2026-11-09 |
| X1 | gwl-space-time-smooth#302 | experiment | 1 | #275 | open |  |  | 2026-11-09 |
| X2 | gwl-space-time-smooth#303 | experiment | 1 | #275 | open |  |  | 2026-11-09 |
| Q1 | gwl-space-time-smooth#307 | decision | 2 | #302 | held |  |  | 2026-11-09 |
| Q2 | gwl-space-time-smooth#308 | decision | 2 | #303 | held |  |  | 2026-11-09 |
| Q3 | gwl-space-time-smooth#309 | decision | 2 | #298 | held | awaiting PI decision; draft record posted recommending option (a): forecast.liquid_input owns snow, coupled_water_budget owns the root zone, soil_moisture pair wrapped then deleted | issues/Q3-decision-draft.md; https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/309#issuecomment-6746956342 | 2026-11-09 |
| Q4 | gwl-space-time-smooth#310 | decision | 2 | #302 | held |  |  | 2026-11-09 |
| X3 | gwl-space-time-smooth#304 | experiment | 4 | #289 | open |  |  | 2026-11-09 |
| B188 | gwl-space-time-smooth#306 | feature | 4 | #9, #188, #235, #285 | open |  |  | 2026-11-09 |
| X4 | gwl-space-time-smooth#305 | experiment | 5 | #235 | open |  |  | 2026-11-09 |
| Q5 | gwl-space-time-smooth#311 | decision | 6 | #230 | held |  |  | 2026-11-09 |
| QF | gwl-space-time-smooth#312 | decision | 6 | #297, #298, #299, #300, #301, #302, #303, #304, #305, #307, #308, #309, #310, #311 | held |  |  | 2026-11-09 |

## Amended existing issues

| issue | title | state | blocked by | updated |
|---|---|---|---|---|
| #232 | Whole-system water ledger: land-surface stores now, then coupled LSM + | open | none | 2026-11-09 |
| #280 | Land-surface to MODFLOW exchange: exact block aggregation, drainage ou | open | #232, #265, #275, #302, #307 | 2026-11-09 |
| #282 | Transient pilot: daily stress periods, UZF, warm-up rule, multi-year h | open | #70, #234, #280, #281 | 2026-11-09 |
| #283 | Grid resolution and layering convergence study for the pilot (90 / 180 | open | #281 | 2026-11-09 |
| #286 | Held-out validation of the calibrated pilot (wells, recorders, gauge)  | open | #236, #285 | 2026-11-09 |
| #142 | Seasonal-high depth-to-water in liquefiable units: sub-1.5 m accuracy, | open | #9, #286 | 2026-11-09 |
| #270 | Value-of-information gate: does the dynamic water table matter in the  | open | #143, #144, #260 | 2026-11-09 |
| #188 | Cycling localized ensemble nowcast on MODFLOW 6 + land surface: exact  | open | #187, #289 | 2026-11-09 |
| #289 | MODFLOW 6 ensemble runner over modflowapi: pause, update, resume betwe | open | #155, #275, #280 | 2026-11-09 |
| #187 | P0: Define the canonical probabilistic state, parameter, forcing, and  | open | #52, #265 | 2026-11-09 |
| #234 | Snowpack as a carried state (SWE initial condition) + rain-on-snow / l | open | none | 2026-11-09 |
| #52 | P1: Resolve the two-theta ambiguity (estimate_soil_moisture vs total_w | open | none | 2026-11-09 |
| #191 | P1: Make SoilStateForecast ensemble-native and initialize it from the  | open | #188 | 2026-11-09 |
| #230 | P0 bug: Stage-3 DTW assembly adds water-table-elevation anomalies to d | open | none | 2026-11-09 |
| #195 | P1: Calibrate and validate probabilistic nowcasts and forecasts by lea | open | #191, #194 | 2026-11-09 |
| #235 | Ingest continuous groundwater recorders + frozen well/basin holdout ma | open | none | 2026-11-09 |
| #189 | P1: Operationalize ground-sensor observation records, operators, QC, a | open | #9, #187 | 2026-11-09 |
| #247 | Kernel sanity: codameter band kernels are not normalized and have larg | open | none | 2026-11-09 |
| #198 | P0: Use one depth-resolved hydromechanical operator for forward predic | open | #187, #247 | 2026-11-09 |
| #127 | [epic] LandLab landslide handoff — from hydrology to a factor-of-safet | open | #231 | 2026-11-09 |
| #129 | Run LandLab LandslideProbability end-to-end on a pilot corridor and sc | open | #128 | 2026-11-09 |
| #193 | P2: Propagate joint hydrologic, parameter, forcing, and mechanical ens | open | #187 | 2026-11-09 |
| #260 | Decision record: pin the liquefaction model, version and probability s | open | none | 2026-11-09 |
| #141 | MVP: geospatial liquefaction GLM driven by the dynamic seasonal-high w | open | #260, #270 | 2026-11-09 |
| #267 | Port and fix the rainier3d 1-D Richards solver as a reference column a | open | none | 2026-11-09 |

## Decision log

| question | prerequisite evidence | decision | date | decided by |
|---|---|---|---|---|
| (none yet) | | | | |
