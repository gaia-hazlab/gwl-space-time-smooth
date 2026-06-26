---
name: water-table-model
description: >
  Build a reproducible, observation-anchored model of the US water table in space and
  time using USGS NWIS well data, physical covariates, and ML. Skeptical of gridded
  ML/satellite products (Fan et al., GRACE downscaling) which contain gridding artifacts
  dangerous for research. Covers: USGS data acquisition and QC, covariate processing
  (DEM, climate, soils, geology), spatial/temporal modeling (RF, XGBoost, GP, LSTM),
  artifact detection, uncertainty quantification, literature review (USGS pubs, AGU WRR/GRL,
  HydroShare), and reproducible packaging. Use when: "model the water table", "groundwater
  level map", "depth to water table", "USGS well data", "NWIS groundwater", "water table
  interpolation", "groundwater ML model", "WTD prediction", "Fan et al water table",
  "GRACE water table", "HydroShare groundwater", "national water model groundwater",
  "critique gridded water table product", or any request to map, model, or analyze water
  table depth.
---

# Water Table Model Skill

A structured, multi-phase workflow for building a reproducible, observation-anchored model
of the US water table (depth-to-groundwater, WTD) in space and time.

**Core philosophy**: Real wells first, physics-informed covariates second, ML/statistical
learning third. Never trust a gridded product until validated against held-out observations.
Gridding artifacts are the default assumption, not the exception.

Detailed reference docs:
- [`references/data-sources.md`](references/data-sources.md) — NWIS API patterns, covariate sources, field-name mappings
- [`references/modeling-approaches.md`](references/modeling-approaches.md) — modeling decision tree, spatial CV, deep learning caveats
- [`references/literature-review-protocol.md`](references/literature-review-protocol.md) — key papers, scan workflow

---

## Phase 0 — Scope and Assumptions

Before writing any code, document these decisions in `README.md` and create the living docs:

1. **Spatial domain**: CONUS? Single state? An aquifer system (High Plains, Central Valley)?
   Start with a well-monitored aquifer before attempting CONUS.
2. **Temporal resolution**: Monthly is the pragmatic sweet spot given NWIS measurement cadence.
3. **Target variable**: WTE (water table elevation, m NAVD88) internally; deliver DTW (m below surface).
   WTE is smoother for interpolation. DTW is what users want.
4. **Output grid**: 1 km, EPSG:5070 (NAD83 CONUS Albers) for analysis; EPSG:4326 for delivery.
5. **Assumptions register** (`docs/assumptions.md`): tag every assumption low/medium/high severity.
6. **Limitations register** (`docs/limitations.md`): pre-populate with sparse West, seasonal bias,
   legacy datum uncertainty; update continuously.

---

## Phase 1 — Data Acquisition

See `references/data-sources.md` for URLs, API patterns, and field-name mappings.

### 1.1 USGS NWIS Groundwater Levels (the anchor dataset)

This is the one dataset we fully trust. Everything else is a covariate or comparison target.

**Download** (`src/data/download_nwis.py`):
```bash
make data   # pixi run python -m src.data.download_nwis --start-date 2000-01-01 --output-dir data/raw/nwis
```

Critical fields: `site_no`, `dec_lat_va`, `dec_long_va`, `lev_dt`, `lev_va` (feet DTW),
`lev_status_cd`, `well_depth_va`, `alt_va` (land surface altitude NAVD88 feet).

**QC chain** (`src/data/qc_nwis.py`) — steps are enumerated in the module docstring:
```bash
make qc     # pixi run python -m src.data.qc_nwis --input-dir data/raw/nwis --output ...
```

Output schema: `site_no, lat, lon, year, month, wte_m, dtw_m, n_obs, well_depth_m, aquifer_cd`
→ `data/processed/nwis_gwlevels_monthly.parquet`

### 1.2 Covariates

Each covariate is downloaded, reprojected to the analysis grid (EPSG:5070, 1 km), and stored
as GeoTIFF or xarray Dataset under `data/raw/<name>/`. Add every dataset to `data/raw/MANIFEST.md`.

| Covariate | Source | Why it matters |
|-----------|--------|----------------|
| DEM (elevation, slope, TWI) | USGS 3DEP / MERIT Hydro | WTE ≈ smoothed topography |
| Precipitation & ET | PRISM / gridMET / Daymet | Recharge driver |
| Soil properties | gSSURGO / SoilGrids | Infiltration capacity |
| Geology / aquifer type | USGS aquifer maps, GLiM | Hydraulic conductivity proxy |
| Land use / land cover | NLCD | Irrigation, urbanization |
| GRACE TWSA | NASA PO.DAAC | Large-scale storage anomaly |
| Distance to nearest stream | NHDPlus HR | GW–SW interaction proxy |

