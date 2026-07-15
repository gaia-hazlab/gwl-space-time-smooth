# Archived materials

Superseded by the multi-chapter twin report under [`docs/twin/`](../docs/twin/). Kept for provenance,
not maintained. Nothing here is imported by `src/` or by the current twin figure generators.

## `old/docs/`
- `gwl_hybrid_framework.qmd` — the original single-file technical report. Replaced by the linked
  chapters in `docs/twin/`. Its committed render is still served at `/report.html`.
- `gwl_soil_moisture_demo.qmd` — the Puget-pilot GWL + soil-moisture demo page (built by
  `build_demo_qmd.py`). Its committed render is still served at `/gwl_soil_moisture_demo.html`.

## `old/notebooks/`
Figure generators that fed **only** the archived report/demo (the twin uses its own generators in
`notebooks/`): `make_products_90m`, `make_digital_twin`, `make_dvv_figures`,
`make_ensemble_dvv_figures`, `make_water_budget_figure`, `make_landlab_export_figure`,
`make_well_screening_figure`, `make_forecast_leadtime`, `make_static_layers_figure`, plus the demo
builders `demo_gwl_sm` and `build_demo_qmd`. Exploratory notebooks: `01_eda`, `02_hydrogen_eda`,
`03_temporal_model`, `1-HydroGEN Retrieval`.

Their `pixi run` tasks (e.g. `demo`, `digital-twin`, `products-90m`, `water-budget`,
`forecast-leadtime`) still resolve — they were repointed to these `old/` paths, not deleted.
