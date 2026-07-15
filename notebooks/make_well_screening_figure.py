"""Well hydrostratigraphic screening diagnostic (issue #46).

Shows why the DTW target must be depth-screened: shallow water-table wells and deep confined-outwash
wells are two populations with very different heads, and HAND can only predict the shallow one.

  1. Well-depth histogram coloured by hydro class, with the shallow/deep thresholds.
  2. Median DTW vs well depth -- deeper wells sit at a deeper (potentiometric) level (the mixing).
  3. Map of shallow water-table vs deep-confined wells over the pilot.

Run:  pixi run python notebooks/make_well_screening_figure.py   (or: pixi run well-screen)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import numpy as np
import pandas as pd

from src.features.well_hydrostratigraphy import (
    DEEP_MIN_M,
    SHALLOW_MAX_M,
    classify_well_hydro,
    screening_summary,
)
from src.viz.fonts import register_inter

mpl.use("Agg")
import matplotlib.pyplot as plt

PROC = Path("data/processed")
OUT = Path("figures/demo"); OUT.mkdir(parents=True, exist_ok=True)
ASSETS = Path("docs/assets"); ASSETS.mkdir(parents=True, exist_ok=True)
INK, MUTED, GRID = "#1a1a2e", "#5a5a6e", "#d9d9e0"
COL = {"shallow_watertable": "#0072B2", "ambiguous": "#E69F00", "deep_confined": "#D55E00"}
LAB = {"shallow_watertable": "shallow water table", "ambiguous": "ambiguous",
       "deep_confined": "deep confined"}


def main():
    register_inter(size=11)
    plt.rcParams.update({"axes.titlecolor": INK, "axes.titleweight": "bold",
                         "axes.edgecolor": MUTED, "figure.dpi": 130})
    d = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    cls = classify_well_hydro(d)
    depth = pd.to_numeric(d.well_depth_m, errors="coerce")
    dtw = pd.to_numeric(d.median_dtw_m, errors="coerce")
    summ = screening_summary(d)

    fig, ax = plt.subplots(1, 3, figsize=(15.5, 4.6), gridspec_kw={"width_ratios": [1.1, 1.1, 1.0]})

    # 1: depth histogram by class
    a = ax[0]
    bins = np.linspace(0, 200, 41)
    for k in ("shallow_watertable", "ambiguous", "deep_confined"):
        a.hist(depth[cls == k].clip(upper=200), bins=bins, color=COL[k], alpha=0.8,
               label=f"{LAB[k]} (n={summ[k]['n']})", stacked=False)
    a.axvline(SHALLOW_MAX_M, color=INK, ls="--", lw=1); a.axvline(DEEP_MIN_M, color=INK, ls=":", lw=1)
    a.set_xlabel("well depth (m)"); a.set_ylabel("wells"); a.legend(fontsize=12)
    a.set_title("Well-depth screen\n(dashed=30 m, dotted=60 m)", fontsize=15)

    # 2: DTW vs depth (mixing)
    a = ax[1]
    for k in ("shallow_watertable", "ambiguous", "deep_confined"):
        m = cls == k
        a.scatter(depth[m], dtw[m], s=10, c=COL[k], alpha=0.55, linewidths=0, label=LAB[k])
    a.set_xlim(0, 200); a.set_ylim(0, min(120, float(np.nanpercentile(dtw, 98))))
    a.set_xlabel("well depth (m)"); a.set_ylabel("median DTW (m)")
    a.set_title(f"DTW mixing: shallow median {summ['shallow_watertable']['median_dtw_m']:.0f} m "
                f"vs confined {summ['deep_confined']['median_dtw_m']:.0f} m", fontsize=13)
    a.legend(fontsize=12); a.grid(color=GRID, lw=0.5)

    # 3: map
    a = ax[2]
    for k in ("deep_confined", "ambiguous", "shallow_watertable"):
        m = cls == k
        a.scatter(d.lon[m], d.lat[m], s=12, c=COL[k], alpha=0.7, linewidths=0, label=LAB[k])
    a.set_xlabel("longitude"); a.set_ylabel("latitude"); a.legend(fontsize=12, loc="lower left")
    a.set_title("Well population by hydro class", fontsize=15); a.grid(color=GRID, lw=0.5)

    fig.suptitle("HAND predicts only the shallow unconfined water table — screen the confined "
                 "glacial-outwash wells out of the DTW target (#46)",
                 fontsize=15, fontweight="bold", color=INK, y=1.03)
    fig.tight_layout()
    for p in (OUT / "well_screening.png", ASSETS / "well_screening.png"):
        fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "well_screening.png", "| classes:",
          {k: summ[k]["n"] for k in summ})


if __name__ == "__main__":
    main()