**TWI (Topographic Wetness Index)** is the single most predictive static covariate in humid regions.
Compute via `richdem` (already in `pixi.toml`): `TWI = ln(upstream_area / tan(slope))`.
Use hydrologically conditioned DEM + D-inf flow routing. MERIT Hydro pre-built TWI is a valid shortcut.

### 1.3 Comparison-Only Gridded Products

Download for benchmarking **only — never use as ground truth or training data**:
- Fan et al. (2013) — severe gridding artifacts in mountainous terrain; staircase patterns at tile edges
- de Graaf et al. (2017) — physically based but 5 arcmin; all sub-5-arcmin structure is smoothed away
- Any GRACE-downscaled WTD — inherits GRACE's ~300 km native resolution; finer structure is hallucinated

Store in `data/comparison/` and never mix with `data/processed/`.

---

## Phase 2 — Exploratory Data Analysis

`notebooks/01_eda.ipynb` (run via `make eda`). Cover:

1. Map of well locations colored by mean DTW — identify spatial clusters and voids
2. Temporal coverage heatmap: sites × months showing data availability
3. Histograms of DTW (expect heavy right tail — log-transform likely needed)
4. Empirical variograms of mean WTE in several subregions — if no sill, domain is too large
   for stationary geostatistics; partition or use non-stationary methods
5. Covariate correlation matrix — TWI and elevation will be correlated; keep both
6. STL seasonal decomposition on a subset of long-record wells — informs temporal model structure

---

## Phase 3 — Modeling

See `references/modeling-approaches.md` for the full decision tree.

### GAIA-integrated three-stage pipeline (current implementation)

**Stage 0 — Terrain covariates** (`src/features/compute_terrain.py`):
- HAND (Height Above Nearest Drainage) is the primary spatial predictor.
  HAND=0 in valley floors (highest liquefaction/flood risk); large on ridges.
  Compute from 3DEP 10 m DEM via richdem D8 flow directions and stream initiation threshold.
- TWI = ln(α / tan(β)) per Beven & Kirkby 1979. Complements HAND in upland areas.
- Do NOT use raw DEM elevation as primary predictor — causes HUC-2 tiling artifacts.

**Stage 1 — Regression kriging baseline** (`src/models/baseline_regression.py`):
- LightGBMRegressor on [HAND, TWI, slope, SOLUS100 Ksat, clay%, mean_ppt, aridity_idx, lat, lon]
  → long-term median DTW per well.
- Spatial block CV: verde.BlockShuffleSplit(spacing=200_000, n_splits=5). Never random CV.
- Conformal prediction intervals: MapieRegressor(method="plus", cv=spatial_splitter).
- Kriging of LightGBM residuals: pykrige.OrdinaryKriging with NST (QuantileTransformer).
- Final DTW = LightGBM pred + kriged residual.

**Stage 2 — Climate response functions** (`src/models/climate_response.py`):
- Per-site OLS: ΔDTW(t) = β₀ + β₁·SPI3(t) + β₂·ΔSWE(t−lag*) + β₃·PDO(t)
- SWE lag* optimised per terrain zone (valley / transition / upland) by AIC.
- β maps kriged to 1 km grid; monthly anomaly = β(x,y)·climate_index(t).
- AR term (β₄) = 0 until Stage IV intercomparison delivers a ranked product.

**Stage 3 — Residual kriging + assembly** (`src/models/interpolate_residuals.py`):
- Ordinary kriging of (obs_anomaly − climate_response) per HUC-2, per month.
- Final: DTW = baseline + climate_anom + kriged_residual.

**Legacy (comparison only)**:
- `src/models/interpolate_baseline.py` — GStatSim co-kriging MM1 (original Stage 1)
- `src/models/interpolate_anomalies.py` — pure kriging of anomalies (original Stage 2)

### Why HAND instead of DEM elevation?

DEM elevation causes HUC-2 tiling artifacts in co-kriging because elevation varies
hugely between adjacent HUC-2 regions (mountains vs. valleys). HAND removes this
artifact by normalising to the local stream network. HAND=0 exactly where liquefaction
risk is highest (low-lying valley floors), making it the physically correct predictor
for the Sanger et al. and LandLab target applications.

### Uncertainty Quantification

