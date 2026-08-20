"""Tests for the well hydrostratigraphic screen (issue #46).

Runs standalone (`python -m tests.test_well_hydrostratigraphy`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.well_hydrostratigraphy import (
    MEASUREMENT_TARGETS,
    classify_well_hydro,
    measurement_target,
    measurement_target_summary,
    screening_summary,
    water_table_observations,
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


# --- observation semantics: what does the water level actually constrain? (issue #189) ------------

def _annotated_wells():
    """A well set exercising every evidence path of ``measurement_target``."""
    return pd.DataFrame({
        "site_no": ["shallow", "screened_shallow", "screened_deep", "confined_code",
                    "flowing", "deep", "greyband", "nometa"],
        "well_depth_m": [10.0, 40.0, 40.0, 12.0, 15.0, 150.0, 45.0, np.nan],
        "screen_top_m":  [np.nan, 6.0, 80.0, np.nan, np.nan, np.nan, np.nan, np.nan],
        "screen_bottom_m": [np.nan, 12.0, 95.0, np.nan, np.nan, np.nan, np.nan, np.nan],
        "aqfr_type_cd": [None, None, None, "C", "U", None, None, None],
        # note the "U" on the flowing well: unconfined-coded AND flowing is precisely the ambiguous
        # case (a surfacing water table vs a locally confined lens), so it must land on "unknown"
        "is_flowing": [False, False, False, False, True, False, False, False],
        "is_deep_well": [False, False, False, False, False, True, False, False],
        "median_dtw_m": [3.0, 4.0, 25.0, 2.0, -1.0, 60.0, 15.0, 5.0],
    })


def test_measurement_target_uses_the_most_direct_evidence_available():
    t = measurement_target(_annotated_wells()).tolist()
    assert t == [
        "water_table",     # shallow well, no contrary evidence
        "water_table",     # 40 m well but the SCREEN tops out at 6 m -> brackets the phreatic surface
        "aquifer_head",    # 40 m well but the screen is at 80-95 m -> a deeper interval
        "aquifer_head",    # shallow, but NWIS says the unit is confined -- the code overrules depth
        "unknown",         # flowing, but shallow with no confining evidence: NOT a water table,
                           # and we cannot honestly call it an aquifer head either
        "aquifer_head",    # deep well / is_deep_well flag
        "unknown",         # 45 m: in the grey band between the shallow and deep thresholds
        "unknown",         # no depth, no screen, no aquifer code -- flagged, never assumed
    ]
    assert set(t) <= set(MEASUREMENT_TARGETS)


def test_flowing_disqualifies_water_table_and_only_asserts_aquifer_head_when_corroborated():
    sites = pd.DataFrame({
        "well_depth_m": [10.0, 10.0, 150.0, 10.0],
        "aqfr_type_cd": [None, "C", None, None],
        "is_flowing": [True, True, True, False],
    })
    assert measurement_target(sites).tolist() == [
        "unknown",          # flowing, shallow, uncorroborated -> honest "we don't know"
        "aquifer_head",     # flowing + confined code -> artesian confined interval
        "aquifer_head",     # flowing + deep -> artesian confined interval
        "water_table",      # not flowing -> the shallow-depth evidence stands
    ]


def test_a_shallow_well_in_a_confined_unit_is_not_promoted_to_water_table():
    # depth alone would call this a water-table well; the aquifer-type code must win, because a
    # shallow screen in a confined unit still measures a potentiometric head.
    sites = pd.DataFrame({"well_depth_m": [12.0], "aqfr_type_cd": ["C"]})
    assert measurement_target(sites).iloc[0] == "aquifer_head"
    assert classify_well_hydro(sites).iloc[0] == "shallow_watertable"   # the OLD, depth-only view


def test_unknown_wells_are_excluded_from_the_water_table_screen_unless_opted_in():
    w = _annotated_wells()
    strict = water_table_observations(w)
    assert set(strict.site_no) == {"shallow", "screened_shallow"}
    assert set(strict.measurement_target) == {"water_table"}
    lenient = water_table_observations(w, include_unknown=True)
    assert set(lenient.site_no) == {"shallow", "screened_shallow", "greyband", "nometa", "flowing"}
    # the conservative screen is strictly tighter than the legacy depth-only one, which keeps
    # unknown-depth wells by default
    assert len(strict) < len(watertable_wells(w))


def test_measurement_target_summary_accounts_for_every_well():
    s = measurement_target_summary(_annotated_wells())
    assert s["n_total"] == 8
    assert s["water_table"]["n"] + s["aquifer_head"]["n"] + s["unknown"]["n"] == 8
    # the aquifer-head population sits deeper, which is the whole reason not to pool them
    assert s["aquifer_head"]["median_dtw_m"] > s["water_table"]["median_dtw_m"]


def test_measurement_target_handles_a_frame_with_no_metadata_columns_at_all():
    bare = pd.DataFrame({"site_no": ["a", "b"]})
    assert measurement_target(bare).tolist() == ["unknown", "unknown"]
    assert len(water_table_observations(bare)) == 0
    assert measurement_target(pd.DataFrame()).empty


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
    print("all well-hydrostratigraphy tests passed")
