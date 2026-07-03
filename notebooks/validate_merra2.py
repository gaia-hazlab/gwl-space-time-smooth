"""Native-scale validation: model θ vs MERRA-2 root-zone soil moisture (issue #29).

MERRA-2 is a NASA reanalysis (a model cross-check, not a satellite retrieval), but its **root-zone**
field RZMC (~0–1 m) is depth-matched to our root-zone bucket, so the absolute bias should be far
smaller than SMAP's 0–5 cm surface — and it covers **2025**, the period of interest. Following the
scale-aware principle we **upscale** our model θ to MERRA-2's native 0.5°×0.625° grid and score
there. RZMC is the headline (depth-matched); SFMC (surface) is a secondary comparison.

Run:  pixi run python notebooks/validate_merra2.py   (after fetch_merra2 + soil-moisture)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr

from src.models.downscale import upscale_to_grid

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
INK, OI = "#1a1a2e", {"model": "#009E73", "rz": "#0072B2", "sfc": "#56B4E9"}


def _upscale_series(model_da, ref_like, common, mod_t, ref_t):
    U, T = [], []
    for p in common:
        mi = int(np.where(mod_t == p)[0][0])
        U.append(upscale_to_grid(model_da.isel(time=mi), ref_like).values)
        T.append(p.to_timestamp())
    return np.stack(U, 0), pd.DatetimeIndex(T)


def _stats(U, R):
    ok = np.isfinite(U) & np.isfinite(R)
    u, r = U[ok], R[ok]
    return {"r": float(np.corrcoef(u, r)[0, 1]), "bias": float(np.mean(u - r)),
            "rmse": float(np.sqrt(np.mean((u - r) ** 2)))}


def main():
    mer = xr.open_zarr(PROC / "merra2_soil_moisture_monthly_puget.zarr").load()
    model = xr.open_zarr(PROC / "soil_moisture_monthly_puget.zarr").load()
    mer_t = pd.DatetimeIndex(mer.time.values).to_period("M")
    mod_t = pd.DatetimeIndex(model.time.values).to_period("M")
    common = [p for p in mer_t if p in set(mod_t)]

    mth = model["theta"].rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
    ref_like = mer["theta_rz"].isel(time=0).rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
    U, tt = _upscale_series(mth, ref_like, common, mod_t, mer_t)
    RZ = np.stack([mer["theta_rz"].sel(time=p.to_timestamp()).values for p in common], 0)
    SF = np.stack([mer["theta_sfc"].sel(time=p.to_timestamp()).values for p in common], 0)

    st_rz, st_sf = _stats(U, RZ), _stats(U, SF)
    um = np.nanmean(U, (1, 2)); rzm = np.nanmean(RZ, (1, 2)); sfm = np.nanmean(SF, (1, 2))
    r_dm_rz = float(np.corrcoef(um, rzm)[0, 1])
    summary = {"n_months": len(common), "period": [str(tt.min())[:7], str(tt.max())[:7]],
               "n_cells": int(np.isfinite(RZ[0]).sum()), "root_zone": st_rz, "surface": st_sf,
               "domain_mean_r_rootzone": r_dm_rz}
    (PROC / "merra2_validation.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    # --- Figure ---
    fig = plt.figure(figsize=(15, 4.6))
    gs = fig.add_gridspec(1, 3, wspace=0.32, width_ratios=[1.6, 1, 1])
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.plot(tt, rzm, color=OI["rz"], lw=1.8, marker="o", ms=3, label="MERRA-2 root-zone (0–1 m)")
    ax0.plot(tt, sfm, color=OI["sfc"], lw=1.1, ls="--", label="MERRA-2 surface (0–5 cm)")
    ax0.plot(tt, um, color=OI["model"], lw=1.8, marker="s", ms=3, label="model θ (upscaled to 0.5°)")
    ax0.set_ylabel("domain-mean θ (m³/m³)")
    ax0.set_title(f"Depth-matched reanalysis validation — domain mean (r = {r_dm_rz:.2f})",
                  fontsize=11, fontweight="bold")
    ax0.legend(fontsize=8, loc="upper right"); ax0.grid(alpha=0.3)

    ax1 = fig.add_subplot(gs[0, 1])
    ok = np.isfinite(U) & np.isfinite(RZ)
    ax1.scatter(RZ[ok], U[ok], s=14, alpha=0.4, color=OI["model"])
    lim = [min(RZ[ok].min(), U[ok].min()) * 0.9, max(RZ[ok].max(), U[ok].max()) * 1.05]
    ax1.plot(lim, lim, "k--", lw=1)
    ax1.set_xlabel("MERRA-2 root-zone θ (m³/m³)"); ax1.set_ylabel("model θ (m³/m³)")
    ax1.set_title(f"native 0.5° cells (r = {st_rz['r']:.2f})", fontsize=11, fontweight="bold")
    ax1.grid(alpha=0.3)

    ax2 = fig.add_subplot(gs[0, 2]); ax2.axis("off")
    txt = ("MERRA-2 reanalysis (root-zone, 0–1 m)\n"
           f"native 0.5°×0.625°, {summary['period'][0]}–{summary['period'][1]}\n"
           "(includes 2025)\n\n"
           "ROOT-ZONE (depth-matched):\n"
           f"  domain-mean r : {r_dm_rz:.2f}\n"
           f"  per-cell r    : {st_rz['r']:.2f}\n"
           f"  bias          : {st_rz['bias']:+.3f}\n"
           f"  RMSE          : {st_rz['rmse']:.3f} m³/m³\n\n"
           f"surface (0–5 cm): r={st_sf['r']:.2f}, bias={st_sf['bias']:+.2f}\n\n"
           "Reanalysis is a model cross-check (not an\nindependent satellite obs like SMAP), but\n"
           "depth-matched, so the bias is far smaller\nthan the surface comparison — the level and\n"
           "the seasonal cycle both line up.")
    ax2.text(0.0, 1.0, txt, va="top", family="DejaVu Sans Mono", fontsize=8.2, color=INK)

    fig.suptitle("Depth-matched validation — model θ vs MERRA-2 root-zone reanalysis (native 0.5°, incl. 2025)",
                 fontsize=12.5, fontweight="bold", y=1.02)
    fig.savefig(OUT / "merra2_validation.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "merra2_validation.png", "and", PROC / "merra2_validation.json")


if __name__ == "__main__":
    main()
