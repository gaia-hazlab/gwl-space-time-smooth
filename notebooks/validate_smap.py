"""Independent native-scale validation: model θ vs SMAP satellite θ (issue #29).

SMAP surface soil moisture is a satellite retrieval **independent of the SOLUS texture and
TerraClimate/PRISM forcing** that drive our model — so unlike the TerraClimate ``soil``
cross-check (shared forcing) and the now-training SNOTEL anchors, it is a genuinely independent
check, and the first one over the *lowland* pilot.

Per the scale-aware principle we **upscale** our fine model θ to SMAP's native 9 km EASE grid
(area-mean) and score there — we do not downscale SMAP to 90 m. Correlation is the honest metric
(SMAP is 0–5 cm surface, our θ is a 0–1 m root-zone bucket, so an absolute depth/representativeness
bias is expected, as with SNOTEL).

Run:  pixi run python notebooks/validate_smap.py   (after fetch_smap + soil-moisture)
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
INK, OI = "#1a1a2e", {"model": "#009E73", "smap": "#0072B2"}


def main():
    smap = xr.open_zarr(PROC / "smap_soil_moisture_monthly_puget.zarr").load()
    model = xr.open_zarr(PROC / "soil_moisture_monthly_puget.zarr").load()
    smap_t = pd.DatetimeIndex(smap.time.values).to_period("M")
    mod_t = pd.DatetimeIndex(model.time.values).to_period("M")
    common = [p for p in smap_t if p in set(mod_t)]

    # Model θ (4 km WGS84) → rioxarray; SMAP grid template (9 km EPSG:6933).
    mth = model["theta"].rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
    smap_like = smap["theta_smap"].isel(time=0).rio.write_crs("EPSG:6933")

    up_stack, sm_stack, times = [], [], []
    for p in common:
        mi = int(np.where(mod_t == p)[0][0]); si = int(np.where(smap_t == p)[0][0])
        up = upscale_to_grid(mth.isel(time=mi), smap_like).values     # model upscaled to 9 km
        sm = smap["theta_smap"].isel(time=si).values
        up_stack.append(up); sm_stack.append(sm); times.append(p.to_timestamp())
    U = np.stack(up_stack, 0); S = np.stack(sm_stack, 0)              # (t, y, x) at 9 km

    ok = np.isfinite(U) & np.isfinite(S)
    u, s = U[ok], S[ok]
    r_pool = float(np.corrcoef(u, s)[0, 1])
    bias = float(np.mean(u - s)); rmse = float(np.sqrt(np.mean((u - s) ** 2)))

    # domain-mean monthly series
    um = np.nanmean(np.where(np.isfinite(U) & np.isfinite(S), U, np.nan), axis=(1, 2))
    smm = np.nanmean(np.where(np.isfinite(U) & np.isfinite(S), S, np.nan), axis=(1, 2))
    good = np.isfinite(um) & np.isfinite(smm)
    r_dm = float(np.corrcoef(um[good], smm[good])[0, 1])
    # deseasonalised (anomaly) correlation of the domain mean
    tt = pd.DatetimeIndex(times)
    dfm = pd.DataFrame({"u": um, "s": smm, "m": tt.month})[good]
    ua = dfm.u - dfm.groupby("m").u.transform("mean"); sa = dfm.s - dfm.groupby("m").s.transform("mean")
    r_anom = float(np.corrcoef(ua, sa)[0, 1])
    # per-cell temporal r
    cell_r = []
    for i in range(U.shape[1]):
        for j in range(U.shape[2]):
            a, b = U[:, i, j], S[:, i, j]
            m = np.isfinite(a) & np.isfinite(b)
            if m.sum() >= 12 and a[m].std() > 0 and b[m].std() > 0:
                cell_r.append(np.corrcoef(a[m], b[m])[0, 1])
    r_cell = float(np.nanmedian(cell_r)) if cell_r else float("nan")

    summary = {"n_months": int(good.sum()), "n_cells_9km": int(np.isfinite(S).any(0).sum()),
               "pooled_r": r_pool, "domain_mean_r": r_dm, "domain_mean_anomaly_r": r_anom,
               "median_cell_r": r_cell, "bias": bias, "rmse": rmse,
               "period": [str(tt.min())[:7], str(tt.max())[:7]]}
    (PROC / "smap_validation.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    # --- Figure ---
    fig = plt.figure(figsize=(15, 4.6))
    gs = fig.add_gridspec(1, 3, wspace=0.32, width_ratios=[1.5, 1, 1])
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.plot(tt[good], smm[good], color=OI["smap"], lw=1.6, label="SMAP satellite (9 km, 0–5 cm)")
    ax0.plot(tt[good], um[good], color=OI["model"], lw=1.6, label="model θ (upscaled to 9 km)")
    ax0.set_ylabel("domain-mean θ (m³/m³)")
    ax0.set_title(f"Independent satellite validation — domain mean (r = {r_dm:.2f})",
                  fontsize=11, fontweight="bold")
    ax0.legend(fontsize=8, loc="upper right"); ax0.grid(alpha=0.3)

    ax1 = fig.add_subplot(gs[0, 1])
    ax1.scatter(s, u, s=4, alpha=0.15, color=OI["model"])
    lim = [0, max(np.nanpercentile(u, 99), np.nanpercentile(s, 99))]
    ax1.plot(lim, lim, "k--", lw=1)
    ax1.set_xlabel("SMAP θ (m³/m³)"); ax1.set_ylabel("model θ (m³/m³)")
    ax1.set_title(f"9 km cells (pooled r = {r_pool:.2f})", fontsize=11, fontweight="bold")
    ax1.grid(alpha=0.3)

    ax2 = fig.add_subplot(gs[0, 2]); ax2.axis("off")
    txt = ("SMAP SPL3SMP_E — satellite surface θ,\nindependent of SOLUS + TerraClimate\n"
           f"({summary['period'][0]}–{summary['period'][1]}, native 9 km EASE grid)\n\n"
           f"domain-mean r      : {r_dm:.2f}\n"
           f"deseasonalised r   : {r_anom:.2f}\n"
           f"per-cell median r  : {r_cell:.2f}\n"
           f"pooled (space+time): {r_pool:.2f}\n"
           f"bias (model−SMAP)  : {bias:+.3f}\n"
           f"RMSE               : {rmse:.3f} m³/m³\n\n"
           "Compared at SMAP's native scale (upscale-\nthen-compare). SMAP is 0–5 cm surface,\n"
           "the model a 0–1 m root zone → an absolute\ndepth bias is expected; correlation is the\n"
           "honest skill. First independent check over\nthe lowland pilot (SNOTEL was upland-only).")
    ax2.text(0.0, 1.0, txt, va="top", family="DejaVu Sans Mono", fontsize=8.2, color=INK)

    fig.suptitle("Independent satellite validation — model θ vs SMAP at native 9 km scale",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "smap_validation.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "smap_validation.png", "and", PROC / "smap_validation.json")


if __name__ == "__main__":
    main()
