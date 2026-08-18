"""Tests for the linear-Gaussian observability / information-gain core (issue: sensor design).

Runs standalone (`python -m tests.test_observability`); also pytest-discoverable.

These pin the invariants that make the resolution and information maps trustworthy: a resolution
outside [0,1], or one that a sensor could DECREASE by adding data, would make the "where is each sensor
worth its cost" map meaningless.
"""

from __future__ import annotations

import numpy as np

from src.models import observability as obs_module
from src.models.observability import (
    TEMPORAL_TAU_DAYS,
    GaussianPrior,
    channel_footprints,
    information_gain,
    lagged_observation,
    marginal_resolution,
    matern_correlation,
    normalise_footprint,
    ou_correlation,
    point_footprint,
    blue_update,
    resolution,
    satellite_footprints,
    screening_observability,
    temporal_resolution,
)


def _raises(fn, exc=Exception):
    try:
        fn()
    except exc:
        return True
    return False


def _grid(n=16, span=20.0):
    a = np.linspace(0, span, n)
    xx, yy = np.meshgrid(a, a)
    return np.column_stack([xx.ravel(), yy.ravel()])


def _joint_gaussian_resolution(C, G, lag_days, tau_days, obs_var):
    r"""``R_truth(x)``: the exact posterior variance-reduction ratio, from the joint Gaussian ONLY.

    Issue #166: this is the independent reference the screening claims are checked against, and it is
    built from the separable space-time prior directly -- ``Cov(m(x,t), m(x',t')) = C(x,x') rho(|t-t'|)``
    -- with NO decomposition into an "effective operator plus drift noise". It deliberately does NOT
    call :func:`lagged_observation`, which is the routine under suspicion.

    For data ``y_i = g_i' m(t - dt_i) + eps_i`` the joint Gaussian of ``(m(t), y)`` has

        Cov(m(t), y) = C G' D,   D = diag(rho(dt_i))
        Var(y) = M   = (G C G') o rho_pair + diag(sigma_d^2),   rho_pair_ij = rho(|dt_i - dt_j|)

    (``o`` = Hadamard product), so the variance removed at cell ``x`` is ``[C G' D M^-1 D G C]_xx`` and
    ``R_truth(x)`` is that over ``C_xx``. Note ``rho_pair`` is the correlation of the LAG DIFFERENCES,
    not the outer product ``rho_i rho_j`` -- they coincide only when ``min(dt_i, dt_j) = 0``.
    """
    C = np.asarray(C, dtype="float64")
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    lags = np.broadcast_to(np.asarray(lag_days, dtype="float64"), (G.shape[0],))
    rho = ou_correlation(lags, tau_days)
    rho_pair = ou_correlation(np.abs(lags[:, None] - lags[None, :]), tau_days)
    sigma_d2 = np.broadcast_to(np.asarray(obs_var, dtype="float64"), (G.shape[0],))

    CG = C @ G.T                                          # (n_cell, n_obs)
    M = (G @ CG) * rho_pair + np.diag(sigma_d2)           # (n_obs, n_obs)
    A = CG * rho[None, :]                                 # C G' D
    reduction = np.einsum("ij,ji->i", A, np.linalg.solve(M, A.T))
    return reduction / np.diag(C)


def test_footprints_sum_to_one():
    c = _grid()
    assert abs(point_footprint(c, (10.0, 10.0)).sum() - 1.0) < 1e-9
    raw = np.random.default_rng(0).random(len(c))
    assert abs(normalise_footprint(raw).sum() - 1.0) < 1e-9


def test_point_footprint_never_returns_an_all_zero_row():
    # underflow (width far below the cell size) or a location far outside the grid must still place
    # unit mass on the nearest cell, so a point sensor is never silently dropped from the design.
    c = _grid(n=10, span=20.0)
    tiny = point_footprint(c, (10.0, 10.0), width_km=1e-6)
    assert abs(tiny.sum() - 1.0) < 1e-9 and (tiny > 0).sum() == 1
    outside = point_footprint(c, (500.0, 500.0), width_km=0.5)
    assert abs(outside.sum() - 1.0) < 1e-9                # mass on the nearest in-grid cell
    assert int(np.argmax(outside)) == int(np.argmin(np.sum((c - [500.0, 500.0]) ** 2, axis=1)))


