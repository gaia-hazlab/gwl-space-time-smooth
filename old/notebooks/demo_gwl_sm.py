"""Demo figures: coupled GWL + soil-moisture state over the Puget Sound pilot.

Renders three publication-style PNGs into ``figures/demo/`` from the real, already-computed
products (no synthetic data):

  1. gwl_state.png            — groundwater level: DTW map + σ + feature importance +
                                spatial block-CV + a 24-yr well hydrograph.
  2. soil_moisture_state.png  — soil moisture: static SOLUS→Saxton-Rawls envelope (90 m) +
                                wet/dry θ maps + the 2000–2024 θ series vs TerraClimate soil.
  3. coupled_overview.png     — the two state variables side by side (the "reanalysis" view).

Colour: CVD-safe sequential/diverging colormaps (viridis/cividis/YlGnBu/RdBu) for
magnitude/polarity; Okabe-Ito categorical hues for bars/lines. One y-axis per plot.

Run:  pixi run python notebooks/demo_gwl_sm.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr
from pyproj import Transformer

mpl.use("Agg")

PROC = Path("data/processed")
OUT = Path("figures/demo")
OUT.mkdir(parents=True, exist_ok=True)

# Okabe-Ito colourblind-safe categorical palette (fixed order, never cycled).
OI = {
    "blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "vermillion": "#D55E00",
    "sky": "#56B4E9", "yellow": "#F0E442", "purple": "#CC79A7", "black": "#111111",
}
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 150, "font.size": 10,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "font.family": "DejaVu Sans",
})


def _to_wgs84(path: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(path, masked=True).squeeze("band", drop=True)
    return da.rio.reproject("EPSG:4326")


def _map(ax, da, cmap, title, cbar_label, vmin=None, vmax=None, wells=None):
    x = da.x.values if "x" in da.coords else da.lon.values
    y = da.y.values if "y" in da.coords else da.lat.values
    ext = [float(x.min()), float(x.max()), float(y.min()), float(y.max())]
    im = ax.imshow(da.values, extent=ext, origin="upper", cmap=cmap, vmin=vmin, vmax=vmax,
                   aspect="auto", interpolation="nearest")
    if wells is not None:
        ax.scatter(wells[0], wells[1], s=6, c="#111111", edgecolors="white",
                   linewidths=0.3, alpha=0.8, zorder=5, label="NWIS wells")
    ax.set_title(title, fontsize=10.5)
    ax.tick_params(labelsize=8)
    ax.grid(False)
    cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label(cbar_label, fontsize=8.5, labelpad=2); cb.ax.tick_params(labelsize=8)
    return im


# ---------------------------------------------------------------------------
# Load shared data
# ---------------------------------------------------------------------------
sites = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
# pilot bbox from the 90 m grid
_hand = rioxarray.open_rasterio(PROC / "terrain_hand_90m.tif")
L, B, R, T = _hand.rio.bounds()
sx, sy = tf.transform(sites.lon.values, sites.lat.values)
pin = (sx >= L) & (sx <= R) & (sy >= B) & (sy <= T)
well_lon, well_lat = sites.lon.values[pin], sites.lat.values[pin]

monthly = pd.read_parquet(PROC / "nwis_gwlevels_monthly.parquet")


# ---------------------------------------------------------------------------
# FIGURE 1 — Groundwater level state
# ---------------------------------------------------------------------------
def fig_gwl():
    dtw = _to_wgs84(PROC / "baseline_dtw_m.tif")
    rf = _to_wgs84(PROC / "baseline_rf_std_m.tif")
    kr = _to_wgs84(PROC / "baseline_kriging_std_m.tif")
    sigma = np.sqrt(rf ** 2 + kr ** 2)

    fig = plt.figure(figsize=(15, 8.4))
    gs = fig.add_gridspec(2, 3, hspace=0.36, wspace=0.42,
                          height_ratios=[1.15, 1.0])

    ax0 = fig.add_subplot(gs[0, 0])
    v = dtw.values[np.isfinite(dtw.values)]
    _map(ax0, dtw, "cividis_r", "Depth to water table (baseline)", "DTW (m below surface)",
         vmin=float(np.nanpercentile(v, 2)), vmax=float(np.nanpercentile(v, 98)),
         wells=(well_lon, well_lat))
    ax0.legend(loc="upper right", fontsize=7, framealpha=0.85, markerscale=1.2)

    ax1 = fig.add_subplot(gs[0, 1])
    sv = sigma.values[np.isfinite(sigma.values)]
    _map(ax1, sigma, "magma", "Prediction uncertainty (1σ)", "σ (m)",
         vmax=float(np.nanpercentile(sv, 97)))

    # Feature importance
    ax2 = fig.add_subplot(gs[0, 2])
    fi = json.loads((PROC / "rf_feature_importance.json").read_text())
    order = sorted(fi, key=fi.get)
    vals = [fi[k] for k in order]
    labels = [k.replace("_", " ") for k in order]
    colors = [OI["blue"] if k == "hand_m" else OI["sky"] for k in order]
    ax2.barh(labels, vals, color=colors, height=0.66)
    for yy, vv in zip(range(len(vals)), vals):
        ax2.text(vv + 0.008, yy, f"{vv:.2f}", va="center", fontsize=8.5, color=INK)
    ax2.set_xlim(0, max(vals) * 1.22)
    ax2.set_title("RF feature importance\n(HAND dominant — no lat/lon)", fontsize=10.5)
    ax2.set_xlabel("importance"); ax2.grid(axis="y", visible=False)

    # Spatial block-CV
    ax3 = fig.add_subplot(gs[1, 0])
    cv = json.loads((PROC / "block_cv_metrics.json").read_text())["pooled"]
    folds = cv["folds"]
    fids = sorted(folds, key=int)
    rmse = [folds[f]["rmse"] for f in fids]
    mae = [folds[f]["mae"] for f in fids]
    xpos = np.arange(len(fids))
    ax3.bar(xpos - 0.2, rmse, width=0.38, color=OI["vermillion"], label="RMSE")
    ax3.bar(xpos + 0.2, mae, width=0.38, color=OI["orange"], label="MAE")
    ax3.axhline(cv["rmse_mean"], color=OI["vermillion"], ls="--", lw=1,
                label=f"pooled RMSE {cv['rmse_mean']:.1f} m")
    ax3.set_xticks(xpos); ax3.set_xticklabels([f"fold {f}" for f in fids], fontsize=8)
    ax3.set_ylabel("error (m)"); ax3.set_title("Spatial block cross-validation", fontsize=10.5)
    ax3.legend(fontsize=7.5, loc="upper left"); ax3.grid(axis="x", visible=False)

    # Well hydrograph (best-recorded pilot well)
    ax4 = fig.add_subplot(gs[1, 1:])
    site = "471032122292701"
    ts = monthly[monthly.site_no == site].copy()
    ts["date"] = pd.to_datetime(dict(year=ts.year, month=ts.month, day=15))
    ts = ts.sort_values("date")
    ax4.plot(ts.date, ts.dtw_m, color=OI["blue"], lw=1.3, marker="o", ms=2.6,
             mfc=OI["blue"], mec="white", mew=0.2)
    ax4.invert_yaxis()
    ax4.set_ylabel("DTW (m below surface)")
    ax4.set_title(f"Observed monthly hydrograph — well {site}  ({len(ts)} months, "
                  f"{int(ts.year.min())}–{int(ts.year.max())})", fontsize=10.5)
    ax4.grid(axis="x", visible=False)

    fig.suptitle("Groundwater level — observation-anchored RF baseline + kriged residuals "
                 "(Puget Sound pilot, 90 m)", fontsize=13, fontweight="bold", y=0.99)
    fig.savefig(OUT / "gwl_state.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "gwl_state.png")


# ---------------------------------------------------------------------------
# FIGURE 2 — Soil-moisture state
# ---------------------------------------------------------------------------
def fig_sm():
    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    env_ll = env.rio.reproject("EPSG:4326")
    sm = xr.open_zarr(PROC / "soil_moisture_monthly_puget.zarr").load()

    time = pd.DatetimeIndex(sm.time.values)
    theta_dm = sm.theta.mean(("lat", "lon")).values
    tc = sm.tc_soil_mm.mean(("lat", "lon")).values
    # pick a wet month and a dry month by domain-mean θ
    wet_i = int(np.argmax(theta_dm)); dry_i = int(np.argmin(theta_dm))

    fig = plt.figure(figsize=(15, 8.4))
    gs = fig.add_gridspec(2, 3, hspace=0.36, wspace=0.42, height_ratios=[1.15, 1.0])

    ax0 = fig.add_subplot(gs[0, 0])
    _map(ax0, env_ll["theta_sat"], "YlGnBu", "Porosity θ_sat (static, SOLUS→PTF)",
         "θ_sat (m³/m³)")
    ax1 = fig.add_subplot(gs[0, 1])
    _map(ax1, env_ll["theta_fc"], "YlGnBu", "Field capacity θ_fc (static)", "θ_fc (m³/m³)")
    ax2 = fig.add_subplot(gs[0, 2])
    _map(ax2, env_ll["awc_mm"], "YlOrBr", "Available water capacity (static)", "AWC (mm)")

    vmin = float(np.nanpercentile(sm.theta.values, 3))
    vmax = float(np.nanpercentile(sm.theta.values, 97))
    ax3 = fig.add_subplot(gs[1, 0])
    _map(ax3, sm.theta.isel(time=wet_i), "YlGnBu",
         f"θ — wettest month ({time[wet_i]:%Y-%m})", "θ (m³/m³)", vmin=vmin, vmax=vmax)
    ax4 = fig.add_subplot(gs[1, 1])
    _map(ax4, sm.theta.isel(time=dry_i), "YlGnBu",
         f"θ — driest month ({time[dry_i]:%Y-%m})", "θ (m³/m³)", vmin=vmin, vmax=vmax)

    # θ time series vs TerraClimate soil (PEER water-balance model, shares our P&PET forcing):
    # standardised on ONE axis. Thin raw monthly (seasonal) + bold 13-month rolling mean.
    ax5 = fig.add_subplot(gs[1, 2])
    z = lambda a: (a - np.nanmean(a)) / np.nanstd(a)
    r = np.corrcoef(theta_dm, tc)[0, 1]
    zt, zc = z(theta_dm), z(tc)
    roll = lambda a: pd.Series(a).rolling(13, center=True, min_periods=7).mean().values
    ax5.plot(time, zt, color=OI["green"], lw=0.6, alpha=0.4)
    ax5.plot(time, zc, color=OI["purple"], lw=0.6, alpha=0.4)
    ax5.plot(time, roll(zt), color=OI["green"], lw=2.0, label="our θ (SOLUS × T-M)")
    ax5.plot(time, roll(zc), color=OI["purple"], lw=1.6, label="TerraClimate soil (peer model)")
    ax5.set_ylabel("standardised anomaly (z)")
    ax5.set_title(f"θ vs peer water balance — consistency (r = {r:.2f})", fontsize=10.5)
    ax5.legend(fontsize=7.5, loc="lower left", ncol=1, framealpha=0.9)
    ax5.grid(axis="x", visible=False)

    fig.suptitle("Soil moisture — static SOLUS→Saxton-Rawls envelope × dynamic TerraClimate "
                 "water balance (2000–2024)", fontsize=13, fontweight="bold", y=0.99)
    fig.savefig(OUT / "soil_moisture_state.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "soil_moisture_state.png")


# ---------------------------------------------------------------------------
# FIGURE 3 — Coupled overview (the two state variables together)
# ---------------------------------------------------------------------------
def fig_coupled():
    dtw = _to_wgs84(PROC / "baseline_dtw_m.tif")
    sm = xr.open_zarr(PROC / "soil_moisture_monthly_puget.zarr").load()
    time = pd.DatetimeIndex(sm.time.values)
    theta_dm = sm.theta.mean(("lat", "lon")).values
    theta_clim = pd.Series(theta_dm, index=time.month).groupby(level=0).mean()

    fig = plt.figure(figsize=(15, 4.6))
    gs = fig.add_gridspec(1, 3, wspace=0.4, width_ratios=[1, 1, 1.05])

    ax0 = fig.add_subplot(gs[0, 0])
    v = dtw.values[np.isfinite(dtw.values)]
    _map(ax0, dtw, "cividis_r", "Groundwater — DTW", "m below surface",
         vmin=float(np.nanpercentile(v, 2)), vmax=float(np.nanpercentile(v, 98)),
         wells=(well_lon, well_lat))

    ax1 = fig.add_subplot(gs[0, 1])
    _map(ax1, sm.theta.mean("time"), "YlGnBu", "Soil moisture — mean θ", "m³/m³")

    ax2 = fig.add_subplot(gs[0, 2])
    months = np.arange(1, 13)
    ax2.plot(months, theta_clim.values, color=OI["green"], lw=1.8, marker="o", ms=4,
             mfc=OI["green"], mec="white")
    ax2.fill_between(months, theta_clim.values, theta_clim.values.min(),
                     color=OI["green"], alpha=0.12)
    ax2.set_xticks(months)
    ax2.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax2.set_ylabel("θ (m³/m³)")
    ax2.set_title("Seasonal cycle — wet winter, summer drought", fontsize=10.5)
    ax2.grid(axis="x", visible=False)

    fig.suptitle("Coupled subsurface state — groundwater level + soil moisture from one "
                 "data-driven pipeline (Puget Sound pilot)", fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "coupled_overview.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "coupled_overview.png")


if __name__ == "__main__":
    fig_gwl()
    fig_sm()
    fig_coupled()
    print("done ->", OUT)
