"""Stage 3: Krige observation residuals and assemble final GWL product.

Residuals = observed monthly anomaly − climate_response anomaly.
Ordinary kriging of residuals (per HUC-2, per calendar month) removes the
systematic bias that the climate response functions leave unexplained at well
locations.

Final assembly:
  DTW(x,y,t) = baseline_dtw(x,y) + climate_response_anom(x,y,t) + kriged_residual(x,y,t)
  WTE(x,y,t) = DEM(x,y) − DTW(x,y,t)

Outputs (data/processed/):
  gwl_residual.zarr     — (time, y, x) kriged residuals
  gwl_dtw.zarr          — (time, y, x) final depth to groundwater (m)
  gwl_wte.zarr          — (time, y, x) final water table elevation (m NAVD88)
  gwl_kriging_std.zarr  — (time, y, x) kriging σ on residuals
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from pykrige.ok import OrdinaryKriging
from sklearn.preprocessing import QuantileTransformer

logger = logging.getLogger(__name__)

NODATA = -9999.0
MIN_SITES_PER_MONTH = 30
K_NEIGHBOURS = 100
SEARCH_RADIUS_M = 300_000
NST_QUANTILES = 500
ZARR_CHUNK_T = 12  # months per chunk

# HUC-2 approximate bounding boxes in EPSG:5070 (x_min, y_min, x_max, y_max)
# PNW relevant regions (others will fall through to global kriging)
HUC2_APPROX_BOXES = {
    "17": (-2300000, 2200000, -1400000, 3300000),  # Pacific Northwest
    "18": (-2400000, 1700000, -1700000, 2700000),  # California
    "16": (-1900000, 2100000, -1200000, 3000000),  # Great Basin
}


def _load_monthly_anomalies(
    monthly_parquet: Path, sites: pd.DataFrame
) -> pd.DataFrame:
    """Load monthly WTE anomalies for all PNW sites."""
    monthly = pd.read_parquet(monthly_parquet)
    monthly["time"] = pd.to_datetime(monthly["time"])
    # Join coordinates
    monthly = monthly.merge(
        sites[["site_no", "x_5070", "y_5070"]],
        on="site_no", how="inner",
    )
    return monthly


def _krige_residuals_month(
    resid_x: np.ndarray,
    resid_y: np.ndarray,
    resid_z: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Krige one month of residuals; return (values, kriging_std)."""
    valid = ~np.isnan(resid_z)
    n_valid = valid.sum()

    if n_valid < MIN_SITES_PER_MONTH:
        return np.full(len(grid_x), np.nan), np.full(len(grid_x), np.nan)

    qt = QuantileTransformer(
        n_quantiles=min(NST_QUANTILES, n_valid),
        output_distribution="normal",
        random_state=0,
    )
    z_nst = qt.fit_transform(resid_z[valid].reshape(-1, 1)).ravel()

    ok = OrdinaryKriging(
        resid_x[valid], resid_y[valid], z_nst,
        variogram_model="exponential",
        nlags=15,
        enable_plotting=False,
        verbose=False,
    )
    z_krige_nst, ss = ok.execute(
        "points", grid_x, grid_y,
        backend="loop",
        n_closest_points=K_NEIGHBOURS,
    )
    z_krige = qt.inverse_transform(
        np.array(z_krige_nst).reshape(-1, 1)
    ).ravel()
    return z_krige.astype(np.float32), np.sqrt(np.maximum(ss, 0)).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 3: krige observation residuals and assemble final GWL."
    )
    parser.add_argument("--monthly", type=Path, default=Path("data/processed/nwis_gwlevels_monthly.parquet"))
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--climate-response", type=Path, default=Path("data/processed/gwl_climate_response.zarr"))
    parser.add_argument("--baseline-dtw", type=Path, default=Path("data/processed/baseline_dtw_m.tif"))
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/3dep_1km_5070.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load climate response anomaly Zarr
    logger.info("Loading climate response anomaly from %s", args.climate_response)
    cr_ds = xr.open_zarr(args.climate_response, consolidated=True)
    cr_anom = cr_ds["wte_anomaly_m"]  # (time, y, x)
    grid_times = pd.DatetimeIndex(cr_anom["time"].values)
    x_coords = cr_anom["x"].values
    y_coords = cr_anom["y"].values
    nrows = len(y_coords)
    ncols = len(x_coords)

    # Build flat grid coordinates
    xx, yy = np.meshgrid(x_coords, y_coords)
    grid_x_flat = xx.ravel()
    grid_y_flat = yy.ravel()

    # Load baseline DTW
    logger.info("Loading baseline DTW from %s", args.baseline_dtw)
    with rasterio.open(args.baseline_dtw) as src:
        baseline_dtw = src.read(1).astype(np.float32)
        baseline_dtw[baseline_dtw == src.nodata] = np.nan
        dem_profile = src.profile.copy()

    # Load DEM for WTE computation
    logger.info("Loading DEM from %s", args.dem)
    with rasterio.open(args.dem) as src:
        dem_arr = src.read(1).astype(np.float32)
        dem_arr[dem_arr == src.nodata] = np.nan

    # Load monthly observations
    logger.info("Loading monthly observations...")
    sites = pd.read_parquet(args.sites)
    monthly = _load_monthly_anomalies(args.monthly, sites)

    # Loop over time steps: compute residual = obs_anomaly − cr_anom(site, t)
    residual_cube = np.full((len(grid_times), nrows, ncols), np.nan, dtype=np.float32)
    krige_std_cube = np.full_like(residual_cube, np.nan)

    logger.info("Kriging residuals for %d months...", len(grid_times))
    for ti, t in enumerate(grid_times):
        if ti % 12 == 0:
            logger.info("  %s (month %d/%d)", t.strftime("%Y-%m"), ti, len(grid_times))

        # Observed anomalies for this month
        month_obs = monthly[monthly["time"] == t][["x_5070", "y_5070", "wte_anomaly_m"]].dropna()
        if len(month_obs) < MIN_SITES_PER_MONTH:
            continue

        # Climate response prediction at well sites
        cr_at_sites = cr_anom.sel(time=t, method="nearest").sel(
            x=xr.DataArray(month_obs["x_5070"].values, dims="pts"),
            y=xr.DataArray(month_obs["y_5070"].values, dims="pts"),
            method="nearest",
        ).values

        resid = month_obs["wte_anomaly_m"].values - cr_at_sites

        z, std = _krige_residuals_month(
            month_obs["x_5070"].values,
            month_obs["y_5070"].values,
            resid,
            grid_x_flat,
            grid_y_flat,
        )
        residual_cube[ti] = z.reshape(nrows, ncols)
        krige_std_cube[ti] = std.reshape(nrows, ncols)

    # Write residual Zarr
    def _write_zarr(cube: np.ndarray, name: str, long_name: str, out_path: Path) -> None:
        da = xr.DataArray(
            cube, dims=["time", "y", "x"],
            coords={"time": grid_times, "y": y_coords, "x": x_coords},
            attrs={"long_name": long_name, "units": "m"},
        )
        xr.Dataset({name: da}).to_zarr(
            out_path, mode="w", consolidated=True,
            encoding={name: {"chunks": [ZARR_CHUNK_T, nrows, ncols]}}
        )
        logger.info("Written: %s", out_path)

    _write_zarr(residual_cube, "wte_residual_m", "Kriged observation residuals (m)", out_dir / "gwl_residual.zarr")
    _write_zarr(krige_std_cube, "kriging_std_m", "Kriging σ on residuals (m)", out_dir / "gwl_kriging_std.zarr")

    # Final assembly
    logger.info("Assembling final GWL product...")
    cr_cube = cr_anom.values  # (time, y, x)
    dtw_final = (
        baseline_dtw[np.newaxis, :, :]     # broadcast over time
        + cr_cube
        + residual_cube
    )
    wte_final = dem_arr[np.newaxis, :, :] - dtw_final

    _write_zarr(dtw_final.astype(np.float32), "dtw_m", "Depth to groundwater (m, positive = below surface)", out_dir / "gwl_dtw.zarr")
    _write_zarr(wte_final.astype(np.float32), "wte_m", "Water table elevation (m NAVD88)", out_dir / "gwl_wte.zarr")

    logger.info("Stage 3 complete. Outputs in %s", out_dir)


if __name__ == "__main__":
    main()
