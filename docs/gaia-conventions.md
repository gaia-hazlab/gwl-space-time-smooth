# GAIA HazLab Conventions for gwl-space-time-smooth

This document records the GAIA ecosystem standards adopted in this repository.
Follow these conventions in all new modules. Legacy modules (interpolate_baseline.py,
interpolate_anomalies.py) predate these conventions and are preserved for comparison only.

---

## Output Format: xarray.DataTree

All final outputs are written as **xarray.DataTree** Zarr stores via `src/io/zarr_io.py`.
The DataTree is a hierarchical structure where each node is an xarray.Dataset.

### Standard GWL DataTree schema

```
/                    root — global metadata, grid_mapping variable
├── /baseline        static (y, x) — LightGBM + kriged residual baseline
│   ├── wte_m        water table elevation (m NAVD88)
│   ├── dtw_m        depth to groundwater (m, positive = below surface)
│   └── std_m        total baseline σ (conformal PI half-width + kriging σ)
├── /climate         dynamic (time, y, x) — forcing indices on the 1 km grid
│   ├── spi3         3-month Standardized Precipitation Index (dimensionless)
│   ├── swe_anom     SWE anomaly (mm, vs site long-term mean)
│   ├── pdo          PDO index (dimensionless)
│   └── ar_count     atmospheric river count (events/month; placeholder = 0)
├── /beta            static (y, x) — climate response coefficients
│   ├── b_spi3       β₁ — SPI-3 sensitivity (m / unit SPI)
│   ├── b_swe        β₂ — SWE sensitivity (m / 100 mm)
│   ├── b_pdo        β₃ — PDO sensitivity (m / unit PDO)
│   ├── b_ar         β₄ — AR sensitivity (placeholder = 0)
│   └── r2           OLS coefficient of determination (dimensionless)
├── /anomaly         dynamic (time, y, x) — climate-response-reconstructed anomaly
│   ├── wte_anomaly_m  Δwte from baseline (m)
│   └── std_m          reconstruction σ (derived from per-site R² residuals)
├── /residual        dynamic (time, y, x) — Stage 3 kriged obs residuals
│   ├── wte_residual_m  observed − (baseline + climate anomaly) (m)
│   └── std_m           kriging σ (m)
├── /final           dynamic (time, y, x) — fully assembled product
│   ├── wte_m          water table elevation (m NAVD88)
│   ├── dtw_m          depth to groundwater (m)
│   └── total_std_m    σ_total = sqrt(σ_lgbm² + σ_krige_baseline² + σ_response² + σ_krige_residual²)
└── /mask            static (y, x)
    └── well_density_50km  1 = within 50 km of a usable well, 0 = extrapolation
```

### Writing a DataTree

```python
from src.io.zarr_io import build_gwl_datatree, write_datatree, add_cf_attrs
import xarray as xr

# build component datasets with CF attributes
wte = add_cf_attrs(wte_da, "water table elevation", "m", "water_table_elevation")
dtw = add_cf_attrs(dtw_da, "depth to groundwater", "m")
baseline_ds = xr.Dataset({"wte_m": wte, "dtw_m": dtw, "std_m": std_da})

dt = build_gwl_datatree(baseline=baseline_ds, mask=mask_ds)
write_datatree(dt, "data/processed/gwl_output.zarr")
```

### Reading a DataTree

```python
from src.io.zarr_io import read_datatree

dt = read_datatree("data/processed/gwl_output.zarr")
dtw = dt["final/dtw_m"]          # xr.DataArray
baseline_wte = dt["baseline"]["wte_m"]
```

---

## Four-Part Provenance (GAIA standard)

Every output product carries four provenance fields as STAC `extra_fields`:

| Field | Key | Example |
|-------|-----|---------|
| Source | `gaia:source` | `"USGS-NWIS + 3DEP + SOLUS100 + PRISM"` |
| Measurement | `gaia:measurement` | `"depth-to-water (m below surface)"` |
| Resolution | `gaia:resolution_m` | `1000` |
| Uncertainty | `gaia:uncertainty_path` | `"data/processed/gwl_std.zarr"` |

Generate a STAC sidecar JSON after each model run:

```python
from src.io.stac_publish import make_stac_item, save_stac_item
from pathlib import Path

item = make_stac_item(
    product_path=Path("data/processed/gwl_dtw.zarr"),
    product_id="gwl_dtw_pnw_2024_01",
    source="USGS-NWIS + 3DEP + SOLUS100 + PRISM",
    measurement="depth-to-water (m below surface)",
    resolution_m=1000,
    uncertainty_path=Path("data/processed/gwl_total_std.zarr"),
)
save_stac_item(item)
```

---

## Data Access: Loading from s3://cresst

SOLUS100 soil properties and PRISM climate are available on s3://cresst with anonymous
read access via odc.stac:

