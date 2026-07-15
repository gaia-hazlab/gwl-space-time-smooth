"""Digital-twin GIF: the soil state through the 2025-26 wet season, western Cascades domain.

Run: ``pixi run twin-gif``

The animation is the forward soil-state model (`forecast_soil_state` under PRISM rainfall) CORRECTED
each frame by a BLUE assimilation (`src/models/observability.blue_update`):

- the **water table** is pulled toward the in-domain NWIS wells' observed SEASONAL CLIMATOLOGY (the
  typical depth-to-water for that calendar month, across 2000-2026 -- the wells inside this mountainous
  domain have no live 2025-26 readings), plus a synthetic deep-band dv/v at the seismic stations;
- **soil moisture** is updated by a synthetic shallow-band dv/v.

The dv/v is synthetic and derived from the model state, so its update is a self-consistency check that
recovers the model near the stations and adds no independent information -- the real information comes
from the wells' seasonal signal. Both facts are stated on the figure. To keep the covariance tractable
the update runs on a coarse grid and its (smooth) correction is interpolated back to the 90 m display.
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
from matplotlib.animation import FuncAnimation, PillowWriter
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/twin_wetseason.gif")
STEP = 8            # display grid subsample (the GIF is a communication artefact, not an analysis)
AFAC = 5           # coarse assimilation grid = STEP*AFAC (dense BLUE covariance must stay tractable)
CADENCE = 7        # days between frames

# petrophysical band sensitivities (dv/v per unit state) and prior/noise scales
S_THETA, K_SAT = -1.0, 5.0e-4
SIG_GWL, L_GWL = 0.5, 12.0          # water-table anomaly prior: 0.5 m, 12 km correlation
SIG_SM, L_SM = 0.03, 8.0            # soil-moisture prior
WELL_VAR = 0.15 ** 2               # NWIS reading error (m), squared
DVV_RISE_VAR = 0.40 ** 2           # synthetic deep dv/v as a rise datum: deliberately loose
DVV_TH_VAR = 0.02 ** 2             # synthetic shallow dv/v as a theta datum
SEED = 11


def _tif(name):
    return rxr.open_rasterio(PROC / name, masked=True).squeeze("band", drop=True)


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.io.zarr_store import open_zarr
    from src.models.forecast import ForecastForcing, forecast_soil_state
    from src.models.observability import (
        GaussianPrior, blue_update, normalise_footprint, point_footprint,
    )
    from src.models.dvv_sensitivity import pair_kernel, single_station_kernel

    soil = xr.open_zarr(PROC / "soil_domain_90m.zarr")
    wt = xr.open_zarr(PROC / "baseline_wt_domain_90m.zarr")
    f = open_zarr(PROC / "prism_daily_2025-09_2026-06.zarr").rio.write_crs("EPSG:4326")

    tmpl = DOMAIN.template()
    sub = tmpl.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    precip = f.precip_mm.rio.reproject_match(sub).values
    tmean = f.tmean_c.rio.reproject_match(sub).values
    pet = f.pet_mm.rio.reproject_match(sub).values
    times = pd.to_datetime(f.time.values)

    sl = (slice(None, None, STEP), slice(None, None, STEP))
    wp, fc_, sat = (soil[k].values[sl] for k in ("theta_wp", "theta_fc", "theta_sat"))
    d0 = wt.dtw_m.values[sl]
    hand = _tif("terrain_hand_domain_90m.tif").values[sl]
    tan_b = np.tan(np.radians(_tif("terrain_slope_domain_90m.tif").values[sl]))
    vs30 = _tif("vs30_domain_90m.tif").values[sl]
    root = soil.root_depth_m.values[sl]

    forcing = ForecastForcing(times=times.values, precip_mm=precip, pet_mm=pet, dt_days=1.0,
                              tmean_c=tmean, source="PRISM")
    fx = forecast_soil_state(forcing, theta_wp=wp, theta_fc=fc_, theta_sat=sat, vs30_base=vs30,
                             wt_depth0_m=d0, root_depth_m=root, slope_tan=tan_b, hand_m=hand)

    land = np.isfinite(d0) & np.isfinite(wp) & np.isfinite(hand)
    msk = lambda a: np.where(land, a, np.nan)          # noqa: E731

    # --- coarse assimilation grid: a further ::AFAC subsample of the display grid ------------------
    cy, cx = sub.y.values[::AFAC], sub.x.values[::AFAC]
    cslice = (slice(None, None, AFAC), slice(None, None, AFAC))
    gx, gy = np.meshgrid(cx / 1000.0, cy / 1000.0)
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    cshape = gx.shape
    B_gwl = GaussianPrior(SIG_GWL, L_GWL).cov(coords)
    B_sm = GaussianPrior(SIG_SM, L_SM).cov(coords)

    # seismic stations -> coarse-km coords; fixed coda footprints (single-station + short pairs)
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)
    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet").drop_duplicates(["lat", "lon"])
    sxm, sym = tf.transform(seis.lon.values, seis.lat.values)
    ins = (sxm >= x0) & (sxm <= x1) & (sym >= y0) & (sym <= y1)
    st_km = np.column_stack([sxm[ins] / 1000.0, sym[ins] / 1000.0])
    Gs = [normalise_footprint(single_station_kernel(gx, gy, s)) for s in st_km]
    for i in range(len(st_km)):
        for j in range(i + 1, len(st_km)):
            if np.hypot(*(st_km[i] - st_km[j])) <= 40.0:
                Gs.append(normalise_footprint(pair_kernel(gx, gy, st_km[i], st_km[j])))
    Gs = np.vstack(Gs)

    # NWIS wells. The wells INSIDE this mountainous domain have no 2025-26 readings (the wells that do
    # are in the Puget lowlands, outside the domain), so there is no *live* in-domain water-table
    # observation for this window. What the in-domain wells do give is their observed SEASONAL
    # CLIMATOLOGY: for each site, the typical monthly depth-to-water across all years of record. The
    # rise anomaly for calendar month m is (site all-year mean) - (site month-m mean); shallower-than-
    # usual months read as a positive rise. This is real, in-domain data and constrains the seasonal
    # amplitude and phase of the water table -- it is NOT the specific 2025-26 values, and is labelled
    # as climatology on the figure.
    allw = pd.read_parquet(PROC / "nwis_gwlevels_monthly.parquet")
    wxm_a, wym_a = tf.transform(allw.lon.values, allw.lat.values)
    allw = allw[(wxm_a >= x0) & (wxm_a <= x1) & (wym_a >= y0) & (wym_a <= y1)].copy()
    site_mean = allw.groupby("site_no").dtw_m.mean()
    clim = (allw.groupby(["site_no", "month"]).dtw_m.mean().rename("month_dtw").reset_index())
    clim["rise_obs"] = clim.site_no.map(site_mean) - clim.month_dtw
    pos = (allw.drop_duplicates("site_no").set_index("site_no")[["lon", "lat"]])
    wxm, wym = tf.transform(pos.lon.values, pos.lat.values)
    pos = pos.assign(xkm=wxm / 1000.0, ykm=wym / 1000.0)
    # one point footprint per in-domain well, cached (positions fixed; the monthly value varies)
    Gw_all = {sid: normalise_footprint(point_footprint(coords, (r.xkm, r.ykm)))
              for sid, r in pos.iterrows()}
    clim_by_month = {m: g for m, g in clim.groupby("month")}          # month -> rows(site_no, rise_obs)

    rng = np.random.default_rng(SEED)

    def upsample(corr_c):
        """Interpolate a coarse correction back to the display grid; edges get zero correction."""
        da = xr.DataArray(corr_c, dims=("y", "x"), coords={"y": cy, "x": cx})
        fine = da.interp(y=sub.y.values, x=sub.x.values, method="linear").values
        return np.nan_to_num(fine)

    def assimilate(k):
        """Return (theta_field, rise_field) at frame k: forward model + BLUE correction."""
        theta_f = fx.theta[k]
        rise_f = d0 - fx.wt_depth_m[k]
        theta_c = np.nan_to_num(theta_f[cslice]).ravel()
        rise_c = np.nan_to_num(rise_f[cslice]).ravel()

        # water table: in-domain well seasonal climatology (this calendar month) + synthetic deep dv/v
        mth = pd.Timestamp(times[k])
        wk = clim_by_month.get(mth.month, clim.iloc[:0])
        Grows, d, nv = [], [], []
        for _, r in wk.iterrows():
            Grows.append(Gw_all[r.site_no]); d.append(r.rise_obs); nv.append(WELL_VAR)
        d_dvv = K_SAT * (Gs @ rise_c) + np.sqrt(DVV_RISE_VAR) * K_SAT * rng.standard_normal(len(Gs))
        for i in range(len(Gs)):
            Grows.append(Gs[i]); d.append(d_dvv[i] / K_SAT); nv.append(DVV_RISE_VAR)
        m_a, _ = blue_update(B_gwl, np.vstack(Grows), np.array(d), np.array(nv), prior_mean=rise_c)
        rise_out = rise_f + upsample((m_a - rise_c).reshape(cshape))

        # soil moisture: synthetic shallow dv/v only (self-consistency; ~no independent information)
        d_th = S_THETA * (Gs @ theta_c) + np.sqrt(DVV_TH_VAR) * abs(S_THETA) * rng.standard_normal(len(Gs))
        m_a, _ = blue_update(B_sm, Gs, d_th / S_THETA, np.full(len(Gs), DVV_TH_VAR), prior_mean=theta_c)
        theta_out = theta_f + upsample((m_a - theta_c).reshape(cshape))
        return msk(theta_out), msk(rise_out), int(wk.site_no.nunique())

    idx = np.arange(0, len(times), CADENCE)
    theta_st, rise_st, nwell_st = [], [], []
    for k in idx:
        th, ri, nw = assimilate(k)
        theta_st.append(th); rise_st.append(ri); nwell_st.append(nw)
    stacks = [
        (np.stack(theta_st), "Soil moisture θ  (dv/v-assimilated)", "YlGnBu", "m³ m⁻³"),
        (np.stack(rise_st), "Water table rise  (wells + dv/v)", "Blues", "m above baseline"),
        (np.stack([msk(100 * fx.dvv_high[i]) for i in idx]), "dv/v  (shallow band, forward)", "RdBu", "%"),
    ]
    pr_series = np.array([np.nanmean(precip[i][land]) for i in range(len(times))])

    # well + station pixel positions on the display grid
    def px(xm, ym):
        return (xm - x0) / (DOMAIN.res_m * STEP), (y1 - ym) / (DOMAIN.res_m * STEP)
    wpx, wpy = px(wxm, wym)
    spx, spy = px(sxm[ins], sym[ins])

    fig, ax = plt.subplots(1, 4, figsize=(17.0, 5.0), constrained_layout=True,
                           gridspec_kw={"width_ratios": [1, 1, 1, 1.15]})
    ims = []
    for a, (data, title, cmap, unit) in zip(ax[:3], stacks):
        v = data[np.isfinite(data)]
        lo, hi = np.percentile(v, [2, 98])
        if title.startswith("dv"):
            hi = max(abs(lo), abs(hi)); lo = -hi
        cm = plt.get_cmap(cmap).copy(); cm.set_bad("#eef0f3")
        im = a.imshow(data[0], cmap=cm, vmin=lo, vmax=hi)
        ims.append(im)
        a.set_title(f"{title}\n[{unit}]", fontsize=18)
        a.set_xticks([]); a.set_yticks([])
        cb = fig.colorbar(im, ax=a, shrink=.78)
        cb.ax.tick_params(labelsize=15)
    ax[0].scatter(spx, spy, s=16, c="k", marker="*", linewidths=0, alpha=.65)
    ax[1].scatter(wpx, wpy, s=20, facecolors="none", edgecolors="#B00020", linewidths=.9)
    ax[2].scatter(spx, spy, s=16, c="k", marker="*", linewidths=0, alpha=.65)

    ax[3].bar(times, pr_series, color="#2E86AB", width=1.0)
    cursor = ax[3].axvline(times[0], color="#E84855", lw=2.5)
    ax[3].set_title("Rainfall forcing (PRISM daily)", fontsize=18)
    ax[3].set_ylabel("mm / day", fontsize=16)
    ax[3].tick_params(axis="x", rotation=35, labelsize=15)
    ax[3].tick_params(axis="y", labelsize=15)
    title = fig.suptitle("", fontsize=18, fontweight="bold")

    def update(k):
        for im, (data, *_) in zip(ims, stacks):
            im.set_data(data[k])
        cursor.set_xdata([times[idx[k]]] * 2)
        title.set_text(
            "GAIA Digital Twin of Soil — wet season 2025–26, western Cascades (90 m)   ·   %s\n"
            "%d in-domain wells assimilated (seasonal climatology, 2000–2026) · dv/v synthetic"
            % (pd.Timestamp(times[idx[k]]).strftime("%d %b %Y"), nwell_st[k]))
        return ims + [cursor, title]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    FuncAnimation(fig, update, frames=len(idx), blit=False).save(
        OUT, writer=PillowWriter(fps=5), dpi=90)
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s (%d frames; wells/month range %d-%d)"
          % (OUT, len(idx), min(nwell_st), max(nwell_st)))


if __name__ == "__main__":
    main()
