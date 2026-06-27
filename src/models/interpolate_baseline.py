"""
Interpolate the spatial baseline water table elevation (WTE) via co-kriging
with the MERIT Hydro DEM as a secondary variable (Markov Model 1).

Two operating modes
-------------------
DEM-only (default)
    NST(WTE) co-kriged against NST(DEM); same as original implementation.

EDK — External Drift Kriging with HydroGEN physics prior
    Activated by supplying ``--hydrogen-wtd``.  The Ma 2025 median WTD grid
    is used as a physics prior:

    WTE_prior(site) = DEM(site) − Ma2025_DTW(site)
    r(site)         = obs_WTE(site) − WTE_prior(site)      ← residual

    Residuals are NST-transformed and then co-kriged with DEM (MM1).
    The kriged residual field is added back to the continuous WTE_prior grid:

    baseline_wte(x,y) = (DEM(x,y) − Ma2025_DTW(x,y)) + kriged_residual(x,y)

    SGS realisations are computed on residuals; their spread gives σ_EDK(x,y).

Pipeline steps
--------------
1.  Load usable wells; project to EPSG:5070.
2.  [EDK] Sample Ma2025 WTD at well locations; compute WTE residuals.
    [DEM] Use obs_WTE directly.
3.  NST on the fitting target (residuals or WTE).
4.  Sample DEM at wells; NST(DEM); MM1 correlation ρ₁₂.
5.  Fit per-HUC-2 variogram on NST-target via skgstat.
6.  Co-krige NST-target with DEM secondary (MM1) per HUC-2 patch.
7.  SGS ensemble (N realisations) for σ_EDK or σ_DEM.
8.  Inverse NST; add residuals back to WTE_prior if EDK.
9.  Apply 50 km well-density mask.
10. Write: baseline_wte_m.tif, baseline_dtw_m.tif,
           baseline_kriging_std_m.tif, well_density_mask.tif

Usage (EDK):
    python -m src.models.interpolate_baseline \\
        --sites data/processed/nwis_sites_clean.parquet \\
        --dem data/raw/dem/merit_hydro_90m_5070.tif \\
        --hydrogen-wtd data/processed/hydrogen_wtd_prior_90m.tif \\
        --output-dir data/processed

Usage (DEM-only, original mode):
    python -m src.models.interpolate_baseline \\
        --sites data/processed/nwis_sites_clean.parquet \\
        --dem data/raw/dem/merit_hydro_90m_5070.tif \\
        --output-dir data/processed

Assumptions and limitations: docs/assumptions.md (A-series) / docs/limitations.md (L-series).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio.crs import CRS
from scipy.spatial import cKDTree
from sklearn.preprocessing import QuantileTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)

# Minimum usable sites per HUC-2 region to attempt kriging
MIN_SITES_PER_REGION = 10

# Number of nearest neighbours for co-kriging search
K_NEIGHBOURS = 100

# Search radius for kriging (m); 2 × typical variogram range
SEARCH_RADIUS_M = 300_000.0

# Well-density mask: cells > this distance from nearest usable well → NaN
MASK_DISTANCE_M = 50_000.0

# Number of SGS realisations for uncertainty estimation
N_SGS_REALISATIONS = 20

# NST quantiles
NST_QUANTILES = 500


# ---------------------------------------------------------------------------
# HUC-2 fallback: approximate CONUS bounding boxes in EPSG:5070 (m)
# Used when the full NHDPlus HUC-2 shapefile is not available to assign each
# well to a hydrological region. The bounding boxes below are approximate and
# intentionally overlap so that edge wells are always claimed by exactly one
# region (first match wins in _assign_huc2_grid).
# ---------------------------------------------------------------------------
HUC2_APPROX_BOXES = {
    "01": {"xmin": 1_400_000, "xmax": 2_258_000, "ymin": 2_400_000, "ymax": 3_173_000},  # New England
    "02": {"xmin": 900_000, "xmax": 1_900_000, "ymin": 1_800_000, "ymax": 2_800_000},   # Mid-Atlantic
    "03": {"xmin": 500_000, "xmax": 1_500_000, "ymin": 270_000, "ymax": 1_500_000},     # South Atlantic / Gulf
    "04": {"xmin": -200_000, "xmax": 1_200_000, "ymin": 1_900_000, "ymax": 3_000_000},  # Great Lakes
    "05": {"xmin": -200_000, "xmax": 900_000, "ymin": 1_300_000, "ymax": 2_200_000},    # Ohio
    "06": {"xmin": 100_000, "xmax": 800_000, "ymin": 900_000, "ymax": 1_600_000},       # Tennessee
    "07": {"xmin": -600_000, "xmax": 200_000, "ymin": 1_500_000, "ymax": 2_700_000},    # Upper Mississippi
    "08": {"xmin": -500_000, "xmax": 400_000, "ymin": 270_000, "ymax": 1_200_000},      # Lower Mississippi
    "09": {"xmin": -1_400_000, "xmax": -400_000, "ymin": 2_000_000, "ymax": 3_173_000}, # Souris/Red/Rainy
    "10": {"xmin": -1_000_000, "xmax": 0, "ymin": 1_200_000, "ymax": 2_600_000},        # Missouri
    "11": {"xmin": -700_000, "xmax": 150_000, "ymin": 600_000, "ymax": 1_500_000},      # Arkansas-White-Red
    "12": {"xmin": -1_100_000, "xmax": -200_000, "ymin": 270_000, "ymax": 1_100_000},   # Texas-Gulf
    "13": {"xmin": -1_600_000, "xmax": -700_000, "ymin": 500_000, "ymax": 1_500_000},   # Rio Grande
    "14": {"xmin": -2_000_000, "xmax": -1_100_000, "ymin": 1_100_000, "ymax": 2_200_000},# Upper Colorado
    "15": {"xmin": -2_100_000, "xmax": -1_100_000, "ymin": 270_000, "ymax": 1_300_000}, # Lower Colorado
    "16": {"xmin": -2_100_000, "xmax": -1_200_000, "ymin": 1_500_000, "ymax": 2_600_000},# Great Basin
    "17": {"xmin": -2_356_000, "xmax": -1_400_000, "ymin": 1_800_000, "ymax": 3_173_000},# Pacific NW
    "18": {"xmin": -2_356_000, "xmax": -1_500_000, "ymin": 270_000, "ymax": 1_800_000}, # California
}


def _assign_huc2_approx(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Assign approximate HUC-2 codes to EPSG:5070 coordinates using bounding boxes.

    Falls back to '99' (unassigned) when no box matches.
    """
    codes = np.full(len(x), "99", dtype="<U2")
    for huc, box in HUC2_APPROX_BOXES.items():
        mask = (
            (x >= box["xmin"])
            & (x <= box["xmax"])
            & (y >= box["ymin"])
            & (y <= box["ymax"])
        )
        # Only assign where not already claimed by an earlier region
        unassigned = codes == "99"
        codes[mask & unassigned] = huc
    return codes


