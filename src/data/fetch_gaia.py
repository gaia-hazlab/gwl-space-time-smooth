"""Fetch GAIA data from s3://cresst via odc.stac.

Sub-commands:
  solus   — SOLUS100 soil properties (clay, Ksat, pH, bulk density)
  prism   — PRISM monthly precipitation (2000-present)

Usage:
  python -m src.data.fetch_gaia solus --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
  python -m src.data.fetch_gaia prism --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

# PNW pilot bbox: west, south, east, north (WGS84)
PNW_BBOX_WGS84 = (-124.9, 42.0, -116.5, 49.0)

# GAIA STAC catalog endpoints (update when catalog URLs are finalised)
SOLUS_STAC_URL = "https://gaia-hazlab.github.io/solus-stac/catalog.json"
PRISM_STAC_URL = "https://gaia-hazlab.github.io/prism-stac/catalog.json"

# SOLUS100 band names → output variable names
SOLUS_BAND_MAP = {
    "clay_0_5cm_mean": "clay_pct",
    "ksat_0_5cm_mean": "ksat_cm_hr",
    "phh2o_0_5cm_mean": "ph",
    "bdod_0_5cm_mean": "bulk_density",
}


def fetch_solus100(
    bbox_wgs84: tuple[float, float, float, float],
    output_dir: Path,
) -> Path:
    """Load SOLUS100 soil properties from s3://cresst and write to Zarr.

    Falls back to a direct s3 Zarr read if the STAC catalog is unavailable.

    Parameters
    ----------
    bbox_wgs84:
        (west, south, east, north) in WGS84.
    output_dir:
        Directory for output Zarr.

    Returns
    -------
    Path
        Path to written Zarr store.
    """
    try:
        import odc.stac
        import pystac_client

        logger.info("Searching SOLUS100 STAC catalog: %s", SOLUS_STAC_URL)
        catalog = pystac_client.Client.open(SOLUS_STAC_URL)
        items = list(
            catalog.search(bbox=list(bbox_wgs84), collections=["solus100"]).items()
        )
        if not items:
            raise RuntimeError("No SOLUS100 items found for bbox %s" % str(bbox_wgs84))

        bands = list(SOLUS_BAND_MAP.keys())
        ds = odc.stac.load(
            items,
            bands=bands,
            crs="EPSG:5070",
            resolution=100,
            chunks={"x": 512, "y": 512},
        )
        ds = ds.rename(SOLUS_BAND_MAP)

    except Exception as exc:
        logger.warning("STAC fetch failed (%s); trying direct s3 Zarr read.", exc)
        import s3fs

        fs = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
        store = fs.get_mapper("s3://cresst/solus-stac/solus100_conus.zarr")
        full = xr.open_zarr(store, consolidated=True)

        # Clip to bbox
        import pyproj
        from shapely.geometry import box
        from shapely.ops import transform as shp_transform

        project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        west, south, east, north = bbox_wgs84
        bbox_5070 = shp_transform(project, box(west, south, east, north)).bounds
        ds = full.sel(
            x=slice(bbox_5070[0], bbox_5070[2]),
            y=slice(bbox_5070[3], bbox_5070[1]),
        )
        # Rename to standard variable names if needed
        rename = {k: v for k, v in SOLUS_BAND_MAP.items() if k in ds}
        if rename:
            ds = ds.rename(rename)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "solus100_wa.zarr"
    logger.info("Writing SOLUS100 → %s", out_path)
    ds.to_zarr(out_path, mode="w", consolidated=True)
    logger.info("SOLUS100 written: %s", out_path)
    return out_path


def fetch_prism(
    bbox_wgs84: tuple[float, float, float, float],
    output_dir: Path,
    start: str = "2000-01-01",
    end: str | None = None,
) -> Path:
    """Load PRISM monthly precipitation from s3://cresst and write to Zarr.

    Also writes prism_mean_annual_ppt_wa.tif (long-term mean annual precipitation,
    resampled to 90 m EPSG:5070) as a static covariate for the random forest.

    Parameters
    ----------
    bbox_wgs84:
        (west, south, east, north) in WGS84.
    output_dir:
        Directory for Zarr and GeoTIFF outputs.
    start:
        ISO start date for monthly time series.
    end:
        ISO end date (defaults to today).

    Returns
    -------
    Path
        Path to monthly Zarr store.
    """
    import pandas as pd

    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    try:
        import odc.stac
        import pystac_client

        logger.info("Searching PRISM STAC catalog: %s", PRISM_STAC_URL)
        catalog = pystac_client.Client.open(PRISM_STAC_URL)
        items = list(
            catalog.search(
                bbox=list(bbox_wgs84),
                collections=["prism-monthly-ppt"],
                datetime=f"{start}/{end}",
            ).items()
        )
        if not items:
            raise RuntimeError("No PRISM items found")

        ds = odc.stac.load(
            items,
            bands=["ppt"],
            crs="EPSG:5070",
            resolution=4000,
            chunks={"time": 12, "x": 256, "y": 256},
        )

    except Exception as exc:
        logger.warning("PRISM STAC fetch failed (%s); trying direct s3 Zarr read.", exc)
        import s3fs

        fs = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
        store = fs.get_mapper("s3://cresst/prism-stac/prism_monthly_conus.zarr")
        full = xr.open_zarr(store, consolidated=True)
        # Time and spatial clip
        import pyproj
        from shapely.geometry import box
        from shapely.ops import transform as shp_transform

        project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        west, south, east, north = bbox_wgs84
        bbox_5070 = shp_transform(project, box(west, south, east, north)).bounds
        ds = full.sel(
            x=slice(bbox_5070[0], bbox_5070[2]),
            y=slice(bbox_5070[3], bbox_5070[1]),
            time=slice(start, end),
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write monthly Zarr
    out_monthly = output_dir / "prism_monthly_wa.zarr"
    logger.info("Writing PRISM monthly → %s", out_monthly)
    ds.to_zarr(out_monthly, mode="w", consolidated=True)

    # Write long-term mean annual GeoTIFF as static covariate
    _write_mean_annual_ppt(ds, output_dir / "prism_mean_annual_ppt_wa.tif")

    return out_monthly


def _write_mean_annual_ppt(ds: xr.Dataset, output_path: Path) -> None:
    """Write long-term mean annual precipitation (mm/yr) as 1 km COG."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import calculate_default_transform, reproject

    # Sum 12 months → annual, then mean across years
    ppt = ds["ppt"] if "ppt" in ds else ds[list(ds.data_vars)[0]]
    annual = ppt.resample(time="YE").sum("time")
    mean_annual = annual.mean("time").values.astype(np.float32)

    # Write at native resolution then resample to 90 m
    import tempfile, os
    y_vals = ds["y"].values if "y" in ds.coords else ds.coords[list(ds.coords)[0]].values
    x_vals = ds["x"].values if "x" in ds.coords else ds.coords[list(ds.coords)[1]].values
    dy = float(y_vals[1] - y_vals[0]) if len(y_vals) > 1 else 4000.0
    dx = float(x_vals[1] - x_vals[0]) if len(x_vals) > 1 else 4000.0
    from rasterio.transform import from_origin
    transform = from_origin(float(x_vals[0]) - dx / 2, float(y_vals[0]) - dy / 2, abs(dx), abs(dy))

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with rasterio.open(
            tmp_path, "w", driver="GTiff", height=mean_annual.shape[-2],
            width=mean_annual.shape[-1], count=1, dtype="float32",
            crs="EPSG:5070", transform=transform, nodata=-9999.0,
        ) as src_ds:
            src_ds.write(np.where(np.isnan(mean_annual), -9999.0, mean_annual), 1)

        with rasterio.open(tmp_path) as src_ds:
            dst_t, dst_w, dst_h = calculate_default_transform(
                src_ds.crs, src_ds.crs, src_ds.width, src_ds.height, *src_ds.bounds,
                resolution=1000.0,
            )
            profile = src_ds.profile.copy()
            profile.update(transform=dst_t, width=dst_w, height=dst_h, compress="LZW",
                           tiled=True, blockxsize=256, blockysize=256)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(output_path, "w", **profile) as dst_ds:
                reproject(rasterio.band(src_ds, 1), rasterio.band(dst_ds, 1),
                          src_transform=src_ds.transform, src_crs=src_ds.crs,
                          dst_transform=dst_t, dst_crs=src_ds.crs,
                          resampling=Resampling.average)
    finally:
        os.unlink(tmp_path)
    logger.info("Mean annual ppt → %s", output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GAIA data from s3://cresst.")
    sub = parser.add_subparsers(dest="command", required=True)

    for cmd in ("solus", "prism"):
        p = sub.add_parser(cmd)
        p.add_argument("--bbox", nargs=4, type=float,
                       metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                       default=list(PNW_BBOX_WGS84))
        p.add_argument("--output-dir", type=Path, default=Path("data/processed"))
        if cmd == "prism":
            p.add_argument("--start", default="2000-01-01")
            p.add_argument("--end", default=None)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bbox = tuple(args.bbox)
    out = Path(args.output_dir)

    if args.command == "solus":
        fetch_solus100(bbox, out)
    elif args.command == "prism":
        fetch_prism(bbox, out, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
