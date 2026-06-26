# Data Manifest

Record of all downloaded datasets with provenance. Update after each download.

## USGS NWIS Groundwater Levels

| Field | Value |
|-------|-------|
| Source | USGS NWIS Web Services via `dataretrieval` Python package |
| URL | `https://waterservices.usgs.gov/nwis/gwlevels/` |
| Query | All CONUS states, site type GW, 2000-01-01 to present |
| Download date | _pending_ |
| Script | `src/data/download_nwis.py` |
| Raw location | `data/raw/nwis/` |
| Checksum | See `data/raw/nwis/download_log.json` |
| Notes | State-by-state download with checkpointing |

## Comparison / Physics Prior Datasets

### Ma 2025 — HydroGEN Ensemble WTD

| Field | Value |
|-------|-------|
| Source | Princeton HydroGEN via `hf_hydrodata` Python package |
| Reference | Ma et al. (2025), *ERL* |
| URL | `https://hydrogen.princeton.edu` |
| Dataset name | `ma_2025` |
| Variables | `water_table_depth` (median, 50th pct.), `wtd_uncertainty` (ensemble spread) |
| Native grid | CONUS2, LCC 24.14 m, delivered as WGS84 mosaic |
| Raw files | `data/comparison/WT2-ma_wtd_50.tif`, `data/comparison/wtd_uncertainty_mosaic_wgs84.tif` |
| Retrieval script | `1-HydroGEN Retrieval.ipynb` (in notebooks/; uses `hf_hydrodata`) |
| Alignment script | `src/features/align_hydrogen.py` — reprojects to EPSG:5070, 1 km |
| Aligned outputs | `data/processed/hydrogen_wtd_prior_1km.tif`, `data/processed/hydrogen_wtd_uncertainty_1km.tif` |
| Role in model | Physics prior WTE(x,y) for EDK baseline; σ_physics uncertainty layer |
| Notes | DTW sign: positive = below surface. WTE_prior = DEM − Ma2025_DTW. Uncertainty is ensemble spread (confirm IQR vs σ in notebooks/02_hydrogen_eda.ipynb) |

## Terrain

### 3DEP 10 m DEM

| Field | Value |
|-------|-------|
| Source | USGS 3D Elevation Program (3DEP) via OpenTopography API |
| API | `py3dep.get_map("DEM", geometry, resolution=10)` |
| Coverage | PNW pilot: WA + OR bbox (WGS84: -124.9, 42.0, -116.5, 49.0) |
| Native CRS | EPSG:4269 (NAD83 geographic) |
| Download script | `src/data/download_3dep.py` |
| Raw output | `data/raw/dem/3dep_10m_5070.tif` — 10 m EPSG:5070 |
| Derived output | `data/raw/dem/3dep_1km_5070.tif` — resampled 1 km |
| Terrain products | `data/processed/terrain_{hand,twi,slope,contrib_area}_1km.tif` |
| Compute script | `src/features/compute_terrain.py` |
| Notes | Replaces MERIT Hydro. HAND=0 in valley floors; critical for liquefaction-model inputs. |

## Soil Properties

### SOLUS100

| Field | Value |
|-------|-------|
| Source | USDA/NRCS SOLUS100 — 100m EPSG:5070 soil properties |
| Variables | clay_0_5cm_mean, ksat_0_5cm_mean, phh2o_0_5cm_mean, bdod_0_5cm_mean |
| Access | Anonymous read from s3://cresst via odc.stac + pystac_client |
| STAC catalog | gaia-hazlab/solus-stac |
| Coverage | PNW pilot bbox (loaded on demand; no local raw copy) |
| Fetch script | `src/data/fetch_gaia.py solus` |
| Processed output | `data/processed/solus100_pnw.zarr` (clay_pct, ksat_cm_hr, ph, bulk_density) |

## Climate Indices

### PRISM Monthly Precipitation

| Field | Value |
|-------|-------|
| Source | PRISM Climate Group via prism-stac (s3://cresst/prism-stac) |
| Variables | ppt (mm/month) |
| Period | 2000-01-01 to present |
| Native resolution | 4 km |
| Fetch script | `src/data/fetch_gaia.py prism` |
| Processed outputs | `data/processed/prism_monthly_pnw.zarr`, `prism_mean_annual_ppt_pnw.tif` |

### PDO Index (Pacific Decadal Oscillation)

| Field | Value |
|-------|-------|
| Source | NOAA PSL (Physical Sciences Laboratory) |
| URL | https://psl.noaa.gov/data/timeseries/monthly/PDO/ |
| Format | CSV (~10 kB), monthly 1900-present |
| Fetch script | `src/data/fetch_climate.py pdo` |
| Output | `data/raw/climate/pdo_monthly.csv` |

### SNODAS Snow Water Equivalent

| Field | Value |
|-------|-------|
| Source | NSIDC SNODAS G02158 |
| Variables | Monthly mean SWE (mm) |
| Period | 2003-10-01 to present |
| Coverage | PNW pilot bbox |
| Fetch script | `src/data/fetch_climate.py swe` |
| Output | `data/raw/climate/snodas_swe_monthly_pnw.zarr` |

### SPI-3 (3-month Standardized Precipitation Index)

| Field | Value |
|-------|-------|
| Source | Derived from PRISM monthly ppt |
| Method | 3-month rolling sum → per-cell empirical CDF → norm.ppf() standardization |
| Compute script | `src/data/fetch_climate.py spi3` |
| Output | `data/processed/spi3_monthly_pnw.zarr` — (time, y, x) 1 km EPSG:5070 |

## Covariates (deferred)

| Dataset | Source | Resolution | Status | Notes |
|---------|--------|-----------|--------|-------|
| Stage IV radar-gauge precip | NWS / CPC | 4 km hourly | Deferred | AR event capture; pending intercomparison |
| PANGA GPS VLM | geodesy.unr.edu | ~40 PNW stations | Deferred | Coastal boundary condition (Stage 4) |
| GRACE-FO TWSA | JPL PO.DAAC | 0.5° monthly | Deferred | Long-term storage trends (Priority 3) |
| NHDPlus streams | USGS | Vector | Deferred | Stream network for HAND validation |
