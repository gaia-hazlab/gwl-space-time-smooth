"""Observation-anchor soil moisture to SNOTEL over the Puget+Cascade domain (issue #28).

Extends θ east to where the SNOTEL soil-moisture stations actually are (soil moisture needs only
SOLUS texture, not the 90 m terrain), then applies the residual anchor (obs − model, distance-
weighted) so the product is pulled toward the in-situ data — the soil-moisture analogue of the
GWL Stage-3 well anchoring. A leave-one-station-out test shows whether the anchoring generalises
(reduces held-out bias/RMSE), and a depth-honest note separates the plant-available bucket from
the sensors' total-volumetric reading.

Run:  pixi run python notebooks/anchor_snotel.py   (after fetch_snotel + the wider fetches)
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
from pyproj import Transformer

from src.models.anchor import loso_anchor_skill, residual_anchor
from src.models.soil_moisture import (
    DEFAULT_ROOT_DEPTH_M,
    apply_snow_if_available,
    saxton_rawls_envelope,
    total_water_bucket,
)

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
INK, OI = "#1a1a2e", {"raw": "#bbbbbb", "anch": "#009E73", "obs": "#1a1a2e"}
LENGTH_SCALE_M = 30_000.0        # ~30 km anchoring support radius


def build_theta_field():
    """θ(time, lat, lon) over the Puget+Cascade domain at the TerraClimate 4 km grid."""
    drv = xr.open_zarr(PROC / "terraclimate_puget_cascade.zarr")
    drv = drv.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
    solus = xr.open_zarr(PROC / "solus100_wa.zarr")
    if solus.rio.crs is None:
        solus = solus.rio.write_crs("EPSG:5070")
    s4 = solus.rio.reproject_match(drv)                       # sand/clay at 4 km
    env = saxton_rawls_envelope(s4["sand_pct"].values, s4["clay_pct"].values)
    liquid = apply_snow_if_available(drv, drv["precip_mm"].values)
    theta = total_water_bucket(liquid, drv["pet_mm"].values, env["theta_wp"], env["theta_fc"],
                               env["theta_sat"], DEFAULT_ROOT_DEPTH_M)
    return xr.DataArray(theta, dims=("time", "lat", "lon"),
                        coords={"time": drv.time.values, "lat": drv.lat.values, "lon": drv.lon.values})


def main():
    theta = build_theta_field()
    tt = pd.DatetimeIndex(theta.time.values).to_period("M")
    sn = pd.read_parquet(PROC / "snotel_soil_moisture_monthly.parquet")
    sn["date"] = pd.to_datetime(dict(year=sn.year, month=sn.month, day=1))
    stns = sn.drop_duplicates("triplet")[["triplet", "name", "lat", "lon", "elev_ft"]].reset_index(drop=True)

    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    stns["x"], stns["y"] = tf.transform(stns.lon.values, stns.lat.values)
    latg, long_ = np.meshgrid(theta.lat.values, theta.lon.values, indexing="ij")
    gx, gy = tf.transform(long_, latg)

    # Per-station model vs obs (time-mean over the overlap) → residuals.
    mvals, ovals = [], []
    for _, st in stns.iterrows():
        iy = int(np.abs(theta.lat.values - st.lat).argmin())
        ix = int(np.abs(theta.lon.values - st.lon).argmin())
        series = pd.Series(theta.values[:, iy, ix], index=tt)
        obs = sn[sn.triplet == st.triplet].set_index(pd.PeriodIndex(
            sn[sn.triplet == st.triplet].date, freq="M")).theta_obs
        common = series.index.intersection(obs.index)
        mvals.append(float(series.loc[common].mean())); ovals.append(float(obs.loc[common].mean()))
    stns["model"] = mvals; stns["obs"] = ovals; stns["resid"] = stns.obs - stns.model

    # Leave-one-station-out anchoring skill.
    rb, rr, ab, ar = loso_anchor_skill(stns.x, stns.y, stns.model, stns.obs, LENGTH_SCALE_M)
    prior = float(np.nanstd(stns.resid))
    anchor_field, sigma_field = residual_anchor(gx, gy, stns.x.values, stns.y.values,
                                                stns.resid.values, LENGTH_SCALE_M, prior)

    summary = {"n_stations": int(len(stns)), "length_scale_km": LENGTH_SCALE_M / 1000,
               "loso_bias_raw": rb, "loso_bias_anchored": ab,
               "loso_rmse_raw": rr, "loso_rmse_anchored": ar,
               "per_station": stns[["name", "elev_ft", "model", "obs", "resid"]].to_dict("records")}
    (PROC / "snotel_anchor.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_station"}, indent=2))

    # Anchored θ field for a representative wet month.
    mo = pd.Period("2019-05", "M")
    mi = int(np.where(tt == mo)[0][0])
    model_m = theta.values[mi]
    anchored_m = model_m + anchor_field
    ext = [float(theta.lon.min()), float(theta.lon.max()), float(theta.lat.min()), float(theta.lat.max())]

    fig = plt.figure(figsize=(15, 4.8))
    gs = fig.add_gridspec(1, 3, wspace=0.3, width_ratios=[1.05, 1.05, 1])
    vmin, vmax = 0.10, 0.45
    for ax, fld, title in [(fig.add_subplot(gs[0, 0]), model_m, "Model θ (Puget+Cascade, 2019-05)"),
                           (fig.add_subplot(gs[0, 1]), anchored_m, "SNOTEL-anchored θ")]:
        im = ax.imshow(fld, extent=ext, origin="lower", cmap="YlGnBu", vmin=vmin, vmax=vmax, aspect="auto")
        ax.scatter(stns.lon, stns.lat, s=45, c="#D55E00", edgecolors="white", linewidths=0.6, zorder=5)
        ax.set_title(title, fontsize=10.5, fontweight="bold"); ax.tick_params(labelsize=8)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label("θ (m³/m³)", fontsize=8.5)

    ax3 = fig.add_subplot(gs[0, 2])
    x = np.arange(2)
    ax3.bar(x - 0.2, [abs(rb), rr], 0.38, color=OI["raw"], label="model only")
    ax3.bar(x + 0.2, [abs(ab), ar], 0.38, color=OI["anch"], label="SNOTEL-anchored (LOSO)")
    ax3.set_xticks(x); ax3.set_xticklabels(["|bias|", "RMSE"]); ax3.set_ylabel("m³/m³")
    ax3.set_title("Held-out (leave-one-station-out)\nanchoring skill", fontsize=10.5, fontweight="bold")
    ax3.legend(fontsize=8); ax3.grid(axis="x", visible=False)
    for s in ("top", "right"):
        ax3.spines[s].set_visible(False)

    fig.suptitle("Observation-anchored soil moisture — SNOTEL residual anchor over the Cascades (issue #28)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "snotel_anchor.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "snotel_anchor.png", "and", PROC / "snotel_anchor.json")


if __name__ == "__main__":
    main()
