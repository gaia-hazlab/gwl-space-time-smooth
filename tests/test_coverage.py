"""Tests for calibrated-uncertainty diagnostics (issue #5).

Runs standalone (`python -m tests.test_coverage`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.evaluation.coverage import (
    coverage_at_levels,
    crps_gaussian,
    per_domain_coverage,
    pit_values,
    rf_spatial_oof,
    write_coverage_report,
)
from src.features.hydrogeologic_domains import DOMAINS

CODE = {v: k for k, v in DOMAINS.items()}


def test_coverage_matches_nominal_when_calibrated():
    rng = np.random.default_rng(0)
    n = 20000
    mu = rng.normal(0, 1, n)
    sigma = rng.uniform(0.5, 2.0, n)
    y = rng.normal(mu, sigma)                          # perfectly calibrated
    cov = coverage_at_levels(y, mu, sigma)
    for lvl in (0.5, 0.9, 0.95):
        assert abs(cov[lvl] - lvl) < 0.02


def test_overconfident_undercovers():
    rng = np.random.default_rng(1)
    n = 20000
    mu = np.zeros(n)
    y = rng.normal(0, 2.0, n)                          # true spread 2× stated
    cov = coverage_at_levels(y, mu, np.ones(n))
    assert cov[0.9] < 0.9                              # 90% interval covers far less


def test_pit_uniform_when_calibrated():
    rng = np.random.default_rng(2)
    n = 20000
    mu = rng.normal(0, 1, n); sigma = np.ones(n); y = rng.normal(mu, sigma)
    pit = pit_values(y, mu, sigma)
    assert abs(pit.mean() - 0.5) < 0.02 and abs(np.std(pit) - 1 / np.sqrt(12)) < 0.02


def test_crps_smaller_for_sharper_accurate_forecast():
    y = np.zeros(2000)
    sharp = crps_gaussian(y, np.zeros(2000), np.full(2000, 0.5))
    diffuse = crps_gaussian(y, np.zeros(2000), np.full(2000, 3.0))
    assert sharp < diffuse


def test_per_domain_coverage_structure_and_gate():
    rng = np.random.default_rng(3)
    n = 500
    mu = rng.normal(0, 1, n); sigma = np.ones(n); y = rng.normal(mu, sigma)
    codes = np.full(n, CODE["unconsolidated_valley_fill"])
    rep = per_domain_coverage(y, mu, sigma, codes)
    vf = rep["unconsolidated_valley_fill"]
    assert "coverage" in vf and vf["calibration"]["status"] == "pass"
    # masked domain present but unscored
    assert rep["confined_basalt"]["mode"] == "masked" and "coverage" not in rep["confined_basalt"]

    # uncalibrated (overconfident) gate domain -> FAIL + write_coverage_report False
    import json, pathlib, tempfile
    y2 = rng.normal(mu, 3.0)                           # 3× too confident
    rep2 = per_domain_coverage(y2, mu, sigma, codes)
    assert rep2["unconsolidated_valley_fill"]["calibration"]["status"] == "FAIL"
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "coverage_metrics.json"
        ok = write_coverage_report(rep2, p)
        payload = json.loads(p.read_text())
    assert ok is False and "unconsolidated_valley_fill" in payload["uncalibrated_domains"]


def test_rf_spatial_oof_produces_finite_predictions():
    from sklearn.ensemble import RandomForestRegressor  # noqa: F401  (availability check)
    rng = np.random.default_rng(4)
    n = 80
    xy = rng.uniform(0, 40_000, (n, 2))
    y = 1.0 + np.sin(xy[:, 0] / 4_000) + 0.2 * rng.standard_normal(n)
    X = np.column_stack([xy[:, 0], xy[:, 1]])
    codes = np.full(n, CODE["unconsolidated_valley_fill"])
    mu, sd = rf_spatial_oof(dict(n_estimators=40, random_state=0), X, y, xy, codes, n_splits=3)
    assert np.isfinite(mu).any() and np.all(sd[np.isfinite(sd)] >= 0)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
