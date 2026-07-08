# GAIA Soil Reanalysis — GAIA HazLab

> Formerly **gwl-space-time-smooth**. The GitHub slug rename to `gaia-soil-reanalysis` is pending;
> the badge/site URLs below still use the old slug until then.

[![Render & Publish Quarto Site](https://github.com/gaia-hazlab/gwl-space-time-smooth/actions/workflows/quarto-pages.yml/badge.svg)](https://github.com/gaia-hazlab/gwl-space-time-smooth/actions/workflows/quarto-pages.yml)

**A living hydromechanical state of the subsurface** — water table depth, soil moisture, and
near-surface stiffness (Vs) — at the ~90 m space and time scales that downstream **flood, landslide,
and liquefaction** models need, over the Pacific Northwest. It is built from high-resolution static
layers, assimilated ground sensors and satellites, a **closed pixel-wise water budget**, and
ambient-noise **dv/v** assimilation, integrated with the [GAIA HazLab](https://gaia-hazlab.github.io)
ecosystem. Outputs feed the Sanger liquefaction GLM (valleys/basins) and the LandLab landslide chain
(mountain slopes).

## Published pages

Everything is served from one landing page (self-contained HTML — no build needed to view):

| Page | What it is |
|------|------------|
| **[Landing](https://gaia-hazlab.github.io/gwl-space-time-smooth/)** | Entry point linking everything below |
| **[Technical report](https://gaia-hazlab.github.io/gwl-space-time-smooth/report.html)** | Full framework: mission, scientific & data grounds, coupled water budget, dv/v, Vs30 + NEHRP, uncertainty, validation, digital-twin MVP, LandLab coupling |
| **[GWL + soil-moisture demo](https://gaia-hazlab.github.io/gwl-space-time-smooth/gwl_soil_moisture_demo.html)** | The two mature states produced end-to-end on real public data at 90 m, with animated GIFs |
| **[Audit & forecast framework](https://gaia-hazlab.github.io/gwl-space-time-smooth/gwl_audit_framework.html)** | AI weather forecast → antecedent hydrologic state → hazard forcing |

The report source is `docs/gwl_hybrid_framework.qmd` (Quarto → `report.html`); the demo and audit pages
are pre-rendered self-contained HTML committed under `docs/`.

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

## Demo — coupled GWL + soil moisture

**[📊 Open the demo dashboard →](docs/gwl_soil_moisture_demo.html)** (self-contained; published to
`gaia-hazlab.github.io/gwl-space-time-smooth/gwl_soil_moisture_demo.html`)

Shows two of the three gaia-soil-hydromechanics state variables modelled from one data-driven
pipeline over the Puget Sound pilot: the mature **groundwater-level** module and the new
**soil-moisture** module (`src/models/soil_moisture.py`). Soil moisture combines a static
SOLUS100 → Saxton-Rawls hydraulic envelope with a dynamic TerraClimate (P & PET)
Thornthwaite-Mather water balance; the estimate reproduces TerraClimate's *independent*
soil-water field at **r = 0.98**. Both products are delivered at **90 m** — the coarse dynamic
signal is statistically downscaled onto the fine static envelope, with a tracked
**static / dynamic / downscaling** uncertainty budget and **animated GIFs** of GWL and θ evolving
month-by-month. Rebuild the whole page with `pixi run terraclimate && pixi run soil-moisture && pixi run demo`.

## Outputs

- `soil_hydraulic_envelope_90m.zarr` — static θ_wp/θ_fc/θ_sat/AWC/Ksat (SOLUS → Saxton-Rawls)
- `soil_moisture_monthly_puget.zarr` — monthly volumetric θ + θ_std (2000–2024)
- `gwl_wte.zarr` — monthly WTE (m NAVD88), 90 m EPSG:5070
- `gwl_dtw.zarr` — monthly DTW (m below surface)
- `gwl_climate_response.zarr` — Stage 2 climate-response anomaly
- `gwl_residual.zarr` — Stage 3 kriged observation residuals
- `baseline_dtw_m.tif` — long-term median DTW (random forest + kriged residuals)
- `beta_spi3_90m.tif`, `beta_swe_90m.tif`, `beta_pdo_90m.tif` — β-coefficient maps
- `well_density_mask.tif` — 1 = within 50 km of usable well

All outputs are also written as an **xarray.DataTree** Zarr store (`gwl_output.zarr`)
with GAIA four-part provenance (source, measurement, resolution, uncertainty).

## Scope

| Parameter | Value |
|-----------|-------|
| **Spatial domain** | Washington pilot (Puget Sound lowland); expandable to PNW/CONUS |
| **Temporal resolution** | Monthly |
| **Temporal extent** | 2000-01-01 → present |
| **Output grid** | 90 m, EPSG:5070 (NAD83 CONUS Albers) |
| **Delivery CRS** | EPSG:4326 |
| **Stage 1 model** | Observation-anchored random forest + kriged residuals (replaces co-kriging MM1) |
| **Stage 2 model** | Per-site OLS β-maps (SPI-3, SWE, PDO) |
| **Stage 3 model** | Ordinary kriging of observation residuals |
| **GAIA data** | SOLUS100, POLARIS, Vs30 (Sanger & Maurer), PRISM-stac; gaia-cli compatible |

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
│   │   ├── download_3dep.py      ← 3DEP 10 m DEM via py3dep
│   │   ├── fetch_gaia.py         ← SOLUS100/POLARIS/Vs30/dtb/lithology from s3://cresst via odc.stac
│   │   ├── fetch_public.py       ← same layers from ORIGINAL public hosts (SOLUS100 full set, PRISM) — GAIA-independent
│   │   ├── fetch_vs30.py         ← Vs30: Wald-Allen slope proxy / USGS grid / Sanger-Maurer + NEHRP class prob.
│   │   ├── fetch_terraclimate.py ← TerraClimate P/PET/soil monthly driver (~4 km)
│   │   ├── fetch_prism_monthly.py← PRISM monthly obs driver (ppt+tmean → Hamon PET)
│   │   ├── fetch_{snotel,uscrn}.py ← in-situ soil-moisture station networks (anchors + validation)
│   │   ├── fetch_{smap,merra2}.py  ← satellite / reanalysis soil moisture (native-scale checks)
│   │   ├── fetch_seismic.py      ← UW + CC seismic station metadata / waveforms (seisfetch)
│   │   ├── rasterize_geology.py  ← LOCAL DNR geology polygons → lithology_90m.tif (pre-DataHub)
│   │   └── fetch_climate.py      ← PDO index, SNODAS SWE, SPI-3 derivation
│   ├── features/
│   │   ├── compute_grid.py           ← canonical 90 m EPSG:5070 grid definition
│   │   ├── compute_terrain.py        ← HAND, TWI, slope, contributing area from 3DEP DEM
│   │   ├── hydrogeologic_domains.py  ← domain mask from lithology + HAND + dist-coast (issue #2)
│   │   └── well_hydrostratigraphy.py ← screen wells to the shallow unconfined water table (issue #46)
│   ├── models/
│   │   ├── baseline_regression.py   ← Stage 1: random forest + regression kriging (GWL)
│   │   ├── climate_response.py      ← Stage 2: per-site OLS β-maps
│   │   ├── interpolate_residuals.py ← Stage 3: krige residuals + final assembly
│   │   ├── soil_moisture.py         ← soil-moisture state (Saxton-Rawls envelope × T-M bucket)
│   │   ├── water_budget.py          ← coupled pixel-wise water budget (recharge/capillary/runoff/lateral)
│   │   ├── soil_hydraulics.py       ← modular K_sat / transmissivity registry (shared with LandLab)
│   │   ├── dvv.py                   ← ambient-noise dv/v → depth-separated soil moisture + rel. WTD
│   │   ├── dvv_coupling.py          ← dv/v ↔ state coupling parameters
│   │   ├── downscale.py             ← static-envelope × coarse-driver downscalers + σ budget
│   │   ├── anchor.py                ← precision-weighted point assimilation (obs anchoring)
│   │   ├── attribution.py           ← RF permutation feature-importance attribution
│   │   ├── soil_mechanics.py        ← SCAFFOLD: full soil-mechanics coupling (#19)
│   │   └── interpolate_{baseline,anomalies}.py ← LEGACY co-kriging (comparison only)
│   ├── evaluation/
│   │   ├── cross_validate.py        ← spatial block CV (variogram-sized blocks)
│   │   ├── domain_gates.py          ← per-hydrogeologic-domain RMSE/coverage gates
│   │   ├── confidence_mask.py       ← variogram-driven well-density confidence mask
│   │   ├── coverage.py              ← calibrated-uncertainty coverage / PIT / CRPS
│   │   └── uncertainty_stack.py     ← combine static / dynamic / downscaling σ
│   ├── viz/fonts.py                 ← bundled Inter registration for figures
│   └── io/
│       ├── landlab_export.py        ← dynamic hydro export (canonical .asc/COG + manifest) for LandLab
│       ├── zarr_io.py               ← xarray.DataTree write/read + CF attrs
│       └── stac_publish.py          ← STAC item + GAIA four-part provenance
│
├── notebooks/                   ← figure + product generators (each has a `pixi run` task)
│   ├── make_products_90m.py         ← 90 m GWL + θ GIFs and the downscaling uncertainty budget
│   ├── make_digital_twin.py         ← digital-twin MVP: 2×3 animated state + σ, dv/v assimilation
│   ├── make_dvv_figures.py          ← dv/v module: kernels → banded dv/v (UQ) → SM & rel. WTD
│   ├── make_water_budget_figure.py  ← coupled water-budget demo
│   ├── make_well_screening_figure.py← shallow vs deep-confined well screen
│   ├── make_landlab_export_figure.py← exported LandLab bundle (fields + per-cell σ)
│   └── build_demo_qmd.py / 01_eda.ipynb ← demo-page assembler; EDA
│
├── data/                      ← all data files are git-ignored
│   ├── raw/
│   │   ├── nwis/              ← one parquet per state + download_log.json
│   │   ├── dem/               ← 3dep_10m_5070.tif, 3dep_90m_5070.tif
│   │   ├── climate/           ← pdo_monthly.csv, snodas_swe_monthly_pnw.zarr
│   │   └── MANIFEST.md        ← dataset registry (git-tracked)
│   └── processed/             ← QC'd parquets, terrain TIFs, β maps, Zarr archives
│
├── docs/
│   ├── REFACTORING_PLAN.md          ← 6-phase GAIA integration plan (git-tracked)
│   ├── gaia-conventions.md          ← DataTree schema, STAC provenance, lithology contract
│   ├── intermediate-staging-plan.md ← pre-gaia-cli staging + soil-hydromechanics scope
│   ├── assumptions.md               ← severity-tagged assumptions register
│   └── limitations.md               ← known limitations
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

> **`make` or `pixi run`?** `pixi` is the canonical task runner (gaia-cli parity, and it
> is what the GitHub Actions workflows use). Every `make <target>` below has an equivalent
> `pixi run <target>` — the `Makefile` recipes simply call `pixi run` under the hood, so
> both stay in sync. Use `pixi run <target>` in CI; `make <target>` is a local convenience.

```bash
make data              # Download NWIS GW levels (state-by-state, checkpointed)
make qc                # QC + monthly aggregation → data/processed/
make 3dep              # 3DEP 10 m DEM for PNW (replaces make dem)
make gaia-data         # SOLUS100 soil + PRISM ppt + Vs30 + depth-to-bedrock from s3://cresst
make climate           # PDO index, SNODAS SWE, SPI-3 derivation
make terrain           # HAND + TWI + slope → data/processed/terrain_*.tif
make grid              # 90 m EPSG:5070 grid → data/processed/
make domain-inputs     # lithology + distance-to-coast (see "Lithology" note below)
make domains           # hydrogeologic-domain mask → hydrogeologic_domain_90m.tif (issue #2)
make baseline          # random forest + regression kriging → baseline_*.tif
make climate-response  # β-map OLS fitting → beta_*.tif + gwl_climate_response.zarr
make residuals         # Stage 3 kriging + final GWL → gwl_dtw.zarr / gwl_wte.zarr
make eda               # EDA notebook → HTML
make clean             # Remove processed outputs (keeps raw downloads)
```

`make data` is the slowest step (~hours for CONUS; checkpointed per state).
`make gaia-data` requires anonymous s3 access — no credentials needed. `make domains`
feeds per-domain validation gates in `make baseline`, so run it first.

#### Lithology layer — local vs. DataHub

The `domains` mask needs a standardized lithology raster. Until the GAIA DataHub
`lithology-stac` collection is live, produce it **locally** from WA DNR surface-geology
polygons instead of `make domain-inputs`:

```bash
# 1. discover the attribute values in your DNR extract, to complete the crosswalk
make list-geology-units      # or: pixi run list-geology-units
# 2. edit data/processed/lithology_crosswalk.json until coverage is complete
# 3. rasterize DNR polygons → lithology_90m.tif, aligned to the HAND grid
make lithology-local         # needs make terrain first (uses terrain_hand_90m.tif as --like)
```

`make lithology-local` writes a raster byte-compatible with the future DataHub layer, so
switching to `make domain-inputs` later is a drop-in swap. Point `GEOLOGY_VECTOR` in the
`Makefile` at your DNR file. See [`docs/intermediate-staging-plan.md`](docs/intermediate-staging-plan.md).

Legacy pipeline (comparison):
```bash
make baseline-legacy   # Old co-kriging MM1
make anomalies-legacy  # Old ordinary kriging of anomalies
```

#### Coupled subsurface-state modules

The **GAIA Soil Reanalysis** is a coupled subsurface-state estimator (soil moisture + groundwater
level + near-surface stiffness) for the liquefaction / landslide / flood digital twins. Each state
variable is built the same way: a **fine 90 m static envelope** (what the ground can hold / where
water sits / how stiff it can be) combined with a **coarse dynamic driver** (how it varies in time),
statistically downscaled to 90 m with a tracked uncertainty budget.

| State variable | Static (fine) | Dynamic (coarse / observed) | Status |
|---|---|---|---|
| Groundwater level | HAND + SOLUS → RF baseline (90 m) | kriged monthly well anomalies; coupled pixel-wise water budget | **live** |
| Soil moisture | SOLUS100 → Saxton-Rawls envelope (90 m) | TerraClimate P&PET → T-M bucket (4 km); SNOTEL/USCRN anchors, SMAP/MERRA-2 checks | **live** |
| Near-surface stiffness (Vs) | Vs30 Wald-Allen slope proxy (90 m) + SOLUS | ambient-noise dv/v, depth-separated into soil moisture + relative water table | **live (MVP)** — real multi-year waveform run staged (#30) |

The three coupled through a **closed pixel-wise water budget** (`src/models/water_budget.py`:
recharge, capillary rise, ET, saturation-excess runoff, TOPMODEL lateral flow) and a **petrophysical
bridge** (`src/models/dvv.py`: pore-pressure ↔ dv/v poroelastic, dv/v ↔ partial-saturation/suction).
A modular **K_sat / transmissivity registry** (`src/models/soil_hydraulics.py`) keeps our hydrology
and the LandLab Factor-of-Safety on one pedotransfer, and `src/io/landlab_export.py` exports the
dynamic hydrological state (`water_table__depth`, `soil_moisture__saturation_fraction`, recharge) as
LandLab-ready fields. See the report's **Scientific & Data Grounds** and **Downstream: LandLab
coupling** sections.

**Run the soil-moisture + 90 m coupled demo** (needs `baseline` and `terrain` outputs first):

```bash
# 1. Dynamic driver — TerraClimate monthly precip/PET/soil over the pilot (2000→), via THREDDS NCSS.
pixi run terraclimate          # → data/processed/terraclimate_monthly_puget.zarr

# 2. Soil-moisture state — SOLUS→Saxton-Rawls static envelope × Thornthwaite-Mather dynamic bucket.
pixi run soil-moisture         # → soil_hydraulic_envelope_90m.zarr, soil_moisture_monthly_puget.zarr

# 3. 90 m time-varying products — statistical downscaling → GWL + θ GIFs + tracked σ budget.
pixi run products-90m          # → figures/demo/{gwl_90m,theta_90m}.gif, uncertainty_budget.png, provenance.json

# 3b. Alternative forcing (PRISM obs + Hamon PET) for the forcing ensemble; dv/v-coupling figs.
pixi run prism && pixi run ensemble-dvv

# 3c. Independent θ validation vs SNOTEL in-situ soil moisture (uplands; NRCS AWDB, no auth).
pixi run snotel && pixi run snotel-validate   # → snotel_soil_moisture_monthly.parquet, snotel_validation.{json,png}

# 4. Assemble the self-contained demo page (static figures + GIFs + provenance → Quarto HTML).
pixi run demo                  # → docs/gwl_soil_moisture_demo.html  (also re-runs 1-panel figures)

# soil mechanics (full coupling) is still a scaffold — exits with a message:
pixi run soil-mechanics        # SCAFFOLD (#19)
```

**Mechanics, water budget, digital twin, and the LandLab export:**

```bash
pixi run vs30                  # Vs30 (Wald-Allen slope proxy by default) → vs30_90m.tif
pixi run dvv-demo              # dv/v module figure: kernels → banded dv/v (UQ) → SM + rel. WTD
pixi run water-budget          # coupled water-budget demo (recharge/capillary/runoff/lateral)
pixi run digital-twin          # digital-twin MVP GIF: GWL + θ + Vs30 (+ σ) with dv/v assimilation
pixi run landlab-export        # dynamic hydro export → canonical .asc/COG + manifest (for LandLab)
pixi run landlab-export-figure # figure of the exported LandLab bundle (fields + per-cell σ)
```

The LandLab export writes `water_table__depth`, `soil_moisture__saturation_fraction`, and
`soil_water__recharge_rate` on the shared grid so they drop onto the landslide-data-prep static stack;
static soil-hydromechanical parameters (K_sat, transmissivity) are ingested and reconciled via the
modular `soil_hydraulics` registry, not re-exported.

Each stage is independent Python (`src/data/fetch_terraclimate.py`, `src/models/soil_moisture.py`,
`src/models/gwl_dynamic.py`, `src/models/downscale.py`) with a validated unit test
(`tests/test_soil_moisture.py`). Tests run standalone: `pixi run python -m tests.test_soil_moisture`.

**Outputs & validation.** The soil-moisture θ reproduces TerraClimate's *independent* soil-water
field at **r = 0.98**; the uncertainty budget separates static / dynamic / **downscaling**
representativeness for both products (see `data/processed/provenance.json`). The demo page —
`docs/gwl_soil_moisture_demo.html`, published to
`gaia-hazlab.github.io/gwl-space-time-smooth/gwl_soil_moisture_demo.html` — is a self-contained
Quarto dashboard (all figures/GIFs embedded) suitable for linking from the GAIA soil-reanalysis chapter.

See [`docs/intermediate-staging-plan.md`](docs/intermediate-staging-plan.md) for the scope,
the static/dynamic sources, and the (deferred) rename checklist (#24).

### 3. Outputs

| File | Description |
|------|-------------|
| `data/processed/nwis_sites_clean.parquet` | QC-passed well sites |
| `data/processed/nwis_gwlevels_monthly.parquet` | Monthly median WTE/DTW per site |
| `data/raw/dem/3dep_10m_5070.tif` | 3DEP 10 m DEM, EPSG:5070 |
| `data/processed/terrain_hand_90m.tif` | HAND (m above nearest drainage) |
| `data/processed/terrain_twi_90m.tif` | TWI (Beven & Kirkby 1979) |
| `data/processed/solus100_pnw.zarr` | SOLUS100 soil properties (clay, Ksat, pH) |
| `data/processed/spi3_monthly_pnw.zarr` | SPI-3 on 90 m grid |
| `data/processed/baseline_dtw_m.tif` | Long-term median DTW (random forest + kriged residual) |
| `data/processed/baseline_wte_m.tif` | Long-term median WTE |
| `data/processed/beta_spi3_90m.tif` | SPI-3 sensitivity β-map |
| `data/processed/beta_swe_90m.tif` | SWE sensitivity β-map |
| `data/processed/beta_pdo_90m.tif` | PDO sensitivity β-map |
| `data/processed/gwl_climate_response.zarr` | Stage 2 climate-response anomaly |
| `data/processed/gwl_dtw.zarr` | Final monthly DTW (m, positive = below surface) |
| `data/processed/gwl_wte.zarr` | Final monthly WTE (m NAVD88) |
| `data/processed/well_density_mask.tif` | 1 = within 50 km of usable well |
| `data/processed/terraclimate_monthly_puget.zarr` | Monthly TerraClimate P/PET/soil driver (2000→) |
| `data/processed/soil_hydraulic_envelope_90m.zarr` | Static θ_wp/θ_fc/θ_sat/AWC/Ksat (SOLUS → Saxton-Rawls) |
| `data/processed/soil_moisture_monthly_puget.zarr` | Monthly volumetric θ + θ_std |
| `data/processed/provenance.json` | Per-product source → operation → resolution + σ budget |
| `figures/demo/{gwl,theta}_90m.gif` | Animated 90 m GWL and θ products |
| `docs/gwl_soil_moisture_demo.html` | Self-contained demo dashboard (Quarto) |

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
- **scikit-learn (random forest)**: Pedregosa et al. (2011), JMLR

## License

- Code: MIT
- Data products: CC-BY-4.0
