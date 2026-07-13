"""Presentation figures on the EXTENDED (western Cascades) domain."""
from __future__ import annotations
import shutil, sys, warnings
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np, rioxarray as rxr, xarray as xr
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from src.viz.fonts import register_inter; register_inter()
except Exception: pass

P = Path("data/processed")
g = lambda f: rxr.open_rasterio(P/f, masked=True).squeeze("band", drop=True)

soil = xr.open_zarr(P/"soil_domain_90m.zarr")
wt   = xr.open_zarr(P/"baseline_wt_domain_90m.zarr")
hand, slope, twi = g("terrain_hand_domain_90m.tif"), g("terrain_slope_domain_90m.tif"), g("terrain_twi_domain_90m.tif")
vs30 = g("vs30_domain_90m.tif")

land = np.isfinite(hand.values) & np.isfinite(soil.theta_fc.values)
def m(a):
    o = np.asarray(a, float).copy(); o[~land] = np.nan; return o

PANELS = [
    (m(hand.values),                 "HAND",              "YlGnBu_r", "m"),
    (m(slope.values),                "Slope",             "magma",    "deg"),
    (m(twi.values),                  "TWI",               "GnBu",     "ln(a/tanβ)"),
    (m(soil.clay_pct.values),        "Clay",              "YlOrBr",   "%"),
    (m(soil.om_pct.values),          "Organic matter",    "copper_r", "%"),
    (m(soil.root_depth_m.values),    "Root depth",        "BrBG",     "m"),
    (m(soil.ksat.values),            "Ksat",              "viridis",  "mm hr⁻¹"),
    (m(wt.dtw_m.values),             "Water table",       "Blues_r",  "m depth"),
    (m(vs30.values),                 "Vs30 (SVM)",        "plasma",   "m s⁻¹"),
]
fig, axes = plt.subplots(3, 3, figsize=(12.4, 12.6), constrained_layout=True)
for ax, (arr, t, cm, u) in zip(axes.ravel(), PANELS):
    v = arr[np.isfinite(arr)]
    lo, hi = (np.percentile(v, 2), np.percentile(v, 98)) if v.size else (0, 1)
    c = plt.get_cmap(cm).copy(); c.set_bad("#eef0f3")
    im = ax.imshow(arr, cmap=c, vmin=lo, vmax=hi)
    ax.set_title(f"{t}  [{u}]", fontsize=11, fontweight="bold", pad=3)
    fig.colorbar(im, ax=ax, shrink=0.7); ax.set_xticks([]); ax.set_yticks([])
fig.suptitle("Static layers — western Cascades domain, 90 m, EPSG:5070 (2.96 M cells)\n"
             "Puyallup & Nisqually headwaters · all 8 gauged basins inside",
             fontsize=13, fontweight="bold")
out = Path("figures/demo/static_layers_domain.png"); out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=125, bbox_inches="tight", facecolor="white")
shutil.copy(out, Path("docs/twin/assets")/out.name)
print("wrote", out)
