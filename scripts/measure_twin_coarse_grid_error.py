"""Grid-convergence study of the twin's coarse-assimilation workaround (issues #154 / #189).

`notebooks/make_twin_gif.py` solves the BLUE update on a STEP*AFAC = 40-cell (3.6 km) assimilation
grid and bilinearly upsamples the correction back to the 720 m display grid. This script measures what
that costs, so the number quoted in that module's docstring is traceable rather than folklore.

Method (all on the real EPSG:5070 domain, `src.config.domain.DOMAIN`, in km):

1. fix 60 physical sensor locations once (seeded), independent of cell size;
2. build the resolution map R at cell sizes h = 7.2, 3.6, 1.8, 0.9, 0.45 km -- each an exact strided
   subsample of the 90 m grid, so every coarse grid's cell centres are a SUBSET of the finest grid's
   (which is what `cy = sub.y.values[::AFAC]` does in the twin, so the interpolation is faithful);
3. bilinearly interpolate each coarse R onto the finest grid with the same
   `xr.DataArray.interp(method="linear")` + `nan_to_num` that `make_twin_gif.upsample()` uses;
4. report RMS and max |dR| against the finest grid.

Repeat with `width_km` = 0.5 (the twin's value) and 2.0 to separate FOOTPRINT ALIASING from
covariance discretisation: a 0.5 km Gaussian blob collapses to near-one-hot on a 3.6 km cell, so the
datum is silently treated as a 3.6 km-support average.

Run: `PYTHONPATH=. pixi run python scripts/measure_twin_coarse_grid_error.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.observability import GaussianPrior, point_footprint, resolution  # noqa: E402

# the twin's own prior / noise / geometry constants (make_twin_gif.py)
SIG_GWL, L_GWL = 0.5, 12.0
WELL_VAR = 0.15 ** 2
N_OBS = 60
SEED = 11
BASE_M = 90.0
STRIDES = (80, 40, 20, 10, 5)        # -> h = 7.2, 3.6, 1.8, 0.9, 0.45 km


def _axes(stride: int) -> tuple[np.ndarray, np.ndarray]:
    """(y, x) axis values in km for the 90 m domain grid subsampled by ``stride`` (y descending)."""
    x0, y0, x1, y1 = -2005000.0, 2892000.0, -1864000.0, 3062000.0     # DOMAIN.bounds_5070
    h = BASE_M / 1000.0
    nx = int(round((x1 - x0) / BASE_M))
    ny = int(round((y1 - y0) / BASE_M))
    x = (x0 / 1000.0 + h * (np.arange(nx) + 0.5))[::stride]
    y = (y1 / 1000.0 - h * (np.arange(ny) + 0.5))[::stride]           # north-up: DESCENDING
    return y, x


def _resolution_map(stride: int, locs: np.ndarray, width_km: float) -> xr.DataArray:
    y, x = _axes(stride)
    gx, gy = np.meshgrid(x, y)
    c = np.column_stack([gx.ravel(), gy.ravel()])
    op = GaussianPrior(sigma=SIG_GWL, length_km=L_GWL, nu=1.5).operator(c)
    G = np.vstack([point_footprint(c, p, width_km=width_km) for p in locs])
    res, _ = resolution(op, G, WELL_VAR)
    return xr.DataArray(res.reshape(len(y), len(x)), dims=("y", "x"), coords={"y": y, "x": x})


def main() -> int:
    yf, xf = _axes(STRIDES[-1])
    rng = np.random.default_rng(SEED)
    locs = np.column_stack([rng.uniform(xf.min(), xf.max(), N_OBS),
                            rng.uniform(yf.min(), yf.max(), N_OBS)])   # FIXED physical locations
    for width_km in (0.5, 2.0):
        fine = _resolution_map(STRIDES[-1], locs, width_km)
        print(f"\nwidth_km = {width_km}   (reference h = {BASE_M * STRIDES[-1] / 1000:.2f} km, "
              f"{fine.size} cells, n_obs = {N_OBS})")
        print(f"{'h (km)':>8} {'cells':>9} {'RMS dR':>10} {'max dR':>10} {'RMS dR*':>10} {'max dR*':>10}")
        for s in STRIDES[:-1]:
            coarse = _resolution_map(s, locs, width_km)
            up = np.nan_to_num(coarse.interp(y=yf, x=xf, method="linear").values)  # == twin upsample()
            interior = ~np.isnan(coarse.interp(y=yf, x=xf, method="linear").values)
            d = up - fine.values
            print(f"{BASE_M * s / 1000:8.2f} {coarse.size:9d} {np.sqrt((d ** 2).mean()):10.4f} "
                  f"{np.abs(d).max():10.4f} {np.sqrt((d[interior] ** 2).mean()):10.4f} "
                  f"{np.abs(d[interior]).max():10.4f}")
    print("\n* = restricted to the interior the coarse grid actually spans (no zero-fill edge band).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
