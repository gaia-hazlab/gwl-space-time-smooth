"""The analysis domain — ONE definition, imported everywhere (issue #92, milestone v0.4).

Before this module there were **seven** copies of ``PUGET_CASCADES_BBOX = (-123.3, 46.8, -120.8,
48.5)`` scattered across the fetchers, and none of them matched the grid the static layers were
actually built on (``-122.91, 47.07, -121.60, 48.13``). The declared bbox and the real footprint had
already drifted apart. Every layer must key off one definition or alignment is luck.

## v0.4: the extended domain (western Cascades)

The domain is set by what we must be able to MODEL, not by what is convenient to download. The gauged
basins are the only observational constraint on the water-budget flux partition, and the old footprint
contained exactly one of them (Newaukum Ck, 79 km2; Nisqually/Puyallup/Green/Skykomish were all at 0%).
It is also rain-dominated lowland, so the degree-day snow module never fires -- and snowmelt is what
sets the water table's April peak (#100). Both failures are fixed by the same extension.

    grid   EPSG:5070, 90 m, bounds (-2005000, 2892000, -1864000, 3062000)
           = 141 x 170 km -> ~1567 x 1889 = ~3.0 M cells (3.2x the legacy 0.92 M)

Covers the Puyallup and Nisqually headwaters (Mt Rainier), Green, Cedar, Snoqualmie, Skykomish.

## Guarding against silent mixing

Products built on the LEGACY grid (0.92 M cells) are not aligned with the new one and must never be
combined with it silently. :func:`assert_on_grid` raises instead, and :func:`which_grid` names the
grid a raster is on. A misaligned overlay is exactly the kind of error that looks plausible.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

ANALYSIS_CRS = "EPSG:5070"
RES_M = 90.0
GEO_CRS = "EPSG:4326"

TEMPLATE = Path("data/processed/domain_grid_90m.tif")


@dataclass(frozen=True)
class Domain:
    """A frozen analysis grid, defined in the ANALYSIS CRS.

    The grid is authoritative in EPSG:5070, not in lat/lon. Albers is conic, so a lat/lon rectangle
    maps to a *curved* quadrilateral and its projected bounding box is substantially larger than the
    grid you meant -- defining the domain in lat/lon and projecting inflated it from 3.0 to 5.1 M
    cells, and failed to round-trip the legacy grid (0.92 -> 2.20 M). Define it here, derive lat/lon
    for the fetchers that need it.
    """

    name: str
    bounds_5070: tuple         # (x0, y0, x1, y1)
    res_m: float = RES_M
    crs: str = ANALYSIS_CRS
    snap: bool = True          # snap OUTWARD to whole cells; False = bounds are already exact

    def bounds(self):
        x0, y0, x1, y1 = self.bounds_5070
        if not self.snap:      # legacy: these ARE the raster bounds; snapping would shift them a cell
            return (x0, y0, x1, y1)
        r = self.res_m
        return (np.floor(x0 / r) * r, np.floor(y0 / r) * r,
                np.ceil(x1 / r) * r, np.ceil(y1 / r) * r)

    @property
    def bbox_4326(self):
        """Lat/lon bbox that CONTAINS the projected grid — for fetchers that take lon/lat.

        Deliberately a superset: we fetch a little extra and clip to the grid, never the reverse.
        """
        from pyproj import Transformer

        x0, y0, x1, y1 = self.bounds()
        tf = Transformer.from_crs(self.crs, GEO_CRS, always_xy=True)
        lons, lats = [], []
        for x in np.linspace(x0, x1, 50):
            for y in (y0, y1):
                lo, la = tf.transform(x, y)
                lons.append(lo); lats.append(la)
        for y in np.linspace(y0, y1, 50):
            for x in (x0, x1):
                lo, la = tf.transform(x, y)
                lons.append(lo); lats.append(la)
        return (round(min(lons), 3), round(min(lats), 3), round(max(lons), 3), round(max(lats), 3))

    def shape(self):
        x0, y0, x1, y1 = self.bounds()
        return int(round((y1 - y0) / self.res_m)), int(round((x1 - x0) / self.res_m))   # (rows, cols)

    def transform(self):
        from rasterio.transform import from_origin

        x0, _, _, y1 = self.bounds()
        return from_origin(x0, y1, self.res_m, self.res_m)      # north-up

    def n_cells(self):
        r, c = self.shape()
        return r * c

    def template(self):
        """An all-NaN DataArray on this grid — the ``reproject_match`` target."""
        import rioxarray  # noqa: F401
        import xarray as xr

        rows, cols = self.shape()
        x0, y0, x1, y1 = self.bounds()
        x = x0 + self.res_m * (np.arange(cols) + 0.5)
        y = y1 - self.res_m * (np.arange(rows) + 0.5)           # descending: north-up
        da = xr.DataArray(np.full((rows, cols), np.nan, "float32"),
                          dims=("y", "x"), coords={"y": y, "x": x}, name="domain")
        return da.rio.write_crs(self.crs).rio.write_transform(self.transform())


# --- THE domain (v0.4). Import this, do not re-declare a bbox. --------------------------------------
# Bounds = the union of the gauged basins (NLDI) with the legacy footprint, plus ~5 km of padding.
# Measured, not guessed: see notebooks/close_basin_budget.py and issue #91.
DOMAIN = Domain(
    name="western-cascades-v0.4",
    bounds_5070=(-2005000.0, 2892000.0, -1864000.0, 3062000.0),
)

# The grid the CURRENT static layers were built on. Kept ONLY so legacy products can be identified and
# refused, never silently mixed with the extended grid. Do not build anything new on it.
LEGACY_DOMAIN = Domain(
    name="puget-lowland-legacy",
    bounds_5070=(-1999881.0, 2956991.0, -1924731.0, 3056441.0),   # terrain_hand_90m.tif, exact
    snap=False,
)

# Backwards-compatible alias. The old value (-123.3, 46.8, -120.8, 48.5) never matched the real grid
# anyway; point it at the domain so the seven scattered copies converge.
PUGET_CASCADES_BBOX = DOMAIN.bbox_4326


def write_template(path=TEMPLATE, domain=DOMAIN):
    """Write the canonical grid to disk so alignment is by construction, not by luck."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    domain.template().rio.to_raster(p)
    return p


