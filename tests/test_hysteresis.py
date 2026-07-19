"""Tests for the capillary-hysteresis retention model (src/models/hysteresis.py, #120)."""
import numpy as np

from src.models.hysteresis import (
    hysteretic_suction,
    hysteretic_vs_loop,
    vg_suction,
    vs_from_suction,
)

ALPHA_D, N = 0.05, 1.6          # a silty-loam-ish bounding pair
THETA_R, PHI = 0.06, 0.42


def _wet_then_dry(n_up=40, n_dn=40, se_lo=0.30, se_hi=0.85):
    """A saturation path that wets from se_lo to se_hi then dries back — visits mid-values twice."""
    up = np.linspace(se_lo, se_hi, n_up)
    dn = np.linspace(se_hi, se_lo, n_dn)
    return np.concatenate([up, dn])


def test_drying_bound_holds_more_suction_than_wetting_at_equal_saturation():
    # Kool-Parker: alpha_w = 2 alpha_d, so at the SAME Se the drying suction exceeds the wetting one.
    se = np.linspace(0.1, 0.9, 25)
    hd = vg_suction(se, ALPHA_D, N)
    hw = vg_suction(se, 2.0 * ALPHA_D, N)
    assert np.all(hd > hw), "drying bound must lie above the wetting bound in suction"


