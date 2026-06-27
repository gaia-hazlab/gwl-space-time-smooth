.PHONY: data qc dem grid baseline anomalies covariates eda train validate clean clean-all all \
        pilot pilot-qc pilot-grid pilot-eda hydrogen pilot-baseline uncertainty-stack \
        3dep terrain gaia-data climate baseline-regression climate-response residuals \
        baseline-legacy anomalies-legacy

# === Configuration ===
START_DATE := 2026-01-01
RAW_DIR := data/raw/nwis
RAW_DEM_DIR := data/raw/dem
PROCESSED_DIR := data/processed
MONTHLY_PARQUET := $(PROCESSED_DIR)/nwis_gwlevels_monthly.parquet
SITES_PARQUET := $(PROCESSED_DIR)/nwis_sites_clean.parquet
# 3DEP replaces MERIT Hydro; legacy var kept for backward compat
DEM_TIF := $(RAW_DEM_DIR)/merit_hydro_90m_5070.tif
DEM_3DEP := $(RAW_DEM_DIR)/3dep_10m_5070.tif
HAND_TIF := $(PROCESSED_DIR)/terrain_hand_90m.tif
SPI3_ZARR := $(PROCESSED_DIR)/spi3_monthly_wa.zarr
SWE_ZARR  := data/raw/climate/snodas_swe_monthly_wa.zarr
PDO_CSV   := data/raw/climate/pdo_monthly.csv
SOLUS_ZARR := $(PROCESSED_DIR)/solus100_wa.zarr
GRID_NC := $(PROCESSED_DIR)/conus_grid_90m.nc
BASELINE_WTE := $(PROCESSED_DIR)/baseline_wte_m.tif

# Pacific Northwest pilot scope
PILOT_STATES := WA OR ID
# EPSG:5070 bbox for PNW: left bottom right top (metres)
PNW_BBOX := -2300000 2200000 -1400000 3300000
# WGS84 bbox (for py3dep and odc.stac): west south east north
PNW_BBOX_WGS84 := -124.9 42.0 -116.5 49.0
PILOT_GRID_NC := $(PROCESSED_DIR)/bbox_grid_90m.nc
HYDROGEN_WTD := $(PROCESSED_DIR)/hydrogen_wtd_prior_90m.tif
HYDROGEN_UNC := $(PROCESSED_DIR)/hydrogen_wtd_uncertainty_90m.tif
PILOT_BASELINE_WTE := $(PROCESSED_DIR)/baseline_wte_m.tif
PILOT_BASELINE_STD := $(PROCESSED_DIR)/baseline_kriging_std_m.tif

# === Targets ===

## Primary pipeline (GAIA-integrated)
all: data qc 3dep gaia-data climate terrain grid baseline climate-response residuals

## Download raw NWIS groundwater data (state-by-state, checkpointed)
data:
	pixi run python -m src.data.download_nwis \
		--start-date $(START_DATE) \
		--output-dir $(RAW_DIR)

## Run QC filtering and monthly aggregation
qc: $(RAW_DIR)/download_log.json
	pixi run python -m src.data.qc_nwis \
		--input-dir $(RAW_DIR) \
		--output $(MONTHLY_PARQUET)

## Download 3DEP 10 m DEM for PNW via py3dep (replaces MERIT Hydro)
3dep:
	pixi run python -m src.data.download_3dep \
		--bbox $(PNW_BBOX_WGS84) \
		--output-dir $(RAW_DEM_DIR)

## Compute HAND, TWI, slope, contributing area from 3DEP DEM
terrain: $(DEM_3DEP)
	pixi run python -m src.features.compute_terrain \
		--dem $(DEM_3DEP) \
		--output-dir $(PROCESSED_DIR)

## Fetch SOLUS100 soil properties + PRISM precipitation from s3://cresst via odc.stac
gaia-data:
	pixi run python -m src.data.fetch_gaia solus \
		--bbox $(PNW_BBOX_WGS84) \
		--output-dir $(PROCESSED_DIR)
	pixi run python -m src.data.fetch_gaia prism \
		--bbox $(PNW_BBOX_WGS84) \
		--output-dir $(PROCESSED_DIR)

