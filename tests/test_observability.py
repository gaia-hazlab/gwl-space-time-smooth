"""Tests for the linear-Gaussian observability / information-gain core (issue: sensor design).

Runs standalone (`python -m tests.test_observability`); also pytest-discoverable.

These pin the invariants that make the resolution and information maps trustworthy: a resolution
outside [0,1], or one that a sensor could DECREASE by adding data, would make the "where is each sensor
worth its cost" map meaningless.
"""

from __future__ import annotations

import numpy as np

from src.models.observability import (
    GaussianPrior,
    information_gain,
    marginal_resolution,
    normalise_footprint,
    point_footprint,
    resolution,
)


def _grid(n=16, span=20.0):
    a = np.linspace(0, span, n)
    xx, yy = np.meshgrid(a, a)
    return np.column_stack([xx.ravel(), yy.ravel()])


def test_footprints_sum_to_one():
    c = _grid()
    assert abs(point_footprint(c, (10.0, 10.0)).sum() - 1.0) < 1e-9
    raw = np.random.default_rng(0).random(len(c))
    assert abs(normalise_footprint(raw).sum() - 1.0) < 1e-9


def test_resolution_is_a_fraction_in_the_unit_interval():
    c = _grid()
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    G = np.vstack([point_footprint(c, loc) for loc in [(5, 5), (15, 15), (5, 15)]])
    res, vpost = resolution(C, G, noise_var=0.01)
    assert res.shape == (len(c),)
    assert np.all(res >= -1e-9) and np.all(res <= 1.0 + 1e-9)
    assert np.all(vpost >= -1e-9) and np.all(vpost <= np.diag(C) + 1e-9)


def test_resolution_is_highest_at_the_sensor_and_decays_away():
    c = _grid()
    C = GaussianPrior(sigma=1.0, length_km=3.0).cov(c)
    loc = (10.0, 10.0)
    res, _ = resolution(C, point_footprint(c, loc)[None, :], noise_var=1e-3)
    d = np.hypot(c[:, 0] - loc[0], c[:, 1] - loc[1])
    near = res[d < 2.0].mean()
    far = res[d > 12.0].mean()
    assert near > far                                    # a sensor informs its own neighbourhood most


def test_lower_noise_gives_more_resolution():
    c = _grid()
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    g = point_footprint(c, (10.0, 10.0))[None, :]
    precise, _ = resolution(C, g, noise_var=1e-3)
    noisy, _ = resolution(C, g, noise_var=1.0)
    assert precise.max() > noisy.max()                   # a better instrument resolves more


def test_more_sensors_never_reduce_resolution_and_no_sensors_is_zero():
    c = _grid()
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    base = np.vstack([point_footprint(c, (5, 5)), point_footprint(c, (15, 15))])
    res_base, _ = resolution(C, base, 0.05)
    both = np.vstack([base, point_footprint(c, (10, 10))])
    res_both, _ = resolution(C, both, 0.05)
    assert np.all(res_both >= res_base - 1e-9)           # adding data cannot lose resolution
    # empty observation set -> nothing is resolved
    res_none, vpost = resolution(C, np.empty((0, len(c))), 0.05)
    assert np.allclose(res_none, 0.0)
    assert np.allclose(vpost, np.diag(C))


def test_marginal_gain_is_where_the_added_sensor_reaches_beyond_the_base():
    # A dv/v-like footprint away from the base point sensors must show POSITIVE marginal gain there,
    # and ~zero where the base already resolves the field. This is the "worth its cost" invariant.
    c = _grid(n=20, span=30.0)
    C = GaussianPrior(sigma=1.0, length_km=3.0).cov(c)
    base = point_footprint(c, (5.0, 5.0))[None, :]                  # one well in a corner
    added = point_footprint(c, (25.0, 25.0), width_km=3.0)[None, :] # a sensor in the far corner
    mg = marginal_resolution(C, added, base, noise_added=0.05, noise_base=0.05)
    assert np.all(mg >= -1e-9)
    far = np.hypot(c[:, 0] - 25, c[:, 1] - 25) < 4
    near_base = np.hypot(c[:, 0] - 5, c[:, 1] - 5) < 4
    assert mg[far].mean() > mg[near_base].mean()         # it adds most where the base cannot reach


def test_information_gain_is_monotone_in_variance_reduction():
    vp = np.array([1.0, 1.0, 1.0])
    vq = np.array([1.0, 0.5, 0.1])                        # increasing reduction
    ig = information_gain(vp, vq)
    assert ig[0] < ig[1] < ig[2] and ig[0] == 0.0


if __name__ == "__main__":
    test_footprints_sum_to_one()
    test_resolution_is_a_fraction_in_the_unit_interval()
    test_resolution_is_highest_at_the_sensor_and_decays_away()
    test_lower_noise_gives_more_resolution()
    test_more_sensors_never_reduce_resolution_and_no_sensors_is_zero()
    test_marginal_gain_is_where_the_added_sensor_reaches_beyond_the_base()
    test_information_gain_is_monotone_in_variance_reduction()
    print("all observability tests passed")
