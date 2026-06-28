"""Fetch GAIA DataHub layers from s3://cresst via odc.stac (the GAIA CLI downloader).

Sub-commands:
  solus    — SOLUS100 soil properties (clay, Ksat, sand, pH, bulk density), 100 m
  prism    — PRISM monthly precipitation (2000-present)
  vs30       — Vs30 near-surface stiffness (Sanger & Maurer 2025 parametric model)
  polaris    — POLARIS soil hydraulics (Ksat, clay, sand), 30 m — drop-in for --solus
  dtb        — depth to bedrock (GAIA subsurface reanalysis)
  lithology  — standardized lithology classes (WA DNR geology + USGS SGMC); for #2 domains
  dist_coast — distance to marine coast (m); for the coastal domain + sea-level boundary

All gridded covariates are delivered on the 90 m EPSG:5070 WA grid, ready for the
observation-anchored Stage 1 model (src/models/baseline_regression.py). vs30 and dtb
write the optional-covariate GeoTIFFs the baseline auto-detects
(vs30_90m.tif, depth_to_bedrock_90m.tif).

Usage:
  python -m src.data.fetch_gaia solus   --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
  python -m src.data.fetch_gaia vs30    --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
  python -m src.data.fetch_gaia polaris --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
  python -m src.data.fetch_gaia dtb     --bbox -124.9 42.0 -116.5 49.0 --output-dir data/processed
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

# Canonical analysis-grid resolution (matches src/features/compute_grid.TARGET_RES_M)
TARGET_RES_M = 90.0

# GAIA STAC catalog endpoints (update when catalog URLs are finalised)
SOLUS_STAC_URL = "https://gaia-hazlab.github.io/solus-stac/catalog.json"
PRISM_STAC_URL = "https://gaia-hazlab.github.io/prism-stac/catalog.json"
VS_STAC_URL = "https://gaia-hazlab.github.io/vs-stac/catalog.json"
POLARIS_STAC_URL = "https://gaia-hazlab.github.io/polaris-stac/catalog.json"
SUBSURFACE_STAC_URL = "https://gaia-hazlab.github.io/subsurface-stac/catalog.json"
LITHOLOGY_STAC_URL = "https://gaia-hazlab.github.io/lithology-stac/catalog.json"
COASTLINE_STAC_URL = "https://gaia-hazlab.github.io/coastline-stac/catalog.json"

# SOLUS100 band names → output variable names
SOLUS_BAND_MAP = {
    "clay_0_5cm_mean": "clay_pct",
    "ksat_0_5cm_mean": "ksat_cm_hr",
    "sand_0_5cm_mean": "sand_pct",
    "phh2o_0_5cm_mean": "ph",
    "bdod_0_5cm_mean": "bulk_density",
}

# POLARIS band names → output variable names (POLARIS 0–5 cm mean layer).
# NOTE: POLARIS ksat is stored as log10(cm/hr); converted to cm/hr below.
POLARIS_BAND_MAP = {
    "ksat_mean_0_5": "ksat_cm_hr",
    "clay_mean_0_5": "clay_pct",
    "sand_mean_0_5": "sand_pct",
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
                resolution=TARGET_RES_M,
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


def _bbox_5070(bbox_wgs84: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Reproject a WGS84 (w, s, e, n) bbox to EPSG:5070 (minx, miny, maxx, maxy)."""
    import pyproj
    from shapely.geometry import box
    from shapely.ops import transform as shp_transform

    project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    west, south, east, north = bbox_wgs84
    return shp_transform(project, box(west, south, east, north)).bounds


