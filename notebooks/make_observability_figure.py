"""Resolution and per-sensor information-gain maps for GWL and soil moisture.

Run: ``pixi run observability-figure``

For each state we run the linear-Gaussian design (src/models/observability.py) with the instruments
that actually observe it:
    GWL  <- wells (point) + dv/v DEEP band (footprint)
    SM   <- SNOTEL (point) + dv/v SHALLOW band (footprint)
and report where each network resolves the state, and where dv/v adds information the point sensors
cannot reach.
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
OUT = Path("figures/demo/observability.png")
STEP = 22                       # coarse grid for the covariance solve (resolution maps are smooth)

# Prior correlation lengths, and per-instrument observation-error VARIANCES sigma_d^2 (NOT std) in
# units of the prior VARIANCE -- this is what resolution(..., noise_var=...) expects. The prior sigma
# is 1.0 below, so prior variance is 1.0 and these read directly as noise-to-prior-variance ratios;
# resolution is scale-free, so only that ratio matters. Larger = a noisier / less-trusted stream:
# deep dv/v (0.25) is a weaker handle on the water table than a well (0.02); shallow dv/v (0.12) a
# moderate handle on moisture vs a probe (0.03).
GWL_L_KM, SM_L_KM = 6.0, 3.0    # GWL varies more smoothly than soil moisture
NOISE = dict(well=0.02, snotel=0.03, dvv_deep=0.25, dvv_shallow=0.12)


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
        information_gain,
        marginal_resolution,
        normalise_footprint,
        point_footprint,
        resolution,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    land = np.isfinite(sub.values).ravel()
    gx, gy = np.meshgrid(sub.x.values / 1000.0, sub.y.values / 1000.0)   # km
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    shp = gx.shape
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)

    def stations_km(lon, lat):
        xm, ym = tf.transform(np.asarray(lon), np.asarray(lat))
        keep = (xm >= x0) & (xm <= x1) & (ym >= y0) & (ym <= y1)
        return np.column_stack([xm[keep] / 1000.0, ym[keep] / 1000.0])

    wells = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    swe, sm = PROC / "snotel_swe_daily.parquet", PROC / "snotel_soil_moisture_monthly.parquet"
    snotel = pd.read_parquet(swe) if swe.exists() else pd.DataFrame()
    if "lat" not in snotel.columns and sm.exists():        # offline-safe: SWE table may lack coords
        snotel = pd.read_parquet(sm)

    well_km = stations_km(wells.lon, wells.lat)
    sno_km = stations_km(snotel.drop_duplicates("triplet").lon, snotel.drop_duplicates("triplet").lat)
    seis_km = stations_km(seis.lon, seis.lat)

    # --- observation operators ------------------------------------------------------------------
    def point_G(pts):
        return np.vstack([point_footprint(coords, p) for p in pts]) if len(pts) else np.empty((0, len(coords)))

    G_well = point_G(well_km)
    G_sno = point_G(sno_km)

    # dv/v footprints: every pair (<=40 km) + every single-station autocorrelation, each a normalised
    # coda kernel on the coarse grid. The SAME spatial footprints inform both states -- what differs is
    # the depth band (deep -> GWL, shallow -> SM) and its noise.
    dvv_rows = []
    for i in range(len(seis_km)):
        dvv_rows.append(normalise_footprint(single_station_kernel(gx, gy, seis_km[i])))
        for j in range(i + 1, len(seis_km)):
            if np.hypot(*(seis_km[i] - seis_km[j])) <= 40.0:
                dvv_rows.append(normalise_footprint(pair_kernel(gx, gy, seis_km[i], seis_km[j])))
    G_dvv = np.vstack(dvv_rows)

    def masked(v):
        o = np.where(land, v, np.nan).reshape(shp)
        return o

    C_gwl = GaussianPrior(1.0, GWL_L_KM).cov(coords)
    C_sm = GaussianPrior(1.0, SM_L_KM).cov(coords)
    # prior variance PER STATE, from the covariance diagonal -- so information_gain stays correct if a
    # prior sigma is ever changed, rather than silently assuming sigma=1 for both.
    vp_gwl, vp_sm = np.diag(C_gwl).copy(), np.diag(C_sm).copy()

    # GWL: wells + deep dv/v
    res_well, _ = resolution(C_gwl, G_well, NOISE["well"])
    res_dvvG, _ = resolution(C_gwl, G_dvv, NOISE["dvv_deep"])
    mg_dvvG = marginal_resolution(C_gwl, G_dvv, G_well, NOISE["dvv_deep"], NOISE["well"])
    both_G = np.vstack([G_well, G_dvv])
    nv_G = np.concatenate([np.full(len(G_well), NOISE["well"]), np.full(len(G_dvv), NOISE["dvv_deep"])])
    _, vpost_G = resolution(C_gwl, both_G, nv_G)
    ig_G = information_gain(vp_gwl, vpost_G)

    # SM: SNOTEL + shallow dv/v
    res_sno, _ = resolution(C_sm, G_sno, NOISE["snotel"])
    res_dvvS, _ = resolution(C_sm, G_dvv, NOISE["dvv_shallow"])
    mg_dvvS = marginal_resolution(C_sm, G_dvv, G_sno, NOISE["dvv_shallow"], NOISE["snotel"])
    both_S = np.vstack([G_sno, G_dvv])
    nv_S = np.concatenate([np.full(len(G_sno), NOISE["snotel"]), np.full(len(G_dvv), NOISE["dvv_shallow"])])
    _, vpost_S = resolution(C_sm, both_S, nv_S)
    ig_S = information_gain(vp_sm, vpost_S)

    fig, ax = plt.subplots(2, 4, figsize=(19.5, 9.6), constrained_layout=True)
    RES = dict(cmap="viridis", vmin=0, vmax=1)
    rows = [
        ("GROUNDWATER LEVEL", "#2E86AB",
         [(res_well, "Wells alone", RES), (res_dvvG, "dv/v alone (deep band)", RES),
          (mg_dvvG, "dv/v gain beyond wells", dict(cmap="magma", vmin=0, vmax=0.6)),
          (ig_G, "Information gain (nats)", dict(cmap="cividis", vmin=0, vmax=4))]),
        ("SOIL MOISTURE", "#3BB273",
         [(res_sno, "SNOTEL alone", RES), (res_dvvS, "dv/v alone (shallow band)", RES),
          (mg_dvvS, "dv/v gain beyond SNOTEL", dict(cmap="magma", vmin=0, vmax=0.6)),
          (ig_S, "Information gain (nats)", dict(cmap="cividis", vmin=0, vmax=4))]),
    ]
    for r, (state, col, panels) in enumerate(rows):
        for cc, (field, title, kw) in enumerate(panels):
            a = ax[r, cc]
            cm = plt.get_cmap(kw["cmap"]).copy(); cm.set_bad("#eef0f3")
            im = a.imshow(masked(field), cmap=cm, vmin=kw["vmin"], vmax=kw["vmax"])
            a.set_title(title, fontsize=13, fontweight="bold")
            fig.colorbar(im, ax=a, shrink=.72)
            a.set_xticks([]); a.set_yticks([])
        ax[r, 0].set_ylabel(state, fontsize=15, fontweight="bold", color=col, labelpad=8)

    fig.suptitle("Observability of the twin — resolution and information gain by sensor network\n"
                 "GWL: wells (point) + dv/v deep band (volume)      "
                 "SM: SNOTEL (point) + dv/v shallow band (volume)",
                 fontsize=16, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s  (%d cells, %d wells, %d SNOTEL, %d dv/v footprints)"
          % (OUT, int(land.sum()), len(well_km), len(sno_km), len(G_dvv)))


if __name__ == "__main__":
    main()
