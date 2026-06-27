"""
Interpolate monthly WTE anomaly fields via ordinary kriging per HUC-2 region.

For each calendar month in the NWIS record, computes:
    anomaly_wte_m = obs_wte_m − site_median_wte_m

and then kriging-interpolates the anomaly field onto the 90 m CONUS grid.

The result is accumulated into Zarr archives:
    gwl_anomaly.zarr  — (time, y, x) anomaly from site median WTE (m)
    gwl_wte.zarr      — (time, y, x)  = baseline_wte + anomaly (m NAVD88)
    gwl_dtw.zarr      — (time, y, x)  = DEM − gwl_wte (m below surface; positive = groundwater below land)

Months with fewer than MIN_SITES_PER_MONTH observations across CONUS are written
as all-NaN slices (no interpolation from too-sparse data).

Usage:
    python -m src.models.interpolate_anomalies \\
        --monthly  data/processed/nwis_gwlevels_monthly.parquet \\
        --sites    data/processed/nwis_sites_clean.parquet \\
        --baseline-wte data/processed/baseline_wte_m.tif \\
        --dem      data/raw/dem/merit_hydro_90m_5070.tif \\
        --output-dir data/processed
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import rasterio
import zarr
from rasterio.crs import CRS
from sklearn.preprocessing import QuantileTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)

# Minimum observations across CONUS per month to attempt interpolation
MIN_SITES_PER_MONTH = 30

# NST quantiles
NST_QUANTILES = 500

# Kriging search parameters
K_NEIGHBOURS = 100
SEARCH_RADIUS_M = 300_000.0

# Zarr chunk size: one month at a time in time, full spatial extent
ZARR_CHUNK_T = 1


def _assign_huc2_approx(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Reuse HUC-2 approximate bounding-box assignment from interpolate_baseline."""
    from src.models.interpolate_baseline import _assign_huc2_approx as _assign

    return _assign(x, y)


def load_monthly_anomalies(
    monthly_parquet: Path,
    sites_parquet: Path,
) -> pd.DataFrame:
    """
    Compute per-site, per-month WTE anomaly relative to the site's long-term median.

    Parameters
    ----------
    monthly_parquet:
        ``nwis_gwlevels_monthly.parquet`` with columns site_no, year, month, wte_m.
    sites_parquet:
        ``nwis_sites_clean.parquet`` with columns site_no, median_wte_m, lat, lon,
        is_sparse_timeseries, has_long_gap.

    Returns
    -------
    DataFrame with columns:
        site_no, year, month, anomaly_wte_m, X, Y (EPSG:5070), date (Timestamp)
    """
    df_monthly = pd.read_parquet(monthly_parquet)
    df_sites = pd.read_parquet(sites_parquet)

    logger.info(f"Monthly records: {len(df_monthly):,}")
    logger.info(f"Sites: {len(df_sites):,}")

    # Keep only usable sites
    usable = df_sites[~df_sites["is_sparse_timeseries"] & ~df_sites["has_long_gap"]].copy()
    usable = usable.dropna(subset=["lat", "lon", "median_wte_m"])

    # Project to EPSG:5070
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    x5070, y5070 = transformer.transform(usable["lon"].values, usable["lat"].values)
    usable["X"] = x5070
    usable["Y"] = y5070

    # Merge monthly observations with usable sites (inner join — only usable sites kept)
    df = df_monthly.merge(
        usable[["site_no", "median_wte_m", "X", "Y"]],
        on="site_no",
        how="inner",
    )

    # Compute anomaly
    df["anomaly_wte_m"] = df["wte_m"] - df["median_wte_m"]
    df = df.dropna(subset=["anomaly_wte_m", "X", "Y"])

    # Date column for easy iterating
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month"], "day": 1})

    logger.info(f"  Anomaly records (usable sites, non-NaN): {len(df):,}")
    return df


