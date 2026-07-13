"""Tests for the rainfall-driven soil-state forecast (AI weather -> theta / GWL / Vs).

Runs standalone (`python -m tests.test_forecast`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.data.fetch_earth2studio import (
    PRECIP_CAPABLE,
    PRECIP_ZERO_MODELS,
    assert_precipitation_is_real,
)
from src.models.forecast import ForecastForcing, forecast_soil_state, liquid_input
from src.models.water_budget import SPECIFIC_YIELD, coupled_water_budget

ENV = dict(theta_wp=0.10, theta_fc=0.25, theta_sat=0.45)


def _forcing(precip, tmean=None, dt_days=1.0):
    n = len(precip)
    t = np.arange("2024-12-01", np.datetime64("2024-12-01") + n, dtype="datetime64[D]")
    return ForecastForcing(times=t, precip_mm=np.asarray(precip, float).reshape(n, 1),
                           pet_mm=np.full((n, 1), 1.0),
                           tmean_c=None if tmean is None else np.asarray(tmean, float).reshape(n, 1),
                           dt_days=dt_days, source="test")


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def test_graphcast_operational_zeros_are_refused():
    # GraphCastOperational emits tp06 as a zero-filled placeholder. If that ever reaches the water
    # budget we silently forecast a drought. It must be refused BY NAME, and an all-zero field must
    # be refused regardless of which model produced it.
    assert "GraphCastOperational" in PRECIP_ZERO_MODELS
    assert "GraphCastOperational" not in PRECIP_CAPABLE
    assert _raises(lambda: assert_precipitation_is_real(np.ones((4, 3)), "GraphCastOperational"))
    assert _raises(lambda: assert_precipitation_is_real(np.zeros((4, 3)), "GraphCastSmall"))
    assert _raises(lambda: assert_precipitation_is_real(np.full((4, 3), np.nan), "GraphCastSmall"))
    # a real forecast passes and returns its total
    total = assert_precipitation_is_real(np.full((4, 3), 5.0), "GraphCastSmall")
    assert abs(total - 60.0) < 1e-9


def test_fuxi_is_the_15_day_precip_model():
    # FuXi is the only other earth2studio prognostic that natively emits tp06, at 0.25 deg, and is a
    # cascade trained for 5/10/15-day leads -- so it, not GraphCast, is the +1..+15 model.
    from src.data.fetch_earth2studio import MAX_LEAD_DAYS, PREFERRED_MODEL
    assert PREFERRED_MODEL == "FuXi"
    assert "FuXi" in PRECIP_CAPABLE
    assert MAX_LEAD_DAYS["FuXi"] == 15 and MAX_LEAD_DAYS["GraphCastSmall"] == 10
    assert assert_precipitation_is_real(np.full((4, 3), 2.0), "FuXi") > 0


def test_daily_step_does_not_drain_30x_too_fast():
    # The per-month rate parameters must be converted to the step. A daily run driven with mm/day
    # must NOT behave like a monthly run driven with mm/month.
    monthly = coupled_water_budget(np.array([[120.0]]), np.array([[30.0]]), **ENV)
    daily = coupled_water_budget(np.full((30, 1), 4.0), np.full((30, 1), 1.0), dt_days=1.0, **ENV)
    # same total water in, both physical: theta stays inside the envelope and the table does not blow up
    for r in (monthly, daily):
        assert np.all(r.theta >= ENV["theta_wp"] - 1e-9) and np.all(r.theta <= ENV["theta_sat"] + 1e-9)
    assert np.isfinite(daily.wt_depth_m).all()
    # the daily run resolves drainage properly, so it recharges rather than fabricating runoff
    assert daily.recharge_mm.sum() > 0.0


def test_storm_concentration_changes_the_answer():
    # The whole point of a daily forecast: the same water, concentrated, generates saturation-excess
    # runoff and a theta spike that a uniform (monthly-mean-like) forcing cannot produce.
    n, total = 30, 400.0
    uniform = coupled_water_budget(np.full((n, 1), total / n), np.full((n, 1), 2.0),
                                   dt_days=1.0, **ENV)
    storm_p = np.zeros((n, 1)); storm_p[10:13, 0] = total / 3.0
    storm = coupled_water_budget(storm_p, np.full((n, 1), 2.0), dt_days=1.0, **ENV)
    assert storm.runoff_mm.sum() > uniform.runoff_mm.sum()      # events generate runoff
    assert storm.theta.max() > uniform.theta.max()              # and a wetness spike


def test_snow_defers_the_response_until_melt():
    # A cold-season forecast over the Cascades is snow-dominated. Treating snowfall as rain would
    # fabricate an immediate theta/Vs response that physically waits for melt.
    p = [20.0] * 10
    cold = liquid_input(_forcing(p, tmean=[-5.0] * 10))
    warm = liquid_input(_forcing(p, tmean=[10.0] * 10))
    assert cold.sum() < 1e-9                       # all snow, nothing reaches the soil yet
    assert abs(warm.sum() - 200.0) < 1e-6          # all rain
    # then a warm spell melts the accumulated pack -> delayed liquid input
    melt = liquid_input(_forcing([20.0] * 5 + [0.0] * 5, tmean=[-5.0] * 5 + [8.0] * 5))
    assert melt[:5].sum() < 1e-9 and melt[5:].sum() > 0.0


def test_forecast_storm_response_has_the_right_physics():
    n = 10
    p = np.zeros(n); p[3:6] = 60.0                              # a 3-day atmospheric river
    f = _forcing(p, tmean=[8.0] * n)
    fc = forecast_soil_state(f, vs30_base=400.0, wt_depth0_m=5.0,
                             sand_pct=40.0, clay_pct=20.0, **ENV)
    assert fc.theta.shape == (n, 1) and fc.vs30.shape == (n, 1)

    # theta responds within days, then drains back down
    assert fc.theta.max() - fc.theta[0, 0] > 0.02
    assert fc.theta[-1, 0] < fc.theta.max()

    # the table RISES with recharge (h += R/S_y -- fast), it does not sit still: the ~6-month tau is
    # the RECESSION timescale, not the rise. Rise must match the reservoir arithmetic.
    rise = 5.0 - fc.wt_depth_m.min()
    assert rise > 0.5                                           # a real storm lifts the table
    # == R/S_y. Reference the actual default, not a hard-coded 0.12: S_y is CALIBRATED
    # (D7) against the well seasonal amplitude, so pinning it here would break on recalibration.
    assert abs(rise - fc.recharge_mm.sum() / 1000.0 / SPECIFIC_YIELD) < 0.05
    # and it recedes only slowly: still well above baseline at the end of the window
    assert (5.0 - fc.wt_depth_m[-1, 0]) > 0.8 * rise

    # wetting softens the ground: Vs falls below baseline at the wettest moment
    assert fc.vs30.min() < 400.0
    # the shallow (moisture) band carries the storm; the deep (head) band barely moves -- this is why
    # dv/v is the right observable for a storm-scale forecast. Dominance is >1 order of magnitude.
    assert abs(fc.dvv_high).max() > 10.0 * abs(fc.dvv_low).max()
    # ...and Vs30 itself barely moves, because the root zone is only 1/30 of the averaging depth:
    # dv/v sees the storm, Vs30 mostly does not.
    assert abs(fc.vs30_frac).max() < 0.1 * abs(fc.dvv_high).max()


if __name__ == "__main__":
    test_graphcast_operational_zeros_are_refused()
    test_fuxi_is_the_15_day_precip_model()
    test_daily_step_does_not_drain_30x_too_fast()
    test_storm_concentration_changes_the_answer()
    test_snow_defers_the_response_until_melt()
    test_forecast_storm_response_has_the_right_physics()
    print("all forecast tests passed")
