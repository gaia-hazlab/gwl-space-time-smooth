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
    # any POSITIVE nu is now supported (the calibration grid needs 1.0 and 2.0, which have no
    # elementary closed form); only non-positive / non-finite nu is rejected.
    assert _raises(lambda: matern_correlation(1.0, length, nu=0.0), ValueError)
    assert _raises(lambda: matern_correlation(1.0, length, nu=-1.0), ValueError)
    assert _raises(lambda: matern_correlation(1.0, length, nu=np.nan), ValueError)


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
    test_blue_update_recovers_a_smooth_truth_and_reverts_off_support()
    test_information_gain_is_monotone_in_variance_reduction()
    print("all observability tests passed")


# --- the prior is a statistical model, chosen independently of nu, convention, and backend ---------

def test_general_nu_matches_the_half_integer_closed_forms_and_covers_the_calibration_grid():
    # nu=1.0 and nu=2.0 have no elementary closed form but are on the groundwater candidate grid, so
    # the general (Bessel) branch must exist AND agree with the closed forms where both apply.
    from scipy.special import gammaln, kv

    d = np.array([0.0, 0.25, 1.0, 3.0, 10.0, 200.0])
    L = 4.0

    def bessel_form(r, nu):
        x = (2.0 * nu) ** 0.5 * np.asarray(r) / L
        out = np.ones_like(x)
        p = x > 0
        out[p] = np.exp((1.0 - nu) * np.log(2.0) - gammaln(nu) + nu * np.log(x[p])) * kv(nu, x[p])
        return np.nan_to_num(out)

    for nu in (0.5, 1.5, 2.5):
        assert np.allclose(matern_correlation(d, L, nu), bessel_form(d, nu), atol=1e-12)
    for nu in (1.0, 2.0):
        m = matern_correlation(d, L, nu)
        assert m[0] == 1.0
        assert np.all(np.diff(m) <= 1e-12)
        assert np.all((m >= 0.0) & (m <= 1.0))
    # smoothness ordering at a fixed lag: rougher fields decorrelate faster near the origin
    at_half_L = [matern_correlation(np.array([L / 2]), L, nu)[0] for nu in (0.5, 1.0, 1.5, 2.0, 2.5)]
    assert all(a < b for a, b in zip(at_half_L, at_half_L[1:]))


def test_nu_one_half_is_the_plain_exponential_not_exp_of_sqrt2_r_over_L():
    # The documented convention is sqrt(2 nu) r / L, so sqrt(2*0.5)=1 exactly and rho = exp(-r/L).
    # The assimilation chapter previously stated exp(-sqrt(2) r / L); this pins the correct form.
    d = np.linspace(0.0, 30.0, 61)
    L = 7.0
    assert np.allclose(matern_correlation(d, L, nu=0.5), np.exp(-d / L))
    assert not np.allclose(matern_correlation(d, L, nu=0.5), np.exp(-np.sqrt(2.0) * d / L))


def test_range_convention_conversion_and_microergodic_parameter():
    from src.models.observability import (
        RANGE_CONVENTION,
        convert_matern_range,
        microergodic_parameter,
    )

    assert RANGE_CONVENTION == "sqrt(2*nu)*L".replace("*L", "*r/L")   # documented verbatim
    L, nu = 12.0, 1.5
    # Lindgren's practical range uses sqrt(8 nu) r / rho; matching arguments gives rho = 2 L
    assert convert_matern_range(L, nu, "lindgren") == 2.0 * L
    kappa = convert_matern_range(L, nu, "kappa")
    assert np.isclose(kappa, np.sqrt(2 * nu) / L)
    # the microergodic quantity is sigma^2 kappa^(2nu) -- NOT the convention-free sigma^2 / L^(2nu)
    sigma = 0.5
    assert np.isclose(microergodic_parameter(sigma, L, nu), sigma ** 2 * kappa ** (2 * nu))
    assert not np.isclose(microergodic_parameter(sigma, L, nu), sigma ** 2 / L ** (2 * nu))
    # it is invariant along the (sigma, L) ridge Zhang (2004) says is unidentifiable: scaling L by c
    # and sigma^2 by c^(2nu) leaves it unchanged
    c = 1.7
    assert np.isclose(microergodic_parameter(sigma * c ** nu, L * c, nu),
                      microergodic_parameter(sigma, L, nu))
    assert _raises(lambda: convert_matern_range(L, nu, "nonsense"), ValueError)