def _fit_anomaly_variograms(df: pd.DataFrame) -> dict[str, list]:
    """
    Fit per-HUC-2 variograms on the pooled multi-month anomaly dataset.

    Uses all months combined for stability (anomalies should be stationary in
    time around zero).  Returns a dict mapping HUC-2 code → GStatSim vario list.
    """
    from src.models.interpolate_baseline import _fit_variogram

    df = df.copy()
    df["huc2"] = _assign_huc2_approx(df["X"].values, df["Y"].values)

    # NST on pooled anomaly values (per-region)
    variograms: dict[str, list] = {}
    unique_hucs = sorted(df["huc2"].unique())

    for huc in unique_hucs:
        subset = df[df["huc2"] == huc].copy()
        if len(subset) < 50:
            continue

        # Sub-sample for variogram fitting if too many points (speed)
        if len(subset) > 5000:
            subset = subset.sample(5000, random_state=42)

        nst = QuantileTransformer(
            n_quantiles=min(NST_QUANTILES, len(subset)),
            output_distribution="normal",
        )
        Nanom = nst.fit_transform(subset["anomaly_wte_m"].values.reshape(-1, 1)).ravel()
        vario = _fit_variogram(
            subset["X"].values,
            subset["Y"].values,
            Nanom,
            max_lag_m=400_000.0,
        )
        variograms[huc] = vario
        logger.info(f"  Anomaly variogram HUC-2 {huc}: range={vario[2]/1000:.0f} km, sill={vario[4]:.3f}")

    return variograms


