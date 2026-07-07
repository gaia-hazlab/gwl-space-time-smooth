"""Tests for the coupled water budget (issues #43 recharge/capillary, #44 runoff/lateral flow).

Runs standalone (`python -m tests.test_water_budget`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.models.water_budget import (
    accumulate_runoff,
    coupled_water_budget,
    topmodel_watertable,
)

_WP, _FC, _SAT = np.array([[0.10]]), np.array([[0.28]]), np.array([[0.45]])


def _forcing(nt=48, p0=60.0, pet0=50.0):
    t = np.arange(nt)
    P = np.clip(p0 + 50 * np.sin(2 * np.pi * (t - 2) / 12), 0, None)[:, None, None]
    PET = np.clip(pet0 + 45 * np.sin(2 * np.pi * t / 12), 0, None)[:, None, None]
    return P, PET


def test_mass_is_conserved_each_step():
    P, PET = _forcing()
    wb = coupled_water_budget(P, PET, _WP, _FC, _SAT, root_depth_m=1.0, wt_depth0_m=5.0)
    z = 1000.0
    S = wb.theta[:, 0, 0].astype("float64") * z
    dS = np.diff(S)
    flux = (wb.cap_rise_mm + P - wb.runoff_mm - wb.aet_mm - wb.recharge_mm)[1:, 0, 0].astype("float64")
    assert np.max(np.abs(dS - flux)) < 1e-2                 # dS = cap + I - runoff - aet - recharge


def test_theta_within_envelope():
    P, PET = _forcing()
    wb = coupled_water_budget(P, PET, _WP, _FC, _SAT, root_depth_m=1.0)
    assert np.all(wb.theta >= _WP[0, 0] - 1e-6) and np.all(wb.theta <= _SAT[0, 0] + 1e-6)


def test_recharge_raises_the_water_table():
    P, PET = _forcing(p0=90.0)                              # wet forcing -> net recharge
    wb = coupled_water_budget(P, PET, _WP, _FC, _SAT, wt_depth0_m=5.0)
    assert wb.recharge_mm.sum() > 0
    assert wb.wt_depth_m.min() < 5.0                        # table rises above its start depth


def test_capillary_rise_activates_for_a_shallow_table():
    # A shallow table (0.5 m) within the root-zone + fringe reach should pull water up in a dry column.
    P = np.zeros((24, 1, 1)); PET = np.full((24, 1, 1), 80.0)
    deep = coupled_water_budget(P, PET, _WP, _FC, _SAT, wt_depth0_m=8.0, init="wp")
    shallow = coupled_water_budget(P, PET, _WP, _FC, _SAT, wt_depth0_m=0.5, init="wp")
    assert shallow.cap_rise_mm.sum() > 0                    # capillary rise happens
    assert deep.cap_rise_mm.sum() == 0                      # not when the table is deep
    assert shallow.theta.mean() >= deep.theta.mean()        # shallow table keeps the root zone wetter


def test_saturation_excess_runoff():
    # Huge input with a shallow table: the column fills and sheds saturation-excess runoff.
    P = np.full((12, 1, 1), 400.0); PET = np.zeros((12, 1, 1))
    wb = coupled_water_budget(P, PET, _WP, _FC, _SAT, wt_depth0_m=1.0)
    assert wb.runoff_mm.sum() > 0
    assert np.all(wb.theta <= _SAT[0, 0] + 1e-6)            # never exceeds porosity


def test_topmodel_valleys_are_wetter_than_ridges():
    twi = np.array([[3.0, 7.0, 12.0]])                     # ridge -> slope -> valley
    d = topmodel_watertable(5.0, twi)
    assert d[0, 2] < d[0, 1] < d[0, 0]                     # higher TWI -> shallower table
    assert np.all(d >= 0)


def test_runoff_routing_concentrates_downhill():
    routed = accumulate_runoff(np.array([[10.0, 10.0]]), np.array([[1.0, 100.0]]))
    assert routed[0, 1] > routed[0, 0]                     # high-accumulation cell gets more


if __name__ == "__main__":
    test_mass_is_conserved_each_step()
    test_theta_within_envelope()
    test_recharge_raises_the_water_table()
    test_capillary_rise_activates_for_a_shallow_table()
    test_saturation_excess_runoff()
    test_topmodel_valleys_are_wetter_than_ridges()
    test_runoff_routing_concentrates_downhill()
    print("all water-budget tests passed")
