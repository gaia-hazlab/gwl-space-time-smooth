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
from src.models.dvv_coupling import coupling_envelope, forward_dvv, invert_dvv


def test_hamon_pet_positive_and_seasonal():
    times = pd.DatetimeIndex(["2015-01-01", "2015-07-01"])
    lat = np.array([47.5])
    tmean = xr.DataArray(np.array([[[2.0]], [[20.0]]]), dims=("time", "lat", "lon"))
    pet = hamon_pet_mm(tmean, times, lat)
    assert pet.shape == (2, 1, 1)
    assert np.all(pet >= 0)
    assert pet[1, 0, 0] > pet[0, 0, 0]        # July PET > January PET (warmer, longer days)


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
    test_dvv_forward_inverse_closed_loop()
    test_modular_downscaler_registry()
    test_upscale_and_native_scale_comparison()
    print("all coupling/ensemble/downscale tests passed")