def _load_layer(
    stac_url: str,
    collection: str,
    bands: list[str],
    s3_zarr: str,
    bbox_wgs84: tuple[float, float, float, float],
    resolution: float = TARGET_RES_M,
    resampling: str = "bilinear",
    rename: dict[str, str] | None = None,
) -> xr.Dataset:
    """Load a GAIA DataHub layer onto the 90 m EPSG:5070 grid.

    Primary path: GAIA STAC + odc.stac.load (regrids on read). Falls back to a
    direct s3 Zarr read clipped to the bbox and interpolated to ``resolution``.
    """
    try:
        import odc.stac
        import pystac_client

        logger.info("Searching %s STAC: %s", collection, stac_url)
        catalog = pystac_client.Client.open(stac_url)
        items = list(catalog.search(bbox=list(bbox_wgs84), collections=[collection]).items())
        if not items:
            raise RuntimeError(f"No {collection} items found for bbox {bbox_wgs84}")
        ds = odc.stac.load(
            items, bands=bands, crs="EPSG:5070", resolution=resolution,
            resampling=resampling, chunks={"x": 512, "y": 512},
        )
    except Exception as exc:
        logger.warning("STAC fetch for %s failed (%s); trying direct s3 Zarr read.",
                       collection, exc)
        import s3fs

        fs = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
        full = xr.open_zarr(fs.get_mapper(s3_zarr), consolidated=True)
        minx, miny, maxx, maxy = _bbox_5070(bbox_wgs84)
        sub = full.sel(x=slice(minx, maxx), y=slice(maxy, miny))
        # Resample to the target 90 m grid.
        tx = np.arange(minx, maxx, resolution)
        ty = np.arange(maxy, miny, -resolution)
        ds = sub.interp(x=tx, y=ty, method="linear")
        if bands:
            ds = ds[[b for b in bands if b in ds]]

    if rename:
        ds = ds.rename({k: v for k, v in rename.items() if k in ds})
    if "time" in ds.dims:
        ds = ds.isel(time=0, drop=True)
    return ds


