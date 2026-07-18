"""Capillary hysteresis: the retention loop and the velocity loop it produces (#120).

Run: ``pixi run hysteresis-demo``

Left: water content vs suction traces a LOOP between the main drying and wetting curves, not a single
line — and a mid-season re-wetting opens an inner scanning loop, the soil's memory of the reversal.
Right: the same path in the observable, V_s(theta): at equal moisture the drying limb is STIFFER (higher
velocity, higher dv/v) than the wetting limb. This is what the single-valued map in the twin cannot
represent, and what a measured dv/v is sensitive to.
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path("figures/demo/hysteresis_loop.png")
ASSETS = Path("docs/twin/assets")
ALPHA_D, N = 0.05, 1.6          # silty-loam-ish bounding pair
THETA_R, PHI = 0.06, 0.42


def _coloured_path(ax, x, y, cmap="viridis", lw=3.0):
    pts = np.array([x, y]).T.reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    lc = LineCollection(segs, cmap=cmap, lw=lw, zorder=4)
    lc.set_array(np.linspace(0, 1, len(x)))
    ax.add_collection(lc)
    return lc


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.models.hysteresis import hysteretic_vs_loop, vg_suction, vs_from_suction

    # a seasonal moisture path: wet up (winter), dry down (summer) with a mid-drying storm (scanning loop)
    theta = np.concatenate([
        np.linspace(0.12, 0.36, 60),      # wetting
        np.linspace(0.36, 0.20, 40),      # drying
        np.linspace(0.20, 0.28, 15),      # a summer storm re-wets
        np.linspace(0.28, 0.12, 45),      # drying out
    ])
    out = hysteretic_vs_loop(theta, THETA_R, PHI, ALPHA_D, N, start="wetting")

    # bounding curves over the full moisture range
    tg = np.linspace(THETA_R + 1e-3, PHI - 1e-3, 200)
    se_g = (tg - THETA_R) / (PHI - THETA_R)
    hd_g = vg_suction(se_g, ALPHA_D, N)
    hw_g = vg_suction(se_g, 2.0 * ALPHA_D, N)
    vs_d = vs_from_suction(tg, se_g, hd_g, PHI)
    vs_w = vs_from_suction(tg, se_g, hw_g, PHI)

    fig, ax = plt.subplots(1, 2, figsize=(15.5, 6.4), constrained_layout=True)

    # --- panel 1: retention loop ---
    ax[0].plot(tg, hd_g, color="#B00020", lw=2.2, label="main drying curve")
    ax[0].plot(tg, hw_g, color="#2E86AB", lw=2.2, ls="--", label="main wetting curve")
    lc = _coloured_path(ax[0], theta, out["suction"])
    ax[0].set_yscale("log")
    ax[0].set_xlabel("volumetric water content  θ  [m³ m⁻³]")
    ax[0].set_ylabel("matric suction  [kPa]  (log)")
    ax[0].set_title("Retention is a LOOP, not a line", fontweight="bold")
    ax[0].set_xlim(THETA_R, PHI)
    ax[0].legend(loc="upper right", framealpha=.92)
    ax[0].annotate("summer storm\n(inner scanning loop)", xy=(0.26, np.interp(0.26, theta[100:115], out["suction"][100:115])),
                   xytext=(0.30, 40), fontsize=12, color="#333",
                   arrowprops=dict(arrowstyle="->", color="#333"))

    # --- panel 2: the observable loop ---
    ax[1].plot(tg, vs_d, color="#B00020", lw=2.0, label="drying bound")
    ax[1].plot(tg, vs_w, color="#2E86AB", lw=2.0, ls="--", label="wetting bound")
    ax[1].plot(tg, np.interp(tg, tg, (vs_d + vs_w) / 2), color="#999", lw=1.4, ls=":",
               label="single-valued (current model)")
    _coloured_path(ax[1], theta, out["vs"])
    ax[1].set_xlabel("volumetric water content  θ  [m³ m⁻³]")
    ax[1].set_ylabel("shear-wave velocity  Vₛ  [m s⁻¹]")
    ax[1].set_title("The velocity the twin measures is a LOOP too", fontweight="bold")
    ax[1].set_xlim(THETA_R, PHI)
    ax[1].legend(loc="upper right", framealpha=.92)
    # annotate the vertical gap at a fixed moisture
    t0 = 0.24
    vlo, vhi = np.interp(t0, tg, vs_w), np.interp(t0, tg, vs_d)
    ax[1].annotate("", xy=(t0, vhi), xytext=(t0, vlo),
                   arrowprops=dict(arrowstyle="<->", color="#333", lw=1.6))
    ax[1].text(t0 + 0.005, (vlo + vhi) / 2, "same θ,\nstiffer on drying", fontsize=12, color="#333")

    cb = fig.colorbar(lc, ax=ax, shrink=.7, pad=0.01)
    cb.set_label("time along the path  (wetting → drying)")
    fig.suptitle("Capillary hysteresis — the soil state's memory of its wetting/drying path "
                 "(Kool–Parker scanning curves; coupled to the twin's Hertz–Mindlin velocity map)",
                 fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=125, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    gap = float(np.nanmax(out["vs"]) - np.nanmin(out["vs"]))
    print("wrote %s  (Vs loop spans %.0f m/s; drying vs wetting Vs gap at θ=0.24 is %.0f m/s)"
          % (OUT, gap, vhi - vlo))


if __name__ == "__main__":
    main()
