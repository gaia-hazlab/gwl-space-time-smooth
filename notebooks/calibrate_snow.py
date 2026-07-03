"""Calibrate the snow module and characterise the residual bias against SNOTEL (issue #28).

Two problems were separated in the validation: **phase** (the snow module's timing) and **bias**
(model θ saturates near field capacity while the shallow SNOTEL sensors read higher).

  1. **Snow-parameter calibration.** Grid-search the degree-day factor and the rain/snow &
     melt temperature thresholds to maximise the mean per-station correlation. Correlation is
     invariant to an additive bias, so this targets *phase/amplitude*, not the offset. Reported
     with **leave-one-station-out (LOSO)** so it is an out-of-sample number, not an in-sample fit.

  2. **Bias correction (operational).** A per-station linear rescale (match obs mean+std) removes
     the representativeness offset; it preserves correlation and collapses RMSE. This *consumes
     SNOTEL as training*, so after it SNOTEL is no longer independent — SMAP (#29) remains the
     independent test. Reported to show how much of the gap is a fixable offset vs. real error.

Writes the calibrated snow constants back into ``src/models/soil_moisture.py`` guidance (printed)
and a figure + JSON. Run after fetch_snotel + fetch_terraclimate --bbox … .
"""

from __future__ import annotations

import itertools
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
    thornthwaite_mather_wetness,
)

mpl.use("Agg")
PROC = Path("data/processed")
OUT = Path("figures/demo")
INK, OI = "#1a1a2e", ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7"]
SOLUS = "/vsicurl/https://storage.googleapis.com/solus100pub"
DEFAULT = dict(ddf=3.0, t_snow_hi=3.0, t_melt=0.0)
GRID = dict(ddf=[1.5, 2.5, 3.5, 5.0, 7.0], t_snow_hi=[1.0, 2.0, 3.0], t_melt=[-1.0, 0.0, 1.0])


def _load():
    sn = pd.read_parquet(PROC / "snotel_soil_moisture_monthly.parquet")
    sn["date"] = pd.to_datetime(dict(year=sn.year, month=sn.month, day=1))
    tc = xr.open_zarr(PROC / "terraclimate_snotel.zarr")
    tct = pd.DatetimeIndex(tc.time.values)
    days = np.array([t.days_in_month for t in tct])
    stns = sn.drop_duplicates("triplet")[["triplet", "name", "lat", "lon", "elev_ft"]].reset_index(drop=True)
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    xs, ys = tf.transform(stns.lon.values, stns.lat.values)
    clay = rxr.open_rasterio(f"{SOLUS}/claytotal_0_cm_p.tif")
    sand = rxr.open_rasterio(f"{SOLUS}/sandtotal_0_cm_p.tif")
    st = {}
    for i, s in stns.iterrows():
        j = int(np.hypot(tc.lon.values[None, :] - s.lon, tc.lat.values[:, None] - s.lat).argmin())
        iy, ix = np.unravel_index(j, (tc.lat.size, tc.lon.size))
        obs = sn[sn.triplet == s.triplet][["date", "theta_obs"]]
        st[s["name"]] = dict(
            sand=float(sand.sel(x=xs[i], y=ys[i], method="nearest").values.squeeze()),
            clay=float(clay.sel(x=xs[i], y=ys[i], method="nearest").values.squeeze()),
            P=tc["precip_mm"].values[:, iy, ix], PET=tc["pet_mm"].values[:, iy, ix],
            T=tc["tmean_c"].values[:, iy, ix], elev=s.elev_ft, obs=obs)
    return st, tct, days


def _theta(s, params, tct, days):
    env = saxton_rawls_envelope(np.array([s["sand"]]), np.array([s["clay"]]))
    wp, fc = float(env["theta_wp"][0]), float(env["theta_fc"][0])
    awc = np.array([[max(fc - wp, 0.02) * DEFAULT_ROOT_DEPTH_M * 1000.0]])
    liq, _ = snowmelt_liquid_input(s["P"][:, None, None], s["T"][:, None, None], days, **params)
    w = thornthwaite_mather_wetness(liq[:, 0, :], s["PET"][:, None], awc)[:, 0]
    return pd.DataFrame({"date": tct, "theta_mod": wp + w * (fc - wp)})


def _per_site_r(st, params, tct, days, names=None):
    rs = {}
    for nm, s in st.items():
        if names and nm not in names:
            continue
        mg = s["obs"].merge(_theta(s, params, tct, days), on="date")
        if len(mg) >= 12:
            rs[nm] = float(np.corrcoef(mg.theta_obs, mg.theta_mod)[0, 1])
    return rs