def _write_da_geotiff(da: xr.DataArray, output_path: Path, nodata: float = -9999.0) -> None:
    """Write a 2D (y, x) EPSG:5070 DataArray as a north-up float32 GeoTIFF."""
    import rasterio
    from rasterio.transform import from_origin

    da = da.sortby("y", ascending=False).sortby("x")
    x = da["x"].values
    y = da["y"].values
    dx = abs(float(x[1] - x[0]))
    dy = abs(float(y[0] - y[1]))
    transform = from_origin(float(x[0]) - dx / 2, float(y[0]) + dy / 2, dx, dy)

    arr = np.where(np.isnan(da.values), nodata, da.values).astype(np.float32)
    profile = dict(
        driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype="float32", crs="EPSG:5070", transform=transform, nodata=nodata,
        compress="LZW", tiled=True, blockxsize=256, blockysize=256,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(arr, 1)


def fetch_vs30(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path,
    resolution: float = TARGET_RES_M,
) -> Path:
    """Fetch Vs30 (Sanger & Maurer 2025 parametric model) → vs30_90m.tif.

    Vs30 is the near-surface stiffness field shared with the Sanger & Maurer
    liquefaction GLM, so using it as a Stage 1 predictor keeps the two models
    physically consistent.
    """
    ds = _load_layer(
        VS_STAC_URL, "vs30", ["vs30"],
        "s3://cresst/vs-stac/vs30_conus.zarr", bbox_wgs84, resolution,
    )
    da = ds["vs30"] if "vs30" in ds else ds[list(ds.data_vars)[0]]
    out = Path(output_dir) / "vs30_90m.tif"
    _write_da_geotiff(da, out)
    logger.info("Vs30 → %s", out)
    return out


def fetch_polaris(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path,
    resolution: float = TARGET_RES_M,
) -> Path:
    """Fetch POLARIS soil hydraulics (30 m) → polaris_wa.zarr (drop-in for --solus).

    Writes ksat_cm_hr / clay_pct / sand_pct on the 90 m grid using the same
    variable names as the SOLUS100 store, so baseline_regression.py can consume
    it directly via ``--solus polaris_wa.zarr``.
    """
    ds = _load_layer(
        POLARIS_STAC_URL, "polaris", list(POLARIS_BAND_MAP.keys()),
        "s3://cresst/polaris-stac/polaris_conus.zarr", bbox_wgs84, resolution,
        rename=POLARIS_BAND_MAP,
    )
    # POLARIS ksat is stored as log10(cm/hr); convert to cm/hr to match SOLUS.
    if "ksat_cm_hr" in ds:
        ds["ksat_cm_hr"] = 10.0 ** ds["ksat_cm_hr"]
    out = Path(output_dir) / "polaris_wa.zarr"
    out.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Writing POLARIS (drop-in for --solus) → %s", out)
    ds.to_zarr(out, mode="w", consolidated=True)
    return out


def fetch_dtb(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path,
    resolution: float = TARGET_RES_M,
) -> Path:
    """Fetch depth-to-bedrock (GAIA subsurface reanalysis) → depth_to_bedrock_90m.tif."""
    ds = _load_layer(
        SUBSURFACE_STAC_URL, "depth-to-bedrock", ["dtb"],
        "s3://cresst/subsurface-stac/depth_to_bedrock_conus.zarr", bbox_wgs84, resolution,
    )
    da = ds["dtb"] if "dtb" in ds else ds[list(ds.data_vars)[0]]
    out = Path(output_dir) / "depth_to_bedrock_90m.tif"
    _write_da_geotiff(da, out)
    logger.info("Depth to bedrock → %s", out)
    return out


def fetch_lithology(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path,
    resolution: float = TARGET_RES_M,
) -> Path:
    """Fetch the standardized lithology raster → lithology_90m.tif.

    Categorical layer (0 unconsolidated, 1 fractured-bedrock, 2 young-volcanic, 3 CRBG)
    staged in the GAIA DataHub from WA DNR surface geology + USGS SGMC by the
    gaia-data-downloaders ``Geology_Shoreline_Downloader`` notebook. Consumed directly by
    ``src.features.hydrogeologic_domains`` (issue #2). Nearest-neighbour resampling — never
    interpolate class codes.
    """
    ds = _load_layer(
        LITHOLOGY_STAC_URL, "lithology", ["lithology"],
        "s3://cresst/lithology-stac/lithology_wa.zarr", bbox_wgs84, resolution,
        resampling="nearest",
    )
    da = ds["lithology"] if "lithology" in ds else ds[list(ds.data_vars)[0]]
    out = Path(output_dir) / "lithology_90m.tif"
    _write_da_geotiff(da, out, nodata=255.0)
    logger.info("Lithology → %s", out)
    return out


def fetch_dist_coast(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path,
    resolution: float = TARGET_RES_M,
) -> Path:
    """Fetch distance-to-marine-coast (m) → dist_coast_90m.tif.

    Derived in the DataHub from a marine shoreline (NOAA medium-resolution shoreline in
    production; WA DNR 'Water' polygons in the demo notebook) via a distance transform.
    Drives the ``coastal`` domain (#2) and the sea-level boundary condition (#10).
    """
    ds = _load_layer(
        COASTLINE_STAC_URL, "dist-coast", ["dist_coast_m"],
        "s3://cresst/coastline-stac/dist_coast_conus.zarr", bbox_wgs84, resolution,
    )
    da = ds["dist_coast_m"] if "dist_coast_m" in ds else ds[list(ds.data_vars)[0]]
    out = Path(output_dir) / "dist_coast_90m.tif"
    _write_da_geotiff(da, out)
    logger.info("Distance to coast → %s", out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GAIA DataHub layers from s3://cresst.")
    sub = parser.add_subparsers(dest="command", required=True)

    for cmd in ("solus", "prism", "vs30", "polaris", "dtb", "lithology", "dist_coast"):
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
    elif args.command == "vs30":
        fetch_vs30(bbox, out)
    elif args.command == "polaris":
        fetch_polaris(bbox, out)
    elif args.command == "dtb":
        fetch_dtb(bbox, out)
    elif args.command == "lithology":
        fetch_lithology(bbox, out)
    elif args.command == "dist_coast":
        fetch_dist_coast(bbox, out)


if __name__ == "__main__":
    main()
