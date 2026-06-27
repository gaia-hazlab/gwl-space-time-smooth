"""
Krige monthly WTE anomaly fields for a regional pilot over a bbox grid.

Does NOT require the DEM or full CONUS baseline TIF.  Uses
``bbox_grid_90m.nc`` as the output grid and each site's long-term median
WTE as the spatial reference from which anomalies are computed.

Model
-----
    WTE_obs(site, t)  = WTE_median(site) + anomaly(site, t)
    anomaly(x, y, t)  = Ordinary-kriging of {anomaly(site, t)} on bbox grid

Output (in --output-dir):
    pilot_gwl_anomaly.zarr  — (time, y, x)  anomaly from median WTE (m)
    pilot_gwl_wte.zarr      — (time, y, x)  estimated absolute WTE (m NAVD88)
                              populated only when --hydrogen-wtd is supplied;
                              = HydroGEN_WTE_prior + anomaly

Usage::

    python -m src.models.pilot_temporal \\
        --monthly  data/processed/nwis_gwlevels_monthly.parquet \\
        --sites    data/processed/nwis_sites_clean.parquet \\
        --grid     data/processed/bbox_grid_90m.nc \\
        --states   WA OR \\
        --output-dir data/processed

    # optionally limit to the last N months (fast smoke-test):
    python -m src.models.pilot_temporal ... --n-months 24
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import rasterio
import xarray as xr
from sklearn.preprocessing import QuantileTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Kriging hyper-parameters ──────────────────────────────────────────────
MIN_SITES_PER_MONTH: int = 10       # skip month if fewer observations
K_NEIGHBOURS: int = 80              # conditioning points per kriging cell
SEARCH_RADIUS_M: float = 350_000.0  # search radius (m)
NST_QUANTILES: int = 500            # QuantileTransformer quantiles
NLAG_VARIOGRAM: int = 25            # semi-variogram bins
MAX_VARIOGRAM_PTS: int = 5_000      # sub-sample for variogram fit

# ── Zarr chunking ─────────────────────────────────────────────────────────
ZARR_CHUNK_T: int = 12  # months per chunk


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_anomalies(
    monthly_parquet: Path,
    sites_parquet: Path,
    states: list[str],
) -> pd.DataFrame:
    """
    Load monthly NWIS data, filter to specified states, and compute per-site
    WTE anomalies relative to each site's long-term median WTE.

    Parameters
    ----------
    monthly_parquet:
        ``nwis_gwlevels_monthly.parquet`` — columns site_no, year, month,
        wte_m, state, …
    sites_parquet:
        ``nwis_sites_clean.parquet`` — columns site_no, lat, lon,
        median_wte_m, is_sparse_timeseries, has_long_gap, …
    states:
        Two-letter USPS state codes to retain.

    Returns
    -------
    DataFrame with columns:
        site_no, date (Timestamp), year, month,
        anomaly_wte_m, X (EPSG:5070), Y (EPSG:5070), wte_m
    """
    df_monthly = pd.read_parquet(monthly_parquet)
    df_sites = pd.read_parquet(sites_parquet)

    # Filter to requested states (monthly parquet carries state col)
    df_monthly = df_monthly[df_monthly["state"].isin(states)].copy()
    logger.info(f"Monthly records in {states}: {len(df_monthly):,}")

    # Only usable (non-sparse, non-gappy) sites
    usable = df_sites[
        ~df_sites["is_sparse_timeseries"] & ~df_sites["has_long_gap"]
    ].copy()
    usable = usable.dropna(subset=["lat", "lon", "median_wte_m"])
    logger.info(f"Usable sites: {len(usable):,}")

    # Project lat/lon → EPSG:5070
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", "EPSG:5070", always_xy=True
    )
    x5070, y5070 = transformer.transform(usable["lon"].values, usable["lat"].values)
    usable = usable.assign(X=x5070, Y=y5070)

    # Merge: inner join keeps only usable sites with monthly data
    df = df_monthly.merge(
        usable[["site_no", "median_wte_m", "X", "Y"]],
        on="site_no",
        how="inner",
    )
    df["anomaly_wte_m"] = df["wte_m"] - df["median_wte_m"]
    df = df.dropna(subset=["anomaly_wte_m", "X", "Y"])
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month"], "day": 1})

    logger.info(f"Anomaly records (post-join, non-NaN): {len(df):,}")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Variogram fitting
# ---------------------------------------------------------------------------

def fit_variogram(
    x: np.ndarray,
    y: np.ndarray,
    values: np.ndarray,
    max_lag_m: float = 400_000.0,
) -> list:
    """
    Fit an exponential variogram on NST-transformed values using scikit-gstat.

    Returns a GStatSim variogram list:
        [azimuth, nugget, major_range, minor_range, sill, vtype]
    """
    try:
        import skgstat as skg
    except ImportError as exc:
        raise ImportError("scikit-gstat required. Run `pixi install`.") from exc

    coords = np.column_stack([x, y])
    V = skg.Variogram(
        coords, values,
        model="exponential",
        n_lags=NLAG_VARIOGRAM,
        maxlag=max_lag_m,
    )
    desc = V.describe()
    nugget = max(float(desc.get("nugget", 0.0)), 0.0)
    sill = max(float(desc.get("sill", 1.0)), 1e-6)
    vrange = max(float(desc.get("effective_range", max_lag_m / 3)), 1_000.0)
    vario = [0.0, nugget, vrange, vrange, sill, "Exponential"]
    logger.info(
        f"  Variogram — range={vrange/1000:.0f} km  sill={sill:.3f}  nugget={nugget:.3f}"
    )
    return vario


# ---------------------------------------------------------------------------
# Single-month kriging
# ---------------------------------------------------------------------------

def krige_month(
    df_month: pd.DataFrame,
    grid_x_flat: np.ndarray,
    grid_y_flat: np.ndarray,
    vario: list,
    nst_pool: QuantileTransformer,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Ordinary-krige one month's anomaly values onto the pilot grid.

    Parameters
    ----------
    df_month:
        Observations for this month: must have columns X, Y, anomaly_wte_m.
    grid_x_flat, grid_y_flat:
        Flattened EPSG:5070 grid coordinates.
    vario:
        GStatSim variogram list from :func:`fit_variogram`.
    nst_pool:
        QuantileTransformer fitted on pooled anomalies (all months).

    Returns
    -------
    anomaly : shape (n_cells,) — interpolated anomaly (m), NaN outside reach.
    krige_std : shape (n_cells,) — 1-σ uncertainty propagated through NST (m).
    """
    try:
        import gstatsim as gs
    except ImportError as exc:
        raise ImportError("gstatsim required. Run `pixi install`.") from exc

    from scipy.spatial import cKDTree

    out = np.full(len(grid_x_flat), np.nan, dtype=np.float64)
    out_std = np.full(len(grid_x_flat), np.nan, dtype=np.float64)

    if len(df_month) < 3:
        return out, out_std

    # NST-transform observations
    df_ok = df_month.copy()
    df_ok["Nanom"] = nst_pool.transform(
        df_ok["anomaly_wte_m"].values.reshape(-1, 1)
    ).ravel()

    # Mask prediction grid to cells within SEARCH_RADIUS_M of a well.
    # Cells farther than the search radius will never find a neighbour in
    # okrige and would raise an error; leave them as NaN.
    well_tree = cKDTree(df_ok[["X", "Y"]].values)
    grid_pts = np.column_stack([grid_x_flat, grid_y_flat])
    dists, _ = well_tree.query(grid_pts, k=1, workers=-1)
    in_range = dists <= SEARCH_RADIUS_M
    if not in_range.any():
        logger.warning("    No grid cells within search radius — skipping month")
        return out, out_std

    Pred_grid = grid_pts[in_range]

    try:
        est_N, var_ok = gs.Interpolation.okrige(
            Pred_grid,
            df_ok[["X", "Y", "Nanom"]],
            "X", "Y", "Nanom",
            num_points=min(K_NEIGHBOURS, len(df_ok)),
            vario=vario,
            radius=SEARCH_RADIUS_M,
        )
    except Exception as exc:
        logger.warning(f"    okrige failed: {exc}")
        return out, out_std

    # Inverse-NST for mean estimate
    out[in_range] = nst_pool.inverse_transform(est_N.reshape(-1, 1)).ravel()

    # Propagate kriging variance through inverse-NST (±1σ bounds)
    std_N = np.sqrt(np.maximum(var_ok, 0.0))
    p84 = nst_pool.inverse_transform((est_N + std_N).reshape(-1, 1)).ravel()
    p16 = nst_pool.inverse_transform((est_N - std_N).reshape(-1, 1)).ravel()
    out_std[in_range] = np.abs(p84 - p16) / 2.0

    return out, out_std


