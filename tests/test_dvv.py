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


def test_top_layer_mean_and_vs30_conversion():
    z = np.array([0.005, 0.02, 0.05, 0.5, 2.0])
    prof = np.array([0.01, 0.01, -0.02, 0.0, 0.0])          # shallow stiffening in the top 30 m
    top = dvv.top_layer_mean_dvv(prof, z, top_km=0.03)
    assert abs(top - 0.01) < 1e-9                            # mean of the two nodes <= 30 m
    frac, std = dvv.dvv_to_vs30_change(np.array([0.01]), np.array([0.002]))
    assert frac[0] > 0 and std[0] > 0                        # positive dVs/Vs -> higher Vs30
    # Vs30(t) = baseline*(1+frac): a +1% velocity change is a +1% Vs30 change
    assert abs((400.0 * (1 + frac[0])) - 404.0) < 1e-6


def test_register_inter_is_safe():
    from src.viz.fonts import register_inter
    fam = register_inter()                                   # bundled Inter present -> "Inter"
    assert isinstance(fam, str) and len(fam) > 0


def test_synthetic_depth_time_low_slow_high_fast():
    if not _codameter_available():
        print("skip: codameter/disba not installed")
        return
    from codameter.uq_depth import band_sensitivity_matrix
    prof = dvv.pnw_velocity_profile(400.0)
    fc = np.sqrt(np.asarray(dvv.DEFAULT_BANDS)[:, 0] * np.asarray(dvv.DEFAULT_BANDS)[:, 1])
    K = band_sensitivity_matrix(prof, fc)
    m, t = dvv.synthetic_depth_time_truth(K.depths_km, n_epoch=73, dt_days=5.0)
    assert m.shape == (K.depths_km.size, 73)
    dvv_bt = dvv.forward_banded_dvv(m, K)
    assert dvv_bt.shape == (len(fc), 73)
    assert np.allclose(dvv_bt, K.G @ m)                       # forward == G @ m
    # deep band (slow GWL) is smoother than the shallow band (fast ET/storms)
    rough = np.var(np.diff(dvv_bt, axis=1), axis=1)
    assert rough[0] < rough[-1]
    # per-band recovery through the NCF synthesis
    lags, ref, series = dvv.synthesize_banded_ncfs(dvv_bt)
    banded = dvv.measure_banded_dvv(series, ref, lags, 25.0, coda_s=(5.0, 30.0), times=t)
    for bi in (0, len(fc) - 1):
        rec = banded.dvv[:, bi]; g = np.isfinite(rec)
        assert np.corrcoef(rec[g], dvv_bt[bi][g])[0, 1] > 0.9


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
    test_top_layer_mean_and_vs30_conversion()
    test_register_inter_is_safe()
    test_synthetic_depth_time_low_slow_high_fast()
    test_processing_ensemble_covariance_exceeds_weaver_floor()
    test_depth_separation_orders_and_splits_at_water_table()
    print("all dv/v tests passed")
