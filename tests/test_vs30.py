"""Tests for the Wald-Allen Vs30 slope proxy (issue #54).

Runs standalone (`python -m tests.test_vs30`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.data.fetch_vs30 import wald_allen_vs30


def test_monotone_and_nehrp_range():
    slopes = np.array([0.0, 1.0, 3.0, 8.0, 20.0])
    vs = wald_allen_vs30(slopes)
    assert np.all(np.diff(vs) >= 0)                 # steeper terrain -> stiffer (non-decreasing)
    assert vs[0] == 180.0                            # flat valley fill -> NEHRP E
    assert vs[-1] == 760.0                           # steep -> NEHRP B/C boundary
    assert np.all((vs >= 180.0) & (vs <= 760.0))     # spans the standard NEHRP Vs30 range


def test_bins_map_to_expected_classes():
    # a gentle 1 deg slope (gradient ~0.017) sits in the 300-360 range, not 180 and not 760
    v = float(wald_allen_vs30(np.array([1.0]))[0])
    assert 240.0 <= v <= 360.0


def test_nan_slope_gives_nan():
    vs = wald_allen_vs30(np.array([np.nan, 5.0]))
    assert np.isnan(vs[0]) and np.isfinite(vs[1])


if __name__ == "__main__":
    test_monotone_and_nehrp_range()
    test_bins_map_to_expected_classes()
    test_nan_slope_gives_nan()
    print("all Vs30 tests passed")
