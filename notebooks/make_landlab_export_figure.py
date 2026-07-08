"""Demo figure for the LandLab dynamic export (#64): the three canonical fields + per-cell sigma.

Builds the export bundle from the real reanalysis products (via src.io.landlab_export loaders),
aligns each field to the 90 m template, and renders a 2x3 panel (top: fields; bottom: 1 sigma).
Writes figures/demo/landlab_export.png and copies it to docs/assets/ for the report.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rioxarray as rxr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.io import landlab_export as le

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("landlab_export_figure")

D = Path("data/processed")
OUT = Path("figures/demo/landlab_export.png")

try:
    from src.viz.fonts import register_inter
    register_inter()
except Exception:
    pass

# (canonical title, DynamicField key, field cmap, sigma cmap, unit)
PANELS = [
    ("Water-table depth", "water_table__depth", "viridis_r", "magma", "m"),
    ("Saturation fraction θ/n", "soil_moisture__saturation_fraction", "Blues", "magma", "–"),
    ("Recharge", "soil_water__recharge_rate", "YlGnBu", "magma", "mm day⁻¹"),
]


def _fields():
    template = rxr.open_rasterio(D / "baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    out = {}
    for f in le.load_water_table_field(D / "baseline_dtw_m.tif", D / "baseline_rf_std_m.tif",
                                       D / "baseline_kriging_std_m.tif", D / "well_density_mask.tif"):
        if f.epoch == "mean":
            out["water_table__depth"] = f
    out["soil_moisture__saturation_fraction"] = le.load_saturation_field(
        D / "soil_moisture_monthly_puget.zarr")
    rech_mean, _ = le.load_recharge_field(D / "terraclimate_monthly_puget.zarr",
                                          D / "soil_moisture_monthly_puget.zarr")
    out["soil_water__recharge_rate"] = rech_mean
    return template, out


def main():
    template, fields = _fields()
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 8.2), constrained_layout=True)
    for j, (title, key, cmap, scmap, unit) in enumerate(PANELS):
        f = fields[key]
        da = le.align_to_grid(f.data, template)
        sig = le.align_to_grid(f.sigma, template) if f.sigma is not None else None
        v = da.values[np.isfinite(da.values)]
        vlo, vhi = (np.nanpercentile(v, 2), np.nanpercentile(v, 98)) if v.size else (0, 1)

        im = axes[0, j].imshow(da.values, cmap=cmap, vmin=vlo, vmax=vhi)
        axes[0, j].set_title(f"{title}\n[{unit}]", fontsize=11)
        fig.colorbar(im, ax=axes[0, j], shrink=0.8)

        if sig is not None:
            sv = sig.values[np.isfinite(sig.values)]
            im2 = axes[1, j].imshow(sig.values, cmap=scmap,
                                    vmax=np.nanpercentile(sv, 98) if sv.size else 1)
            axes[1, j].set_title(f"1σ {title.split()[0].lower()}", fontsize=10)
            fig.colorbar(im2, ax=axes[1, j], shrink=0.8)
        else:
            axes[1, j].axis("off")
        for r in (0, 1):
            axes[r, j].set_xticks([]); axes[r, j].set_yticks([])

    fig.suptitle("LandLab dynamic export — canonical hydrological fields + per-cell uncertainty "
                 "(90 m EPSG:5070; masked to the well-supported domain)", fontsize=12)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=130, bbox_inches="tight", facecolor="white")
    logger.info("wrote %s", OUT)
    assets = Path("docs/assets") / OUT.name
    if assets.parent.exists():
        shutil.copy(OUT, assets)
        logger.info("copied to %s", assets)


if __name__ == "__main__":
    main()
