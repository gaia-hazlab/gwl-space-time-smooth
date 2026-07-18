"""Coupled water-budget demo (issues #43, #44): recharge, capillary rise, runoff, lateral flow.

Three panels:
  1. Monthly fluxes (precip, AET, recharge, saturation-excess runoff, capillary rise) from the
     coupled column budget driven by real domain-mean TerraClimate forcing.
  2. The coupling in action: soil moisture theta and the water-table depth co-evolve -- recharge
     from the vadose column raises the table, and a shallow table feeds capillary rise back up.
  3. Subsurface lateral flow: the TOPMODEL steady-state water table over the real 90 m TWI field
     (valleys shallow/wet, ridges deep/dry).

Run:  pixi run python notebooks/make_water_budget_figure.py   (or: pixi run water-budget)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import numpy as np
import rioxarray as rxr
import xarray as xr

from src.models.water_budget import coupled_water_budget, topmodel_watertable
from src.viz.fonts import register_inter

mpl.use("Agg")
import matplotlib.pyplot as plt

PROC = Path("data/processed")
OUT = Path("figures/demo"); OUT.mkdir(parents=True, exist_ok=True)
ASSETS = Path("docs/assets"); ASSETS.mkdir(parents=True, exist_ok=True)
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
OI = {"precip": "#0072B2", "aet": "#E69F00", "recharge": "#009E73", "runoff": "#D55E00",
      "cap": "#CC79A7", "theta": "#009E73", "wt": "#0072B2"}


def _forcing():
    """Domain-mean monthly precip and PET from real TerraClimate; synthetic seasonal fallback."""
    try:
        tc = xr.open_zarr(PROC / "terraclimate_monthly_puget.zarr")
        P = np.asarray(tc["precip_mm"].mean(("lat", "lon")).values, "float64")
        PET = np.asarray(tc["pet_mm"].mean(("lat", "lon")).values, "float64")
        import pandas as pd
        t = pd.DatetimeIndex(tc.time.values)
        return P[:, None, None], PET[:, None, None], t, "TerraClimate (domain mean)"
    except Exception:
        import pandas as pd
        n = 60; k = np.arange(n)
        P = np.clip(70 + 60 * np.sin(2 * np.pi * (k - 2) / 12), 0, None)[:, None, None]
        PET = np.clip(55 + 50 * np.sin(2 * np.pi * k / 12), 0, None)[:, None, None]
        t = pd.date_range("2015-01-01", periods=n, freq="MS")
        return P, PET, t, "synthetic seasonal"


def main():
    register_inter(size=11)
    plt.rcParams.update({"axes.titlecolor": INK, "axes.titleweight": "bold",
                         "axes.edgecolor": MUTED, "figure.dpi": 130})
    P, PET, t, src = _forcing()
    wp, fc, sat = np.array([[0.12]]), np.array([[0.28]]), np.array([[0.45]])
    wb = coupled_water_budget(P, PET, wp, fc, sat, root_depth_m=1.0, wt_depth0_m=4.0)

    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6), gridspec_kw={"width_ratios": [1.25, 1.1, 1.0]})

    # panel 1: fluxes
    a = ax[0]
    a.plot(t, P[:, 0, 0], color=OI["precip"], lw=1.4, label="precip in")
    a.plot(t, wb.aet_mm[:, 0, 0], color=OI["aet"], lw=1.2, label="AET")
    a.plot(t, wb.recharge_mm[:, 0, 0], color=OI["recharge"], lw=1.4, label="recharge → water table")
    a.plot(t, wb.runoff_mm[:, 0, 0], color=OI["runoff"], lw=1.2, label="sat-excess runoff")
    a.plot(t, wb.cap_rise_mm[:, 0, 0], color=OI["cap"], lw=1.2, ls="--", label="capillary rise ↑")
    a.set_ylabel("flux (mm / month)"); a.set_title(f"Coupled water-budget fluxes\n({src})", fontsize=15)
    a.legend(fontsize=12, ncol=2); a.grid(color=GRID, lw=0.5)

    # panel 2: theta and water table co-evolving
    a = ax[1]
    a.plot(t, wb.theta[:, 0, 0], color=OI["theta"], lw=1.6, label="soil moisture θ")
    a.set_ylabel("θ (m³/m³)", color=OI["theta"]); a.tick_params(axis="y", colors=OI["theta"])
    a2 = a.twinx()
    a2.plot(t, wb.wt_depth_m[:, 0, 0], color=OI["wt"], lw=1.6, label="water-table depth")
    a2.set_ylabel("water-table depth (m)", color=OI["wt"]); a2.tick_params(axis="y", colors=OI["wt"])
    a2.invert_yaxis()                                        # shallower = up
    a.set_title("θ ↔ water table coupling\n(recharge raises the table)", fontsize=15)
    a.grid(color=GRID, lw=0.5)

    # panel 3: TOPMODEL water table over real TWI
    a = ax[2]
    try:
        twi = rxr.open_rasterio(PROC / "terrain_twi_90m.tif", masked=True).squeeze("band", drop=True)
        twi_ll = twi.rio.reproject("EPSG:4326")
        step = max(twi_ll.shape[0] // 200, 1)
        twis = twi_ll.values[::step, ::step]
        d = topmodel_watertable(wb.wt_depth_m[:, 0, 0].mean(), twis)
        x = twi_ll.x.values[::step]; y = twi_ll.y.values[::step]
        im = a.imshow(d, extent=[x.min(), x.max(), y.min(), y.max()], origin="upper",
                      cmap="YlGnBu_r", aspect="auto")
        fig.colorbar(im, ax=a, shrink=0.85, label="water-table depth (m)")
        a.set_title("Subsurface lateral flow (TOPMODEL)\nshallow=blue (valleys), deep=pale (ridges)",
                    fontsize=15)
        a.set_xticks([]); a.set_yticks([])
    except Exception as exc:
        a.text(0.5, 0.5, f"TWI unavailable\n{exc}", ha="center", va="center", transform=a.transAxes)

    fig.suptitle("Closing the water budget: vertical recharge + capillary rise (#43) and "
                 "saturation-excess runoff + TOPMODEL lateral flow (#44)",
                 fontsize=15, fontweight="bold", color=INK, y=1.02)
    fig.tight_layout()
    for p in (OUT / "water_budget.png", ASSETS / "water_budget.png"):
        fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "water_budget.png",
          f"| total recharge {wb.recharge_mm.sum():.0f} mm, runoff {wb.runoff_mm.sum():.0f} mm, "
          f"cap rise {wb.cap_rise_mm.sum():.0f} mm")


if __name__ == "__main__":
    main()
