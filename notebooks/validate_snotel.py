"""Independent validation: model soil moisture vs SNOTEL in-situ θ (issue #28).

For each SNOTEL soil-moisture station we run the *same* model — SOLUS→Saxton-Rawls envelope
forced by a TerraClimate Thornthwaite–Mather bucket — at the station point, and compare monthly
model θ to the QC'd in-situ θ. Because SNOTEL is a field measurement independent of SOLUS and
TerraClimate, this is the project's first genuinely *independent* θ validation (the TerraClimate
`soil` cross-check shares forcing, so it only tests consistency).

These stations are high-elevation, snowmelt-driven uplands — the weak regime for a bucket with
no explicit snowpack — so temporal correlation (does the model track the dynamics?) is the honest
metric; absolute θ carries a depth-representativeness offset (0–1 m bucket vs shallow sensors).

Run:  pixi run python notebooks/validate_snotel.py   (after fetch_snotel + fetch_terraclimate --bbox …)
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
import rioxarray as rxr
import xarray as xr
from pyproj import Transformer

from src.models.soil_moisture import (
    DEFAULT_ROOT_DEPTH_M,
    saxton_rawls_envelope,
    snowmelt_liquid_input,
    total_water_bucket,
)

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
OUT.mkdir(parents=True, exist_ok=True)
INK = "#1a1a2e"
OI = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]
SOLUS = "/vsicurl/https://storage.googleapis.com/solus100pub"


def _model_theta(sand, clay, precip, pet, tmean=None, days=None, snow=False, root_m=DEFAULT_ROOT_DEPTH_M):
    env = saxton_rawls_envelope(np.array([sand]), np.array([clay]))
    wp = np.array([[float(env["theta_wp"][0])]]); fc = np.array([[float(env["theta_fc"][0])]])
    sat = np.array([[float(env["theta_sat"][0])]])
    liquid = precip
    if snow and tmean is not None:
        liquid, _ = snowmelt_liquid_input(precip[:, None, None], tmean[:, None, None], days)
        liquid = liquid[:, 0, 0]
    return total_water_bucket(liquid[:, None, None], pet[:, None, None], wp, fc, sat, root_m)[:, 0, 0]


def main():
    sn = pd.read_parquet(PROC / "snotel_soil_moisture_monthly.parquet")
    tc = xr.open_zarr(PROC / "terraclimate_snotel.zarr")
    tc_t = pd.DatetimeIndex(tc.time.values)
    stns = sn.drop_duplicates("triplet")[["triplet", "name", "lat", "lon", "elev_ft"]].reset_index(drop=True)

    # Sample SOLUS texture at the station points (independent static input).
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    xs, ys = tf.transform(stns.lon.values, stns.lat.values)
    clay = rxr.open_rasterio(f"{SOLUS}/claytotal_0_cm_p.tif")
    sand = rxr.open_rasterio(f"{SOLUS}/sandtotal_0_cm_p.tif")
    stns["clay"] = [float(clay.sel(x=x, y=y, method="nearest").values.squeeze()) for x, y in zip(xs, ys)]
    stns["sand"] = [float(sand.sel(x=x, y=y, method="nearest").values.squeeze()) for x, y in zip(xs, ys)]

    days = np.array([pd.Timestamp(t).days_in_month for t in tc_t])
    rows, series = [], {}
    for _, st in stns.iterrows():
        j = int(np.hypot(tc.lon.values[None, :] - st.lon, tc.lat.values[:, None] - st.lat).argmin())
        iy, ix = np.unravel_index(j, (tc.lat.size, tc.lon.size))
        P = tc["precip_mm"].values[:, iy, ix]
        PET = tc["pet_mm"].values[:, iy, ix]
        Tm = tc["tmean_c"].values[:, iy, ix]
        # snow OFF (baseline) vs snow ON (temperature-index redistribution)
        mod0 = pd.Series(_model_theta(st.sand, st.clay, P, PET, snow=False), index=tc_t)
        mod1 = pd.Series(_model_theta(st.sand, st.clay, P, PET, tmean=Tm, days=days, snow=True), index=tc_t)

        obs = sn[sn.triplet == st.triplet].copy()
        obs["date"] = pd.to_datetime(dict(year=obs.year, month=obs.month, day=1))
        merged = obs.merge(pd.DataFrame({"date": tc_t, "theta_nosnow": mod0.values,
                                         "theta_mod": mod1.values}), on="date")
        if len(merged) < 12:
            continue
        o = merged.theta_obs.values
        r = float(np.corrcoef(o, merged.theta_mod.values)[0, 1])
        r_nosnow = float(np.corrcoef(o, merged.theta_nosnow.values)[0, 1])
        clim_o = merged.groupby(merged.date.dt.month).theta_obs.transform("mean")
        clim_m = merged.groupby(merged.date.dt.month).theta_mod.transform("mean")
        r_anom = float(np.corrcoef(o - clim_o, merged.theta_mod.values - clim_m)[0, 1])
        rows.append({"name": st["name"], "elev_ft": st.elev_ft, "n": len(merged),
                     "r": r, "r_nosnow": r_nosnow, "r_anom": r_anom,
                     "bias": float(np.mean(merged.theta_mod.values - o)),
                     "rmse": float(np.sqrt(np.mean((merged.theta_mod.values - o) ** 2)))})
        series[st["name"]] = merged

    res = pd.DataFrame(rows).sort_values("r", ascending=False)
    pooled = pd.concat(series.values())
    r_pool = float(np.corrcoef(pooled.theta_obs, pooled.theta_mod)[0, 1])
    r_pool_nosnow = float(np.corrcoef(pooled.theta_obs, pooled.theta_nosnow)[0, 1])
    print(res.to_string(index=False))
    print(f"\npooled r: no-snow {r_pool_nosnow:.2f} -> snow {r_pool:.2f}  "
          f"(n={len(pooled)} station-months, {len(res)} stations)")

    summary = {"n_stations": int(len(res)), "n_station_months": int(len(pooled)),
               "pooled_r": r_pool, "pooled_r_nosnow": r_pool_nosnow,
               "median_seasonal_r": float(res.r.median()),
               "median_seasonal_r_nosnow": float(res.r_nosnow.median()),
               "median_anomaly_r": float(res.r_anom.median()), "median_bias": float(res.bias.median()),
               "per_station": res.to_dict("records")}
    (PROC / "snotel_validation.json").write_text(json.dumps(summary, indent=2))

    # --- Figure ---
    fig = plt.figure(figsize=(14, 5))
    gs = fig.add_gridspec(1, 3, wspace=0.3, width_ratios=[1, 1.4, 1])

    ax = fig.add_subplot(gs[0, 0])
    for i, (nm, mg) in enumerate(series.items()):
        ax.scatter(mg.theta_obs, mg.theta_mod, s=8, alpha=0.4, color=OI[i % len(OI)], label=nm[:14])
    lim = [0, max(pooled.theta_obs.max(), pooled.theta_mod.max()) * 1.05]
    ax.plot(lim, lim, "k--", lw=1)
    ax.set_xlabel("SNOTEL in-situ θ (m³/m³)"); ax.set_ylabel("model θ (m³/m³)")
    ax.set_title(f"Independent θ validation (snow ON)\npooled r = {r_pool:.2f}", fontsize=11, fontweight="bold")
    ax.legend(fontsize=6.5, loc="upper left"); ax.grid(alpha=0.3)

    # best-recorded station time series: snow OFF vs ON vs in-situ
    ax2 = fig.add_subplot(gs[0, 1])
    nm0 = res.iloc[0]["name"]
    mg = series[nm0].sort_values("date")
    ax2.plot(mg.date, mg.theta_obs, color=INK, lw=1.5, label="SNOTEL in-situ")
    ax2.plot(mg.date, mg.theta_nosnow, color="#bbbbbb", lw=1.2, label="model — no snow")
    ax2.plot(mg.date, mg.theta_mod, color=OI[2], lw=1.5, label="model — snow module")
    ax2.set_ylabel("θ (m³/m³)")
    r0 = res.iloc[0]
    ax2.set_title(f"{nm0} ({int(r0.elev_ft)} ft) — r {r0.r_nosnow:.2f}→{r0.r:.2f} with snow",
                  fontsize=11, fontweight="bold")
    ax2.legend(fontsize=8, loc="upper right"); ax2.grid(alpha=0.3)

    ax3 = fig.add_subplot(gs[0, 2]); ax3.axis("off")
    txt = ("SNOTEL soil-moisture (upland, in-situ)\nθ independent of SOLUS + TerraClimate\n\n"
           f"pooled r:  no-snow {r_pool_nosnow:.2f}  →  snow {r_pool:.2f}\n\n")
    txt += f"{'station':<15}{'r_off':>6}{'r_on':>6}\n" + "-" * 27 + "\n"
    for _, rr in res.iterrows():
        txt += f"{rr['name'][:14]:<15}{rr['r_nosnow']:>6.2f}{rr['r']:>6.2f}\n"
    txt += ("\nTemperature-index snow module accumulates\nwinter precip as SWE and releases it as a\n"
            "degree-day spring melt — restoring the\nsnowmelt signal the bare bucket missed.\n"
            "Parameters nominal (calibration vs SNOTEL\nSWE pending).")
    ax3.text(0.0, 1.0, txt, va="top", family="DejaVu Sans Mono", fontsize=8.2, color=INK)

    fig.suptitle("Independent validation + snow module — model vs SNOTEL in-situ θ (uplands)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "snotel_validation.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "snotel_validation.png", "and", PROC / "snotel_validation.json")


if __name__ == "__main__":
    main()
