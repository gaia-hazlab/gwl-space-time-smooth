"""Landlab consumer causality (review ladder C1, issue #300). Skips visibly without landlab."""
from __future__ import annotations

import importlib
import tempfile

import numpy as np
import pytest
import xarray as xr

pytest.importorskip("landlab", reason="landlab is not in the twin's environment; see docs/reviews/2026-11-07-fable-soil-state-review/results/c1_landlab_causal.json")

from src.io import landlab_export as le  # noqa: E402


def _grid(values):
    ny, nx = values.shape
    da = xr.DataArray(values, dims=("y", "x"),
                      coords={"y": 90.0 * np.arange(ny)[::-1], "x": 90.0 * np.arange(nx)})
    return da.rio.write_crs("EPSG:5070")


def _manifest():
    fields = [le.DynamicField("water_table__depth", _grid(np.full((5, 6), 3.0)), epoch="seasonal_high"),
              le.DynamicField("saturation_fraction", _grid(np.full((5, 6), 0.6)), epoch="mean"),
              le.DynamicField("recharge", _grid(np.full((5, 6), 1.2)), epoch="mean")]
    with tempfile.TemporaryDirectory() as d:
        return le.export_dynamic_bundle(fields, d, write_cog=False)


def test_manifest_consumer_resolves_to_the_executed_component():
    from landlab.components import LandslideProbability
    module, _, name = _manifest()["consumer"].rpartition(".")
    assert getattr(importlib.import_module(module), name) is LandslideProbability


def test_component_does_not_consume_the_exported_fields():
    module, _, name = _manifest()["consumer"].rpartition(".")
    consumer = getattr(importlib.import_module(module), name)
    exported = {e["canonical_name"] for e in _manifest()["fields"]}
    assert exported == {"water_table__depth", "soil_moisture__saturation_fraction", "soil_water__recharge_rate"}
    assert exported.isdisjoint(consumer.input_var_names)