def test_normalise_footprint_null_observation_is_all_zeros():
    # a footprint with NO grid support is a null observation -> all zeros, treated by resolution() as
    # observing nothing (not a silent 1/0 or an unnormalised row).
    assert np.all(normalise_footprint(np.zeros(9)) == 0.0)
    assert np.all(normalise_footprint(np.full(9, np.nan)) == 0.0)


def test_matern_correlation_is_rougher_than_the_old_squared_exponential():
    length = 5.0
    d = np.linspace(0.0, 20.0, 50)
    rbf = np.exp(-(d ** 2) / (2.0 * length ** 2))                # the old (issue #163) kernel
    for nu in (0.5, 1.5, 2.5):
        m = matern_correlation(d, length, nu=nu)
        assert m[0] == 1.0                                       # unit correlation at zero distance
        assert np.all(np.diff(m) <= 1e-12)                       # monotone decreasing with distance
        assert np.all(m >= -1e-9)
    # nu=0.5 (exponential) is rougher near the origin than the squared-exponential -- it decays faster
    assert matern_correlation(np.array([1.0]), length, nu=0.5)[0] < rbf[np.argmin(np.abs(d - 1.0))]
    assert _raises(lambda: matern_correlation(1.0, length, nu=99), ValueError)


def test_gaussian_prior_defaults_to_matern_and_is_positive_semidefinite():
    c = _grid(n=12, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)          # default nu=1.5
    assert np.allclose(C, C.T)
    eigvals = np.linalg.eigvalsh(C)
    assert np.all(eigvals >= -1e-8 * eigvals.max())              # PSD (a valid covariance)
    assert np.allclose(np.diag(C), 1.0)                          # unit variance at distance 0


def test_region_id_masks_correlation_across_a_terrain_divide():
    # Two cells at the SAME distance apart: one pair in the same region (valley), one pair split
    # across regions (ridge vs valley). The terrain-aware prior must NOT correlate the split pair,
    # unlike a plain isotropic kernel which treats them identically (issue #163's core complaint).
    c = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0], [11.0, 0.0]])
    region = np.array([0, 0, 1, 1])          # cells 0,1 in region A; cells 2,3 in region B
    prior = GaussianPrior(sigma=1.0, length_km=4.0, region_id=region)
    C = prior.cov(c)
    same_region_corr = C[0, 1] / (prior.sigma ** 2)
    cross_region_corr = C[1, 2] / (prior.sigma ** 2)             # 9 km apart, still > 0 without masking
    assert same_region_corr > 0.5                                 # unmasked, close-by, still correlated
    assert cross_region_corr == 0.0                               # masked: no leakage across the divide
    # without region_id, the isotropic kernel WOULD correlate cells 1 and 2 (9 km apart, still > 0)
    unmasked = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    assert unmasked[1, 2] > 0.0


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


