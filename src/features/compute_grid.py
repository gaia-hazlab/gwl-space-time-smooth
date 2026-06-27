"""
Define the canonical 90 m WA analysis grid and provide coordinate helpers.

The canonical grid is derived from the MERIT Hydro DEM reprojected to EPSG:5070
so that the interpolation grid is always pixel-aligned with the DEM secondary
variable.  All downstream scripts import from this module rather than re-deriving
the grid independently.

Usage:
    python -m src.features.compute_grid --dem data/raw/dem/merit_hydro_90m_5070.tif \
        --output-dir data/processed

Outputs:
    data/processed/conus_grid_90m.nc   ← NetCDF with X/Y coordinate arrays + metadata
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import NamedTuple

import numpy as np
import rasterio
import xarray as xr
from rasterio.crs import CRS
from rasterio.transform import AffineTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)
TARGET_RES_M = 90.0


class GridSpec(NamedTuple):
    """Canonical 90 m WA analysis grid specification (EPSG:5070)."""

    transform: rasterio.transform.Affine
    width: int
    height: int
    crs: CRS
    nodata: float

    @property
    def x_coords(self) -> np.ndarray:
        """Cell-centre X coordinates in EPSG:5070 (metres)."""
        left = self.transform.c + self.transform.a * 0.5  # pixel centre
        return left + np.arange(self.width) * self.transform.a

    @property
    def y_coords(self) -> np.ndarray:
        """Cell-centre Y coordinates in EPSG:5070 (metres, top-to-bottom)."""
        top = self.transform.f + self.transform.e * 0.5  # pixel centre (e is negative)
        return top + np.arange(self.height) * self.transform.e

    def prediction_dataframe(self) -> "pd.DataFrame":
        """
        Return a (width×height, 2) DataFrame with columns X, Y for every cell.

        The order is row-major (Y varies slowly, X varies fast), suitable for
        passing directly to ``gs.Gridding.prediction_grid`` helpers.
        """
        import pandas as pd

        xx, yy = np.meshgrid(self.x_coords, self.y_coords)
        return pd.DataFrame({"X": xx.ravel(), "Y": yy.ravel()})

    def unravel(self, flat_values: np.ndarray) -> np.ndarray:
        """Reshape a flat (height*width,) array back to (height, width)."""
        return flat_values.reshape(self.height, self.width)


def load_grid_spec(dem_path: Path) -> GridSpec:
    """
    Derive the canonical GridSpec from the MERIT Hydro DEM raster.

    Parameters
    ----------
    dem_path:
        Path to ``merit_hydro_90m_5070.tif``.

    Returns
    -------
    GridSpec
    """
    with rasterio.open(dem_path) as src:
        if src.crs.to_epsg() != 5070:
            raise ValueError(f"DEM CRS is {src.crs} — expected EPSG:5070. Re-run make dem.")
        return GridSpec(
            transform=src.transform,
            width=src.width,
            height=src.height,
            crs=src.crs,
            nodata=src.nodata if src.nodata is not None else -9999.0,
        )


def read_dem_array(dem_path: Path, grid: GridSpec) -> np.ndarray:
    """
    Load DEM elevation values as a masked 2-D float32 array (height × width).

    NoData cells are returned as NaN.

    Parameters
    ----------
    dem_path:
        Path to the 90 m EPSG:5070 DEM GeoTIFF.
    grid:
        GridSpec from :func:`load_grid_spec`.

    Returns
    -------
    np.ndarray, shape (height, width), dtype float32
    """
    with rasterio.open(dem_path) as src:
        arr = src.read(1, out_dtype=np.float32)
    arr[arr == grid.nodata] = np.nan
    return arr


def sample_dem_at_points(
    dem_path: Path,
    x_5070: np.ndarray,
    y_5070: np.ndarray,
) -> np.ndarray:
    """
    Sample DEM elevation at arbitrary EPSG:5070 point coordinates.

    Uses bilinear interpolation via rasterio index lookup.

    Parameters
    ----------
    dem_path:
        Path to the 90 m EPSG:5070 DEM GeoTIFF.
    x_5070, y_5070:
        1-D arrays of EPSG:5070 coordinates.

    Returns
    -------
    np.ndarray of shape (n,), dtype float32 — NaN where point falls outside DEM extent
    """
    with rasterio.open(dem_path) as src:
        coords = list(zip(x_5070.tolist(), y_5070.tolist()))
        values = np.array(
            [v[0] for v in src.sample(coords, indexes=1)],
            dtype=np.float32,
        )
        nd = src.nodata if src.nodata is not None else -9999.0
    values[values == nd] = np.nan
    return values


def save_grid_nc(grid: GridSpec, output_path: Path) -> None:
    """
    Write a lightweight NetCDF with X/Y coordinate arrays and grid metadata.

    This is used for documentation and by downstream scripts that want grid
    metadata without opening the full DEM.

    Parameters
    ----------
    grid:
        Canonical GridSpec.
    output_path:
        Destination ``conus_grid_90m.nc``.
    """
    ds = xr.Dataset(
        coords={
            "x": ("x", grid.x_coords.astype(np.float64), {"units": "m", "crs": "EPSG:5070", "axis": "X"}),
            "y": ("y", grid.y_coords.astype(np.float64), {"units": "m", "crs": "EPSG:5070", "axis": "Y"}),
        },
        attrs={
            "title": "Canonical CONUS 90 m analysis grid",
            "crs": "EPSG:5070 (NAD83 / Conus Albers)",
            "resolution_m": TARGET_RES_M,
            "width": grid.width,
            "height": grid.height,
            "transform": str(grid.transform),
        },
    )
    ds.to_netcdf(output_path)
    logger.info(f"Grid metadata saved: {output_path}  ({grid.width} × {grid.height})")


def build_grid_from_bbox(
    left: float,
    bottom: float,
    right: float,
    top: float,
    res_m: float = TARGET_RES_M,
) -> GridSpec:
    """
    Build a GridSpec directly from EPSG:5070 bounding-box coordinates.

    This does not require the DEM to be downloaded and is the preferred way to
    define a sub-CONUS (e.g. regional pilot) grid when the full DEM mosaic is
    not yet available.

    Parameters
    ----------
    left, bottom, right, top:
        Bounding box in EPSG:5070 metres (NAD83 CONUS Albers).
    res_m:
        Pixel resolution in metres (default: 1000 m = 90 m).

    Returns
    -------
    GridSpec
    """
    from rasterio.transform import from_bounds

    width = int(round((right - left) / res_m))
    height = int(round((top - bottom) / res_m))
    transform = from_bounds(left, bottom, right, top, width, height)
    return GridSpec(
        transform=transform,
        width=width,
        height=height,
        crs=TARGET_CRS,
        nodata=-9999.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build canonical 90 m grid from MERIT Hydro DEM or a bounding box",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # CONUS grid from DEM\n"
            "  python -m src.features.compute_grid --dem data/raw/dem/merit_hydro_90m_5070.tif\n\n"
            "  # PNW regional grid from bbox (no DEM needed)\n"
            "  python -m src.features.compute_grid \\\n"
            "    --bbox -2334000 2467000 -1103000 2998000 --output-dir data/processed"
        ),
    )
    parser.add_argument(
        "--dem",
        type=Path,
        default=None,
        help="Path to MERIT Hydro 90 m EPSG:5070 DEM. Mutually exclusive with --bbox.",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"),
        default=None,
        help=(
            "Bounding box in EPSG:5070 metres: left bottom right top. "
            "Use instead of --dem to build a regional grid without the full mosaic."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory for grid .nc output.",
    )
    parser.add_argument(
        "--output-name",
        type=str,
        default=None,
        help="Output filename (default: conus_grid_90m.nc or bbox_grid_90m.nc).",
    )
    args = parser.parse_args()

    if args.dem is None and args.bbox is None:
        parser.error("Provide either --dem or --bbox.")
    if args.dem is not None and args.bbox is not None:
        parser.error("--dem and --bbox are mutually exclusive.")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.dem is not None:
        if not args.dem.exists():
            raise FileNotFoundError(f"DEM not found: {args.dem}. Run `make dem` first.")
        grid = load_grid_spec(args.dem)
        out_name = args.output_name or "conus_grid_90m.nc"
    else:
        left, bottom, right, top = args.bbox
        grid = build_grid_from_bbox(left, bottom, right, top)
        out_name = args.output_name or "bbox_grid_90m.nc"

    logger.info(f"Grid: {grid.width} × {grid.height} px at {TARGET_RES_M} m, EPSG:5070")
    save_grid_nc(grid, args.output_dir / out_name)


if __name__ == "__main__":
    main()
