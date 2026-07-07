"""Tests for the well hydrostratigraphic screen (issue #46).

Runs standalone (`python -m tests.test_well_hydrostratigraphy`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.well_hydrostratigraphy import (
    classify_well_hydro,
    screening_summary,
    watertable_wells,
)


def _wells():
    # shallow water-table (5, 20 m), ambiguous (45 m), deep-confined (80 m, and a 500ft-flagged one)
    return pd.DataFrame({
        "well_depth_m": [5.0, 20.0, 45.0, 80.0, 200.0, np.nan],
        "is_deep_well": [False, False, False, False, True, False],
        "median_dtw_m": [4.0, 6.0, 20.0, 35.0, 40.0, 8.0],
    })


def test_classify_separates_shallow_from_confined():
    cls = classify_well_hydro(_wells(), shallow_max_m=30.0, deep_min_m=60.0)
    assert list(cls) == ["shallow_watertable", "shallow_watertable", "ambiguous",
                         "deep_confined", "deep_confined", "ambiguous"]


def test_watertable_screen_drops_deep_and_flagged():
    wt = watertable_wells(_wells(), max_depth_m=30.0)
    # keeps the two shallow (<=30) + the unknown-depth well; drops 45/80/200(is_deep)
    assert set(wt.well_depth_m.fillna(-1)) == {5.0, 20.0, -1.0}
    assert len(wt) == 3


def test_screen_reduces_dtw_mixing():
    s = screening_summary(_wells(), shallow_max_m=30.0, deep_min_m=60.0)
    # the shallow water-table population has a shallower median DTW than the deep-confined one
    assert s["shallow_watertable"]["median_dtw_m"] < s["deep_confined"]["median_dtw_m"]
    assert s["shallow_watertable"]["n"] == 2 and s["deep_confined"]["n"] == 2


if __name__ == "__main__":
    test_classify_separates_shallow_from_confined()
    test_watertable_screen_drops_deep_and_flagged()
    test_screen_reduces_dtw_mixing()
    print("all well-hydrostratigraphy tests passed")