def main():
    st, tct, days = _load()
    names = list(st)

    def mean_r(params, train):
        rs = _per_site_r(st, params, tct, days, names=train)
        return float(np.mean(list(rs.values()))) if rs else -1.0

    combos = [dict(ddf=a, t_snow_hi=b, t_melt=c)
              for a, b, c in itertools.product(GRID["ddf"], GRID["t_snow_hi"], GRID["t_melt"])]

    # Global best (all stations) — the parameters we adopt.
    best = max(combos, key=lambda p: mean_r(p, names))
    r_default = _per_site_r(st, DEFAULT, tct, days)
    r_best = _per_site_r(st, best, tct, days)

    # LOSO: calibrate on 4 stations, evaluate the held-out — out-of-sample generalisation.
    loso_def, loso_cal = [], []
    for held in names:
        train = [n for n in names if n != held]
        p = max(combos, key=lambda p: mean_r(p, train))
        loso_def.append(_per_site_r(st, DEFAULT, tct, days, [held])[held])
        loso_cal.append(_per_site_r(st, p, tct, days, [held])[held])

    # Per-site bias correction (linear mean+std match) — RMSE before/after (preserves r).
    rmse_raw, rmse_bc = [], []
    bc_series = {}
    for nm, s in st.items():
        mg = s["obs"].merge(_theta(s, best, tct, days), on="date")
        o, m = mg.theta_obs.values, mg.theta_mod.values
        m_bc = o.mean() + (m - m.mean()) * (o.std() / (m.std() + 1e-9))
        rmse_raw.append(np.sqrt(np.mean((m - o) ** 2)))
        rmse_bc.append(np.sqrt(np.mean((m_bc - o) ** 2)))
        mg["theta_bc"] = m_bc
        bc_series[nm] = mg

    summary = {
        "default_params": DEFAULT, "calibrated_params": best,
        "mean_r_default": float(np.mean(list(r_default.values()))),
        "mean_r_calibrated": float(np.mean(list(r_best.values()))),
        "loso_mean_r_default": float(np.mean(loso_def)),
        "loso_mean_r_calibrated": float(np.mean(loso_cal)),
        "rmse_raw": float(np.mean(rmse_raw)), "rmse_bias_corrected": float(np.mean(rmse_bc)),
        "per_site_r_default": r_default, "per_site_r_calibrated": r_best,
    }
    (PROC / "snow_calibration.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if not k.startswith("per_site")}, indent=2))
    print("\n>>> adopt in src/models/soil_moisture.py:  "
          f"_DDF_MM_PER_C_DAY={best['ddf']}, _T_SNOW_HI={best['t_snow_hi']}, _T_MELT={best['t_melt']}")

    # --- Figure ---
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1.1, 1.4, 1]})
    x = np.arange(len(names))
    ax[0].bar(x - 0.2, [r_default[n] for n in names], 0.38, color="#bbbbbb", label="default snow")
    ax[0].bar(x + 0.2, [r_best[n] for n in names], 0.38, color=OI[2], label="calibrated snow")
    ax[0].set_xticks(x); ax[0].set_xticklabels([n[:10] for n in names], rotation=30, ha="right", fontsize=8)
    ax[0].set_ylabel("per-station r"); ax[0].legend(fontsize=8)
    ax[0].set_title(f"Snow calibration (LOSO r {summary['loso_mean_r_default']:.2f}→"
                    f"{summary['loso_mean_r_calibrated']:.2f})", fontsize=11, fontweight="bold")
    ax[0].grid(axis="x", visible=False)

    nm0 = max(r_best, key=r_best.get)
    mg = bc_series[nm0].sort_values("date")
    ax[1].plot(mg.date, mg.theta_obs, color=INK, lw=1.5, label="SNOTEL in-situ")
    ax[1].plot(mg.date, mg.theta_mod, color="#bbbbbb", lw=1.2, label="model (calibrated snow)")
    ax[1].plot(mg.date, mg.theta_bc, color=OI[3], lw=1.4, label="+ per-site bias correction")
    ax[1].set_ylabel("θ (m³/m³)"); ax[1].legend(fontsize=8, loc="upper right")
    ax[1].set_title(f"{nm0} — bias correction anchors the level", fontsize=11, fontweight="bold")
    ax[1].grid(alpha=0.3)

    ax[2].axis("off")
    txt = ("Snow parameters (grid + LOSO)\n" + "-" * 30 + "\n"
           f"default   ddf={DEFAULT['ddf']}  T_hi={DEFAULT['t_snow_hi']}  T_melt={DEFAULT['t_melt']}\n"
           f"calibrated ddf={best['ddf']}  T_hi={best['t_snow_hi']}  T_melt={best['t_melt']}\n\n"
           f"mean per-site r : {summary['mean_r_default']:.2f} -> {summary['mean_r_calibrated']:.2f}\n"
           f"LOSO (held-out) : {summary['loso_mean_r_default']:.2f} -> {summary['loso_mean_r_calibrated']:.2f}\n\n"
           "Per-site bias correction (operational;\nconsumes SNOTEL as training):\n"
           f"  RMSE {summary['rmse_raw']:.3f} -> {summary['rmse_bias_corrected']:.3f} m³/m³\n"
           "  (correlation preserved; the offset is a\n  fixable representativeness bias)\n\n"
           "After bias correction SNOTEL is training,\nnot validation — SMAP (#29) is the\nremaining independent test.")
    ax[2].text(0.0, 1.0, txt, va="top", family="DejaVu Sans Mono", fontsize=8.2, color=INK)

    fig.suptitle("Snow-parameter calibration + bias decomposition against SNOTEL",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.savefig(OUT / "snow_calibration.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", OUT / "snow_calibration.png", "and", PROC / "snow_calibration.json")


if __name__ == "__main__":
    main()
