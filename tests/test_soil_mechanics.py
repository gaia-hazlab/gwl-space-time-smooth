"""Tests for the landslide infinite-slope factor of safety (src/models/soil_mechanics.py, #128)."""
import numpy as np

from src.models.soil_mechanics import (
    PHI_DEG,
    MechanicsInputs,
    colluvium_thickness,
    estimate_mechanics,
    infinite_slope_factor_of_safety,
)


def test_dry_cohesionless_reduces_to_tanphi_over_tanslope():
    # The classic infinite-slope limit: cohesionless + dry table -> FS = tan(phi)/tan(slope).
    t = 0.5
    ss = infinite_slope_factor_of_safety(t, wt_depth_m=10.0, soil_depth_m=1.0,
                                         root_cohesion_pa=0.0, soil_cohesion_pa=0.0, phi_deg=PHI_DEG)
    assert abs(float(ss.fs) - np.tan(np.radians(PHI_DEG)) / t) < 1e-6


def test_rising_water_table_lowers_fs():
    # A shallower water table (more pore pressure on the failure plane) must reduce FS.
    kw = dict(slope_tan=0.6, soil_depth_m=1.5, root_cohesion_pa=2000.0, phi_deg=PHI_DEG)
    dry = infinite_slope_factor_of_safety(wt_depth_m=5.0, **kw).fs      # table below the soil
    wet = infinite_slope_factor_of_safety(wt_depth_m=0.0, **kw).fs      # table at the surface
    assert float(wet) < float(dry)
    # and the fully-wet case reports the column as saturated
    assert abs(float(infinite_slope_factor_of_safety(wt_depth_m=0.0, **kw).sat_fraction) - 1.0) < 1e-9


def test_steeper_slope_lowers_fs():
    # Dry, fixed depth: steeper ground is less stable.
    kw = dict(wt_depth_m=10.0, soil_depth_m=1.0, root_cohesion_pa=1000.0, phi_deg=PHI_DEG)
    gentle = infinite_slope_factor_of_safety(slope_tan=np.tan(np.radians(15.0)), **kw).fs
    steep = infinite_slope_factor_of_safety(slope_tan=np.tan(np.radians(40.0)), **kw).fs
    assert float(steep) < float(gentle)


def test_root_cohesion_raises_fs_and_can_prevent_failure():
    kw = dict(slope_tan=np.tan(np.radians(38.0)), wt_depth_m=0.0, soil_depth_m=1.2, phi_deg=PHI_DEG)
    bare = infinite_slope_factor_of_safety(root_cohesion_pa=0.0, **kw).fs      # steep, saturated, bare
    rooted = infinite_slope_factor_of_safety(root_cohesion_pa=8000.0, **kw).fs
    assert float(bare) < 1.0 < float(rooted), "bare steep-saturated fails; roots stabilise it"


def test_failure_probability_is_bounded_and_tracks_fs():
    t = np.tan(np.radians(38.0))
    depth = np.full(5, 1.2)
    dtw = np.array([3.0, 1.2, 0.8, 0.4, 0.0])                            # drying -> wetting
    ss = infinite_slope_factor_of_safety(np.full(5, t), dtw, soil_depth_m=depth,
                                         root_cohesion_pa=1500.0, phi_deg=PHI_DEG)
    assert np.all((ss.p_failure >= 0.0) & (ss.p_failure <= 1.0))
    assert np.all(np.diff(ss.fs) <= 1e-9)                               # FS falls as the table rises
    assert ss.p_failure[-1] > ss.p_failure[0]                          # failure prob rises with wetness


def test_colluvium_thinner_on_steep_slopes():
    z = colluvium_thickness(np.tan(np.radians([0.0, 20.0, 45.0, 70.0])))
    assert z[0] > z[1] > z[2]                                          # monotone thinning
    assert abs(z[0] - 2.0) < 1e-9 and abs(z[2] - 0.3) < 1e-9           # flat=z_max, >=cap=z_min
    assert abs(z[3] - z[2]) < 1e-9                                     # holds at z_min beyond the cap


def test_nan_inputs_propagate():
    t = np.array([0.5, np.nan, 0.5])
    ss = infinite_slope_factor_of_safety(t, wt_depth_m=2.0, soil_depth_m=1.0)
    assert np.isnan(ss.fs[1]) and np.isnan(ss.p_failure[1])
    assert np.all(np.isfinite(ss.fs[[0, 2]]))


def test_estimate_mechanics_uses_the_seasonal_high_table():
    # A time-varying DTW is reduced to the shallow-tail (wet high) before FS -- the worst case.
    ny, nx, nt = 2, 3, 12
    slope = np.full((ny, nx), np.tan(np.radians(35.0)))
    dtw_t = np.linspace(0.2, 4.0, nt)[:, None, None] * np.ones((nt, ny, nx))   # seasonal swing
    ss = estimate_mechanics(MechanicsInputs(slope_tan=slope, water_table_depth=dtw_t,
                                            soil_depth_m=np.full((ny, nx), 1.5)))
    # FS should match the wet high (P10 DTW), not the mean DTW
    high_dtw = np.nanquantile(dtw_t, 0.1, axis=0)
    ref = infinite_slope_factor_of_safety(slope, high_dtw, soil_depth_m=np.full((ny, nx), 1.5))
    assert np.allclose(ss.fs, ref.fs, equal_nan=True)
    assert ss.fs.shape == (ny, nx)


if __name__ == "__main__":
    test_dry_cohesionless_reduces_to_tanphi_over_tanslope()
    test_rising_water_table_lowers_fs()
    test_steeper_slope_lowers_fs()
    test_root_cohesion_raises_fs_and_can_prevent_failure()
    test_failure_probability_is_bounded_and_tracks_fs()
    test_colluvium_thinner_on_steep_slopes()
    test_nan_inputs_propagate()
    test_estimate_mechanics_uses_the_seasonal_high_table()
    print("all soil-mechanics tests passed")
