# Refactoring Plan: gwl-space-time-smooth → GAIA HazLab Integration

## Context

gwl-space-time-smooth builds a monthly 1 km groundwater level (GWL) product anchored to
USGS NWIS well observations. The existing pipeline (co-kriging spatial baseline + ordinary
kriging of monthly anomalies) has four diagnosed gaps: DEM is the wrong spatial predictor
(HAND is correct), temporal anomalies have no climate backbone, the baseline has HUC-2
tiling artifacts, and there is no coastal boundary condition for SoDo.

This refactoring integrates the repo into the GAIA HazLab ecosystem (target org:
gaia-hazlab), adopts GAIA output conventions (DataTree, STAC provenance, cresst-format
Zarr/COG), and replaces the spatial and temporal model cores with physically-grounded
alternatives: LightGBM regression kriging (Stage 1) and per-site climate response
functions (Stage 2). Coastal boundary condition and Earth2Studio scenario generation
are deferred.

The NWIS download and 8-step QC chain are unchanged. EPSG:5070, 1 km grid, and monthly
resolution are unchanged. Well-density mask is unchanged.

---

## New Repository Structure

```
gwl-space-time-smooth/          (→ gaia-hazlab/gwl-space-time-smooth)
├── src/
│   ├── data/
│   │   ├── download_nwis.py        UNCHANGED — NWIS OGC API download
│   │   ├── qc_nwis.py              UNCHANGED — 8-step QC chain
│   │   ├── download_3dep.py        NEW — replaces download_dem.py (3DEP 10 m via py3dep)
│   │   ├── fetch_gaia.py           NEW — SOLUS100 + PRISM via odc.stac from s3://cresst
│   │   └── fetch_climate.py        NEW — PDO index, SNODAS SWE, SPI-3 derivation
│   ├── features/
│   │   ├── compute_grid.py         UNCHANGED — canonical 1 km EPSG:5070 grid
│   │   ├── compute_terrain.py      NEW — HAND, TWI, slope, contributing area from DEM
│   │   └── align_hydrogen.py       KEEP (benchmark only — HydroGEN cross-validation)
│   ├── models/
│   │   ├── baseline_regression.py  NEW — LightGBM + regression kriging (replaces interpolate_baseline.py)
│   │   ├── climate_response.py     NEW — per-site OLS β-maps, Stage 2 (replaces interpolate_anomalies.py)
│   │   ├── interpolate_residuals.py NEW — Stage 3 kriging of (obs − climate_response) residuals
│   │   ├── interpolate_baseline.py DEPRECATED (kept for legacy comparison; make baseline-legacy)
│   │   ├── interpolate_anomalies.py DEPRECATED (kept for legacy comparison)
│   │   └── pilot_temporal.py       DEPRECATED (absorbed into new pipeline)
│   ├── evaluation/
│   │   ├── cross_validate.py       NEW — verde.BlockShuffleSplit spatial block CV runner
│   │   ├── pillar1_compare.py      NEW — compare NWIS-anchored GWT vs Pillar 1 d_wt
│   │   └── uncertainty_stack.py    UPDATE — add Stage 2 σ_response component
│   └── io/
│       ├── zarr_io.py              NEW — DataTree write/read helpers, CF metadata
│       └── stac_publish.py         NEW — STAC item generation, four-part provenance
├── notebooks/
│   ├── 01_eda.ipynb                UPDATE — add terrain EDA (HAND vs DTW scatter)
│   ├── 02_hydrogen_eda.ipynb       UPDATE — compare HydroGEN vs LightGBM baseline
│   ├── 03_temporal_model.ipynb     UPDATE — replace pure kriging with climate response + residuals
│   ├── 04_climate_response.ipynb   NEW — explore β maps, terrain-zone sensitivity, lag analysis
│   └── 05_gaia_integration.ipynb   NEW — SOLUS100 load, STAC DataTree output demo
├── docs/
│   ├── assumptions.md              UPDATE — add HAND, regression, climate response assumptions
│   ├── limitations.md              UPDATE
│   └── gaia-conventions.md         NEW — GAIA alignment guide (DataTree, STAC, provenance)
├── .github/
│   ├── copilot-instructions.md     UPDATE — new stages, new modules, new data sources
│   └── skills/water-table-model/
│       ├── SKILL.md                UPDATE — regression kriging, climate response phases
│       └── references/
│           ├── data-sources.md     UPDATE — 3DEP API, SOLUS100, PDO, SNODAS, gaia-cli, odc.stac
│           └── modeling-approaches.md  UPDATE — regression kriging, β-map approach
├── data/raw/MANIFEST.md            UPDATE — register 3DEP, SOLUS100, PDO, SNODAS, PRISM
├── pixi.toml                       UPDATE — add odc-stac, py3dep, pystac, s3fs; remove unused
├── Makefile                        UPDATE — new targets (see below)
└── README.md                       UPDATE — new pipeline, GAIA context, new data sources
```

