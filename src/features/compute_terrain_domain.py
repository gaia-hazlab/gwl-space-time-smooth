"""Terrain derivatives (HAND / slope / TWI / contributing area) over the extended domain (D2, #93).

Routing is **global by necessity**: depression filling, D8 accumulation and HAND all follow flow
across the whole grid, so they cannot be tiled. Only the DEM *download* is tiled
(:mod:`src.data.download_3dep_domain`). Here we route once over the full 10 m DEM (240 M cells,
~0.96 GB per float32 array) and only then downsample to the 90 m analysis grid — never route on a
downsampled DEM, which would destroy the drainage network.

## Why this is not just the old module with a bigger input

``src.features.compute_terrain.compute_hand`` traces the D8 path **for every cell, in a Python
double loop**, re-walking up to 5000 steps each time: O(N x path length) scalar operations. At
240 M cells that is ~1e11 Python iterations — it would never finish.

HAND is computed here by **pointer doubling** instead. Each cell points at its D8 downstream
neighbour; stream cells point at themselves. Repeatedly applying ``next = next[next]`` resolves every
cell to its drainage terminal in O(log L) *vectorised* passes rather than O(N x L) scalar ones — ~10
gathers instead of 1e11 steps. Then ``HAND = dem - dem[terminal]``.

Cells whose path ends in a pit rather than a stream are returned as **NaN**, not as a fabricated
height above a non-existent drainage. HAND is what the river/baseflow sink is anchored to, so a
silently wrong HAND would corrupt the water budget in exactly the way we have been chasing.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import rioxarray as rxr

from src.config.domain import DOMAIN

logger = logging.getLogger("terrain_domain")

NODATA = -9999.0
STREAM_THRESHOLD_M2 = 1.0e6          # 1 km^2 contributing area defines a channel head
DEM_10M = Path("data/raw/dem/3dep_10m_domain_5070.tif")
OUT_DIR = Path("data/processed")

# D8 neighbour offsets (drow, dcol) and their distances in cell units
_D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
_DIST = np.array([1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2)])


def _d8_downstream_index(dem, cell_m):
    """Flat index of each cell's steepest-descent D8 neighbour; self where there is no descent.

    Computed by 8 shifted comparisons keeping only the running best, so peak memory is a few arrays
    rather than the (rows, cols, 9) FlowProportions block richdem would return (8.6 GB at this size).

    **Must be float64.** richdem's epsilon depression-fill imposes a ~1e-6 m gradient across flats so
    that water has somewhere to go. At ~1000 m elevation that is BELOW float32 precision (~6e-5), so
    in float32 the gradient vanishes, every filled flat becomes a pit, and HAND coverage collapses
    (measured: 4.5% instead of 71%). The heights can be float32; the DIRECTIONS cannot.
    """
    dem = np.asarray(dem, dtype="float64")
    rows, cols = dem.shape
    n = rows * cols
    idx = np.arange(n, dtype=np.int64).reshape(rows, cols)

    best_drop = np.zeros((rows, cols), dtype="float64")     # steepest positive drop per unit distance
    nxt = idx.copy()                                        # default: self (pit / edge / flat)

    for k, (dr, dc) in enumerate(_D8):
        # neighbour elevation, shifted; out-of-bounds -> +inf so it can never be downhill
        nb = np.full((rows, cols), np.inf, dtype="float64")
        nb_idx = np.full((rows, cols), -1, dtype=np.int64)
        # nb[r, c] must be dem[r + dr, c + dc]. Getting these two slices the wrong way round flips
        # the flow direction and sends water UPHILL -- it silently drops HAND coverage to ~5%.
        dst_r = slice(max(-dr, 0), rows - max(dr, 0))
        dst_c = slice(max(-dc, 0), cols - max(dc, 0))
        src_r = slice(max(dr, 0), rows - max(-dr, 0))
        src_c = slice(max(dc, 0), cols - max(-dc, 0))
        nb[dst_r, dst_c] = dem[src_r, src_c]
        nb_idx[dst_r, dst_c] = idx[src_r, src_c]

        drop = (dem - nb) / (_DIST[k] * cell_m)             # +ve = downhill
        better = np.isfinite(drop) & (drop > best_drop) & (nb_idx >= 0)
        best_drop = np.where(better, drop, best_drop)
        nxt = np.where(better, nb_idx, nxt)
        del nb, nb_idx, drop, better

    return nxt.ravel()


def compute_hand(dem, contrib_area_m2, cell_m, stream_threshold_m2=STREAM_THRESHOLD_M2):
    """HAND by pointer doubling — O(log path) vectorised passes, not O(N x path) Python steps.

    ``dem`` must be the **epsilon-filled** surface, and is used in float64 for the flow directions
    (see :func:`_d8_downstream_index`).
    """
    rows, cols = dem.shape
    flat_dem = np.asarray(dem, dtype="float64").ravel()
    is_stream = (contrib_area_m2 >= stream_threshold_m2) & np.isfinite(dem)

    nxt = _d8_downstream_index(dem, cell_m)
    n = nxt.size
    self_idx = np.arange(n, dtype=np.int64)

    # streams are absorbing: they point at themselves and every path must terminate on one
    nxt[is_stream.ravel()] = self_idx[is_stream.ravel()]

    # pointer doubling: next = next[next] until nothing changes
    for it in range(64):
        new = nxt[nxt]
        moved = int(np.count_nonzero(new != nxt))
        nxt = new
        logger.info("  HAND pointer-doubling pass %2d: %d cells still resolving", it + 1, moved)
        if moved == 0:
            break

    terminal_is_stream = is_stream.ravel()[nxt]
    hand = flat_dem - flat_dem[nxt]
    # a path ending in a PIT has no drainage: NaN, never a fabricated height above nothing
    hand = np.where(terminal_is_stream, np.maximum(hand, 0.0), np.nan)
    hand = np.where(np.isfinite(flat_dem), hand, np.nan)
    return hand.reshape(rows, cols).astype("float32")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Terrain derivatives over the extended domain.")
    p.add_argument("--dem", type=Path, default=DEM_10M)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--suffix", default="_domain_90m")
    a = p.parse_args()

    import richdem as rd

    logger.info("loading %s", a.dem)
    dem_da = rxr.open_rasterio(a.dem, masked=True).squeeze("band", drop=True)
    dem = dem_da.values.astype("float32")
    cell_m = abs(float(dem_da.rio.resolution()[0]))
    logger.info("DEM %s @ %.1f m = %.1f M cells, %.0f%% finite",
                dem.shape, cell_m, dem.size / 1e6, 100 * np.isfinite(dem).mean())

    # --- fill depressions ONCE; every derivative below must use the same filled surface ----------
    logger.info("filling depressions (global — flow crosses tiles, so this cannot be chunked) ...")
    rda = rd.rdarray(np.where(np.isfinite(dem), dem, NODATA).astype("float64"), no_data=NODATA)
    # richdem defaults to a UNIT cell size. Without this the slope is computed with dx = 1 m instead
    # of the real ~8.3 m and comes out ~8x too steep (median 64 deg instead of ~8 deg) -- and TWI,
    # which divides by tan(slope), is wrong with it.
    rda.geotransform = (0.0, cell_m, 0.0, 0.0, 0.0, -cell_m)
    rd.FillDepressions(rda, epsilon=True, in_place=True)
    filled = np.asarray(rda, dtype="float64")      # float64: the epsilon gradient must survive
    filled[~np.isfinite(dem)] = np.nan

    logger.info("slope ...")
    slope = np.asarray(rd.TerrainAttribute(rda, attrib="slope_degrees"), dtype="float32")
    slope[~np.isfinite(dem)] = np.nan

    logger.info("D8 flow accumulation ...")
    accum = np.asarray(rd.FlowAccumulation(rda, method="D8"), dtype="float32")
    contrib = accum * cell_m ** 2                      # m^2
    contrib[~np.isfinite(dem)] = np.nan
    del rda, accum

    logger.info("HAND (pointer doubling) ...")
    hand = compute_hand(filled, contrib, cell_m)

    logger.info("TWI ...")
    tanb = np.tan(np.radians(np.clip(slope, 0.1, None)))
    twi = np.log(np.clip(contrib / cell_m, 1e-6, None) / tanb).astype("float32")
    twi[~np.isfinite(dem)] = np.nan

    # --- downsample to the 90 m analysis grid (route first, THEN coarsen) ------------------------
    a.out_dir.mkdir(parents=True, exist_ok=True)
    tmpl = DOMAIN.template()
    for name, arr, how in (("hand", hand, "average"), ("slope", slope, "average"),
                           ("twi", twi, "average"), ("contrib_area", contrib, "max")):
        da = dem_da.copy(data=arr).rio.write_nodata(np.nan)
        res = da.rio.reproject_match(tmpl, resampling=getattr(__import__(
            "rasterio.enums", fromlist=["Resampling"]).Resampling, how))
        out = a.out_dir / f"terrain_{name}{a.suffix}.tif"
        res.rio.to_raster(out, compress="LZW", dtype="float32")
        v = res.values
        logger.info("wrote %s  %.0f%% finite  median %.2f", out,
                    100 * np.isfinite(v).mean(), float(np.nanmedian(v)))


if __name__ == "__main__":
    main()
