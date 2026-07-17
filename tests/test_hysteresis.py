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


if __name__ == "__main__":
    test_drying_bound_holds_more_suction_than_wetting_at_equal_saturation()
    test_the_loop_opens_on_a_wet_then_dry_path()
    test_velocity_shows_the_same_loop_the_observable()
    test_no_hysteresis_when_ratio_is_one()
    test_reversal_resets_the_memory_anchor()
    print("all hysteresis tests passed")