---

## Phase 0 — GAIA Conventions Scaffolding
*Touches: pixi.toml, src/io/, docs/, .github/, MANIFEST.md*

### pixi.toml additions
Add to `[pypi-dependencies]`:
```
odc-stac = "*"       # STAC catalog loading via odc
odc-geo = "*"        # geometry utilities for odc
py3dep = "*"         # 3DEP elevation data (wraps OpenTopography API)
pystac = "*"         # STAC item/collection generation
s3fs = "*"           # s3://cresst anonymous read
```
Remove `gstatsim` from pypi-dependencies (GStatSim co-kriging is replaced; pykrige covers residual kriging). Keep `scikit-gstat` for variogram fitting.

### src/io/zarr_io.py
Write helpers:
- `write_datatree(dt: xr.DataTree, path: Path, chunks: dict) → None` — write Zarr v3 with CF attributes
- `read_datatree(path: Path) → xr.DataTree`
- `add_cf_attrs(da: xr.DataArray, long_name, units, standard_name, grid_mapping="albers_conical_equal_area") → xr.DataArray`
- Standard GWL DataTree schema:
  ```
  /baseline/   wte_m, dtw_m, std_m
  /anomaly/    wte_anomaly_m, std_m
  /climate/    spi3, swe_anom, pdo, ar_count
  /beta/       b_spi3, b_swe, b_pdo, b_ar, r2
  /residual/   wte_residual_m, std_m
  /final/      wte_m, dtw_m, total_std_m
  /mask/       well_density_50km
  ```

### src/io/stac_publish.py
- `make_stac_item(product_path, product_id, source, measurement, resolution_m, uncertainty_path) → pystac.Item`
- Four-part provenance as STAC `extra_fields`: `gaia:source`, `gaia:measurement`, `gaia:resolution_m`, `gaia:uncertainty_path`
- No upload to s3 — just generate and save `{product_id}_stac_item.json` alongside the Zarr

### docs/gaia-conventions.md
Document: DataTree schema, four-part provenance, CRS/unit/format rules, how to load via odc.stac.

### .github/copilot-instructions.md
Add new pipeline section (Stages 0–3), new modules list, new data sources. Keep existing QC chain section verbatim.

---

## Phase 1 — Terrain Module
*Touches: src/data/download_3dep.py, src/features/compute_terrain.py, Makefile, MANIFEST.md*

### src/data/download_3dep.py
Replace `download_dem.py`. Uses `py3dep` (wraps OpenTopography 3DEP API, free key):
```python
# CLI: --bbox LEFT BOTTOM RIGHT TOP (EPSG:4326) or use PNW_BBOX
# --output-dir data/raw/dem
# --resolution 10  (metres; 3DEP 1/3 arc-sec ≈ 10 m)
import py3dep
dem_10m = py3dep.get_map("DEM", geometry=bbox_wgs84, resolution=10)
# reproject to EPSG:5070; write data/raw/dem/3dep_10m_5070.tif
# resample to 1km: data/raw/dem/3dep_1km_5070.tif
```
Key constants: `TARGET_CRS = CRS.from_epsg(5070)`, `CONUS_BOUNDS_5070` (same as download_dem.py).

Keep `download_dem.py` with a deprecation warning for backward compat.

