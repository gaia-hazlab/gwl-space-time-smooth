"""Stage 1: observation-anchored random-forest regression kriging baseline.

Replaces the LightGBM + conformal variant (and the legacy GStatSim co-kriging MM1
in src/models/interpolate_baseline.py).

Design (mirrors docs/gwl_hybrid_framework.qmd, Stage 1):
  * Trains **directly on NWIS well observations** — the wells anchor the model.
  * Predictors are **physically meaningful** DataHub covariates only; absolute
    coordinates (easting/northing) are deliberately excluded, because coordinate
    features let the model memorise where the training wells are and fail at
    ungauged locations. Position enters physically through HAND and the drainage
    network, and through the shared Vs30 field used by the Sanger & Maurer
    liquefaction model.
  * Uncertainty comes from the **random-forest tree ensemble spread** (per-cell σ),
    not a conformal wrapper.

Pipeline:
  1. Load well sites (median DTW per site from QC-passed wells).
  2. Sample terrain (HAND, TWI, slope) + soil (SOLUS100 Ksat, clay%, sand%) +
     stiffness (Vs30) + depth-to-bedrock + climate (mean annual ppt) at each well.
  3. Spatial block CV (verde.BlockShuffleSplit) → RMSE, R².
  4. Fit RandomForestRegressor on all usable sites (OOB score reported).
  5. Predict DTW on the target grid; per-cell σ from the tree ensemble.
  6. Compute residuals at wells; krige residuals via pykrige.OrdinaryKriging.
  7. Final DTW = RF prediction + kriged residuals;  Final WTE = DEM − Final DTW.

Outputs (data/processed/):
  baseline_dtw_m.tif          — median DTW (m, positive = below surface)
  baseline_wte_m.tif          — median WTE = DEM − DTW (m NAVD88)
  baseline_rf_std_m.tif       — random-forest tree-ensemble σ (m)
  baseline_kriging_std_m.tif  — kriging σ on residuals (m)
  well_support_mask_90m.tif   — ordinal confidence (variogram-driven, #4): 0 masked .. 3 high
  well_density_mask.tif       — binary support (confidence > 0; back-compat)
  rf_feature_importance.json
  block_cv_metrics.json       — per-domain spatial-block CV gates (#3)
  coverage_metrics.json       — per-domain interval coverage / PIT / CRPS calibration (#5)
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

# Always-available physical predictors (no coordinates).
# Terrain predictors are always required (HAND is the headline covariate and comes from
# 3DEP, independent of the GAIA DataHub).
BASE_FEATURE_COLS = [
    "hand_m",          # terrain: Height Above Nearest Drainage
    "twi",             # terrain: Topographic Wetness Index
    "slope_deg",       # terrain: slope in degrees
]
# Soil predictors from the SOLUS100/POLARIS zarr — included only when that store exists.
SOLUS_FEATURE_COLS = ["ksat_cm_hr", "clay_pct", "sand_pct"]
# Climate predictors derived from the PRISM mean-annual-ppt raster — included only when it
# exists (aridity_idx = mean_ppt / PET-proxy is derived from the same raster).
PRISM_FEATURE_COLS = ["mean_ppt_mm", "aridity_idx"]
# Optional predictors, included only when the corresponding raster is provided.
# name -> CLI arg attribute holding its raster path.
OPTIONAL_FEATURE_RASTERS = {
    "vs30_ms": "vs30",   # near-surface stiffness (Sanger & Maurer 2025) — shared with liquefaction GLM
    "dtb_m":   "dtb",    # depth to bedrock
}
TARGET_COL = "median_dtw_m"

NODATA = -9999.0
WELL_DENSITY_RADIUS_M = 50_000  # 50 km mask threshold

# Kriging parameters (same as legacy interpolate_baseline.py for consistency)
K_NEIGHBOURS = 100
SEARCH_RADIUS_M = 300_000

# Random-forest hyperparameters (match the qmd demo).
RF_KWARGS = dict(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1)


def _active_feature_cols(args) -> list[str]:
    """Terrain predictors plus any soil/climate/optional layers present on disk.

    The model degrades gracefully to whatever covariates exist: terrain (HAND/TWI/slope)
    is always used; SOLUS soil and PRISM climate predictors join only when their rasters
    are available (e.g. once the GAIA DataHub publishes them).
    """
    cols = list(BASE_FEATURE_COLS)
    if getattr(args, "solus", None) is not None and Path(args.solus).exists():
        cols += SOLUS_FEATURE_COLS
    else:
        logger.info("SOLUS predictors skipped (no store at %s).", getattr(args, "solus", None))
    if getattr(args, "prism_ppt", None) is not None and Path(args.prism_ppt).exists():
        cols += PRISM_FEATURE_COLS
    else:
        logger.info("PRISM predictors skipped (no raster at %s).", getattr(args, "prism_ppt", None))
    for name, arg in OPTIONAL_FEATURE_RASTERS.items():
        path = getattr(args, arg, None)
        if path is not None and Path(path).exists():
            cols.append(name)
        else:
            logger.info("Optional predictor %s skipped (no raster at %s).", name, path)
    return cols


def _load_sites(sites_parquet: Path) -> pd.DataFrame:
    """Load QC-passed sites with usable long-term median DTW."""
    df = pd.read_parquet(sites_parquet)
    mask = (
        (~df.get("is_sparse_timeseries", pd.Series(False, index=df.index)))
        & (~df.get("is_deep_well", pd.Series(False, index=df.index)))
        & df["median_dtw_m"].notna()
        & (df["median_dtw_m"] > 0)  # DTW must be positive
    )
    df = df[mask].copy()

    # Project site lon/lat (EPSG:4326) to the analysis CRS (EPSG:5070) if not already
    # present; every downstream sampler indexes rasters by x_5070/y_5070 metres.
    if "x_5070" not in df.columns or "y_5070" not in df.columns:
        from pyproj import Transformer

        tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
        df["x_5070"], df["y_5070"] = tf.transform(df["lon"].to_numpy(), df["lat"].to_numpy())

    logger.info("Loaded %d usable sites for baseline regression.", len(df))
    return df


def _sample_raster_at_points(
    raster_path: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> np.ndarray:
    """Sample a raster at (x, y) point coordinates in EPSG:5070."""
    coords = list(zip(x_5070.tolist(), y_5070.tolist()))
    with rasterio.open(raster_path) as src:
        values = np.array([v[0] for v in src.sample(coords)], dtype=np.float32)
    values[values == NODATA] = np.nan
    return values


def _sample_domain_at_points(
    domain_tif: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> np.ndarray:
    """Sample the categorical hydrogeologic-domain raster at well points (int codes).

    The raster's nodata is normalised to ``DOMAIN_NODATA`` so out-of-mask wells carry an
    explicit code (they intersect no domain in per_domain_cv) rather than a silent value.
    """
    from src.features.hydrogeologic_domains import DOMAIN_NODATA

    coords = list(zip(x_5070.tolist(), y_5070.tolist()))
    with rasterio.open(domain_tif) as src:
        vals = np.array([v[0] for v in src.sample(coords)], dtype=np.int16)
        nod = src.nodata
    if nod is not None:
        vals[vals == int(nod)] = DOMAIN_NODATA
    return vals


def _load_solus_at_points(
    solus_zarr: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> pd.DataFrame:
    """Sample SOLUS100 Zarr at site locations; return DataFrame."""
    import xarray as xr

    ds = xr.open_zarr(solus_zarr, consolidated=True)
    rows = []
    for xi, yi in zip(x_5070, y_5070):
        row = {}
        for var in ("ksat_cm_hr", "clay_pct", "sand_pct"):
            if var in ds:
                row[var] = float(ds[var].sel(x=xi, y=yi, method="nearest").values)
            else:
                row[var] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _build_feature_matrix(
    sites: pd.DataFrame,
    active_cols: list[str],
    hand_tif: Path,
    twi_tif: Path,
    slope_tif: Path,
    solus_zarr: Path,
    prism_ppt_tif: Path,
    optional_rasters: dict[str, Path],
) -> pd.DataFrame:
    """Build the random-forest feature matrix for all usable sites."""
    x = sites["x_5070"].values
    y = sites["y_5070"].values

    feats = pd.DataFrame(index=sites.index)
    feats["hand_m"] = _sample_raster_at_points(hand_tif, x, y)
    feats["twi"] = _sample_raster_at_points(twi_tif, x, y)
    feats["slope_deg"] = _sample_raster_at_points(slope_tif, x, y)

    # SOLUS soil predictors — only when their columns are active (store present).
    if any(c in active_cols for c in SOLUS_FEATURE_COLS):
        soil = _load_solus_at_points(solus_zarr, x, y)
        soil.index = sites.index
        feats["ksat_cm_hr"] = soil["ksat_cm_hr"]
        feats["clay_pct"] = soil["clay_pct"]
        feats["sand_pct"] = soil["sand_pct"]

    # PRISM climate predictors — only when active (raster present). Aridity index:
    # precipitation / (PET proxy ≈ 1200 mm/yr at PNW latitudes).
    if any(c in active_cols for c in PRISM_FEATURE_COLS):
        feats["mean_ppt_mm"] = _sample_raster_at_points(prism_ppt_tif, x, y)
        feats["aridity_idx"] = feats["mean_ppt_mm"] / 1200.0

    # Optional physical predictors.
    for name, path in optional_rasters.items():
        feats[name] = _sample_raster_at_points(path, x, y)

    return feats[active_cols]


def _read_grid(dem_tif: Path) -> tuple[np.ndarray, np.ndarray, rasterio.profiles.Profile]:
    """Return (x_grid, y_grid) flat arrays and profile from the target-grid DEM."""
    with rasterio.open(dem_tif) as src:
        profile = src.profile.copy()
        rows, cols = np.meshgrid(
            np.arange(src.height), np.arange(src.width), indexing="ij"
        )
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


def _tree_ensemble_std(rf, X: np.ndarray) -> np.ndarray:
    """Per-sample predictive σ from the spread of the random-forest trees."""
    per_tree = np.stack([est.predict(X) for est in rf.estimators_])
    return per_tree.std(axis=0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Observation-anchored random-forest regression kriging GWL baseline."
    )
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--hand", type=Path, default=Path("data/processed/terrain_hand_90m.tif"))
    parser.add_argument("--twi", type=Path, default=Path("data/processed/terrain_twi_90m.tif"))
    parser.add_argument("--slope", type=Path, default=Path("data/processed/terrain_slope_90m.tif"))
    parser.add_argument("--solus", type=Path, default=Path("data/processed/solus100_wa.zarr"))
    parser.add_argument("--prism-ppt", type=Path, default=Path("data/processed/prism_mean_annual_ppt_wa.tif"))
    parser.add_argument("--vs30", type=Path, default=Path("data/processed/vs30_90m.tif"),
                        help="Vs30 raster (Sanger & Maurer 2025); optional, used if present.")
    parser.add_argument("--dtb", type=Path, default=Path("data/processed/depth_to_bedrock_90m.tif"),
                        help="Depth-to-bedrock raster; optional, used if present.")
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/3dep_90m_5070.tif"))
    parser.add_argument("--domain", type=Path, default=Path("data/processed/hydrogeologic_domain_90m.tif"),
                        help="Hydrogeologic-domain raster (#2) for per-domain validation gates (#3).")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--n-cv-splits", type=int, default=5)
    parser.add_argument("--cv-block-km", type=float, default=200.0,
                        help="Spatial block-CV block size in km (Roberts et al. 2017).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from sklearn.ensemble import RandomForestRegressor
    from sklearn.preprocessing import QuantileTransformer
    from pykrige.ok import OrdinaryKriging
    from src.evaluation.cross_validate import run_cv_metrics

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    active_cols = _active_feature_cols(args)
    optional_rasters = {
        name: getattr(args, arg)
        for name, arg in OPTIONAL_FEATURE_RASTERS.items()
        if name in active_cols
    }
    logger.info("Active predictors (%d, no coordinates): %s", len(active_cols), active_cols)

    # Load sites + features
    sites = _load_sites(args.sites)
    feats = _build_feature_matrix(
        sites, active_cols, args.hand, args.twi, args.slope, args.solus,
        args.prism_ppt, optional_rasters,
    )

    valid = feats[active_cols].notna().all(axis=1)
    sites = sites[valid]
    feats = feats[valid]
    y = sites[TARGET_COL].values.astype(np.float64)
    X = feats[active_cols].values.astype(np.float64)
    coords = np.column_stack([sites["x_5070"].values, sites["y_5070"].values])

    logger.info("Fitting baseline on %d wells with %d features.", len(y), X.shape[1])

    # Validation — per hydrogeologic domain with variogram-sized blocks (#3), not a
    # single pooled gate. Falls back to a pooled score only if no domain raster is given.
    rf = RandomForestRegressor(**RF_KWARGS)
    domain_ranges: dict[str, float] = {}              # domain -> variogram block (m), for #4
    if args.domain and Path(args.domain).exists():
        from src.evaluation.domain_gates import per_domain_cv, write_report
        from src.evaluation.coverage import (per_domain_coverage, rf_spatial_oof,
                                             write_coverage_report)
        from src.features.hydrogeologic_domains import DOMAIN_NODATA
        dom = _sample_domain_at_points(args.domain, sites["x_5070"].values,
                                       sites["y_5070"].values)
        n_out = int((dom == DOMAIN_NODATA).sum())
        if n_out:
            logger.warning("%d of %d wells fall outside the domain mask (nodata) and are "
                           "excluded from per-domain validation.", n_out, len(dom))
        # Per-domain spatial-block CV gates (#3).
        report = per_domain_cv(rf, X, y, coords, dom, n_splits=args.n_cv_splits)
        gates_pass = write_report(report, out_dir / "block_cv_metrics.json")
        if not gates_pass:
            logger.warning("One or more per-domain validation gates FAILED (see "
                           "block_cv_metrics.json).")
        domain_ranges = {name: r["block_km"] * 1000.0
                         for name, r in report.items() if "block_km" in r}
        # Calibrated-uncertainty diagnostics (#5): OOF tree-ensemble σ -> coverage/PIT/CRPS.
        mu_oof, sd_oof = rf_spatial_oof(RF_KWARGS, X, y, coords, dom,
                                        n_splits=args.n_cv_splits,
                                        block_m_by_domain=domain_ranges)
        cov_report = per_domain_coverage(y, mu_oof, sd_oof, dom)
        if not write_coverage_report(cov_report, out_dir / "coverage_metrics.json"):
            logger.warning("Predictive intervals are NOT calibrated in one or more gate "
                           "domains (see coverage_metrics.json).")
    else:
        logger.warning("No --domain raster: falling back to a single pooled CV score. "
                       "Run `make domains` and pass --domain for per-domain gates (#3).")
        cv_metrics = run_cv_metrics(rf, X, y, coords,
                                    spacing_m=args.cv_block_km * 1000.0,
                                    n_splits=args.n_cv_splits)
        with open(out_dir / "block_cv_metrics.json", "w") as fh:
            json.dump({"pooled": cv_metrics}, fh, indent=2)
        logger.info("Pooled CV: RMSE=%.2f m  R²=%.3f",
                    cv_metrics["rmse_mean"], cv_metrics["r2_mean"])

    # Final fit on all usable sites (with OOB estimate).
    rf = RandomForestRegressor(oob_score=True, **RF_KWARGS)
    rf.fit(X, y)
    logger.info("OOB R²=%.3f", rf.oob_score_)

    importance = dict(zip(active_cols, rf.feature_importances_.tolist()))
    with open(out_dir / "rf_feature_importance.json", "w") as fh:
        json.dump(importance, fh, indent=2)

    # Grid prediction
    logger.info("Predicting DTW on target grid from %s ...", args.dem)
    x_grid, y_grid, dem_profile = _read_grid(args.dem)
    nrows = dem_profile["height"]
    ncols = dem_profile["width"]

    def _grid_sample(tif: Path) -> np.ndarray:
        with rasterio.open(tif) as src:
            arr = src.read(1).ravel().astype(np.float32)
        arr[arr == NODATA] = np.nan
        return arr

    grid_feats: dict[str, np.ndarray] = {
        "hand_m": _grid_sample(args.hand),
        "twi": _grid_sample(args.twi),
        "slope_deg": _grid_sample(args.slope),
    }

    # PRISM climate on grid — only when active (mirrors the training feature matrix).
    if any(c in active_cols for c in PRISM_FEATURE_COLS):
        grid_feats["mean_ppt_mm"] = _grid_sample(args.prism_ppt)
        grid_feats["aridity_idx"] = grid_feats["mean_ppt_mm"] / 1200.0

    # SOLUS soil on grid (nearest-sampled from native Zarr) — only when active.
    if any(c in active_cols for c in SOLUS_FEATURE_COLS):
        import xarray as xr
        solus_ds = xr.open_zarr(args.solus, consolidated=True)
        xq = xr.DataArray(x_grid, dims="pts")
        yq = xr.DataArray(y_grid, dims="pts")
        for var in SOLUS_FEATURE_COLS:
            if var in solus_ds:
                grid_feats[var] = np.asarray(
                    solus_ds[var].sel(x=xq, y=yq, method="nearest").values, dtype=np.float32
                )
            else:
                grid_feats[var] = np.full_like(grid_feats["hand_m"], np.nan)

    for name, path in optional_rasters.items():
        grid_feats[name] = _grid_sample(path)

    X_grid = np.column_stack([grid_feats[c] for c in active_cols])

    valid_grid = ~np.isnan(X_grid).any(axis=1)
    dtw_grid = np.full(nrows * ncols, np.nan)
    rf_std_grid = np.full(nrows * ncols, np.nan)

    dtw_grid[valid_grid] = rf.predict(X_grid[valid_grid])
    rf_std_grid[valid_grid] = _tree_ensemble_std(rf, X_grid[valid_grid])

    dtw_grid_2d = dtw_grid.reshape(nrows, ncols)
    rf_std_2d = rf_std_grid.reshape(nrows, ncols)

    # Krige residuals (normal-score transform first).
    logger.info("Kriging random-forest residuals at %d well sites...", len(y))
    resid = y - rf.predict(X)
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
    z_krige = qt.inverse_transform(np.array(z_krige_nst).reshape(-1, 1)).ravel()
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

    # Spatial support — variogram-driven confidence mask (#4), replacing the fixed 50 km
    # well-density mask. Falls back to 50 km only if no aligned domain raster is available.
    well_xy = np.column_stack([sites["x_5070"].values, sites["y_5070"].values])
    mask_2d = None
    if args.domain and Path(args.domain).exists():
        from src.evaluation.confidence_mask import (build_confidence_mask,
                                                    write_confidence_mask)
        with rasterio.open(args.domain) as dsrc:
            dom_arr = dsrc.read(1)
        if dom_arr.shape == (nrows, ncols):
            conf = build_confidence_mask(dom_arr, x_grid, y_grid, well_xy, domain_ranges)
            write_confidence_mask(conf, dem_profile, out_dir / "well_support_mask_90m.tif")
            mask_2d = ((conf > 0) & (conf != 255)).astype(np.float32)  # binary back-compat
        else:
            logger.warning("Domain raster shape %s != grid %s; using 50 km fallback mask.",
                           dom_arr.shape, (nrows, ncols))
    if mask_2d is None:
        dist, _ = cKDTree(well_xy).query(np.column_stack([x_grid, y_grid]))
        mask_2d = (dist.reshape(nrows, ncols) <= WELL_DENSITY_RADIUS_M).astype(np.float32)

    # Write outputs
    _write_tif(dtw_final_2d, dem_profile, out_dir / "baseline_dtw_m.tif")
    _write_tif(wte_final_2d, dem_profile, out_dir / "baseline_wte_m.tif")
    _write_tif(rf_std_2d, dem_profile, out_dir / "baseline_rf_std_m.tif")
    _write_tif(krige_std_2d, dem_profile, out_dir / "baseline_kriging_std_m.tif")
    _write_tif(mask_2d, dem_profile, out_dir / "well_density_mask.tif")

    logger.info("Observation-anchored random-forest baseline complete.")


if __name__ == "__main__":
    main()
