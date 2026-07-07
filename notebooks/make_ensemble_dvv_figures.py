"""Showcase figures for the forcing ensemble (PRISM vs TerraClimate) and the dv/v coupling.

  1. forcing_ensemble.png — same envelope + Thornthwaite-Mather bucket under two independent
     forcings (TerraClimate reanalysis vs PRISM observations); domain-mean θ agreement and the
     per-cell forcing-uncertainty σ that this ensemble contributes to the budget (UQ / bootstrap).
  2. dvv_coupling.png — demonstrative dv/v ↔ (GWL, SM) coupling: the modelled states forward-mapped
     to banded dv/v (low band → water table, high band → soil moisture), then inverted back,
     showing dv/v can *derive* both states (closed-loop recovery).

Run:  pixi run python notebooks/make_ensemble_dvv_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr
from pyproj import Transformer

from src.models.dvv_coupling import coupling_envelope, forward_dvv, invert_dvv
from src.models.gwl_dynamic import gwl_dynamic_90m
from src.models.soil_moisture import soil_moisture_90m, soil_moisture_forcing_ensemble

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
OUT.mkdir(parents=True, exist_ok=True)
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"tc": "#0072B2", "prism": "#E69F00", "green": "#009E73", "purple": "#CC79A7", "vermillion": "#D55E00"}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titlecolor": INK, "axes.titleweight": "bold",
                     "axes.edgecolor": MUTED, "figure.dpi": 130})


def _map(ax, da_ll, cmap, title, label, vmin=None, vmax=None):
    x, y = da_ll.x.values, da_ll.y.values
    im = ax.imshow(da_ll.values, extent=[x.min(), x.max(), y.min(), y.max()], origin="upper",
                   cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_title(title, fontsize=10.5); ax.tick_params(labelsize=8)
    cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label(label, fontsize=8.5)
    cb.ax.tick_params(labelsize=8)


def fig_forcing_ensemble(env, tc, prism):
    months, per, ens, sig_forcing = soil_moisture_forcing_ensemble(env, {"TerraClimate": tc, "PRISM": prism})
    t = pd.DatetimeIndex(months)
    tcm, prm = np.nanmean(per["TerraClimate"], (1, 2)), np.nanmean(per["PRISM"], (1, 2))
    r = np.corrcoef(tcm, prm)[0, 1]

    fig = plt.figure(figsize=(14, 4.6))
    gs = fig.add_gridspec(1, 3, wspace=0.32, width_ratios=[1.5, 1, 1])

    ax = fig.add_subplot(gs[0, 0])
    roll = lambda a: pd.Series(a).rolling(13, center=True, min_periods=7).mean().values
    ax.plot(t, tcm, color=OI["tc"], lw=0.5, alpha=0.35)
    ax.plot(t, prm, color=OI["prism"], lw=0.5, alpha=0.35)
    ax.plot(t, roll(tcm), color=OI["tc"], lw=2, label="TerraClimate forcing (reanalysis)")
    ax.plot(t, roll(prm), color=OI["prism"], lw=2, label="PRISM forcing (observations)")
    ax.set_title(f"Same bucket, two independent forcings  (r = {r:.2f})", fontsize=10.5)
    ax.set_ylabel("domain-mean θ (m³/m³)"); ax.legend(fontsize=7.5, loc="upper right"); ax.grid(alpha=0.3)

    sig = env["theta_fc"].copy(data=sig_forcing).rio.write_crs("EPSG:5070").rio.reproject("EPSG:4326")
    ax2 = fig.add_subplot(gs[0, 1])
    v = sig_forcing[np.isfinite(sig_forcing)]
    _map(ax2, sig, "magma", "Forcing uncertainty σ_forcing", "m³/m³", vmax=float(np.nanpercentile(v, 97)))

    ax3 = fig.add_subplot(gs[0, 2])
    comps = {"static\npedotransfer": 0.030, "dynamic\nbucket": 0.014,
             "downscaling": 0.011, "forcing\n(TC/PRISM)": float(np.nanmedian(sig_forcing))}
    ax3.bar(range(len(comps)), list(comps.values()),
            color=[OI["tc"], OI["prism"], OI["vermillion"], OI["green"]])
    ax3.set_xticks(range(len(comps))); ax3.set_xticklabels(list(comps), fontsize=7.5)
    ax3.set_ylabel("median 1σ (m³/m³)"); ax3.set_title("θ uncertainty components\n(forcing now explicit)", fontsize=10.5)
    ax3.grid(axis="x", visible=False)
    for s in ("top", "right"):
        ax3.spines[s].set_visible(False)

    fig.suptitle("Soil-moisture forcing ensemble — swappable, observation vs reanalysis forcing (UQ)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "forcing_ensemble.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "forcing_ensemble.png")


def fig_dvv_coupling(env, tc):
    # Modelled states for one month in the dense-well window.
    base = rxr.open_rasterio(PROC / "baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    rfs = rxr.open_rasterio(PROC / "baseline_rf_std_m.tif", masked=True).squeeze("band", drop=True)
    m = pd.read_parquet(PROC / "nwis_gwlevels_monthly.parquet")
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    m["x_5070"], m["y_5070"] = tf.transform(m.lon.values, m.lat.values)
    m["date"] = pd.to_datetime(dict(year=m.year, month=m.month, day=1))
    L, B, R, T = base.rio.bounds()
    pin = m[(m.x_5070 >= L) & (m.x_5070 <= R) & (m.y_5070 >= B) & (m.y_5070 <= T)]
    # Multi-month window so each month's anomaly is relative to the window climatology (not 0).
    g_times, dtw, _ = gwl_dynamic_90m(pin, base, rfs, ("2010-04-01", "2012-12-01"))
    gi = int(np.argmin([abs((pd.Timestamp(t) - pd.Timestamp("2011-02-01")).days) for t in g_times]))
    dtw_anom = dtw[gi] - base.values                     # DTW anomaly for the chosen month (m)
    mon = pd.Timestamp(g_times[gi])

    drv_t = pd.DatetimeIndex(tc.time.values)
    idx = [int(np.where((drv_t.year == mon.year) & (drv_t.month == mon.month))[0][0])]
    _, theta, _ = soil_moisture_90m(env, tc, times=idx, downscaler="twi")
    theta = theta[0]
    theta_ref = env["theta_wp"].values + 0.5 * (env["theta_fc"].values - env["theta_wp"].values)

    # Real SOLUS texture (reprojected to the 90 m grid) for the coupling sensitivities.
    solus = xr.open_zarr(PROC / "solus100_wa.zarr")
    if solus.rio.crs is None:
        solus = solus.rio.write_crs("EPSG:5070")
    solus90 = solus.rio.reproject_match(base)
    envc = coupling_envelope(solus90["sand_pct"].values, solus90["clay_pct"].values,
                             env["theta_wp"].values, env["theta_sat"].values)
    dvv = forward_dvv(dtw_anom, theta, theta_ref, envc)
    dtw_rec, theta_rec = invert_dvv(dvv["dvv_low"], dvv["dvv_high"], envc,
                                    dtw0=base.values, theta_ref=theta_ref)

    def to_ll(arr):
        return base.copy(data=arr).rio.write_crs("EPSG:5070").rio.reproject("EPSG:4326")

    fig = plt.figure(figsize=(14, 8))
    gs = fig.add_gridspec(2, 3, hspace=0.34, wspace=0.34)
    _map(fig.add_subplot(gs[0, 0]), to_ll(dvv["dvv_low"] * 100), "RdBu_r",
         "Forward dv/v — low band (→ water table)", "dv/v (%)", vmin=-0.15, vmax=0.15)
    _map(fig.add_subplot(gs[0, 1]), to_ll(dvv["dvv_high"] * 100), "RdBu_r",
         "Forward dv/v — high band (→ soil moisture)", "dv/v (%)", vmin=-6, vmax=6)
    _map(fig.add_subplot(gs[0, 2]), to_ll(theta), "YlGnBu", "Modelled θ (2011-02)", "θ (m³/m³)")

    # recovery scatter
    ok = np.isfinite(dtw_anom) & np.isfinite(dtw_rec - base.values)
    axg = fig.add_subplot(gs[1, 0])
    xg, yg = dtw_anom[ok], (dtw_rec - base.values)[ok]
    axg.scatter(xg, yg, s=2, alpha=0.2, color=OI["tc"])
    axg.plot([xg.min(), xg.max()], [xg.min(), xg.max()], "k--", lw=1)
    axg.set_xlabel("modelled DTW anomaly (m)"); axg.set_ylabel("dv/v-derived (m)")
    axg.set_title(f"GWL recovered from dv/v  (r = {np.corrcoef(xg, yg)[0,1]:.2f})", fontsize=10.5)
    axg.grid(alpha=0.3)

    oks = np.isfinite(theta) & np.isfinite(theta_rec)
    axs = fig.add_subplot(gs[1, 1])
    xs, ys = theta[oks], theta_rec[oks]
    axs.scatter(xs, ys, s=2, alpha=0.2, color=OI["green"])
    axs.plot([xs.min(), xs.max()], [xs.min(), xs.max()], "k--", lw=1)
    axs.set_xlabel("modelled θ (m³/m³)"); axs.set_ylabel("dv/v-derived θ")
    axs.set_title(f"Soil moisture recovered from dv/v  (r = {np.corrcoef(xs, ys)[0,1]:.2f})", fontsize=10.5)
    axs.grid(alpha=0.3)

    axt = fig.add_subplot(gs[1, 2]); axt.axis("off")
    axt.text(0.0, 0.95, "dv/v → GWL & SM (frequency bands)", fontsize=11, fontweight="bold", va="top")
    axt.text(0.0, 0.80, "Low band  (deep, saturated):\n  (dv/v) = −S_sk·β·B·Δh  →  water table\n\n"
             "High band (shallow, vadose):\n  V_s=√(G/ρ_b), G∝P_e^(1/3)  →  θ\n\n"
             "Superposition: Δv_obs ≈ Δv_sat + Δv_vad\n"
             "Depth kernel:  Δv ≈ ∫ K(z) Δv(z) dz\n\n"
             "Demonstrative closed loop on modelled\nstates; real dv/v via ambient noise\n(codameter), parameters pending\nborehole calibration.",
             fontsize=8.5, va="top", color=INK, family="DejaVu Sans")

    fig.suptitle("dv/v coupling (demonstrative) — one observable derives both subsurface states",
                 fontsize=13, fontweight="bold", y=0.98)
    fig.savefig(OUT / "dvv_coupling.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "dvv_coupling.png")


if __name__ == "__main__":
    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    tc = xr.open_zarr(PROC / "terraclimate_monthly_puget.zarr")
    prism = xr.open_zarr(PROC / "prism_monthly_puget.zarr")
    fig_forcing_ensemble(env, tc, prism)
    fig_dvv_coupling(env, tc)
    print("done ->", OUT)
