"""Variogram-driven well-support / confidence mask (issue #4).

Retires the fixed 50 km well-density mask. Confidence in a cell is set by its distance to
the nearest usable well **relative to that cell's hydrogeologic-domain variogram range**
(in glacial fill the range is a few km; in fractured rock, sub-km — a 50 km mask called
nearly all of western Washington "confident"). Domains where the shallow-water-table
physics does not hold (volcanic_deep, confined_basalt) are hard-masked regardless of well
distance — better silent than confidently wrong for a hazard product.

Pairs with the domain mask (#2) and the per-domain CV block sizes (#3); consumed by the
uncertainty stack and by the downstream liquefaction / LandLab models.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from scipy.spatial import cKDTree

from src.evaluation.domain_gates import DEFAULT_BLOCK_M, DOMAIN_GATES
from src.features.hydrogeologic_domains import DOMAIN_NODATA, DOMAINS

logger = logging.getLogger(__name__)

# Ordinal confidence levels (uint8). 0 = unsupported / masked.
CONF_LEVELS = {0: "masked", 1: "low", 2: "moderate", 3: "high"}
CONF_NODATA = 255
MASKED_DOMAINS = {name for name, g in DOMAIN_GATES.items() if g["mode"] == "masked"}


def build_confidence_mask(
    domain_arr: np.ndarray,
    cell_x: np.ndarray,
    cell_y: np.ndarray,
    well_xy: np.ndarray,
    domain_ranges: dict[str, float] | None = None,
) -> np.ndarray:
    """Ordinal confidence raster aligned to ``domain_arr``.

    A cell is **high** (3) within 1×, **moderate** (2) within 2×, **low** (1) within 3× its
    domain's variogram range of a well, else **masked** (0); cells in a masked domain are 0
    and domain-nodata cells are CONF_NODATA.

    Parameters
    ----------
    domain_arr : (ny, nx) int domain codes (``DOMAINS`` legend; DOMAIN_NODATA outside).
    cell_x, cell_y : flat EPSG:5070 cell-centre coords, row-major to match ``domain_arr``.
    well_xy : (n_wells, 2) EPSG:5070 well coordinates.
    domain_ranges : domain name → variogram range (m); falls back to DEFAULT_BLOCK_M.
    """
    domain_arr = np.asarray(domain_arr)
    ny, nx = domain_arr.shape
    domain_ranges = domain_ranges or {}

    cell_xy = np.column_stack([np.asarray(cell_x, float), np.asarray(cell_y, float)])
    if len(well_xy):
        dist, _ = cKDTree(np.asarray(well_xy, float)).query(cell_xy)
    else:
        dist = np.full(cell_xy.shape[0], np.inf)
    dist = dist.reshape(ny, nx)

    out = np.full((ny, nx), CONF_NODATA, np.uint8)
    for code, name in DOMAINS.items():
        m = domain_arr == code
        if not m.any():
            continue
        if name in MASKED_DOMAINS:
            out[m] = 0
            continue
        r = float(domain_ranges.get(name, DEFAULT_BLOCK_M))
        d = dist[m]
        out[m] = np.where(d <= r, 3, np.where(d <= 2 * r, 2,
                          np.where(d <= 3 * r, 1, 0))).astype(np.uint8)
    out[domain_arr == DOMAIN_NODATA] = CONF_NODATA
    return out


def write_confidence_mask(arr: np.ndarray, profile: dict, path: Path) -> None:
    """Write the ordinal confidence raster (uint8, embedded level legend)."""
    p = profile.copy()
    p.update({"dtype": "uint8", "count": 1, "nodata": CONF_NODATA,
              "compress": "LZW", "tiled": True, "blockxsize": 256, "blockysize": 256})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr, 1)
        dst.update_tags(**{f"CONF_{k}": v for k, v in CONF_LEVELS.items()})
    logger.info("Confidence mask written: %s", path)
