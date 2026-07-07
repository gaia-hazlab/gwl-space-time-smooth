"""Tests for the dynamic LandLab export (saturation fraction, seasonal-high WTD, .asc + manifest).

Runs standalone (`python -m tests.test_landlab_export`); also pytest-discoverable. Parses the ESRI
ASCII header directly so it does not depend on landlab being installed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

from src.io import landlab_export as le


def _grid(nx=6, ny=5, res=90.0, values=None):
    """A small EPSG:5070 DataArray with descending y (north-up), like our rasters."""
    x = 0.0 + res * np.arange(nx)
    y = 0.0 + res * np.arange(ny)[::-1]
    if values is None:
        values = np.arange(ny * nx, dtype="float64").reshape(ny, nx)
    da = xr.DataArray(values, dims=("y", "x"), coords={"y": y, "x": x})
    return da.rio.write_crs("EPSG:5070")


def test_saturation_fraction_ratio_and_clip():
    theta = np.array([0.1, 0.3, 0.5, 0.6])
    n = np.array([0.4, 0.4, 0.4, 0.4])
    s = le.saturation_fraction(theta, n)
    assert np.isclose(s[0], 0.25) and np.isclose(s[1], 0.75)
    assert s[3] == 1.0                                   # theta>n clips to fully saturated
    # zero porosity -> nan (no divide-by-zero blow-up)
    assert np.isnan(le.saturation_fraction([0.2], [0.0])[0])


def test_seasonal_high_is_the_shallow_tail_of_dtw():
    # depth-to-water positive-down; a wet season with small DTW should drive the high table
    t = 20
    dtw = np.linspace(2.0, 8.0, t)[:, None, None] * np.ones((t, 2, 2))
    high = le.seasonal_high_water_table(dtw, quantile=0.1)
    assert high.shape == (2, 2)
    assert np.all(high < np.mean(dtw, axis=0))           # high table shallower than the mean
    assert np.all(high >= dtw.min())                     # within range


def test_write_ascii_has_valid_esri_header_and_nodata():
    da = _grid()
    with tempfile.TemporaryDirectory() as d:
        p = le.write_landlab_ascii(da, Path(d) / "field.asc", nodata=-9999.0)
        head = {}
        with open(p) as fh:
            for _ in range(6):
                k, v = fh.readline().split()
                head[k.lower()] = float(v)
        assert int(head["ncols"]) == da.sizes["x"]
        assert int(head["nrows"]) == da.sizes["y"]
        assert head["nodata_value"] == -9999.0
        assert np.isclose(head["cellsize"], 90.0)


def test_align_to_grid_matches_template_shape():
    src = _grid(nx=6, ny=5, res=90.0)
    tmpl = _grid(nx=12, ny=10, res=45.0)                 # finer target grid
    out = le.align_to_grid(src, tmpl)
    assert out.sizes["x"] == 12 and out.sizes["y"] == 10


def test_apply_confidence_mask_blanks_unsupported_cells():
    da = _grid(values=np.full((5, 6), 3.0))
    mask = _grid(values=np.ones((5, 6)))
    mask.values[0, :] = 0.0                               # top row unsupported
    out = le.apply_confidence_mask(da, mask)
    assert np.all(np.isnan(out.values[0, :]))            # masked row -> nan (no-data)
    assert np.all(out.values[1:, :] == 3.0)              # supported cells untouched


def test_sigma_sidecar_is_written_and_recorded():
    da = _grid(values=np.full((5, 6), 2.0))
    sig = _grid(values=np.full((5, 6), 0.3))
    with tempfile.TemporaryDirectory() as d:
        manifest = le.export_dynamic_bundle(
            [le.DynamicField("water_table__depth", da, epoch="mean", sigma=sig)], d, write_cog=False)
        entry = manifest["fields"][0]
        assert entry["std_asc"] is not None
        assert (Path(d) / entry["std_asc"]).exists()     # the _std sidecar exists on disk


def test_export_bundle_writes_canonical_files_and_manifest():
    wtd = _grid(values=np.full((5, 6), 3.0))
    theta = _grid(values=np.full((5, 6), 0.25))
    n = _grid(values=np.full((5, 6), 0.5))
    sat = theta.copy(data=le.saturation_fraction(theta.values, n.values))
    rech = _grid(values=np.full((5, 6), 1.2))
    fields = [
        le.DynamicField("water_table__depth", wtd, epoch="seasonal_high"),
        le.DynamicField("saturation_fraction", sat, epoch="mean"),
        le.DynamicField("recharge", rech, epoch="mean"),
    ]
    with tempfile.TemporaryDirectory() as d:
        manifest = le.export_dynamic_bundle(fields, d, write_cog=False)
        names = {e["canonical_name"] for e in manifest["fields"]}
        assert names == {"water_table__depth", "soil_moisture__saturation_fraction",
                         "soil_water__recharge_rate"}
        # every declared .asc actually exists on disk, plus the manifest
        for e in manifest["fields"]:
            assert (Path(d) / e["asc"]).exists()
        assert (Path(d) / "landlab_export_manifest.json").exists()
        reloaded = json.loads((Path(d) / "landlab_export_manifest.json").read_text())
        assert reloaded["consumer"].endswith("LandslideProbability")
        # unknown key is rejected
        try:
            le.export_dynamic_bundle([le.DynamicField("bogus", wtd)], d)
            raise AssertionError("expected ValueError for unknown field key")
        except ValueError:
            pass


if __name__ == "__main__":
    test_saturation_fraction_ratio_and_clip()
    test_seasonal_high_is_the_shallow_tail_of_dtw()
    test_write_ascii_has_valid_esri_header_and_nodata()
    test_align_to_grid_matches_template_shape()
    test_apply_confidence_mask_blanks_unsupported_cells()
    test_sigma_sidecar_is_written_and_recorded()
    test_export_bundle_writes_canonical_files_and_manifest()
    print("all landlab-export tests passed")
