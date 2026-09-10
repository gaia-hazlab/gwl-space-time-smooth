"""Tests for the NISAR SME2 soil-moisture fetcher (network-free).

Exercises the pure logic that guards and shapes the download — the temporal guard (NISAR does
not exist before 2025-10-01), the bbox→WKT footprint, introspective HDF5 variable resolution, and
the scatter→grid binning — without touching ASF/Earthdata. Runs standalone
(`python -m tests.test_fetch_nisar`); also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.data.fetch_nisar import (
    NISAR_SME2_START,
    bbox_to_wkt,
    bin_to_grid,
    find_var,
    guard_temporal_window,
    make_target_grid,
)

BBOX = (-122.95, 47.05, -121.55, 48.15)


def test_temporal_guard_clamps_and_rejects():
    # A window straddling launch clamps the start up to the mission start month.
    s, e = guard_temporal_window("2020-01", "2026-03")
    assert s == NISAR_SME2_START.to_period("M")   # clamped, not 2020-01
    assert str(e) == "2026-03"
    # A window entirely before launch is a hard error, never a silent empty product.
    with pytest.raises(SystemExit):
        guard_temporal_window("2018-01", "2019-12")
    # A window already after launch is untouched.
    s2, _ = guard_temporal_window("2025-11", "2026-01")
    assert str(s2) == "2025-11"


def test_bbox_to_wkt_is_closed_polygon_with_corners():
    wkt = bbox_to_wkt(BBOX)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    coords = wkt[len("POLYGON(("):-2].split(",")
    assert len(coords) == 5                        # closed ring: 4 corners + repeat
    assert coords[0] == coords[-1]                 # first == last
    w, s, e, n = BBOX
    assert coords[0] == f"{w} {s}" and f"{e} {n}" in coords


def test_make_target_grid_covers_bbox_at_resolution():
    lon_c, lat_c = make_target_grid(BBOX, res=0.01)
    w, s, e, n = BBOX
    assert w < lon_c[0] < lon_c[-1] < e            # cell centres strictly inside the bbox
    assert s < lat_c[0] < lat_c[-1] < n
    assert np.allclose(np.diff(lon_c), 0.01) and np.allclose(np.diff(lat_c), 0.01)


def test_find_var_locates_soil_moisture_in_hdf5(tmp_path):
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "granule.h5"
    with h5py.File(path, "w") as f:
        grp = f.create_group("science/LSAR/SME2/grids")
        grp.create_dataset("soil_moisture", data=np.zeros((3, 3)))
        grp.create_dataset("latitude", data=np.zeros(3))
        grp.create_dataset("longitude", data=np.zeros(3))
        grp.create_dataset("quality_flag", data=np.zeros((3, 3)))   # decoy
        with h5py.File(path, "r") as r:
            assert find_var(r, (r"soil.?moisture",)).endswith("soil_moisture")
            assert find_var(r, (r"latitude",)).endswith("latitude")
            assert find_var(r, (r"nonexistent_var",)) is None


def test_bin_to_grid_averages_and_masks():
    lon_c, lat_c = make_target_grid(BBOX, res=0.5)   # coarse → cells easy to reason about
    # Two points in the same cell average; one off-grid and one NaN are dropped.
    lat = np.array([lat_c[0], lat_c[0], lat_c[0], 90.0])
    lon = np.array([lon_c[0], lon_c[0], lon_c[-1], lon_c[0]])
    vals = np.array([0.20, 0.40, np.nan, 0.99])
    grid = bin_to_grid(lat, lon, vals, lon_c, lat_c)
    assert grid.shape == (lat_c.size, lon_c.size)
    assert np.isclose(grid[0, 0], 0.30)              # (0.20 + 0.40) / 2
    assert np.isnan(grid[0, -1])                     # only the NaN point fell here → empty
    assert np.isfinite(grid).sum() == 1              # off-grid (lat=90) point discarded


if __name__ == "__main__":
    test_temporal_guard_clamps_and_rejects()
    test_bbox_to_wkt_is_closed_polygon_with_corners()
    test_make_target_grid_covers_bbox_at_resolution()
    test_bin_to_grid_averages_and_masks()
    print("all NISAR fetcher tests passed (find_var needs pytest for the h5py fixture)")
