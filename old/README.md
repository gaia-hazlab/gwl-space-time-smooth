# `old/`

Not an inert archive: **11 `pixi run` tasks execute scripts under `old/notebooks/` directly**
(`products-90m` `pixi.toml:109`, `ensemble-dvv` `:111`, `dvv-demo` `:116`, `forecast-leadtime`
`:122`, `hindcast` `:168`, `digital-twin` `:170`, `water-budget` `:172`, `well-screen` `:174`,
`static-layers` `:176`, `landlab-export-figure` `:180`, and `demo` `:182`, which chains four of
the scripts below plus a `quarto render` of `old/docs/gwl_soil_moisture_demo.qmd`). Those tasks
were repointed to these paths rather than deleted, so the scripts they invoke are load-bearing
and have to keep working, the same as any script under `notebooks/`.

**"Not maintained" only applies to the two `old/docs/` report sources and the four exploratory
notebooks below** — nothing else here is a dead archive.

`import`-wise the original claim holds: nothing under `old/` is imported by `src/` or by the
`notebooks/` figure generators (verified by grep; no `from old`/`import old` anywhere outside
`old/` itself). The coupling to the 11 live tasks above is *invocation*, not import — `pixi run
<task>` runs `python old/notebooks/X.py` as a subprocess — but invocation is still a real
dependency: renaming an input file those scripts read (e.g. under `data/processed/`) breaks the
task that calls them.

## `old/notebooks/` — load-bearing scripts (invoked by the pixi tasks named above)
- `make_products_90m.py` — `products-90m`
- `make_ensemble_dvv_figures.py` — `ensemble-dvv`, and again inside `demo`
- `make_dvv_figures.py` — `dvv-demo`
- `make_forecast_leadtime.py` — `forecast-leadtime`, and with different flags by `hindcast`
- `make_digital_twin.py` — `digital-twin`
- `make_water_budget_figure.py` — `water-budget`
- `make_well_screening_figure.py` — `well-screen`
- `make_static_layers_figure.py` — `static-layers`
- `make_landlab_export_figure.py` — `landlab-export-figure`
- `demo_gwl_sm.py`, `build_demo_qmd.py` — chained (with `make_products_90m.py` and
  `make_ensemble_dvv_figures.py` above) into `demo`

## `old/notebooks/` — genuinely inert
No pixi task or import references these; kept for provenance only: `01_eda.ipynb`,
`02_hydrogen_eda.ipynb`, `03_temporal_model.ipynb`, `1-HydroGEN Retrieval.ipynb`.

## `old/docs/`
- `gwl_hybrid_framework.qmd` — the original single-file technical report, superseded by the
  linked chapters in `docs/twin/`. The source `.qmd` is not re-rendered by any pixi task; its
  previously-committed render is still served at `/report.html`.
- `gwl_soil_moisture_demo.qmd` — the Puget-pilot GWL + soil-moisture demo page, rebuilt by the
  `demo` task (via `build_demo_qmd.py`, then `quarto render`). Its render is served at
  `/gwl_soil_moisture_demo.html`.
