"""The full observing system: point + volume + satellite + surface-water, for GWL and soil moisture.

Run: ``pixi run observing-system-figure``

Extends the ground-network observability with the two distributed streams:
    SM   <- SNOTEL (point) + dv/v shallow (volume) + SMAP 9 km + NISAR ~0.2 km (satellite, future)
    GWL  <- wells (point)  + dv/v deep (volume)    + surface-water extent (variable source area)
Only the sensor GEOMETRY and noise enter -- resolution is a scale-free ratio -- so a not-yet-flown
product (NISAR) can be evaluated for the coverage it WOULD provide.
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/observing_system.png")
STEP = 22
GWL_L_KM, SM_L_KM = 6.0, 3.0
NOISE = dict(well=0.02, snotel=0.03, dvv_deep=0.25, dvv_shallow=0.12,
             smap=0.10, nisar=0.06, surfwater=0.04)


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.models.dvv_sensitivity import pair_kernel, single_station_kernel
    from src.models.observability import (
        GaussianPrior,
        channel_footprints,
        normalise_footprint,
        point_footprint,
        resolution,
        satellite_footprints,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    land = np.isfinite(sub.values).ravel()
    gx, gy = np.meshgrid(sub.x.values / 1000.0, sub.y.values / 1000.0)
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    shp = gx.shape
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)

    def st_km(lon, lat):
        xm, ym = tf.transform(np.asarray(lon), np.asarray(lat))
        k = (xm >= x0) & (xm <= x1) & (ym >= y0) & (ym <= y1)
        return np.column_stack([xm[k] / 1000.0, ym[k] / 1000.0])

    wells = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    sno = pd.read_parquet(PROC / "snotel_swe_daily.parquet")
    if "lat" not in sno.columns:
        sno = pd.read_parquet(PROC / "snotel_soil_moisture_monthly.parquet")

    well_km = st_km(wells.lon, wells.lat)
    sno_km = st_km(sno.drop_duplicates("triplet").lon, sno.drop_duplicates("triplet").lat)
    seis_km = st_km(seis.lon, seis.lat)

    pt = lambda pts: (np.vstack([point_footprint(coords, p) for p in pts])
                      if len(pts) else np.empty((0, len(coords))))       # noqa: E731
    G_well, G_sno = pt(well_km), pt(sno_km)
    dvv = []
    for i in range(len(seis_km)):
        dvv.append(normalise_footprint(single_station_kernel(gx, gy, seis_km[i])))
        for j in range(i + 1, len(seis_km)):
            if np.hypot(*(seis_km[i] - seis_km[j])) <= 40.0:
                dvv.append(normalise_footprint(pair_kernel(gx, gy, seis_km[i], seis_km[j])))
    G_dvv = np.vstack(dvv)
    G_smap = satellite_footprints(coords, 9.0, land)
    G_nisar = satellite_footprints(coords, 3.0, land)                     # ~coarsened NISAR for display
    G_surf = channel_footprints(coords, sub.values.ravel(), land, hand_max_m=3.0)

    C_gwl = GaussianPrior(1.0, GWL_L_KM).cov(coords)
    C_sm = GaussianPrior(1.0, SM_L_KM).cov(coords)
    m = lambda v: np.where(land, v, np.nan).reshape(shp)                  # noqa: E731

    def stack(C, gs, ns):
        nz = [(g, nz_noise) for g, nz_noise in zip(gs, ns) if g.shape[0]]
        if not nz:                                            # every operator empty -> nothing resolved
            return np.zeros(len(coords))
        G = np.vstack([g for g, _ in nz])
        nv = np.concatenate([np.full(g.shape[0], nz_noise) for g, nz_noise in nz])
        return resolution(C, G, nv)[0]

    # SM: cumulative -- SNOTEL, +SMAP, +dv/v, +NISAR(future)
    sm_panels = [
        (resolution(C_sm, G_sno, NOISE["snotel"])[0], "SNOTEL only", "#3BB273"),
        (stack(C_sm, [G_sno, G_smap], [NOISE["snotel"], NOISE["smap"]]), "+ SMAP  (9 km)", "#3BB273"),
        (stack(C_sm, [G_sno, G_smap, G_dvv], [NOISE["snotel"], NOISE["smap"], NOISE["dvv_shallow"]]),
         "+ dv/v  (volume)", "#3BB273"),
        (stack(C_sm, [G_sno, G_smap, G_dvv, G_nisar],
               [NOISE["snotel"], NOISE["smap"], NOISE["dvv_shallow"], NOISE["nisar"]]),
         "+ NISAR  (~0.2 km, future)", "#3BB273"),
    ]
    gwl_panels = [
        (resolution(C_gwl, G_well, NOISE["well"])[0], "Wells only", "#2E86AB"),
        (stack(C_gwl, [G_well, G_dvv], [NOISE["well"], NOISE["dvv_deep"]]), "+ dv/v  (volume)", "#2E86AB"),
        (stack(C_gwl, [G_well, G_dvv, G_surf], [NOISE["well"], NOISE["dvv_deep"], NOISE["surfwater"]]),
         "+ surface water  (VSA)", "#2E86AB"),
        (stack(C_gwl, [G_well, G_dvv, G_surf, G_smap],
               [NOISE["well"], NOISE["dvv_deep"], NOISE["surfwater"], NOISE["smap"]]),
         "+ satellite (indirect)", "#2E86AB"),
    ]

    fig, ax = plt.subplots(2, 4, figsize=(19.5, 9.7), constrained_layout=True)
    for r, (state, panels) in enumerate([("SOIL MOISTURE", sm_panels),
                                         ("GROUNDWATER LEVEL", gwl_panels)]):
        for cc, (field, title, col) in enumerate(panels):
            a = ax[r, cc]
            cm = plt.get_cmap("viridis").copy(); cm.set_bad("#eef0f3")
            im = a.imshow(m(field), cmap=cm, vmin=0, vmax=1)
            a.set_title(title, fontsize=10.5, fontweight="bold")
            fig.colorbar(im, ax=a, shrink=.72, label="resolution")
            a.set_xticks([]); a.set_yticks([])
        ax[r, 0].set_ylabel(state, fontsize=12, fontweight="bold",
                            color=panels[0][2], labelpad=8)

    fig.suptitle("The full observing system — resolution of the state as each network is added\n"
                 "point (wells, SNOTEL) · volume (dv/v) · satellite (SMAP now, NISAR future) · "
                 "surface water (variable source area)",
                 fontsize=13, fontweight="bold")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s  (SMAP %d px, NISAR %d px, surface-water %d cells, dv/v %d)"
          % (OUT, G_smap.shape[0], G_nisar.shape[0], G_surf.shape[0], G_dvv.shape[0]))


if __name__ == "__main__":
    main()
