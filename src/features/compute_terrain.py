"""Compute HAND, TWI, slope, and contributing area from a 3DEP DEM.

Outputs (all at 90 m EPSG:5070, float32, nodata=-9999):
  data/processed/terrain_hand_90m.tif          — Height Above Nearest Drainage (m)
  data/processed/terrain_twi_90m.tif           — Topographic Wetness Index (dimensionless)
  data/processed/terrain_slope_90m.tif         — slope (degrees)
  data/processed/terrain_contrib_area_90m.tif  — contributing area (m²)

Physical basis:
  HAND=0 in valley floors (highest liquefaction risk), large on ridge crests.
  TWI = ln(α / tan(β)) where α = contributing area per unit contour (m²/m) and β = slope.
  Ref: Beven & Kirkby (1979), Hydrol. Sci. Bull.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import rasterio
import richdem as rd
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject

logger = logging.getLogger(__name__)

NODATA = -9999.0
TARGET_RES_90M = 90.0

# Stream initiation threshold: cells with contributing area > this (m²) are streams.
# 1e6 m² = 1 km² — appropriate for PNW drainage network at 10 m resolution.
STREAM_THRESHOLD_M2 = 1e6


def _load_dem_array(dem_path: Path) -> tuple[np.ndarray, rasterio.profiles.Profile]:
    """Load DEM as float32 array with nodata masked to NaN."""
    with rasterio.open(dem_path) as src:
        profile = src.profile.copy()
        arr = src.read(1).astype(np.float32)
        nodata = src.nodata
    if nodata is not None:
        arr[arr == nodata] = np.nan
    return arr, profile


def compute_slope(dem_arr: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Compute slope in degrees using richdem.

    Parameters
    ----------
    dem_arr:
        2D float32 array, NaN where nodata.
    cell_size_m:
        Grid resolution in metres.

    Returns
    -------
    np.ndarray
        Slope in degrees.
    """
    rda = rd.rdarray(np.where(np.isnan(dem_arr), NODATA, dem_arr), no_data=NODATA)
    rda.geotransform = (0, cell_size_m, 0, 0, 0, -cell_size_m)
    slope = rd.TerrainAttribute(rda, attrib="slope_degrees")
    result = np.array(slope).astype(np.float32)
    result[result == NODATA] = np.nan
    return result


