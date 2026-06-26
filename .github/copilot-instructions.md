# gwl-space-time-smooth — Workspace Instructions

Reproducible, observation-anchored model of water table elevation (WTE) and
depth-to-groundwater (DTW) across CONUS at monthly resolution (2000–present).

**Core philosophy**: Real wells first. Physics-informed covariates second. ML third.
Never trust a gridded product until validated against held-out observations.

## Environment

**Use pixi, not conda/mamba directly.**

```bash
pixi install          # set up environment (first time or after pixi.toml changes)
pixi run lab          # start JupyterLab
pixi shell            # activate environment in terminal
```

- `pixi.toml` is the canonical dependency file. `environment.yml` is kept for reference only.
- Always run Python via `pixi run python` (or `pixi run` for Makefile tasks) — bare `python` resolves to the system interpreter.
- `richdem` must stay in `[dependencies]` (conda), not `[pypi-dependencies]` — it fails to compile from source on macOS clang.

## Build & Pipeline

Primary pipeline (GAIA-integrated, PNW pilot scope):
```bash
make data              # Download NWIS GW levels (state-by-state, checkpointed)
make qc                # QC + monthly aggregation → data/processed/
make 3dep              # Download 3DEP 10 m DEM via py3dep → data/raw/dem/3dep_10m_5070.tif
make gaia-data         # Fetch SOLUS100 + PRISM from s3://cresst via odc.stac
make climate           # Fetch PDO, SNODAS SWE; derive SPI-3
make terrain           # Compute HAND, TWI, slope → data/processed/terrain_*.tif
make grid              # Build canonical 1 km PNW grid → data/processed/
make baseline          # LightGBM + regression kriging → data/processed/baseline_*.tif
make climate-response  # β-map OLS fitting → data/processed/beta_*.tif + gwl_climate_response.zarr
make residuals         # Stage 3 kriging + final assembly → data/processed/gwl_*.zarr
make eda               # Execute EDA notebook → HTML
make clean             # Remove processed outputs (keeps raw downloads)
make clean-all         # Remove everything including raw downloads
```

Legacy targets (kept for comparison only):
```bash
make baseline-legacy   # Old co-kriging MM1
make anomalies-legacy  # Old ordinary kriging of anomalies
make dem               # Old MERIT Hydro DEM download (deprecated)
```

## Data Layout & Provenance

```
data/raw/nwis/            ← one parquet per state (git-ignored)
                            download_log.json ← checkpoint + provenance (git-tracked)
data/raw/dem/             ← MERIT Hydro tiles + merit_hydro_1km_5070.tif (git-ignored)
data/raw/MANIFEST.md      ← dataset registry (git-tracked)
data/processed/           ← QC'd parquets, GeoTIFFs, Zarr archives (git-ignored)
data/comparison/          ← held-out comparison datasets (git-ignored)
```

**Rule**: Data files (`.parquet`, `.tif`, `.nc`, `.csv`, …) are never committed.
Provenance files (`download_log.json`, `MANIFEST.md`, `src/` scripts) are always committed.
Update `data/raw/MANIFEST.md` after adding any new dataset.

## Key Conventions

**Target variables**
- Model internally in **WTE (m NAVD88)** — smoother for interpolation.
- Deliver as **DTW (m below surface)** — what users expect.
- Output grid: 1 km, EPSG:5070 (NAD83 CONUS Albers); deliver in EPSG:4326.

**QC chain** (`src/data/qc_nwis.py`) — do not add steps without updating docstring:
1. Filter bad `lev_status_cd` codes (pumping, dry, obstructed, etc.)
2. Drop sites with < N measurements
3. Flag deep wells (> 150 m) as likely confined — exclude or tag
4. Convert feet → meters
5. Compute WTE from DTW + `alt_va` (land surface altitude)
6. Exclude NGVD29 datum sites (VERTCON correction deferred — see A4 in `docs/assumptions.md`)
7. Aggregate to monthly medians per site
8. Compute per-site temporal coverage statistics (`coverage_fraction`, `max_gap_months`); flag sparse sites (`is_sparse_timeseries`) and sites with long gaps (`has_long_gap`) — **no gap filling, no interpolation**

**Modeling — three-stage pipeline**

Stage 0 — Terrain covariates (`src/features/compute_terrain.py`):
- Primary spatial predictor is HAND (Height Above Nearest Drainage), not raw DEM elevation.
  HAND = 0 in valley floors (highest liquefaction risk), large on ridge crests.