def _krige_month(
    df_month: pd.DataFrame,
    grid_x_flat: np.ndarray,
    grid_y_flat: np.ndarray,
    variograms: dict[str, list],
    nst_pool: QuantileTransformer,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Ordinary-krige one month's anomaly field onto the CONUS grid.

    Propagates kriging variance (from ``okrige``) through the inverse NST
    to estimate
    per-cell temporal kriging uncertainty σ_anomaly(x, y, t).

    Parameters
    ----------
    df_month:
        Observations for this month: columns X, Y, anomaly_wte_m.
    grid_x_flat, grid_y_flat:
        Ravelled EPSG:5070 grid coordinates.
    variograms:
        Per-HUC-2 variogram lists.
    nst_pool:
        NST transformer fitted on pooled anomalies.

    Returns
    -------
    anomaly : np.ndarray, shape (n_cells,) — interpolated anomaly (m), NaN where not interpolated.
    krige_std : np.ndarray, shape (n_cells,) — σ from SGS realisations (m), NaN where not interpolated.
    """
    try:
        import gstatsim as gs
    except ImportError as exc:
        raise ImportError("gstatsim is required. Run `pixi install`.") from exc

    out = np.full(len(grid_x_flat), np.nan, dtype=np.float64)
    out_std = np.full(len(grid_x_flat), np.nan, dtype=np.float64)

    df_month = df_month.copy()
    df_month["Nanom"] = nst_pool.transform(df_month["anomaly_wte_m"].values.reshape(-1, 1)).ravel()
    df_month["huc2"] = _assign_huc2_approx(df_month["X"].values, df_month["Y"].values)

    grid_huc2 = _assign_huc2_approx(grid_x_flat, grid_y_flat)

    for huc in df_month["huc2"].unique():
        if huc not in variograms:
            continue
        region_wells = df_month[df_month["huc2"] == huc]
        if len(region_wells) < 3:
            continue

        cell_mask = grid_huc2 == huc
        if cell_mask.sum() == 0:
            continue

        Pred_grid = np.column_stack([grid_x_flat[cell_mask], grid_y_flat[cell_mask]])

        try:
            est_N, var_ok = gs.Interpolation.okrige(
                Pred_grid,
                region_wells[["X", "Y", "Nanom"]],
                "X", "Y", "Nanom",
                num_points=min(K_NEIGHBOURS, len(region_wells)),
                vario=variograms[huc],
                radius=SEARCH_RADIUS_M,
            )
        except Exception as exc:
            logger.debug(f"  HUC-2 {huc} okrige failed: {exc}")
            continue

        # Inverse NST for the mean estimate
        anom_vals = nst_pool.inverse_transform(est_N.reshape(-1, 1)).ravel()
        out[cell_mask] = anom_vals

        # Propagate kriging variance to original units via ±1σ in NST space.
        # okrige returns var_ok = kriging variance (NST space); ±sqrt(var) bounds
        # are inversely transformed to give the asymmetric 1σ interval.
        std_N = np.sqrt(np.maximum(var_ok, 0.0))
        p84 = nst_pool.inverse_transform((est_N + std_N).reshape(-1, 1)).ravel()
        p16 = nst_pool.inverse_transform((est_N - std_N).reshape(-1, 1)).ravel()
        out_std[cell_mask] = np.abs(p84 - p16) / 2.0

    return out, out_std


def save_zarr(
    array_3d: np.ndarray,
    dates: list,
    transform: rasterio.transform.Affine,
    grid_width: int,
    grid_height: int,
    path: Path,
    long_name: str,
    units: str,
) -> None:
    """Write a (time, y, x) float32 array to a Zarr store."""
    import xarray as xr

    times = np.array(dates, dtype="datetime64[ns]")
    x_left = transform.c + transform.a * 0.5
    y_top = transform.f + transform.e * 0.5
    x_coords = x_left + np.arange(grid_width) * transform.a
    y_coords = y_top + np.arange(grid_height) * transform.e

    ds = xr.Dataset(
        {
            "data": xr.DataArray(
                array_3d.astype(np.float32),
                dims=["time", "y", "x"],
                coords={"time": times, "y": y_coords, "x": x_coords},
                attrs={"long_name": long_name, "units": units, "crs": "EPSG:5070"},
            )
        }
    )
    # Chunk: 1 month × full spatial extent
    ds = ds.chunk({"time": ZARR_CHUNK_T, "y": grid_height, "x": grid_width})
    ds.to_zarr(path, mode="w")
    logger.info(f"  Saved: {path}")


def main() -> None:  # noqa: C901
    parser = argparse.ArgumentParser(description="Krige monthly WTE anomaly fields")
    parser.add_argument("--monthly", type=Path, default=Path("data/processed/nwis_gwlevels_monthly.parquet"))
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--baseline-wte", type=Path, default=Path("data/processed/baseline_wte_m.tif"))
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/merit_hydro_90m_5070.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    for p in [args.monthly, args.sites, args.baseline_wte, args.dem]:
        if not p.exists():
            raise FileNotFoundError(f"Required input not found: {p}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load grid ----
    from src.features.compute_grid import load_grid_spec, read_dem_array

    grid = load_grid_spec(args.dem)
    dem_arr = read_dem_array(args.dem, grid)
    grid_xx, grid_yy = np.meshgrid(grid.x_coords, grid.y_coords)
    grid_x_flat = grid_xx.ravel()
    grid_y_flat = grid_yy.ravel()
    logger.info(f"Grid: {grid.width} × {grid.height} px")

    # ---- Load baseline WTE ----
    with rasterio.open(args.baseline_wte) as src:
        baseline_wte = src.read(1).astype(np.float32)
        nodata_val = src.nodata if src.nodata is not None else -9999.0
    baseline_wte[baseline_wte == nodata_val] = np.nan
    logger.info(f"Baseline WTE loaded: {args.baseline_wte.name}")

    # ---- Load monthly anomalies ----
    df_anom = load_monthly_anomalies(args.monthly, args.sites)

    # ---- Pool-level NST for anomalies ----
    all_anomalies = df_anom["anomaly_wte_m"].values
    nst_pool = QuantileTransformer(
        n_quantiles=min(NST_QUANTILES, len(all_anomalies)),
        output_distribution="normal",
    )
    nst_pool.fit(all_anomalies.reshape(-1, 1))
    logger.info("Pooled NST fitted on anomaly values")

    # ---- Fit per-HUC-2 anomaly variograms (pooled across months) ----
    logger.info("Fitting anomaly variograms …")
    anomaly_variograms = _fit_anomaly_variograms(df_anom)

    # ---- Iterate over months ----
    sorted_dates = sorted(df_anom["date"].unique())
    n_times = len(sorted_dates)
    logger.info(f"Processing {n_times} months …")

    anomaly_cube = np.full((n_times, grid.height, grid.width), np.nan, dtype=np.float32)
    krige_std_cube = np.full((n_times, grid.height, grid.width), np.nan, dtype=np.float32)
    skipped_months: list[str] = []
    site_counts: dict[str, int] = {}

    for t_idx, dt in enumerate(sorted_dates):
        df_t = df_anom[df_anom["date"] == dt]
        n_sites = len(df_t)
        date_str = str(dt)[:7]

        if n_sites < MIN_SITES_PER_MONTH:
            logger.info(f"  {date_str}: {n_sites} sites — skipping (< {MIN_SITES_PER_MONTH})")
            skipped_months.append(date_str)
            site_counts[date_str] = n_sites
            continue

        site_counts[date_str] = n_sites

        anomaly_flat, krige_std_flat = _krige_month(
            df_t,
            grid_x_flat,
            grid_y_flat,
            anomaly_variograms,
            nst_pool,
        )
        anomaly_cube[t_idx] = anomaly_flat.reshape(grid.height, grid.width).astype(np.float32)
        krige_std_cube[t_idx] = krige_std_flat.reshape(grid.height, grid.width).astype(np.float32)

        if (t_idx + 1) % 12 == 0 or t_idx == n_times - 1:
            logger.info(f"  Progress: {t_idx + 1}/{n_times} months  (current: {date_str}, {n_sites} sites)")

    # ---- Build WTE and DTW cubes ----
    wte_cube = baseline_wte[np.newaxis, :, :] + anomaly_cube  # (time, y, x)
    dtw_cube = dem_arr[np.newaxis, :, :] - wte_cube           # positive = water below surface

    # ---- Save Zarr ----
    logger.info("Saving Zarr archives …")
    save_zarr(
        anomaly_cube, sorted_dates, grid.transform, grid.width, grid.height,
        args.output_dir / "gwl_anomaly.zarr",
        long_name="Monthly WTE anomaly from site median",
        units="m",
    )
    save_zarr(
        wte_cube, sorted_dates, grid.transform, grid.width, grid.height,
        args.output_dir / "gwl_wte.zarr",
        long_name="Water table elevation (NAVD88)",
        units="m",
    )
    save_zarr(
        dtw_cube, sorted_dates, grid.transform, grid.width, grid.height,
        args.output_dir / "gwl_dtw.zarr",
        long_name="Depth to groundwater (positive = below surface)",
        units="m",
    )
    save_zarr(
        krige_std_cube, sorted_dates, grid.transform, grid.width, grid.height,
        args.output_dir / "gwl_kriging_std.zarr",
        long_name="Temporal kriging uncertainty \u03c3_anomaly (1 std, monthly SGS spread)",
        units="m",
    )

    # ---- Metadata ----
    metadata = {
        "date_range": [str(sorted_dates[0])[:7], str(sorted_dates[-1])[:7]],
        "n_months_total": n_times,
        "n_months_skipped": len(skipped_months),
        "skipped_months": skipped_months,
        "site_counts_per_month": site_counts,
        "min_sites_per_month": MIN_SITES_PER_MONTH,
        "anomaly_variograms_huc2": anomaly_variograms,
    }
    meta_path = args.output_dir / "gwl_metadata.json"
    with open(meta_path, "w") as fh:
        json.dump(metadata, fh, indent=2)
    logger.info(f"Metadata: {meta_path}")
    logger.info(
        f"Done. {n_times - len(skipped_months)}/{n_times} months interpolated; "
        f"{len(skipped_months)} skipped."
    )


if __name__ == "__main__":
    main()
