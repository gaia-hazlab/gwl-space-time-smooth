"""Static-layer catalog figure for the structural-model chapter — from the processed rasters on disk.

Reads the actual 90 m static layers on disk (terrain derivatives, SOLUS texture, the Saxton-Rawls
hydraulic envelope, Vs30), reprojects the SOLUS 100 m grid onto the terrain grid, clips to the
finite-data window, and renders a labelled 3x3 catalog. Writes figures/demo/static_layers.png and
copies it to docs/twin/assets/ (committed, since data/processed is gitignored and CI has no data).

Provenance caveat: eight of the nine panels are measured/derived public products (3DEP terrain,
SOLUS100 texture, Saxton-Rawls envelope). ``vs30_90m.tif`` carries NO source tag, so this script
cannot tell whether it holds a real Vs30 estimate (``pixi run vs30`` -> fetch_vs30/fetch_gaia) or a
proxy staged under the same name. It therefore claims neither: the Vs30 panel is annotated
provenance-unverified and the title's "real 90 m rasters" claim explicitly excludes it.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rioxarray as rxr
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("static_layers")

PROC = Path("data/processed")
OUT = Path("figures/demo/static_layers.png")
# Panel annotation for any layer whose provenance cannot be established from the file itself.
VS30_PROV_NOTE = "provenance unverified\n(derived/proxy — not a\nmeasured Vs30 grid)"

try:
    from src.viz.fonts import register_inter
    register_inter()
except Exception:
    pass


def _tif(name):
    return rxr.open_rasterio(PROC / name, masked=True).squeeze("band", drop=True)


def main():
    hand = _tif("terrain_hand_90m.tif")                       # reference 90 m EPSG:5070 grid
    slope = _tif("terrain_slope_90m.tif")
    twi = _tif("terrain_twi_90m.tif")
    vs30 = _tif("vs30_90m.tif")
    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    solus = xr.open_zarr(PROC / "solus100_wa.zarr").rio.write_crs("EPSG:5070")
    clay = solus["clay_pct"].rio.reproject_match(hand)        # 100 m -> the 90 m reference grid
    sand = solus["sand_pct"].rio.reproject_match(hand)

    # Clip to the HAND finite-data window and mask every layer to the common analysis footprint
    # (where terrain — the 90 m parent grid — is defined), so all panels share one coverage.
    # Common land footprint: terrain AND soil. The SVM returns a (valid) seafloor Vs30 over open
    # water, which is not a surface site condition, so water is masked out of every panel alike.
    fin = np.isfinite(hand.values) & np.isfinite(clay.values)
    if not fin.any():
        raise ValueError(
            "terrain_hand_90m.tif has no finite cells — cannot define the analysis footprint; "
            "check the raster extent / nodata before regenerating the figure."
        )
    ys = np.where(fin.any(axis=1))[0]
    xs = np.where(fin.any(axis=0))[0]
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    footprint = fin[sl]
    def w(a):  # window to the HAND land box, blanked outside the terrain footprint
        out = np.asarray(a, dtype="float64")[sl].copy()
        out[~footprint] = np.nan
        return out

    # (array, title, colormap, units, provenance note drawn on the panel or None)
    PANELS = [
        (w(hand.values),          "HAND",          "YlGnBu_r", "m",          None),
        (w(slope.values),         "Slope",         "magma",    "deg",        None),
        (w(twi.values),           "TWI",           "GnBu",     "ln(a/tanβ)", None),
        (w(clay.values),          "Clay",          "YlOrBr",   "%",          None),
        (w(sand.values),          "Sand",          "YlOrBr",   "%",          None),
        (w(env["ksat"].values),   "Ksat",          "viridis",  "mm hr⁻¹",    None),
        (w(env["theta_fc"].values), "θ field cap.", "Blues",   "m³ m⁻³",     None),
        (w(env["awc_mm"].values), "AWC",           "cividis",  "mm",         None),
        (w(vs30.values),          "Vs30",          "plasma",   "m s⁻¹",      VS30_PROV_NOTE),
    ]

    fig, axes = plt.subplots(3, 3, figsize=(11.0, 10.4), constrained_layout=True)
    for ax, (arr, title, cmap, unit, note) in zip(axes.ravel(), PANELS):
        v = arr[np.isfinite(arr)]
        vlo, vhi = (np.percentile(v, 2), np.percentile(v, 98)) if v.size else (0, 1)
        cm = plt.get_cmap(cmap).copy(); cm.set_bad("#eeeef2")
        im = ax.imshow(arr, cmap=cm, vmin=vlo, vmax=vhi)
        ax.set_title(f"{title}  [{unit}]", fontsize=15, fontweight="bold", pad=3)
        fig.colorbar(im, ax=ax, shrink=0.72)
        ax.set_xticks([]); ax.set_yticks([])
        if note:                       # white bbox: legible over any of the panel colormaps
            ax.text(0.5, 0.5, note, transform=ax.transAxes, ha="center", va="center", zorder=6,
                    fontsize=10.5, fontweight="bold", color="#8B0000", linespacing=1.3,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#8B0000", lw=1.0, alpha=0.93))

    fig.suptitle("Static-layer catalog — real 90 m rasters: terrain, SOLUS texture, hydraulic "
                 "envelope (Puget Sound / Cascades), EPSG:5070\nVs30 excluded from that claim — "
                 "its source is not recorded in vs30_90m.tif (see the panel annotation)",
                 fontsize=14, fontweight="bold")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=130, bbox_inches="tight", facecolor="white")
    logger.info("wrote %s", OUT)
    assets = Path("docs/twin/assets"); assets.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUT, assets / OUT.name)
    logger.info("copied to %s", assets / OUT.name)


if __name__ == "__main__":
    main()
