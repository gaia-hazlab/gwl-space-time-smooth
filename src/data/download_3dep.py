"""Download 3DEP 10 m DEM for a PNW bounding box via py3dep.

Replaces download_dem.py (MERIT Hydro). Outputs:
  data/raw/dem/3dep_10m_5070.tif  — 10 m, EPSG:5070
  data/raw/dem/3dep_1km_5070.tif  — resampled 1 km (for LightGBM feature stack)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import py3dep
import rasterio
from pyproj import CRS
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import box

logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)
TARGET_RES_10M = 10.0
TARGET_RES_1KM = 1000.0
NODATA = -9999.0

# PNW pilot bbox: west, south, east, north (WGS84)
PNW_BBOX_WGS84 = (-124.9, 42.0, -116.5, 49.0)


def _download_dem(bbox_wgs84: tuple[float, float, float, float]) -> "xr.DataArray":
    """Download 3DEP 1/3 arc-sec DEM for the given WGS84 bbox via py3dep."""
    west, south, east, north = bbox_wgs84
    geom = box(west, south, east, north)
    logger.info("Requesting 3DEP DEM for bbox %s", bbox_wgs84)
    dem = py3dep.get_map("DEM", geom, resolution=10, geo_crs="EPSG:4326")
    logger.info("Downloaded: shape=%s crs=%s", dem.shape, dem.rio.crs)
    return dem


def _reproject_to_5070(dem_da: "xr.DataArray", output_path: Path) -> None:
    """Reproject a rioxarray DataArray to EPSG:5070 and write as GeoTIFF."""
    import rioxarray  # noqa: F401

    dem_5070 = dem_da.rio.reproject("EPSG:5070", resampling=Resampling.bilinear)
    dem_5070 = dem_5070.where(dem_5070 != dem_5070.rio.nodata, other=NODATA)
    dem_5070.rio.write_nodata(NODATA, inplace=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dem_5070.rio.to_raster(
        output_path,
        driver="GTiff",
        compress="LZW",
        tiled=True,
        blockxsize=512,
        blockysize=512,
        dtype="float32",
    )
    logger.info("Wrote 10 m DEM → %s", output_path)


def _resample_to_1km(src_path: Path, dst_path: Path) -> None:
    """Resample 10 m EPSG:5070 raster to 1 km using bilinear resampling."""
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs,
            src.crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=TARGET_RES_1KM,
        )
        profile = src.profile.copy()
        profile.update(
            {
                "transform": transform,
                "width": width,
                "height": height,
                "nodata": NODATA,
                "dtype": "float32",
                "compress": "LZW",
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            }
        )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=src.crs,
                resampling=Resampling.bilinear,
            )
    logger.info("Resampled to 1 km → %s", dst_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download 3DEP 10 m DEM for PNW.")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=list(PNW_BBOX_WGS84),
        help="WGS84 bounding box (default: PNW pilot)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/dem"),
        help="Output directory",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    bbox = tuple(args.bbox)
    output_dir = Path(args.output_dir)
    path_10m = output_dir / "3dep_10m_5070.tif"
    path_1km = output_dir / "3dep_1km_5070.tif"

    dem_da = _download_dem(bbox)
    _reproject_to_5070(dem_da, path_10m)
    _resample_to_1km(path_10m, path_1km)
    logger.info("3DEP download complete.")


if __name__ == "__main__":
    main()