### src/features/compute_terrain.py
Input: `data/raw/dem/3dep_10m_5070.tif` (or fallback to 1km DEM)
Uses `richdem` (already in pixi.toml, conda-forge only):
```python
# Functions:
# compute_flow_direction(dem) -> rd.rdarray
# compute_contributing_area(dem) -> np.ndarray   (m²)
# compute_hand(dem, flow_dir, contrib_area, stream_threshold=1e6) -> np.ndarray
#   stream cells: contrib_area > stream_threshold
#   HAND = DEM - DEM[nearest_stream_cell]  (via richdem distance function or manual BFS)
# compute_twi(contrib_area, slope) -> np.ndarray
#   TWI = ln(contrib_area / tan(slope_rad))  [Beven & Kirkby 1979]
# compute_slope(dem) -> np.ndarray  (degrees)
# resample_to_1km(array_10m, dem_10m_path, grid_spec) -> np.ndarray
```
Output (all at 1 km EPSG:5070, float32, nodata=-9999):
- `data/processed/terrain_hand_1km.tif`
- `data/processed/terrain_twi_1km.tif`
- `data/processed/terrain_slope_1km.tif`
- `data/processed/terrain_contrib_area_1km.tif`

Validation: at Green River Valley / Duwamish / Puyallup, HAND should be < 5 m.

### Makefile additions
```makefile
DEM_3DEP := $(RAW_DEM_DIR)/3dep_10m_5070.tif
HAND_TIF  := $(PROCESSED_DIR)/terrain_hand_1km.tif

3dep:   # replaces dem
    python -m src.data.download_3dep --bbox $(PNW_BBOX_WGS84) --output-dir $(RAW_DEM_DIR)

terrain: $(DEM_3DEP)
    python -m src.features.compute_terrain --dem $(DEM_3DEP) --output-dir $(PROCESSED_DIR)

dem: # DEPRECATED — kept for backward compat, calls download_dem.py
```

---

## Phase 2 — GAIA Data Staging
*Touches: src/data/fetch_gaia.py, src/data/fetch_climate.py, Makefile, MANIFEST.md*

### src/data/fetch_gaia.py
Two sub-commands: `solus` and `prism`.