def test_groundwater_and_soil_moisture_can_carry_different_nu():
    # The core configuration defect this audit fixes: ONE GaussianPrior default silently governed
    # both states. The registry must let them differ, and the priors must actually differ.
    from src.models.observability import NU_CANDIDATES, PRIOR_HYPERPARAMETERS, prior_for_state

    assert set(PRIOR_HYPERPARAMETERS) == {"water_table_head_anomaly", "soil_moisture_anomaly"}
    gw = prior_for_state("water_table_head_anomaly", nu=1.5)
    sm = prior_for_state("soil_moisture_anomaly", nu=0.5)
    assert gw.nu != sm.nu
    c = _grid(n=8, span=20.0)
    assert not np.allclose(gw.cov(c) / gw.sigma ** 2, sm.cov(c) / sm.sigma ** 2)
    # ...and changing one state's nu must not touch the other's
    assert prior_for_state("soil_moisture_anomaly").nu == PRIOR_HYPERPARAMETERS[
        "soil_moisture_anomaly"].nu
    # the candidate grids are state-specific, per the audit
    assert NU_CANDIDATES["water_table_head_anomaly"] == (0.5, 1.0, 1.5, 2.0)
    assert NU_CANDIDATES["soil_moisture_anomaly"] == (0.5, 1.0, 1.5)
    # nothing is labelled calibrated, because nothing has been
    assert all(hp.status != "calibrated" for hp in PRIOR_HYPERPARAMETERS.values())
    assert _raises(lambda: prior_for_state("dvv"), KeyError)


def test_dtw_and_head_anomalies_share_one_prior_entry_not_two():
    # WTD anomaly = -head anomaly, so a separate "wtd" hyperparameter entry would be a modelling
    # error. Assert the registry does not contain one.
    from src.models.observability import PRIOR_HYPERPARAMETERS

    keys = " ".join(PRIOR_HYPERPARAMETERS).lower()
    assert "wtd" not in keys and "dtw" not in keys


def test_barrier_id_is_an_alias_of_region_id_and_a_contradiction_is_refused():
    c = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0], [11.0, 0.0]])
    region = np.array([0, 0, 1, 1])
    by_region = GaussianPrior(sigma=1.0, length_km=4.0, region_id=region)
    by_barrier = GaussianPrior(sigma=1.0, length_km=4.0, barrier_id=region)
    assert np.allclose(by_region.cov(c), by_barrier.cov(c))
    assert np.array_equal(by_region.barrier_id, region)          # the alias is populated both ways
    assert np.array_equal(by_barrier.region_id, region)
    assert _raises(lambda: GaussianPrior(sigma=1.0, length_km=4.0, region_id=region,
                                         barrier_id=np.array([0, 1, 0, 1])), ValueError)


# --- variance reduction is not resolution ----------------------------------------------------------

def test_resolution_is_an_alias_of_variance_reduction_ratio():
    from src.models.observability import resolution as res_alias
    from src.models.observability import variance_reduction_ratio

    assert res_alias is variance_reduction_ratio
    c = _grid()
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    G = np.vstack([point_footprint(c, (10.0, 10.0))])
    a, b = variance_reduction_ratio(C, G, 0.01)
    a2, b2 = res_alias(C, G, 0.01)
    assert np.allclose(a, a2) and np.allclose(b, b2)


def test_averaging_kernel_rows_sum_toward_one_where_constrained_and_zero_where_not():
    from src.models.observability import averaging_kernel, variance_reduction_ratio

    c = _grid(n=16, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=3.0).cov(c)
    G = np.vstack([point_footprint(c, (5.0, 5.0), width_km=0.4)])
    A = averaging_kernel(C, G, noise_var=1e-4)
    assert A.shape == (len(c), len(c))
    near = int(np.argmin(np.sum((c - [5.0, 5.0]) ** 2, axis=1)))
    far = int(np.argmax(np.sum((c - [5.0, 5.0]) ** 2, axis=1)))
    assert A[near].sum() > 0.9                      # essentially fully informed by the datum
    assert abs(A[far].sum()) < 0.2                  # the far cell mostly keeps its prior
    # a no-observation system has a zero resolution operator and zero DFS
    assert np.allclose(averaging_kernel(C, np.empty((0, len(c))), 1.0), 0.0)