- TWI = ln(contributing_area / tan(slope)) per Beven & Kirkby (1979).
- Computed from 3DEP 10 m DEM via richdem; resampled to 1 km for model inputs.

Stage 1 — Regression kriging baseline (`src/models/baseline_regression.py`):
- LightGBMRegressor on [HAND, TWI, slope, SOLUS100 Ksat, clay%, mean_ppt, aridity_idx, lat, lon]
  → long-term median DTW per well. Replaces GStatSim co-kriging MM1.
- Conformal PIs via MapieRegressor(method="plus", cv=spatial_splitter).
- Kriging of LightGBM residuals via pykrige.OrdinaryKriging (exponential model, per HUC-2).
- NST (QuantileTransformer) applied before residual kriging; inverse-NST on output.
- Spatial block CV via verde.BlockShuffleSplit(spacing=200_000, n_splits=5) — never random CV.
- Outputs: baseline_dtw_m.tif, baseline_wte_m.tif, baseline_lgbm_std_m.tif, baseline_kriging_std_m.tif

Stage 2 — Climate response functions (`src/models/climate_response.py`):
- Per-site OLS: ΔDTW(t) = β₀ + β₁·SPI3(t) + β₂·ΔSWE(t−lag) + β₃·PDO(t) + ε
- SWE lag optimized per terrain zone (valley/transition/upland) via AIC.
- β maps kriged to 1 km grid; reconstruct monthly anomaly as β(x,y)·climate_index(t).
- AR term (β₄) placeholder = 0 until Stage IV intercomparison delivers ranked precipitation product.
- Outputs: beta_spi3_1km.tif, beta_swe_1km.tif, beta_pdo_1km.tif, gwl_climate_response.zarr

Stage 3 — Residual kriging + final assembly (`src/models/interpolate_residuals.py`):
- Ordinary kriging of (obs_anomaly − climate_response) residuals per HUC-2 and calendar month.
- Final: DTW = baseline_dtw + climate_response_anom + kriged_residual
- Outputs: gwl_dtw.zarr, gwl_wte.zarr (same filenames as before — backward compat)

Legacy modules (use for comparison only, do not modify):
- `src/models/interpolate_baseline.py` — GStatSim co-kriging MM1 (original Stage 1)
- `src/models/interpolate_anomalies.py` — ordinary kriging of anomaly fields (original Stage 2)

Uncertainty stack (`src/evaluation/uncertainty_stack.py`):
- σ_total = sqrt(σ_lgbm² + σ_kriging_baseline² + σ_response² + σ_residual_krige²)
- Use well-density confidence mask alongside predictions; flag cells > 50 km from nearest well.

**GAIA ecosystem integration**
- SOLUS100 soil properties: loaded from s3://cresst via odc.stac (see `src/data/fetch_gaia.py`)
- PRISM precipitation: from prism-stac, same pattern
- Outputs: xarray.DataTree (see DataTree schema in `docs/gaia-conventions.md`)
- STAC provenance JSON generated per product via `src/io/stac_publish.py`
- Four-part provenance on every variable: gaia:source, gaia:measurement, gaia:resolution_m, gaia:uncertainty_path

## Coding Conventions

- **CRS**: All spatial analysis in **EPSG:5070** (NAD83 CONUS Albers); deliver outputs in **EPSG:4326**.
- **Units**: SI throughout (meters, seconds, kg). Convert NWIS feet → meters on ingest; never store raw feet in processed files.
- **Time**: UTC only. Use `pandas.Timestamp` or `numpy.datetime64`; no bare strings.
- **Paths**: `pathlib.Path` everywhere in `src/`; no `os.path` string concatenation.
- **Logging**: Use the `logging` module in all `src/` modules; no `print()` statements.
- **Style**: NumPy-style docstrings and type hints on every public function.

## Documentation

- [`docs/assumptions.md`](../docs/assumptions.md) — severity-tagged assumptions register; update when adding any new assumption
- [`docs/limitations.md`](../docs/limitations.md) — known limitations; update continuously
- New scripts: add a row to `data/raw/MANIFEST.md` for any newly downloaded dataset

## Modeling Workflow

For the full phase-by-phase workflow (scope → data → EDA → modeling → validation → packaging), invoke the `water-table-model` skill.
