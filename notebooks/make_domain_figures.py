"""Presentation figures on the EXTENDED (western Cascades) domain.

Run: ``pixi run domain-figures``
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rioxarray as rxr
import xarray as xr

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/static_layers_domain.png")


def _tif(name):
    return rxr.open_rasterio(PROC / name, masked=True).squeeze("band", drop=True)


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass

    soil = xr.open_zarr(PROC / "soil_domain_90m.zarr")
    wt = xr.open_zarr(PROC / "baseline_wt_domain_90m.zarr")
    hand = _tif("terrain_hand_domain_90m.tif")
    slope = _tif("terrain_slope_domain_90m.tif")
    twi = _tif("terrain_twi_domain_90m.tif")
    vs30 = _tif("vs30_domain_90m.tif")

    land = np.isfinite(hand.values) & np.isfinite(soil.theta_fc.values)

    def m(a):
        o = np.asarray(a, dtype="float64").copy()
        o[~land] = np.nan
        return o

    panels = [
        (m(hand.values), "HAND", "YlGnBu_r", "m"),
        (m(slope.values), "Slope", "magma", "deg"),
        (m(twi.values), "TWI", "GnBu", "ln(a/tanβ)"),
        (m(soil.clay_pct.values), "Clay", "YlOrBr", "%"),
        (m(soil.om_pct.values), "Organic matter", "copper_r", "%"),
        (m(soil.root_depth_m.values), "Root depth", "BrBG", "m"),
        (m(soil.ksat.values), "Ksat", "viridis", "mm hr⁻¹"),
        (m(wt.dtw_m.values), "Water table", "Blues_r", "m depth"),
        (m(vs30.values), "Vs30 (SVM)", "plasma", "m s⁻¹"),
    ]

    fig, axes = plt.subplots(3, 3, figsize=(12.4, 12.6), constrained_layout=True)
    for ax, (arr, title, cmap, unit) in zip(axes.ravel(), panels):
        v = arr[np.isfinite(arr)]
        lo, hi = (np.percentile(v, 2), np.percentile(v, 98)) if v.size else (0, 1)
        cm = plt.get_cmap(cmap).copy()
        cm.set_bad("#eef0f3")
        im = ax.imshow(arr, cmap=cm, vmin=lo, vmax=hi)
        ax.set_title(f"{title}  [{unit}]", fontsize=11, fontweight="bold", pad=3)
        fig.colorbar(im, ax=ax, shrink=0.7)
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle("Static layers — western Cascades domain, 90 m, EPSG:5070 (2.96 M cells)\n"
                 "Puyallup & Nisqually headwaters · all 8 gauged basins inside",
                 fontsize=13, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)      # a fresh clone has no assets dir; copy would raise
    fig.savefig(OUT, dpi=125, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
