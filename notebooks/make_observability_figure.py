"""Resolution and per-sensor information-gain maps for GWL and soil moisture -- now including the
STATIC LAYERS as a source of resolution, not only the sensor network.

Run: ``pixi run observability-figure``

For each state we run the linear-Gaussian design (src/models/observability.py) with the instruments
that actually observe it:
    GWL  <- wells (point) + dv/v DEEP band (footprint)
    SM   <- SNOTEL (point) + dv/v SHALLOW band (footprint)
and report where each network resolves the state, and where dv/v adds information the point sensors
cannot reach.

The static-layer column and the (now static+network) information-gain column follow
`make_static_resolution_figure.py`'s reframing: the covariate-informed estimate is a virtual
self-observation of every cell (footprint = identity, noise = its own per-cell sigma), which turns
into a NONSTATIONARY prior C(x,x') = sigma(x) sigma(x') rho(|x-x'|) that the sensor network is then
updated against -- sequential Bayesian updating, not a separate calculation.

GWL's static sigma is the random-forest tree-ensemble spread (`rf_std_m`, genuinely spatially
varying -- HAND/soil covariates resolve real structure). Soil moisture's Stage 1 is a pedotransfer
envelope (Saxton-Rawls), not a fitted regression, so its static uncertainty (`_PTF_SIGMA` in
soil_moisture.py) is a single constant, not a spatially-resolved one -- the SM static-layer panel is
therefore honestly FLAT, not patchy like GWL's, and is not a cross-validated spatial skill metric the
way GWL's block-CV R^2 is.
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
import xarray as xr
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
PTF_SIGMA = 0.03                 # soil_moisture.py's constant pedotransfer-envelope sigma (m3/m3)


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
        matern_correlation,
        normalise_footprint,
        point_footprint,
        resolution,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    wt = xr.open_zarr(PROC / "baseline_wt_domain_90m.zarr")
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    sub_rfstd = wt.rf_std_m.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
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

    # --- physical (not normalised) prior variances: the "know nothing" baseline each static-layer
    # resolution is measured against -- the population variance of the observed target itself.
    wmask = (~wells.get("is_sparse_timeseries", pd.Series(False, index=wells.index)))
    wmask &= (~wells.get("is_deep_well", pd.Series(False, index=wells.index)))
    wmask &= wells["median_dtw_m"].notna() & (wells["median_dtw_m"] > 0)
    sigma_flat2_gwl = float(np.var(wells[wmask]["median_dtw_m"].values))
    theta_obs = pd.read_parquet(sm)["theta_obs"].dropna().values if sm.exists() else np.array([0.1])
    sigma_flat2_sm = float(np.var(theta_obs))

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

    # --- static-layer resolution: the covariate-informed sigma treated as a per-cell self-
    # observation, and as a NONSTATIONARY prior C(x,x') = sigma(x) sigma(x') rho(d) for the
    # static+network combined info-gain column (see make_static_resolution_figure.py).
    sigma_rf = np.nan_to_num(sub_rfstd.values, nan=np.sqrt(sigma_flat2_gwl)).ravel()
    res_static_gwl = np.clip(1.0 - sigma_rf ** 2 / sigma_flat2_gwl, 0.0, 1.0)
    res_static_sm = np.full(coords.shape[0], np.clip(1.0 - PTF_SIGMA ** 2 / sigma_flat2_sm, 0.0, 1.0))

    dist = np.sqrt(np.sum((coords[:, None, :] - coords[None, :, :]) ** 2, axis=-1))
    C_static_gwl = np.outer(sigma_rf, sigma_rf) * matern_correlation(dist, GWL_L_KM, nu=1.5)
    C_static_sm = (PTF_SIGMA ** 2) * matern_correlation(dist, SM_L_KM, nu=1.5)   # constant sigma -> stationary

    # GWL: wells + deep dv/v
    res_well, _ = resolution(C_gwl, G_well, NOISE["well"])
    res_dvvG, _ = resolution(C_gwl, G_dvv, NOISE["dvv_deep"])
    mg_dvvG = marginal_resolution(C_gwl, G_dvv, G_well, NOISE["dvv_deep"], NOISE["well"])
    both_G = np.vstack([G_well, G_dvv])
    nv_G = np.concatenate([np.full(len(G_well), NOISE["well"]), np.full(len(G_dvv), NOISE["dvv_deep"])])
    _, vpost_G_static = resolution(C_static_gwl, both_G, nv_G * sigma_flat2_gwl)
    ig_G = information_gain(np.full_like(vpost_G_static, sigma_flat2_gwl), vpost_G_static)

    # SM: SNOTEL + shallow dv/v
    res_sno, _ = resolution(C_sm, G_sno, NOISE["snotel"])
    res_dvvS, _ = resolution(C_sm, G_dvv, NOISE["dvv_shallow"])
    mg_dvvS = marginal_resolution(C_sm, G_dvv, G_sno, NOISE["dvv_shallow"], NOISE["snotel"])
    both_S = np.vstack([G_sno, G_dvv])
    nv_S = np.concatenate([np.full(len(G_sno), NOISE["snotel"]), np.full(len(G_dvv), NOISE["dvv_shallow"])])
    _, vpost_S_static = resolution(C_static_sm, both_S, nv_S * sigma_flat2_sm)
    ig_S = information_gain(np.full_like(vpost_S_static, sigma_flat2_sm), vpost_S_static)

    # Colorbar saturation fix: the previous fixed vmax=4 (information_gain's own clip default) left
    # most of the map looking flat, because actual values rarely approach 4 nats. Saturate to the
    # 98th percentile of what's actually on the map instead, and use a punchier, more saturated
    # colormap (cividis reads "washed out" at a glance -- deliberately low-chroma for colorblind
    # safety, but that is exactly the "hard to read" complaint here).
    ig_all = np.concatenate([ig_G[land], ig_S[land]])
    ig_vmax = max(float(np.nanpercentile(ig_all, 98)), 0.05)
    IG = dict(cmap="inferno", vmin=0, vmax=ig_vmax)
    RES = dict(cmap="viridis", vmin=0, vmax=1)

    fig, ax = plt.subplots(2, 5, figsize=(24.0, 9.6), constrained_layout=True)
    rows = [
        ("GROUNDWATER LEVEL", "#2E86AB",
         [(res_static_gwl, "Static layers alone\n(HAND/soil -> RF)", RES),
          (res_well, "Wells alone", RES), (res_dvvG, "dv/v alone (deep band)", RES),
          (mg_dvvG, "dv/v gain beyond wells", dict(cmap="magma", vmin=0, vmax=0.6)),
          (ig_G, "Information gain (nats)\nstatic + wells + dv/v", IG)]),
        ("SOIL MOISTURE", "#3BB273",
         [(res_static_sm, "Static layers alone\n(pedotransfer, constant σ)", RES),
          (res_sno, "SNOTEL alone", RES), (res_dvvS, "dv/v alone (shallow band)", RES),
          (mg_dvvS, "dv/v gain beyond SNOTEL", dict(cmap="magma", vmin=0, vmax=0.6)),
          (ig_S, "Information gain (nats)\nstatic + SNOTEL + dv/v", IG)]),
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

    fig.suptitle("Observability of the twin — resolution and information gain, static layers included\n"
                 "GWL: HAND/soil (RF) + wells (point) + dv/v deep band (volume)      "
                 "SM: pedotransfer envelope + SNOTEL (point) + dv/v shallow band (volume)",
                 fontsize=16, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s  (%d cells, %d wells, %d SNOTEL, %d dv/v footprints, ig_vmax=%.2f nats)"
          % (OUT, int(land.sum()), len(well_km), len(sno_km), len(G_dvv), ig_vmax))


if __name__ == "__main__":
    main()
