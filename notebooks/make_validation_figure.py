"""The validation money-plot: the calibrated twin vs gauges AND wells.

Run: ``pixi run validation-figure``
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/validation_domain.png")
BFI_OBS, QP_OBS, AMP_OBS = 0.47, 0.65, 1.06


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    # imported inside main(): `setup()` runs a full 300-day solve, so importing this module must not
    # trigger it (Copilot, PR #102).
    from notebooks.calibrate_fluxes import setup
    from src.models.water_budget import (
        K_ANISO,
        RECHARGE_REF_MM_DAY,
        SPECIFIC_YIELD,
        coupled_water_budget,
    )

    liquid, E, env, d0, hd, tb, rd, times, land, Ptot = setup()
    r = coupled_water_budget(liquid, E, env["theta_wp"], env["theta_fc"], env["theta_sat"],
                             root_depth_m=rd, wt_depth0_m=d0, dt_days=1.0,
                             slope_tan=tb, hand_m=hd)
    M = lambda a: float(np.nanmean(np.nansum(a, 0)[land]))   # noqa: E731
    ro, it, bf, rc = M(r.runoff_mm), M(r.interflow_mm), M(r.baseflow_mm), M(r.recharge_mm)
    Q = ro + it + bf
    rise = d0[None, :, :] - r.wt_depth_m
    ser = np.array([np.nanmean(rise[i][land]) for i in range(len(times))])
    mon = pd.Series(ser, index=times).groupby(times.month).mean()

    w = pd.read_parquet("data/processed/nwis_gwlevels_monthly.parquet")
    w = w[~w.is_deep_well].dropna(subset=["dtw_m"])
    w["anom"] = w.dtw_m - w.groupby("site_no").dtw_m.transform("mean")
    obs = -(w.groupby("month").anom.mean())

    C_M, C_O = "#7B2D8B", "#2E86AB"
    fig, ax = plt.subplots(1, 3, figsize=(14.5, 4.5), constrained_layout=True)

    names = ["Baseflow\nindex", "Runoff coef.\nQ/P", "Seasonal\namplitude (m)"]
    mod = [bf / Q, Q / Ptot, float(mon.max() - mon.min())]
    obsv = [BFI_OBS, QP_OBS, AMP_OBS]
    x, wd = np.arange(3), 0.35
    ax[0].bar(x - wd / 2, mod, wd, color=C_M, label="model (calibrated)")
    ax[0].bar(x + wd / 2, obsv, wd, color=C_O, label="OBSERVED")
    for i, (a, b) in enumerate(zip(mod, obsv)):
        ax[0].text(i - wd / 2, a + .02, "%.2f" % a, ha="center", fontsize=13, fontweight="bold")
        ax[0].text(i + wd / 2, b + .02, "%.2f" % b, ha="center", fontsize=13)
    ax[0].set_xticks(x)
    ax[0].set_xticklabels(names, fontsize=13)
    ax[0].set_title("Calibrated against gauges AND wells", fontweight="bold")
    ax[0].legend(fontsize=12, frameon=False)
    ax[0].set_ylim(0, 1.35)
    ax[0].text(.5, -.28, "gauges → fluxes    wells → state", transform=ax[0].transAxes,
               ha="center", fontsize=12, style="italic", color="#555")

    order = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6]
    lab = ["S", "O", "N", "D", "J", "F", "M", "A", "M", "J"]
    mm = np.array([mon.get(m, np.nan) for m in order])
    oo = np.array([obs.get(m, np.nan) for m in order])
    mm, oo = mm - np.nanmean(mm), oo - np.nanmean(oo)
    ax[1].plot(range(10), mm, "o-", color=C_M, lw=2, label="model")
    ax[1].plot(range(10), oo, "s--", color=C_O, lw=2, label="observed wells (26,816 obs)")
    ax[1].axvline(7, color="#bbb", lw=1, ls=":")
    ax[1].text(7.05, ax[1].get_ylim()[1] * .8, "April\n(snowmelt peak)", fontsize=12, color="#555")
    ax[1].set_xticks(range(10))
    ax[1].set_xticklabels(lab)
    ax[1].set_ylabel("water-table anomaly (m)")
    ax[1].set_title("Seasonal cycle — the snowmelt clock", fontweight="bold")
    ax[1].legend(fontsize=12, frameon=False)
    ax[1].grid(alpha=.25)

    lbls = ["runoff", "interflow", "baseflow\n(→rivers)", "recharge\n(retained)"]
    vals = [ro, it, bf, rc - bf]
    cols = ["#E84855", "#F6AE2D", "#2E86AB", "#3BB273"]
    ax[2].barh(range(4), vals, color=cols)
    for i, v in enumerate(vals):
        ax[2].text(v + 12, i, "%.0f mm" % v, va="center", fontsize=13)
    ax[2].set_yticks(range(4))
    ax[2].set_yticklabels(lbls, fontsize=13)
    ax[2].invert_yaxis()
    ax[2].set_xlabel("mm over the wet season (P = %.0f mm)" % Ptot)
    ax[2].set_title("Where the water goes", fontweight="bold")
    ax[2].set_xlim(0, max(vals) * 1.32)

    fig.suptitle("GAIA Digital Twin of Soil — the water budget closes against observations\n"
                 "Ka=%.0f · S_y=%.2f · R_ref=%.1f mm/d   (each pinned by a DIFFERENT observation)"
                 % (K_ANISO, SPECIFIC_YIELD, RECHARGE_REF_MM_DAY), fontsize=15, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)      # fresh clone has no assets dir; copy would raise
    fig.savefig(OUT, dpi=130, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
