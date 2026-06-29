"""Tests for per-domain validation gates and variogram-sized CV (issue #3).

Runs standalone (`python -m tests.test_domain_gates`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.evaluation.domain_gates import (
    DEFAULT_BLOCK_M,
    DOMAIN_GATES,
    MAX_BLOCK_M,
    MIN_BLOCK_M,
    _evaluate_gate,
    estimate_variogram_range,
    per_domain_cv,
)
from src.features.hydrogeologic_domains import DOMAINS


def test_gates_cover_every_domain():
    assert set(DOMAIN_GATES) == set(DOMAINS.values())


def test_variogram_range_clamped_and_reasonable():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 30_000, (200, 2))           # 30 km extent
    # spatially smooth field → finite autocorrelation range
    vals = np.sin(xy[:, 0] / 5_000) + 0.1 * rng.standard_normal(200)
    r = estimate_variogram_range(xy, vals)
    assert MIN_BLOCK_M <= r <= MAX_BLOCK_M


def test_variogram_range_fallback_few_points():
    assert estimate_variogram_range(np.zeros((3, 2)), np.zeros(3)) == DEFAULT_BLOCK_M


def test_evaluate_gate_pass_and_fail():
    p = _evaluate_gate("unconsolidated_valley_fill", {"rmse": 0.6, "bias": 0.1})
    assert p["status"] == "pass" and p["meets_target"]
    f = _evaluate_gate("unconsolidated_valley_fill", {"rmse": 2.0, "bias": 0.1})
    assert f["status"] == "FAIL"
    # bias alone can fail the gate
    fb = _evaluate_gate("coastal", {"rmse": 0.5, "bias": 0.9})
    assert fb["status"] == "FAIL"
    assert _evaluate_gate("fractured_upland", {})["status"] == "report_only"


def test_per_domain_cv_structure():
    from sklearn.linear_model import LinearRegression

    rng = np.random.default_rng(1)
    code = {v: k for k, v in DOMAINS.items()}
    parts = []
    # gate domain with enough wells; a sparse domain; a masked domain
    for name, n in [("unconsolidated_valley_fill", 80), ("fractured_upland", 5),
                    ("confined_basalt", 40)]:
        xy = rng.uniform(0, 40_000, (n, 2))
        # short-range spatial structure so the variogram range << domain extent
        y = 1.0 + np.sin(xy[:, 0] / 4_000) + 0.2 * rng.standard_normal(n)
        X = np.column_stack([xy[:, 0], xy[:, 1], y + rng.standard_normal(n)])
        parts.append((np.full(n, code[name]), X, y, xy))
    codes = np.concatenate([p[0] for p in parts])
    X = np.vstack([p[1] for p in parts])
    y = np.concatenate([p[2] for p in parts])
    xy = np.vstack([p[3] for p in parts])

    rep = per_domain_cv(LinearRegression(), X, y, xy, codes, n_splits=3)
    # masked domain: scored only by count, no gate
    assert rep["confined_basalt"]["mode"] == "masked" and "gate" not in rep["confined_basalt"]
    # sparse domain: too few wells -> note, no CV metrics
    assert "note" in rep["fractured_upland"] and "rmse" not in rep["fractured_upland"]
    # gate domain: has CV metrics + a gate verdict + a data-derived block size
    vf = rep["unconsolidated_valley_fill"]
    assert "rmse" in vf and vf["gate"]["status"] in {"pass", "FAIL"}
    assert MIN_BLOCK_M / 1000 <= vf["block_km"] <= MAX_BLOCK_M / 1000


def test_unvalidatable_gate_domain_does_not_pass():
    # A gate-mode domain with too few wells must be flagged 'unvalidated', and
    # write_report must NOT report all_gates_pass.
    import json, pathlib, tempfile
    from sklearn.linear_model import LinearRegression
    from src.evaluation.domain_gates import per_domain_cv, write_report
    code = {v: k for k, v in DOMAINS.items()}
    n = 5                                            # < MIN_WELLS_FOR_CV
    rng = np.random.default_rng(2)
    xy = rng.uniform(0, 10_000, (n, 2))
    y = rng.standard_normal(n)
    X = np.column_stack([xy[:, 0], xy[:, 1]])
    codes = np.full(n, code["unconsolidated_valley_fill"])
    rep = per_domain_cv(LinearRegression(), X, y, xy, codes, n_splits=3)
    assert rep["unconsolidated_valley_fill"]["gate"]["status"] == "unvalidated"
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "block_cv_metrics.json"
        ok = write_report(rep, out)
        payload = json.loads(out.read_text())
    assert ok is False and "unconsolidated_valley_fill" in payload["failed_domains"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