def load_usable_sites(sites_parquet: Path) -> gpd.GeoDataFrame:
    """
    Load QC-passed sites and project to EPSG:5070.

    Filters to sites that are neither sparse nor long-gap, have valid WTE and
    coordinates, and are not flagged as confined (deep wells).

    Parameters
    ----------
    sites_parquet:
        Path to ``nwis_sites_clean.parquet``.

    Returns
    -------
    GeoDataFrame with columns: site_no, X, Y (EPSG:5070 m), median_wte_m
    """
    df = pd.read_parquet(sites_parquet)
    logger.info(f"Loaded {len(df):,} sites from {sites_parquet.name}")

    required = ["site_no", "lat", "lon", "median_wte_m", "is_sparse_timeseries", "has_long_gap"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns in sites parquet: {missing}")

    usable = df[~df["is_sparse_timeseries"] & ~df["has_long_gap"]].copy()
    usable = usable.dropna(subset=["lat", "lon", "median_wte_m"])
    logger.info(f"  Usable sites (not sparse, not long-gap): {len(usable):,}")

    # Project to EPSG:5070
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    x5070, y5070 = transformer.transform(usable["lon"].values, usable["lat"].values)
    usable = usable.copy()
    usable["X"] = x5070.astype(np.float64)
    usable["Y"] = y5070.astype(np.float64)

    return usable


def _fit_nst(values: np.ndarray) -> tuple[QuantileTransformer, np.ndarray]:
    """
    Fit a Normal Score Transform on 1-D values and return the transformer + transformed values.
    """
    nst = QuantileTransformer(n_quantiles=min(NST_QUANTILES, len(values)), output_distribution="normal")
    transformed = nst.fit_transform(values.reshape(-1, 1)).ravel()
    return nst, transformed


def _fit_variogram(
    x: np.ndarray,
    y: np.ndarray,
    values: np.ndarray,
    max_lag_m: float = 500_000.0,
    n_lags: int = 70,
) -> list:
    """
    Fit an exponential variogram using scikit-gstat and return the GStatSim vario list.

    Parameters
    ----------
    x, y:
        EPSG:5070 coordinates (m).
    values:
        NST-transformed values (should be approximately N(0,1)).
    max_lag_m:
        Maximum lag distance for variogram fitting (m).
    n_lags:
        Number of lag bins.

    Returns
    -------
    list: [azimuth, nugget, major_range, minor_range, sill, vtype]
        In the format expected by GStatSim.
    """
    try:
        import skgstat as skg
    except ImportError as exc:
        raise ImportError("scikit-gstat is required. Run `pixi install`.") from exc

    coords = np.column_stack([x, y])
    V = skg.Variogram(
        coords,
        values,
        bin_func="even",
        n_lags=n_lags,
        maxlag=max_lag_m,
        normalize=False,
    )
    V.model = "exponential"

    try:
        vrange, vsill, vnugget = V.parameters
    except Exception:
        # Fallback: use empirical estimates
        vnugget = 0.0
        vsill = float(np.var(values))
        vrange = max_lag_m * 0.3

    # GStatSim vario list: [azimuth, nugget, major_range, minor_range, sill, vtype]
    # Isotropic: major_range == minor_range
    return [0.0, float(vnugget), float(vrange), float(vrange), float(vsill), "Exponential"]


def _sample_dem(dem_path: Path, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Sample DEM at EPSG:5070 point coordinates; return float32 array (NaN for nodata)."""
    from src.features.compute_grid import sample_dem_at_points
    return sample_dem_at_points(dem_path, x, y)


def sample_raster_at_points(
    raster_path: Path,
    x: np.ndarray,
    y: np.ndarray,
) -> np.ndarray:
    """
    Sample any float32 EPSG:5070 raster at point coordinates.

    Parameters
    ----------
    raster_path:
        GeoTIFF in EPSG:5070.
    x, y:
        1-D arrays of EPSG:5070 coordinates.

    Returns
    -------
    np.ndarray, shape (n,), float32 — nodata/out-of-bounds → NaN.
    """
    with rasterio.open(raster_path) as src:
        nd = src.nodata if src.nodata is not None else -9999.0
        coords = list(zip(x.tolist(), y.tolist()))
        values = np.array(
            [v[0] for v in src.sample(coords, indexes=1)],
            dtype=np.float32,
        )
    values[values == nd] = np.nan
    return values


def compute_edk_residuals(
    obs_wte_m: np.ndarray,
    dem_at_wells: np.ndarray,
    hydrogen_dtw_at_wells: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the EDK residual at each well.

    WTE_prior(site) = DEM(site) − Ma2025_DTW(site)
    residual(site)  = obs_WTE(site) − WTE_prior(site)

    Parameters
    ----------
    obs_wte_m:
        Observed long-term median WTE at each well (m NAVD88).
    dem_at_wells:
        DEM elevation at each well (m NAVD88).
    hydrogen_dtw_at_wells:
        Ma 2025 HydroGEN WTD at each well (m, positive = below surface).

    Returns
    -------
    wte_prior : np.ndarray — physics-model WTE at each well (m NAVD88)
    residual  : np.ndarray — obs_WTE − WTE_prior (m); NaN where prior is NaN
    """
    wte_prior = dem_at_wells - hydrogen_dtw_at_wells  # NaN where H2 is NaN
    residual = obs_wte_m - wte_prior
    n_valid = np.isfinite(residual).sum()
    n_total = len(residual)
    logger.info(
        f"EDK residuals: {n_valid:,}/{n_total:,} wells have valid HydroGEN prior; "
        f"residual mean={np.nanmean(residual):.2f} m  std={np.nanstd(residual):.2f} m"
    )
    if n_valid < n_total * 0.5:
        logger.warning(
            f"Only {n_valid}/{n_total} wells overlap with the HydroGEN grid — "
            "check that hydrogen_wtd_prior_90m.tif covers the study region."
        )
    return wte_prior, residual


def _build_prediction_grid_for_region(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    dem_flat: np.ndarray,
    huc2_code: str,
) -> "pd.DataFrame":
    """
    Return a prediction DataFrame for all grid cells assigned to a HUC-2 region.

    Parameters
    ----------
    grid_x, grid_y:
        Ravelled EPSG:5070 coordinates for every cell in the CONUS grid.
    dem_flat:
        DEM values at each grid cell (same order as grid_x/grid_y).
    huc2_code:
        HUC-2 code string (2 digits).

    Returns
    -------
    pd.DataFrame with columns X, Y, DEM (valid non-NaN cells only).
    """
    import pandas as pd

    huc_codes = _assign_huc2_approx(grid_x, grid_y)
    mask = (huc_codes == huc2_code) & np.isfinite(dem_flat)
    return pd.DataFrame({
        "X": grid_x[mask],
        "Y": grid_y[mask],
        "DEM": dem_flat[mask],
        "_idx": np.where(mask)[0],
    })


def run_cokrige_region(
    df_wells: pd.DataFrame,
    pred_df: pd.DataFrame,
    vario: list,
    nst_wte: QuantileTransformer,
    nst_dem: QuantileTransformer,
    rho12: float,
    n_sgs: int = N_SGS_REALISATIONS,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run co-kriging MM1 and co-SGS for a single HUC-2 region.

    Parameters
    ----------
    df_wells:
        Wells in this region with columns X, Y, Nwte (NST WTE), Ndem (NST DEM).
    pred_df:
        Prediction grid with columns X, Y, Ndem (NST DEM at grid cells).
    vario:
        GStatSim variogram list.
    nst_wte, nst_dem:
        NST transformers (used for inverse transform).
    rho12:
        MM1 correlation coefficient between NST WTE and NST DEM.
    n_sgs:
        Number of SGS realisations for uncertainty estimation.

    Returns
    -------
    mean_wte : np.ndarray shape (n_pred,) — co-kriging estimate in original WTE units
    std_wte  : np.ndarray shape (n_pred,) — std across SGS realisations, WTE units
    """
    try:
        import gstatsim as gs
    except ImportError as exc:
        raise ImportError("gstatsim is required. Run `pixi install`.") from exc

    Pred_grid = pred_df[["X", "Y"]].values
    df_primary = df_wells[["X", "Y", "Nwte"]].copy()
    df_secondary = pred_df[["X", "Y", "Ndem"]].copy()

    # --- Co-kriging mean estimate ---
    est_N, _ = gs.Interpolation.cokrige_mm1(
        Pred_grid,
        df_primary, "X", "Y", "Nwte",
        df_secondary, "X", "Y", "Ndem",
        num_points=min(K_NEIGHBOURS, len(df_wells)),
        vario=vario,
        radius=SEARCH_RADIUS_M,
        corrcoef=rho12,
    )

    # --- SGS realisations for uncertainty ---
    realisations_N = []
    for _ in range(n_sgs):
        sim_N = gs.Interpolation.cosim_mm1(
            Pred_grid,
            df_primary, "X", "Y", "Nwte",
            df_secondary, "X", "Y", "Ndem",
            num_points=min(K_NEIGHBOURS, len(df_wells)),
            vario=vario,
            radius=SEARCH_RADIUS_M,
            corrcoef=rho12,
        )
        realisations_N.append(sim_N)

    realisations_N = np.array(realisations_N)  # (n_sgs, n_pred)

    # Inverse NST
    mean_wte = nst_wte.inverse_transform(est_N.reshape(-1, 1)).ravel()
    std_wte = nst_wte.inverse_transform(
        np.percentile(realisations_N, 84, axis=0).reshape(-1, 1)
    ).ravel() - nst_wte.inverse_transform(
        np.percentile(realisations_N, 16, axis=0).reshape(-1, 1)
    ).ravel()
    std_wte = np.abs(std_wte) / 2.0  # approx 1σ from 16–84th percentile range

    return mean_wte, std_wte


def build_well_density_mask(
    x_wells: np.ndarray,
    y_wells: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    max_dist_m: float = MASK_DISTANCE_M,
) -> np.ndarray:
    """
    Return a boolean mask (True = valid) for grid cells within max_dist_m of a well.

    Parameters
    ----------
    x_wells, y_wells:
        EPSG:5070 coordinates of usable wells.
    grid_x, grid_y:
        Ravelled EPSG:5070 coordinates of every grid cell.
    max_dist_m:
        Maximum distance threshold (m).

    Returns
    -------
    np.ndarray of bool, shape (n_cells,)
    """
    tree = cKDTree(np.column_stack([x_wells, y_wells]))
    dists, _ = tree.query(np.column_stack([grid_x, grid_y]), workers=-1)
    return dists <= max_dist_m


def save_geotiff(array: np.ndarray, transform: rasterio.transform.Affine, path: Path, nodata: float = np.nan) -> None:
    """Write a 2-D float32 array to a GeoTIFF in EPSG:5070."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=np.float32,
        crs=TARGET_CRS,
        transform=transform,
        nodata=-9999.0,
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        out = array.astype(np.float32)
        if np.isnan(nodata):
            out = np.where(np.isnan(out), -9999.0, out)
        dst.write(out, 1)
    logger.info(f"  Saved: {path}")


def main() -> None:  # noqa: C901 (complexity OK for pipeline entry point)
    parser = argparse.ArgumentParser(
        description="Interpolate spatial WTE baseline. EDK mode activated by --hydrogen-wtd.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sites", type=Path, default=Path("data/processed/nwis_sites_clean.parquet"))
    parser.add_argument("--dem", type=Path, default=Path("data/raw/dem/merit_hydro_90m_5070.tif"))
    parser.add_argument(
        "--hydrogen-wtd",
        type=Path,
        default=None,
        help=(
            "Path to hydrogen_wtd_prior_90m.tif (Ma 2025 WTD, EPSG:5070). "
            "When supplied, runs EDK mode: co-krige residuals = obs_WTE − WTE_prior. "
            "When absent, falls back to DEM-only co-kriging of raw WTE (original mode)."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--n-sgs", type=int, default=N_SGS_REALISATIONS, help="SGS realisations for uncertainty")
    args = parser.parse_args()

    edk_mode = args.hydrogen_wtd is not None
    logger.info(f"Mode: {'EDK (HydroGEN physics prior)' if edk_mode else 'DEM-only co-kriging'}")

    # ---- 0. Validate inputs ----
    required = [args.sites, args.dem]
    if edk_mode:
        required.append(args.hydrogen_wtd)
    for p in required:
        if not p.exists():
            raise FileNotFoundError(f"Required input not found: {p}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Load grid geometry ----
    from src.features.compute_grid import load_grid_spec, read_dem_array

    grid = load_grid_spec(args.dem)
    dem_arr = read_dem_array(args.dem, grid)  # (height, width) float32, NaN for nodata
    logger.info(f"DEM loaded: {grid.width} × {grid.height} px")

    # Flatten grid to ravelled arrays for cKDTree / GStatSim
    grid_xx, grid_yy = np.meshgrid(grid.x_coords, grid.y_coords)
    grid_x_flat = grid_xx.ravel()
    grid_y_flat = grid_yy.ravel()
    dem_flat = dem_arr.ravel()

    # ---- 1b. [EDK] Load HydroGEN WTD grid ----
    if edk_mode:
        with rasterio.open(args.hydrogen_wtd) as src:
            h2_dtw_arr = src.read(1).astype(np.float32)
            h2_nodata = src.nodata if src.nodata is not None else -9999.0
        h2_dtw_arr[h2_dtw_arr == h2_nodata] = np.nan
        h2_dtw_flat = h2_dtw_arr.ravel()
        # WTE_prior grid = DEM − Ma2025_DTW
        h2_wte_flat = dem_flat - h2_dtw_flat
        logger.info(f"HydroGEN WTD prior loaded: {args.hydrogen_wtd.name}")
    else:
        h2_dtw_arr = None
        h2_wte_flat = None

    # ---- 2. Load usable wells ----
    df_wells = load_usable_sites(args.sites)

    # ---- 3. Determine fitting target: residuals (EDK) or raw WTE (DEM-only) ----
    # Sample DEM at wells first (needed for both modes)
    dem_at_wells = _sample_dem(args.dem, df_wells["X"].values, df_wells["Y"].values)
    valid_dem = np.isfinite(dem_at_wells)
    df_wells = df_wells[valid_dem].copy()
    dem_at_wells = dem_at_wells[valid_dem]

    if edk_mode:
        h2_dtw_at_wells = sample_raster_at_points(
            args.hydrogen_wtd, df_wells["X"].values, df_wells["Y"].values
        )
        wte_prior_at_wells, residuals = compute_edk_residuals(
            df_wells["median_wte_m"].values, dem_at_wells, h2_dtw_at_wells
        )
        # Drop wells where HydroGEN coverage is missing
        valid_h2 = np.isfinite(residuals)
        df_wells = df_wells[valid_h2].copy()
        dem_at_wells = dem_at_wells[valid_h2]
        fitting_values = residuals[valid_h2]  # krige residuals
        logger.info(f"EDK: {valid_h2.sum():,} wells with valid HydroGEN prior for fitting")
    else:
        fitting_values = df_wells["median_wte_m"].values  # krige raw WTE
        logger.info("DEM-only: kriging raw WTE")

    # ---- 4. NST on fitting target ----
    nst_fit, n_fit = _fit_nst(fitting_values)
    df_wells = df_wells.copy()
    df_wells["Nfit"] = n_fit  # renamed from Nwte for clarity; column used in run_cokrige_region
    df_wells["Nwte"] = n_fit  # run_cokrige_region expects "Nwte"
    logger.info(f"NST({'residuals' if edk_mode else 'WTE'}) fitted")

    # ---- 5. NST on DEM (secondary variable for MM1) ----
    nst_dem, ndem_wells = _fit_nst(dem_at_wells)
    df_wells["Ndem"] = ndem_wells
    logger.info(f"DEM sampled at {len(df_wells):,} wells; NST(DEM) fitted")

    # ---- 6. NST(DEM) on full grid (needed for MM1 secondary) ----
    valid_grid = np.isfinite(dem_flat)
    ndem_grid = np.full(len(dem_flat), np.nan, dtype=np.float64)
    ndem_grid[valid_grid] = nst_dem.transform(dem_flat[valid_grid].reshape(-1, 1)).ravel()

    # ---- 7. Correlation coefficient for MM1 ----
    rho12 = float(np.corrcoef(df_wells["Nwte"].values, df_wells["Ndem"].values)[0, 1])
    logger.info(f"MM1 correlation coefficient ρ₁₂ = {rho12:.3f}")
    if abs(rho12) < 0.3:
        logger.warning(
            f"ρ₁₂ = {rho12:.3f} is low — co-kriging MM1 benefit will be limited. "
            "Consider ordinary kriging only."
        )

    # ---- 8. Assign HUC-2 regions ----
    huc2_wells = _assign_huc2_approx(df_wells["X"].values, df_wells["Y"].values)
    df_wells = df_wells.copy()
    df_wells["huc2"] = huc2_wells
    unique_hucs = sorted(set(huc2_wells))
    logger.info(f"HUC-2 regions represented: {unique_hucs}")

    # ---- 9. Per-HUC-2 variogram fitting ----
    variograms: dict[str, list] = {}
    for huc in unique_hucs:
        subset = df_wells[df_wells["huc2"] == huc]
        if len(subset) < MIN_SITES_PER_REGION:
            logger.warning(f"HUC-2 {huc}: only {len(subset)} sites — skipping variogram fit (will use nearest HUC)")
            continue
        vario = _fit_variogram(subset["X"].values, subset["Y"].values, subset["Nwte"].values)
        variograms[huc] = vario
        logger.info(f"  HUC-2 {huc}: range={vario[2]/1000:.0f} km, sill={vario[4]:.3f}, nugget={vario[1]:.3f}")

    # Fallback: if some HUCs have too few sites, use CONUS-wide variogram
    conus_vario = _fit_variogram(df_wells["X"].values, df_wells["Y"].values, df_wells["Nwte"].values)
    for huc in unique_hucs:
        if huc not in variograms:
            variograms[huc] = conus_vario
            logger.info(f"  HUC-2 {huc}: using CONUS-wide fallback variogram")

    # Save variogram parameters
    vario_path = args.output_dir / "variogram_params_huc2.json"
    with open(vario_path, "w") as fh:
        json.dump({k: v for k, v in variograms.items()}, fh, indent=2)
    logger.info(f"Variogram parameters saved: {vario_path}")

    # ---- 10. Co-kriging per HUC-2 patch ----
    wte_flat = np.full(len(grid_x_flat), np.nan, dtype=np.float64)
    std_flat = np.full(len(grid_x_flat), np.nan, dtype=np.float64)

    for huc in unique_hucs:
        df_region_wells = df_wells[df_wells["huc2"] == huc]
        if len(df_region_wells) < MIN_SITES_PER_REGION:
            logger.warning(f"  HUC-2 {huc}: insufficient wells for kriging — skipping")
            continue

        # Build prediction grid for this HUC-2 (grid cells within the HUC bbox)
        huc2_grid_codes = _assign_huc2_approx(grid_x_flat, grid_y_flat)
        cell_mask = (huc2_grid_codes == huc) & valid_grid
        if cell_mask.sum() == 0:
            continue

        pred_df = pd.DataFrame({
            "X": grid_x_flat[cell_mask],
            "Y": grid_y_flat[cell_mask],
            "Ndem": ndem_grid[cell_mask],
            "_idx": np.where(cell_mask)[0],
        })
        pred_df = pred_df.dropna(subset=["Ndem"])
        if len(pred_df) == 0:
            continue

        logger.info(f"  HUC-2 {huc}: krige {len(pred_df):,} cells with {len(df_region_wells)} wells …")

        try:
            mean_wte, std_wte = run_cokrige_region(
                df_region_wells,
                pred_df,
                variograms[huc],
                nst_wte,
                nst_dem,
                rho12,
                n_sgs=args.n_sgs,
            )
        except Exception as exc:
            logger.error(f"  HUC-2 {huc}: co-kriging failed ({exc}) — leaving NaN")
            continue

        wte_flat[pred_df["_idx"].values] = mean_wte
        std_flat[pred_df["_idx"].values] = std_wte

    # ---- 11. Well-density mask ----
    in_mask = build_well_density_mask(
        df_wells["X"].values, df_wells["Y"].values,
        grid_x_flat, grid_y_flat,
    )
    wte_flat[~in_mask] = np.nan
    std_flat[~in_mask] = np.nan
    logger.info(f"Well-density mask: {in_mask.sum():,} cells within {MASK_DISTANCE_M/1000:.0f} km of a well")

    # ---- 12. Reshape, optionally add back physics prior (EDK), compute DTW ----
    kriging_flat = wte_flat  # co-kriged field (residuals in EDK mode, raw WTE in DEM mode)

    if edk_mode:
        # Add kriged residuals back to the continuous WTE_prior grid
        # h2_wte_flat = DEM - Ma2025_DTW (computed above, NaN outside HydroGEN coverage)
        wte_flat_final = np.where(
            np.isfinite(h2_wte_flat) & np.isfinite(kriging_flat),
            h2_wte_flat + kriging_flat,
            np.nan,
        )
        mode_label = "edk"
    else:
        wte_flat_final = kriging_flat
        mode_label = "dem_only"

    wte_2d = wte_flat_final.reshape(grid.height, grid.width).astype(np.float32)
    std_2d = std_flat.reshape(grid.height, grid.width).astype(np.float32)
    mask_2d = in_mask.reshape(grid.height, grid.width)
    dtw_2d = (dem_arr - wte_2d).astype(np.float32)  # positive = water below surface

    # ---- 13. Save outputs ----
    save_geotiff(wte_2d, grid.transform, args.output_dir / "baseline_wte_m.tif")
    save_geotiff(dtw_2d, grid.transform, args.output_dir / "baseline_dtw_m.tif")
    # Output kriging std under a unified name (whether EDK or DEM-only)
    save_geotiff(std_2d, grid.transform, args.output_dir / "baseline_kriging_std_m.tif")
    # Backward-compat alias
    save_geotiff(std_2d, grid.transform, args.output_dir / "baseline_std_m.tif")
    save_geotiff(
        mask_2d.astype(np.float32), grid.transform, args.output_dir / "well_density_mask.tif",
    )

    # ---- 14. Summary report ----
    report = {
        "mode": mode_label,
        "n_usable_wells": int(len(df_wells)),
        "rho12": rho12,
        "huc2_variograms": variograms,
        "n_sgs_realisations": args.n_sgs,
        "masked_cells": int((~in_mask).sum()),
        "valid_cells": int(in_mask.sum()),
        "dtw_negative_fraction": float(np.nanmean(dtw_2d < 0)),
        "edk_residual_mean_m": float(np.nanmean(fitting_values)) if edk_mode else None,
        "edk_residual_std_m": float(np.nanstd(fitting_values)) if edk_mode else None,
    }
    report_path = args.output_dir / "baseline_report.json"
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    logger.info(f"Report: {report_path}")
    logger.info(f"DTW < 0 fraction: {report['dtw_negative_fraction']:.4f} (target < 0.001)")
    logger.info("Baseline interpolation complete.")


if __name__ == "__main__":
    main()
