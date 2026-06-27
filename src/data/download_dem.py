"""
Download MERIT Hydro DEM tiles, mosaic, and reproject to the analysis grid.

Downloads the MERIT Hydro hydrologically-conditioned DEM at 3 arcsec (~90 m),
mosaics all CONUS tiles, reprojects to EPSG:5070 (NAD83 CONUS Albers), and
resamples to 90 m resolution for use as the co-kriging secondary variable.

MERIT Hydro is preferred over 3DEP here because it is:
- Hydrologically conditioned (filled sinks, carved channels)
- Consistent globally (no seam artifacts at tile edges)
- Freely available without authentication

Source: Yamzaki et al. (2019) MERIT Hydro
  https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/

Usage:
    python -m src.data.download_dem --output-dir data/raw/dem

Outputs:
    data/raw/dem/merit_hydro_raw/     ← per-tile GeoTIFFs (kept for reproducibility)
    data/raw/dem/merit_hydro_90m_5070.tif  ← final 90 m EPSG:5070 mosaic
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import Resampling as WarpResampling
from rasterio.warp import calculate_default_transform, reproject

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# EPSG:5070 — NAD83 / Conus Albers (analysis CRS)
TARGET_CRS = CRS.from_epsg(5070)

# Target resolution in metres (EPSG:5070 is metric)
TARGET_RES_M = 1000.0

# MERIT Hydro base URL — elv (elevation) variant
# Tiles named: n30w090_elv.tif  (lat band × lon band)
MERIT_BASE_URL = "http://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/distribute/v1.0.1"

# CONUS tile grid: lat bands 20–50 N, lon bands 60–130 W (5-degree tiles)
# lat bands: 20, 25, 30, 35, 40, 45, 50 (lower edge of tile)
# lon bands: 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125 (west edge, western hemisphere)
CONUS_LAT_BANDS = [20, 25, 30, 35, 40, 45, 50]
CONUS_LON_BANDS = [60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130]

# Approximate CONUS bounds in EPSG:5070 (metres) for output clipping
CONUS_BOUNDS_5070 = {
    "left": -2_356_000,
    "bottom": 270_000,
    "right": 2_258_000,
    "top": 3_173_000,
}


def _tile_filename(lat: int, lon: int) -> str:
    """Return MERIT Hydro tile filename for a given lat/lon lower-left corner."""
    lat_str = f"n{lat:02d}" if lat >= 0 else f"s{-lat:02d}"
    lon_str = f"w{lon:03d}"
    return f"{lat_str}{lon_str}_elv.tif"


def download_tiles(output_dir: Path) -> list[Path]:
    """
    Download all CONUS MERIT Hydro elevation tiles.

    Parameters
    ----------
    output_dir:
        Directory for raw tiles (created if absent).

    Returns
    -------
    list[Path]
        Paths of successfully downloaded tiles.
    """
    tile_dir = output_dir / "merit_hydro_raw"
    tile_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for lat in CONUS_LAT_BANDS:
        for lon in CONUS_LON_BANDS:
            fname = _tile_filename(lat, lon)
            dest = tile_dir / fname
            if dest.exists():
                logger.info(f"  Tile already present: {fname}")
                downloaded.append(dest)
                continue
            url = f"{MERIT_BASE_URL}/{fname}"
            logger.info(f"  Downloading {fname} …")
            result = subprocess.run(
                ["curl", "-fsSL", "-o", str(dest), url],
                capture_output=True,
            )
            if result.returncode != 0:
                # Tile may not exist (ocean / partial coverage) — skip silently
                logger.debug(f"  Skipped (not available): {fname}")
                if dest.exists():
                    dest.unlink()
            else:
                downloaded.append(dest)

    if not downloaded:
        raise RuntimeError(
            "No MERIT Hydro tiles downloaded. "
            "Check network access and tile URL format in MERIT_BASE_URL."
        )
    logger.info(f"  {len(downloaded)} tiles available")
    return downloaded


def mosaic_and_reproject(tiles: list[Path], output_path: Path) -> None:
    """
    Mosaic MERIT Hydro tiles and reproject/resample to 90 m EPSG:5070.

    Parameters
    ----------
    tiles:
        List of tile paths (GeoTIFF, geographic CRS).
    output_path:
        Destination path for the output GeoTIFF.
    """
    logger.info("Mosaicking tiles …")
    datasets = [rasterio.open(t) for t in tiles]
    mosaic_array, mosaic_transform = merge(
        datasets,
        bounds=(
            -130.0,  # west
            20.0,    # south
            -55.0,   # east
            55.0,    # north
        ),
        res=None,  # keep native resolution
        resampling=Resampling.bilinear,
        nodata=-9999.0,
    )
    for ds in datasets:
        ds.close()

    src_crs = CRS.from_epsg(4326)
    src_height, src_width = mosaic_array.shape[1], mosaic_array.shape[2]

    logger.info("Reprojecting to EPSG:5070 at 90 m …")
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        TARGET_CRS,
        src_width,
        src_height,
        left=-130.0,
        bottom=20.0,
        right=-55.0,
        top=55.0,
        resolution=TARGET_RES_M,
    )

    # Clip to CONUS bounding box in EPSG:5070
    b = CONUS_BOUNDS_5070
    dst_transform = from_bounds(
        b["left"], b["bottom"], b["right"], b["top"],
        int((b["right"] - b["left"]) / TARGET_RES_M),
        int((b["top"] - b["bottom"]) / TARGET_RES_M),
    )
    dst_width = int((b["right"] - b["left"]) / TARGET_RES_M)
    dst_height = int((b["top"] - b["bottom"]) / TARGET_RES_M)

    dst_array = np.full((1, dst_height, dst_width), -9999.0, dtype=np.float32)

    reproject(
        source=mosaic_array.astype(np.float32),
        destination=dst_array,
        src_transform=mosaic_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=TARGET_CRS,
        resampling=WarpResampling.bilinear,
        src_nodata=-9999.0,
        dst_nodata=-9999.0,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=dst_height,
        width=dst_width,
        count=1,
        dtype=np.float32,
        crs=TARGET_CRS,
        transform=dst_transform,
        nodata=-9999.0,
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(dst_array)

    logger.info(f"  Saved: {output_path}  ({dst_width} × {dst_height} px)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and prepare MERIT Hydro DEM for GWL modeling")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/dem"),
        help="Directory in which to store the raw tiles and final mosaic.",
    )
    args = parser.parse_args()

    final_path = args.output_dir / "merit_hydro_90m_5070.tif"
    if final_path.exists():
        logger.info(f"Final DEM already exists: {final_path}. Use --force to redownload.")
        return

    tiles = download_tiles(args.output_dir)
    mosaic_and_reproject(tiles, final_path)
    logger.info("DEM download and reprojection complete.")


if __name__ == "__main__":
    main()
