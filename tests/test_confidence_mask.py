"""Tests for the variogram-driven confidence mask (issue #4).

Runs standalone (`python -m tests.test_confidence_mask`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.evaluation.confidence_mask import CONF_NODATA, build_confidence_mask
from src.features.hydrogeologic_domains import DOMAIN_NODATA, DOMAINS

CODE = {v: k for k, v in DOMAINS.items()}


def _grid(ny=20, nx=20, dx=1000.0):
    rows, cols = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    cell_x = (cols.ravel() * dx).astype(float)
    cell_y = (rows.ravel() * dx).astype(float)
    return ny, nx, cell_x, cell_y


def test_levels_decay_with_distance():
    ny, nx, cx, cy = _grid()
    dom = np.full((ny, nx), CODE["unconsolidated_valley_fill"], dtype=np.int16)
    well = np.array([[0.0, 0.0]])                      # one well at the corner
    out = build_confidence_mask(dom, cx, cy, well, {"unconsolidated_valley_fill": 2000.0})
    assert out[0, 0] == 3                              # at the well → high
    # a far corner (≈ 19*sqrt2 km ≫ 3×2 km) → masked
    assert out[-1, -1] == 0
    # monotone non-increasing along the first row away from the well
    row = out[0]
    assert np.all(np.diff(row.astype(int)) <= 0)


def test_masked_domains_are_zero_regardless_of_wells():
    ny, nx, cx, cy = _grid()
    dom = np.full((ny, nx), CODE["volcanic_deep"], dtype=np.int16)
    well = np.array([[0.0, 0.0]])                      # well right there...
    out = build_confidence_mask(dom, cx, cy, well, {})
    assert np.all(out == 0)                            # ...still hard-masked


def test_domain_nodata_propagates():
    ny, nx, cx, cy = _grid()
    dom = np.full((ny, nx), CODE["unconsolidated_valley_fill"], dtype=np.int16)
    dom[0, 0] = DOMAIN_NODATA
    out = build_confidence_mask(dom, cx, cy, np.array([[0.0, 0.0]]), {})
    assert out[0, 0] == CONF_NODATA


def test_no_wells_all_unsupported():
    ny, nx, cx, cy = _grid()
    dom = np.full((ny, nx), CODE["unconsolidated_basin"], dtype=np.int16)
    out = build_confidence_mask(dom, cx, cy, np.empty((0, 2)), {})
    assert np.all(out == 0)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
