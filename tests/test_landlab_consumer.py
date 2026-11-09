"""Landlab consumer causality (review ladder C1, issue #300). Skips visibly without landlab."""
from __future__ import annotations

import numpy as np
import pytest

landlab = pytest.importorskip("landlab", reason="landlab is not in the twin's environment; see docs/reviews/2026-11-07-fable-soil-state-review/results/c1_landlab_causal.json")


def test_component_does_not_consume_the_exported_fields():
    from landlab.components import LandslideProbability
    for f in ("water_table__depth", "soil_moisture__saturation_fraction", "soil_water__recharge_rate"):
        assert f not in LandslideProbability.input_var_names
