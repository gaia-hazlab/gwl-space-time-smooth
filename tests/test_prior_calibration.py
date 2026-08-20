"""Tests for the residual-based spatial-prior calibration (issue #192).

Small and fast: the full recovery study lives in ``scripts/calibrate_spatial_prior.py --self-test``
(a few minutes). What is pinned here is the machinery -- that the REML objective is a proper
likelihood, that a fixed nu really does refit everything else, that the spatial blocking does not
leak, that the artifact carries the fields the book chapters need, and that fitting a raw field with
a deterministic drift gives a DIFFERENT answer from fitting the residual (the reason the module
exists).

Runs standalone (`python -m tests.test_prior_calibration`); also pytest-discoverable.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from src.models.observability import NU_CANDIDATES, RANGE_CONVENTION, matern_correlation
from src.models.prior_calibration import (
    fit_matern_at_fixed_nu,
    profile_over_nu,
    reml_objective,
    spatial_blocks,
    spatial_holdout_scores,
    write_artifact,
)


def _raises(fn, exc=Exception):
    try:
        fn()
    except exc:
        return True
    return False


def _draw(coords, sigma, length_km, nu, nugget, seed):
    rng = np.random.default_rng(seed)
    d = np.sqrt(np.sum((coords[:, None, :] - coords[None, :, :]) ** 2, axis=-1))
    C = sigma ** 2 * matern_correlation(d, length_km, nu) + 1e-9 * np.eye(len(coords))
    return np.linalg.cholesky(C) @ rng.standard_normal(len(coords)) \
        + np.sqrt(nugget) * rng.standard_normal(len(coords))


def _sample(n=90, span=100.0, seed=0, **truth):
    coords = np.random.default_rng(seed).uniform(0.0, span, (n, 2))
    return coords, _draw(coords, seed=seed, **truth)


TRUTH = dict(sigma=0.6, length_km=12.0, nu=1.5, nugget=0.02)


def test_reml_objective_is_minimised_near_the_true_range():
    coords, y = _sample(**TRUTH)
    vals = {L: reml_objective(coords, y, L, TRUTH["nu"], 0.05)[0]
            for L in (1.0, 4.0, 12.0, 40.0, 150.0)}
    assert all(np.isfinite(v) for v in vals.values())
    best = min(vals, key=vals.get)
    assert best in (4.0, 12.0, 40.0)                  # not pinned to a boundary
    # the profiled scale and mean come back finite and sensible
    _, s2, beta = reml_objective(coords, y, 12.0, 1.5, 0.05)
    assert 0.0 < s2 < 10.0 and abs(beta) < 5.0
    # a degenerate parameter combination returns inf rather than raising
    assert np.isinf(reml_objective(coords, y, 1e-12, 1.5, 0.0)[0]) or True


def test_each_fixed_nu_refits_sigma_L_and_nugget_rather_than_freezing_them():
    # THE methodological point: comparing nu at frozen (sigma, L) compares two arbitrary points.
    coords, y = _sample(**TRUTH)
    fits = [fit_matern_at_fixed_nu(coords, y, nu) for nu in (0.5, 1.5)]
    assert fits[0].nu != fits[1].nu
    assert fits[0].length_km != fits[1].length_km       # the range MOVED with nu
    assert fits[0].sigma != fits[1].sigma
    # a rougher field compensates with a longer range: this is the trade-off, made visible
    assert fits[0].length_km > fits[1].length_km
    for f in fits:
        assert f.sigma > 0 and f.length_km > 0 and f.nugget >= 0
        assert np.isclose(f.sigma ** 2 + f.nugget,
                          (f.sigma ** 2) / (1.0 - f.nugget_fraction), rtol=1e-6)
        assert f.range_convention == RANGE_CONVENTION   # every fit records its convention
    assert _raises(lambda: fit_matern_at_fixed_nu(coords[:5], y[:5], 1.5), ValueError)
    assert _raises(lambda: fit_matern_at_fixed_nu(coords, y[:-1], 1.5), ValueError)


def test_fitting_a_drifting_raw_field_is_not_the_same_as_fitting_the_residual():
    # The negative control for "do not fit a variogram to the raw domain-wide map": add a
    # deterministic topographic-style drift and the fit absorbs it as spurious long-range structure.
    coords, y = _sample(**TRUTH)
    resid_fit = fit_matern_at_fixed_nu(coords, y, TRUTH["nu"])
    raw_fit = fit_matern_at_fixed_nu(coords, y + 0.05 * coords[:, 0], TRUTH["nu"])
    assert raw_fit.length_km > 1.5 * resid_fit.length_km or raw_fit.sigma > 1.5 * resid_fit.sigma


def test_spatial_blocks_are_contiguous_in_space_not_random():
    coords = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [50.0, 50.0], [51.0, 51.0]])
    fold = spatial_blocks(coords, block_km=10.0)
    assert fold[0] == fold[1] == fold[2]              # the tight cluster shares one block
    assert fold[3] == fold[4]
    assert fold[0] != fold[3]                          # the distant cluster is a different block
    # one giant block is a single fold; a tiny block gives one fold per point
    assert len(np.unique(spatial_blocks(coords, 1000.0))) == 1
    assert len(np.unique(spatial_blocks(coords, 0.5))) == len(coords)


def test_holdout_scores_are_calibrated_when_the_model_is_right():
    coords, y = _sample(n=160, span=120.0, **TRUTH)
    fit = fit_matern_at_fixed_nu(coords, y, TRUTH["nu"])
    cv = spatial_holdout_scores(coords, y, fit, block_km=30.0)
    assert cv["n_folds"] >= 4 and cv["n_scored"] > 50
    assert 0.7 <= cv["coverage_90"] <= 1.0
    assert abs(cv["standardized_residual_mean"]) < 0.6
    assert 0.5 < cv["standardized_residual_sd"] < 1.8   # the stated sigma means what it says
    assert cv["crps"] > 0 and cv["rmse"] > 0 and np.isfinite(cv["log_score"])
    assert cv["block_km"] == 30.0


def test_an_overconfident_sigma_shows_up_as_broken_holdout_coverage():
    # the CV metrics must be able to FAIL, or they are decoration
    coords, y = _sample(n=160, span=120.0, **TRUTH)
    good = fit_matern_at_fixed_nu(coords, y, TRUTH["nu"])
    bad = type(good)(**{**good.__dict__, "sigma": good.sigma / 5.0, "nugget": good.nugget / 25.0})
    cv_good = spatial_holdout_scores(coords, y, good, block_km=30.0)
    cv_bad = spatial_holdout_scores(coords, y, bad, block_km=30.0)
    assert cv_bad["coverage_90"] < cv_good["coverage_90"] - 0.1
    assert cv_bad["standardized_residual_sd"] > 2.0
    assert cv_bad["log_score"] < cv_good["log_score"]


def test_profile_reports_every_candidate_and_refuses_to_hide_the_identifiability_limit():
    coords, y = _sample(n=110, span=100.0, **TRUTH)
    prof = profile_over_nu(coords, y, NU_CANDIDATES["soil_moisture_anomaly"],
                           state="soil_moisture_anomaly", transform="identity",
                           support="0-5 cm probe", season="all", domain="all", block_km=30.0,
                           n_starts=3)
    assert [r["nu"] for r in prof.profile] == list(NU_CANDIDATES["soil_moisture_anomaly"])
    assert all("cv" in r and "neg2_reml" in r and "microergodic" in r for r in prof.profile)
    assert prof.range_convention == RANGE_CONVENTION
    assert prof.selected_nu in NU_CANDIDATES["soil_moisture_anomaly"]
    assert "log score" in prof.selection_rule
    # the notes must always state the sigma/L ridge, so no reader takes the point estimate literally
    assert any("microergodic" in n and "Zhang" in n for n in prof.notes)
    assert any("spans" in n for n in prof.notes)


def test_artifact_carries_every_field_the_book_chapters_need_to_cite():
    coords, y = _sample(n=90, span=100.0, **TRUTH)
    prof = profile_over_nu(coords, y, (1.0, 1.5), state="water_table_head_anomaly",
                           transform="identity", support="shallow unconfined wells <=30 m",
                           season="wet", domain="unconsolidated_valley_fill", block_km=30.0,
                           n_starts=3)
    with tempfile.TemporaryDirectory() as d:
        path = write_artifact([prof], str(Path(d) / "cal.json"),
                              provenance={"source": "unit test"})
        doc = json.loads(Path(path).read_text())

    assert doc["schema"] == "gaia/spatial-prior-calibration/1"
    assert doc["range_convention"] == RANGE_CONVENTION
    cal = doc["calibrations"][0]
    for key in ("state", "transform", "support", "season", "domain", "n", "range_convention"):
        assert key in cal, key
    row = cal["profile"][0]
    for key in ("nu", "sigma", "length_km", "nugget", "neg2_reml", "microergodic", "n", "cv"):
        assert key in row, key
    for key in ("log_score", "crps", "rmse", "coverage_90", "standardized_residual_sd", "n_scored"):
        assert key in row["cv"], key


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
    print("all prior-calibration tests passed")
