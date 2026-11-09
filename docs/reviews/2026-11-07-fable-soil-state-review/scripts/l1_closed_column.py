#!/usr/bin/env python3
"""L1 (#297): closed-column water-ledger audit of the legacy store model.

Runs ``src.models.water_budget.coupled_water_budget`` at the pinned revision on one cell with
zero rain and zero PET (unless stated) and books the combined root-zone + aquifer ledger in
float64 from the function's float32 outputs. A diagnostic of the legacy land-surface path: it does
not ask the MODFLOW replacement to reproduce anything here. Writes results/l1_closed_column.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.models import water_budget as wb  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "l1_closed_column.json"
WP, FC, SAT, ROOT_M, SY = 0.10, 0.28, 0.45, 1.0, 0.30
F32_BOUND_MM = float(np.spacing(np.float32(SAT))) * ROOT_M * 1000.0   # theta resolution -> mm of root water


def ledger(res, dtw0, liquid, dt_days):
    """Per-step combined residual (mm): dS_root + Sy*dh*1000 + outflows - inflow, from float32 outputs."""
    S = res.theta.astype("float64")[:, 0, 0] * ROOT_M * 1000.0
    S_prev = np.concatenate([[WP * ROOT_M * 1000.0], S[:-1]])
    wt = res.wt_depth_m.astype("float64")[:, 0, 0]
    wt_prev = np.concatenate([[dtw0], wt[:-1]])
    dG = (wt_prev - wt) * SY * 1000.0                      # aquifer storage change (mm), rising table = +
    out = (res.runoff_mm + res.interflow_mm + res.baseflow_mm + res.aet_mm).astype("float64")[:, 0, 0]
    resid = (S - S_prev) + dG + out - liquid[:, 0, 0]
    return resid, S, wt, out


def run(dtw0, days, cap_max_mm, liquid_mm_day=0.0, pet_mm_day=0.0, hand_m=None, dt_days=1.0):
    nt = int(round(days / dt_days))
    liquid = np.full((nt, 1, 1), liquid_mm_day * dt_days)
    pet = np.full((nt, 1, 1), pet_mm_day * dt_days)
    res = wb.coupled_water_budget(liquid, pet, WP, FC, SAT, root_depth_m=ROOT_M, specific_yield=SY,
                                  wt_depth0_m=dtw0, init="wp", dt_days=dt_days, cap_max_mm=cap_max_mm,
                                  hand_m=None if hand_m is None else np.full((1, 1), hand_m))
    resid, S, wt, out = ledger(res, dtw0, liquid, dt_days)
    return res, resid, S, wt, out


def case(name, dtw0, days, **kw):
    rows = {}
    for label, cap in (("capillary_on", wb.CAP_MAX_MM), ("capillary_off", 0.0)):
        res, resid, S, wt, out = run(dtw0, days, cap, **kw)
        rows[label] = {
            "residual_day1_mm": float(resid[0]), "residual_sum_mm": float(resid.sum()),
            "cap_rise_sum_mm": float(res.cap_rise_mm.astype("float64").sum()),
            "soil_change_mm": float(S[-1] - WP * ROOT_M * 1000.0),
            "aquifer_change_mm": float((dtw0 - wt[-1]) * SY * 1000.0),
            "recharge_sum_mm": float(res.recharge_mm.astype("float64").sum()),
            "baseflow_sum_mm": float(res.baseflow_mm.astype("float64").sum()),
            "aet_sum_mm": float(res.aet_mm.astype("float64").sum()),
            "runoff_sum_mm": float(res.runoff_mm.astype("float64").sum()),
            "wt_depth_final_m": float(wt[-1]), "wt_depth_min_m": float(wt.min()),
            "head_monotone_rise": bool(np.all(np.diff(wt) <= 1e-9)),
            "first_day_table_at_surface": (int(np.argmax(wt <= 0)) + 1) if np.any(wt <= 0) else None,
        }
    return {"name": name, "dtw0_m": dtw0, "days": days, **{k: (None if v is None else float(v)) for k, v in kw.items() if k != "hand_m"},
            "hand_m": kw.get("hand_m"), "rows": rows}


def storage_bound_sweep():
    """Valid forcing (P >= 0, PET >= 0): count how often S leaves [Swp, Ssat] before the clip at line 251."""
    rng = np.random.default_rng(7)
    nt, nc = 3650, 20
    liquid = rng.gamma(0.6, 6.0, size=(nt, nc)) * (rng.random((nt, nc)) < 0.45)   # PRISM-like wet-day mix
    pet = np.clip(2.0 + 2.0 * np.sin(2 * np.pi * np.arange(nt) / 365.25)[:, None] + 0.3 * rng.standard_normal((nt, nc)), 0, None)
    # replicate the loop's own arithmetic to count pre-clip excursions (the function clips silently)
    z = ROOT_M * 1000.0; Swp, Sfc, Ssat = WP * z, FC * z, SAT * z
    S = np.full(nc, Swp); hits = 0; drain_step = 1.0 - np.exp(-1.0 / wb.DRAIN_TAU_DAYS)
    for t in range(nt):
        cap = wb._capillary_rise(5.0, ROOT_M, (Ssat - S) / (Ssat - Swp), wb.CAP_MAX_MM / wb.DAYS_PER_MONTH, wb.CAP_FRINGE_M)
        S = S + (np.minimum(S + cap, Ssat) - S)
        deficit = SY * 5.0 * 1000.0
        S = S + (liquid[t] - np.maximum(liquid[t] - deficit, 0.0))
        S = S - np.maximum(S - Ssat, 0.0)
        S = S - np.minimum(pet[t], np.maximum(S - Swp, 0.0))
        S = S - np.maximum(S - Sfc, 0.0) * drain_step
        hits += int(np.sum((S < Swp - 1e-9) | (S > Ssat + 1e-9)))
        S = np.clip(S, Swp, Ssat)
    # invalid input: negative rain is absorbed by the clip
    bad = wb.coupled_water_budget(np.full((6, 1, 1), -50.0), np.zeros((6, 1, 1)), WP, FC, SAT, root_depth_m=ROOT_M,
                                  specific_yield=SY, wt_depth0_m=5.0, init="fc", dt_days=1.0)
    return {"valid_forcing_days_x_cells": nt * nc, "pre_clip_excursions": hits,
            "invalid_negative_rain_theta_min": float(bad.theta.min()), "note": "six days of -50 mm/d from field capacity (280 mm) would reach -20 mm; the clip at line 251 holds theta at the wilting point and raises nothing"}


def timestep_comparison():
    rows = {}
    for dt in (1.0, 0.25):
        res, *_ = run(5.0, 30, 0.0, liquid_mm_day=10.0, dt_days=dt)
        rows[f"dt_{dt}"] = {"drainage_total_mm": float((res.recharge_mm + res.interflow_mm).astype("float64").sum()),
                            "theta_final": float(res.theta[-1, 0, 0])}
    rows["relative_difference"] = rows["dt_0.25"]["drainage_total_mm"] / rows["dt_1.0"]["drainage_total_mm"] - 1.0
    return rows


def shallow_table_fraction():
    tif = ROOT / "data/processed/baseline_dtw_m.tif"
    if not tif.exists():
        return {"available": False}
    import rasterio
    with rasterio.open(tif) as src:
        a = src.read(1).astype("float64"); a[a == src.nodata] = np.nan
        return {"available": True, "file": str(tif.relative_to(ROOT)), "cells_finite": int(np.isfinite(a).sum()),
                "fraction_dtw_below_3m": float(np.nanmean(a < 3.0)), "fraction_dtw_below_2m": float(np.nanmean(a < 2.0)),
                "note": "legacy baseline raster on disk (July 2026); DTW < root base + 2 m marks cells where option B's upward exchange matters"}


def main():
    src = ROOT / "src/models/water_budget.py"
    record = {
        "issue": "gaia-hazlab/gwl-space-time-smooth#297", "scope": "legacy store model diagnostic; not an MF6 acceptance test",
        "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "parameters": {"theta_wp": WP, "theta_fc": FC, "theta_sat": SAT, "root_depth_m": ROOT_M, "specific_yield": SY,
                       "cap_max_mm_per_month": wb.CAP_MAX_MM, "cap_fringe_m": wb.CAP_FRINGE_M, "init": "wp"},
        "float32_rounding_bound_mm": F32_BOUND_MM,
        "analytic_expectation_mm_day1": {"dtw_0.5": 30.0 / wb.DAYS_PER_MONTH * 0.75, "dtw_1.5": 30.0 / wb.DAYS_PER_MONTH * 0.25, "dtw_2.5": 0.0},
        "cases": [
            case("primary_nonoverlap_dtw1.5", 1.5, 1), case("primary_nonoverlap_dtw1.5_365d", 1.5, 365),
            case("overlap_dtw0.5", 0.5, 1), case("overlap_dtw0.5_365d", 0.5, 365),
            case("negative_control_dtw2.5", 2.5, 1), case("negative_control_dtw2.5_365d", 2.5, 365),
            case("valley_hand0_rain5_365d", 2.0, 365, liquid_mm_day=5.0, hand_m=0.0),
            case("valley_hand0_norain_365d_dtw2.0", 2.0, 365, hand_m=0.0),   # fringe edge: zero capillary flux by construction
            case("valley_hand0_norain_365d_dtw1.5", 1.5, 365, hand_m=0.0),   # created water stays in the root zone (never exceeds field capacity)
            case("valley_hand0_norain_365d_dtw0.5", 0.5, 365, hand_m=0.0),   # created water drains, recharges and lifts a table that has no sink
        ],
        "storage_bound": storage_bound_sweep(), "timestep": timestep_comparison(), "domain_context": shallow_table_fraction(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1, allow_nan=False) + "\n")
    print(json.dumps({c["name"]: {k: round(v["residual_day1_mm"], 6) for k, v in c["rows"].items()} for c in record["cases"]}, indent=1))
    print("storage_bound:", record["storage_bound"]); print("timestep:", record["timestep"]); print("context:", record["domain_context"])


if __name__ == "__main__":
    main()
