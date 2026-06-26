# gwl-space-time-smooth — GAIA HazLab

[![Render & Publish Quarto Site](https://github.com/gaia-hazlab/gwl-space-time-smooth/actions/workflows/quarto-pages.yml/badge.svg)](https://github.com/gaia-hazlab/gwl-space-time-smooth/actions/workflows/quarto-pages.yml)

**[📄 Read the technical paper →](https://gaia-hazlab.github.io/gwl-space-time-smooth/)**

Observation-anchored monthly groundwater level (GWL) product for the Pacific Northwest,
integrated with the [GAIA HazLab](https://gaia-hazlab.github.io) ecosystem. Outputs
support Sanger et al. liquefaction models (valleys/basins) and LandLab landslide
modeling (mountain slopes).

> **Core philosophy**: Real wells first. HAND-based terrain physics second. Climate
> response functions third. Never trust a gridded product until validated against
> held-out observations.

---

## Scientific Motivation

Standard GWL products (Fan et al. 2013, HydroGEN) use DEM elevation as the primary
spatial predictor, which causes HUC-2 tiling artifacts and places the highest uncertainty
exactly where liquefaction risk is greatest (valley floors). This project replaces
DEM with **HAND (Height Above Nearest Drainage)** — HAND=0 in valley floors, large on
ridges — and adds per-site climate response functions to capture PNW seasonal signals
(atmospheric rivers, snowpack, PDO/ENSO).

Four signals modelled:
1. PNW seasonal variations (fall storms → snowpack → late snowmelt recharge)
2. Extreme events (atmospheric rivers, summer droughts) via SPI-3
3. La Niña/El Niño multi-year variations via PDO index
4. Coastal SoDo subsidence and sea level rise (Stage 4, deferred)

## Outputs

- `gwl_wte.zarr` — monthly WTE (m NAVD88), 1 km EPSG:5070
- `gwl_dtw.zarr` — monthly DTW (m below surface)
- `gwl_climate_response.zarr` — Stage 2 climate-response anomaly
- `gwl_residual.zarr` — Stage 3 kriged observation residuals
- `baseline_dtw_m.tif` — long-term median DTW (LightGBM + kriged residuals)
- `beta_spi3_1km.tif`, `beta_swe_1km.tif`, `beta_pdo_1km.tif` — β-coefficient maps
- `well_density_mask.tif` — 1 = within 50 km of usable well

All outputs are also written as an **xarray.DataTree** Zarr store (`gwl_output.zarr`)
with GAIA four-part provenance (source, measurement, resolution, uncertainty).

## Scope

| Parameter | Value |
|-----------|-------|
| **Spatial domain** | PNW pilot (WA + OR); expandable to CONUS |
| **Temporal resolution** | Monthly |
| **Temporal extent** | 2000-01-01 → present |
| **Output grid** | 1 km, EPSG:5070 (NAD83 CONUS Albers) |
| **Delivery CRS** | EPSG:4326 |
| **Stage 1 model** | LightGBM + kriged residuals (replaces co-kriging MM1) |
| **Stage 2 model** | Per-site OLS β-maps (SPI-3, SWE, PDO) |
| **Stage 3 model** | Ordinary kriging of observation residuals |
| **GAIA data** | SOLUS100, PRISM-stac from s3://cresst; gaia-cli compatible |

---

## Repository Structure

```
.
├── pixi.toml                  ← canonical dependency file (use `pixi install`)
├── Makefile                   ← pipeline entry points
├── README.md                  ← this file
│
├── src/
│   ├── data/
│   │   ├── download_nwis.py      ← USGS NWIS well download (state-by-state, checkpointed)
│   │   ├── qc_nwis.py            ← QC chain + monthly aggregation (no gap filling)
│   │   ├── download_3dep.py      ← 3DEP 10 m DEM via py3dep (replaces download_dem.py)
│   │   ├── fetch_gaia.py         ← SOLUS100 + PRISM from s3://cresst via odc.stac
│   │   └── fetch_climate.py      ← PDO index, SNODAS SWE, SPI-3 derivation
│   ├── features/
│   │   ├── compute_grid.py       ← canonical 1 km EPSG:5070 grid definition
│   │   └── compute_terrain.py    ← HAND, TWI, slope, contributing area from 3DEP DEM
│   ├── models/
│   │   ├── baseline_regression.py   ← Stage 1: LightGBM + regression kriging
│   │   ├── climate_response.py      ← Stage 2: per-site OLS β-maps
│   │   ├── interpolate_residuals.py ← Stage 3: krige residuals + final assembly
│   │   ├── interpolate_baseline.py  ← LEGACY: co-kriging MM1 (comparison only)
│   │   └── interpolate_anomalies.py ← LEGACY: ordinary kriging of anomalies
│   ├── evaluation/
│   │   ├── cross_validate.py        ← verde.BlockShuffleSplit spatial block CV
│   │   ├── uncertainty_stack.py     ← combine σ_lgbm + σ_krige + σ_response
│   │   └── pillar1_compare.py       ← compare vs GAIA Pillar 1 d_wt
│   └── io/
│       ├── zarr_io.py               ← xarray.DataTree write/read + CF attrs
│       └── stac_publish.py          ← STAC item + GAIA four-part provenance
│
├── notebooks/
│   ├── 01_eda.ipynb              ← well data + HAND vs DTW scatter
│   ├── 02_hydrogen_eda.ipynb     ← HydroGEN vs LightGBM baseline comparison
│   ├── 03_temporal_model.ipynb   ← climate response + residual kriging
│   ├── 04_climate_response.ipynb ← β maps, terrain-zone sensitivity
│   └── 05_gaia_integration.ipynb ← SOLUS100 loading, DataTree output demo
│
├── data/                      ← all data files are git-ignored
│   ├── raw/
│   │   ├── nwis/              ← one parquet per state + download_log.json
│   │   ├── dem/               ← 3dep_10m_5070.tif, 3dep_1km_5070.tif
│   │   ├── climate/           ← pdo_monthly.csv, snodas_swe_monthly_pnw.zarr
│   │   └── MANIFEST.md        ← dataset registry (git-tracked)
│   └── processed/             ← QC'd parquets, terrain TIFs, β maps, Zarr archives
│
├── docs/
│   ├── REFACTORING_PLAN.md    ← 6-phase GAIA integration plan (git-tracked)
│   ├── gaia-conventions.md    ← DataTree schema, STAC provenance, s3://cresst patterns
│   ├── assumptions.md         ← severity-tagged assumptions register
│   └── limitations.md         ← known limitations
│
└── .github/
    ├── copilot-instructions.md        ← workspace coding rules (updated for GAIA)
    └── skills/water-table-model/
        ├── SKILL.md                   ← domain skill (updated for HAND + β-maps)
        └── references/                ← modeling reference docs
```

**Data provenance rule**: `.parquet`, `.tif`, `.nc`, `.zarr`, `.csv` files are never
committed. Only `download_log.json`, `MANIFEST.md`, and `src/` scripts are tracked.

---

## Reproducing

### 1. Environment

This project uses [pixi](https://prefix.dev/docs/pixi/) for reproducible environments.
Do **not** use `conda` or `pip` directly.

```bash
pixi install       # first time, or after pixi.toml changes
pixi run lab       # launch JupyterLab
pixi shell         # activate the environment in a shell
```

### 2. USGS API key (required for `make data`)

`make data` calls the [USGS Water Data OGC API](https://api.waterdata.usgs.gov/).
Anonymous requests are rate-limited to roughly 1 request/second; at CONUS scale
(~1,800 batches) this triggers `429 Too Many Requests` errors mid-download.
A free API key raises the limit significantly and is **strongly recommended**.

**Getting a key (2 minutes):**

1. Go to <https://api.waterdata.usgs.gov/signup/>
2. Fill in your name and email address — no institution required.
3. You will receive the key immediately by email (subject line: *Your USGS Water Data API Key*).

**Using the key:**

```bash
export USGS_API_KEY=your_key_here   # add to ~/.zshrc or ~/.bashrc to persist
make data
```

The script reads `USGS_API_KEY` from the environment and passes it as a query
parameter on every request.  If the variable is unset the script falls back to
anonymous access with automatic exponential-backoff retry (up to 6 retries per
batch, starting at 15 s and doubling each time), but the download will be
significantly slower and may still hit the anonymous concurrency limit.

> **Note**: The download is checkpointed per state in `data/raw/nwis/download_log.json`.
> If it is interrupted (rate-limited or otherwise), just re-run `make data` and it
> will resume from where it left off — already-completed states are skipped.

### 3. Pipeline (GAIA-integrated)

Run targets in order. Each target is idempotent.

```bash
make data              # Download NWIS GW levels (state-by-state, checkpointed)
make qc                # QC + monthly aggregation → data/processed/
make 3dep              # 3DEP 10 m DEM for PNW (replaces make dem)
make gaia-data         # SOLUS100 soil properties + PRISM ppt from s3://cresst
make climate           # PDO index, SNODAS SWE, SPI-3 derivation
make terrain           # HAND + TWI + slope → data/processed/terrain_*.tif
make grid              # 1 km EPSG:5070 grid → data/processed/
make baseline          # LightGBM + regression kriging → baseline_*.tif
make climate-response  # β-map OLS fitting → beta_*.tif + gwl_climate_response.zarr
make residuals         # Stage 3 kriging + final GWL → gwl_dtw.zarr / gwl_wte.zarr
make eda               # EDA notebook → HTML
make clean             # Remove processed outputs (keeps raw downloads)
```

`make data` is the slowest step (~hours for CONUS; checkpointed per state).
`make gaia-data` requires anonymous s3 access — no credentials needed.

Legacy pipeline (comparison):
```bash
make baseline-legacy   # Old co-kriging MM1
make anomalies-legacy  # Old ordinary kriging of anomalies
```

### 3. Outputs

| File | Description |
|------|-------------|
| `data/processed/nwis_sites_clean.parquet` | QC-passed well sites |
| `data/processed/nwis_gwlevels_monthly.parquet` | Monthly median WTE/DTW per site |
| `data/raw/dem/3dep_10m_5070.tif` | 3DEP 10 m DEM, EPSG:5070 |
| `data/processed/terrain_hand_1km.tif` | HAND (m above nearest drainage) |
| `data/processed/terrain_twi_1km.tif` | TWI (Beven & Kirkby 1979) |
| `data/processed/solus100_pnw.zarr` | SOLUS100 soil properties (clay, Ksat, pH) |
| `data/processed/spi3_monthly_pnw.zarr` | SPI-3 on 1 km grid |
| `data/processed/baseline_dtw_m.tif` | Long-term median DTW (LightGBM + kriged residual) |
| `data/processed/baseline_wte_m.tif` | Long-term median WTE |
| `data/processed/beta_spi3_1km.tif` | SPI-3 sensitivity β-map |
| `data/processed/beta_swe_1km.tif` | SWE sensitivity β-map |
| `data/processed/beta_pdo_1km.tif` | PDO sensitivity β-map |
| `data/processed/gwl_climate_response.zarr` | Stage 2 climate-response anomaly |
| `data/processed/gwl_dtw.zarr` | Final monthly DTW (m, positive = below surface) |
| `data/processed/gwl_wte.zarr` | Final monthly WTE (m NAVD88) |
| `data/processed/well_density_mask.tif` | 1 = within 50 km of usable well |

---

## AI-Assisted Workflow: Copilot Instructions and Skills

This repository uses GitHub Copilot with custom workspace instructions and a domain skill
to accelerate development. Understanding these files lets you steer or extend the AI
assistance.

### How it works

```
.github/copilot-instructions.md      ← always loaded; sets baseline coding rules
.github/skills/water-table-model/
    SKILL.md                         ← loaded on-demand for domain-specific work
    references/
        data-sources.md              ← NWIS API patterns, field-name mappings
        modeling-approaches.md       ← modeling decision tree, spatial CV caveats
        literature-review-protocol.md ← key papers, literature scan workflow
```

Copilot reads `.github/copilot-instructions.md` for every conversation in this workspace.
The `SKILL.md` is loaded automatically when you ask questions related to groundwater
modeling (keywords listed in the skill frontmatter).

### Workspace instructions (`.github/copilot-instructions.md`)

This file sets project-wide conventions that Copilot must follow for all code in this
repository. Edit it to change:

- **Environment rules** — which package manager to use, Python version constraints, any
  banned imports.
- **Pipeline targets** — which `make` targets exist and what they do; keep this in sync
  with the Makefile.
- **Data layout** — directory names, git-tracked vs. git-ignored files.
- **Coding conventions** — CRS choice, unit conventions (always SI), path handling
  (`pathlib.Path`, no `os.path`), logging (no `print()`), docstring style.
- **QC chain** — the ordered steps in `qc_nwis.py`; any change to the QC chain must be
  reflected here and in the module docstring.

**When to edit**: whenever you add a new pipeline stage, change a directory convention, or
introduce a new data source.

### Skill file (`.github/skills/water-table-model/SKILL.md`)

The skill provides deep domain knowledge activated when you describe groundwater or
water-table tasks. Edit the skill to:

- Add new modeling approaches (e.g., change from GStatSim kriging to a different method).
- Update the trigger keywords in the YAML frontmatter (`description: >`) so Copilot
  activates the skill for new task formulations.
- Link additional reference documents under `references/` for complex sub-topics
  (e.g., add a `covariate-processing.md` when developing the covariates pipeline).

**When to edit**: whenever the modeling approach changes, or when you want Copilot to
favour a particular library or algorithm. The skill is versioned in git alongside the
code it governs.

### Reference documents (`.github/skills/water-table-model/references/`)

Detailed lookup tables and decision trees the skill can point to. Add a new file here
(and a link in `SKILL.md`) when a topic is complex enough to warrant its own reference.

| File | Content |
|------|---------|
| `data-sources.md` | NWIS REST API patterns, available fields, covariate dataset URLs |
| `modeling-approaches.md` | Interpolation method decision tree, spatial CV protocol |
| `literature-review-protocol.md` | Key papers to check, how to scan new literature |

### Quick-reference: what to edit and where

| You want to… | Edit this file |
|---|---|
| Change the Python environment or add a dependency | `pixi.toml` |
| Add a new `make` target | `Makefile` + `pixi.toml [tasks]` + `.github/copilot-instructions.md` |
| Change a coding convention (CRS, units, style) | `.github/copilot-instructions.md` |
| Change the interpolation method | `.github/skills/water-table-model/SKILL.md` + `src/models/` |
| Change the QC chain | `src/data/qc_nwis.py` + docstring + `.github/copilot-instructions.md` |
| Add a new covariate dataset | `src/data/` + `data/raw/MANIFEST.md` + `references/data-sources.md` |
| Add domain knowledge (new paper, new algorithm) | `.github/skills/water-table-model/references/` + `SKILL.md` link |
| Change model assumptions | `docs/assumptions.md` + `.github/copilot-instructions.md` |

---

## Key Documents

- [`docs/assumptions.md`](docs/assumptions.md) — All simplifying assumptions with severity ratings
- [`docs/limitations.md`](docs/limitations.md) — Known limitations, updated continuously
- [`data/raw/MANIFEST.md`](data/raw/MANIFEST.md) — Registry of all raw datasets with provenance

---

## GAIA Ecosystem Credits

This repository is part of the [GAIA HazLab](https://gaia-hazlab.github.io) ecosystem:
- **SOLUS100**: USDA-NRCS, staged on s3://cresst by GAIA
- **PRISM-stac**: PRISM Climate Group, staged on s3://cresst by GAIA
- **Complementary product**: GAIA Pillar 1 (vadose-zone physics) — cross-validates at the water-table surface. See `docs/gaia-conventions.md`.

## Citation

If you use outputs from this pipeline, please cite:
- **USGS NWIS**: [https://waterdata.usgs.gov/nwis/gw](https://waterdata.usgs.gov/nwis/gw)
- **3DEP**: USGS 3D Elevation Program, https://www.usgs.gov/3d-elevation-program
- **SOLUS100**: Ramcharan et al. (2018) + GAIA HazLab staging
- **SNODAS**: NSIDC G02158, https://doi.org/10.7265/N5TB14TC
- **LightGBM**: Ke et al. (2017), NeurIPS

## License

- Code: MIT
- Data products: CC-BY-4.0
