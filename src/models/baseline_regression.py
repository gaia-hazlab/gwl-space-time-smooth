"""Stage 1: LightGBM regression kriging spatial baseline.

Replaces src/models/interpolate_baseline.py (GStatSim co-kriging MM1).

Pipeline:
  1. Load well sites (median DTW per site from QC-passed wells).
  2. Sample terrain (HAND, TWI, slope) + soil (SOLUS100 Ksat, clay%) + climate
     (mean annual ppt) at each well location.
  3. Spatial block CV (verde.BlockShuffleSplit, 200 km blocks) → RMSE, R².
  4. Fit LGBMRegressor on all usable sites.
  5. Conformal prediction intervals via MapieRegressor.
  6. Predict DTW on the 1 km grid.
  7. Compute residuals at wells; krige residuals via pykrige.OrdinaryKriging.
  8. Final DTW = LightGBM prediction + kriged residuals.
     Final WTE = DEM_1km − Final DTW.

Outputs (data/processed/):
  baseline_dtw_m.tif          — median DTW (m, positive = below surface)
  baseline_wte_m.tif          — median WTE = DEM − DTW (m NAVD88)
  baseline_lgbm_std_m.tif     — conformal PI half-width (90% PI / 2)
  baseline_kriging_std_m.tif  — kriging σ on residuals (m)
  well_density_mask.tif       — 1 where nearest well ≤ 50 km, 0 elsewhere
  lgbm_feature_importance.json
  block_cv_metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_bounds
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

# Feature set: (column_name, source)
# Columns produced by _build_feature_matrix()
FEATURE_COLS = [
    "hand_m",          # terrain: Height Above Nearest Drainage
    "twi",             # terrain: Topographic Wetness Index
    "slope_deg",       # terrain: slope in degrees
    "ksat_cm_hr",      # soil: saturated hydraulic conductivity (SOLUS100)
    "clay_pct",        # soil: clay fraction 0-5 cm (SOLUS100)
    "mean_ppt_mm",     # climate: mean annual precipitation (PRISM)
    "aridity_idx",     # climate: mean_ppt / (PET proxy) — computed as lat-adjusted
    "easting_km",      # location: EPSG:5070 easting / 1000
    "northing_km",     # location: EPSG:5070 northing / 1000
]
TARGET_COL = "median_dtw_m"

NODATA = -9999.0
WELL_DENSITY_RADIUS_M = 50_000  # 50 km mask threshold

# Kriging parameters (same as legacy interpolate_baseline.py for consistency)
K_NEIGHBOURS = 100
SEARCH_RADIUS_M = 300_000
N_SGS_REALISATIONS = 0  # deterministic kriging (regression kriging handles uncertainty)


def _load_sites(sites_parquet: Path) -> pd.DataFrame:
    """Load QC-passed sites with usable long-term median DTW."""
    df = pd.read_parquet(sites_parquet)
    # Only use sites with reliable median
    mask = (
        (~df.get("is_sparse_timeseries", pd.Series(False, index=df.index)))
        & (~df.get("is_deep_well", pd.Series(False, index=df.index)))
        & df["median_dtw_m"].notna()
        & (df["median_dtw_m"] > 0)  # DTW must be positive
    )
    df = df[mask].copy()
    logger.info("Loaded %d usable sites for baseline regression.", len(df))
    return df


def _sample_raster_at_points(
    raster_path: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> np.ndarray:
    """Sample a raster at (x, y) point coordinates in EPSG:5070."""
    import rasterio
    coords = list(zip(x_5070.tolist(), y_5070.tolist()))
    with rasterio.open(raster_path) as src:
        values = np.array([v[0] for v in src.sample(coords)], dtype=np.float32)
    values[values == NODATA] = np.nan
    return values


def _load_solus_at_points(
    solus_zarr: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> pd.DataFrame:
    """Sample SOLUS100 Zarr at site locations; return DataFrame."""
    import xarray as xr

    ds = xr.open_zarr(solus_zarr, consolidated=True)
    rows = []
    for xi, yi in zip(x_5070, y_5070):
        row = {}
        for var in ("ksat_cm_hr", "clay_pct"):
            if var in ds:
                row[var] = float(
                    ds[var].sel(x=xi, y=yi, method="nearest").values
                )
            else:
                row[var] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _build_feature_matrix(
    sites: pd.DataFrame,
    hand_tif: Path,
    twi_tif: Path,
    slope_tif: Path,
    solus_zarr: Path,
    prism_ppt_tif: Path,
) -> pd.DataFrame:
    """Build the LightGBM feature matrix for all usable sites."""
    x = sites["x_5070"].values
    y = sites["y_5070"].values

    feats = pd.DataFrame(index=sites.index)
    feats["hand_m"] = _sample_raster_at_points(hand_tif, x, y)
    feats["twi"] = _sample_raster_at_points(twi_tif, x, y)
    feats["slope_deg"] = _sample_raster_at_points(slope_tif, x, y)
    feats["mean_ppt_mm"] = _sample_raster_at_points(prism_ppt_tif, x, y)

    soil = _load_solus_at_points(solus_zarr, x, y)
    soil.index = sites.index
    feats["ksat_cm_hr"] = soil["ksat_cm_hr"]
    feats["clay_pct"] = soil["clay_pct"]

    # Aridity index: precipitation / (potential evapotranspiration proxy)
    # Proxy: Thornthwaite PET ≈ 1200 mm/yr at PNW latitudes as first approximation
    feats["aridity_idx"] = feats["mean_ppt_mm"] / 1200.0

    feats["easting_km"] = x / 1000.0
    feats["northing_km"] = y / 1000.0

    return feats


def _read_grid(dem_tif: Path) -> tuple[np.ndarray, np.ndarray, rasterio.profiles.Profile]:
    """Return (x_grid, y_grid) flat arrays and profile from the 1 km DEM."""
    with rasterio.open(dem_tif) as src:
        profile = src.profile.copy()
        rows, cols = np.meshgrid(
            np.arange(src.height), np.arange(src.width), indexing="ij"
        )
        # Centre of each pixel
        xs, ys = rasterio.transform.xy(src.transform, rows.ravel(), cols.ravel())
    return np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64), profile


def _write_tif(
    arr: np.ndarray, profile: dict, path: Path, nodata: float = NODATA
) -> None:
    """Write a 2D float32 array as a GeoTIFF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    p = profile.copy()
    p.update({"dtype": "float32", "count": 1, "nodata": nodata,
               "compress": "LZW", "tiled": True, "blockxsize": 256, "blockysize": 256})
    arr_out = np.where(np.isnan(arr), nodata, arr).astype(np.float32)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr_out, 1)
    logger.info("Written: %s", path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LightGBM regression kriging spatial GWL baseline."
    )
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--hand", type=Path, default=Path("data/processed/terrain_hand_1km.tif"))
    parser.add_argument("--twi", type=Path, default=Path("data/processed/terrain_twi_1km.tif"))
    parser.add_argument("--slope", type=Path, default=Path("data/processed/terrain_slope_1km.tif"))
    parser.add_argument("--solus", type=Path, default=Path("data/processed/solus100_pnw.zarr"))
    parser.add_argument("--prism-ppt", type=Path, default=Path("data/processed/prism_mean_annual_ppt_pnw.tif"))
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/3dep_1km_5070.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--n-cv-splits", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from lightgbm import LGBMRegressor
    from mapie.regression import MapieRegressor
    from pykrige.ok import OrdinaryKriging
    from sklearn.preprocessing import QuantileTransformer
    from src.evaluation.cross_validate import spatial_block_cv, run_cv_metrics

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load sites
    sites = _load_sites(args.sites)
    feats = _build_feature_matrix(
        sites, args.hand, args.twi, args.slope, args.solus, args.prism_ppt
    )

    # Drop sites with any missing feature
    valid = feats[FEATURE_COLS].notna().all(axis=1)
    sites = sites[valid]
    feats = feats[valid]
    y = sites[TARGET_COL].values.astype(np.float64)
    X = feats[FEATURE_COLS].values.astype(np.float64)
    coords = np.column_stack([sites["x_5070"].values, sites["y_5070"].values])

    logger.info("Fitting baseline on %d wells with %d features.", len(y), X.shape[1])

    # Spatial block CV
    lgbm = LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=63,
                          random_state=0, n_jobs=-1)
    cv_metrics = run_cv_metrics(lgbm, X, y, coords, n_splits=args.n_cv_splits)
    with open(out_dir / "block_cv_metrics.json", "w") as fh:
        json.dump(cv_metrics, fh, indent=2)
    logger.info("CV: RMSE=%.2f m  R²=%.3f", cv_metrics["rmse_mean"], cv_metrics["r2_mean"])

    # Final fit on all usable sites
    lgbm.fit(X, y)

    # Feature importance
    importance = dict(zip(FEATURE_COLS, lgbm.feature_importances_.tolist()))
    with open(out_dir / "lgbm_feature_importance.json", "w") as fh:
        json.dump(importance, fh, indent=2)

    # Conformal prediction (90% PI)
    from verde import BlockShuffleSplit
    spatial_cv = BlockShuffleSplit(spacing=200_000, n_splits=args.n_cv_splits, random_state=0)
    mapie = MapieRegressor(estimator=LGBMRegressor(n_estimators=500, learning_rate=0.05,
                                                    num_leaves=63, random_state=0, n_jobs=-1),
                           method="plus", cv=spatial_cv)
    mapie.fit(X, y, groups=(coords[:, 0], coords[:, 1]))

    # Grid prediction
    logger.info("Predicting DTW on 1 km grid from %s ...", args.dem)
    x_grid, y_grid, dem_profile = _read_grid(args.dem)
    nrows = dem_profile["height"]
    ncols = dem_profile["width"]

    # Sample terrain features on grid
    def _grid_sample(tif: Path) -> np.ndarray:
        with rasterio.open(tif) as src:
            arr = src.read(1).ravel().astype(np.float32)
        arr[arr == NODATA] = np.nan
        return arr

    hand_g = _grid_sample(args.hand)
    twi_g = _grid_sample(args.twi)
    slope_g = _grid_sample(args.slope)
    ppt_g = _grid_sample(args.prism_ppt)

    # SOLUS on grid (bilinear-sampled from native 100m Zarr on read)
    import xarray as xr
    solus_ds = xr.open_zarr(args.solus, consolidated=True)
    ksat_g = np.array(solus_ds["ksat_cm_hr"].sel(
        x=xr.DataArray(x_grid, dims="pts"),
        y=xr.DataArray(y_grid, dims="pts"),
        method="nearest",
    ).values, dtype=np.float32) if "ksat_cm_hr" in solus_ds else np.full_like(hand_g, np.nan)
    clay_g = np.array(solus_ds["clay_pct"].sel(
        x=xr.DataArray(x_grid, dims="pts"),
        y=xr.DataArray(y_grid, dims="pts"),
        method="nearest",
    ).values, dtype=np.float32) if "clay_pct" in solus_ds else np.full_like(hand_g, np.nan)

    aridity_g = ppt_g / 1200.0
    X_grid = np.column_stack([
        hand_g, twi_g, slope_g, ksat_g, clay_g, ppt_g, aridity_g,
        x_grid / 1000.0, y_grid / 1000.0,
    ])

    # Mask rows with any NaN feature
    valid_grid = ~np.isnan(X_grid).any(axis=1)
    dtw_grid = np.full(nrows * ncols, np.nan)
    lgbm_std_grid = np.full(nrows * ncols, np.nan)

    y_pred, y_pi = mapie.predict(X_grid[valid_grid], alpha=0.10)
    dtw_grid[valid_grid] = y_pred
    lgbm_std_grid[valid_grid] = (y_pi[:, 1, 0] - y_pi[:, 0, 0]) / 2.0

    dtw_grid_2d = dtw_grid.reshape(nrows, ncols)
    lgbm_std_2d = lgbm_std_grid.reshape(nrows, ncols)

    # Krige residuals
    logger.info("Kriging LightGBM residuals at %d well sites...", len(y))
    resid = y - lgbm.predict(X)
    # NST before kriging
    qt = QuantileTransformer(n_quantiles=min(500, len(resid)), output_distribution="normal",
                              random_state=0)
    resid_nst = qt.fit_transform(resid.reshape(-1, 1)).ravel()

    ok = OrdinaryKriging(
        sites["x_5070"].values,
        sites["y_5070"].values,
        resid_nst,
        variogram_model="exponential",
        nlags=20,
        enable_plotting=False,
        verbose=False,
    )
    z_krige_nst, ss = ok.execute(
        "points",
        x_grid[valid_grid],
        y_grid[valid_grid],
        backend="loop",
        n_closest_points=K_NEIGHBOURS,
    )
    z_krige = qt.inverse_transform(
        np.array(z_krige_nst).reshape(-1, 1)
    ).ravel()
    krige_std = np.sqrt(np.maximum(ss, 0))

    resid_grid = np.full(nrows * ncols, np.nan)
    krige_std_grid = np.full(nrows * ncols, np.nan)
    resid_grid[valid_grid] = z_krige
    krige_std_grid[valid_grid] = krige_std

    resid_2d = resid_grid.reshape(nrows, ncols)
    krige_std_2d = krige_std_grid.reshape(nrows, ncols)

    # Final DTW and WTE
    dtw_final_2d = dtw_grid_2d + resid_2d
    with rasterio.open(args.dem) as dem_src:
        dem_arr = dem_src.read(1).astype(np.float32)
        dem_arr[dem_arr == dem_src.nodata] = np.nan
    wte_final_2d = dem_arr - dtw_final_2d

    # Well density mask
    tree = cKDTree(np.column_stack([sites["x_5070"].values, sites["y_5070"].values]))
    dist, _ = tree.query(np.column_stack([x_grid, y_grid]))
    mask_2d = (dist.reshape(nrows, ncols) <= WELL_DENSITY_RADIUS_M).astype(np.float32)

    # Write outputs
    _write_tif(dtw_final_2d, dem_profile, out_dir / "baseline_dtw_m.tif")
    _write_tif(wte_final_2d, dem_profile, out_dir / "baseline_wte_m.tif")
    _write_tif(lgbm_std_2d, dem_profile, out_dir / "baseline_lgbm_std_m.tif")
    _write_tif(krige_std_2d, dem_profile, out_dir / "baseline_kriging_std_m.tif")
    _write_tif(mask_2d, dem_profile, out_dir / "well_density_mask.tif")

    logger.info("Baseline regression kriging complete.")


if __name__ == "__main__":
    main()
