"""3DEP 10 m DEM over the extended analysis domain, downloaded in tiles and mosaicked (D2, #93).

The extended domain (141 x 170 km) is **240 M cells at 10 m** — a single ``py3dep.get_map`` request
for that is not going to happen, so the DOWNLOAD is tiled.

**The routing is NOT tiled, and must not be.** Flow crosses tile boundaries: depression filling, D8
flow accumulation and HAND are *global* operations, and computing them per tile would sever every
stream at the seams and silently corrupt HAND (which is what the river/baseflow sink is anchored to).
So: tile the download, mosaic to ONE 10 m DEM, then route once over the whole array. At 0.96 GB per
float32 array and ~5-6 live arrays, richdem's working set is ~6 GB — comfortable on this machine.

Tiles are fetched with a halo and mosaicked; the DEM is reprojected to the analysis CRS ONCE, at the
end, so no tile is resampled twice.

    pixi run 3dep-domain              # -> data/raw/dem/3dep_10m_domain_5070.tif
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
import rioxarray as rxr
import xarray as xr
from rasterio.enums import Resampling
from shapely.geometry import box

from src.config.domain import DOMAIN

logger = logging.getLogger("download_3dep_domain")

NODATA = -9999.0
OUT = Path("data/raw/dem/3dep_10m_domain_5070.tif")
TILE_DIR = Path("data/raw/dem/tiles")
HALO_M = 500.0          # overlap so tile edges are not the mosaic edges


def tile_bounds(domain=DOMAIN, tile_km=25.0, halo_m=HALO_M):
    """Split the domain's projected bounds into overlapping tiles (EPSG:5070 metres)."""
    x0, y0, x1, y1 = domain.bounds()
    step = tile_km * 1000.0
    out = []
    for xa in np.arange(x0, x1, step):
        for ya in np.arange(y0, y1, step):
            out.append((max(xa - halo_m, x0 - halo_m), max(ya - halo_m, y0 - halo_m),
                        min(xa + step + halo_m, x1 + halo_m),
                        min(ya + step + halo_m, y1 + halo_m)))
    return out


def _fetch_tile(bounds_5070, idx, res=10, retries=3):
    """One 3DEP tile, requested DIRECTLY in the analysis CRS. Cached, so a re-run after a failure
    does not refetch what already landed.

    Uses ``py3dep.get_dem`` (the static-COG path), NOT ``get_map``: the 3DEP WMS endpoint returns
    non-TIFF payloads and fails. get_dem also accepts a CRS, so tiles arrive in EPSG:5070 already and
    are never reprojected twice.
    """
    import py3dep

    TILE_DIR.mkdir(parents=True, exist_ok=True)
    cache = TILE_DIR / f"3dep_{idx:04d}.tif"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache

    for attempt in range(retries):
        try:
            dem = py3dep.get_dem(tuple(bounds_5070), resolution=res, crs=DOMAIN.crs)
            dem.rio.to_raster(cache, driver="GTiff", compress="LZW", dtype="float32")
            return cache
        except Exception as exc:
            if attempt == retries - 1:
                logger.warning("tile %d failed after %d tries (%s)", idx, retries, exc)
                return None
            time.sleep(3 * (attempt + 1))
    return None


def download(domain=DOMAIN, tile_km=25.0, res=10, out=OUT):
    """Fetch the DEM in tiles, mosaic, and reproject ONCE to the analysis CRS."""
    from rasterio.merge import merge as rio_merge

    tiles = tile_bounds(domain, tile_km)
    logger.info("domain %s: %d tiles of %.0f km (+%.0f m halo) at %d m",
                domain.name, len(tiles), tile_km, HALO_M, res)

    paths = []
    for i, b in enumerate(tiles):
        p = _fetch_tile(b, i, res)
        if p:
            paths.append(p)
        if (i + 1) % 5 == 0:
            logger.info("  %d/%d tiles", i + 1, len(tiles))
    if not paths:
        raise RuntimeError("no 3DEP tiles downloaded")
    if len(paths) < len(tiles):
        # A hole in the DEM severs the drainage network and silently corrupts HAND downstream.
        raise RuntimeError(
            f"only {len(paths)}/{len(tiles)} tiles downloaded. A missing tile puts a HOLE in the DEM, "
            "which severs the flow network and corrupts HAND. Re-run (tiles are cached) rather than "
            "routing on an incomplete DEM."
        )

    logger.info("mosaicking %d tiles ...", len(paths))
    import rasterio

    srcs = [rasterio.open(p) for p in paths]
    arr, transform = rio_merge(srcs, nodata=np.nan)
    crs_in = srcs[0].crs
    for s in srcs:
        s.close()

    da = xr.DataArray(arr[0], dims=("y", "x"), name="dem")
    da = da.rio.write_crs(crs_in).rio.write_transform(transform).rio.write_nodata(np.nan)

    logger.info("reprojecting the mosaic to %s @ %d m (once, not per tile) ...", domain.crs, res)
    x0, y0, x1, y1 = domain.bounds()
    dem = da.rio.reproject(
        domain.crs, resolution=(res, res), resampling=Resampling.bilinear,
        nodata=np.nan,
    ).rio.clip_box(x0, y0, x1, y1)

    out.parent.mkdir(parents=True, exist_ok=True)
    dem.rio.to_raster(out, driver="GTiff", compress="LZW", tiled=True,
                      blockxsize=512, blockysize=512, dtype="float32")
    finite = float(np.isfinite(dem.values).mean())
    logger.info("wrote %s  shape %s  %.1f%% finite", out, tuple(dem.shape), 100 * finite)
    if finite < 0.98:
        logger.warning("only %.1f%% of the DEM is finite — check for gaps before routing", 100 * finite)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="3DEP 10 m DEM over the extended domain (tiled).")
    p.add_argument("--tile-km", type=float, default=25.0)
    p.add_argument("--res", type=int, default=10)
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args()
    download(tile_km=a.tile_km, res=a.res, out=a.out)


if __name__ == "__main__":
    main()
