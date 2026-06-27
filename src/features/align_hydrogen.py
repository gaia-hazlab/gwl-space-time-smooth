"""
Reproject and align the Ma 2025 HydroGEN water table depth rasters to the
canonical PNW 90 m analysis grid (EPSG:5070).

Two input rasters (WGS84) are expected in ``data/comparison/``:

    WT2-ma_wtd_50.tif              — median water table depth (m below surface)
    wtd_uncertainty_mosaic_wgs84.tif — ensemble spread (same units; confirm σ vs IQR)

Outputs are written to ``data/processed/``:

    hydrogen_wtd_prior_90m.tif       — median WTD on the PNW 90 m grid, EPSG:5070
    hydrogen_wtd_uncertainty_90m.tif — uncertainty on same grid

Both outputs are float32, nodata = -9999.0, CRS = EPSG:5070.

Usage:
    python -m src.features.align_hydrogen \\
        --wtd    data/comparison/WT2-ma_wtd_50.tif \\
        --unc    data/comparison/wtd_uncertainty_mosaic_wgs84.tif \\
        --grid   data/processed/bbox_grid_90m.nc \\
        --output-dir data/processed

If ``--grid`` is not supplied, ``--dem`` can be used instead to derive the grid
from the MERIT Hydro DEM (CONUS run).

Sign convention
---------------
The HydroGEN product stores water table *depth* (DTW, positive = below surface).
This module preserves that convention.  Negative values after reprojection
(rasterio bilinear artefacts near nodata borders) are clamped to zero.

Uncertainty interpretation
--------------------------
Ma et al. 2025 reports ensemble spread.  Whether it is σ or IQR is confirmed by
examining values at well locations in ``notebooks/02_hydrogen_eda.ipynb``.
A diagnostic log message reports the 50th-percentile uncertainty value; if
this is ~1.35× larger than expected σ, it is likely IQR.  The
``--scale-uncertainty`` flag applies an IQR→σ divisor of 1.35 if needed.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)
NODATA_OUT = np.float32(-9999.0)
IQR_TO_SIGMA = 1.0 / 1.35  # divisor to convert IQR → σ


def _load_grid_spec_from_nc(nc_path: Path):
    """Return (transform, width, height) from a grid .nc written by compute_grid."""
    import xarray as xr
    from rasterio.transform import from_bounds

    ds = xr.open_dataset(nc_path)
    x = ds["x"].values
    y = ds["y"].values
    width = len(x)
    height = len(y)
    # compute transform from cell-centre coordinates
    res = float(x[1] - x[0])  # pixel size (positive, metres)
    left = float(x[0]) - res / 2
    bottom = float(y[-1]) - res / 2  # y is top-down (decreasing); y[-1] is smallest
    right = float(x[-1]) + res / 2
    top = float(y[0]) + res / 2
    transform = from_bounds(left, bottom, right, top, width, height)
    ds.close()
    return transform, width, height


def _load_grid_spec_from_dem(dem_path: Path):
    """Return (transform, width, height) from the MERIT Hydro DEM GeoTIFF."""
    from src.features.compute_grid import load_grid_spec
    g = load_grid_spec(dem_path)
    return g.transform, g.width, g.height


def reproject_to_grid(
    src_path: Path,
    dst_transform: "rasterio.transform.Affine",
    dst_width: int,
    dst_height: int,
    resampling: Resampling = Resampling.bilinear,
    clamp_negative: bool = True,
    scale: float = 1.0,
) -> np.ndarray:
    """
    Reproject and resample a raster to the target EPSG:5070 grid.

    Parameters
    ----------
    src_path:
        Source GeoTIFF (any CRS; float32 expected).
    dst_transform:
        Affine transform of the destination grid.
    dst_width, dst_height:
        Pixel dimensions of the destination grid.
    resampling:
        Rasterio resampling algorithm.  Bilinear is appropriate for
        continuous fields; nearest-neighbour for categorical.
    clamp_negative:
        If True, values < 0 in the output are forced to 0 (physically, a
        negative water table depth is rare and likely a reprojection artefact
        near nodata borders).
    scale:
        Multiply the reprojected values by this factor before saving.  Use
        ``IQR_TO_SIGMA`` (0.741) when the source raster stores IQR.

    Returns
    -------
    np.ndarray, shape (dst_height, dst_width), float32.
    Cells outside the source extent are NaN (converted from NODATA_OUT).
    """
    dst_array = np.full((dst_height, dst_width), NODATA_OUT, dtype=np.float32)

    with rasterio.open(src_path) as src:
        src_nodata = src.nodata if src.nodata is not None else -9999.0
        logger.info(
            f"  Source: {src_path.name}  CRS={src.crs}  res={src.res}  "
            f"shape={src.shape}  nodata={src_nodata}"
        )
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src_nodata,
            dst_transform=dst_transform,
            dst_crs=TARGET_CRS,
            dst_nodata=float(NODATA_OUT),
            resampling=resampling,
        )

    out = dst_array.astype(np.float32)
    # Replace nodata sentinel with NaN for arithmetic; re-apply before saving
    nodata_mask = out == NODATA_OUT
    out[nodata_mask] = np.nan

    if clamp_negative:
        neg = (~nodata_mask) & (out < 0)
        if neg.sum() > 0:
            logger.debug(f"  Clamped {neg.sum():,} negative cells to 0 after reprojection")
        out[neg] = 0.0

    if scale != 1.0:
        out[~nodata_mask] *= scale

    # Stats
    valid = out[~np.isnan(out)]
    if len(valid):
        logger.info(
            f"  Output stats: n_valid={len(valid):,}  "
            f"min={valid.min():.2f}  median={np.median(valid):.2f}  "
            f"max={valid.max():.2f}  p50_unc={np.percentile(valid, 50):.2f}"
        )

    return out


def save_aligned_tif(
    array: np.ndarray,
    dst_transform: "rasterio.transform.Affine",
    dst_path: Path,
) -> None:
    """Write a float32 array to EPSG:5070 GeoTIFF, nodata = NODATA_OUT."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    out = np.where(np.isnan(array), NODATA_OUT, array).astype(np.float32)

    with rasterio.open(
        dst_path, "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=np.float32,
        crs=TARGET_CRS,
        transform=dst_transform,
        nodata=float(NODATA_OUT),
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(out, 1)
    logger.info(f"Saved: {dst_path}")


def align_hydrogen(
    wtd_path: Path,
    unc_path: Path,
    dst_transform: "rasterio.transform.Affine",
    dst_width: int,
    dst_height: int,
    output_dir: Path,
    scale_uncertainty: bool = False,
) -> dict[str, Path]:
    """
    Reproject both HydroGEN rasters to the target grid and save to output_dir.

    Parameters
    ----------
    wtd_path:
        Path to the median WTD GeoTIFF (``WT2-ma_wtd_50.tif``).
    unc_path:
        Path to the uncertainty GeoTIFF (``wtd_uncertainty_mosaic_wgs84.tif``).
    dst_transform, dst_width, dst_height:
        Target grid specification (EPSG:5070).
    output_dir:
        Where to write aligned TIFs.
    scale_uncertainty:
        If True, multiply uncertainty by ``IQR_TO_SIGMA`` (divide by 1.35)
        to convert from IQR to approximate 1σ.  Check the EDA notebook first.

    Returns
    -------
    dict with keys ``"wtd"`` and ``"unc"``, values = output Paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Aligning WTD prior …")
    wtd_arr = reproject_to_grid(
        wtd_path, dst_transform, dst_width, dst_height,
        clamp_negative=True, scale=1.0,
    )
    wtd_out = output_dir / "hydrogen_wtd_prior_90m.tif"
    save_aligned_tif(wtd_arr, dst_transform, wtd_out)

    unc_scale = IQR_TO_SIGMA if scale_uncertainty else 1.0
    if scale_uncertainty:
        logger.info(f"Scaling uncertainty by IQR→σ factor ({IQR_TO_SIGMA:.4f})")

    logger.info("Aligning uncertainty raster …")
    unc_arr = reproject_to_grid(
        unc_path, dst_transform, dst_width, dst_height,
        clamp_negative=True, scale=unc_scale,
    )
    unc_out = output_dir / "hydrogen_wtd_uncertainty_90m.tif"
    save_aligned_tif(unc_arr, dst_transform, unc_out)

    return {"wtd": wtd_out, "unc": unc_out}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Align HydroGEN Ma 2025 WTD rasters to the PNW 90 m EPSG:5070 grid",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--wtd",
        type=Path,
        default=Path("data/comparison/WT2-ma_wtd_50.tif"),
        help="Ma 2025 median WTD raster (WGS84)",
    )
    parser.add_argument(
        "--unc",
        type=Path,
        default=Path("data/comparison/wtd_uncertainty_mosaic_wgs84.tif"),
        help="Ma 2025 WTD uncertainty raster (WGS84)",
    )
    grid_group = parser.add_mutually_exclusive_group(required=True)
    grid_group.add_argument(
        "--grid",
        type=Path,
        default=None,
        help="bbox_grid_90m.nc or conus_grid_90m.nc from compute_grid",
    )
    grid_group.add_argument(
        "--dem",
        type=Path,
        default=None,
        help="MERIT Hydro 90 m EPSG:5070 DEM (alternative to --grid)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
    )
    parser.add_argument(
        "--scale-uncertainty",
        action="store_true",
        default=False,
        help="Divide uncertainty by 1.35 to convert from IQR to approximate 1σ",
    )
    args = parser.parse_args()

    for p in [args.wtd, args.unc]:
        if not p.exists():
            raise FileNotFoundError(
                f"Input raster not found: {p}. "
                "Copy from ~/Downloads/ to data/comparison/ first."
            )

    if args.grid is not None:
        if not args.grid.exists():
            raise FileNotFoundError(f"Grid file not found: {args.grid}. Run `make pilot-grid` first.")
        dst_transform, dst_width, dst_height = _load_grid_spec_from_nc(args.grid)
        logger.info(f"Target grid from {args.grid.name}: {dst_width} × {dst_height} px")
    else:
        if not args.dem.exists():
            raise FileNotFoundError(f"DEM not found: {args.dem}. Run `make dem` first.")
        dst_transform, dst_width, dst_height = _load_grid_spec_from_dem(args.dem)
        logger.info(f"Target grid from DEM: {dst_width} × {dst_height} px")

    outputs = align_hydrogen(
        wtd_path=args.wtd,
        unc_path=args.unc,
        dst_transform=dst_transform,
        dst_width=dst_width,
        dst_height=dst_height,
        output_dir=args.output_dir,
        scale_uncertainty=args.scale_uncertainty,
    )

    logger.info(f"WTD prior  → {outputs['wtd']}")
    logger.info(f"Uncertainty → {outputs['unc']}")
    logger.info(
        "Next: run notebooks/02_hydrogen_eda.ipynb to check sign convention "
        "and confirm whether uncertainty is σ or IQR. Use --scale-uncertainty if IQR."
    )


if __name__ == "__main__":
    main()
