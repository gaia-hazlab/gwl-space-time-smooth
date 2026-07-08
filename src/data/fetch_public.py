"""Fetch model covariates from their ORIGINAL public sources (GAIA-independent fallback).

The GAIA DataHub STAC endpoints (solus-stac, prism-stac, vs-stac, …) are not yet published,
so ``src.data.fetch_gaia`` cannot stage the covariates. This module pulls the same layers
directly from their authoritative public hosts, writing outputs byte-compatible with what
the models already consume — so the pipeline improves off its terrain-only floor today and
switches back to the DataHub with no code change once those endpoints go live.

Sources
-------
- **SOLUS100** (Soil Landscapes of the United States, 100 m, USDA-NRCS; Nauman et al. 2024):
  public cloud-optimized GeoTIFFs at ``https://storage.googleapis.com/solus100pub/``.
  Natively **EPSG:5070** — our analysis CRS — so no reprojection is needed. Read windowed
  via ``/vsicurl/`` (HTTP range requests), never the full CONUS COG.

Note: SOLUS100 does **not** publish saturated hydraulic conductivity (ksat); it is a
derived quantity. We fetch the *measured* SOLUS static soil-hydromechanical set — texture
(clay/sand/silt), pH, CEC, oven-dry bulk density, and depth-to-lithic (soil thickness) —
which is exactly the static set the LandLab landslide data-prep (``gaia-hazlab/landslide-data-prep``)
consumes. K_sat is then derived on demand and *modularly* by ``src.models.soil_hydraulics`` (choose
Saxton-Rawls, the LandLab pedotransfer, or a provided field), never silently synthesised here, so
our water-budget K_sat and LandLab's transmissivity can be held to the same pedotransfer.

Scaling caveat: pH / CEC / bulk-density SOLUS COGs may carry an embedded ``scale_factor``; we read
with ``mask_and_scale=True`` so any such scaling is applied. Confirm the returned magnitudes (pH ~4-8,
CEC in cmol(+) kg⁻¹, bulk density ~1.0-1.8 g cm⁻³) match the pedotransfer's expected units before use.

Usage
-----
    python -m src.data.fetch_public solus --bbox -122.6 47.2 -121.9 48.0 \
        --output-dir data/processed
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_RES_M = 90.0  # analysis-grid resolution (matches src.features.compute_grid)

SOLUS_BASE = "/vsicurl/https://storage.googleapis.com/solus100pub"
SOLUS_NODATA = 255  # uint8 percent fields

# PRISM 30-year (1991–2020) normals web service. date "14" = the annual normal; ppt in mm.
# res is "800m" (~30 arc-sec) or "4km". Returns a zip of the BIL raster (NAD83 geographic).
PRISM_NORMALS_URL = "https://services.nacse.org/prism/data/get/normals/us/{res}/ppt/14"

# SOLUS depth-resolved properties: short-name -> (output var, is_percent). All are the shared
# static soil-hydromechanical set consumed by both our water budget and LandLab's Factor-of-Safety.
SOLUS_PROPS = {
    "claytotal": ("clay_pct", True),
    "sandtotal": ("sand_pct", True),
    "silttotal": ("silt_pct", True),
    "ph1to1h2o": ("ph", False),          # pH (H2O)
    "cec7": ("cec", False),              # cation exchange capacity, cmol(+)/kg
    "dbovendry": ("bulk_density", False),  # oven-dry bulk density, g/cm3
}
# SOLUS single-value (not depth-resolved) properties: filename stem -> output var.
SOLUS_SINGLE = {"anylithicdpt_cm": "soil_thickness_cm"}  # depth to any lithic contact = soil thickness
# Depths (cm) averaged to a representative 0–5 cm value (SOLUS predicts at points 0, 5, …).
SOLUS_DEPTHS = (0, 5)


def _bbox_5070(bbox_wgs84: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Transform a (west, south, east, north) WGS84 bbox to EPSG:5070 (minx, miny, maxx, maxy)."""
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    w, s, e, n = bbox_wgs84
    xs, ys = tf.transform([w, e, w, e], [s, s, n, n])
    return min(xs), min(ys), max(xs), max(ys)


def fetch_solus(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path
) -> Path:
    """Fetch the SOLUS100 static soil-hydromechanical set → solus100_wa.zarr (native 100 m grid).

    Writes the shared static set consumed by both our water budget and LandLab's Factor-of-Safety:
    ``clay_pct`` / ``sand_pct`` / ``silt_pct`` (0–5 cm), ``ph`` / ``cec`` / ``bulk_density`` (0–5 cm),
    and ``soil_thickness_cm`` (depth to any lithic contact). Data variables are on EPSG:5070 ``x`` /
    ``y`` coordinates. ``clay_pct`` / ``sand_pct`` keep the schema ``baseline_regression`` and
    ``src.data.fetch_gaia.fetch_solus100`` expect, so downstream consumers are unchanged; the extra
    variables are additive.
    """
    import rioxarray  # noqa: F401
    import xarray as xr

    minx, miny, maxx, maxy = _bbox_5070(bbox_wgs84)

    def _read(url):
        # mask_and_scale applies any embedded nodata + scale_factor (needed for pH/CEC/bulk density).
        da = rioxarray.open_rasterio(url, mask_and_scale=True).squeeze("band", drop=True)
        return da.rio.clip_box(minx, miny, maxx, maxy)

    data_vars = {}
    for prop, (out_name, is_percent) in SOLUS_PROPS.items():
        layers = []
        for depth in SOLUS_DEPTHS:
            url = f"{SOLUS_BASE}/{prop}_{depth}_cm_p.tif"
            logger.info("Reading %s", url)
            da = _read(url)
            if is_percent:
                # Belt-and-suspenders: mask the 255 sentinel for percent fields whose COG nodata
                # metadata may be missing, so it is never averaged in as a real 255 % value.
                da = da.where(da != SOLUS_NODATA)
            layers.append(da)
        # The SOLUS depth COGs share one 100 m EPSG:5070 grid, so clipped windows align.
        mean = xr.concat(layers, dim="depth").mean("depth") if len(layers) > 1 else layers[0]
        data_vars[out_name] = mean.astype("float32")
        logger.info("%s: %d×%d cells, median=%.2f", out_name, mean.sizes["x"], mean.sizes["y"],
                    float(np.nanmedian(mean.values)))

    # Single-value (non-depth-resolved) layers, e.g. depth-to-lithic (soil thickness).
    for stem, out_name in SOLUS_SINGLE.items():
        url = f"{SOLUS_BASE}/{stem}_p.tif"
        logger.info("Reading %s", url)
        da = _read(url).astype("float32")
        data_vars[out_name] = da
        logger.info("%s: median=%.1f cm", out_name, float(np.nanmedian(da.values)))

    ds = xr.Dataset(data_vars)
    ds = ds.rio.write_crs("EPSG:5070")
    out = Path(output_dir) / "solus100_wa.zarr"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Drop the spatial_ref scalar so the Zarr matches the plain x/y schema the sampler expects.
    ds = ds.drop_vars("spatial_ref", errors="ignore")
    ds.to_zarr(out, mode="w", consolidated=True)
    logger.info("SOLUS100 static set (%s) → %s", ", ".join(ds.data_vars), out)
    return out


