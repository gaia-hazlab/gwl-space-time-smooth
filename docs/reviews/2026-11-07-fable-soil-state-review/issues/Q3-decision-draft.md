# Draft decision record for #309: one snow model and one root-zone bucket

Status: draft for the PI, posted as a comment on #309 on 2026-11-09; the decision line in section 6 is the PI's. Facts read from `435445f` (the review branches do
not change `src/`). Evidence: `results/l2_reinitialisation.json` (PR #315), `data/processed/snow_calibration.json`.

## 1. What exists today

| | Snow model A | Snow model B | Root bucket A | Root bucket B |
|---|---|---|---|---|
| Function | `forecast.liquid_input` (`src/models/forecast.py:105-131`) | `soil_moisture.snowmelt_liquid_input` (`src/models/soil_moisture.py:205-228`) | `water_budget.coupled_water_budget` (`:119-284`) | `soil_moisture.total_water_bucket` (`:162-190`) |
| Step | the forcing's own step (daily for PRISM, 6 h for FuXi) | monthly (`days_in_month`) | daily or legacy monthly (`dt_days`) | monthly only |
| Parameters | DDF 3 mm/degC/d; snow below 0 degC, rain above 4 degC; melt above 1 degC | DDF 3; snow below -1 degC, rain above 3 degC; melt above 0 degC | drainage e-folding 2 d (daily) or 0.6/month (legacy); S_y, HAND sink, interflow, capillary term | drainage 0.6/month; water above field capacity leaves the system; no aquifer |
| Provenance | D8 (#100): melt-out timing against SNOTEL SWE; code says 28 stations, ROADMAP says 30; `notebooks/calibrate_snow_swe.py`; no committed artifact | nominal; the 5-station grid search overfit (`snow_calibration.json`: LOSO r 0.439 calibrated vs 0.493 default), so defaults are used | D7 (#98) on gauges and wells, with the undebited capillary term active (#297) | none |
| State carried across calls | none (SWE starts at zero, `:123`) | none (`:216`) | none (`init` label, `wt_depth0_m`) | none |
| Callers | `forecast_soil_state`; `calibrate_fluxes.py`; `make_validation_figure.py` | `soil_moisture.apply_snow_if_available` (the monthly 90 m soil-moisture product, `:231-237`, `:292`); `validate_snotel.py`; `calibrate_snow.py`; `tests/test_coupling.py:69` | `forecast_soil_state`; `landlab_export.py:304`; `calibrate_fluxes.py`; `close_basin_budget.py`; `make_validation_figure.py`; `tests/test_water_budget.py`, `test_forecast.py` | soil-moisture product (`:292`, `:452`); `validate_snotel.py`; `calibrate_snow.py`; `anchor_snotel.py`; `tests/test_soil_moisture.py` |

A third root-zone representation, `thornthwaite_mather_wetness` (plant-available, capped at field
capacity, `:121-155`), is the source of the two-theta ambiguity in #52. The Landlab export
(`landlab_export.py:304`) passes precipitation to the bucket with no snow model at all.

## 2. What the evidence says

| Quantity | Value | Source |
|---|---|---|
| Liquid input over one synthetic 120-day winter, model A vs B | 458 vs 510 mm | `l2_reinitialisation.json` `two_snow_models` |
| Days on which the two models give different liquid input | 60 of 120 | same |
| Largest daily difference | 8.6 mm | same |
| Melt lost when a forecast restarts mid-winter (model A, SWE reset to zero) | 50 of 150 mm | same, `snow_restart` |
| LOSO correlation of the 5-station tuning of model B | 0.439 tuned vs 0.493 default | `snow_calibration.json` |

## 3. Options

| Option | Content | For | Against |
|---|---|---|---|
| (a) recommended | Owner = `forecast.liquid_input` for snow and `coupled_water_budget` for the root zone. `snowmelt_liquid_input` becomes a thin wrapper (monthly call scaled by `days_in_month`) and is deleted once its four callers migrate; `total_water_bucket` becomes a wrapper of `coupled_water_budget` with `cap_max_mm=0`, a deep `wt_depth0_m` and `dt_days=None`, then is deleted; `thornthwaite_mather_wetness` stays only as a named plant-available diagnostic | one step convention matching PRISM, FuXi and the MODFLOW daily stress period; the only snow parameters with a stated SWE-based objective; the only bucket with a ledger and the aquifer exchange the MF6 partition replaces; one place to add the carried SWE and root state (#234, #187) | the monthly soil-moisture product and its SNOTEL/MERRA-2 comparisons change numerically and must be rerun; the 28/30-station calibration has no committed artifact and must be reproduced before it is called the owner's calibration |
| (b) | Keep both pairs, force one shared parameter set and one `SnowState` | smaller diff | two integrators of the same store remain; restart and ledger must be built twice |
| (c) | Owner = the `soil_moisture` pair | monthly product unchanged | monthly step cannot carry a storm; nominal parameters that overfit when tuned; no aquifer, water leaves the system |

## 4. Consequences if (a) is decided

- #234: `liquid_input(forcing, swe0=None) -> (liquid, swe)`; SWE carried and restartable; the segmented-run test in `tests/test_forecast_restart_legacy.py` flips from `xfail` to pass; `landlab_export.py:304` and `apply_snow_if_available` call the same function.
- #52: the product theta is the total-water theta of the single owner; sigma uses the same pedotransfer partials; `thornthwaite_mather_wetness` is labelled diagnostic.
- #232 (a): the ledger test covers the single owner only.
- Reproduce the melt-out calibration (`notebooks/calibrate_snow_swe.py`) and commit its artifact with the station count; fix the 28-versus-30 discrepancy in `forecast.py:53` or `ROADMAP.md:52,147`.
- Rerun `validate_snotel.py`, `anchor_snotel.py` and the MERRA-2 comparison on the owner; record the change in `docs/limitations.md`.
- `tests/test_coupling.py:69` (snow mass conservation) moves to the owner.

## 5. Acceptance for the follow-up PRs

- One function each for snow and root zone is imported by every caller listed in section 1 (grep-enforced test).
- `tests/test_forecast_restart_legacy.py::test_segmented_snow_run_equals_continuous_run` passes.
- The monthly product rerun is reported against the SNOTEL stations with before/after statistics; a worse result is recorded, not hidden.
- `TRACKER.md` row Q3 updated with the decision and date.

## 6. Decision (to be filled by the PI)

Decision: ______ (option a / b / c, or other). Date: ______. Label `needs-human-decision` removed by the PI.
