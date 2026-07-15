"""Tests for the 2-D coda sensitivity of the seismic network (Copilot, PR #105).

Runs standalone (`python -m tests.test_dvv_sensitivity`); also pytest-discoverable.

These pin the invariants that make the sensitivity field trustworthy as an OBSERVABILITY map: if the
kernel is not symmetric, not peaked between the stations, or does not broaden with lapse time, the
resulting "where can dv/v test the twin" map is decorative rather than physical.
"""

from __future__ import annotations

import numpy as np

from src.models.dvv_sensitivity import (
    DIFFUSIVITY_KM2_S,
    LAPSE_TIME_S,
    network_sensitivity,
    pair_kernel,
    sensitivity_to_sigma,
    single_station_kernel,
)


def _grid(half=40.0, n=81):
    a = np.linspace(-half, half, n)
    return np.meshgrid(a, a)


def test_pair_kernel_is_nonnegative_and_sum_normalised():
    x, y = _grid()
    k = pair_kernel(x, y, (-10.0, 0.0), (10.0, 0.0))
    assert k.shape == x.shape
    assert np.all(k >= 0.0)                       # a sensitivity cannot be negative
    assert abs(float(np.nansum(k)) - 1.0) < 1e-9  # discrete-sum normalised (see the docstring)
    assert np.all(np.isfinite(k))


def test_pair_kernel_is_symmetric_under_swapping_the_stations():
    # dv/v between r1 and r2 is the same measurement as between r2 and r1: the kernel must not care.
    x, y = _grid()
    s1, s2 = (-12.0, 3.0), (8.0, -5.0)
    a = pair_kernel(x, y, s1, s2)
    b = pair_kernel(x, y, s2, s1)
    assert np.allclose(a, b, atol=1e-12)


def test_sensitivity_is_concentrated_near_the_stations_not_far_away():
    # The physical content: the coda samples the medium near the receivers and along the path between
    # them. A kernel that is flat, or peaked in the wrong place, would make the observability map lie.
    x, y = _grid()
    s1, s2 = (-10.0, 0.0), (10.0, 0.0)
    k = pair_kernel(x, y, s1, s2)
    r_mid = np.hypot(x, y)                                   # midpoint of the pair
    r_far = np.hypot(x - 35.0, y - 35.0)                     # a far corner
    near_pair = k[r_mid < 12.0].mean()
    far_away = k[r_far < 12.0].mean()
    assert near_pair > 10.0 * far_away


def test_longer_lapse_time_broadens_the_kernel():
    # The coda samples further from the receivers the longer you wait. A kernel that did not broaden
    # would mean the lapse-time choice had no physical consequence.
    x, y = _grid()
    s1, s2 = (-8.0, 0.0), (8.0, 0.0)
    r = np.hypot(x, y)

    def spread(t):
        k = pair_kernel(x, y, s1, s2, t_lapse=t)
        return float((k * r).sum() / k.sum())                # mean distance from the pair centre

    assert spread(60.0) > spread(15.0)


def test_network_sensitivity_counts_pairs_and_single_stations():
    x, y = _grid()
    st = np.array([[-10.0, 0.0], [10.0, 0.0], [0.0, 12.0], [4.0, -6.0]])
    m = len(st)
    # pairs only
    _, n_pairs = network_sensitivity(x, y, st, include_single=False)
    assert n_pairs == m * (m - 1) // 2                       # 4 stations -> 6 pairs
    # default adds one single-station (autocorrelation) kernel per station
    s, n_all = network_sensitivity(x, y, st)
    assert n_all == m * (m - 1) // 2 + m                     # 6 pairs + 4 autos
    assert np.all(s >= 0.0) and np.all(np.isfinite(s))
    # a separation limit must DROP pairs, never silently keep them (single-station is unaffected)
    _, n_lim = network_sensitivity(x, y, st, max_pair_km=15.0, include_single=False)
    assert n_lim < n_pairs


def test_single_station_kernel_is_peaked_at_the_receiver():
    # An autocorrelation samples the medium AT the station, not between two -- the kernel maximum must
    # sit on the receiver, and its mass must be more localised than an inter-station kernel.
    x, y = _grid()
    s0 = (6.0, -4.0)
    k = single_station_kernel(x, y, s0)
    assert np.all(k >= 0.0)
    iy, ix = np.unravel_index(int(np.argmax(k)), k.shape)
    assert abs(x[iy, ix] - s0[0]) < 2.0 and abs(y[iy, ix] - s0[1]) < 2.0
    # more concentrated than a 20 km-separated PAIR kernel (same total weight, smaller spread)
    r_auto = np.hypot(x - s0[0], y - s0[1])
    kp = pair_kernel(x, y, (-10.0, 0.0), (10.0, 0.0))
    r_pair = np.hypot(x, y)
    assert (k * r_auto).sum() < (kp * r_pair).sum()


def test_sigma_is_infinite_where_there_is_no_sensitivity():
    # A cell the network cannot see must return NO CONSTRAINT, not a large-but-finite number that
    # invites interpolation. This is the whole point of the map.
    sens = np.array([1.0, 0.25, 0.0, 1e-12])
    sig = sensitivity_to_sigma(sens, floor=1e-6)
    assert np.isinf(sig[2]) and np.isinf(sig[3])             # zero / below-floor -> no constraint
    assert np.isfinite(sig[0]) and np.isfinite(sig[1])
    assert abs(sig[0] - 1.0) < 1e-12                         # best-observed cell normalised to 1
    assert abs(sig[1] - 2.0) < 1e-9                          # sigma ~ S^-1/2: 0.25 -> 2x worse


def test_defaults_are_physical():
    assert DIFFUSIVITY_KM2_S > 0.0 and LAPSE_TIME_S > 0.0


if __name__ == "__main__":
    test_pair_kernel_is_nonnegative_and_sum_normalised()
    test_pair_kernel_is_symmetric_under_swapping_the_stations()
    test_sensitivity_is_concentrated_near_the_stations_not_far_away()
    test_longer_lapse_time_broadens_the_kernel()
    test_network_sensitivity_counts_pairs_and_single_stations()
    test_single_station_kernel_is_peaked_at_the_receiver()
    test_sigma_is_infinite_where_there_is_no_sensitivity()
    test_defaults_are_physical()
    print("all dv/v sensitivity tests passed")