def test_satellite_footprints_tile_the_domain_and_a_finer_pixel_resolves_more():
    c = _grid(n=24, span=30.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    coarse = satellite_footprints(c, pixel_km=9.0)        # SMAP-like
    fine = satellite_footprints(c, pixel_km=2.0)          # NISAR-like
    assert coarse.shape[0] > 4 and fine.shape[0] > coarse.shape[0]   # a satellite covers EVERYWHERE
    for G in (coarse, fine):
        assert np.allclose(G.sum(axis=1), 1.0)            # every footprint is an averaging operator
    res_coarse, _ = resolution(C, coarse, 0.05)
    res_fine, _ = resolution(C, fine, 0.05)
    assert res_fine.mean() > res_coarse.mean()            # finer pixels resolve more of the field
    # and a satellite (everywhere) resolves the field more UNIFORMLY than a few points
    pts = np.vstack([point_footprint(c, loc) for loc in [(5, 5), (25, 25)]])
    res_pts, _ = resolution(C, pts, 0.05)
    assert res_coarse.min() > res_pts.min()               # no dark corners under a satellite


def test_satellite_footprints_validate_inputs_and_average_uniformly():
    c = _grid(n=12, span=24.0)
    G = satellite_footprints(c, pixel_km=8.0)
    for row in G:                                        # top-hat: a pixel averages uniformly
        nz = row[row > 0]
        assert np.allclose(nz, nz[0])
    assert _raises(lambda: satellite_footprints(c, pixel_km=0.0))
    assert _raises(lambda: satellite_footprints(c, pixel_km=8.0, land=np.ones(len(c) + 3, bool)))
    land2d = np.ones((12, 12), dtype=bool)               # a 2-D raster mask (flattened) is accepted
    assert satellite_footprints(c, 8.0, land=land2d).shape[0] > 0


def test_channel_footprints_validate_lengths():
    c = _grid(n=10, span=20.0)
    hand = np.hypot(c[:, 0] - 10, c[:, 1] - 10)
    assert _raises(lambda: channel_footprints(c, hand[:-2], np.ones(len(c), bool)))
    assert _raises(lambda: channel_footprints(c, hand, np.ones(len(c) - 1, bool)))


def test_channel_footprints_sit_only_on_low_hand_cells():
    c = _grid(n=20, span=20.0)
    hand = np.hypot(c[:, 0] - 10, c[:, 1] - 10)           # a valley at the centre, ridges at the edge
    land = np.ones(len(c), dtype=bool)
    G = channel_footprints(c, hand, land, hand_max_m=2.0)
    assert G.shape[0] >= 1
    # each surface-water observation must be centred on a low-HAND (valley) cell
    peak_cells = G.argmax(axis=1)
    assert np.all(hand[peak_cells] <= 2.0 + 1e-9)


def test_temporal_resolution_captures_the_space_time_tradeoff():
    tau = 5.0                                            # soil moisture: fast (days)
    # a continuous stream resolves ~everything; a weekly one aliases a fast state
    assert temporal_resolution(0.0, tau) == 1.0
    assert temporal_resolution(1.0, tau) > temporal_resolution(7.0, tau)
    assert temporal_resolution(30.0, tau) < 0.1          # monthly revisit vs a 5-day state -> aliased
    # the SAME revisit resolves a SLOW state far better than a fast one
    sat_revisit = 7.0
    assert temporal_resolution(sat_revisit, 120.0) > temporal_resolution(sat_revisit, 5.0)
    assert np.all((temporal_resolution([0.0, 3.0, 12.0], tau) >= 0) &
                  (temporal_resolution([0.0, 3.0, 12.0], tau) <= 1))


def test_ou_correlation_is_the_single_exponent_behind_temporal_resolution():
    # rho(dt) = exp(-dt/tau), no independent factor of 2 (that belongs to the spatial RBF kernel only)
    tau = 10.0
    assert ou_correlation(0.0, tau) == 1.0
    assert np.isclose(ou_correlation(tau, tau), np.exp(-1.0))
    # temporal_resolution is exactly rho^2 (issue #161: previously exp(-dt/2tau), an inconsistent
    # exponent copied from the spatial kernel, not rho^2 of the OU process)
    dt = np.array([0.0, 3.0, 10.0, 40.0])
    assert np.allclose(temporal_resolution(dt, tau), ou_correlation(dt, tau) ** 2)


def test_lagged_observation_shrinks_gain_and_adds_drift_noise():
    tau, state_var, obs_var = 10.0, 1.0, 0.01
    g = np.array([0.25, 0.25, 0.5])

    # no lag: gain unchanged, no drift noise added
    g0, nv0 = lagged_observation(g, 0.0, tau, state_var, obs_var)
    assert np.allclose(g0, g)
    assert np.isclose(nv0, obs_var)

    # a stale datum: gain shrinks (rho < 1) and effective noise grows (drift term > 0) --
    # NOT the old "unit gain, inflate noise by 1/rho^2" treatment, which left g untouched
    g1, nv1 = lagged_observation(g, tau, tau, state_var, obs_var)
    rho = np.exp(-1.0)
    assert np.allclose(g1, rho * g)
    assert np.isclose(nv1, state_var * (1 - rho ** 2) + obs_var)
    assert nv1 > obs_var                                 # strictly more than the unlagged noise
    assert np.sum(g1) < np.sum(g)                        # gain shrank, unlike the unit-gain treatment

    # as the lag grows without bound, the datum carries no information about the current state:
    # gain -> 0 and effective noise -> the full state variance (plus obs noise), not to infinity
    g_inf, nv_inf = lagged_observation(g, 1e6, tau, state_var, obs_var)
    assert np.allclose(g_inf, 0.0, atol=1e-6)
    assert np.isclose(nv_inf, state_var + obs_var, atol=1e-6)


def test_blue_update_recovers_a_smooth_truth_and_reverts_off_support():
    # A smooth "truth" sampled at two points must be recovered NEAR the sensors and REVERT TO THE PRIOR
    # MEAN (0) far from them -- this is the estimator the whole framework rests on.
    c = _grid(n=25, span=40.0)
    truth = np.sin(c[:, 0] / 8.0) * np.cos(c[:, 1] / 8.0)      # a smooth field
    B = GaussianPrior(sigma=1.0, length_km=6.0).cov(c)
    locs = [(10.0, 10.0), (30.0, 30.0)]
    G = np.vstack([point_footprint(c, p) for p in locs])
    d = np.array([truth[int(np.argmin(np.sum((c - p) ** 2, 1)))] for p in locs])
    m_a, vpost = blue_update(B, G, d, noise_var=1e-3)
    # near a sensor the analysis matches the truth; far away it reverts to the prior mean 0
    for p, di in zip(locs, d):
        near = np.argmin(np.sum((c - p) ** 2, 1))
        assert abs(m_a[near] - di) < 0.15
    far = np.argmin(np.sum((c - [40.0, 0.0]) ** 2, 1))         # a corner with no nearby sensor
    assert abs(m_a[far]) < abs(truth[far]) + 0.3 and abs(m_a[far]) < 0.4
    assert np.all(vpost <= np.diag(B) + 1e-9)
    # a nonzero prior mean is honoured (empty obs -> exactly the prior mean)
    m0, _ = blue_update(B, np.empty((0, len(c))), np.array([]), 1e-3, prior_mean=2.5)
    assert np.allclose(m0, 2.5)


def test_information_gain_is_monotone_in_variance_reduction():
    vp = np.array([1.0, 1.0, 1.0])
    vq = np.array([1.0, 0.5, 0.1])                        # increasing reduction
    ig = information_gain(vp, vq)
    assert ig[0] < ig[1] < ig[2] and ig[0] == 0.0


def test_screening_observability_exists_under_its_new_name_and_the_old_name_is_gone():
    # Issue #166: `effective_observability` was renamed to `screening_observability` because the old
    # name asserted something the function is not -- an observability, i.e. a posterior-variance
    # diagonal of an arbitrary observing system. The old name is GONE, not aliased: it had zero call
    # sites, and keeping it would keep the false claim alive in every IDE completion list.
    assert not hasattr(obs_module, "effective_observability")
    assert hasattr(obs_module, "screening_observability")

    # what the wrapper is FOR, without restating its one-line body: it must select tau by STATE, decay
    # with revisit, be the identity at zero revisit, and be linear in the spatial factor.
    rng = np.random.default_rng(3)
    spatial = rng.random(40)
    assert np.array_equal(screening_observability(spatial, 0.0, "gwl"), spatial)       # no lag, no loss
    slow = screening_observability(spatial, 30.0, "gwl")                # tau = 120 d
    fast = screening_observability(spatial, 30.0, "soil_moisture")      # tau = 5 d
    assert np.all(slow[spatial > 0] > fast[spatial > 0])                # same revisit aliases the FAST state
    assert np.all(screening_observability(spatial, 60.0, "gwl") < slow[:] + 1e-15)   # monotone in revisit
    assert np.allclose(screening_observability(2.0 * spatial, 30.0, "gwl"), 2.0 * slow)  # linear in space
    assert np.array_equal(screening_observability(0.5, 0.0, "gwl"), np.asarray(0.5))     # scalar input
    assert _raises(lambda: screening_observability(spatial, 30.0, "no_such_state"))  # never silent


def test_the_screening_product_is_the_exact_variance_reduction_of_one_lagged_datum_at_a_common_lag():
    # Issue #166 (RETRACTED F1/F2/F3): an earlier round of these tests pinned the screening product as
    # an "optimistic upper bound", tight only at zero lag or for a one-hot footprint. That was the
    # arithmetic of a DEFECT in `lagged_observation` (see the known-defect pin below), not the physics.
    # Derived from the joint Gaussian of (m(t), y) directly, a single datum at lag dt gives
    #   Cov(m(t), y) = rho C g,   Var(y) = g'Cg + sigma_d^2   (rho_pair = 1 for one datum),
    # so the reduction carries a clean factor rho^2 and R_truth = rho^2 * R_space EXACTLY -- for ANY
    # footprint, at ANY lag. The product is not a bound; it is the answer.
    c = _grid(n=8, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    g = point_footprint(c, (10.0, 10.0), width_km=3.0)                  # spread over MANY cells
    assert (g > 1e-6).sum() > 4 and float(g @ C @ g) < 1.0              # g'Cg < sigma_m^2: the old "gap"
    lag = 60.0

    r_space, _ = resolution(C, g[None, :], noise_var=0.05)
    r_screen = screening_observability(r_space, lag, "gwl")
    r_truth = _joint_gaussian_resolution(C, g[None, :], lag, TEMPORAL_TAU_DAYS["gwl"], 0.05)

    lit = r_truth > 1e-12
    assert lit.sum() > 10                                               # the comparison is not vacuous
    assert np.max(np.abs(r_screen[lit] / r_truth[lit] - 1.0)) < 1e-14   # EXACT, not a bound
    assert np.all(r_truth >= -1e-12) and np.all(r_truth <= 1.0 + 1e-12)
    # and the temporal factor really is rho^2, not rho: the two differ by a lot at this lag
    rho = ou_correlation(lag, TEMPORAL_TAU_DAYS["gwl"])
    assert np.max(np.abs(r_truth[lit] / r_space[lit] - rho ** 2)) < 1e-14
    assert abs(rho - rho ** 2) > 0.1


def test_the_screening_product_stays_exact_for_several_mutually_correlated_data_at_a_common_lag():
    # Issue #166 (RETRACTED F5): the old test claimed the product "is not a bound at all" once two
    # footprints are prior-correlated. False -- at a COMMON lag rho_pair is the all-ones matrix, so
    #   Cov(m(t), y) = rho C G',   Var(y) = G C G' + diag(sigma_d^2)
    # and the rho factors out of the whole n_obs x n_obs solve untouched: R_truth = rho^2 * R_space,
    # exactly, however strongly the data are correlated with one another.
    c = _grid(n=8, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    G = np.vstack([point_footprint(c, loc, width_km=2.0) for loc in [(8, 8), (10, 10), (9, 12)]])
    assert np.all((G > 1e-6).sum(axis=1) > 20)         # spread footprints, not one-hot degenerate ones
    cross = G @ C @ G.T
    off = cross[~np.eye(3, dtype=bool)]
    assert off.min() > 0.6 * np.diag(cross).min()      # these data ARE strongly mutually correlated
    assert np.linalg.eigvalsh(cross).max() > 1.0       # the old "PSD condition" that supposedly broke it
    lag = 45.0

    r_space, _ = resolution(C, G, noise_var=0.05)
    r_screen = screening_observability(r_space, lag, "gwl")
    r_truth = _joint_gaussian_resolution(C, G, lag, TEMPORAL_TAU_DAYS["gwl"], 0.05)

    lit = r_truth > 1e-12
    assert lit.sum() > 10
    assert np.max(np.abs(r_screen[lit] / r_truth[lit] - 1.0)) < 1e-14


def test_a_signed_footprint_is_still_exactly_the_screening_product_at_a_common_lag():
    # Issue #166 (RETRACTED F4): the old test claimed a signed footprint (a dv/v coda kernel with
    # negative lobes, which `normalise_footprint` permits) "REVERSES the screening inequality". There is
    # no inequality to reverse. Nothing in the joint-Gaussian derivation asks for g >= 0 or for
    # g'Cg <= sigma_m^2 -- the rho^2 factors out regardless of the sign structure of g.
    c = _grid(n=8, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    g = 1.6 * point_footprint(c, (5.0, 5.0), width_km=2.0) - 0.6 * point_footprint(c, (18.0, 18.0),
                                                                                   width_km=2.0)
    assert abs(g.sum() - 1.0) < 1e-12 and g.min() < -0.05          # normalised, but SIGNED
    assert float(g @ C @ g) > 1.0                                   # g'Cg > sigma_m^2: the retracted trigger
    lag = 60.0

    r_space, _ = resolution(C, g[None, :], noise_var=0.10)
    r_screen = screening_observability(r_space, lag, "gwl")
    r_truth = _joint_gaussian_resolution(C, g[None, :], lag, TEMPORAL_TAU_DAYS["gwl"], 0.10)

    lit = r_truth > 1e-12
    assert lit.sum() > 10
    assert np.max(np.abs(r_screen[lit] / r_truth[lit] - 1.0)) < 1e-14


def test_mixed_lags_admit_no_single_temporal_factor_while_a_common_lag_admits_exactly_one():
    # Issue #166: THE justification for calling this a screening SCORE rather than a resolution. The
    # `revisit_days` argument is a single scalar, and that restriction is load-bearing: with data at
    # DIFFERENT lags, rho_pair_ij = rho(|dt_i - dt_j|) is not the outer product rho_i rho_j (equal only
    # when min(dt_i, dt_j) = 0), so no scalar can be pulled out of the n_obs x n_obs solve. The sharp,
    # measurable signature is the per-cell ratio R_truth / R_space: EXACTLY constant at a common lag,
    # spread over most of the unit interval once the lags differ.
    tau = TEMPORAL_TAU_DAYS["gwl"]
    # the mechanism itself, in one line: rho(|7 - 30|) != rho(7) rho(30)
    assert abs(ou_correlation(23.0, tau) - ou_correlation(7.0, tau) * ou_correlation(30.0, tau)) > 0.08

    c = _grid(n=8, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    G = np.vstack([point_footprint(c, loc, width_km=3.0)
                   for loc in [(5, 5), (10, 10), (7, 12), (15, 6)]])
    r_space, _ = resolution(C, G, noise_var=0.05)
    lit = r_space > 1e-8
    assert lit.sum() > 10

    # (a) mixed lags: the ratio is NOT a constant -- it ranges from ~0.19 to ~1.00 across the grid
    mixed = _joint_gaussian_resolution(C, G, [0.0, 7.0, 30.0, 90.0], tau, 0.05)[lit] / r_space[lit]
    assert mixed.max() - mixed.min() > 0.5          # reference figure: 0.188 to 0.997, spread 0.81
    assert mixed.min() < 0.35 and mixed.max() > 0.9
    # so no `temporal_resolution(revisit, tau)` -- for ANY revisit -- reproduces this map
    for revisit in (0.0, 7.0, 30.0, 90.0):
        assert not np.allclose(mixed, temporal_resolution(revisit, tau), atol=0.05)

    # (b) the SAME data at a COMMON lag: the spread collapses to machine precision, and the constant is
    # exactly temporal_resolution -- i.e. screening_observability is the exact answer in this case only
    common = _joint_gaussian_resolution(C, G, 30.0, tau, 0.05)[lit] / r_space[lit]
    assert common.max() - common.min() < 1e-12      # EXACTLY constant, unlike (a)
    assert np.max(np.abs(common - temporal_resolution(30.0, tau))) < 1e-14
    screened = screening_observability(r_space, 30.0, "gwl")[lit]
    assert np.max(np.abs(screened / (_joint_gaussian_resolution(C, G, 30.0, tau, 0.05)[lit]) - 1.0)) < 1e-14


def test_lagged_observation_into_resolution_still_disagrees_with_the_truth_a_known_open_defect():
    # KNOWN OPEN DEFECT, issue #166 -- this test pins a BUG, not physics. DELETE IT when the defect is
    # repaired; it is here so the wrong number cannot be quoted as a result and so the repair announces
    # itself loudly instead of silently changing every downstream map.
    #
    # `lagged_observation` charges a drift variance (1 - rho^2) * state_var, but the correct drift
    # variance for a FOOTPRINT-AVERAGED datum is (1 - rho^2) * g'Cg. Since g'Cg < sigma_m^2 for a spread
    # non-negative footprint, it over-charges the noise and is therefore PESSIMISTIC. (For n_obs > 1 the
    # true drift is also CORRELATED across data, (1 - rho^2) g_i'C g_j, which `resolution`'s diagonal
    # `noise_var` structurally cannot represent at all.) The direction and rough size are pinned; the
    # exact number is not a physical quantity and must not be treated as one.
    c = _grid(n=8, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    g = point_footprint(c, (10.0, 10.0), width_km=3.0)
    lag, obs_var = 60.0, 0.05

    g_eff, nv_eff = lagged_observation(g[None, :], np.full(1, lag), TEMPORAL_TAU_DAYS["gwl"],
                                       1.0, obs_var)
    r_defect, _ = resolution(C, g_eff, nv_eff)
    r_truth = _joint_gaussian_resolution(C, g[None, :], lag, TEMPORAL_TAU_DAYS["gwl"], obs_var)
    lit = r_truth > 1e-12
    assert np.all(r_defect[lit] < r_truth[lit])                  # pessimistic at EVERY lit cell
    assert r_defect[lit].max() / r_truth[lit].max() < 0.7        # and by far more than roundoff


if __name__ == "__main__":
    test_footprints_sum_to_one()
    test_resolution_is_a_fraction_in_the_unit_interval()
    test_resolution_is_highest_at_the_sensor_and_decays_away()
    test_lower_noise_gives_more_resolution()
    test_more_sensors_never_reduce_resolution_and_no_sensors_is_zero()
    test_marginal_gain_is_where_the_added_sensor_reaches_beyond_the_base()
    test_satellite_footprints_tile_the_domain_and_a_finer_pixel_resolves_more()
    test_satellite_footprints_validate_inputs_and_average_uniformly()
    test_channel_footprints_validate_lengths()
    test_channel_footprints_sit_only_on_low_hand_cells()
    test_temporal_resolution_captures_the_space_time_tradeoff()
    test_lagged_observation_shrinks_gain_and_adds_drift_noise()
    test_blue_update_recovers_a_smooth_truth_and_reverts_off_support()
    test_information_gain_is_monotone_in_variance_reduction()
    test_screening_observability_exists_under_its_new_name_and_the_old_name_is_gone()
    test_the_screening_product_is_the_exact_variance_reduction_of_one_lagged_datum_at_a_common_lag()
    test_the_screening_product_stays_exact_for_several_mutually_correlated_data_at_a_common_lag()
    test_a_signed_footprint_is_still_exactly_the_screening_product_at_a_common_lag()
    test_mixed_lags_admit_no_single_temporal_factor_while_a_common_lag_admits_exactly_one()
    test_lagged_observation_into_resolution_still_disagrees_with_the_truth_a_known_open_defect()
    print("all observability tests passed")
