#!/usr/bin/env python3
"""C1 (#300): does landlab.components.LandslideProbability use anything the twin exports?

Run with a Python that has landlab installed (a scratch venv; the twin's pixi env is unchanged).
Positive control: failure probability must respond to groundwater__recharge_mean. Causal test:
scaling the exported fields water_table__depth, soil_moisture__saturation_fraction and
soil_water__recharge_rate must leave the outputs bit-identical. Writes results/c1_landlab_causal.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "results" / "c1_landlab_causal.json"


def make_grid():
    from landlab import RasterModelGrid
    g = RasterModelGrid((5, 5), xy_spacing=90.0)
    n = g.number_of_nodes
    g.add_field("topographic__slope", np.full(n, 0.6), at="node")                          # tan(31 deg)
    g.add_field("topographic__specific_contributing_area", np.full(n, 300.0), at="node")
    g.add_field("soil__transmissivity", np.full(n, 20.0), at="node")                     # m2/day
    g.add_field("soil__saturated_hydraulic_conductivity", np.full(n, 10.0), at="node")
    g.add_field("soil__mode_total_cohesion", np.full(n, 8000.0), at="node")
    g.add_field("soil__minimum_total_cohesion", np.full(n, 6000.0), at="node")
    g.add_field("soil__maximum_total_cohesion", np.full(n, 10000.0), at="node")
    g.add_field("soil__internal_friction_angle", np.full(n, 32.0), at="node")
    g.add_field("soil__density", np.full(n, 1800.0), at="node")
    g.add_field("soil__thickness", np.full(n, 1.5), at="node")
    return g


def run(g, recharge_mean, seed=0):
    from landlab.components import LandslideProbability
    ls = LandslideProbability(g, number_of_iterations=400, groundwater__recharge_distribution="lognormal",
                              groundwater__recharge_mean=recharge_mean, groundwater__recharge_standard_deviation=0.25 * recharge_mean, seed=seed)
    ls.calculate_landslide_probability()
    return {k: g.at_node[k].copy() for k in ("landslide__probability_of_failure", "soil__probability_of_saturation", "soil__mean_relative_wetness")}


def main():
    import landlab
    from landlab.components import LandslideProbability
    rec = {"issue": "gaia-hazlab/gwl-space-time-smooth#300", "landlab_version": landlab.__version__, "python": sys.version.split()[0],
           "input_var_names": sorted(LandslideProbability.input_var_names), "output_var_names": sorted(LandslideProbability.output_var_names)}
    exported = ("water_table__depth", "soil_moisture__saturation_fraction", "soil_water__recharge_rate")
    rec["exported_fields_among_inputs"] = [f for f in exported if f in LandslideProbability.input_var_names]
    # positive control: recognised input
    pos = []
    for rm in (20.0, 60.0, 120.0, 240.0):
        out = run(make_grid(), rm, seed=0)
        pos.append({"recharge_mean_mm_day": rm, "p_fail_core_mean": float(out["landslide__probability_of_failure"][6:19].mean()),
                    "mean_rel_wetness": float(out["soil__mean_relative_wetness"][6:19].mean())})
    rec["positive_control"] = pos
    rec["positive_control_monotone"] = bool(np.all(np.diff([p["p_fail_core_mean"] for p in pos]) >= 0)) and pos[-1]["p_fail_core_mean"] > pos[0]["p_fail_core_mean"]
    # causal test: exported fields present and scaled, same seed
    base = make_grid()
    for f, val in zip(exported, (2.0, 0.6, 3.0)):
        base.add_field(f, np.full(base.number_of_nodes, val), at="node")
    ref = run(base, 60.0, seed=0)
    diffs = {}
    for scale in (0.5, 2.0):
        g = make_grid()
        for f, val in zip(exported, (2.0, 0.6, 3.0)):
            g.add_field(f, np.full(g.number_of_nodes, val * scale), at="node")
        out = run(g, 60.0, seed=0)
        diffs[f"scale_{scale}"] = {k: float(np.max(np.abs(out[k] - ref[k]))) for k in ref}
    rec["causal_test_max_abs_difference"] = diffs
    rec["outputs_invariant_to_exported_fields"] = all(v == 0.0 for d in diffs.values() for v in d.values())
    rec["layers"] = {"file_readability": "landlab_export writes ESRI ASCII + manifest; parsed by tests/test_landlab_export.py",
                     "executable_api_coupling": "component instantiated here; consumes recharge distribution, T or Ksat, slope, area, cohesion, density, thickness, friction angle",
                     "scientific_validation": "none here; needs an inventory (#224, #129)"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("landlab_version", "exported_fields_among_inputs", "positive_control", "positive_control_monotone", "causal_test_max_abs_difference", "outputs_invariant_to_exported_fields")}, indent=1))


if __name__ == "__main__":
    main()
