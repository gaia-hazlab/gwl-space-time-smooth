"""Tests for the 2-D coda sensitivity of the seismic network (Copilot, PR #105).

Runs standalone (`python -m tests.test_dvv_sensitivity`); also pytest-discoverable.

These pin the invariants that make the sensitivity field trustworthy as an OBSERVABILITY map: if the
kernel is not symmetric, not peaked between the stations, or does not broaden with lapse time, the
resulting "where can dv/v test the twin" map is decorative rather than physical.

The second half of the file pins something different and stricter: BIT-LEVEL EQUIVALENCE of the
vectorised lapse-time quadrature in ``pair_kernel`` against the original Python-loop implementation
it replaced. A performance rewrite is only legitimate if it is behaviour-preserving, and the
physics invariants above are far too forgiving to prove that -- a subtly wrong quadrature still
produces a smooth, non-negative, correctly-shaped kernel.
"""

from __future__ import annotations

import numpy as np

from src.models.dvv_sensitivity import (
    DIFFUSIVITY_KM2_S,
    LAPSE_TIME_S,
    _intensity_2d,
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


# ---------------------------------------------------------------------------------------------
# Regression guard for the vectorised lapse-time quadrature (issue #159, m3)
#
# `pair_kernel` used to evaluate the Pacheco-Snieder time convolution with a Python loop over the
# n_quad midpoint nodes, accumulating into a grid-shaped array. It now broadcasts over a node axis
# and walks the flattened grid in blocks sized to cap the (n_quad, n_cell) temporary. That is a
# PURE PERFORMANCE REWRITE: the quadrature rule, the node positions, the weights, the denominator
# guard and the sum normalisation are all supposed to be unchanged.
#
# "Supposed to be" is why these tests exist. A vectorisation like this can silently change the
# science in ways no physics-invariant test above would catch: an off-by-one in the node offset
# (0.5 -> 0.0 turns midpoint into left-rectangle rule), a node axis that broadcasts against the
# wrong grid axis, a block boundary that drops or double-counts cells, or a normalisation that
# ends up per-block instead of over the whole grid. Every one of those still yields a smooth,
# non-negative, symmetric, correctly-broadening kernel -- it just yields the WRONG one.
#
# So the invariant pinned here is EQUIVALENCE, not plausibility: the shipped function must return
# what the original loop returned, to the last few bits, on the cases that exercise every branch.
# ---------------------------------------------------------------------------------------------

# Copied VERBATIM from `git show HEAD:src/models/dvv_sensitivity.py` (the pre-vectorisation body),
# with only the name changed. Do not "tidy" this -- its value is that it is the old code, not a
# paraphrase of it. It deliberately reuses the shipped `_intensity_2d`, which the change did not
# touch, so any difference is attributable to the quadrature rewrite alone.
def _pair_kernel_original_loop(x_km, y_km, s1, s2,
                               t_lapse=LAPSE_TIME_S, d=DIFFUSIVITY_KM2_S, n_quad=24):
    r1 = np.hypot(x_km - s1[0], y_km - s1[1])
    r2 = np.hypot(x_km - s2[0], y_km - s2[1])
    r12 = float(np.hypot(s1[0] - s2[0], s1[1] - s2[1]))

    # convolution over the time the wave spends getting from r1 to s and then s to r2
    u = (np.arange(n_quad) + 0.5) * (t_lapse / n_quad)
    num = np.zeros_like(r1, dtype="float64")
    for ui in u:
        num += _intensity_2d(r1, ui, d) * _intensity_2d(r2, t_lapse - ui, d)
    num *= t_lapse / n_quad

    den = _intensity_2d(np.array(r12), t_lapse, d)
    k = num / max(float(den), 1e-30)
    tot = float(np.nansum(k))
    return k / tot if tot > 0 else k


# The blocked path splits the flattened grid at `max(1, (1 << 20) // n_quad)` cells. A grid smaller
# than that is computed in ONE block, so it never exercises the loop that stitches blocks together
# -- the interesting failure mode (a cell dropped, double-counted, or normalised per block) is
# invisible on the 81x81 grid the rest of this file uses.
_BLOCK_CELLS = (1 << 20) // 24                      # 43690 cells at the default n_quad


def _assert_matches_original(k, x, y, s1, s2, rtol=1e-13, **kw):
    """Assert the shipped kernel equals the original midpoint loop to `rtol`.

    Tolerance note: on numpy 2.2.6 the two agree BIT-EXACTLY (max relative deviation 0.0) on every
    case below. That is not luck -- reducing with ``np.sum(..., axis=0)`` over a strided leading
    axis accumulates row by row in the same order the Python loop did, so no floating-point
    reassociation occurs. rtol=1e-13 is a guard band for numpy versions that might reassociate the
    reduction (pairwise summation over n_quad<=2000 terms could not plausibly cost more than that);
    it is NOT a tolerance the current code needs.
    """
    ref = _pair_kernel_original_loop(x, y, s1, s2, **kw)
    assert k.shape == ref.shape
    assert np.allclose(k, ref, rtol=rtol, atol=0.0, equal_nan=True)


def test_vectorised_quadrature_matches_the_original_loop_inter_station():
    # The default measurement geometry: two distinct receivers, default t_lapse/d/n_quad.
    x, y = _grid()
    s1, s2 = (-10.0, 0.0), (10.0, 0.0)
    _assert_matches_original(pair_kernel(x, y, s1, s2), x, y, s1, s2)


def test_vectorised_quadrature_matches_the_original_loop_autocorrelation():
    # s1 == s2 collapses r1 == r2 and sends the pair separation to zero, so the denominator is
    # p(0, t) -- its largest possible value -- while the numerator integrand is a perfect square.
    # It is a genuinely different arithmetic path through the same code and is reached in
    # production through `single_station_kernel`, so pin it through that entry point.
    x, y = _grid()
    s = (6.0, -4.0)
    _assert_matches_original(single_station_kernel(x, y, s), x, y, s, s)


def test_vectorised_quadrature_matches_the_original_loop_off_default_parameters():
    # The defaults are not the only calibration; `network_sensitivity` forwards whatever t_lapse and
    # d the caller supplies, and n_quad controls the node COUNT, which is exactly what the rewrite
    # broadcasts over. A rewrite that happened to be right at n_quad=24 and wrong elsewhere would
    # pass every other test in this file.
    a = np.linspace(-25.0, 25.0, 61)
    x, y = np.meshgrid(a, a)
    s1, s2 = (-7.0, 2.0), (5.0, -3.0)
    kw = dict(t_lapse=35.0, d=3.5, n_quad=7)
    _assert_matches_original(pair_kernel(x, y, s1, s2, **kw), x, y, s1, s2, **kw)
    kw = dict(t_lapse=2.5, d=20.0, n_quad=1)        # n_quad=1: the degenerate single-node rule
    _assert_matches_original(pair_kernel(x, y, s1, s2, **kw), x, y, s1, s2, **kw)


def test_vectorised_quadrature_matches_the_original_loop_across_block_boundaries():
    # THE POINT OF THIS ONE: force the grid past the block size so the stitching loop actually runs
    # more than once. Two ways in, and both are cheap enough for an offline suite, so do both:
    #   (a) a real-sized grid at the default n_quad -- 210x210 = 44100 cells > 43690, so 2 blocks.
    #       This is the configuration production actually hits first (a ~90 m twin grid is far
    #       bigger than this), and it costs ~10 ms.
    #   (b) a small grid at a large n_quad -- block shrinks to 524 cells, so 2500 cells span 5
    #       blocks. Cheap way to get MANY boundaries rather than just one.
    a = np.linspace(-40.0, 40.0, 210)
    x, y = np.meshgrid(a, a)
    assert x.size > _BLOCK_CELLS                     # the test is worthless if this stops holding
    s1, s2 = (-10.0, 0.0), (10.0, 0.0)
    _assert_matches_original(pair_kernel(x, y, s1, s2), x, y, s1, s2)

    b = np.linspace(-20.0, 20.0, 50)
    xb, yb = np.meshgrid(b, b)
    kw = dict(n_quad=2000)
    assert xb.size > 4 * max(1, (1 << 20) // 2000)   # >= 5 blocks
    _assert_matches_original(pair_kernel(xb, yb, s1, s2, **kw), xb, yb, s1, s2, **kw)


def test_kernel_does_not_depend_on_which_block_a_cell_lands_in():
    # Block-invariance cannot be tested by comparing a big grid to a sub-grid: the normalisation is
    # a sum over the WHOLE grid, so a sub-grid legitimately gets a different answer and the
    # comparison would be meaningless. Permuting the CELLS instead keeps the cell set -- and
    # therefore the normalising sum -- identical while completely rearranging which cells share a
    # block and where in a block each one sits. Un-permute and the answer must be unchanged.
    rng = np.random.default_rng(0)
    a = np.linspace(-20.0, 20.0, 50)
    x, y = np.meshgrid(a, a)
    kw = dict(n_quad=2000)                           # block = 524 cells -> 2500 cells span 5 blocks
    s1, s2 = (-6.0, 1.0), (6.0, -1.0)

    k = pair_kernel(x, y, s1, s2, **kw)
    p = rng.permutation(x.size)
    kp = pair_kernel(x.ravel()[p].reshape(x.shape), y.ravel()[p].reshape(y.shape), s1, s2, **kw)
    restored = np.empty(x.size)
    restored[p] = kp.ravel()
    assert np.allclose(restored.reshape(x.shape), k, rtol=1e-13, atol=0.0)


def test_nan_cells_produce_the_same_nan_pattern_as_the_original_loop():
    # Twin grids carry NaN (masked cells outside the domain). NaN interacts with three separate
    # things here: it propagates through `_intensity_2d`, `np.nansum` deliberately IGNORES it when
    # forming the normalising total, and `tot > 0` decides whether the normalisation happens at
    # all. Vectorising must not move a NaN, create one, or swallow one -- so pin the exact mask,
    # not just the finite values.
    a = np.linspace(-20.0, 20.0, 21)
    x, y = np.meshgrid(a, a)
    s1, s2 = (-5.0, 0.0), (5.0, 0.0)

    xn = x.copy()
    xn[3, 4] = np.nan
    xn[10, 10] = np.nan                              # one of them sits on the pair axis
    yn = y.copy()
    yn[:, 0] = np.nan                                # a whole column, i.e. a contiguous NaN run

    for gx, gy in ((xn, y), (x, yn)):
        k = pair_kernel(gx, gy, s1, s2)
        ref = _pair_kernel_original_loop(gx, gy, s1, s2)
        assert np.array_equal(np.isnan(k), np.isnan(ref))
        assert np.allclose(k, ref, rtol=1e-13, atol=0.0, equal_nan=True)
        assert abs(float(np.nansum(k)) - 1.0) < 1e-12    # NaNs must not break the normalisation

    # NaN cells split across block boundaries must behave the same way.
    k = pair_kernel(xn, y, s1, s2, n_quad=2000)
    ref = _pair_kernel_original_loop(xn, y, s1, s2, n_quad=2000)
    assert np.array_equal(np.isnan(k), np.isnan(ref))
    assert np.allclose(k, ref, rtol=1e-13, atol=0.0, equal_nan=True)


def test_degenerate_grids_keep_their_shape_through_the_blocking_loop():
    # The blocked path ravels the grid and walks it with `range(0, size, block)`. A zero-size grid
    # makes that range empty, and a 1x1 or single-row grid makes it a single short block -- all
    # cases where a reshape mistake would surface as a wrong-shaped return rather than a wrong
    # number. Downstream code adds these arrays together, so a shape change is a crash later, not
    # here.
    s1, s2 = (-5.0, 0.0), (5.0, 0.0)
    grids = [
        (np.array([[0.0]]), np.array([[0.0]])),                       # 1x1
        (np.array([[0.0, 1.0, 2.0, 3.0]]), np.zeros((1, 4))),         # single row
        (np.array([[0.0], [1.0], [2.0], [3.0]]), np.zeros((4, 1))),   # single column
        (np.zeros((0, 5)), np.zeros((0, 5))),                         # empty, 2-D
        (np.zeros((0,)), np.zeros((0,))),                             # empty, 1-D
    ]
    for gx, gy in grids:
        k = pair_kernel(gx, gy, s1, s2)
        ref = _pair_kernel_original_loop(gx, gy, s1, s2)
        assert k.shape == gx.shape
        assert k.shape == ref.shape
        assert np.allclose(k, ref, rtol=1e-13, atol=0.0, equal_nan=True)


def test_unnormalisable_and_floored_denominator_branches_still_behave_as_before():
    # Two guards in this function only fire in extreme geometry, which means they are exactly the
    # code a rewrite can break without anyone noticing:
    #
    #   (1) `tot > 0` -- if the pair is so far outside the grid that the numerator underflows to
    #       zero everywhere, there is nothing to normalise. The function must return the ZERO field
    #       ("this pair constrains nothing here"), NOT divide by zero and hand back NaN, which
    #       would poison the whole summed network field.
    #   (2) `max(float(den), 1e-30)` -- for a widely separated pair the denominator p(r12, t)
    #       underflows, and the floor keeps the ratio finite. The kernel must still normalise to 1.
    a = np.linspace(0.0, 4.0, 11)
    x, y = np.meshgrid(a, a)
    far = pair_kernel(x, y, (5000.0, 0.0), (5010.0, 0.0))
    assert float(np.nansum(far)) == 0.0              # the tot == 0 fallback really is reached
    assert np.all(far == 0.0) and np.all(np.isfinite(far))
    assert np.allclose(far, _pair_kernel_original_loop(x, y, (5000.0, 0.0), (5010.0, 0.0)),
                       rtol=1e-13, atol=0.0)

    r12 = 150.0                                      # p(150 km, 10 s) ~ 3e-34, below the 1e-30 floor
    assert float(_intensity_2d(np.array(r12), LAPSE_TIME_S, DIFFUSIVITY_KM2_S)) < 1e-30
    b = np.linspace(-r12 / 2 - 20.0, r12 / 2 + 20.0, 41)
    xb, yb = np.meshgrid(b, b)
    s1, s2 = (-r12 / 2, 0.0), (r12 / 2, 0.0)
    k = pair_kernel(xb, yb, s1, s2)
    assert np.all(np.isfinite(k))
    assert abs(float(np.nansum(k)) - 1.0) < 1e-12
    _assert_matches_original(k, xb, yb, s1, s2)


def test_returns_float64_shaped_like_the_grid_for_any_station_container():
    # `network_sensitivity` passes rows of an ndarray; callers and notebooks pass tuples and lists.
    # The rewrite indexes s1[0]/s1[1] exactly as before, but it also ravels and reshapes the grid,
    # so pin the contract: float64, shaped like x_km, same numbers regardless of container.
    a = np.linspace(-20.0, 20.0, 31)
    x, y = np.meshgrid(a, a)
    base = pair_kernel(x, y, (-5.0, 2.0), (5.0, -2.0))
    assert base.dtype == np.float64 and base.shape == x.shape
    for s1, s2 in [([-5.0, 2.0], [5.0, -2.0]),
                   (np.array([-5.0, 2.0]), np.array([5.0, -2.0])),
                   ([-5, 2], [5, -2])]:              # ints must not demote the result
        k = pair_kernel(x, y, s1, s2)
        assert k.dtype == np.float64 and k.shape == x.shape
        assert np.array_equal(k, base)
    # a non-C-contiguous grid (a transposed view) must survive the ravel/reshape round trip
    kt = pair_kernel(x.T, y.T, (-5.0, 2.0), (5.0, -2.0))
    assert kt.shape == x.T.shape
    assert np.allclose(kt, _pair_kernel_original_loop(x.T, y.T, (-5.0, 2.0), (5.0, -2.0)),
                       rtol=1e-13, atol=0.0)
    # an integer grid must be promoted, not truncated
    xi = np.arange(12).reshape(3, 4)
    ki = pair_kernel(xi, xi, (-5.0, 0.0), (5.0, 0.0))
    assert ki.dtype == np.float64 and ki.shape == xi.shape


def test_midpoint_quadrature_is_consistent_refining_n_quad_reduces_the_error():
    """SANITY CHECK ON THE DISCRETISATION -- NOT A CORRECTNESS PROOF, AND NOT AN EQUIVALENCE CLAIM.

    Everything above pins the vectorised code against the ORIGINAL code, which would pass just as
    happily if the original quadrature rule had been under-resolved or plain wrong. This asks a
    separate, independent question: does the midpoint rule actually converge on the continuous time
    integral it approximates?

    It does -- the peak-relative error against a 4000-node reference falls monotonically with
    n_quad, at observed order ~1 (not the formal 2 of the midpoint rule, because the integrand
    p(r1, u) p(r2, t-u) is sharply peaked near u = 0 and u = t for cells close to a receiver).
    That is enough to say the rule is CONSISTENT, i.e. the node axis the rewrite broadcasts over is
    doing real quadrature and not, say, integrating over the wrong variable.

    Read it as nothing more than that. It does NOT establish that the default n_quad is adequate
    (see the next test -- it is not), that D and t_lapse are calibrated, or that Pacheco-Snieder is
    the right kernel for this network. Those belong to numerical review, not to a unit test.
    """
    # Offset the grid so that NO cell lands exactly on a station: at r = 0 the integrand is
    # genuinely divergent and the "error" would be measuring that, not the quadrature.
    a = np.linspace(-30.0, 30.0, 61) + 0.37
    x, y = np.meshgrid(a, a)
    s1, s2 = (-10.0, 0.0), (10.0, 0.0)
    ref = pair_kernel(x, y, s1, s2, n_quad=4000)
    peak = float(np.max(ref))

    errs = [float(np.max(np.abs(pair_kernel(x, y, s1, s2, n_quad=n) - ref)) / peak)
            for n in (6, 12, 24, 48, 96)]
    assert all(lo > hi for lo, hi in zip(errs, errs[1:])), f"not converging: {errs}"
    assert errs[-1] < 0.1                                # n_quad=96 is within 10% of the integral


def test_default_n_quad_is_NOT_converged_and_diverges_on_station_cells():
    """CHARACTERISATION OF A KNOWN, PRE-EXISTING DEFECT. A green tick here is NOT an endorsement.

    This test passing means "the known problem is still exactly as measured", not "the kernel is
    right". Two findings, both present identically in the pre-vectorisation loop -- they are NOT
    regressions from the m3 rewrite, and they are numerical-soundness questions for review rather
    than bugs to patch here:

    1. The default n_quad=24 is NOT converged. Against a 4000-node reference its peak-relative
       error is ~25% on a grid whose cells avoid the stations. Because the kernel is then
       normalised by its sum over the grid, that error is not confined to a few cells -- it
       reweights the whole field, and hence the network sensitivity and the sigma map derived
       from it.

    2. Where a cell coincides exactly with a receiver, r = 0 and the integrand goes as 1/u, so the
       lapse-time integral DIVERGES logarithmically. Nothing regularises it except the `1e-6`
       clamp inside `_intensity_2d`, which is a floating-point guard, not a physical cutoff. The
       kernel value at such a cell is therefore a function of n_quad and never settles: the peak
       grows by ~2.7x going from n_quad=24 to n_quad=1e5. Whether a station lands on a cell centre
       is an accident of the grid, so this is a discretisation artefact sitting on the single most
       important cell of each kernel.

    If either is fixed (more nodes, an endpoint-aware rule, or a physical near-field cutoff), this
    test SHOULD fail -- that is the point of pinning it. Update the numbers deliberately.
    """
    a = np.linspace(-30.0, 30.0, 61) + 0.37
    x, y = np.meshgrid(a, a)
    s1, s2 = (-10.0, 0.0), (10.0, 0.0)
    ref = pair_kernel(x, y, s1, s2, n_quad=4000)
    err24 = float(np.max(np.abs(pair_kernel(x, y, s1, s2, n_quad=24) - ref)) / np.max(ref))
    assert 0.15 < err24 < 0.40, f"the known under-resolution has moved: {err24:.3e}"

    # on-node grid: a cell sits exactly on each station, so r == 0 and the integral diverges
    b = np.linspace(-30.0, 30.0, 61)
    xb, yb = np.meshgrid(b, b)
    assert np.any(np.hypot(xb - s1[0], yb - s1[1]) == 0.0)
    peaks = [float(np.max(pair_kernel(xb, yb, s1, s2, n_quad=n))) for n in (24, 240, 2400)]
    assert all(lo < hi for lo, hi in zip(peaks, peaks[1:])), f"expected divergence, got {peaks}"
    assert peaks[-1] / peaks[0] > 1.5                    # grows without settling, not converging


if __name__ == "__main__":
    test_pair_kernel_is_nonnegative_and_sum_normalised()
    test_pair_kernel_is_symmetric_under_swapping_the_stations()
    test_sensitivity_is_concentrated_near_the_stations_not_far_away()
    test_longer_lapse_time_broadens_the_kernel()
    test_network_sensitivity_counts_pairs_and_single_stations()
    test_single_station_kernel_is_peaked_at_the_receiver()
    test_sigma_is_infinite_where_there_is_no_sensitivity()
    test_defaults_are_physical()
    test_vectorised_quadrature_matches_the_original_loop_inter_station()
    test_vectorised_quadrature_matches_the_original_loop_autocorrelation()
    test_vectorised_quadrature_matches_the_original_loop_off_default_parameters()
    test_vectorised_quadrature_matches_the_original_loop_across_block_boundaries()
    test_kernel_does_not_depend_on_which_block_a_cell_lands_in()
    test_nan_cells_produce_the_same_nan_pattern_as_the_original_loop()
    test_degenerate_grids_keep_their_shape_through_the_blocking_loop()
    test_unnormalisable_and_floored_denominator_branches_still_behave_as_before()
    test_returns_float64_shaped_like_the_grid_for_any_station_container()
    test_midpoint_quadrature_is_consistent_refining_n_quad_reduces_the_error()
    test_default_n_quad_is_NOT_converged_and_diverges_on_station_cells()
    print("all dv/v sensitivity tests passed")
