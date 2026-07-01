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
derived quantity. We therefore write the *measured* texture fractions (clay, sand) only.
The baseline model uses whichever SOLUS variables are present, so ksat simply stays absent
until sourced separately (e.g. POLARIS) rather than being silently synthesised here.

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

SOLUS_BASE = "/vsicurl/https://storage.googleapis.com/solus100pub"
SOLUS_NODATA = 255  # uint8 percent fields

# SOLUS property short-name -> output variable name expected by the models.
SOLUS_PROPS = {"claytotal": "clay_pct", "sandtotal": "sand_pct"}
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
    """Fetch SOLUS100 clay% and sand% (0–5 cm) → solus100_wa.zarr on the native 100 m grid.

    Output schema matches ``src.data.fetch_gaia.fetch_solus100``: data variables
    ``clay_pct`` / ``sand_pct`` on EPSG:5070 ``x`` / ``y`` coordinates, so
    ``baseline_regression`` consumes it unchanged.
    """
    import rioxarray  # noqa: F401
    import xarray as xr

    minx, miny, maxx, maxy = _bbox_5070(bbox_wgs84)
    data_vars = {}
    for prop, out_name in SOLUS_PROPS.items():
        layers = []
        for depth in SOLUS_DEPTHS:
            url = f"{SOLUS_BASE}/{prop}_{depth}_cm_p.tif"
            logger.info("Reading %s", url)
            da = rioxarray.open_rasterio(url, masked=True).squeeze("band", drop=True)
            da = da.rio.clip_box(minx, miny, maxx, maxy)
            layers.append(da)
        # The SOLUS depth COGs share one 100 m EPSG:5070 grid, so clipped windows align
        # and can be averaged directly to a representative 0–5 cm value.
        mean = xr.concat(layers, dim="depth").mean("depth") if len(layers) > 1 else layers[0]
        data_vars[out_name] = mean.astype("float32")
        logger.info("%s: %d×%d cells, median=%.1f%%", out_name, mean.sizes["x"], mean.sizes["y"],
                    float(np.nanmedian(mean.values)))

    ds = xr.Dataset(data_vars)
    ds = ds.rio.write_crs("EPSG:5070")
    out = Path(output_dir) / "solus100_wa.zarr"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Drop the spatial_ref scalar so the Zarr matches the plain x/y schema the sampler expects.
    ds = ds.drop_vars("spatial_ref", errors="ignore")
    ds.to_zarr(out, mode="w", consolidated=True)
    logger.info("SOLUS100 (clay, sand) → %s", out)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    ps = sub.add_parser("solus", help="SOLUS100 clay%/sand% (0–5 cm) from the public GCS bucket.")
    ps.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("W", "S", "E", "N"), help="WGS84 bbox: west south east north.")
    ps.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = p.parse_args()

    if args.command == "solus":
        fetch_solus(tuple(args.bbox), args.output_dir)


if __name__ == "__main__":
    main()
