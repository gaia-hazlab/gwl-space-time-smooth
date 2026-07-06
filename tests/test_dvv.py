"""Tests for the dv/v module: correlation layer + codameter measurement/depth wiring.

Runs standalone (`python -m tests.test_dvv`); also pytest-discoverable. The codameter-dependent
tests skip cleanly if codameter (or its disba kernels) is not installed, so the correlation
layer is always exercised.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from src.models import dvv


def _synthetic(n_epoch=24, sr=25.0, maxlag=60.0, noise=0.15, seed=0):
    """Reference coda NCF + a daily NCF series with a known imposed dv/v(t)."""
    rng = np.random.RandomState(seed)
    lags = np.arange(-int(maxlag * sr), int(maxlag * sr) + 1) / sr
    env = np.exp(-np.abs(lags) / 20.0)
    sos = signal.butter(4, [0.1, 8.0], btype="band", fs=sr, output="sos")
    ref = signal.sosfiltfilt(sos, rng.randn(lags.size)) * env
    t_days = np.arange(n_epoch, dtype=float)
    dvv_true = 0.003 * np.sin(2 * np.pi * t_days / 12.0)
    series = np.array([np.interp(lags, lags * (1 + e), ref) for e in dvv_true])
    series = series + noise * np.array(
        [signal.sosfiltfilt(sos, rng.randn(lags.size)) * env for _ in range(n_epoch)])
    return lags, ref, series, dvv_true, t_days, sr


def test_peak_depth_relation():
    # L = Vs/(3f): higher frequency -> shallower; 2 Hz ~ 250 m for Vs=1500 m/s.
    z = dvv.peak_depth_km([0.5, 2.0], vs_ms=1500.0)
    assert z[0] > z[1]
    assert abs(z[1] - 0.25) < 0.01


def test_cross_correlate_shapes_and_symmetry():
    sr = 25.0
    rng = np.random.RandomState(1)
    a = dvv.preprocess(rng.randn(int(300 * sr)), sr)
    b = dvv.preprocess(rng.randn(int(300 * sr)), sr)
    lags, ccf = dvv.cross_correlate(a, b, sr, maxlag_s=30.0)
    assert ccf.shape == lags.shape
    assert lags[0] == -lags[-1]                       # symmetric lag axis
    assert np.max(np.abs(ccf)) <= 1.0 + 1e-9          # normalized


def test_stretching_recovers_known_dvv():
    lags, ref, series, dvv_true, t_days, sr = _synthetic()
    banded = dvv.measure_banded_dvv(series, ref, lags, sr, coda_s=(5.0, 30.0), times=t_days)
    bi = 2                                             # 1-2 Hz band
    rec = banded.dvv[:, bi]
    good = np.isfinite(rec)
    r = np.corrcoef(rec[good], dvv_true[good])[0, 1]
    rmse = np.sqrt(np.nanmean((rec - dvv_true) ** 2))
    assert r > 0.95 and rmse < 5e-4


def test_dvv_to_state_conversions_and_signs():
    # deep band: dv/v = k_sat * ΔWTD  ->  a positive dv/v means a deeper table (head drop)
    wtd, wtd_sd = dvv.dvv_to_wtd_change(np.array([5e-4]), np.array([1e-4]))
    assert abs(wtd[0] - 1.0) < 1e-6                    # 5e-4 dv/v -> +1 m with k_sat=5e-4
    assert wtd_sd[0] > 0
    # shallow band: wetting softens (dv/v < 0) -> positive Δθ
    dth, dth_sd = dvv.dvv_to_theta_change(np.array([-0.02]), np.array([0.004]))
    assert dth[0] > 0 and dth_sd[0] > 0


def _codameter_available():
    try:
        import codameter  # noqa: F401
        from codameter.kernels import disba_wrapper  # noqa: F401
        import disba  # noqa: F401
        return True
    except Exception:
        return False


def test_processing_ensemble_covariance_exceeds_weaver_floor():
    if not _codameter_available():
        print("skip: codameter/disba not installed")
        return
    lags, ref, series, dvv_true, t_days, sr = _synthetic()
    ens = dvv.processing_ensemble_dvv(series, lags, sr, times_days=t_days)
    fc = sorted(ens)[2]
    E = ens[fc]["ensemble"]
    # total variance includes methodological spread on top of the Weaver within-method floor
    assert (E.total_std >= E.within_std - 1e-12).all()
    assert np.median(E.methodological_std) > 0
    Cd = ens[fc]["Cd"]
    assert Cd.shape == (len(t_days), len(t_days)) and np.allclose(Cd, Cd.T)


def test_depth_separation_orders_and_splits_at_water_table():
    if not _codameter_available():
        print("skip: codameter/disba not installed")
        return
    lags, ref, series, dvv_true, t_days, sr = _synthetic()
    ens = dvv.processing_ensemble_dvv(series, lags, sr, times_days=t_days)
    prof = dvv.pnw_velocity_profile(vs30_ms=400.0)
    post, part = dvv.separate_depth(ens, prof, water_table_depth_km=0.03, epoch=6)
    pk = part["peak_depths_km"]
    assert (np.diff(pk) <= 1e-9).all()                # peak depth decreases with frequency
    assert np.isfinite(part["soil_moisture_dvv"]) and np.isfinite(part["wtd_relative_dvv"])
    assert part["soil_moisture_dvv_std"] > 0 and part["wtd_relative_dvv_std"] > 0
    assert post.mean.shape == post.std.shape == part["depths_km"].shape


if __name__ == "__main__":
    test_peak_depth_relation()
    test_cross_correlate_shapes_and_symmetry()
    test_stretching_recovers_known_dvv()
    test_dvv_to_state_conversions_and_signs()
    test_processing_ensemble_covariance_exceeds_weaver_floor()
    test_depth_separation_orders_and_splits_at_water_table()
    print("all dv/v tests passed")
