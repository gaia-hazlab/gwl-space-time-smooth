"""Digital-twin GIF: the soil state through the 2025-26 wet season, western Cascades domain.

Run: ``pixi run twin-gif``
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr
from matplotlib.animation import FuncAnimation, PillowWriter

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/twin_wetseason.gif")
STEP = 8            # grid subsample (the GIF is a communication artefact, not an analysis product)
CADENCE = 7         # days between frames


def _tif(name):
    return rxr.open_rasterio(PROC / name, masked=True).squeeze("band", drop=True)


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.io.zarr_store import open_zarr
    from src.models.forecast import ForecastForcing, forecast_soil_state

    soil = xr.open_zarr(PROC / "soil_domain_90m.zarr")
    wt = xr.open_zarr(PROC / "baseline_wt_domain_90m.zarr")
    f = open_zarr(PROC / "prism_daily_2025-09_2026-06.zarr").rio.write_crs("EPSG:4326")

    sub = DOMAIN.template().isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    precip = f.precip_mm.rio.reproject_match(sub).values
    tmean = f.tmean_c.rio.reproject_match(sub).values
    pet = f.pet_mm.rio.reproject_match(sub).values
    times = pd.to_datetime(f.time.values)

    sl = (slice(None, None, STEP), slice(None, None, STEP))
    wp, fc, sat = (soil[k].values[sl] for k in ("theta_wp", "theta_fc", "theta_sat"))
    d0 = wt.dtw_m.values[sl]
    hand = _tif("terrain_hand_domain_90m.tif").values[sl]
    tan_b = np.tan(np.radians(_tif("terrain_slope_domain_90m.tif").values[sl]))
    vs30 = _tif("vs30_domain_90m.tif").values[sl]
    root = soil.root_depth_m.values[sl]

    forcing = ForecastForcing(times=times.values, precip_mm=precip, pet_mm=pet, dt_days=1.0,
                              tmean_c=tmean, source="PRISM")
    fx = forecast_soil_state(forcing, theta_wp=wp, theta_fc=fc, theta_sat=sat, vs30_base=vs30,
                             wt_depth0_m=d0, root_depth_m=root, slope_tan=tan_b, hand_m=hand)

    land = np.isfinite(d0) & np.isfinite(wp) & np.isfinite(hand)
    msk = lambda a: np.where(land, a, np.nan)          # noqa: E731
    idx = np.arange(0, len(times), CADENCE)
    stacks = [
        (np.stack([msk(fx.theta[i]) for i in idx]), "Soil moisture θ", "YlGnBu", "m³ m⁻³"),
        (np.stack([msk(d0 - fx.wt_depth_m[i]) for i in idx]), "Water table rise", "Blues",
         "m above baseline"),
        (np.stack([msk(100 * fx.dvv_high[i]) for i in idx]), "dv/v  (shallow band)", "RdBu", "%"),
    ]
    pr_series = np.array([np.nanmean(precip[i][land]) for i in range(len(times))])

    fig, ax = plt.subplots(1, 4, figsize=(13.5, 3.9), constrained_layout=True,
                           gridspec_kw={"width_ratios": [1, 1, 1, 1.15]})
    ims = []
    for a, (data, title, cmap, unit) in zip(ax[:3], stacks):
        v = data[np.isfinite(data)]
        lo, hi = np.percentile(v, [2, 98])
        if title.startswith("dv"):                      # diverging: symmetric about zero
            hi = max(abs(lo), abs(hi))
            lo = -hi
        cm = plt.get_cmap(cmap).copy()
        cm.set_bad("#eef0f3")
        im = a.imshow(data[0], cmap=cm, vmin=lo, vmax=hi)
        ims.append(im)
        a.set_title(f"{title}\n[{unit}]", fontsize=11, fontweight="bold")
        a.set_xticks([])
        a.set_yticks([])
        fig.colorbar(im, ax=a, shrink=.75)

    ax[3].bar(times, pr_series, color="#2E86AB", width=1.0)
    cursor = ax[3].axvline(times[0], color="#E84855", lw=2)
    ax[3].set_title("Rainfall forcing (PRISM daily)", fontsize=11, fontweight="bold")
    ax[3].set_ylabel("mm / day")
    ax[3].tick_params(axis="x", rotation=35, labelsize=8)
    title = fig.suptitle("", fontsize=13, fontweight="bold")

    def update(k):
        for im, (data, *_) in zip(ims, stacks):
            im.set_data(data[k])
        cursor.set_xdata([times[idx[k]]] * 2)
        title.set_text("GAIA Digital Twin of Soil — wet season 2025–26, western Cascades (90 m)\n%s"
                       % pd.Timestamp(times[idx[k]]).strftime("%d %b %Y"))
        return ims + [cursor, title]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)      # fresh clone has no assets dir; copy would raise
    FuncAnimation(fig, update, frames=len(idx), blit=False).save(
        OUT, writer=PillowWriter(fps=5), dpi=72)
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s (%d frames)" % (OUT, len(idx)))


if __name__ == "__main__":
    main()
