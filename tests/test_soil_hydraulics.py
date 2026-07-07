"""Tests for the modular K_sat / transmissivity registry (LandLab-coupling consistency).

Runs standalone (`python -m tests.test_soil_hydraulics`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.models import soil_hydraulics as sh


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def test_saxton_rawls_ksat_units_and_texture_ordering():
    # sandy soil drains faster than clayey soil; output is a positive m/day value
    k_sand = sh.saturated_conductivity("saxton_rawls", sand_pct=85.0, clay_pct=5.0)
    k_clay = sh.saturated_conductivity("saxton_rawls", sand_pct=15.0, clay_pct=55.0)
    assert np.all(k_sand > 0) and np.all(k_clay > 0)
    assert float(k_sand) > float(k_clay)                    # sand K_sat > clay K_sat
    # m/day is O(0.01-100) for real soils; not the raw mm/hr (which would be ~24x larger)
    assert 1e-3 < float(k_sand) < 1e3


def test_solus_pedotransfer_matches_landslide_dataprep_formula():
    # exact reproduction of gaia-hazlab/landslide-data-prep compute_ksat for one pixel
    ph, clay, silt, cec = 6.0, 20.0, 40.0, 15.0
    got = sh.saturated_conductivity("solus_pedotransfer", ph=ph, clay_pct=clay,
                                    silt_pct=silt, cec=cec)
    expect = 10 ** (0.40220 + 0.26122 * ph + 0.44565
                    - 0.02329 * clay - 0.01265 * silt - 0.01038 * cec)
    assert np.isclose(float(got), expect)
    # unit_scale multiplies through (the documented unit-conversion hook)
    scaled = sh.saturated_conductivity("solus_pedotransfer", ph=ph, clay_pct=clay,
                                       silt_pct=silt, cec=cec, unit_scale=0.24)
    assert np.isclose(float(scaled), expect * 0.24)


def test_provided_passthrough_and_method_validation():
    field = np.array([0.5, 1.0, 2.0])
    out = sh.saturated_conductivity("provided", ksat_field=field)
    assert np.allclose(out, field)
    assert _raises(lambda: sh.saturated_conductivity("provided"))          # missing field
    assert _raises(lambda: sh.saturated_conductivity("saxton_rawls", sand_pct=50.0))  # missing clay
    assert _raises(lambda: sh.saturated_conductivity("nope", sand_pct=1, clay_pct=1))  # unknown


def test_transmissivity_methods_and_relations():
    ksat = np.array([1.0, 2.0])          # m/day
    h = np.array([2.0, 0.5])             # m
    t_plain = sh.transmissivity(ksat, h, "ksat_x_thickness")
    t_aniso = sh.transmissivity(ksat, h, "ksat_x_thickness_anisotropy", anisotropy=2.5)
    t_topmodel = sh.transmissivity(ksat, h, "topmodel_exponential", decay_depth_m=3.0)
    assert np.allclose(t_plain, ksat * h)                   # T = K·h  [m^2/day]
    assert np.allclose(t_aniso, ksat * h * 2.5)             # anisotropy scales it
    assert np.allclose(t_topmodel, ksat * 3.0)              # profile transmissivity K·d
    assert _raises(lambda: sh.transmissivity(ksat, h, "bogus"))


def test_soil_hydraulic_properties_bundles_ksat_and_transmissivity():
    props = sh.soil_hydraulic_properties(
        "saxton_rawls", sand_pct=40.0, clay_pct=20.0, thickness_m=1.5,
        transmissivity_method="ksat_x_thickness_anisotropy", anisotropy=2.5)
    assert "ksat" in props and "transmissivity" in props
    assert props["ksat_method"] == "saxton_rawls"
    assert np.allclose(props["transmissivity"], props["ksat"] * 1.5 * 2.5)
    # without thickness, only K_sat comes back (no transmissivity)
    only_k = sh.soil_hydraulic_properties("saxton_rawls", sand_pct=40.0, clay_pct=20.0)
    assert "transmissivity" not in only_k


if __name__ == "__main__":
    test_saxton_rawls_ksat_units_and_texture_ordering()
    test_solus_pedotransfer_matches_landslide_dataprep_formula()
    test_provided_passthrough_and_method_validation()
    test_transmissivity_methods_and_relations()
    test_soil_hydraulic_properties_bundles_ksat_and_transmissivity()
    print("all soil-hydraulics tests passed")