def compute_contributing_area(dem_arr: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Compute D8 contributing area in m² using richdem.

    Parameters
    ----------
    dem_arr:
        2D float32 array, NaN where nodata.
    cell_size_m:
        Grid resolution in metres.

    Returns
    -------
    np.ndarray
        Contributing area in m² (cell count × cell_size_m²).
    """
    rda = rd.rdarray(np.where(np.isnan(dem_arr), NODATA, dem_arr), no_data=NODATA)
    rda.geotransform = (0, cell_size_m, 0, 0, 0, -cell_size_m)
    rd.FillDepressions(rda, epsilon=True, in_place=True)
    accum = rd.FlowAccumulation(rda, method="D8")
    result = np.array(accum).astype(np.float32) * cell_size_m ** 2
    result[result < 0] = np.nan
    return result


def compute_hand(
    dem_arr: np.ndarray,
    contrib_area_m2: np.ndarray,
    stream_threshold_m2: float = STREAM_THRESHOLD_M2,
) -> np.ndarray:
    """Compute HAND (Height Above Nearest Drainage).

    Stream cells are defined where contributing area ≥ stream_threshold_m2.
    HAND at each cell = elevation of that cell − elevation of the nearest stream cell
    (in the D8 flow direction network, following the path to the stream).

    The D8 downstream neighbour of each cell is derived from richdem's
    ``FlowProportions`` (the single slot equal to 1.0 under D8), and each non-stream cell
    is traced along that network to its first stream cell, recording the elevation
    difference.

    Parameters
    ----------
    dem_arr:
        2D float32 DEM array.
    contrib_area_m2:
        Contributing area in m² (same shape as dem_arr).
    stream_threshold_m2:
        Cells with contrib_area ≥ this are classified as streams.

    Returns
    -------
    np.ndarray
        HAND values in metres (0 at stream cells, positive above stream).
    """
    nrows, ncols = dem_arr.shape
    is_stream = contrib_area_m2 >= stream_threshold_m2

    # richdem's Python API exposes FlowProportions (not FlowDirections). For D8 exactly
    # one proportion slot per cell is 1.0, giving the single downstream neighbour. Fill
    # depressions first so routing matches the contributing-area / stream network above.
    rda = rd.rdarray(np.where(np.isnan(dem_arr), NODATA, dem_arr), no_data=NODATA)
    rd.FillDepressions(rda, epsilon=True, in_place=True)
    # (nrows, ncols, 9) float array — force float32 to halve peak memory on large 3DEP tiles.
    props = np.asarray(rd.FlowProportions(rda, method="D8"), dtype=np.float32)

    # richdem neighbour offsets for proportion slots 1..8: (drow, dcol) = (RD_DY[n], RD_DX[n]).
    RD_DX = np.array([0, -1, -1, 0, 1, 1, 1, 0, -1])
    RD_DY = np.array([0, 0, -1, -1, -1, 0, 1, 1, 1])
    nbr = np.argmax(props[:, :, 1:9], axis=2) + 1     # dominant downstream slot (1..8)
    has_flow = props[:, :, 1:9].max(axis=2) > 0        # False at pits / outlets / edges
    del props  # free the (nrows, ncols, 9) array before the per-cell tracing loop

    # For each non-stream cell, follow the D8 path until a stream cell is reached
    hand = np.full((nrows, ncols), np.nan, dtype=np.float32)
    hand[is_stream] = 0.0

    for row in range(nrows):
        for col in range(ncols):
            if is_stream[row, col] or np.isnan(dem_arr[row, col]):
                continue
            # Trace downstream to the nearest stream
            r, c = row, col
            for _ in range(5000):  # generous cap for large tiles
                if not has_flow[r, c]:
                    break
                n = nbr[r, c]
                r2, c2 = r + RD_DY[n], c + RD_DX[n]
                if r2 < 0 or r2 >= nrows or c2 < 0 or c2 >= ncols:
                    break
                if is_stream[r2, c2]:
                    if not np.isnan(dem_arr[row, col]) and not np.isnan(dem_arr[r2, c2]):
                        hand[row, col] = max(0.0, dem_arr[row, col] - dem_arr[r2, c2])
                    break
                r, c = r2, c2

    return hand


def compute_twi(contrib_area_m2: np.ndarray, slope_deg: np.ndarray) -> np.ndarray:
    """Compute TWI = ln(α / tan(β)) per Beven & Kirkby (1979).

    Parameters
    ----------
    contrib_area_m2:
        Contributing area in m².
    slope_deg:
        Slope in degrees.

    Returns
    -------
    np.ndarray
        TWI (dimensionless), NaN where slope = 0 or contributing area ≤ 0.
    """
    slope_rad = np.deg2rad(slope_deg)
    tan_slope = np.tan(slope_rad)
    with np.errstate(divide="ignore", invalid="ignore"):
        twi = np.log(contrib_area_m2 / tan_slope)
    twi = np.where((tan_slope <= 0) | (contrib_area_m2 <= 0), np.nan, twi)
    return twi.astype(np.float32)


def _resample_to_90m(
    arr: np.ndarray,
    src_profile: dict,
    dst_path: Path,
    resampling_method: Resampling = Resampling.average,
) -> None:
    """Write a float32 array at native resolution then resample to 90 m."""
    import tempfile
    import os

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    profile = src_profile.copy()
    profile.update({"dtype": "float32", "nodata": NODATA, "count": 1})

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        arr_out = np.where(np.isnan(arr), NODATA, arr).astype(np.float32)
        with rasterio.open(tmp_path, "w", **profile) as tmp_ds:
            tmp_ds.write(arr_out, 1)

        with rasterio.open(tmp_path) as src:
            dst_transform, dst_width, dst_height = calculate_default_transform(
                src.crs, src.crs, src.width, src.height, *src.bounds,
                resolution=TARGET_RES_90M,
            )
            dst_profile = src.profile.copy()
            dst_profile.update({
                "transform": dst_transform,
                "width": dst_width,
                "height": dst_height,
                "nodata": NODATA,
                "dtype": "float32",
                "compress": "LZW",
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            })
            with rasterio.open(dst_path, "w", **dst_profile) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=src.crs,
                    resampling=resampling_method,
                )
    finally:
        os.unlink(tmp_path)

    logger.info("Written: %s", dst_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute terrain attributes from 3DEP DEM.")
    parser.add_argument(
        "--dem",
        type=Path,
        default=Path("data/raw/dem/3dep_10m_5070.tif"),
        help="Input DEM (EPSG:5070 preferred; will use as-is)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Output directory for terrain TIFs",
    )
    parser.add_argument(
        "--stream-threshold",
        type=float,
        default=STREAM_THRESHOLD_M2,
        help="Contributing area threshold for stream initiation (m²)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    dem_path = Path(args.dem)
    out_dir = Path(args.output_dir)

    logger.info("Loading DEM from %s", dem_path)
    dem_arr, profile = _load_dem_array(dem_path)

    with rasterio.open(dem_path) as src:
        cell_size_m = src.res[0]  # assume square pixels

    logger.info("Computing slope (cell size = %.1f m)...", cell_size_m)
    slope = compute_slope(dem_arr, cell_size_m)

    logger.info("Computing contributing area...")
    contrib_area = compute_contributing_area(dem_arr, cell_size_m)

    logger.info("Computing TWI...")
    twi = compute_twi(contrib_area, slope)

    logger.info("Computing HAND (stream threshold = %.0f m²)...", args.stream_threshold)
    hand = compute_hand(dem_arr, contrib_area, stream_threshold_m2=args.stream_threshold)

    logger.info("Resampling to 90 m and writing outputs...")
    _resample_to_90m(hand, profile, out_dir / "terrain_hand_90m.tif", Resampling.average)
    _resample_to_90m(twi, profile, out_dir / "terrain_twi_90m.tif", Resampling.average)
    _resample_to_90m(slope, profile, out_dir / "terrain_slope_90m.tif", Resampling.average)
    _resample_to_90m(
        contrib_area, profile, out_dir / "terrain_contrib_area_90m.tif", Resampling.max
    )

    logger.info("Terrain computation complete.")


if __name__ == "__main__":
    main()