def test_a_broad_footprint_gives_high_variance_reduction_but_a_WIDE_averaging_kernel():
    # This is the claim the docs must stop making: high R(j) does not mean the estimate at j is
    # localized. A single very broad footprint drives R up while the averaging kernel stays wide.
    from src.models.observability import (
        averaging_kernel,
        resolution_width_km,
        variance_reduction_ratio,
    )

    c = _grid(n=21, span=40.0)
    C = GaussianPrior(sigma=1.0, length_km=15.0).cov(c)
    centre = np.array([20.0, 20.0])
    j = int(np.argmin(np.sum((c - centre) ** 2, axis=1)))

    narrow = np.vstack([point_footprint(c, centre, width_km=0.4)])
    broad = np.vstack([point_footprint(c, centre, width_km=6.0)])     # a dv/v-like volume average

    r_narrow, _ = variance_reduction_ratio(C, narrow, 1e-3)
    r_broad, _ = variance_reduction_ratio(C, broad, 1e-3)
    w_narrow = resolution_width_km(C, narrow, 1e-3, c, rows=[j])[0]
    w_broad = resolution_width_km(C, broad, 1e-3, c, rows=[j])[0]

    assert r_broad[j] > 0.9 and r_narrow[j] > 0.9      # BOTH look "well resolved" on the diagonal
    assert w_broad > 10.0 * w_narrow                   # but the broad datum is far less localized
    assert w_broad > 5.0                               # kilometres, not the 90 m the grid suggests
    # the wide kernel is genuinely spread: its peak weight is a smaller share of the row
    A_broad = averaging_kernel(C, broad, 1e-3, rows=[j])[0]
    A_narrow = averaging_kernel(C, narrow, 1e-3, rows=[j])[0]
    assert A_broad.max() < A_narrow.max()
    # an unconstrained system has no width, not zero width
    assert np.isnan(resolution_width_km(C, np.empty((0, len(c))), 1.0, c, rows=[j])[0])


def test_degrees_of_freedom_for_signal_is_bounded_by_the_number_of_observations():
    from src.models.observability import degrees_of_freedom_for_signal as dfs

    c = _grid(n=12, span=20.0)
    C = GaussianPrior(sigma=1.0, length_km=4.0).cov(c)
    locs = [(4.0, 4.0), (16.0, 4.0), (4.0, 16.0), (16.0, 16.0)]
    G = np.vstack([point_footprint(c, p) for p in locs])

    assert dfs(C, np.empty((0, len(c))), 1.0) == 0.0
    d_low, d_high = dfs(C, G, 1e-4), dfs(C, G, 10.0)
    assert 0.0 < d_high < d_low <= len(locs) + 1e-9      # noisier data determine fewer numbers
    assert d_low > 3.0                                   # 4 well-separated precise data ~ 4 dof
    # co-located duplicates add data but almost no independent information
    dup = np.vstack([point_footprint(c, (4.0, 4.0)) for _ in range(4)])
    assert dfs(C, dup, 1e-4) < 1.5


# --- a screened/confined well cannot use the shallow water-table point operator (#189) --------------

def test_water_table_point_operator_refuses_a_confined_or_unknown_observation():
    from src.models.observability import water_table_point_footprint

    c = _grid(n=8, span=20.0)
    loc = (10.0, 10.0)
    g = water_table_point_footprint(c, loc, "water_table")
    assert np.isclose(g.sum(), 1.0)
    assert np.allclose(g, point_footprint(c, loc))          # same operator, just gated

    assert _raises(lambda: water_table_point_footprint(c, loc, "aquifer_head"), ValueError)
    assert _raises(lambda: water_table_point_footprint(c, loc, "unknown"), ValueError)
    assert _raises(lambda: water_table_point_footprint(c, loc, "shallow_watertable"), ValueError)


def test_a_deep_confined_well_is_classified_then_refused_end_to_end():
    # the semantic layer and the operator layer must agree: a well NWIS says is confined must not be
    # able to reach the h_wt point operator by any ordinary route.
    import pandas as pd

    from src.features.well_hydrostratigraphy import measurement_target
    from src.models.observability import water_table_point_footprint

    sites = pd.DataFrame({
        "well_depth_m": [8.0, 8.0, 120.0, np.nan],
        "aqfr_type_cd": ["U", "C", None, None],      # a SHALLOW well in a confined unit is not h_wt
        "is_flowing": [False, False, False, True],
    })
    tgt = list(measurement_target(sites))
    assert tgt == ["water_table", "aquifer_head", "aquifer_head", "unknown"]

    c = _grid(n=6, span=10.0)
    assert np.isclose(water_table_point_footprint(c, (5.0, 5.0), tgt[0]).sum(), 1.0)
    for bad in tgt[1:]:
        assert _raises(lambda t=bad: water_table_point_footprint(c, (5.0, 5.0), t), ValueError)
