#!/usr/bin/env python3
"""L2 (#298): forecast reinitialisation and issue-time leakage record for the legacy twin.

Synthetic forcing only. Writes results/l2_reinitialisation.json.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.models import forecast as fc, soil_moisture as sm, hysteresis as hy, water_budget as wb  # noqa: E402
from src.models.dvv_coupling import coupling_envelope  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "l2_reinitialisation.json"
WP, FC, SAT = 0.10, 0.28, 0.45


def forcing(start, days, precip, tmean, pet=0.5):
    times = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(days, "D"))
    return fc.ForecastForcing(times=times, precip_mm=np.full((days, 1, 1), precip, float), pet_mm=np.full((days, 1, 1), pet, float),
                              dt_days=1.0, tmean_c=np.asarray(tmean, float).reshape(days, 1, 1), source="synthetic")


def snow_restart():
    """A mountain winter: 20 cold days (SWE 200 mm) then 10 warm days whose melt capacity (15 mm/d)
    exceeds the pack a segmented run starting on day 11 can hold (100 mm)."""
    t = np.r_[np.full(20, -5.0), np.full(10, 6.0)]
    full = forcing("2026-01-01", 30, 10.0, t)
    liq_full = fc.liquid_input(full)[:, 0, 0]
    seg2 = forcing("2026-01-11", 20, 10.0, t[10:])
    liq_seg2 = fc.liquid_input(seg2)[:, 0, 0]
    return {"melt_days_21_30_continuous_mm": float(liq_full[20:].sum() - 10.0 * 10), "melt_days_21_30_segmented_mm": float(liq_seg2[10:].sum() - 10.0 * 10),
            "swe_available_continuous_mm": 200.0, "swe_available_segmented_mm": 100.0, "melt_capacity_days_21_30_mm": 150.0,
            "forecast_signature_has_state_argument": any(k in inspect.signature(fc.forecast_soil_state).parameters for k in ("state", "swe0", "S0", "h0", "prior_state")),
            "budget_signature_has_initial_arrays": any(k in inspect.signature(wb.coupled_water_budget).parameters for k in ("S0", "theta0", "h0", "state")),
            "budget_init_choices": "init in {'fc', anything else -> wp}; wt_depth0_m only; head anomaly starts at 0"}


def theta_ref_after_first_step():
    f = forcing("2026-01-01", 10, 20.0, np.full(10, 8.0))
    out = fc.forecast_soil_state(f, WP, FC, SAT, vs30_base=300.0, wt_depth0_m=3.0, sand_pct=40.0, clay_pct=20.0)
    return {"theta_initial_fc": FC, "theta_after_step1": float(out.theta[0, 0, 0]),
            "theta_ref_equals_post_step_state": bool(abs(float(out.theta[0, 0, 0]) - FC) > 1e-6),
            "dvv_high_step1_is_zero_by_construction": float(out.dvv_high[0, 0, 0])}


def budget_segmented():
    liq = np.full((20, 1, 1), 8.0); pet = np.full((20, 1, 1), 1.0)
    full = wb.coupled_water_budget(liq, pet, WP, FC, SAT, wt_depth0_m=3.0, init="fc", dt_days=1.0)
    a = wb.coupled_water_budget(liq[:10], pet[:10], WP, FC, SAT, wt_depth0_m=3.0, init="fc", dt_days=1.0)
    b = wb.coupled_water_budget(liq[10:], pet[10:], WP, FC, SAT, wt_depth0_m=float(a.wt_depth_m[-1, 0, 0]), init="fc", dt_days=1.0)
    return {"theta_day20_continuous": float(full.theta[-1, 0, 0]), "theta_day20_segmented": float(b.theta[-1, 0, 0]),
            "wt_day20_continuous_m": float(full.wt_depth_m[-1, 0, 0]), "wt_day20_segmented_m": float(b.wt_depth_m[-1, 0, 0]),
            "note": "root storage cannot be handed over (init is a label), the legacy recession reference resets to the new wt_depth0"}


def hysteresis_branch():
    env = coupling_envelope(np.array([[40.0]]), np.array([[20.0]]), np.array([[WP]]), np.array([[SAT]]))
    th = np.linspace(0.15, 0.40, 26)                                   # a pure wetting trajectory
    traj = th.reshape(-1, 1, 1)
    full = hy.vadose_dvv_hysteretic(traj, env)[:, 0, 0]
    late = hy.vadose_dvv_hysteretic(traj[13:], env)[:, 0, 0]          # the same trajectory entered mid-wetting
    sig = inspect.signature(hy.vadose_dvv_hysteretic)
    return {"signature": str(sig), "dvv_at_theta_0.40_continuous": float(full[-1]), "dvv_at_theta_0.40_entered_mid_wetting": float(late[-1]),
            "difference": float(full[-1] - late[-1]), "note": "each call starts from theta[0] on the default branch; the reversal memory is not carried across calls"}


def centring_leakage():
    dates = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    dtw = 5.0 + 0.05 * np.arange(len(dates)) + 0.4 * np.sin(2 * np.pi * dates.month / 12)   # trend + season
    df = pd.DataFrame({"site_no": "S1", "date": dates, "dtw_m": dtw})
    issue = pd.Timestamp("2025-01-01")
    well_mean = df.groupby("site_no").dtw_m.transform("mean")            # gwl_dynamic.py:94-97, whole window
    anom_whole = (df.dtw_m - well_mean)[df.date == issue].item()
    pre = df[df.date < issue].dtw_m.mean()                              # baseline frozen at issue time
    anom_frozen = (df.dtw_m - pre)[df.date == issue].item()
    return {"anomaly_at_issue_whole_window_m": float(anom_whole), "anomaly_at_issue_frozen_baseline_m": float(anom_frozen),
            "leakage_shift_m": float(anom_whole - anom_frozen), "trend_m_per_year": 0.6}


def two_snow_models():
    days = 120
    t = -4.0 + 10.0 * np.sin(np.linspace(0, np.pi, days)) ** 2 - 2.0      # cold shoulders, warm middle
    p = np.full(days, 6.0)
    f = forcing("2025-12-01", days, 6.0, t)
    liq_fc = fc.liquid_input(f)[:, 0, 0]
    sig = str(inspect.signature(sm.snowmelt_liquid_input))
    try:
        W, swe_sm = sm.snowmelt_liquid_input(p.reshape(days, 1, 1), t.reshape(days, 1, 1), np.ones(days))   # monthly model driven per day
        liq_sm = np.asarray(W, float).reshape(days, -1)[:, 0]
        res = {"callable": True, "liquid_total_forecast_model_mm": float(liq_fc.sum()), "liquid_total_soil_moisture_model_mm": float(liq_sm.sum()),
               "max_abs_daily_difference_mm": float(np.max(np.abs(liq_fc - liq_sm))), "days_with_different_liquid": int(np.sum(np.abs(liq_fc - liq_sm) > 1e-9)),
               "final_swe_soil_moisture_model_mm": float(np.asarray(swe_sm, float).ravel()[0])}
    except Exception as e:  # record, do not hide
        res = {"callable": False, "error": repr(e)[:200], "liquid_total_forecast_model_mm": float(liq_fc.sum())}
    res.update({"soil_moisture_signature": sig, "forecast_params": {"DDF": fc.DDF_MM_C_DAY, "T_SNOW_LO": fc.T_SNOW_LO, "T_SNOW_HI": fc.T_SNOW_HI, "T_MELT": fc.T_MELT},
                "soil_moisture_params": {k: getattr(sm, k) for k in dir(sm) if k.isupper() and any(s in k for s in ("DDF", "SNOW", "MELT", "T_"))}})
    return res


def main():
    record = {"issue": "gaia-hazlab/gwl-space-time-smooth#298",
              "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
              "sources_sha256": {p: hashlib.sha256((ROOT / "src/models" / p).read_bytes()).hexdigest() for p in ("forecast.py", "water_budget.py", "hysteresis.py", "gwl_dynamic.py", "soil_moisture.py")},
              "snow_restart": snow_restart(), "theta_ref": theta_ref_after_first_step(), "budget_segmented": budget_segmented(),
              "hysteresis_branch": hysteresis_branch(), "centring_leakage": centring_leakage(), "two_snow_models": two_snow_models()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1, allow_nan=False, default=float) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k not in ("sources_sha256",)}, indent=1, default=str)[:3500])


if __name__ == "__main__":
    main()