## Fetch PDO index, SNODAS SWE; derive SPI-3 from PRISM
climate:
	pixi run python -m src.data.fetch_climate pdo \
		--output-dir data/raw/climate
	pixi run python -m src.data.fetch_climate swe \
		--bbox $(PNW_BBOX_WGS84) \
		--output-dir data/raw/climate
	pixi run python -m src.data.fetch_climate spi3 \
		--prism $(PROCESSED_DIR)/prism_monthly_wa.zarr \
		--output-dir $(PROCESSED_DIR)

## Download MERIT Hydro DEM (DEPRECATED — use 3dep instead)
dem:
	@echo "WARNING: make dem is deprecated. Use 'make 3dep' for 3DEP 10m (preferred)."
	pixi run python -m src.data.download_dem \
		--output-dir $(RAW_DEM_DIR)

## Build canonical 90 m WA grid definition
grid: $(DEM_3DEP)
	pixi run python -m src.features.compute_grid \
		--dem $(DEM_3DEP) \
		--output-dir $(PROCESSED_DIR)

## Observation-anchored random forest + kriging spatial baseline (replaces co-kriging MM1)
baseline: $(SITES_PARQUET) $(HAND_TIF) $(SOLUS_ZARR)
	pixi run python -m src.models.baseline_regression \
		--sites $(SITES_PARQUET) \
		--hand $(HAND_TIF) \
		--twi $(PROCESSED_DIR)/terrain_twi_90m.tif \
		--slope $(PROCESSED_DIR)/terrain_slope_90m.tif \
		--solus $(SOLUS_ZARR) \
		--prism-ppt $(PROCESSED_DIR)/prism_mean_annual_ppt_wa.tif \
		--dem $(RAW_DEM_DIR)/3dep_90m_5070.tif \
		--output-dir $(PROCESSED_DIR)

## Per-site OLS β-map climate response functions (Stage 2)
climate-response: $(SITES_PARQUET) $(MONTHLY_PARQUET) $(SPI3_ZARR) $(SWE_ZARR) $(PDO_CSV)
	pixi run python -m src.models.climate_response \
		--monthly $(MONTHLY_PARQUET) \
		--sites $(SITES_PARQUET) \
		--spi3 $(SPI3_ZARR) \
		--swe $(SWE_ZARR) \
		--pdo $(PDO_CSV) \
		--hand $(HAND_TIF) \
		--output-dir $(PROCESSED_DIR)

## Krige residuals (obs − climate_response) and assemble final GWL (Stage 3)
residuals: $(PROCESSED_DIR)/gwl_climate_response.zarr $(MONTHLY_PARQUET)
	pixi run python -m src.models.interpolate_residuals \
		--monthly $(MONTHLY_PARQUET) \
		--sites $(SITES_PARQUET) \
		--climate-response $(PROCESSED_DIR)/gwl_climate_response.zarr \
		--baseline-dtw $(PROCESSED_DIR)/baseline_dtw_m.tif \
		--output-dir $(PROCESSED_DIR)

## Monthly anomaly fields (LEGACY — use climate-response + residuals instead)
anomalies: $(BASELINE_WTE) $(MONTHLY_PARQUET)
	$(MAKE) anomalies-legacy

## Co-kriging MM1 baseline (LEGACY — kept for comparison)
baseline-legacy: $(SITES_PARQUET) $(DEM_TIF)
	pixi run python -m src.models.interpolate_baseline \
		--sites $(SITES_PARQUET) \
		--dem $(DEM_TIF) \
		--output-dir $(PROCESSED_DIR)

## Ordinary kriging anomalies (LEGACY — kept for comparison)
anomalies-legacy: $(BASELINE_WTE) $(MONTHLY_PARQUET)
	pixi run python -m src.models.interpolate_anomalies \
		--monthly $(MONTHLY_PARQUET) \
		--sites $(SITES_PARQUET) \
		--baseline-wte $(BASELINE_WTE) \
		--dem $(DEM_TIF) \
		--output-dir $(PROCESSED_DIR)

