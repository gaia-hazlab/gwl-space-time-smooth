"""90 m time-varying products: animated GIFs + a downscaling uncertainty budget.

Produces, over one shared window (default 2010-04 → 2013-03, dense well coverage):
  * figures/demo/gwl_90m.gif        — depth-to-water evolving month by month (90 m).
  * figures/demo/theta_90m.gif      — soil moisture θ evolving month by month (90 m).
  * figures/demo/uncertainty_budget.png — per-product σ maps + static/dynamic/downscaling split.
  * data/processed/provenance.json  — every source → operation → resolution step (for the page).

Both products share the fine-static + coarse-dynamic + statistical-downscaling design, so the
GIFs and the budget make the 90 m resolution — and the cost of getting there — explicit.

Run:  pixi run python notebooks/make_products_90m.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path for `src`

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr
from matplotlib.animation import FuncAnimation, PillowWriter
from pyproj import Transformer

from src.models.gwl_dynamic import gwl_dynamic_90m
from src.models.soil_moisture import soil_moisture_90m

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
OUT.mkdir(parents=True, exist_ok=True)

WINDOW = ("2010-04-01", "2013-03-01")
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"gwl": "#0072B2", "sm": "#009E73", "static": "#0072B2", "dynamic": "#E69F00", "downscaling": "#D55E00"}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titlecolor": INK, "text.color": INK})


def _extent_ll(da):
    ll = da.rio.reproject("EPSG:4326")
    x, y = ll.x.values, ll.y.values
    return ll, [float(x.min()), float(x.max()), float(y.min()), float(y.max())]


def _make_gif(stack, template_da, times, cmap, label, title, path, vlims):
    """Animate a (t,y,x) stack over the 90 m grid → GIF (reprojected to lon/lat for display)."""
    vmin, vmax = vlims
    # Reproject each frame to WGS84 for clean lon/lat axes.
    ll0, ext = _extent_ll(template_da.copy(data=stack[0]))
    fig, ax = plt.subplots(figsize=(5.0, 5.4))
    im = ax.imshow(ll0.values, extent=ext, origin="upper", cmap=cmap, vmin=vmin, vmax=vmax,
                   aspect="auto", interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label(label, fontsize=13)
    ax.set_title(title, fontsize=15, fontweight="bold")
    txt = ax.text(0.03, 0.96, "", transform=ax.transAxes, fontsize=15, fontweight="bold",
                  va="top", ha="left", color=INK,
                  bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=GRID, alpha=0.85))
    ax.tick_params(labelsize=12)

    def update(i):
        frame = template_da.copy(data=stack[i]).rio.reproject("EPSG:4326")
        im.set_data(frame.values)
        txt.set_text(pd.Timestamp(times[i]).strftime("%Y-%m"))
        return im, txt

    anim = FuncAnimation(fig, update, frames=len(stack), blit=False)
    anim.save(path, writer=PillowWriter(fps=4))
    plt.close(fig)
    print("wrote", path, f"({len(stack)} frames)")


def _budget_figure(theta_da, th_budget, dtw_da, gwl_budget, path):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), gridspec_kw={"width_ratios": [1.25, 1]})
    for row, (name, da, bud, cmap, unit) in enumerate([
        ("Soil moisture θ", theta_da, th_budget, "magma", "m³/m³"),
        ("Groundwater DTW", dtw_da, gwl_budget, "magma", "m"),
    ]):
        tot = bud.total()
        ll, ext = _extent_ll(da.copy(data=tot))
        ax = axes[row, 0]
        v = tot[np.isfinite(tot)]
        im = ax.imshow(ll.values, extent=ext, origin="upper", cmap=cmap,
                       vmax=float(np.nanpercentile(v, 97)), aspect="auto")
        ax.set_title(f"{name} — total 1σ", fontsize=15, fontweight="bold")
        ax.tick_params(labelsize=12)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label(unit, fontsize=13)

        ax2 = axes[row, 1]
        fr = bud.fractions()
        keys = list(fr.keys())
        bottom = 0.0
        for k in keys:
            c = OI.get(k.split("_")[0], "#888")
            ax2.bar(0, fr[k], bottom=bottom, width=0.5, color=c, label=k.replace("_", " "))
            if fr[k] > 0.04:
                ax2.text(0, bottom + fr[k] / 2, f"{fr[k]*100:.0f}%", ha="center", va="center",
                         color="white", fontweight="bold", fontsize=13)
            bottom += fr[k]
        ax2.set_ylim(0, 1); ax2.set_xlim(-0.6, 1.4); ax2.set_xticks([])
        ax2.set_ylabel("variance share")
        ax2.set_title(f"{name} — σ² budget\n(median total σ = {np.nanmedian(tot):.3g} {unit})",
                      fontsize=13, fontweight="bold")
        ax2.legend(fontsize=12, loc="center left", bbox_to_anchor=(0.55, 0.5), frameon=False)
        for s in ("top", "right"):
            ax2.spines[s].set_visible(False)
    fig.suptitle("Uncertainty budget — static (fine) ⊕ dynamic (coarse) ⊕ downscaling (representativeness)",
                 fontsize=16, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", path)


def main():
    base = rxr.open_rasterio(PROC / "baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    rfs = rxr.open_rasterio(PROC / "baseline_rf_std_m.tif", masked=True).squeeze("band", drop=True)
    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    drv = xr.open_zarr(PROC / "terraclimate_monthly_puget.zarr")

    m = pd.read_parquet(PROC / "nwis_gwlevels_monthly.parquet")
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    m["x_5070"], m["y_5070"] = tf.transform(m.lon.values, m.lat.values)
    m["date"] = pd.to_datetime(dict(year=m.year, month=m.month, day=1))
    L, B, R, T = base.rio.bounds()
    pin = m[(m.x_5070 >= L) & (m.x_5070 <= R) & (m.y_5070 >= B) & (m.y_5070 <= T)]

    # --- GWL time-varying at 90 m ---
    g_times, dtw, gwl_budget = gwl_dynamic_90m(pin, base, rfs, WINDOW, coarse_res_m=2000.0)

    # --- θ at 90 m for the SAME months (align frames) ---
    drv_t = pd.DatetimeIndex(drv.time.values)
    idx = [int(np.where((drv_t.year == pd.Timestamp(t).year) & (drv_t.month == pd.Timestamp(t).month))[0][0])
           for t in g_times]
    t_times, theta, th_budget = soil_moisture_90m(env, drv, times=idx, downscaler="twi")

    # --- GIFs (fixed colour limits across frames) ---
    tv = theta[np.isfinite(theta)]
    dv = dtw[np.isfinite(dtw)]
    _make_gif(theta, env["theta_fc"].rio.write_crs("EPSG:5070"), t_times, "YlGnBu", "θ (m³/m³)",
              "Soil moisture θ — 90 m", OUT / "theta_90m.gif",
              (float(np.nanpercentile(tv, 3)), float(np.nanpercentile(tv, 97))))
    _make_gif(dtw, base, g_times, "cividis_r", "DTW (m below surface)",
              "Groundwater depth-to-water — 90 m", OUT / "gwl_90m.gif",
              (float(np.nanpercentile(dv, 3)), float(np.nanpercentile(dv, 97))))

    # --- Uncertainty budget figure ---
    _budget_figure(env["theta_fc"].rio.write_crs("EPSG:5070"), th_budget, base, gwl_budget,
                   OUT / "uncertainty_budget.png")

    # --- Provenance table (both products) ---
    prov = {
        "window": [WINDOW[0][:7], WINDOW[1][:7]], "n_months": len(g_times), "target_res_m": 90.0,
        "soil_moisture": [s.as_row() for s in th_budget.provenance],
        "groundwater": [s.as_row() for s in gwl_budget.provenance],
        "budget_fractions": {"soil_moisture": th_budget.fractions(), "groundwater": gwl_budget.fractions()},
        "median_total_sigma": {"soil_moisture_m3m3": float(np.nanmedian(th_budget.total())),
                                "groundwater_m": float(np.nanmedian(gwl_budget.total()))},
    }
    (PROC / "provenance.json").write_text(json.dumps(prov, indent=2))
    print("wrote", PROC / "provenance.json")
    print(f"done — {len(g_times)} months {WINDOW[0][:7]}..{WINDOW[1][:7]}")


if __name__ == "__main__":
    main()
