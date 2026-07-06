"""Tests for the forcing-ensemble PET, dv/v coupling, and modular downscaling.

Runs standalone (`python -m tests.test_coupling`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from src.data.fetch_prism_monthly import hamon_pet_mm
from src.models.downscale import (
    _DOWNSCALERS,
    bilinear_downscale,
    downscale,
    native_scale_comparison,
    register_downscaler,
    upscale_to_grid,
)
from src.models.anchor import assimilate_points, loso_anchor_skill, residual_anchor
from src.models.dvv_coupling import coupling_envelope, forward_dvv, invert_dvv
from src.models.soil_moisture import snowmelt_liquid_input


def test_hamon_pet_positive_and_seasonal():
    times = pd.DatetimeIndex(["2015-01-01", "2015-07-01"])
    lat = np.array([47.5])
    tmean = xr.DataArray(np.array([[[2.0]], [[20.0]]]), dims=("time", "lat", "lon"))
    pet = hamon_pet_mm(tmean, times, lat)
    assert pet.shape == (2, 1, 1)
    assert np.all(pet >= 0)
    assert pet[1, 0, 0] > pet[0, 0, 0]        # July PET > January PET (warmer, longer days)


def test_residual_anchor_pulls_to_obs_and_fades():
    # one station with a +0.1 residual at the grid centre; anchor should be ~0.1 there and →0 far.
    gy, gx = np.meshgrid(np.linspace(0, 100_000, 11), np.linspace(0, 100_000, 11), indexing="ij")
    anchor, sigma = residual_anchor(gx, gy, np.array([50_000.0]), np.array([50_000.0]),
                                    np.array([0.1]), length_scale_m=10_000.0, prior_sigma=0.05)
    ci = 5  # centre index
    assert anchor[ci, ci] > 0.09                       # near the station → full correction
    assert abs(anchor[0, 0]) < 0.02                    # far corner → correction fades out
    assert sigma[ci, ci] < sigma[0, 0]                 # σ small at the station, large far away


def test_loso_anchor_reduces_bias():
    # four stations with a shared systematic model bias → LOSO anchoring should shrink |bias|.
    x = np.array([0.0, 30_000, 0.0, 30_000]); y = np.array([0.0, 0.0, 30_000, 30_000])
    model = np.array([0.15, 0.16, 0.15, 0.16]); obs = model + 0.10   # uniform +0.10 residual
    rb, rr, ab, ar = loso_anchor_skill(x, y, model, obs, length_scale_m=40_000.0)
    assert abs(ab) < abs(rb)                           # held-out bias reduced
    assert ar < rr                                     # and RMSE reduced for a uniform bias


def test_snow_module_conserves_and_redistributes():
    # One cold snowy month then warm months: precip falls in month 0, temperature rises.
    nt = 6
    precip = np.zeros((nt, 1, 1)); precip[0, 0, 0] = 100.0     # 100 mm all in a cold month
    tmean = np.array([-5, -2, 1, 4, 8, 12], dtype="float64")[:, None, None]
    days = np.full(nt, 30)
    W, swe_end = snowmelt_liquid_input(precip, tmean, days)
    # Water is conserved over the run (rain+melt total ≈ precip total, up to leftover SWE).
    assert abs(W.sum() + swe_end.sum() - precip.sum()) < 1e-6
    # Redistribution: the cold precip month yields ~no liquid input; melt appears in warm months.
    assert W[0, 0, 0] < 5.0                            # cold month → snow stored, little liquid
    assert W[2:, 0, 0].sum() > 50.0                    # melt released in the warm months


def test_dvv_forward_inverse_closed_loop():
    rng = np.random.RandomState(1)
    ny, nx = 12, 12
    sand = rng.uniform(20, 70, (ny, nx))
    clay = rng.uniform(5, 35, (ny, nx))
    wp = 0.08 + 0.001 * clay
    sat = 0.45 + 0.0005 * sand
    env = coupling_envelope(sand, clay, wp, sat)
    dtw_anom = rng.uniform(-2, 2, (ny, nx))
    theta_ref = 0.5 * (wp + sat)
    theta = np.clip(theta_ref + rng.uniform(-0.05, 0.05, (ny, nx)), wp, sat)

    dvv = forward_dvv(dtw_anom, theta, theta_ref, env)
    dtw0 = np.zeros((ny, nx))
    dtw_rec, theta_rec = invert_dvv(dvv["dvv_low"], dvv["dvv_high"], env, dtw0=dtw0, theta_ref=theta_ref)
    # water table recovered (dtw0=0 → recovered dtw equals the anomaly)
    assert np.corrcoef(dtw_rec.ravel(), dtw_anom.ravel())[0, 1] > 0.999
    # soil moisture recovered
    assert np.sqrt(np.mean((theta_rec - theta) ** 2)) < 0.01


def _grid(res, n, crs="EPSG:5070", x0=-2_000_000.0, y0=3_000_000.0):
    x = x0 + res * (np.arange(n) + 0.5)
    y = y0 - res * (np.arange(n) + 0.5)
    da = xr.DataArray(np.ones((n, n)), dims=("y", "x"), coords={"y": y, "x": x})
    return da.rio.write_crs(crs)


def test_modular_downscaler_registry():
    assert "bilinear" in _DOWNSCALERS
    fine = _grid(90.0, 40)
    coarse = _grid(900.0, 4)
    out = downscale(coarse, fine, method="bilinear")
    assert out.shape == fine.shape
    # unknown method raises
    try:
        downscale(coarse, fine, method="does-not-exist")
        raised = False
    except ValueError:
        raised = True
    assert raised
    # a newly registered method is dispatchable and receives covariates
    seen = {}

    @register_downscaler("passthrough_test")
    def _pt(c, target_like, covariates=None):
        seen["cov"] = covariates
        return bilinear_downscale(c, target_like)

    downscale(coarse, fine, method="passthrough_test", covariates={"k": 1})
    assert seen["cov"] == {"k": 1}
    del _DOWNSCALERS["passthrough_test"]


def test_twi_downscaler_adds_structure_and_falls_back():
    assert "twi" in _DOWNSCALERS
    fine = _grid(90.0, 40)
    coarse = _grid(900.0, 4).copy(data=np.random.RandomState(1).rand(4, 4)).rio.write_crs("EPSG:5070")
    twi = fine.copy(data=np.random.RandomState(2).rand(40, 40)).rio.write_crs("EPSG:5070")
    base = downscale(coarse, fine, method="bilinear")
    # no twi covariate → falls back to bilinear (identical)
    assert np.allclose(downscale(coarse, fine, method="twi").values, base.values, equal_nan=True)
    # with twi → adds fine structure (differs from bilinear)
    out = downscale(coarse, fine, method="twi", covariates={"twi": twi})
    assert not np.allclose(out.values, base.values, equal_nan=True)


def test_regression_and_ml_downscalers_are_mean_preserving():
    # a fine covariate with structure; coarse value is a function of its footprint mean.
    rng = np.random.RandomState(3)
    fine = _grid(90.0, 40).copy(data=np.ones((40, 40))).rio.write_crs("EPSG:5070")
    coarse = _grid(900.0, 4)
    cov = fine.copy(data=rng.rand(40, 40).astype("float32")).rio.write_crs("EPSG:5070")
    coarse = coarse.copy(
        data=(upscale_to_grid(cov, coarse).values * 3.0 + 1.0).astype("float32")
    ).rio.write_crs("EPSG:5070")
    for method in ("regression", "ml"):
        out = downscale(coarse, fine, method=method, covariates={"cov": cov})
        assert out.shape == fine.shape
        up = upscale_to_grid(out, coarse.rio.write_crs("EPSG:5070"))
        assert np.nanmax(np.abs(up.values - coarse.values)) < 1e-4     # exactly mean-preserving
        assert np.nanstd(out.values) > 0                                # added fine structure
    # no covariates -> falls back to bilinear (identical)
    b = downscale(coarse, fine, method="bilinear")
    assert np.allclose(downscale(coarse, fine, method="regression").values, b.values,
                       equal_nan=True)


def test_assimilate_points_precision_weighting_and_posterior_sigma():
    gy, gx = np.meshgrid(np.linspace(0, 100_000, 21), np.linspace(0, 100_000, 21), indexing="ij")
    # two co-located sources: a precise obs (+0.10, σ=0.01) and a noisy obs (−0.10, σ=0.20).
    ox = np.array([50_000.0, 50_000.0]); oy = np.array([50_000.0, 50_000.0])
    val = np.array([0.10, -0.10]); sig = np.array([0.01, 0.20])
    field, sigma = assimilate_points(gx, gy, ox, oy, val, sig,
                                     length_scale_m=15_000.0, prior_sigma=0.05)
    ci = 10  # centre
    assert field[ci, ci] > 0.08                        # precise obs dominates the fusion
    assert sigma[ci, ci] < 0.05                         # posterior σ below prior near the station
    assert abs(field[0, 0]) < 0.01                      # reverts to model far away
    assert sigma[0, 0] > sigma[ci, ci]                  # σ largest far from data


def test_upscale_and_native_scale_comparison():
    fine = _grid(90.0, 40)
    fine = fine.copy(data=np.random.RandomState(0).rand(40, 40)).rio.write_crs("EPSG:5070")
    coarse = _grid(900.0, 4)
    up = upscale_to_grid(fine, coarse)
    assert up.shape == coarse.shape            # upscaled to the coarse product grid
    stats = native_scale_comparison(fine, coarse.copy(data=np.zeros((4, 4))))
    assert set(stats) == {"n", "bias", "rmse", "corr"}
    assert stats["n"] > 0


if __name__ == "__main__":
    test_hamon_pet_positive_and_seasonal()
    test_snow_module_conserves_and_redistributes()
    test_residual_anchor_pulls_to_obs_and_fades()
    test_loso_anchor_reduces_bias()
    test_dvv_forward_inverse_closed_loop()
    test_modular_downscaler_registry()
    test_twi_downscaler_adds_structure_and_falls_back()
    test_regression_and_ml_downscalers_are_mean_preserving()
    test_assimilate_points_precision_weighting_and_posterior_sigma()
    test_upscale_and_native_scale_comparison()
    print("all coupling/ensemble/downscale tests passed")
