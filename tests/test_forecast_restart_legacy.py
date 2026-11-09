"""Forecast reinitialisation record (review ladder L2, issue #298).

Pins what the legacy forecast path does today: no state argument, SWE starts at zero on every
call, theta_ref is the post-step state, the two snow models disagree. The segmented-run
equivalence test is ``xfail(strict=True)`` and flips when #234 carries SWE across calls.
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from src.models import forecast as fc
from src.models import soil_moisture as sm
from src.models import water_budget as wb


def _forcing(days, tmean, precip=10.0):
    times = np.arange(np.datetime64("2026-01-01"), np.datetime64("2026-01-01") + np.timedelta64(days, "D"))
    return fc.ForecastForcing(times=times, precip_mm=np.full((days, 1, 1), precip), pet_mm=np.full((days, 1, 1), 0.5),
                              dt_days=1.0, tmean_c=np.asarray(tmean, float).reshape(days, 1, 1), source="synthetic")


def test_no_state_argument_exists():
    assert not any(k in inspect.signature(fc.forecast_soil_state).parameters for k in ("state", "swe0", "prior_state", "S0", "h0"))
    assert not any(k in inspect.signature(wb.coupled_water_budget).parameters for k in ("S0", "theta0", "h0", "state"))


def test_theta_ref_is_the_post_step_state():
    out = fc.forecast_soil_state(_forcing(10, np.full(10, 8.0), precip=20.0), 0.10, 0.28, 0.45, vs30_base=300.0, wt_depth0_m=3.0)
    assert float(out.theta[0, 0, 0]) != pytest.approx(0.28, abs=1e-6)     # the reference is theta after day 1, not the analysis
    assert float(out.dvv_high[0, 0, 0]) == 0.0


def test_two_snow_models_disagree_on_one_winter():
    days = 120
    t = -4.0 + 10.0 * np.sin(np.linspace(0, np.pi, days)) ** 2 - 2.0
    liq_fc = fc.liquid_input(_forcing(days, t, precip=6.0))[:, 0, 0]
    W, _ = sm.snowmelt_liquid_input(np.full((days, 1, 1), 6.0), t.reshape(days, 1, 1), np.ones(days))
    liq_sm = np.asarray(W, float).reshape(days, -1)[:, 0]
    assert np.sum(np.abs(liq_fc - liq_sm) > 1e-9) > 30                     # different thresholds, different water


@pytest.mark.xfail(strict=True, reason="SWE restarts at zero on every call (forecast.py:123); flips when #234 carries the snow state")
def test_segmented_snow_run_equals_continuous_run():
    t = np.r_[np.full(20, -5.0), np.full(10, 6.0)]
    full = fc.liquid_input(_forcing(30, t))[:, 0, 0]
    seg2 = fc.liquid_input(_forcing(20, t[10:]))[:, 0, 0]
    np.testing.assert_allclose(full[20:], seg2[10:])
