#!/usr/bin/env python3
"""U1 (#299): how much a spatially compound statistic changes when a posterior is sampled from
marginal variances instead of the joint covariance. Sensitivity demonstration, not calibration.
Writes results/u1_dependence_sensitivity.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.special import gamma, kv

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.models import observability as ob  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "u1_dependence_sensitivity.json"
N, DX_KM, SIGMA = 200, 0.09, 0.5
WELLS, OBS_DTW, PRIOR_DTW = [20, 60, 100, 140, 180], 1.2, 1.5
REACH = slice(90, 110)
THRESH_MIN, THRESH_MEAN = 1.0, 1.25
NDRAW, SEED = 10_000, 11


def matern(r_km, L_km, nu):
    """Whittle-Matern with the repository's convention (sqrt(2 nu) r / L), see observability.RANGE_CONVENTION."""
    x = np.sqrt(2 * nu) * np.asarray(r_km, float) / L_km
    out = np.ones_like(x)
    m = x > 0
    out[m] = (2 ** (1 - nu) / gamma(nu)) * (x[m] ** nu) * kv(nu, x[m])
    return out


def main():
    x = np.arange(N) * DX_KM
    r = np.abs(x[:, None] - x[None, :])
    G = np.zeros((len(WELLS), N)); G[np.arange(len(WELLS)), WELLS] = 1.0
    d = np.full(len(WELLS), OBS_DTW)
    rng = np.random.default_rng(SEED)
    rows, checks = [], {}
    for L in (4.0, 12.0, 24.0):
        for nu in (0.5, 1.5, 2.5):
            C = matern(r, L, nu)
            # cross-check the repository's own correlation function on the first row
            try:
                repo = ob.matern_correlation(r[0], L, nu)
                checks[f"L{L}_nu{nu}"] = float(np.max(np.abs(np.asarray(repo) - C[0])))
            except Exception as e:  # signature mismatch is recorded, not hidden
                checks[f"L{L}_nu{nu}"] = f"not comparable: {e!r}"[:120]
            B = SIGMA ** 2 * C
            for Rvar in (0.1, 0.3):
                S = G @ B @ G.T + Rvar * np.eye(len(WELLS))
                K = B @ G.T @ np.linalg.solve(S, np.eye(len(WELLS)))
                m_a = PRIOR_DTW + K @ (d - PRIOR_DTW)
                C_a = B - K @ G @ B
                C_a = 0.5 * (C_a + C_a.T) + 1e-10 * np.eye(N)
                Lc = np.linalg.cholesky(C_a)
                z = rng.standard_normal((NDRAW, N))
                coh = m_a + z @ Lc.T
                ind = m_a + z * np.sqrt(np.diag(C_a))
                def stats(s):
                    reach = s[:, REACH]
                    p_min = float(np.mean(reach.min(axis=1) < THRESH_MIN))
                    p_mean = float(np.mean(reach.mean(axis=1) < THRESH_MEAN))
                    return p_min, p_mean
                pm_c, pa_c = stats(coh); pm_i, pa_i = stats(ind)
                se = lambda p: float(np.sqrt(max(p * (1 - p), 1e-12) / NDRAW))
                rows.append({"L_km": L, "nu": nu, "R_m2": Rvar,
                             "P_min_reach_below_1m": {"coherent": pm_c, "independent": pm_i, "se": se(max(pm_c, pm_i)), "ratio_ind_over_coh": (pm_i / pm_c) if pm_c > 0 else None},
                             "P_mean_reach_below_1.25m": {"coherent": pa_c, "independent": pa_i, "se": se(max(pa_c, pa_i)), "ratio_ind_over_coh": (pa_i / pa_c) if pa_c > 0 else None},
                             "posterior_sigma_reach_mean_m": float(np.sqrt(np.diag(C_a))[REACH].mean()),
                             "posterior_corr_reach_ends": float(C_a[90, 109] / np.sqrt(C_a[90, 90] * C_a[109, 109]))})
    record = {"issue": "gaia-hazlab/gwl-space-time-smooth#299", "scope": "synthetic Matern prior, linear point operator, no model error; sensitivity of a compound statistic to sampling dependence, not a calibration claim",
              "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
              "observability_sha256": hashlib.sha256((ROOT / "src/models/observability.py").read_bytes()).hexdigest(),
              "setup": {"cells": N, "dx_km": DX_KM, "sigma_prior_m": SIGMA, "wells": WELLS, "obs_dtw_m": OBS_DTW, "prior_dtw_m": PRIOR_DTW, "reach_cells": [90, 109], "thresholds_m": {"min": THRESH_MIN, "mean": THRESH_MEAN}, "draws": NDRAW, "seed": SEED},
              "repo_matern_cross_check_max_abs_diff": checks, "rows": rows,
              "production_path_note": "src/models/observability.py:151-153 states the matrix-free path yields only diag(C_post): no samples and no cross-cell covariance; the coherent column above is therefore unavailable at domain scale today"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1, allow_nan=False) + "\n")
    for rw in rows:
        print(f"L={rw['L_km']:>4} nu={rw['nu']} R={rw['R_m2']}: P(min<1) coh {rw['P_min_reach_below_1m']['coherent']:.3f} ind {rw['P_min_reach_below_1m']['independent']:.3f} | P(mean<1.25) coh {rw['P_mean_reach_below_1.25m']['coherent']:.3f} ind {rw['P_mean_reach_below_1.25m']['independent']:.3f} | corr ends {rw['posterior_corr_reach_ends']:.2f}")
    print("matern cross-check:", checks)


if __name__ == "__main__":
    main()
