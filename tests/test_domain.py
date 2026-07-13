"""Tests for the frozen analysis domain (issue #92).

Runs standalone (`python -m tests.test_domain`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.config.domain import (
    DOMAIN,
    LEGACY_DOMAIN,
    PUGET_CASCADES_BBOX,
    assert_on_grid,
    which_grid,
)


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def test_domain_grid_is_frozen_and_self_consistent():
    rows, cols = DOMAIN.shape()
    x0, y0, x1, y1 = DOMAIN.bounds()
    assert cols == round((x1 - x0) / DOMAIN.res_m)
    assert rows == round((y1 - y0) / DOMAIN.res_m)
    assert DOMAIN.n_cells() == rows * cols
    assert 2.5e6 < DOMAIN.n_cells() < 3.5e6          # ~3 M cells; a big jump means the bbox drifted
    # the template must BE the domain grid, or reproject_match aligns to the wrong thing
    t = DOMAIN.template()
    assert tuple(t.shape) == (rows, cols)
    assert which_grid(t) == DOMAIN.name


def test_domain_is_defined_in_the_analysis_crs_not_latlon():
    # Albers is conic: a lat/lon rectangle maps to a curved quadrilateral, so defining the domain in
    # lat/lon and projecting INFLATES it (3.0 -> 5.1 M cells) and fails to round-trip the real grid.
    # The legacy domain must reproduce the actual raster shape exactly (835 x 1105).
    assert LEGACY_DOMAIN.shape() == (1105, 835)
    # and the lat/lon bbox must be a SUPERSET of the projected grid (we fetch extra, then clip)
    w, s, e, n = DOMAIN.bbox_4326
    assert w < -122.9 and e > -120.7 and s < 46.6 and n > 48.2


def test_legacy_products_are_refused_not_silently_mixed():
    # A misaligned overlay produces a plausible-looking WRONG answer rather than an error, so the
    # check is hard. Legacy rasters (0.92 M cells) must not be usable on the extended grid.
    class _Fake:
        shape = LEGACY_DOMAIN.shape()

        class rio:
            @staticmethod
            def bounds():
                return LEGACY_DOMAIN.bounds()

    assert which_grid(_Fake()) == LEGACY_DOMAIN.name
    assert _raises(lambda: assert_on_grid(_Fake()))
    assert assert_on_grid(DOMAIN.template()) is not None


def test_the_domain_contains_the_gauged_basins():
    # The whole reason the domain was extended: the OLD footprint contained exactly ONE gauged basin,
    # and it was a lowland creek -- while interflow is most active on steep ground. This pins the
    # property, not the polygons: the domain must be big enough to hold the Cascade headwaters.
    x0, y0, x1, y1 = DOMAIN.bounds()
    ox0, oy0, ox1, oy1 = LEGACY_DOMAIN.bounds()
    assert x0 < ox0 and y0 < oy0 and x1 > ox1 and y1 > oy1     # strict superset of the legacy grid
    assert (x1 - x0) > 130_000 and (y1 - y0) > 160_000          # >=130 x 160 km, per the basin union


def test_single_source_of_truth():
    assert PUGET_CASCADES_BBOX == DOMAIN.bbox_4326
    assert np.all(np.isfinite(DOMAIN.bounds()))


if __name__ == "__main__":
    test_domain_grid_is_frozen_and_self_consistent()
    test_domain_is_defined_in_the_analysis_crs_not_latlon()
    test_legacy_products_are_refused_not_silently_mixed()
    test_the_domain_contains_the_gauged_basins()
    test_single_source_of_truth()
    print("all domain tests passed")
