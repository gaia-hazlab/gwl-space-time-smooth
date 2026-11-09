"""Dependence-sensitivity sanity check (review ladder U1, issue #299): sampling a posterior from
marginal variances overstates the probability that a 20-cell reach contains a shallow cell."""
from __future__ import annotations

import numpy as np

from src.models.observability import blue_update, matern_correlation


def test_independent_draws_overstate_reach_minimum_probability():
    n, dx, sigma = 200, 0.09, 0.5
    x = np.arange(n) * dx
    B = sigma ** 2 * matern_correlation(np.abs(x[:, None] - x[None, :]), 12.0, 1.5)
    wells = [20, 60, 100, 140, 180]
    G = np.zeros((5, n)); G[np.arange(5), wells] = 1.0
    m_a, var_a = blue_update(B, G, np.full(5, 1.2), 0.1, prior_mean=1.5)
    K = B @ G.T @ np.linalg.inv(G @ B @ G.T + 0.1 * np.eye(5))
    C_a = B - K @ G @ B
    np.testing.assert_allclose(np.diag(C_a), var_a, rtol=1e-8)            # blue_update returns the marginal variance only
    rng = np.random.default_rng(1)
    z = rng.standard_normal((5000, n))
    coh = m_a + z @ np.linalg.cholesky(0.5 * (C_a + C_a.T) + 1e-10 * np.eye(n)).T
    ind = m_a + z * np.sqrt(var_a)
    p_coh = np.mean(coh[:, 90:110].min(axis=1) < 1.0)
    p_ind = np.mean(ind[:, 90:110].min(axis=1) < 1.0)
    assert p_ind > 2.0 * p_coh