```python
import odc.stac
import pystac_client

PNW_BBOX = (-124.9, 42.0, -116.5, 49.0)  # west, south, east, north WGS84

catalog = pystac_client.Client.open("https://gaia-hazlab.github.io/solus-stac/catalog.json")
items = list(catalog.search(bbox=PNW_BBOX, collections=["solus100"]).items())
ds = odc.stac.load(
    items,
    bands=["clay_0_5cm_mean", "ksat_0_5cm_mean"],
    crs="EPSG:5070",
    resolution=100,     # native SOLUS100 resolution
    chunks={"x": 512, "y": 512},
)
```

Use `s3fs.S3FileSystem(anon=True)` for direct Zarr access:

```python
import s3fs, xarray as xr

fs = s3fs.S3FileSystem(anon=True)
store = fs.get_mapper("s3://cresst/solus-stac/solus100_pnw.zarr")
ds = xr.open_zarr(store, consolidated=True)
```

---

## Lithology Layer Contract (DNR geology → standardized classes)

The lithology layer is **categorical** and originates from **vector polygons** (WA DNR
1:100,000 geology + USGS SGMC), so it does not follow the continuous-raster pattern of
SOLUS/PRISM. The raw archive and the analysis layer are deliberately separate tiers:

| Tier | Format | Notes |
|------|--------|-------|
| Raw archive | GeoParquet / GeoPackage (vector) | original DNR unit codes, lossless — **not** Zarr |
| Analysis layer | categorical uint8 COG / Zarr, 90 m EPSG:5070 | classes below, nodata `255`, **nearest-neighbour only** |
| Crosswalk | `lithology_crosswalk.json` | DNR-unit → class mapping (human-curated, reviewable) |

Standardized classes (lock-step with `src.features.hydrogeologic_domains.LITHO_*`):

| Code | Class | Examples |
|------|-------|----------|
| 0 | unconsolidated | alluvium, glacial drift/outwash, fill |
| 1 | fractured_bedrock | sedimentary / metamorphic / intrusive / pre-Tertiary volcanics |
| 2 | young_volcanic | High Cascade basalt, stratovolcano edifices (Plio-Pleistocene+) |
| 3 | crbg | Columbia River Basalt Group (Miocene) |
| 255 | nodata | unmapped unit — explicit, never silently misclassified |

**Producer (DataHub / gaia-cli, target):** publish the `lithology-stac` collection
(`https://gaia-hazlab.github.io/lithology-stac/catalog.json`, backed by
`s3://cresst/lithology-stac/lithology_wa.zarr`).

**Producer (intermediate / local, today):** `src/data/rasterize_geology.py` does the
identical polygon→90 m raster on a laptop and writes `data/processed/lithology_90m.tif`.
See [intermediate-staging-plan.md](intermediate-staging-plan.md).

**Consumer:** `fetch_gaia.fetch_lithology` (`resampling="nearest"`, nodata 255) →
`hydrogeologic_domains` via `--lithology`. **Never interpolate class codes.**

---

## CRS and Units

| Parameter | Rule |
|-----------|------|
| Analysis CRS | EPSG:5070 (NAD83 / CONUS Albers, metres) |
| Delivery CRS | EPSG:4326 (WGS84, degrees) |
| Elevation units | Metres (m NAVD88 for WTE; m below surface for DTW) |
| Time | UTC, `numpy.datetime64` or `pandas.Timestamp`; no bare strings |
| Precipitation | mm (convert PRISM inches on ingest) |
| SWE | mm liquid-water equivalent |

---

## CF Attributes (required on every output DataArray)

```python
da.attrs = {
    "long_name": "...",           # human-readable, always required
    "units": "...",               # udunits string, always required
    "standard_name": "...",       # CF standard name where one exists
    "grid_mapping": "albers_conical_equal_area",   # always EPSG:5070
}
```

The grid-mapping scalar variable is attached by `build_gwl_datatree()` automatically.

---

## Zarr Chunking Strategy

| Dimension | Chunk size | Rationale |
|-----------|-----------|-----------|
| time | 12 | One year per chunk — aligns with seasonal analysis patterns |
| y (northing) | 256 | ~256 km tiles at 1 km resolution |
| x (easting) | 256 | Same |
| depth (soils) | full | SOLUS100 depth layers are always read together |

Static fields (baseline, beta, mask) have no time dimension and use spatial chunks only.

---

## Complementarity with GAIA Pillar 1

GAIA Pillar 1 (Soil Reanalysis) produces `d_wt(x,t)` via Richards equation + rock physics
from the top down (vadose zone). gwl-space-time-smooth produces GWT from the bottom up
anchored to USGS NWIS observations.

These products cross-validate at the water-table surface. Use `src/evaluation/pillar1_compare.py`
to assess agreement; expected behavior:
- Valley floors (HAND < 5 m): both products should agree within 2 m.
- Ridge crests (HAND > 50 m): Pillar 1 may diverge — it handles vadose physics correctly
  but has no observation anchor in mountains.
- Use gwl-space-time-smooth for coastal/basin liquefaction models.
- Use Pillar 1 for vadose-zone soil saturation profiles in landslide models.
