"""Stage 2: Per-site OLS climate response functions (β-maps).

For each well site, fits:
  ΔDTW(t) = β₀ + β₁·SPI3(t) + β₂·ΔSWE(t−lag*) + β₃·PDO(t) + ε

where lag* is optimized per terrain zone (valley / transition / upland) by AIC.

β coefficients are then kriged to the 1 km grid, and monthly GWL anomalies
are reconstructed as a matrix product:
  anomaly_hat(x,y,t) = β₁(x,y)·SPI3(x,y,t) + β₂(x,y)·ΔSWE(x,y,t−lag) + β₃(x,y)·PDO(t)

AR term (β₄) is set to 0 until the Stage IV intercomparison delivers a ranked
precipitation product.

Outputs (data/processed/):
  beta_spi3_1km.tif                — β₁ map (m / unit SPI)
  beta_swe_1km.tif                 — β₂ map (m / 100 mm SWE)
  beta_pdo_1km.tif                 — β₃ map (m / unit PDO)
  beta_r2_1km.tif                  — per-site OLS R²
  optimal_swe_lag_zone.json        — best SWE lag per terrain zone
  climate_response_sites.parquet   — per-site β + diagnostics
  gwl_climate_response.zarr        — (time, y, x) Stage 2 anomaly field
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

logger = logging.getLogger(__name__)

NODATA = -9999.0

# Terrain zone HAND thresholds (metres)
HAND_VALLEY_MAX = 5.0     # HAND < 5 m → valley
HAND_UPLAND_MIN = 20.0    # HAND > 20 m → upland; 5–20 m → transition

# SWE lag search range (months)
MAX_LAG = 6
MIN_OBS_TO_FIT = 36  # minimum months of obs to fit β

# Kriging parameters for β maps (spatial smoothing)
_VARIOGRAM_MODEL = "spherical"
_K_NEIGHBOURS = 80
_SEARCH_RADIUS_M = 350_000


def _terrain_zone(hand_val: float) -> str:
    if np.isnan(hand_val) or hand_val < HAND_VALLEY_MAX:
        return "valley"
    if hand_val < HAND_UPLAND_MIN:
        return "transition"
    return "upland"


def _sample_raster_at_points(
    raster_path: Path, x_5070: np.ndarray, y_5070: np.ndarray
) -> np.ndarray:
    """Sample raster at (x, y) EPSG:5070 coordinates."""
    coords = list(zip(x_5070.tolist(), y_5070.tolist()))
    with rasterio.open(raster_path) as src:
        values = np.array([v[0] for v in src.sample(coords)], dtype=np.float32)
    values[values == NODATA] = np.nan
    return values


def _load_climate_at_site(
    site_x: float,
    site_y: float,
    spi3_ds: xr.Dataset,
    swe_ds: xr.Dataset,
    pdo_df: pd.DataFrame,
    obs_times: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build a time-aligned climate DataFrame for one site."""
    spi3 = spi3_ds["spi3"].sel(
        x=site_x, y=site_y, method="nearest"
    ).to_series().rename("spi3")
    swe_var = list(swe_ds.data_vars)[0]
    swe = swe_ds[swe_var].sel(
        lat=site_y, lon=site_x, method="nearest"
    ).to_series().rename("swe_mm") if "lat" in swe_ds.coords else (
        swe_ds[swe_var].sel(y=site_y, x=site_x, method="nearest").to_series().rename("swe_mm")
    )
    pdo = pdo_df.set_index("time")["pdo"]
    df = pd.DataFrame(index=obs_times)
    df = df.join(spi3, how="left")
    df = df.join(swe, how="left")
    df = df.join(pdo, how="left")
    df["swe_anom"] = df["swe_mm"] - df["swe_mm"].mean()
    return df


