"""SOLUS100 soils + the Saxton-Rawls hydraulic envelope over the extended domain (D3, #94).

The SOLUS source in ``fetch_gaia.py`` is **dead**: its STAC catalog 404s and the
``s3://cresst/solus-stac`` Zarr no longer exists (the bucket has no such prefix). The local
``solus100_wa.zarr`` it produced carries only ``clay_pct`` and ``sand_pct``. This module reads the
**authoritative USDA-NRCS SOLUS100 release** instead:

    https://storage.googleapis.com/solus100pub/{prop}_{depth}_cm_p.tif

They are COGs already in **EPSG:5070 at 100 m**, so a windowed read over the domain costs seconds and
no reprojection — the 337 MB CONUS files are never downloaded. ``_p`` is the prediction; ``_l``/``_h``
are the low/high prediction bounds (available if we later want the soil uncertainty).

## What this adds beyond clay+sand

- **Bulk density** (``dbovendry``) and **organic carbon** (``soc``). Texture alone is a weak handle on
  stiffness; bulk density enters Vs both through rho and, via void ratio, through the modulus (see the
  Vs30 densification milestone).
- **Real organic matter.** ``saxton_rawls_envelope`` has been called with a CONSTANT ``om_pct = 2.5``
  everywhere. Organic matter strongly raises water retention, and PNW forest soils are far from
  uniform in it. We now pass the measured field (OM ~ 1.724 x SOC).
- **Soil thickness** (``resdept``, depth to a restrictive layer; ``anylithicdpt``, depth to lithic
  contact) — so the **root depth stops being a global 1 m constant**. Mountain soils are thin and
  rocky, and root depth directly scales the storage that buffers a storm, so a 1 m column on a
  Cascade ridge fabricates buffering that is not there.

Properties are depth-integrated over the root zone by the trapezoid rule across SOLUS's point depths
(0, 5, 15, 30, 60, 100 cm) rather than taking the 0-5 cm slice as a proxy for the whole column.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np
import rioxarray as rxr
import xarray as xr

from src.config.domain import DOMAIN
from src.io.zarr_store import write_zarr

logger = logging.getLogger("solus_domain")

BASE = "/vsicurl/https://storage.googleapis.com/solus100pub"
DEPTHS_CM = [0, 5, 15, 30, 60, 100]              # SOLUS point depths within the root zone
PROPS = {                                        # SOLUS code -> our name
    "claytotal": "clay_pct",
    "sandtotal": "sand_pct",
    "silttotal": "silt_pct",
    "dbovendry": "bulk_density_g_cm3",
    "soc": "soc_pct",
}
SINGLE = {                                       # single-layer properties (no depth suffix)
    "resdept_all_cm": "soil_thickness_cm",       # depth to a restrictive layer
    "anylithicdpt_cm": "lithic_depth_cm",        # depth to lithic contact
}
SOC_TO_OM = 1.724                                # van Bemmelen: OM% ~ 1.724 x organic carbon%

# SOLUS stores several properties as SCALED INTEGERS. The scale factors are published in the release's
# Final_Layer_Table (column `scalar`) -- NOT guessed. Ignoring them silently produces a bulk density of
# 112 g/cm3 and 214% organic carbon, which then drives theta_sat to an impossible 0.75.
SCALAR = {
    "claytotal": 1.0, "sandtotal": 1.0, "silttotal": 1.0,   # percent mass, unscaled
    "dbovendry": 100.0,                                     # g/cm3
    "soc": 1000.0,                                          # percent mass
    "resdept_all_cm": 1.0, "anylithicdpt_cm": 1.0,          # cm
}


def _read(name, code):
    """Windowed COG read over the domain, with the published scale factor applied.

    SOLUS is already EPSG:5070/100 m, so there is no reprojection here.
    """
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    x0, y0, x1, y1 = DOMAIN.bounds()
    da = rxr.open_rasterio(f"{BASE}/{name}.tif", masked=True, chunks=True).squeeze("band", drop=True)
    return da.rio.clip_box(x0, y0, x1, y1).compute() / SCALAR[code]


def _depth_average(code, root_cm=100):
    """Trapezoid-integrate a property over 0..root_cm across SOLUS's point depths.

    Taking the 0-5 cm slice as a proxy for the whole root zone (what the old fetcher did) biases every
    texture-derived quantity toward the litter layer.
    """
    ds = [d for d in DEPTHS_CM if d <= root_cm]
    layers = [_read(f"{code}_{d}_cm_p", code) for d in ds]
    stack = xr.concat(layers, dim="depth").assign_coords(depth=ds)
    z = np.asarray(ds, dtype="float64")
    w = np.zeros_like(z)                                     # trapezoid weights
    w[0] = (z[1] - z[0]) / 2.0
    w[-1] = (z[-1] - z[-2]) / 2.0
    w[1:-1] = (z[2:] - z[:-2]) / 2.0
    wda = xr.DataArray(w / w.sum(), dims="depth", coords={"depth": ds})
    return (stack * wda).sum("depth", skipna=True).where(stack.notnull().any("depth"))


def build(out_zarr="data/processed/soil_domain_90m.zarr", root_cm=100):
    from src.models.soil_moisture import saxton_rawls_envelope

    tmpl = DOMAIN.template()
    fields = {}
    for code, name in PROPS.items():
        logger.info("SOLUS %s -> %s (trapezoid 0-%d cm)", code, name, root_cm)
        fields[name] = _depth_average(code, root_cm)
    for code, name in SINGLE.items():
        logger.info("SOLUS %s -> %s", code, name)
        fields[name] = _read(f"{code}_p", code)

    logger.info("regridding 100 m -> the 90 m analysis grid ...")
    on = {k: v.rio.reproject_match(tmpl) for k, v in fields.items()}

    sand = on["sand_pct"].values
    clay = on["clay_pct"].values
    om = np.clip(on["soc_pct"].values * SOC_TO_OM, 0.0, 8.0)    # real OM, not a 2.5% constant
    env = saxton_rawls_envelope(sand, clay, om_pct=om)

    # Root depth from the SOIL, not a global 1 m. Thin rocky mountain soils cannot buffer a storm
    # the way a metre of lowland till can, and root depth scales that storage directly.
    thick_cm = np.fmin(np.nan_to_num(on["soil_thickness_cm"].values, nan=200.0),
                       np.nan_to_num(on["lithic_depth_cm"].values, nan=200.0))
    root_m = np.clip(thick_cm / 100.0, 0.10, 2.0)

    ds = xr.Dataset(
        {k: (("y", "x"), v.values.astype("float32")) for k, v in on.items()}
        | {k: (("y", "x"), np.asarray(v, dtype="float32")) for k, v in env.items()}
        | {"om_pct": (("y", "x"), om.astype("float32")),
           "root_depth_m": (("y", "x"), root_m.astype("float32"))},
        coords={"y": tmpl.y, "x": tmpl.x},
    ).rio.write_crs(DOMAIN.crs)
    ds.attrs.update(
        source="USDA-NRCS SOLUS100 (storage.googleapis.com/solus100pub), COG windowed read",
        grid=DOMAIN.name, root_zone_cm=root_cm,
        note=("depth-integrated by trapezoid over SOLUS point depths, NOT the 0-5 cm slice; "
              "Saxton-Rawls uses the REAL organic matter (1.724 x SOC), not a 2.5% constant; "
              "root_depth_m comes from soil thickness, not a global 1 m"),
    )
    write_zarr(ds, out_zarr)
    return ds


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="SOLUS100 + Saxton-Rawls envelope over the domain.")
    p.add_argument("--out", default="data/processed/soil_domain_90m.zarr")
    p.add_argument("--root-cm", type=int, default=100)
    a = p.parse_args()
    ds = build(a.out, a.root_cm)
    for v in sorted(ds.data_vars):
        x = ds[v].values
        logger.info("  %-22s median %8.3f   finite %.0f%%", v, float(np.nanmedian(x)),
                    100 * np.isfinite(x).mean())


if __name__ == "__main__":
    main()
