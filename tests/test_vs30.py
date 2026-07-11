"""Tests for the Wald-Allen Vs30 slope proxy (issue #54).

Runs standalone (`python -m tests.test_vs30`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.data.fetch_vs30 import (
    NEHRP_CLASSES,
    fetch_svm_vs30,
    most_likely_nehrp_class,
    nehrp_class_probabilities,
    vs30_from_vs_profile,
    wald_allen_vs30,
)


def test_svm_vs30_from_profile_is_the_travel_time_average():
    z = np.array([0.0, 10.0, 20.0, 30.0, 50.0])
    # a uniform 300 m/s column to 30 m must give Vs30 = 300 exactly
    uniform = np.array([300.0, 300.0, 300.0, 300.0, 600.0])
    assert abs(float(vs30_from_vs_profile(uniform, z)) - 300.0) < 1e-6
    # a slower cap (soft soil over stiff) must lower Vs30 below the deep value
    soft = np.array([180.0, 180.0, 600.0, 600.0, 900.0])
    v = float(vs30_from_vs_profile(soft, z))
    assert 180.0 < v < 600.0                                 # travel-time average, not arithmetic mean
    # broadcasts over a (depth, y, x) cube
    cube = np.tile(uniform[:, None, None], (1, 3, 2))
    assert vs30_from_vs_profile(cube, z).shape == (3, 2)


def test_vs30_integrates_to_exactly_top_m_with_partial_layer():
    # Real SVM depth grids need not land on 30 m. The integral must run to *exactly* top_m via a
    # partial (interpolated) top layer, not stop at the deepest sample <= 30 m.
    # uniform column, grid skipping 30 m (nodes 0/10/20/40): still exactly 300
    z_skip = np.array([0.0, 10.0, 20.0, 40.0])
    assert abs(float(vs30_from_vs_profile(np.full(4, 300.0), z_skip)) - 300.0) < 1e-6
    # partial layer that actually matters: nodes 0/15/45, Vs 200 then ramp to 800.
    # v(30) interpolates to 500; travel = 15/200 + 15/logmean(200,500), logmean=(500-200)/ln(2.5).
    z = np.array([0.0, 15.0, 45.0]); vs = np.array([200.0, 200.0, 800.0])
    v_lm = (500.0 - 200.0) / np.log(2.5)
    expected = 30.0 / (15.0 / 200.0 + 15.0 / v_lm)
    assert abs(float(vs30_from_vs_profile(vs, z)) - expected) < 1e-6
    # and it is NOT the (wrong) average over just the top 15 m sample (=200)
    assert float(vs30_from_vs_profile(vs, z)) > 200.0
    # a profile shallower than top_m flat-extrapolates the deepest velocity rather than erroring
    assert abs(float(vs30_from_vs_profile(np.array([250.0, 250.0]), np.array([0.0, 12.0]))) - 250.0) < 1e-6


def test_svm_source_is_graceful_when_not_staged():
    # with no staged SVM raster/netCDF, the preferred SVM source returns None (caller falls back)
    assert fetch_svm_vs30(svm_vs30_tif="does/not/exist.tif", svm_nc=None) is None


def test_monotone_and_nehrp_range():
    slopes = np.array([0.0, 1.0, 3.0, 8.0, 20.0])
    vs = wald_allen_vs30(slopes)
    assert np.all(np.diff(vs) >= 0)                 # steeper terrain -> stiffer (non-decreasing)
    assert vs[0] == 180.0                            # flat valley fill -> NEHRP E
    assert vs[-1] == 760.0                           # steep -> NEHRP B/C boundary
    assert np.all((vs >= 180.0) & (vs <= 760.0))     # spans the standard NEHRP Vs30 range


def test_bins_map_to_expected_classes():
    # a gentle 1 deg slope (gradient ~0.017) sits in the 300-360 range, not 180 and not 760
    v = float(wald_allen_vs30(np.array([1.0]))[0])
    assert 240.0 <= v <= 360.0


def test_nan_slope_gives_nan():
    vs = wald_allen_vs30(np.array([np.nan, 5.0]))
    assert np.isnan(vs[0]) and np.isfinite(vs[1])


def test_nehrp_probs_are_a_distribution_centered_on_the_class():
    # 300 m/s with a tight sigma is almost surely NEHRP D (180-360); probs sum to 1
    p = nehrp_class_probabilities(300.0, 20.0)
    assert p.shape == (5,)
    assert abs(p.sum() - 1.0) < 1e-9
    assert NEHRP_CLASSES[int(p.argmax())] == "D"
    assert p[1] > 0.98                                   # index 1 == class D
    cls, prob = most_likely_nehrp_class(300.0, 20.0)
    assert cls == "D" and prob > 0.98


def test_nehrp_boundary_splits_mass_across_two_classes():
    # sitting exactly on the D|C boundary (360) splits ~50/50 between D and C, little elsewhere
    p = nehrp_class_probabilities(360.0, 15.0)
    assert abs(p[1] - 0.5) < 0.05 and abs(p[2] - 0.5) < 0.05  # D and C
    assert p[0] + p[3] + p[4] < 0.02                     # negligible E, B, A


def test_nehrp_wider_sigma_spreads_probability():
    tight = nehrp_class_probabilities(300.0, 10.0)
    wide = nehrp_class_probabilities(300.0, 120.0)
    # the modal (D) probability drops and mass leaks into neighbours as sigma grows
    assert wide[1] < tight[1]
    assert wide[2] > tight[2]                            # more chance of crossing up into C


def test_nehrp_array_broadcasts_per_cell():
    field = np.array([[190.0, 400.0], [800.0, 250.0]])
    p = nehrp_class_probabilities(field, 30.0)
    assert p.shape == (2, 2, 5)
    assert np.allclose(p.sum(axis=-1), 1.0)


def test_nehrp_lognormal_option_runs_and_normalizes():
    p = nehrp_class_probabilities(300.0, 0.2, lognormal=True)   # sigma of ln(Vs30)
    assert abs(p.sum() - 1.0) < 1e-9 and NEHRP_CLASSES[int(p.argmax())] == "D"


def test_nehrp_zero_sigma_is_one_hot_even_on_a_boundary():
    # zero sigma -> deterministic class, no NaN (0/0) even exactly on a boundary
    p = nehrp_class_probabilities(300.0, 0.0)
    assert np.array_equal(p, [0, 1, 0, 0, 0])                # class D, one-hot
    pb = nehrp_class_probabilities(360.0, 0.0)               # exactly on the D|C boundary
    assert np.all(np.isfinite(pb)) and abs(pb.sum() - 1.0) < 1e-9
    # digitize puts the boundary value in the upper bin (C)
    assert NEHRP_CLASSES[int(pb.argmax())] == "C"
    # mixed field: zero-sigma cell stays one-hot, finite-sigma cell stays a distribution
    field = nehrp_class_probabilities(np.array([300.0, 300.0]), np.array([0.0, 60.0]))
    assert np.array_equal(field[0], [0, 1, 0, 0, 0]) and 0.0 < field[1, 1] < 1.0


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def test_nehrp_rejects_negative_sigma_and_nonpositive_lognormal_mean():
    assert _raises(lambda: nehrp_class_probabilities(300.0, -10.0))
    assert _raises(lambda: nehrp_class_probabilities(0.0, 0.2, lognormal=True))


if __name__ == "__main__":
    test_svm_vs30_from_profile_is_the_travel_time_average()
    test_vs30_integrates_to_exactly_top_m_with_partial_layer()
    test_svm_source_is_graceful_when_not_staged()
    test_monotone_and_nehrp_range()
    test_bins_map_to_expected_classes()
    test_nan_slope_gives_nan()
    test_nehrp_probs_are_a_distribution_centered_on_the_class()
    test_nehrp_boundary_splits_mass_across_two_classes()
    test_nehrp_wider_sigma_spreads_probability()
    test_nehrp_array_broadcasts_per_cell()
    test_nehrp_lognormal_option_runs_and_normalizes()
    test_nehrp_zero_sigma_is_one_hot_even_on_a_boundary()
    test_nehrp_rejects_negative_sigma_and_nonpositive_lognormal_mean()
    print("all Vs30 tests passed")