**SOLUS100 fetch** (no download — anonymous read from s3://cresst via odc.stac):
```python
import odc.stac, pystac_client
# Load SOLUS100 for PNW bbox
catalog = pystac_client.Client.open("https://gaia-hazlab.github.io/solus-stac/catalog.json")
items = catalog.search(bbox=PNW_BBOX_WGS84, collections=["solus100"])
ds = odc.stac.load(items, bands=["clay_0_5cm_mean", "ksat_0_5cm_mean", "phh2o_0_5cm_mean",
                                   "bdod_0_5cm_mean"], crs="EPSG:5070", resolution=100)
# Write to data/processed/solus100_pnw.zarr
```
Output: `data/processed/solus100_pnw.zarr` with variables: `clay_pct`, `ksat_cm_hr`, `ph`, `bulk_density`

**PRISM fetch** (from prism-stac if available, else direct PRISM download):
```python
# Load PRISM monthly ppt for PNW, 2000–present
# Write to data/processed/prism_monthly_pnw.zarr
# Derive: data/processed/prism_mean_annual_ppt_pnw.tif (static covariate)
```

### src/data/fetch_climate.py
Three sub-commands: `pdo`, `swe`, `spi3`.

**PDO index**: GET from NOAA PSL (single CSV, ~10 kB), parse to monthly DataFrame.
- Output: `data/raw/climate/pdo_monthly.csv`

**SNODAS SWE** (monthly means for PNW, NSIDC G02158):
- Download via NSIDC HTTPS; parse binary SNODAS format → xarray
- Clip to PNW bbox; compute monthly mean SWE (mm)
- Output: `data/raw/climate/snodas_swe_monthly_pnw.zarr`

**SPI-3 derivation** (from PRISM ppt):
- Load PRISM monthly ppt, compute 3-month rolling sum, standardize per calendar month
- Use `scipy.stats.norm.ppf` on empirical CDF per grid cell per calendar month
- Output: `data/processed/spi3_monthly_pnw.zarr` — (time, y, x), same 1 km EPSG:5070 grid

### Makefile additions
```makefile
gaia-data:    # fetch SOLUS100 + PRISM from s3://cresst
    python -m src.data.fetch_gaia solus --bbox $(PNW_BBOX_WGS84) --output-dir $(PROCESSED_DIR)
    python -m src.data.fetch_gaia prism --bbox $(PNW_BBOX_WGS84) --output-dir $(PROCESSED_DIR)

climate:      # PDO, SNODAS SWE, SPI-3
    python -m src.data.fetch_climate pdo --output-dir data/raw/climate
    python -m src.data.fetch_climate swe --bbox $(PNW_BBOX_WGS84) --output-dir data/raw/climate
    python -m src.data.fetch_climate spi3 --prism $(PROCESSED_DIR)/prism_monthly_pnw.zarr \
        --output-dir $(PROCESSED_DIR)
```

---

## Phase 3 — Regression Baseline (replaces co-kriging Stage 1)
*Touches: src/models/baseline_regression.py, src/evaluation/cross_validate.py*

### src/evaluation/cross_validate.py
Reusable spatial block CV runner. Wraps `verde.BlockShuffleSplit`:
```python
def spatial_block_cv(X, y, coords_5070, spacing_m=200_000, n_splits=5) -> dict:
    # Returns dict: {fold: {train_idx, test_idx, rmse, bias, r2}}
```
Used by both baseline_regression.py and future models.

### src/models/baseline_regression.py
Replaces `interpolate_baseline.py`. CLI args:
```
--sites         data/processed/nwis_sites_clean.parquet
--hand          data/processed/terrain_hand_1km.tif
--twi           data/processed/terrain_twi_1km.tif
--slope         data/processed/terrain_slope_1km.tif
--solus         data/processed/solus100_pnw.zarr
--prism-ppt     data/processed/prism_mean_annual_ppt_pnw.tif
--dem           data/raw/dem/3dep_1km_5070.tif
--output-dir    data/processed
--n-cv-splits   5
```

**Pipeline**:
1. Load usable sites (`is_sparse_timeseries=False`, `has_long_gap=False`, `is_deep_well=False`)
2. Sample terrain + soil features at well locations (rasterio.sample)
3. Feature matrix X = [HAND, TWI, slope, ksat, clay_pct, mean_ppt, aridity_idx, lat_5070, lon_5070]
4. Target y = `median_dtw_m` per well
5. `spatial_block_cv(X, y, coords)` → cross-validated RMSE, bias, R² (logged to JSON)
6. Fit `LGBMRegressor` on all usable sites
7. Conformal PI via `mapie.MapieRegressor(estimator=lgbm, method="plus", cv=spatial_splitter)`
8. Predict median DTW + PI on 1 km grid
9. Compute residuals at wells: `resid = obs_dtw − lgbm_pred`
10. Krige residuals using `pykrige.OrdinaryKriging` (same variogram approach as current interpolate_baseline.py — exponential model, K=100, radius=300km)
11. Final DTW = lgbm_pred + kriged_resid; WTE = DEM − DTW

**Outputs** (same file names as before for backward compat):
- `data/processed/baseline_dtw_m.tif`
- `data/processed/baseline_wte_m.tif`
- `data/processed/baseline_lgbm_std_m.tif` (new — conformal PI half-width)
- `data/processed/baseline_kriging_std_m.tif` (kriging σ on residuals)
- `data/processed/well_density_mask.tif` (unchanged)
- `data/processed/lgbm_feature_importance.json`
- `data/processed/block_cv_metrics.json`

**Makefile**:
```makefile
baseline: $(HAND_TIF) $(SITES_PARQUET)   # now calls baseline_regression.py
    python -m src.models.baseline_regression ...

baseline-legacy:                          # old co-kriging for comparison
    python -m src.models.interpolate_baseline ...
```

---

## Phase 4 — Climate Response Functions (Stage 2)
*Touches: src/models/climate_response.py, src/models/interpolate_residuals.py*

### src/models/climate_response.py
CLI args:
```
--monthly       data/processed/nwis_gwlevels_monthly.parquet
--sites         data/processed/nwis_sites_clean.parquet
--spi3          data/processed/spi3_monthly_pnw.zarr
--swe           data/raw/climate/snodas_swe_monthly_pnw.zarr
--pdo           data/raw/climate/pdo_monthly.csv
--hand          data/processed/terrain_hand_1km.tif
--output-dir    data/processed
--min-months    36   (minimum obs months to fit β)
--max-lag       6    (months to test for SWE lag)
```

**Pipeline**:
1. Load monthly anomalies: `wte_anomaly = obs_wte - site_median_wte` (existing field)
2. For each site: sample SPI-3, SWE_anomaly, PDO at site location and month
3. Lag optimization: for SWE lag in [0,1,2,3,4,5,6], fit OLS and record AIC/BIC → pick best lag per terrain zone (HAND < 5m, 5–20m, > 20m)
4. Per-site OLS: `ΔDTW(t) = β₀ + β₁·SPI3(t) + β₂·ΔSWE(t−lag*) + β₃·PDO(t) + ε`
   - AR (β₄) placeholder — set to 0 until Stage IV intercomparison delivers ranked product
5. Compute per-site: β coefficients, R², residual std, p-values
6. Krige β₁, β₂, β₃ maps to 1 km grid using `pykrige.OrdinaryKriging` (per-HUC-2)
7. Reconstruct monthly GWL anomaly at all grid cells: `anomaly_hat(x,y,t) = β₁(x,y)·SPI3(x,y,t) + β₂(x,y)·ΔSWE(x,y,t−lag) + β₃(x,y)·PDO(t)`

**Outputs**:
- `data/processed/beta_spi3_1km.tif`
- `data/processed/beta_swe_1km.tif`
- `data/processed/beta_pdo_1km.tif`
- `data/processed/beta_r2_1km.tif`
- `data/processed/optimal_swe_lag_zone.json` (lag in months per terrain zone)
- `data/processed/climate_response_sites.parquet` (β + diagnostics per site)
- `data/processed/gwl_climate_response.zarr` — (time, y, x) Stage 2 reconstructed anomaly

### src/models/interpolate_residuals.py
Thin wrapper around existing anomaly kriging logic. Input: `obs_anomaly − climate_response_anomaly`.
Outputs: `data/processed/gwl_residual.zarr` — (time, y, x) Stage 3 kriged residuals.

**Final assembly** (in `main()` of `interpolate_residuals.py`):
```python
final_dtw = baseline_dtw + climate_response_anom + kriged_residual
```
Outputs: `data/processed/gwl_dtw.zarr`, `gwl_wte.zarr` (same filenames as before).

**Makefile**:
```makefile
climate-response: $(SITES_PARQUET) $(MONTHLY_PARQUET) $(SPI3_ZARR) $(SWE_ZARR) $(PDO_CSV)
    python -m src.models.climate_response ...

residuals: data/processed/gwl_climate_response.zarr $(MONTHLY_PARQUET)
    python -m src.models.interpolate_residuals ...

anomalies-legacy:   # old pure kriging for comparison
    python -m src.models.interpolate_anomalies ...
```

---

## Phase 5 — Output Format & GAIA Alignment
*Touches: src/evaluation/uncertainty_stack.py, src/io/, all Zarr outputs*

### uncertainty_stack.py update
Add Stage 2 uncertainty component: `σ_response` = per-cell residual std from climate response R².
`σ_total = sqrt(σ_lgbm² + σ_kriging_baseline² + σ_response² + σ_residual_krige²)`

### DataTree conversion
Wrap all final Zarr writes through `zarr_io.write_datatree()`. The DataTree schema (see Phase 0) 
is written alongside existing flat Zarr files — backward-compatible.

### STAC item generation
After each model run, call `stac_publish.make_stac_item()` to write a sidecar JSON.

---

## Phase 6 — Documentation & Org Migration
*Touches: README.md, .github/, docs/, MANIFEST.md, git remote*

### .github/copilot-instructions.md
Add sections:
- New pipeline stages (0–3): terrain → gaia-data → climate → baseline-regression → climate-response → residuals
- New module names (fetch_gaia, fetch_climate, compute_terrain, baseline_regression, climate_response, interpolate_residuals)
- New data sources: 3DEP (py3dep), SOLUS100 (odc.stac), PDO (NOAA PSL CSV), SNODAS (NSIDC), prism-stac

### SKILL.md update
Replace Stage 1 (co-kriging MM1) with regression kriging. Replace Stage 2 (ordinary kriging) 
with climate response functions. Add AR placeholder note.

### README.md
- New pipeline diagram
- Point to gaia-hazlab org
- Credit GAIA ecosystem (SOLUS100, PRISM-stac, gaia-cli)
- Note Pillar 1 complementarity

### GitHub org migration
```bash
git remote set-url origin git@github.com:gaia-hazlab/gwl-space-time-smooth.git
git push -u origin main
```
(User executes — requires gaia-hazlab org access)

---

## Makefile: Final Target Overview

```makefile
# === NEW PRIMARY PIPELINE ===
all:     data qc 3dep gaia-data climate terrain baseline climate-response residuals

3dep:           # download 3DEP 10 m DEM (replaces dem)
gaia-data:      # SOLUS100 + PRISM from s3://cresst
climate:        # PDO + SNODAS SWE + SPI-3
terrain:        # HAND + TWI + slope from 3DEP
qc:             # (unchanged)
data:           # (unchanged)
baseline:       # NEW: LightGBM + regression kriging (calls baseline_regression.py)
climate-response:  # β-map OLS fitting
residuals:      # Stage 3 kriging + final assembly

# === LEGACY (comparison only) ===
baseline-legacy:    # old co-kriging MM1
anomalies-legacy:   # old pure kriging of anomalies
dem:                # old MERIT Hydro download (deprecated, warns)
```

---

## Validation Strategy (end-to-end)

1. **Terrain check**: HAND at Duwamish / Puyallup valley cells should be < 5 m. HAND on Cascade ridge crests should be > 50 m.
2. **Baseline spatial CV**: `block_cv_metrics.json` should show RMSE < co-kriging baseline on held-out 20% of wells. Target: < 8 m RMSE for PNW.
3. **Climate response R²**: Median R² across WA+OR wells should be > 0.35 (exceeds HydroGEN's 0.341 on a more relevant metric).
4. **Seasonal sanity**: Domain-mean GWL anomaly should peak (shallow) in Feb–Mar (wet season) and trough (deep) in Aug–Sep. Check against `03_temporal_model.ipynb` seasonal cycle figure.
5. **DataTree round-trip**: `zarr_io.read_datatree(path)` → same values as written. Check CF attrs present.
6. **STAC item validity**: `pystac.Item.validate()` passes on each generated item.
7. **Final assembly DTW > 0**: Fraction of cells with DTW < 0 should be < 0.1% (diagnostics checklist item from modeling-approaches.md).

---

## Key Dependencies on Existing Code

- `src/models/baseline_regression.py` reuses `load_usable_sites()` logic from `interpolate_baseline.py:load_usable_sites()`
- `src/models/interpolate_residuals.py` reuses variogram fitting and kriging logic from `interpolate_anomalies.py:_krige_month()` and `_fit_anomaly_variograms()`
- `src/evaluation/cross_validate.py` is used by both `baseline_regression.py` and future `climate_response.py` validation
- `src/features/compute_grid.py:GridSpec` is unchanged and used by all raster-writing modules
- `src/models/uncertainty_stack.py:_read_band()` and `_save_single()` are reused in new modules

---

## Deferred (not in this refactoring)

- Coastal boundary condition (Stage 4): PANGA VLM + SLR tide gauge clamping
- Earth2Studio scenario generation: SPI3 → β-maps → ensemble GWL forecasts
- CONUS-scale pipeline (this refactoring targets PNW pilot: WA + OR)
- VERTCON correction for NGVD29 sites (assumption A4 remains deferred)
- Full GRACE-FO integration (listed as Priority 3 covariate)
