"""Tests for the soil-moisture state module (issue #20).

Runs standalone (`python -m tests.test_soil_moisture`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.models.soil_moisture import (
    SoilMoistureInputs,
    estimate_soil_moisture,
    saxton_rawls_envelope,
    thornthwaite_mather_wetness,
    total_water_bucket,
)


def test_total_water_bucket_spans_full_range_and_drains():
    wp = np.array([[0.10]]); fc = np.array([[0.25]]); sat = np.array([[0.45]])
    # a very wet month then dry months (with ET)
    P = np.array([300.0, 0, 0, 0, 0, 0])[:, None, None]
    PET = np.array([10.0, 60, 60, 60, 60, 60])[:, None, None]
    th = total_water_bucket(P, PET, wp, fc, sat, root_depth_m=1.0)
    assert np.all(th >= wp - 1e-6) and np.all(th <= sat + 1e-6)   # within physical envelope
    assert th[0, 0, 0] > fc[0, 0]                                  # wet month exceeds field capacity
    assert th[-1, 0, 0] < th[0, 0, 0]                             # drains/dries over time


def test_envelope_ordering_and_ranges():
    # A spread of textures: sand, loam, clay.
    sand = np.array([85.0, 40.0, 15.0])
    clay = np.array([5.0, 20.0, 50.0])
    env = saxton_rawls_envelope(sand, clay)
    wp, fc, sat = env["theta_wp"], env["theta_fc"], env["theta_sat"]
    # Physical ordering everywhere.
    assert np.all(wp < fc) and np.all(fc < sat)
    # Plausible volumetric ranges (m³/m³).
    assert np.all((wp > 0.01) & (wp < 0.35))
    assert np.all((fc > 0.05) & (fc < 0.5))
    assert np.all((sat > 0.35) & (sat < 0.75))
    # Clay holds more water than sand at field capacity.
    assert fc[2] > fc[0]
    # Ksat is positive and drains faster in sand than clay.
    assert np.all(env["ksat"] > 0) and env["ksat"][0] > env["ksat"][2]


def test_bucket_responds_to_forcing():
    awc = np.full((1, 1), 100.0)
    wet = thornthwaite_mather_wetness(np.full((8, 1, 1), 160.0), np.full((8, 1, 1), 20.0), awc)
    dry = thornthwaite_mather_wetness(np.full((8, 1, 1), 3.0), np.full((8, 1, 1), 130.0), awc)
    assert wet[-1, 0, 0] > 0.9          # sustained surplus → near-full store
    assert dry[-1, 0, 0] < 0.1          # sustained deficit → near-empty store
    assert np.all((wet >= 0) & (wet <= 1)) and np.all((dry >= 0) & (dry <= 1))


def test_theta_stays_within_envelope():
    wp = np.array([[0.10, 0.12]])
    fc = np.array([[0.28, 0.30]])
    sat = np.array([[0.46, 0.48]])
    # Wetness sweeping 0→1 (plus an out-of-range value to confirm clipping).
    w = np.array([[[0.0, 0.5]], [[1.0, 1.5]]])  # (time=2, y=1, x=2)
    wp_b = np.broadcast_to(wp, (1, 2))
    fc_b = np.broadcast_to(fc, (1, 2))
    sat_b = np.broadcast_to(sat, (1, 2))
    theta, std = estimate_soil_moisture(
        SoilMoistureInputs(field_capacity=fc_b, wilting_point=wp_b, porosity=sat_b, dynamic_driver=w)
    )
    assert theta.shape == (2, 1, 2)
    assert np.all(theta >= wp_b - 1e-6)             # never below wilting point
    assert np.all(theta <= sat_b + 1e-6)            # never above porosity
    # w=0 → wilting point; w≥1 → capped at field capacity (≤ porosity).
    assert np.allclose(theta[0, 0, 0], wp[0, 0], atol=1e-6)
    assert theta[1, 0, 0] <= fc[0, 0] + 1e-6
    assert np.all(std > 0)


if __name__ == "__main__":
    test_envelope_ordering_and_ranges()
    test_total_water_bucket_spans_full_range_and_drains()
    test_bucket_responds_to_forcing()
    test_theta_stays_within_envelope()
    print("all soil-moisture tests passed")
