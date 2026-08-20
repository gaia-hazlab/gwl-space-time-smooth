"""Tests for the hydrologic state vocabulary and its invariants (:mod:`src.models.hydro_state`).

These pin the algebra that the terminology audit turned into code: DTW and water-table head are one
field up to sign, storage diagnoses head under a named specific yield, and pore-pressure conversions
never hide their hydrologic assumption.

Runs standalone (`python -m tests.test_hydro_state`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.models.hydro_state import (
    G,
    RHO_W,
    assert_anomaly_covariance_identity,
    dtw_anomaly_from_head_anomaly,
    dtw_from_water_table_elevation,
    head_anomaly_from_dtw_anomaly,
    hydraulic_head_from_pressure,
    pore_pressure_head_m,
    pore_pressure_hydrostatic_below_water_table,
    pore_pressure_slope_parallel,
    storage_from_water_table_head,
    water_table_elevation_from_dtw,
    water_table_head_from_storage,
)
from src.models.observability import GaussianPrior


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


# --- D = z_s - h_wt, and the round trip ------------------------------------------------------------

def test_dtw_and_water_table_elevation_are_exact_inverses():
    rng = np.random.default_rng(0)
    z_s = rng.uniform(0.0, 800.0, 64)                 # land surface, m NAVD88
    h_wt = z_s - rng.uniform(0.5, 40.0, 64)           # water table below ground

    d = dtw_from_water_table_elevation(z_s, h_wt)
    assert np.all(d > 0)                              # positive downward
    assert np.allclose(water_table_elevation_from_dtw(z_s, d), h_wt)
    assert np.allclose(dtw_from_water_table_elevation(z_s, water_table_elevation_from_dtw(z_s, d)), d)


def test_artesian_condition_is_reported_as_negative_dtw_not_clipped():
    # a head standing above land surface is a flowing/artesian condition; silently clipping it to
    # zero would turn a "this well is not measuring a water table" signal into a plausible-looking
    # zero-depth water table.
    assert dtw_from_water_table_elevation(100.0, 102.5) == -2.5


# --- the invariant: Delta D = -Delta h_wt ----------------------------------------------------------

def test_dtw_anomaly_is_exactly_minus_the_head_anomaly():
    rng = np.random.default_rng(1)
    z_s = rng.uniform(0.0, 800.0, 200)
    h0 = z_s - rng.uniform(1.0, 30.0, 200)
    dh = rng.normal(0.0, 0.8, 200)                    # a head anomaly

    d0 = dtw_from_water_table_elevation(z_s, h0)
    d1 = dtw_from_water_table_elevation(z_s, h0 + dh)
    assert np.allclose(d1 - d0, -dh)                  # the invariant, straight from the definition
    assert np.allclose(dtw_anomaly_from_head_anomaly(dh), d1 - d0)
    assert np.allclose(head_anomaly_from_dtw_anomaly(d1 - d0), dh)


def test_the_two_anomaly_representations_have_identical_covariance():
    # THE point of the invariant: sign flips, covariance does not. So a Matern prior fitted to the
    # WTD anomaly and one fitted to the head anomaly must be the same object -- there is no separate
    # (sigma, L, nu) to fit for WTD.
    rng = np.random.default_rng(2)
    coords = rng.uniform(0.0, 50.0, (40, 2))
    prior = GaussianPrior(sigma=0.5, length_km=12.0, nu=1.5)
    C_head = prior.cov(coords)

    # draw head anomalies, convert each realisation to a DTW anomaly, and compare sample covariances
    Lc = np.linalg.cholesky(C_head + 1e-10 * np.eye(len(coords)))
    dh = (Lc @ rng.normal(size=(len(coords), 20000))).T          # (n_draw, n_cell)
    dd = dtw_anomaly_from_head_anomaly(dh)

    cov_head = np.cov(dh, rowvar=False)
    cov_dtw = np.cov(dd, rowvar=False)
    assert np.allclose(cov_head, cov_dtw)                        # EXACT: (-1)(-1) = 1
    assert np.allclose(np.var(dh, axis=0), np.var(dd, axis=0))   # identical variance too
    # the analytic statement, checked by the guard the configuration code should call
    assert_anomaly_covariance_identity(C_head, C_head)


def test_covariance_identity_guard_rejects_two_different_prior_models():
    coords = np.random.default_rng(3).uniform(0.0, 50.0, (25, 2))
    c_head = GaussianPrior(sigma=0.5, length_km=12.0, nu=1.5).cov(coords)
    c_dtw_wrong = GaussianPrior(sigma=0.5, length_km=6.0, nu=0.5).cov(coords)   # a separate "WTD" fit
    assert _raises(lambda: assert_anomaly_covariance_identity(c_head, c_dtw_wrong))
    assert _raises(lambda: assert_anomaly_covariance_identity(c_head, c_head[:5, :5]))


# --- storage -> head, with specific-yield uncertainty ----------------------------------------------

def test_storage_to_head_round_trips_and_rejects_storativity():
    ds = np.array([0.0, 0.03, -0.06, 0.15])           # m of water
    sy = 0.15
    h, sig = water_table_head_from_storage(ds, sy)
    assert np.allclose(h, ds / sy)
    assert sig is None
    assert np.allclose(storage_from_water_table_head(h, sy), ds)

    # a confined storativity (S ~ 1e-4) is NOT a specific yield; the resulting "water table" would be
    # ~1000x too large, so it is refused rather than computed.
    assert _raises(lambda: water_table_head_from_storage(ds, 1e-4))
    assert _raises(lambda: water_table_head_from_storage(ds, 0.9))
    assert _raises(lambda: storage_from_water_table_head(h, 1e-4))


def test_specific_yield_uncertainty_propagates_into_the_diagnosed_head():
    # relative sigma in head == relative sigma in Sy, and it scales with the size of the head change
    ds = np.array([0.05, 0.10])
    sy, sy_sig = 0.20, 0.05
    h, sig = water_table_head_from_storage(ds, sy, specific_yield_sigma=sy_sig)
    assert np.allclose(sig / np.abs(h), sy_sig / sy)
    assert sig[1] > sig[0]                             # bigger storage change -> bigger head error
    # a zero storage anomaly carries no Sy-induced head error
    h0, sig0 = water_table_head_from_storage(0.0, sy, specific_yield_sigma=sy_sig)
    assert np.allclose(sig0, 0.0)


# --- pore pressure: named assumptions --------------------------------------------------------------

def test_hydrostatic_pore_pressure_is_zero_above_the_water_table_and_linear_below():
    h_wt = 100.0
    z = np.array([102.0, 100.0, 99.0, 95.0])
    u = pore_pressure_hydrostatic_below_water_table(h_wt, z)
    assert u[0] == 0.0 and u[1] == 0.0                 # at/above the table: no positive pore pressure
    assert np.isclose(u[2], RHO_W * G * 1.0)
    assert np.isclose(u[3], RHO_W * G * 5.0)
    assert np.isclose(pore_pressure_head_m(u[3]), 5.0)


def test_slope_parallel_pore_pressure_is_lower_than_hydrostatic_and_reduces_to_it_at_zero_slope():
    h_wt, z = 100.0, 97.0
    u_hydro = pore_pressure_hydrostatic_below_water_table(h_wt, z)
    assert np.isclose(pore_pressure_slope_parallel(h_wt, z, 0.0), u_hydro)
    u30 = pore_pressure_slope_parallel(h_wt, z, np.deg2rad(30.0))
    assert np.isclose(u30 / u_hydro, np.cos(np.deg2rad(30.0)) ** 2)
    assert u30 < u_hydro                               # the difference a factor of safety consumes
    assert np.isclose(u30 / u_hydro, 0.75)


def test_hydraulic_head_at_depth_equals_the_water_table_only_at_zero_gauge_pressure():
    # H = z + p/(rho_w g). At the phreatic surface p = 0 so H = h_wt; deeper, a confined interval can
    # carry ANY head, which is exactly why a screened well is not automatically a water-table well.
    z_screen = 60.0
    assert np.isclose(hydraulic_head_from_pressure(z_screen, 0.0), z_screen)
    confined = hydraulic_head_from_pressure(z_screen, RHO_W * G * 45.0)
    assert np.isclose(confined, 105.0)                 # head 45 m above the screen: potentiometric
    # if the land surface is at 100 m, this well's "level" implies a head ABOVE ground -- artesian,
    # and unambiguously not a phreatic water table
    assert confined > 100.0


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("all hydro-state tests passed")