def _fit_site_beta(
    obs_anomaly: pd.Series,
    climate: pd.DataFrame,
    swe_lag: int,
) -> dict:
    """Fit per-site OLS for a given SWE lag; return β dict."""
    climate = climate.copy()
    climate["swe_lag"] = climate["swe_anom"].shift(swe_lag)
    merged = pd.concat([obs_anomaly.rename("target"), climate], axis=1).dropna()
    if len(merged) < MIN_OBS_TO_FIT:
        return {}

    X = merged[["spi3", "swe_lag", "pdo"]].values
    y = merged["target"].values
    reg = LinearRegression().fit(X, y)
    y_pred = reg.predict(X)
    r2 = float(r2_score(y, y_pred))
    resid_std = float(np.std(y - y_pred))
    # AIC (for lag selection): n·ln(RSS/n) + 2k
    n = len(y)
    rss = float(np.sum((y - y_pred) ** 2))
    k = 4  # intercept + 3 predictors
    aic = n * np.log(rss / n) + 2 * k if rss > 0 else np.inf

    return {
        "beta0": float(reg.intercept_),
        "beta_spi3": float(reg.coef_[0]),
        "beta_swe": float(reg.coef_[1]),
        "beta_pdo": float(reg.coef_[2]),
        "r2": r2,
        "resid_std": resid_std,
        "aic": aic,
        "n_obs": n,
        "swe_lag": swe_lag,
    }


