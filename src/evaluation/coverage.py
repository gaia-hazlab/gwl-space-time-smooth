"""Calibrated-uncertainty diagnostics: interval coverage, PIT, CRPS (issue #5).

"σ grows away from wells" is necessary but not sufficient. For a hazard product the
uncertainty must be *trustworthy*: a 90 % predictive interval should contain ~90 % of
withheld observations. This module produces, **per hydrogeologic domain**, the empirical
coverage of nominal central intervals, the PIT mean, and the CRPS, plus a calibration gate
(|empirical − nominal| ≤ 0.05 at 90 % in gate-mode domains). Out-of-fold (mean, σ) come
from per-domain spatial-block CV with the random-forest tree-ensemble spread.

Pairs with the per-domain gates (#3) and the confidence mask (#4).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from src.evaluation.domain_gates import DOMAIN_GATES
from src.features.hydrogeologic_domains import DOMAINS

logger = logging.getLogger(__name__)

DEFAULT_LEVELS = (0.5, 0.8, 0.9, 0.95)
COVERAGE_TOL = 0.05          # allowed |empirical − nominal| at 90 %
MIN_WELLS_FOR_COVERAGE = 10


def _norm():
    from scipy.stats import norm
    return norm


def coverage_at_levels(y, mu, sigma, levels=DEFAULT_LEVELS) -> dict:
    """Empirical coverage of central Gaussian intervals at each nominal level."""
    norm = _norm()
    sigma = np.maximum(np.asarray(sigma, float), 1e-9)
    z = np.abs((np.asarray(y, float) - np.asarray(mu, float)) / sigma)
    return {lvl: float(np.mean(z <= norm.ppf(0.5 + lvl / 2))) for lvl in levels}


def pit_values(y, mu, sigma) -> np.ndarray:
    """Probability Integral Transform Φ((y−μ)/σ); should be ~Uniform(0,1) if calibrated."""
    norm = _norm()
    sigma = np.maximum(np.asarray(sigma, float), 1e-9)
    return norm.cdf((np.asarray(y, float) - np.asarray(mu, float)) / sigma)


def crps_gaussian(y, mu, sigma) -> float:
    """Mean Continuous Ranked Probability Score for a Gaussian predictive (closed form)."""
    norm = _norm()
    sigma = np.maximum(np.asarray(sigma, float), 1e-9)
    z = (np.asarray(y, float) - np.asarray(mu, float)) / sigma
    crps = sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1.0 / np.sqrt(np.pi))
    return float(np.mean(crps))


def per_domain_coverage(y, mu, sigma, domain_codes, levels=DEFAULT_LEVELS) -> dict:
    """Coverage / PIT / CRPS per domain, with a 90 %-coverage calibration gate."""
    y, mu, sigma = map(lambda a: np.asarray(a, float), (y, mu, sigma))
    domain_codes = np.asarray(domain_codes)
    valid = np.isfinite(mu) & np.isfinite(sigma) & np.isfinite(y)
    out: dict[str, dict] = {}
    for code, name in DOMAINS.items():
        mode = DOMAIN_GATES.get(name, {}).get("mode", "report_only")
        m = (domain_codes == code) & valid
        n = int(m.sum())
        rec: dict = {"n": n, "mode": mode}
        if mode == "masked":
            out[name] = rec
            continue
        if n < MIN_WELLS_FOR_COVERAGE:
            rec["note"] = f"too few wells (<{MIN_WELLS_FOR_COVERAGE}) for coverage"
            if mode == "gate":
                rec["calibration"] = {"status": "unvalidated", "reason": rec["note"]}
            out[name] = rec
            continue
        cov = coverage_at_levels(y[m], mu[m], sigma[m], levels)
        rec["coverage"] = {f"{int(l * 100)}%": round(c, 3) for l, c in cov.items()}
        rec["crps"] = round(crps_gaussian(y[m], mu[m], sigma[m]), 3)
        rec["pit_mean"] = round(float(pit_values(y[m], mu[m], sigma[m]).mean()), 3)
        if mode == "gate":
            err = abs(cov[0.9] - 0.9)
            rec["calibration"] = {
                "status": "pass" if err <= COVERAGE_TOL else "FAIL",
                "cov90": round(cov[0.9], 3), "tol": COVERAGE_TOL,
            }
        out[name] = rec
    return out


def rf_spatial_oof(rf_kwargs, X, y, coords_5070, domain_codes, n_splits=5,
                   block_m_by_domain=None) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-fold (mean, σ) from per-domain spatial-block CV with RF tree-ensemble spread.

    σ is the standard deviation across the fold model's trees at each withheld well — the
    same predictive-spread definition used for the gridded σ in Stage 1.
    """
    from sklearn.ensemble import RandomForestRegressor

    from src.evaluation.cross_validate import spatial_block_cv
    from src.evaluation.domain_gates import (MIN_WELLS_FOR_CV, estimate_variogram_range)

    X, y = np.asarray(X, float), np.asarray(y, float)
    coords_5070 = np.asarray(coords_5070, float)
    domain_codes = np.asarray(domain_codes)
    block_m_by_domain = block_m_by_domain or {}
    mu = np.full(len(y), np.nan)
    sd = np.full(len(y), np.nan)

    for code, name in DOMAINS.items():
        idx = np.where(domain_codes == code)[0]
        if len(idx) < MIN_WELLS_FOR_CV:
            continue
        block = block_m_by_domain.get(name) or estimate_variogram_range(
            coords_5070[idx], y[idx])
        try:
            folds = spatial_block_cv(X[idx], y[idx], coords_5070[idx],
                                     spacing_m=block, n_splits=n_splits)
        except Exception as exc:
            logger.warning("OOF CV failed for %s: %s", name, exc)
            continue
        for f in folds.values():
            tr, te = f["train_idx"], f["test_idx"]
            if len(tr) == 0 or len(te) == 0:
                continue
            rf = RandomForestRegressor(**rf_kwargs).fit(X[idx][tr], y[idx][tr])
            per_tree = np.stack([t.predict(X[idx][te]) for t in rf.estimators_])
            mu[idx[te]] = per_tree.mean(axis=0)
            sd[idx[te]] = per_tree.std(axis=0)
    return mu, sd


def format_report(report: dict) -> str:
    rows = ["", f"{'domain':28s} {'n':>5} {'mode':12s} {'cov90':>6} {'CRPS':>6} {'PIT':>5}  calib",
            "-" * 78]
    for name, r in report.items():
        cov90 = (r.get("coverage") or {}).get("90%", "")
        rows.append(f"{name:28s} {r['n']:5d} {r['mode']:12s} {cov90:>6} "
                    f"{r.get('crps',''):>6} {r.get('pit_mean',''):>5}  "
                    f"{(r.get('calibration') or {}).get('status', r.get('note',''))}")
    return "\n".join(rows)


def write_coverage_report(report: dict, path: Path) -> bool:
    """Write coverage_metrics.json; return True if all gate-mode domains are calibrated."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = [n for n, r in report.items()
                if DOMAIN_GATES.get(n, {}).get("mode") == "gate"
                and (r.get("calibration") or {}).get("status") != "pass"]
    path.write_text(json.dumps(
        {"domains": report, "all_calibrated": not failures, "uncalibrated_domains": failures},
        indent=2))
    logger.info(format_report(report))
    if failures:
        logger.warning("Uncertainty NOT calibrated (90%% coverage) in: %s", failures)
    return not failures