## Download covariates — covered by gaia-data and climate targets
covariates: gaia-data climate

## Run EDA notebook — placeholder
eda:
	pixi run jupyter nbconvert --execute notebooks/01_eda.ipynb --to html

## Train model — placeholder
train:
	@echo "TODO: Implement model training pipeline"

## Run validation and artifact detection — placeholder
validate:
	@echo "TODO: Implement validation pipeline"

## PNW pilot — QC (WA + OR only — ID has no level records yet)
pilot-qc: $(RAW_DIR)/download_log.json
	pixi run python -m src.data.qc_nwis \
		--input-dir $(RAW_DIR) \
		--output $(MONTHLY_PARQUET) \
		--states $(PILOT_STATES)

## WA pilot — build regional 90 m grid from bbox (no DEM required)
pilot-grid:
	pixi run python -m src.features.compute_grid \
		--bbox $(PNW_BBOX) \
		--output-dir $(PROCESSED_DIR)

## PNW pilot — run EDA notebook
pilot-eda:
	pixi run jupyter nbconvert --execute notebooks/01_eda.ipynb --to html

## WA pilot — align HydroGEN TIFs to the 90 m EPSG:5070 grid
hydrogen: $(PILOT_GRID_NC)
	pixi run python -m src.features.align_hydrogen \
		--wtd data/comparison/WT2-ma_wtd_50.tif \
		--unc data/comparison/wtd_uncertainty_mosaic_wgs84.tif \
		--grid $(PILOT_GRID_NC) \
		--output-dir $(PROCESSED_DIR)

## PNW pilot — EDK spatial baseline (HydroGEN prior + kriged residuals)
pilot-baseline: $(SITES_PARQUET) $(DEM_TIF) $(HYDROGEN_WTD)
	pixi run python -m src.models.interpolate_baseline \
		--sites $(SITES_PARQUET) \
		--dem $(DEM_TIF) \
		--hydrogen-wtd $(HYDROGEN_WTD) \
		--output-dir $(PROCESSED_DIR)

## PNW pilot — krige monthly WTE anomaly fields onto the bbox grid
## Default: 5 km pilot grid, last 36 months.  Full run: GRID_STEP=1 N_MONTHS=0
GRID_STEP    ?= 5
PILOT_MONTHS ?= 36
pilot-anomalies: $(PILOT_GRID_NC) $(SITES_PARQUET) $(MONTHLY_PARQUET)
	pixi run python -m src.models.pilot_temporal \
		--monthly $(MONTHLY_PARQUET) \
		--sites $(SITES_PARQUET) \
		--grid $(PILOT_GRID_NC) \
		--hydrogen-wtd $(HYDROGEN_WTD) \
		--states $(PILOT_STATES) \
		--grid-step $(GRID_STEP) \
		--n-months $(PILOT_MONTHS) \
		--output-dir $(PROCESSED_DIR)

## Combine physics + EDK uncertainty into a single explainable stack
uncertainty-stack: $(PILOT_BASELINE_STD) $(HYDROGEN_UNC)
	pixi run python -m src.evaluation.uncertainty_stack \
		--physics $(HYDROGEN_UNC) \
		--edk-std $(PILOT_BASELINE_STD) \
		--mask $(PROCESSED_DIR)/well_density_mask.tif \
		--output-dir $(PROCESSED_DIR)

## PNW pilot — full pipeline: download WA/OR/ID → QC → grid → EDA
## (baseline + anomalies still need the DEM; run `make dem` first for those)
pilot: pilot-qc pilot-grid pilot-eda hydrogen pilot-baseline uncertainty-stack

## Clean processed data (keeps raw downloads)
clean:
	rm -f $(MONTHLY_PARQUET) $(SITES_PARQUET) $(PROCESSED_DIR)/qc_report.json

## Nuclear clean (removes everything including raw downloads)
clean-all: clean
	rm -rf $(RAW_DIR)
