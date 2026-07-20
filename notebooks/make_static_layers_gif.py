"""Animated GIF of the static-layer catalog (docs/twin/00-structural-model.qmd, @fig-static-layers):
one full-frame panel per layer, 3 seconds each, cycling on loop.

Companion to `make_domain_figures.py`'s static 3x3 grid -- same panels, same data, but shown one at a
time at full size so each layer is actually legible (the grid version shrinks every panel to a ninth
of the figure). The title is drawn INSIDE the axes (a labelled box in the corner), not as an external
``ax.set_title`` above the plot, so it survives being read off the frame alone.

Run: ``pixi run domain-layers-gif``
"""
from __future__ import annotations

import shutil
import sys
import warnings
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rioxarray as rxr
import xarray as xr
from PIL import Image

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/static_layers_domain.gif")
FRAME_MS = 3000  # 3 seconds/layer


def _tif(name):
    return rxr.open_rasterio(PROC / name, masked=True).squeeze("band", drop=True)


def _frame(arr, title, cmap, unit) -> Image.Image:
    """Render one static layer as a standalone RGB frame, title INSIDE the axes box."""
    v = arr[np.isfinite(arr)]
    lo, hi = (np.percentile(v, 2), np.percentile(v, 98)) if v.size else (0, 1)
    cm = plt.get_cmap(cmap).copy()
    cm.set_bad("#eef0f3")

    # Fixed axes rects (not constrained_layout, which can shift box position per-frame) so the
    # map sits at the SAME spot in every frame. The domain array is taller than wide (1890x1567),
    # so imshow's equal-aspect image doesn't fill a square box -- set_anchor("W") left-aligns the
    # rendered image within its box instead of matplotlib's default centering.
    fig = plt.figure(figsize=(8.0, 8.0))
    ax = fig.add_axes((0.02, 0.02, 0.78, 0.96))
    ax.set_anchor("W")
    im = ax.imshow(arr, cmap=cm, vmin=lo, vmax=hi)
    ax.set_xticks([])
    ax.set_yticks([])
    # the label lives INSIDE the plot box (top-left corner), not as a title above it
    ax.text(0.03, 0.97, f"{title}  [{unit}]", transform=ax.transAxes, fontsize=20,
            fontweight="bold", va="top", ha="left", color="black",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.85, edgecolor="none"))
    cax = fig.add_axes((0.84, 0.15, 0.03, 0.7))
    fig.colorbar(im, cax=cax)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


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

    frames = [_frame(*panel) for panel in panels]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)      # a fresh clone has no assets dir; copy would raise
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0)
    shutil.copy(OUT, ASSETS / OUT.name)
    print(f"wrote {OUT} ({len(frames)} frames, {FRAME_MS/1000:.0f}s each)")


if __name__ == "__main__":
    main()