def fetch_prism_ppt(
    bbox_wgs84: tuple[float, float, float, float], output_dir: Path, res: str = "800m"
) -> Path:
    """Fetch the PRISM 30-yr mean-annual-precipitation normal → prism_mean_annual_ppt_wa.tif.

    Output matches ``src.data.fetch_gaia._write_mean_annual_ppt``: single-band mm/yr, EPSG:5070,
    90 m, nodata −9999 — so ``baseline_regression`` consumes it unchanged. The PRISM annual
    ppt *normal* (date=14) already IS the long-term mean annual precipitation, so this is
    equivalent to (and simpler than) the GAIA path that sums monthly PRISM; used because the
    GAIA prism-stac endpoint is unpublished.

    Note: this static covariate uses the 30-yr normal. The Stage-2 climate-response model
    needs a monthly PRISM *time series* (prism_monthly_wa.zarr) instead — a separate fetch
    against the daily/monthly PRISM service, not built here.
    """
    import io
    import tempfile
    import zipfile

    import requests
    import rioxarray  # noqa: F401
    from rasterio.enums import Resampling

    url = PRISM_NORMALS_URL.format(res=res)
    logger.info("Downloading PRISM annual ppt normal (%s): %s", res, url)
    r = requests.get(url, timeout=180, headers={"User-Agent": "gwl-space-time-smooth"})
    r.raise_for_status()
    if "zip" not in r.headers.get("Content-Type", ""):
        raise RuntimeError(
            "PRISM did not return a zip (likely the ~2 downloads/IP/day rate limit); retry later. "
            f"Body: {r.text[:200]!r}"
        )
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(tmp)
    # PRISM normals ship as a GeoTIFF (older builds used BIL) — accept either.
    rasters = sorted(tmp.glob("*.tif")) or sorted(tmp.glob("*.bil"))
    if not rasters:
        raise RuntimeError(f"No raster in PRISM zip; contents: {[p.name for p in tmp.iterdir()]}")

    da = rioxarray.open_rasterio(rasters[0], masked=True).squeeze("band", drop=True)
    # Clip in the native CRS (NAD83 geographic) with a small buffer, then reproject to 90 m 5070.
    w, s, e, n = bbox_wgs84
    da = da.rio.clip_box(w - 0.1, s - 0.1, e + 0.1, n + 0.1)
    da = da.rio.reproject("EPSG:5070", resolution=TARGET_RES_M, resampling=Resampling.average)
    # masked read leaves a _FillValue attr that clashes with write_nodata on serialization;
    # drop it, materialise nodata as -9999, and set it cleanly.
    da = da.fillna(-9999.0)
    da.attrs.pop("_FillValue", None)
    da.encoding.pop("_FillValue", None)
    da.rio.write_nodata(-9999.0, inplace=True)
    out = Path(output_dir) / "prism_mean_annual_ppt_wa.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    da.rio.to_raster(out, driver="GTiff", dtype="float32", compress="LZW",
                     tiled=True, blockxsize=256, blockysize=256)
    logger.info("PRISM mean annual ppt (mm/yr) → %s (median=%.0f mm)", out,
                float(np.nanmedian(da.values)))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    ps = sub.add_parser("solus", help="SOLUS100 clay%/sand% (0–5 cm) from the public GCS bucket.")
    ps.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("W", "S", "E", "N"), help="WGS84 bbox: west south east north.")
    ps.add_argument("--output-dir", type=Path, default=Path("data/processed"))

    pp = sub.add_parser("prism", help="PRISM 30-yr mean-annual-ppt normal (mm/yr) from the nacse service.")
    pp.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("W", "S", "E", "N"), help="WGS84 bbox: west south east north.")
    pp.add_argument("--res", choices=["800m", "4km"], default="800m", help="PRISM normal resolution.")
    pp.add_argument("--output-dir", type=Path, default=Path("data/processed"))

    args = p.parse_args()

    if args.command == "solus":
        fetch_solus(tuple(args.bbox), args.output_dir)
    elif args.command == "prism":
        fetch_prism_ppt(tuple(args.bbox), args.output_dir, res=args.res)


if __name__ == "__main__":
    main()