def _krige_beta_map(
    site_x: np.ndarray,
    site_y: np.ndarray,
    site_beta: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Kriging of a β-coefficient to the 1 km grid.

    Returns (kriged_values, kriging_std).
    """
    from pykrige.ok import OrdinaryKriging
    from sklearn.preprocessing import QuantileTransformer

    valid = ~np.isnan(site_beta)
    if valid.sum() < 10:
        logger.warning("Too few valid β values (%d) for kriging — returning NaN.", valid.sum())
        return np.full(len(grid_x), np.nan), np.full(len(grid_x), np.nan)

    beta_v = site_beta[valid]
    qt = QuantileTransformer(
        n_quantiles=min(500, valid.sum()), output_distribution="normal", random_state=0
    )
    beta_nst = qt.fit_transform(beta_v.reshape(-1, 1)).ravel()

    ok = OrdinaryKriging(
        site_x[valid], site_y[valid], beta_nst,
        variogram_model=_VARIOGRAM_MODEL,
        nlags=15,
        enable_plotting=False,
        verbose=False,
    )
    z_nst, ss = ok.execute(
        "points", grid_x, grid_y, backend="loop", n_closest_points=_K_NEIGHBOURS
    )
    z = qt.inverse_transform(np.array(z_nst).reshape(-1, 1)).ravel()
    return z, np.sqrt(np.maximum(ss, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit per-site OLS climate response β-maps.")
    parser.add_argument("--monthly", type=Path, default=Path("data/processed/nwis_gwlevels_monthly.parquet"))
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--spi3", type=Path, default=Path("data/processed/spi3_monthly_pnw.zarr"))
    parser.add_argument("--swe", type=Path, default=Path("data/raw/climate/snodas_swe_monthly_pnw.zarr"))
    parser.add_argument("--pdo", type=Path, default=Path("data/raw/climate/pdo_monthly.csv"))
    parser.add_argument("--hand", type=Path, default=Path("data/processed/terrain_hand_1km.tif"))
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/3dep_1km_5070.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--min-months", type=int, default=MIN_OBS_TO_FIT)
    parser.add_argument("--max-lag", type=int, default=MAX_LAG)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    logger.info("Loading monthly observations...")
    monthly = pd.read_parquet(args.monthly)
    monthly["time"] = pd.to_datetime(monthly["time"])

    sites = pd.read_parquet(args.sites)
    pdo_df = pd.read_csv(args.pdo, parse_dates=["time"])

    logger.info("Loading SPI-3 and SWE Zarr stores...")
    spi3_ds = xr.open_zarr(args.spi3, consolidated=True)
    swe_ds = xr.open_zarr(args.swe, consolidated=True)

    logger.info("Sampling HAND at site locations...")
    site_hand = _sample_raster_at_points(
        args.hand, sites["x_5070"].values, sites["y_5070"].values
    )
    sites = sites.copy()
    sites["hand_m"] = site_hand
    sites["terrain_zone"] = sites["hand_m"].apply(_terrain_zone)

    # Determine optimal SWE lag per terrain zone
    logger.info("Optimising SWE lag per terrain zone (trying lags 0–%d)...", args.max_lag)
    zone_lag_aic: dict[str, dict[int, list[float]]] = {
        z: {lag: [] for lag in range(args.max_lag + 1)}
        for z in ("valley", "transition", "upland")
    }

    site_results = []
    n_sites = len(sites)
    for i, (_, site) in enumerate(sites.iterrows()):
        if i % 200 == 0:
            logger.info("  Processing site %d/%d", i, n_sites)
        site_id = site.get("site_no") or site.get("site_id") or str(i)
        obs = monthly[monthly["site_no"] == site_id][["time", "wte_anomaly_m"]].copy()
        if obs.empty or obs["wte_anomaly_m"].notna().sum() < args.min_months:
            continue
        obs = obs.set_index("time")["wte_anomaly_m"].sort_index()
        obs.index = pd.to_datetime(obs.index).to_period("M").to_timestamp()

        try:
            climate = _load_climate_at_site(
                float(site["x_5070"]), float(site["y_5070"]),
                spi3_ds, swe_ds, pdo_df, obs.index,
            )
        except Exception as exc:
            logger.debug("Climate load failed for site %s: %s", site_id, exc)
            continue

        zone = str(site["terrain_zone"])
        best_lag, best_result = 0, {}
        best_aic = np.inf

        for lag in range(args.max_lag + 1):
            result = _fit_site_beta(obs, climate, lag)
            if result:
                zone_lag_aic[zone][lag].append(result["aic"])
                if result["aic"] < best_aic:
                    best_aic = result["aic"]
                    best_lag = lag
                    best_result = result

        if best_result:
            best_result["site_no"] = site_id
            best_result["x_5070"] = float(site["x_5070"])
            best_result["y_5070"] = float(site["y_5070"])
            best_result["terrain_zone"] = zone
            site_results.append(best_result)

    if not site_results:
        raise RuntimeError("No sites had sufficient data for β fitting.")

    beta_df = pd.DataFrame(site_results)
    beta_df.to_parquet(out_dir / "climate_response_sites.parquet", index=False)
    logger.info("Fitted β for %d sites.", len(beta_df))

    # Optimal lag per zone (minimum median AIC)
    optimal_lag = {}
    for zone, lag_aics in zone_lag_aic.items():
        best_z_lag = min(
            (l for l in lag_aics if lag_aics[l]),
            key=lambda l: np.median(lag_aics[l]) if lag_aics[l] else np.inf,
            default=2,
        )
        optimal_lag[zone] = int(best_z_lag)
        logger.info("  %s zone: optimal SWE lag = %d months", zone, best_z_lag)

    with open(out_dir / "optimal_swe_lag_zone.json", "w") as fh:
        json.dump(optimal_lag, fh, indent=2)

    # Krige β maps to 1 km grid
    logger.info("Kriging β maps to 1 km grid...")
    with rasterio.open(args.dem) as dem_src:
        dem_profile = dem_src.profile.copy()
        nrows, ncols = dem_src.height, dem_src.width

    import rasterio.transform as rt
    rows_g, cols_g = np.meshgrid(np.arange(nrows), np.arange(ncols), indexing="ij")
    xs_g, ys_g = rt.xy(dem_profile["transform"], rows_g.ravel(), cols_g.ravel())
    xs_g, ys_g = np.array(xs_g), np.array(ys_g)

    sx = beta_df["x_5070"].values
    sy = beta_df["y_5070"].values

    beta_keys = {
        "beta_spi3": "beta_spi3_1km.tif",
        "beta_swe": "beta_swe_1km.tif",
        "beta_pdo": "beta_pdo_1km.tif",
        "r2": "beta_r2_1km.tif",
    }
    kriged_betas = {}
    for col, fname in beta_keys.items():
        logger.info("  Kriging %s...", col)
        z, _ = _krige_beta_map(sx, sy, beta_df[col].values, xs_g, ys_g)
        kriged_betas[col] = z
        arr_2d = np.where(np.isnan(z), NODATA, z).astype(np.float32).reshape(nrows, ncols)
        p = dem_profile.copy()
        p.update(dtype="float32", count=1, nodata=NODATA, compress="LZW",
                 tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(out_dir / fname, "w", **p) as dst:
            dst.write(arr_2d, 1)
        logger.info("  Written: %s", fname)

    # Reconstruct monthly anomaly field: β₁·SPI3 + β₂·SWE(t-lag) + β₃·PDO
    logger.info("Reconstructing monthly GWL anomaly from β maps...")
    beta_spi3_grid = kriged_betas["beta_spi3"].reshape(nrows, ncols)
    beta_swe_grid = kriged_betas["beta_swe"].reshape(nrows, ncols)
    beta_pdo_grid = kriged_betas["beta_pdo"].reshape(nrows, ncols)

    spi3_times = pd.DatetimeIndex(spi3_ds["time"].values)
    spi3_arr = spi3_ds["spi3"].values  # (time, ny_spi3, nx_spi3)
    pdo_series = pdo_df.set_index("time")["pdo"].sort_index()

    # For simplicity, use the valley-zone lag as the global lag
    # (a more rigorous implementation would use per-cell lag from terrain_zone raster)
    global_swe_lag = optimal_lag.get("valley", 2)
    swe_var = list(swe_ds.data_vars)[0]
    swe_series_grid: dict = {}  # cached

    # Build time-indexed anomaly cube on the 1 km grid
    common_times = [
        t for t in spi3_times
        if t in pdo_series.index
    ]
    n_time = len(common_times)
    anomaly_cube = np.zeros((n_time, nrows, ncols), dtype=np.float32)

    from scipy.ndimage import zoom

    for ti, t in enumerate(common_times):
        # SPI-3 at time t on spi3 native grid → resample to 1 km
        t_idx = int(np.where(spi3_times == t)[0][0])
        spi3_slice = spi3_arr[t_idx]  # (ny_spi3, nx_spi3)
        if spi3_slice.shape != (nrows, ncols):
            spi3_on_grid = zoom(
                spi3_slice, (nrows / spi3_slice.shape[0], ncols / spi3_slice.shape[1]), order=1
            )
        else:
            spi3_on_grid = spi3_slice

        pdo_val = float(pdo_series.get(t, np.nan))
        if np.isnan(pdo_val):
            continue

        # SWE anomaly at lagged time
        t_lag = t - pd.DateOffset(months=global_swe_lag)
        try:
            swe_slice = swe_ds[swe_var].sel(
                **{"time": t_lag}, method="nearest"
            ).values.astype(np.float32)
            if swe_slice.shape != (nrows, ncols):
                swe_slice = zoom(
                    swe_slice, (nrows / swe_slice.shape[0], ncols / swe_slice.shape[1]), order=1
                )
        except Exception:
            swe_slice = np.zeros((nrows, ncols), dtype=np.float32)

        anomaly_cube[ti] = (
            beta_spi3_grid * spi3_on_grid
            + beta_swe_grid * swe_slice / 100.0  # β₂ is per 100 mm
            + beta_pdo_grid * pdo_val
        )

    # Write anomaly Zarr
    out_zarr = out_dir / "gwl_climate_response.zarr"
    logger.info("Writing climate response anomaly to %s ...", out_zarr)

    # Build x/y coordinates from DEM profile
    transform = dem_profile["transform"]
    x_coords = np.array([transform.c + (j + 0.5) * transform.a for j in range(ncols)])
    y_coords = np.array([transform.f + (i + 0.5) * transform.e for i in range(nrows)])

    anomaly_da = xr.DataArray(
        anomaly_cube,
        dims=["time", "y", "x"],
        coords={"time": common_times, "y": y_coords, "x": x_coords},
        attrs={
            "long_name": "Climate-response-reconstructed GWL anomaly",
            "units": "m",
            "comment": "β₁·SPI3 + β₂·ΔSWE(t-lag) + β₃·PDO; AR term = 0 (placeholder)",
        },
    )
    xr.Dataset({"wte_anomaly_m": anomaly_da}).to_zarr(out_zarr, mode="w", consolidated=True)
    logger.info("Climate response fitting complete.")


if __name__ == "__main__":
    main()
