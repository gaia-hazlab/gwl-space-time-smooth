"""Legacy store-model ledger (review ladder L1, issue #297).

Pins the executed combined root-zone + aquifer residuals of ``coupled_water_budget`` at the
reviewed revision. The combined-conservation assertion is ``xfail(strict=True)``: it fails today
because capillary rise is credited to the root zone and never debited from the aquifer, and it
must start passing (and this marker be removed) when #232 slice (a) lands.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.models import water_budget as wb

WP, FC, SAT, ROOT_M, SY = 0.10, 0.28, 0.45, 1.0, 0.30
F32_BOUND_MM = float(np.spacing(np.float32(SAT))) * ROOT_M * 1000.0


def _day1_residual(dtw0, cap_max_mm, days=1, liquid=0.0, hand_m=None):
    nt = days
    liq = np.full((nt, 1, 1), liquid)
    res = wb.coupled_water_budget(liq, np.zeros((nt, 1, 1)), WP, FC, SAT, root_depth_m=ROOT_M,
                                  specific_yield=SY, wt_depth0_m=dtw0, init="wp", dt_days=1.0,
                                  cap_max_mm=cap_max_mm,
                                  hand_m=None if hand_m is None else np.full((1, 1), hand_m))
    s = float(res.theta[0, 0, 0]) * ROOT_M * 1000.0 - WP * ROOT_M * 1000.0
    g = (dtw0 - float(res.wt_depth_m[0, 0, 0])) * SY * 1000.0
    out = float(res.runoff_mm[0, 0, 0] + res.interflow_mm[0, 0, 0] + res.baseflow_mm[0, 0, 0] + res.aet_mm[0, 0, 0])
    return s + g + out - liquid, res


def test_primary_nonoverlapping_case_creates_water_with_capillary_on():
    resid, _ = _day1_residual(1.5, wb.CAP_MAX_MM)
    assert resid == pytest.approx(30.0 / wb.DAYS_PER_MONTH * 0.25, abs=1e-3)   # +0.2464 mm created


def test_capillary_off_closes_within_float32_bound():
    for dtw0 in (0.5, 1.5, 2.5):
        resid, _ = _day1_residual(dtw0, 0.0)
        assert abs(resid) <= 2 * F32_BOUND_MM


def test_negative_control_below_fringe_closes_either_way():
    for cap in (wb.CAP_MAX_MM, 0.0):
        resid, _ = _day1_residual(2.5, cap)
        assert abs(resid) <= 2 * F32_BOUND_MM


def test_overlap_case_matches_analytic_capillary_credit():
    resid, _ = _day1_residual(0.5, wb.CAP_MAX_MM)
    assert resid == pytest.approx(30.0 / wb.DAYS_PER_MONTH * 0.75, abs=1e-3)


def test_valley_cell_without_sink_rises_monotonically_from_rain_alone():
    _, res = _day1_residual(2.0, 0.0, days=365, liquid=5.0, hand_m=0.0)
    wt = res.wt_depth_m[:, 0, 0].astype("float64")
    assert np.all(np.diff(wt) <= 1e-6) and wt[-1] < 0.0          # table above the surface, never drained
    assert float(res.baseflow_mm.sum()) == 0.0


def test_valley_cell_rises_from_manufactured_water_without_rain():
    # DTW 2.0 m is the fringe edge (zero flux); at 1.5 m the created water stays in the root zone
    # (theta rises, nothing drains); at 0.5 m it exceeds field capacity, drains, and lifts a table
    # that has no sink. Zero rain, zero PET throughout.
    _, r15 = _day1_residual(1.5, wb.CAP_MAX_MM, days=365, liquid=0.0, hand_m=0.0)
    assert float(r15.cap_rise_mm.sum()) > 70.0 and float(r15.recharge_mm.sum()) == 0.0
    assert float(r15.theta[-1, 0, 0]) > WP + 0.07
    _, r05 = _day1_residual(0.5, wb.CAP_MAX_MM, days=365, liquid=0.0, hand_m=0.0)
    wt = r05.wt_depth_m[:, 0, 0].astype("float64")
    assert float(r05.recharge_mm.sum()) > 0.0 and wt[-1] < wt[0] and float(r05.baseflow_mm.sum()) == 0.0


@pytest.mark.xfail(strict=True, reason="capillary rise is credited to the root zone and not debited from the aquifer (#232 a); flips when the ledger is repaired")
def test_combined_ledger_closes_with_capillary_on():
    resid, _ = _day1_residual(1.5, wb.CAP_MAX_MM)
    assert abs(resid) <= 2 * F32_BOUND_MM
