"""Per-hydrogeologic-domain validation gates and variogram-sized spatial CV (issue #3).

Retires the single global ``RMSE < 8 m`` gate and the fixed 200 km CV blocks. Per the
groundwater-hydrologist review, accuracy must be judged **per flow system**: the well-dense
unconsolidated valley fill is held to a sub-metre standard (the liquefaction core), fractured
uplands are report-only, and deep-volcanic / confined-basalt domains are masked rather than
scored. CV blocks are sized to each domain's **empirical variogram range** so held-out blocks
are spatially independent (a 200 km block is larger than the whole Puget Lowland; fractured
rock decorrelates in ~km).

Pairs with ``src.features.hydrogeologic_domains`` (#2). Coverage/PIT calibration is #5.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from src.features.hydrogeologic_domains import DOMAINS

logger = logging.getLogger(__name__)

# Per-domain acceptance gates (depth-to-water, metres). mode:
#   "gate"        — RMSE/bias must meet the target/threshold or the domain FAILS.
#   "report_only" — metrics reported, never fails the build (sparse / hard terrain).
#   "masked"      — out of domain for a shallow product; not scored (masked downstream, #4).
DOMAIN_GATES: dict[str, dict] = {
    "unconsolidated_valley_fill": {"mode": "gate", "rmse_target": 0.75, "rmse_threshold": 1.5, "bias_max": 0.25},
    "unconsolidated_basin":       {"mode": "gate", "rmse_target": 1.5,  "rmse_threshold": 2.5, "bias_max": 0.5},
    "coastal":                    {"mode": "gate", "rmse_target": 1.0,  "rmse_threshold": 2.0, "bias_max": 0.3},
    "fractured_upland":           {"mode": "report_only"},
    "volcanic_deep":              {"mode": "masked"},
    "confined_basalt":            {"mode": "masked"},
}

# Variogram-range clamps for CV block sizing (metres).
MIN_BLOCK_M = 2_000.0
MAX_BLOCK_M = 50_000.0
DEFAULT_BLOCK_M = 10_000.0
MIN_WELLS_FOR_CV = 20      # below this a domain is reported (n only), not cross-validated


def estimate_variogram_range(
    coords_5070: np.ndarray, values: np.ndarray, n_lags: int = 15,
    max_pairs: int = 200_000, random_state: int = 0,
) -> float:
    """Empirical-variogram range (m): the lag at which the semivariance first reaches
    ~95% of its sill. Clamped to [MIN_BLOCK_M, MAX_BLOCK_M]; falls back to DEFAULT_BLOCK_M
    when there are too few points to estimate.
    """
    coords_5070 = np.asarray(coords_5070, float)
    values = np.asarray(values, float)
    n = len(values)
    if n < 8:
        return DEFAULT_BLOCK_M

    rng = np.random.default_rng(random_state)
    total_pairs = n * (n - 1) // 2
    if total_pairs > max_pairs:
        # Sample random index pairs directly — never materialize the O(n^2) triangle.
        i = rng.integers(0, n, size=max_pairs)
        j = rng.integers(0, n, size=max_pairs)
        keep = i != j
        i, j = i[keep], j[keep]
    else:
        i, j = np.triu_indices(n, k=1)
    d = np.hypot(coords_5070[i, 0] - coords_5070[j, 0],
                 coords_5070[i, 1] - coords_5070[j, 1])
    semivar = 0.5 * (values[i] - values[j]) ** 2

    dmax = np.percentile(d, 90)
    if dmax <= 0:
        return DEFAULT_BLOCK_M
    edges = np.linspace(0, dmax, n_lags + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    binned = np.array([semivar[(d >= edges[k]) & (d < edges[k + 1])].mean()
                       if np.any((d >= edges[k]) & (d < edges[k + 1])) else np.nan
                       for k in range(n_lags)])
    valid = ~np.isnan(binned)
    if valid.sum() < 3:
        return DEFAULT_BLOCK_M
    sill = np.nanmax(binned)
    if sill <= 0:
        return DEFAULT_BLOCK_M
    reached = centers[valid][binned[valid] >= 0.95 * sill]
    rng_m = float(reached[0]) if reached.size else float(dmax)
    return float(np.clip(rng_m, MIN_BLOCK_M, MAX_BLOCK_M))


def per_domain_cv(
    estimator, X: np.ndarray, y: np.ndarray, coords_5070: np.ndarray,
    domain_codes: np.ndarray, n_splits: int = 5,
) -> dict:
    """Spatial block CV stratified by hydrogeologic domain, with per-domain block size.

    ``domain_codes`` is the integer domain per sample (``DOMAINS`` legend). Returns a dict
    keyed by domain name: ``{n, mode, block_km, rmse, bias, r2, gate}`` (CV metrics present
    only where the domain has ≥ MIN_WELLS_FOR_CV wells).
    """
    from src.evaluation.cross_validate import run_cv_metrics

    domain_codes = np.asarray(domain_codes)
    out: dict[str, dict] = {}
    for code, name in DOMAINS.items():
        gate = DOMAIN_GATES.get(name, {"mode": "report_only"})
        mask = domain_codes == code
        n = int(mask.sum())
        rec: dict = {"n": n, "mode": gate["mode"]}

        if gate["mode"] == "masked":
            out[name] = rec                       # masked downstream — not scored
            continue
        if n < MIN_WELLS_FOR_CV:
            rec["note"] = f"too few wells (<{MIN_WELLS_FOR_CV}) for spatial CV"
            # A gate-mode domain that cannot be validated must NOT silently pass.
            if gate["mode"] == "gate":
                rec["gate"] = {"status": "unvalidated", "reason": rec["note"]}
            out[name] = rec
            continue

        block_m = estimate_variogram_range(coords_5070[mask], y[mask])
        rec["block_km"] = round(block_m / 1000, 1)
        try:
            m = run_cv_metrics(estimator, X[mask], y[mask], coords_5070[mask],
                               spacing_m=block_m, n_splits=n_splits)
            rec.update(rmse=round(m["rmse_mean"], 3), rmse_std=round(m["rmse_std"], 3),
                       bias=round(m["bias_mean"], 3), r2=round(m["r2_mean"], 3))
            rec["gate"] = _evaluate_gate(name, rec)
        except Exception as exc:                  # degenerate folds etc. — report, don't crash
            rec["note"] = f"CV failed: {type(exc).__name__}: {exc}"
            if gate["mode"] == "gate":
                rec["gate"] = {"status": "unvalidated", "reason": rec["note"]}
        out[name] = rec
    return out


def _evaluate_gate(name: str, rec: dict) -> dict:
    """Pass/fail a single domain against DOMAIN_GATES (gate-mode domains only)."""
    g = DOMAIN_GATES[name]
    if g["mode"] != "gate":
        return {"status": g["mode"]}
    rmse, bias = rec.get("rmse"), abs(rec.get("bias", 0.0))
    passed = rmse is not None and rmse <= g["rmse_threshold"] and bias <= g["bias_max"]
    return {
        "status": "pass" if passed else "FAIL",
        "meets_target": rmse is not None and rmse <= g["rmse_target"],
        "rmse_target": g["rmse_target"], "rmse_threshold": g["rmse_threshold"],
        "bias_max": g["bias_max"],
    }


def format_report(report: dict) -> str:
    """Human-readable per-domain table (logged + printed)."""
    rows = ["", f"{'domain':28s} {'n':>5} {'mode':12s} {'block':>7} {'RMSE':>7} {'bias':>7} {'R2':>6}  gate",
            "-" * 92]
    for name, r in report.items():
        rows.append(
            f"{name:28s} {r['n']:5d} {r['mode']:12s} "
            f"{(str(r.get('block_km',''))+' km') if 'block_km' in r else '':>7} "
            f"{r.get('rmse',''):>7} {r.get('bias',''):>7} {r.get('r2',''):>6}  "
            f"{(r.get('gate') or {}).get('status', r.get('note',''))}"
        )
    return "\n".join(rows)


def write_report(report: dict, path: Path) -> bool:
    """Write per-domain block_cv_metrics.json. Returns True if all gate-mode domains pass."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A gate-mode domain must reach status "pass"; FAIL *or* unvalidated (CV error /
    # too few wells) counts against the build — never silently pass an unchecked domain.
    failures = [n for n, r in report.items()
                if DOMAIN_GATES.get(n, {}).get("mode") == "gate"
                and (r.get("gate") or {}).get("status") != "pass"]
    payload = {"domains": report, "all_gates_pass": not failures, "failed_domains": failures}
    path.write_text(json.dumps(payload, indent=2))
    logger.info(format_report(report))
    if failures:
        logger.warning("Validation gates FAILED in: %s", failures)
    return not failures