def test_the_loop_opens_on_a_wet_then_dry_path():
    se = _wet_then_dry()
    h, _ = hysteretic_suction(se, ALPHA_D, N, start="wetting")
    # a mid saturation visited once on the wetting limb and once on the drying limb
    target = 0.55
    i_wet = int(np.argmin(np.abs(se[: len(se) // 2] - target)))
    j_dry = len(se) // 2 + int(np.argmin(np.abs(se[len(se) // 2:] - target)))
    assert h[j_dry] > h[i_wet] + 1e-3, "at equal Se, the drying limb must carry more suction (open loop)"
    # every point stays between the two bounding curves
    hd = vg_suction(se, ALPHA_D, N)
    hw = vg_suction(se, 2.0 * ALPHA_D, N)
    assert np.all(h <= hd + 1e-6) and np.all(h >= hw - 1e-6), "scanning curves must stay within bounds"


def test_velocity_shows_the_same_loop_the_observable():
    # The point of the module: Vs(theta) is a loop, and drying is STIFFER (higher Vs) than wetting.
    theta = THETA_R + _wet_then_dry() * (PHI - THETA_R)
    out = hysteretic_vs_loop(theta, THETA_R, PHI, ALPHA_D, N, start="wetting")
    half = len(theta) // 2
    target_theta = THETA_R + 0.55 * (PHI - THETA_R)
    i = int(np.argmin(np.abs(theta[:half] - target_theta)))
    j = half + int(np.argmin(np.abs(theta[half:] - target_theta)))
    assert out["vs"][j] > out["vs"][i], "drying limb must be stiffer (higher Vs) at equal moisture"
    # the hysteretic Vs departs from the single-valued reference somewhere on the loop
    assert np.nanmax(np.abs(out["vs"] - out["vs_single"])) > 1.0


def test_no_hysteresis_when_ratio_is_one():
    # ratio=1 collapses the two bounds -> single-valued -> the loop area vanishes.
    se = _wet_then_dry()
    h, _ = hysteretic_suction(se, ALPHA_D, N, wetting_ratio=1.0, start="wetting")
    single = vg_suction(se, ALPHA_D, N)
    assert np.allclose(h, single, atol=1e-6), "ratio=1 must reproduce the single-valued curve"


def test_reversal_resets_the_memory_anchor():
    # A wet -> dry -> wet path creates two reversals; the returned states record them.
    se = np.concatenate([np.linspace(0.3, 0.8, 20), np.linspace(0.8, 0.4, 20), np.linspace(0.4, 0.7, 20)])
    _, states = hysteretic_suction(se, ALPHA_D, N, start="wetting")
    dirs = [s.direction for s in states]
    assert "w" in dirs and "d" in dirs, "both directions must appear"
    # direction actually flips at the turning points
    flips = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
    assert flips >= 2, "at least two reversals expected on a wet-dry-wet path"


def test_trajectory_field_carries_memory_over_the_integrated_path():
    # The vectorised stepper the water budget uses: a wet-then-dry path must give DIFFERENT suction at
    # the same Se depending on which limb it is on — path memory, carried per cell.
    from src.models.hysteresis import hysteretic_suction_field
    se = _wet_then_dry()[:, None]                     # (T, 1 cell)
    h = hysteretic_suction_field(se, ALPHA_D, N, start="wetting")
    half = len(se) // 2
    i = int(np.argmin(np.abs(se[:half, 0] - 0.55)))
    j = half + int(np.argmin(np.abs(se[half:, 0] - 0.55)))
    assert h[j, 0] > h[i, 0] + 1e-3
    # vectorises over cells independently: one cell wets-then-dries, the other dries-then-wets, so at
    # a given time they sit on opposite limbs and their suctions differ.
    c0 = np.concatenate([np.linspace(0.30, 0.85, 40), np.linspace(0.85, 0.30, 40)])
    c1 = np.concatenate([np.linspace(0.85, 0.30, 40), np.linspace(0.30, 0.85, 40)])
    two = np.stack([c0, c1], axis=1)                  # (T, 2)
    hh = hysteretic_suction_field(two, ALPHA_D, N, start="drying")
    assert hh.shape == two.shape and np.nanmax(np.abs(hh[:, 0] - hh[:, 1])) > 1e-3


def test_forecast_dvv_is_path_dependent_when_hysteresis_on():
    # End-to-end: through forecast_soil_state, hysteresis makes the vadose dv/v differ from the
    # single-valued map on a wet-then-dry storm (same water budget, different observable).
    from src.models.forecast import ForecastForcing, forecast_soil_state
    n = 80
    rain = np.zeros(n); rain[5:25] = 12.0             # a storm: wet up then dry out
    t = np.arange("2025-11-01", np.datetime64("2025-11-01") + n, dtype="datetime64[D]")
    kw = dict(theta_wp=0.10, theta_fc=0.28, theta_sat=0.42, vs30_base=350.0, wt_depth0_m=5.0,
              root_depth_m=1.0)
    f = ForecastForcing(times=t, precip_mm=rain, pet_mm=np.full(n, 1.5), dt_days=1.0, source="test")
    hy = forecast_soil_state(f, hysteresis=True, **kw)
    sv = forecast_soil_state(f, hysteresis=False, **kw)
    assert hy.dvv_high.shape == sv.dvv_high.shape
    assert np.nanmax(np.abs(hy.dvv_high - sv.dvv_high)) > 1e-4, "hysteresis must change the vadose dv/v"
    # sanity preserved: vadose band still dominates the saturated band
    assert np.abs(hy.dvv_high).max() > 5.0 * np.abs(hy.dvv_low).max()


def test_invalid_start_fails_fast():
    # An unrecognised start must RAISE, not silently land on the wetting limb.
    from src.models.hysteresis import hysteretic_suction_field

    def _raises(fn):
        try:
            fn(); return False
        except ValueError:
            return True
    assert _raises(lambda: hysteretic_suction(_wet_then_dry(), ALPHA_D, N, start="up"))
    assert _raises(lambda: hysteretic_suction_field(_wet_then_dry()[:, None], ALPHA_D, N, start="x"))


if __name__ == "__main__":
    test_drying_bound_holds_more_suction_than_wetting_at_equal_saturation()
    test_the_loop_opens_on_a_wet_then_dry_path()
    test_velocity_shows_the_same_loop_the_observable()
    test_no_hysteresis_when_ratio_is_one()
    test_reversal_resets_the_memory_anchor()
    test_trajectory_field_carries_memory_over_the_integrated_path()
    test_forecast_dvv_is_path_dependent_when_hysteresis_on()
    test_invalid_start_fails_fast()
    print("all hysteresis tests passed")
