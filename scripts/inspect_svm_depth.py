"""Report the depth convention of the SVM / CVM17 shallow-Vs grid.

The load-bearing question for Vs30: is the depth coordinate `z` referenced to SEA LEVEL (so each
column's ground surface sits at a different z, with void cells above it) or to the GROUND SURFACE
(z=0 at the surface in every column)? The CVM17 metadata says "depth below sea level" while the model
also carries topography, so this must be confirmed against the file, not assumed.

Usage:  python scripts/inspect_svm_depth.py data/raw/CVM17_L01.nc
"""

from __future__ import annotations

import sys

import numpy as np
import xarray as xr


def main(path):
    with xr.open_dataset(path) as ds:
        print("dims:", dict(ds.sizes))
        print("data vars:", list(ds.data_vars))
        print("coords:", list(ds.coords))

        zname = "z" if "z" in ds else next(c for c in ds.coords if c.lower().startswith(("z", "dep")))
        vname = "vs" if "vs" in ds else ("Vs" if "Vs" in ds else None)
        if vname is None:
            print("!! no vs / Vs variable found; inspect manually")
            return
        z = np.asarray(ds[zname].values, dtype="float64")
        print(f"\n{zname}: n={z.size}  range {z.min():.1f} .. {z.max():.1f}  "
              f"spacing {np.unique(np.round(np.diff(z), 3))[:5]}")
        print(f"{zname} attrs: {dict(ds[zname].attrs)}")
        print(f"{vname} attrs: {dict(ds[vname].attrs)}")

        vs = ds[vname]
        zaxis = vs.dims.index(zname)
        # sample a modest subset of columns so we do not pull the whole 6 GB grid
        sub = vs.isel({d: slice(None, None, max(1, s // 40))
                       for d, s in zip(vs.dims, vs.shape) if d != zname})
        arr = np.moveaxis(np.asarray(sub.values, dtype="float64"), zaxis, 0)
        flat = arr.reshape(arr.shape[0], -1)

        valid = np.isfinite(flat) & (flat > 1.0)              # exclude nodata / air / water (Vs~0)
        anyv = valid.any(axis=0)
        print(f"\nsampled {flat.shape[1]} columns; {anyv.sum()} have any valid Vs")
        if not anyv.any():
            print("!! no valid Vs in the sample")
            return

        k0 = np.argmax(valid, axis=0)[anyv]                   # first valid sample per column
        zsurf = z[k0]
        print(f"first-valid-sample depth ({zname}) per column:")
        print(f"   min {zsurf.min():.1f}   median {np.median(zsurf):.1f}   max {zsurf.max():.1f}")
        print(f"   distinct values: {np.unique(zsurf)[:12]}")

        # THE DIAGNOSTIC:
        if np.allclose(zsurf, z[0]):
            print(f"\n=> every column starts at {zname}={z[0]:.1f}: the depth axis is already "
                  f"SURFACE-REFERENCED.\n   Plain top-30 m averaging is correct; topography is "
                  f"already absorbed into the grid.")
        else:
            print(f"\n=> columns begin at DIFFERENT {zname} (spread "
                  f"{zsurf.max() - zsurf.min():.1f} m): the depth axis is referenced to SEA LEVEL and "
                  f"the void cells above each ground surface encode topography.\n"
                  f"   Vs30 MUST be integrated 30 m below each column's own surface — a plain "
                  f"z in [0,30] average would be wrong.\n"
                  f"   (src.data.fetch_vs30.vs30_surface_referenced does exactly this.)")

        below = z[-1] - zsurf
        short = int((below < 30.0).sum())
        print(f"\ncolumns with <30 m of grid below their surface: {short} "
              f"({100.0 * short / zsurf.size:.1f}%) -> these come out NaN")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/CVM17_L01.nc")