def load_template(path=TEMPLATE):
    import rioxarray as rxr

    return rxr.open_rasterio(path, masked=True).squeeze("band", drop=True)


def which_grid(da, tol=1.0):
    """Name the grid a raster sits on: 'western-cascades-v0.4', 'puget-lowland-legacy', or 'unknown'."""
    for d in (DOMAIN, LEGACY_DOMAIN):
        if tuple(da.shape[-2:]) != d.shape():
            continue
        b = da.rio.bounds()
        if all(abs(a - c) <= tol for a, c in zip(b, d.bounds())):
            return d.name
    return "unknown"


def assert_on_grid(da, domain=DOMAIN):
    """Raise unless ``da`` is on ``domain``. Stops a legacy product being overlaid on the new grid.

    A misaligned overlay produces a plausible-looking wrong answer rather than an error, which is the
    worst failure mode there is -- hence a hard check rather than a warning.
    """
    got = which_grid(da)
    if got != domain.name:
        raise ValueError(
            f"raster is on grid '{got}' (shape {tuple(da.shape[-2:])}), not '{domain.name}' "
            f"(shape {domain.shape()}). Legacy products are NOT aligned with the extended domain; "
            "rebuild them rather than reprojecting silently."
        )
    return da


if __name__ == "__main__":
    for d in (DOMAIN, LEGACY_DOMAIN):
        r, c = d.shape()
        x0, y0, x1, y1 = d.bounds()
        print(f"{d.name:26s} {c} x {r} = {d.n_cells()/1e6:.2f} M cells @ {d.res_m:.0f} m")
        print(f"{'':26s} bbox4326 {d.bbox_4326}")
        print(f"{'':26s} bounds5070 ({x0:.0f}, {y0:.0f}, {x1:.0f}, {y1:.0f})"
              f"  {(x1-x0)/1000:.0f} x {(y1-y0)/1000:.0f} km")
    p = write_template()
    print(f"\nwrote template grid -> {p}")