# ---------------------------------------------------------------------------
# Zarr output
# ---------------------------------------------------------------------------

def save_zarr(
    cube: np.ndarray,
    dates: list,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    path: Path,
    long_name: str,
    units: str,
) -> None:
    """Write (time, y, x) float32 cube to a Zarr v3-compatible store."""
    ny, nx = cube.shape[1], cube.shape[2]
    ds = xr.Dataset(
        {
            "data": xr.DataArray(
                cube.astype(np.float32),
                dims=["time", "y", "x"],
                coords={
                    "time": np.array(dates, dtype="datetime64[ns]"),
                    "y": y_coords,
                    "x": x_coords,
                },
                attrs={
                    "long_name": long_name,
                    "units": units,
                    "crs": "EPSG:5070",
                },
            )
        }
    )
    ds = ds.chunk({"time": ZARR_CHUNK_T, "y": ny, "x": nx})
    ds.to_zarr(path, mode="w", zarr_format=2)
    logger.info(f"  Saved: {path}  shape={cube.shape}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pilot temporal kriging of monthly WTE anomaly fields."
    )
    parser.add_argument(
        "--monthly", type=Path,
        default=Path("data/processed/nwis_gwlevels_monthly.parquet"),
    )
    parser.add_argument(
        "--sites", type=Path,
        default=Path("data/processed/nwis_sites_clean.parquet"),
    )
    parser.add_argument(
        "--grid", type=Path,
        default=Path("data/processed/bbox_grid_90m.nc"),
    )
    parser.add_argument(
        "--hydrogen-wtd", type=Path, default=None,
        help="Optional: HydroGEN prior DTW TIF. When supplied, WTE zarr is computed.",
    )
    parser.add_argument(
        "--states", nargs="+", default=["WA", "OR"],
        help="USPS state codes to include.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/processed"),
    )
    parser.add_argument(
        "--n-months", type=int, default=None,
        help="Limit to the most recent N months (useful for quick tests).",
    )
    parser.add_argument(
        "--grid-step", type=int, default=5,
        help="Subsample the bbox grid by this factor before kriging. "
             "Default 5 → 5 km pilot grid; use 1 for full 1 km resolution.",
    )
    args = parser.parse_args()

    for p in [args.monthly, args.sites, args.grid]:
        if not p.exists():
            raise FileNotFoundError(f"Required input not found: {p}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Load grid ────────────────────────────────────────────────────────
    ds_grid = xr.open_dataset(args.grid)
    step = args.grid_step
    x_coords = ds_grid["x"].values[::step]   # shape (nx//step,)
    y_coords = ds_grid["y"].values[::step]   # shape (ny//step,) — descending
    nx, ny = len(x_coords), len(y_coords)
    grid_km = step  # nominal resolution in km (input grid is 90 m)
    logger.info(f"Grid: {ny} rows × {nx} cols at {grid_km} km resolution (EPSG:5070)")

    # Flattened grid coordinates for kriging
    gx, gy = np.meshgrid(x_coords, y_coords)  # (ny, nx)
    grid_x_flat = gx.ravel()
    grid_y_flat = gy.ravel()
    n_cells = len(grid_x_flat)

    # ── Load anomaly data ────────────────────────────────────────────────
    df_anom = load_anomalies(args.monthly, args.sites, args.states)

    # All sorted unique months
    all_dates = sorted(df_anom["date"].unique())
    if args.n_months:
        all_dates = all_dates[-args.n_months:]
        logger.info(f"Limiting to {len(all_dates)} most recent months")

    n_months = len(all_dates)
    logger.info(f"Months to process: {n_months}")

    # ── Fit pooled NST + variogram ───────────────────────────────────────
    pool_vals = df_anom["anomaly_wte_m"].values.copy()
    nst_pool = QuantileTransformer(
        n_quantiles=min(NST_QUANTILES, len(pool_vals)),
        output_distribution="normal",
        random_state=42,
    )
    Npool = nst_pool.fit_transform(pool_vals.reshape(-1, 1)).ravel()

    # Sub-sample for variogram speed
    rng = np.random.default_rng(0)
    if len(pool_vals) > MAX_VARIOGRAM_PTS:
        idx = rng.choice(len(pool_vals), MAX_VARIOGRAM_PTS, replace=False)
        vx = df_anom["X"].values[idx]
        vy = df_anom["Y"].values[idx]
        vN = Npool[idx]
    else:
        vx = df_anom["X"].values
        vy = df_anom["Y"].values
        vN = Npool

    logger.info("Fitting pooled anomaly variogram …")
    vario = fit_variogram(vx, vy, vN)

    # ── Optionally load HydroGEN WTE prior ──────────────────────────────
    h_wte_flat: np.ndarray | None = None
    if args.hydrogen_wtd and args.hydrogen_wtd.exists():
        with rasterio.open(args.hydrogen_wtd) as src:
            h_dtw_grid = src.read(1, out_dtype="float64")
            nd = src.nodata if src.nodata is not None else -9999.0
            h_dtw_grid[h_dtw_grid == nd] = np.nan
            h_transform = src.transform
        # Sample HydroGEN DTW at each grid cell using nearest-neighbour
        cols = np.floor((grid_x_flat - h_transform.c) / h_transform.a).astype(int)
        rows = np.floor((grid_y_flat - h_transform.f) / h_transform.e).astype(int)
        nrows_h, ncols_h = h_dtw_grid.shape
        valid_h = (rows >= 0) & (rows < nrows_h) & (cols >= 0) & (cols < ncols_h)
        h_dtw_flat = np.full(n_cells, np.nan)
        h_dtw_flat[valid_h] = h_dtw_grid[rows[valid_h], cols[valid_h]]
        # WTE prior: we don't have the DEM at each grid cell here, so we cannot
        # convert H_DTW → H_WTE directly.  Instead we store it as None and only
        # output the anomaly zarr.  Full WTE assembly is done in 03_temporal_model.ipynb.
        logger.info(
            f"HydroGEN prior loaded; {np.isfinite(h_dtw_flat).sum():,} valid cells."
        )
        h_wte_flat = h_dtw_flat  # store DTW for now; notebook handles WTE assembly

    # ── Per-month kriging ────────────────────────────────────────────────
    anom_cube = np.full((n_months, ny, nx), np.nan, dtype=np.float32)
    std_cube = np.full((n_months, ny, nx), np.nan, dtype=np.float32)

    for ti, date in enumerate(all_dates):
        df_m = df_anom[df_anom["date"] == date]
        n_obs = len(df_m)

        if n_obs < MIN_SITES_PER_MONTH:
            logger.info(f"  {date:%Y-%m}  n={n_obs} < {MIN_SITES_PER_MONTH} → skip")
            continue

        logger.info(f"  {date:%Y-%m}  n={n_obs} sites …")
        est, std = krige_month(df_m, grid_x_flat, grid_y_flat, vario, nst_pool)
        anom_cube[ti] = est.reshape(ny, nx)
        std_cube[ti] = std.reshape(ny, nx)

    # ── Save anomaly zarr ────────────────────────────────────────────────
    out_anom = args.output_dir / "pilot_gwl_anomaly.zarr"
    save_zarr(
        anom_cube, all_dates, x_coords, y_coords,
        out_anom, "Monthly WTE anomaly (obs − site median)", "m",
    )

    out_std = args.output_dir / "pilot_gwl_anomaly_std.zarr"
    save_zarr(
        std_cube, all_dates, x_coords, y_coords,
        out_std, "Kriging uncertainty of monthly WTE anomaly (1-sigma)", "m",
    )

    logger.info("Pilot temporal kriging complete.")


if __name__ == "__main__":
    main()