Every prediction must carry an uncertainty estimate:
- Spatial CV RMSE/MAE/bias disaggregated by HUC-2 basin
- Prediction intervals from quantile regression forest, GP posterior, or conformal prediction (`mapie` in `pixi.toml`)
- **Well-density mask**: flag cells > 50 km from nearest observation as low-confidence; deliver as companion raster

---

## Phase 4 — Validation and Artifact Detection

Reserve 20% of sites (spatially stratified) as a test set before any modeling.

### Metrics
Report RMSE, MAE, R², bias disaggregated by: region (HUC-2), aquifer type,
DTW bin (shallow < 5 m, moderate 5–30 m, deep > 30 m), and season.

### Artifact Checklist

This is where most published products silently fail:

1. **Tile boundary artifacts** — straight-line discontinuities aligned with DEM tiles, climate
   grid cells, or political boundaries. Zoom into state borders and UTM zone boundaries.
2. **Staircase patterns** — compute spatial gradient of predicted WTE; bimodal distribution
   (lots of near-zero + sharp jumps) indicates discretization artifacts.
3. **Bull's-eye artifacts** — circular patterns centered on well locations = overfitting or
   insufficient smoothing.
4. **Physical plausibility**:
   - WTE should not exceed land surface elevation (DTW < 0 is physically rare)
   - WTE should decrease toward streams (check against NHDPlus flowlines)
   - WTE should be smoother than topography, not sharper
5. **Residual comparison** — plot residuals vs. Fan et al. and de Graaf; persistent spatial
   patterns suggest shared covariate artifacts.

### Document Failures Honestly

`docs/validation_report.md`:
- All metrics disaggregated as above
- Maps of prediction error at test sites
- Identified artifacts and likely causes
- Regions where the model should not be trusted

---

## Phase 5 — Literature Review

See `references/literature-review-protocol.md` for the full scan workflow and annotated paper list.

Key sources:
- **USGS Water Resources publications** — `https://pubs.usgs.gov/` — Professional Papers and SIRs
- **AGU Water Resources Research (WRR)** — top journal; search "water table depth" + "machine learning"
- **HydroShare** — `https://www.hydroshare.org/` — community datasets and notebooks
- **NGWMN** — inter-agency well network metadata and data quality documentation

---

## Phase 6 — Reproducibility and Packaging

Repository structure already matches this skill's expectations:

```
data/raw/         ← download scripts + provenance (git-tracked); binary data git-ignored
data/processed/   ← analysis-ready (git-ignored)
data/comparison/  ← external gridded products (git-ignored)
notebooks/        ← 01_eda.ipynb, 02_spatial_model.ipynb, 03_temporal_model.ipynb, 04_validation.ipynb
src/data/         ← download_nwis.py, qc_nwis.py (git-tracked)
src/features/     ← covariate extraction scripts
src/models/       ← training and prediction
src/evaluation/   ← validation and artifact detection
```

**Environment**: `pixi.toml` is canonical. `environment.yml` is kept for reference only.
Add new packages to `pixi.toml` (`[dependencies]` for conda-forge, `[pypi-dependencies]` for PyPI-only).
Never add `richdem` to `[pypi-dependencies]` — it fails to compile from source on macOS clang.

**HydroShare publication**: Package final WTE/DTW grids as NetCDF + companion uncertainty raster
+ validation notebook. Register in `data/raw/MANIFEST.md`.

---

## Quick-Start Checklist (GAIA-integrated pipeline)

```bash
make data              # Download NWIS GW levels (checkpointed)
make qc                # QC + monthly aggregation
make 3dep              # 3DEP 10 m DEM for PNW
make gaia-data         # SOLUS100 + PRISM from s3://cresst
make climate           # PDO, SNODAS SWE, SPI-3
make terrain           # HAND, TWI, slope (from 3DEP)
make grid              # 1 km EPSG:5070 grid
make baseline          # LightGBM + regression kriging
make climate-response  # β-map OLS
make residuals         # Stage 3 + final assembly
make eda               # EDA notebook
```

Validation targets before publishing:
- [ ] HAND < 5 m at Duwamish / Puyallup valley cells
- [ ] Spatial CV RMSE < co-kriging legacy baseline
- [ ] Seasonal GWL cycle peaks Feb–Mar, troughs Aug–Sep
- [ ] DTW < 0 in < 0.1% of final grid cells
- [ ] Write `docs/validation_report.md`
- [ ] Run `src/evaluation/pillar1_compare.py` for Pillar 1 cross-validation
